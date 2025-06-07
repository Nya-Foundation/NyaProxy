"""
Simple priority queue for handling requests with built-in retry priority.
"""

import asyncio
import random
import time
import traceback
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional, Tuple

from loguru import logger

from ..common.exceptions import (
    QueueFullError,
    ReachedDailyQuotaError,
    ReachedMaxRetriesError,
    RequestExpiredError,
)
from ..common.models import ProxyRequest

if TYPE_CHECKING:
    from starlette.responses import Response

    from ..config import ConfigManager
    from ..services.metrics import MetricsCollector
    from .control import TrafficManager


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
        self.config = config or ConfigManager.get_instance()
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
        await self._setup_endpoint_processor(api_name)

        # Check queue size
        if self._queues[api_name].qsize() >= self.config.get_api_queue_size(api_name):
            raise QueueFullError(f"Queue full for {api_name}")

        # Create future and attach to request
        future = asyncio.Future()
        request.future = future

        # Add to queue
        await self._queues[api_name].put(request)

        logger.debug(
            f"Enqueued {'retry' if is_retry else 'request'} for {api_name}, "
            f"priority={priority}, queue_size={self._queues[api_name].qsize()}"
        )

        if self.metrics_collector:
            self.metrics_collector.record_queue_hit(api_name)

        return future

    async def _setup_endpoint_processor(self, api_name: str) -> None:
        """
        Ensure API queue and workers are initialized.
        """
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
        """
        Process requests for a specific API using worker pool.
        """
        if not self._processor:
            logger.warning(f"No processor registered for {api_name}")
            return

        while True:
            try:
                key, wait_time = await self._check_for_resource_limit(api_name)
                if wait_time > 0 or key is None:
                    await asyncio.sleep(wait_time / 2)
                    continue

                # Get next request (blocks until available)
                request: ProxyRequest = await self._queues[api_name].get()
                request.api_key = key

                # Check if request expired
                if self._is_request_expired(request):
                    request.future.set_exception(
                        RequestExpiredError(api_name, time.time() - request.added_at)
                    )
                    continue

                # Process with worker semaphore
                asyncio.create_task(self._process_with_worker(api_name, request))

            except Exception as e:
                logger.error(
                    f"Error in queue processor for {api_name}: {e}, traceback: {traceback.format_exc()}    "
                )
                await asyncio.sleep(1)

    async def _process_with_worker(self, api_name: str, request: ProxyRequest) -> None:
        """
        Process a single request with worker pool limiting.
        """
        async with self._workers[api_name]:
            try:
                # Check resource availability
                wait_time = await self._handle_proxy_limit(api_name, request)
                if wait_time > 0:
                    return

                request.attempts += 1
                self.control.record_ip_request(api_name, request.ip)
                self.control.record_user_request(api_name, request.user)

                # Process the request
                response = await self._processor(request)

                # unlock the key after processing
                self.control.unlock_key(request.api_name, request.api_key)
                self._free_resources_on_failure(request, response.status_code)

                # If status code requires retry, handle it
                if await self._handle_user_defined_retry(request, response.status_code):
                    return

                if not request.future.done():
                    request.future.set_result(response)

            except Exception as e:
                # unlock the key if processing failed to avoid deadlocks
                self.control.unlock_key(request.api_name, request.api_key)

                if not request.future.done():
                    request.future.set_exception(e)

    def _free_resources_on_failure(
        self, request: ProxyRequest, status_code: int
    ) -> None:
        """
        Release resources if request is failed.
        """
        if status_code < 400:
            return

        api_name = request.api_name

        self.control.release_ip(api_name, request.ip)
        self.control.release_user(api_name, request.user)
        self.control.release_endpoint(api_name)
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

        # check whether retry is enabled for this API
        retry_enabled = self.config.get_api_retry_enabled(api_name)

        if not retry_enabled:
            return False

        # check if request method is in retry list
        retry_methods = self.config.get_api_retry_request_methods(api_name)
        if request.method not in retry_methods:
            return False

        # check if response status code is in retry list
        retry_status_codes = self.config.get_api_retry_status_codes(api_name)
        if status_code not in retry_status_codes:
            return False

        retry_delay = self.config.get_api_retry_after_seconds(api_name)
        self.control.block_key(api_name, request.api_key, retry_delay)

        logger.debug(
            f"[Rate Limit] Marked key {request.api_key}... as exhausted for {retry_delay}s"
        )

        await self._handle_retry(request, retry_delay)
        return True

    async def _handle_proxy_limit(self, api_name: str, request: ProxyRequest):
        """
        Wait for proxy resources to become available before processing.
        """
        # Check IP and user rate limit
        ip_wait = self.control.time_to_ip_ready(api_name, request.ip)
        user_wait = self.control.time_to_user_ready(api_name, request.user)
        logger.debug(
            f"IP wait: {ip_wait:.2f}s, User wait: {user_wait:.2f}s for {api_name} (IP: {request.ip}, User: {request.user})"
        )
        total_wait = max(ip_wait, user_wait)

        if total_wait == 0:
            return 0.0  # resources available

        # free the current key if user/ip rate limit is hit
        self.control.release_key(api_name, request.api_key)
        self.control.release_endpoint(api_name)

        # reset key for retry
        request.api_key = None

        if total_wait > self.config.get_api_queue_expiry(api_name):
            request.future.set_exception(ReachedDailyQuotaError(api_name, total_wait))
            return total_wait

        await self._handle_retry(request, total_wait)

        return total_wait

    async def _check_for_resource_limit(
        self, api_name: str
    ) -> Tuple[Optional[str], float]:
        """
        Wait for resources to become available before processing the request.
        """
        # Check endpoint availability
        endpoint_wait = self.control.time_to_endpoint_ready(api_name)
        if endpoint_wait > 0:
            return None, endpoint_wait  # Endpoint not ready

        # Check key availability
        key, key_wait = await self.control.acquire_key(api_name)
        if key_wait > 0:
            return None, key_wait  # Key not available

        return key, 0.0  # Resources available

    async def _handle_retry(self, request: ProxyRequest, retry_delay: float) -> None:
        """
        Handle retry logic for any type of failure.
        """
        api_name = request.api_name
        max_retries = self.config.get_api_retry_attempts(api_name)
        retry_delay = max(
            retry_delay, self.config.get_api_retry_after_seconds(api_name)
        )

        if request.future.done():
            return

        if request.attempts < max_retries:
            logger.debug(
                f"[Retry] for {api_name} after {retry_delay}s, [Attempt]: {request.attempts}/{max_retries}"
            )
            await asyncio.sleep(random.uniform(0.8 * retry_delay, 1.6 * retry_delay))

            # Re-enqueue with high priority (1 = retry priority)
            request.priority = 1
            await self._queues[request.api_name].put(request)
        else:
            # Max retries reached, fail the request
            request.future.set_exception(ReachedMaxRetriesError(api_name, max_retries))

    def _is_request_expired(self, request: ProxyRequest) -> bool:
        """
        Check if request has expired.
        """
        expiry_seconds = self.config.get_api_queue_expiry(request.api_name)
        return time.time() - request.added_at > expiry_seconds

    def get_queue_size(self, api_name: str) -> int:
        """
        Get current queue size for an API.
        """
        if api_name in self._queues:
            return self._queues[api_name].qsize()
        return 0

    async def get_estimated_wait_time(self, api_name: str) -> float:
        """
        Get estimated wait time for new requests.
        """
        queue_size = self.get_queue_size(api_name)
        if queue_size == 0:
            return 0.0
        return queue_size * 1.0

    async def clear_queue(self, api_name: str) -> int:
        """
        Clear queue for an API.
        """
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
        """
        Get queue sizes for all APIs.
        """
        return {api_name: queue.qsize() for api_name, queue in self._queues.items()}

    def register_processor(
        self, processor: Callable[[ProxyRequest], Awaitable[Any]]
    ) -> None:
        """
        Register the request processor.
        """
        self._processor = processor
        logger.debug("Queue processor registered")
