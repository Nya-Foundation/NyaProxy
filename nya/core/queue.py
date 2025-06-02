"""
Simple priority queue for handling requests with built-in retry priority.
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional, Tuple

from loguru import logger

from ..common.exceptions import (
    EncounterRetryStatusCodeError,
    NoAvailableAPIKeyError,
    NyaProxyError,
    QueueFullError,
    ReachedMaxRetriesError,
    RequestExpiredError,
    RequestRateLimited,
)
from ..common.models import ProxyRequest

if TYPE_CHECKING:
    from starlette.responses import Response

    from ..config import ConfigManager
    from ..services.control import TrafficManager
    from ..services.metrics import MetricsCollector


class RequestQueue:
    """
    Simple priority queue that processes requests using worker pools.
    """

    def __init__(
        self,
        config: "ConfigManager",
        traffic_manager: "TrafficManager",
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """
        Initialize the simple queue.
        """
        self.config = config
        self.control = traffic_manager
        self.metrics_collector = metrics_collector

        # Priority queues for each API
        self._queues: Dict[str, asyncio.PriorityQueue] = {}

        # Worker semaphores to limit concurrency
        self._workers: Dict[str, asyncio.Semaphore] = {}

        # Processing tasks
        self._processors: Dict[str, asyncio.Task] = {}

        # Registered processor
        self._processor: Optional[Callable[[ProxyRequest], Awaitable[Response]]] = None

    async def enqueue_request(
        self, request: ProxyRequest, is_retry: bool = False, priority: int = None
    ) -> asyncio.Future:
        """
        Enqueue a request for processing.
        """
        api_name = request.api_name

        if is_retry:
            priority = priority or 1
        else:
            priority = request.priority

        # Initialize queue and workers if needed
        await self._ensure_api_initialized(api_name)

        # Check queue size
        if self._queues[api_name].qsize() >= self.config.get_api_queue_size(api_name):
            raise QueueFullError(f"Queue full for {api_name}")

        # Create future and attach to request
        future = asyncio.Future()
        request.future = future
        request.added_at = time.time()

        # Add to queue
        await self._queues[api_name].put(request)

        logger.debug(
            f"Enqueued {'retry' if is_retry else 'request'} for {api_name}, "
            f"priority={priority}, queue_size={self._queues[api_name].qsize()}"
        )

        if self.metrics_collector:
            self.metrics_collector.record_queue_hit(api_name)

        return future

    async def _ensure_api_initialized(self, api_name: str) -> None:
        """Ensure API queue and workers are initialized."""
        if api_name not in self._queues:
            # Use queue max size as a reasonable concurrency limit
            max_concurrent = min(self.config.get_api_queue_size(api_name) // 2, 10)

            self._queues[api_name] = asyncio.PriorityQueue()
            self._workers[api_name] = asyncio.Semaphore(max_concurrent)

            # Start processor for this API
            self._processors[api_name] = asyncio.create_task(
                self._process_api_queue(api_name)
            )

    async def _process_api_queue(self, api_name: str) -> None:
        """Process requests for a specific API using worker pool."""
        if not self._processor:
            logger.warning(f"No processor registered for {api_name}")
            return

        logger.debug(f"Starting queue processor for {api_name}")

        while True:
            try:
                # Get next request (blocks until available)
                request = await self._queues[api_name].get()

                # Check if request expired
                if self._is_request_expired(request):
                    request.future.set_exception(
                        RequestExpiredError(api_name, time.time() - request.added_at)
                    )
                    continue

                # Process with worker semaphore
                asyncio.create_task(self._process_with_worker(api_name, request))

            except Exception as e:
                logger.error(f"Error in queue processor for {api_name}: {e}")
                await asyncio.sleep(1)

    async def _process_with_worker(self, api_name: str, request: ProxyRequest) -> None:
        """Process a single request with worker pool limiting."""
        async with self._workers[api_name]:
            try:
                # Check resource availability
                available, wait_time = await self._wait_for_resources(api_name, request)
                if not available:
                    if self.metrics_collector:
                        self.metrics_collector.record_rate_limit_hit(api_name)

                    await self._handle_retry(
                        request, RequestRateLimited(api_name, wait_time)
                    )
                    return

                # Acquire key
                key, _ = await self.control.acquire_key(api_name)
                if not key:
                    await self._handle_retry(request, NoAvailableAPIKeyError(api_name))
                    return

                request.api_key = key
                request.attempts += 1

                # Record usage
                self.control.record_ip_request(api_name, request.ip)
                self.control.record_endpoint_request(api_name)

                # Process the request
                response = await self._processor(request)

                self.release_resources(request, response.status_code)

                # If status code requires retry, handle it
                if await self._handle_user_defined_retry(request, response.status_code):
                    return

                if not request.future.done():
                    request.future.set_result(response)

            except Exception as e:
                if not request.future.done():
                    request.future.set_exception(e)

    def release_resources(self, request: ProxyRequest, status_code: int) -> None:
        """
        Release resources after processing a request.
        """
        if status_code < 400:
            return

        api_name = request.api_name
        self.control.release_ip(api_name, request.ip)
        self.control.release_endpoint(api_name)

        if self.config.get_api_key_concurrency(api_name):
            self.control.release_key(api_name, request.api_key)

        logger.debug(
            f"Released resources for {api_name} after status code {status_code}"
        )

    async def _handle_user_defined_retry(
        self, request: ProxyRequest, status_code: int
    ) -> bool:
        """
        Handle user-defined retry logic.
        """
        api_name = request.api_name
        retry_enabled = self.config.get_api_retry_enabled(api_name)

        if not retry_enabled:
            return False

        retry_status_codes = self.config.get_api_retry_status_codes(api_name)
        if status_code not in retry_status_codes:
            return False

        await self._handle_retry(
            request,
            EncounterRetryStatusCodeError(api_name, status_code),
        )

        return True

    async def _wait_for_resources(
        self, api_name: str, request: ProxyRequest
    ) -> Tuple[bool, float]:
        """Wait for resources to become available."""
        max_wait = self.config.get_api_default_timeout(api_name)
        start_time = time.time()

        while time.time() - start_time < max_wait:
            # Check endpoint availability
            endpoint_wait = self.control.time_to_endpoint_ready(api_name)
            if endpoint_wait > 0:
                await asyncio.sleep(min(endpoint_wait, 1.0))
                continue

            # Check key availability
            key_wait = self.control.time_to_key_ready(api_name)
            if key_wait > 0:
                await asyncio.sleep(min(key_wait, 1.0))
                continue

            # Check IP rate limit
            ip_rate_limit = self.config.get_api_ip_rate_limit(api_name)
            ip_wait = self.control.time_to_ip_ready(api_name, request.ip, ip_rate_limit)
            if ip_wait > 0:
                await asyncio.sleep(min(ip_wait, 1.0))
                continue

            return True, 0.0  # Resources available

        return False, max_wait

    async def _handle_retry(self, request: ProxyRequest, error: NyaProxyError) -> None:
        """Handle retry logic for any type of failure."""
        api_name = request.api_name
        max_retries = self.config.get_api_retry_attempts(api_name)
        retry_delay = self.config.get_api_retry_after_seconds(api_name)

        if request.future.done():
            return

        if not isinstance(error, NoAvailableAPIKeyError):
            self.control.block_key(api_name, request.api_key, retry_delay)

        if request.attempts < max_retries:
            logger.debug(
                f"[Retry] for {api_name} due to: [Reason]: {error.message}, [Attempt]: {request.attempts}/{max_retries}"
            )
            # Schedule retry with delay by creating a delayed task
            asyncio.create_task(self._delayed_retry(request, retry_delay))
        else:
            # Max retries reached, fail the request
            request.future.set_exception(ReachedMaxRetriesError(api_name, max_retries))

    async def _delayed_retry(self, request: ProxyRequest, delay: float) -> None:
        """Schedule a delayed retry by waiting and then re-enqueuing with high priority."""
        await asyncio.sleep(delay)

        # Check if request is still valid
        if request.future.done():
            return

        # Re-enqueue with high priority (1 = retry priority)
        request.priority = 1
        api_name = request.api_name

        await self._queues[api_name].put(request)

    def _is_request_expired(self, request: ProxyRequest) -> bool:
        """Check if request has expired."""
        api_name = request.api_name
        expiry_seconds = self.config.get_api_queue_expiry(api_name)
        return time.time() - request.added_at > expiry_seconds

    def get_queue_size(self, api_name: str) -> int:
        """Get current queue size for an API."""
        if api_name in self._queues:
            return self._queues[api_name].qsize()
        return 0

    async def get_estimated_wait_time(self, api_name: str) -> float:
        """Get estimated wait time for new requests."""
        queue_size = self.get_queue_size(api_name)
        if queue_size == 0:
            return 0.0
        return queue_size * 1.0

    async def clear_queue(self, api_name: str) -> int:
        """Clear queue for an API."""
        count = 0
        if api_name in self._queues:
            queue = self._queues[api_name]

            # Cancel all pending requests
            while not queue.empty():
                try:
                    request = queue.get_nowait()
                    if not request.future.done():
                        request.future.set_exception(
                            RuntimeError(
                                f"Request cancelled: queue cleared for {api_name}"
                            )
                        )
                    count += 1
                except asyncio.QueueEmpty:
                    break

            # Cancel processor
            if api_name in self._processors:
                self._processors[api_name].cancel()
                del self._processors[api_name]

            logger.info(f"Cleared queue for {api_name}: {count} requests cancelled")

        return count

    def get_all_queue_sizes(self) -> Dict[str, int]:
        """Get queue sizes for all APIs."""
        return {api_name: queue.qsize() for api_name, queue in self._queues.items()}

    def register_processor(
        self, processor: Callable[[ProxyRequest], Awaitable[Any]]
    ) -> None:
        """Register the request processor."""
        self._processor = processor
        logger.debug("Queue processor registered")
