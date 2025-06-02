"""
Simple priority queue for handling requests with built-in retry priority.
"""

import asyncio
import random
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Tuple

from loguru import logger

from ..common.exceptions import (
    EncounterRetryStatusCodeError,
    QueueFullError,
    ReachedMaxRetriesError,
)
from ..common.models import ProxyRequest

if TYPE_CHECKING:
    from ..config import ConfigManager
    from ..services.control import TrafficManager
    from ..services.metrics import MetricsCollector


class RequestQueue:
    """
    Simple priority queue that processes requests when keys become available.
    """

    def __init__(
        self,
        config: "ConfigManager",
        traffic_manager: "TrafficManager",
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """Initialize the simple queue."""

        self.config = config
        self.control = traffic_manager
        self.max_size = config.get_queue_size()
        self.expiry_seconds = config.get_queue_expiry()
        self.metrics_collector = metrics_collector

        # Queues for each API
        self._queues: Dict[str, List[ProxyRequest]] = {}
        # Registered processor for handling requests
        self._processor: Optional[Callable[[ProxyRequest], Awaitable[Any]]] = None
        self._lock = asyncio.Lock()
        self._processing_tasks: Dict[str, asyncio.Task] = {}

    async def enqueue_request(
        self, request: ProxyRequest, is_retry: bool = False, priority: int = None
    ) -> asyncio.Future:
        """Enqueue a request for processing."""
        api_name = request.api_name

        request.attempts += 1

        if is_retry:
            request.is_retry = True
            request.priority = priority or 1

        async with self._lock:
            # Initialize queue if needed
            if api_name not in self._queues:
                self._queues[api_name] = []

            # Check if queue is full
            if len(self._queues[api_name]) >= self.max_size:
                raise QueueFullError(f"Queue full for {api_name}")

            # Create queued request
            request.future = asyncio.Future()

            # Add to queue in priority order
            self._queues[api_name].append(request)
            self._queues[api_name].sort()  # Simple sort by priority

            logger.debug(
                f"Enqueued {'retry' if is_retry else 'request'} for {api_name}, "
                f"priority={priority}, queue_size={len(self._queues[api_name])}"
            )

        if self.metrics_collector:
            self.metrics_collector.record_queue_hit(api_name)

        # Start processing if not already running
        await self._ensure_processing(api_name)
        return request.future

    async def _ensure_processing(self, api_name: str) -> None:
        """Ensure processing task is running for an API."""
        if (
            api_name not in self._processing_tasks
            or self._processing_tasks[api_name].done()
        ):
            self._processing_tasks[api_name] = asyncio.create_task(
                self._process_queue(api_name)
            )

    async def _process_queue(self, api_name: str) -> None:
        """Process requests in the queue for an API."""
        logger.debug(f"Starting queue processor for {api_name}")

        while True:
            try:
                queued_req, wait_time = await self._get_next_request(api_name)
                # If no request can be processed and wait
                if not queued_req:
                    if self.metrics_collector:
                        self.metrics_collector.record_rate_limit_hit(api_name)
                    await asyncio.sleep(wait_time)
                    continue

                # Process the request
                if self._processor:
                    try:
                        result = await self._processor(queued_req)
                        if not queued_req.future.done():
                            queued_req.future.set_result(result)
                    except Exception as e:
                        await self._handle_processor_exception(queued_req, e)
                else:
                    if not queued_req.future.done():
                        queued_req.future.set_exception(
                            RuntimeError("No request processor registered")
                        )

            except Exception as e:
                logger.error(f"Error in queue processor for {api_name}: {e}")
                raise

    async def _handle_processor_exception(
        self, request: ProxyRequest, exception: Exception
    ) -> None:
        """Handle exceptions from the request processor, including retry logic."""

        if isinstance(exception, EncounterRetryStatusCodeError):
            max_retries = self.config.get_api_retry_attempts(request.api_name)
            retry_delay = self.config.get_api_retry_after_seconds(
                request.api_name
            ) + random.uniform(0, 0.6)

            self.control.mark_key_exhausted(
                request.api_name, request.api_key, retry_delay
            )

            logger.debug(
                f"Processing retry logic: for {request.api_name}, attempts={request.attempts}, max_retries={max_retries}"
            )

            if request.attempts < max_retries:
                asyncio.create_task(self._schedule_retry(request, retry_delay))
            else:
                target_future = getattr(request, "_original_future", request.future)
                if not target_future.done():
                    target_future.set_exception(
                        ReachedMaxRetriesError(request.api_name, request.attempts)
                    )
        else:
            # Non-retryable exception
            if not request.future.done():
                request.future.set_exception(exception)

    async def _schedule_retry(
        self, original_request: ProxyRequest, retry_delay: float
    ) -> None:
        """Schedule a retry without blocking the queue processor."""
        # Preserve the original future to send results back to client
        original_future = original_request.future

        # Store the original future on the request so we can access it later
        if not hasattr(original_request, "_original_future"):
            original_request._original_future = original_future

        async def delayed_retry():
            await asyncio.sleep(retry_delay)

            # Create new future for the retry
            retry_future = asyncio.Future()
            original_request.future = retry_future

            # Re-enqueue as retry with higher priority
            await self.enqueue_request(original_request, is_retry=True, priority=1)

            # Forward the retry result to the original future
            def forward_result(future):
                if not original_future.done():
                    if future.exception():
                        original_future.set_exception(future.exception())
                    else:
                        original_future.set_result(future.result())

            retry_future.add_done_callback(forward_result)

        # Start the delayed retry as a background task
        asyncio.create_task(delayed_retry())

    async def _get_next_request(
        self, api_name: str
    ) -> Tuple[Optional[ProxyRequest], float]:
        """Get next processable request from queue."""
        async with self._lock:
            if api_name not in self._queues or not self._queues[api_name]:
                return None, 1

            # Clean expired requests
            current_time = time.time()
            self._queues[api_name] = [
                req
                for req in self._queues[api_name]
                if current_time - req.added_at < self.expiry_seconds
            ]

            # Check if we have available keys for this API
            key, wait_time = await self.control.is_endpoint_ready(api_name)
            if not key:
                return None, wait_time

            # Get highest priority request
            if self._queues[api_name]:
                next_req = self._queues[api_name].pop(0)
                next_req.api_key = key
                return next_req, 0

        return None, 1

    def get_queue_size(self, api_name: str) -> int:
        """Get current queue size for an API."""
        return len(self._queues.get(api_name, []))

    async def get_estimated_wait_time(self, api_name: str) -> float:
        """Get estimated wait time for new requests."""
        queue_size = self.get_queue_size(api_name)
        if queue_size == 0:
            return 0.0

        # Simple estimation: 1 second per queued request
        return queue_size * 1.0

    async def clear_queue(self, api_name: str) -> int:
        """Clear queue for an API and stop its processing task."""
        async with self._lock:
            count = 0
            if api_name in self._queues:
                count = len(self._queues[api_name])

                # Cancel all pending futures with meaningful error
                for req in self._queues[api_name]:
                    if not req.future.done():
                        req.future.set_exception(
                            RuntimeError(
                                f"Request cancelled: queue cleared for {api_name}"
                            )
                        )

                # Clear the queue
                self._queues[api_name] = []

                # Stop the processing task for this API
                if api_name in self._processing_tasks:
                    task = self._processing_tasks[api_name]
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass  # Expected when cancelling
                    del self._processing_tasks[api_name]

                logger.info(f"Cleared queue for {api_name}: {count} requests cancelled")

            return count

    def get_all_queue_sizes(self) -> Dict[str, int]:
        """
        Get the current queue sizes for all APIs.

        Returns:
            Dictionary with API names as keys and queue sizes as values
        """
        return {api_name: len(queue) for api_name, queue in self._queues.items()}

    def register_processor(
        self, processor: Callable[[ProxyRequest], Awaitable[Any]]
    ) -> None:
        """Register the request processor."""
        self._processor = processor
        logger.debug("Queue processor registered")
