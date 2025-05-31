"""
Request queue for managing rate-limited requests.
"""

import asyncio
import heapq
import logging
import time
import traceback
import uuid
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    TypeVar,
)

from loguru import logger

from ..common.exceptions import (
    APIKeyExhaustedError,
    QueueFullError,
    RequestExpiredError,
)
from ..common.models import ProxyRequest
from ..utils.helper import format_elapsed_time

if TYPE_CHECKING:
    from .key import KeyManager

# Type for the future response
T = TypeVar("T")


class RequestQueue:
    """
    Queue for storing and processing rate-limited requests.

    Implements a priority queue system that allows requests to be queued when
    rate limits are hit, and processed later when capacity is available.
    Each API has its own isolated queue with configurable size and expiry.
    """

    def __init__(
        self,
        key_manager: "KeyManager",
        max_size: int = 100,
        expiry_seconds: int = 300,
        start_task: bool = True,  # New parameter to control background task
    ):
        """
        Initialize the request queue.

        Args:
            key_manager: KeyManager instance for managing API keys
            max_size: Maximum queue size per API
            expiry_seconds: Default expiry time for queued requests in seconds
            start_task: Whether to start the background processing task
        """
        self.max_size = max_size
        self.default_expiry = expiry_seconds
        self.key_manager = key_manager

        # Use a priority queue (min heap) for each API
        # Each queue entry is a tuple of api_name: List[(scheduled_time, request_id, ProxyRequest)]
        self.queues: Dict[str, List[Tuple[float, str, ProxyRequest]]] = {}

        # Track queue sizes for quick access
        self.sizes: Dict[str, int] = {}

        # Lock to protect queue operations
        self.lock = asyncio.Lock()

        # Request processor callback
        self.processor: Optional[Callable[[ProxyRequest], Awaitable[Any]]] = None

        # Metrics for monitoring
        self.metrics = {
            "total_enqueued": 0,
            "total_processed": 0,
            "total_expired": 0,
            "total_failed": 0,
        }

        # Start processing task
        self.running = True
        self.processing_task = None
        self._background_tasks = set()
        if start_task:
            self.processing_task = asyncio.create_task(self._process_queue_task())
            self._background_tasks.add(self.processing_task)
            self.processing_task.add_done_callback(self._background_tasks.discard)

    def register_processor(
        self, processor: Callable[[ProxyRequest], Awaitable[Any]]
    ) -> None:
        """
        Register a callback function to process queued requests.

        Args:
            processor: Async callback function that processes a request
        """
        self.processor = processor
        logger.debug("Request processor registered")

    async def enqueue_request(
        self,
        r: ProxyRequest,
        reset_in_seconds: Optional[int] = None,
    ) -> asyncio.Future:
        """
        Add a request to the queue and return a future that will resolve with the response.

        Args:
            r: ProxyRequest object to enqueue
            reset_in_seconds: Optional time in seconds after which the rate limit will be reset

        Returns:
            Future that will be resolved with the response when processed

        Raises:
            QueueFullError: If the queue for this API is full
        """
        async with self.lock:
            # Initialize queue for this API if it doesn't exist
            self._ensure_queue_exists(r.api_name)

            # Check if queue is full
            if self.sizes[r.api_name] >= self.max_size:
                logger.warning(
                    f"Queue for {r.api_name} is full ({self.sizes[r.api_name]}/{self.max_size})"
                )
                raise QueueFullError(r.api_name, self.max_size)

            # Create a future for this request's response
            response_future: asyncio.Future = asyncio.Future()

            # Generate a unique request ID for heap ordering
            request_id = str(uuid.uuid4())

            # Calculate scheduled time (when this request should be processed)
            scheduled_time = time.time() + (
                reset_in_seconds
                if reset_in_seconds is not None
                else self.default_expiry
            )

            # Update request with queue metadata
            r._added_at = time.time()
            r._attempts = 0
            r._expiry = scheduled_time
            r._future = response_future

            # Add to priority queue (min heap based on scheduled time)
            heapq.heappush(self.queues[r.api_name], (scheduled_time, request_id, r))
            self.sizes[r.api_name] += 1
            self.metrics["total_enqueued"] += 1

            logger.info(
                f"Request enqueued due to rate limit for {r.api_name}, queue size: {self.get_queue_size(r.api_name)}, "
                f"scheduled in {format_elapsed_time(scheduled_time - time.time())}"
            )

            return response_future

    def _ensure_queue_exists(self, api_name: str) -> None:
        """
        Ensure that a queue exists for the specified API.

        Args:
            api_name: Name of the API
        """
        if api_name not in self.queues:
            self.queues[api_name] = []
            self.sizes[api_name] = 0

    async def get_estimated_wait_time(self, api_name: str) -> float:
        """
        Get the estimated wait time by checking the last scheduled request in the queue.

        Args:
            api_name: Name of the API

        Returns:
            Estimated wait time in seconds, or 0 if no requests are queued
        """
        if api_name not in self.queues or not self.queues[api_name]:
            return 0.0

        # Get the last scheduled request's time
        scheduled_time, _, _ = self.queues[api_name][-1]
        current_time = time.time()
        wait_time = scheduled_time - current_time

        next_key_rese = await self.key_manager.get_key_rate_limit_reset(api_name)
        return max(next_key_rese, wait_time)

    def get_queue_size(self, api_name: str) -> int:
        """
        Get the current queue size for an API.

        Args:
            api_name: Name of the API

        Returns:
            Current queue size
        """
        return self.sizes.get(api_name, 0)

    def get_all_queue_sizes(self) -> Dict[str, int]:
        """
        Get the current queue sizes for all APIs.

        Returns:
            Dictionary with API names as keys and queue sizes as values
        """
        return self.sizes.copy()

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get queue metrics.

        Returns:
            Dictionary with queue metrics
        """
        return {
            **self.metrics,
            "current_queue_sizes": self.get_all_queue_sizes(),
        }

    async def _process_queue_task(self) -> None:
        """Background task for processing queued requests."""
        try:
            while self.running:
                try:
                    # Process queues for all APIs that have available keys
                    await self._process_all_queues()
                    await asyncio.sleep(0.1)  # Check queues every second
                except Exception as e:
                    logger.error(f"Error in queue processing task: {str(e)}")
                    logger.debug(f"Traceback: {traceback.format_exc()}")

                    await asyncio.sleep(2.0)  # Backoff if there are errors
        except asyncio.CancelledError:
            # Handle cancellation gracefully when the queue is stopped
            logger.debug("Queue processing task cancelled")
            return

    async def _process_all_queues(self) -> None:
        """Process all queues for all APIs that have available keys."""
        current_time = time.time()

        # Process each API queue only if it has available keys
        for api_name in list(self.queues.keys()):
            # Skip processing this API's queue if it has no requests
            if not self.queues[api_name]:
                continue

            # Check if this specific API has available keys
            if await self._ready_to_process(api_name):
                await self._process_api_queue(api_name, current_time)
            else:
                break

    async def _ready_to_process(self, api_name: str) -> bool:
        """
        Check if the queue for a specific API is ready to process requests.

        Args:
            api_name: Name of the API

        Returns:
            True if the queue is ready to process, False otherwise
        """
        endpoint_cleared = await self.key_manager.is_api_available(api_name)
        has_available_keys = await self.key_manager.has_available_keys(api_name)

        return endpoint_cleared and has_available_keys and self.queues.get(api_name, [])

    async def _process_api_queue(self, api_name: str, current_time: float) -> None:
        """
        Process the queue for a specific API.

        Args:
            api_name: Name of the API to process
            current_time: Current timestamp
        """
        async with self.lock:
            # Check if the next request is ready to be processed (scheduled_time <= current_time)
            while self.queues[api_name] and self.queues[api_name][0][0] <= current_time:
                # Check if we still have available keys for this API before processing each request
                # This prevents processing multiple requests when only one key is available
                if not await self._ready_to_process(api_name):
                    break

                # Try to get a key BEFORE popping from queue
                try:
                    available_key = await self.key_manager.get_available_key(api_name)
                except APIKeyExhaustedError:
                    # No keys available, exit loop
                    break

                # Pop the next request
                _, _, request = heapq.heappop(self.queues[api_name])
                self.sizes[request.api_name] -= 1

                # Check if the request is expired
                waited_time = current_time - request._added_at
                if waited_time > self.default_expiry:
                    # Handle expired request
                    await self._handle_expired_request(request, waited_time)
                    continue

                # assign an API key to the request
                request.api_key = available_key
                # Process the request outside the lock using a task to avoid blocking
                # This creates a new task but doesn't wait for it to complete
                asyncio.create_task(self._process_request_item(request))

    async def _handle_expired_request(
        self, request: ProxyRequest, wait_time: float
    ) -> None:
        """
        Handle an expired request by completing its future with an error.

        Args:
            request: The expired request
            wait_time: How long the request has been waiting
        """
        logger.warning(
            f"Request in queue for {request.api_name} expired after waiting {format_elapsed_time(wait_time)}"
        )
        self.metrics["total_expired"] += 1
        self._fail_request(request, RequestExpiredError(request.api_name, wait_time))

    async def _process_request_item(self, request: ProxyRequest) -> None:
        """
        Process a single request item from the queue.

        Args:
            request: ProxyRequest object with request details
        """
        if not self.processor:
            logger.error("No request processor registered")
            self._fail_request(request, RuntimeError("No request processor registered"))
            return

        api_name = request.api_name
        try:
            response = await self.processor(request)

            # Ensure the future is properly set with the result
            if hasattr(request, "_future") and not request._future.done():
                request._future.set_result(response)
            else:
                logger.warning(
                    f"Future for request to {api_name} was already done when setting result"
                )

            # Successfully processed
            self.metrics["total_processed"] += 1
            logger.debug(f"Successfully processed queued request for {api_name}")
        except Exception as e:
            logger.error(f"Error processing queued request for {api_name}: {str(e)}")
            self._fail_request(request, e)
            raise

    def _fail_request(self, request: ProxyRequest, error: Exception) -> None:
        """
        Fail a request by setting an exception on its future.

        Args:
            request: The request to fail
            error: The error to set
        """
        if hasattr(request, "_future") and not request._future.done():
            request._future.set_exception(error)

        self.metrics["total_failed"] += 1

    async def clear_queue(self, api_name: str) -> int:
        """
        Clear the queue for a specific API.

        Args:
            api_name: Name of the API

        Returns:
            Number of requests cleared
        """
        if api_name not in self.queues:
            return 0

        async with self.lock:
            queue_size = self.sizes.get(api_name, 0)

            # Fail all pending requests
            failed_count = 0
            while self.queues[api_name]:
                _, _, request = heapq.heappop(self.queues[api_name])
                if hasattr(request, "_future") and not request._future.done():
                    request._future.set_exception(
                        RuntimeError(f"Request was cleared from {api_name} queue")
                    )
                    failed_count += 1

            # Reset queue
            self.queues[api_name] = []
            self.sizes[api_name] = 0

            self.metrics["total_failed"] += failed_count
            logger.info(f"Cleared {failed_count} requests from queue for {api_name}")

            return failed_count

    async def clear_all_queues(self) -> int:
        """
        Clear all queues for all APIs.

        Returns:
            Total number of requests cleared
        """
        total_cleared = 0

        for api_name in list(self.queues.keys()):
            api_cleared = await self.clear_queue(api_name)
            total_cleared += api_cleared

        logger.info(f"Cleared all queues, total of {total_cleared} requests removed")

        return total_cleared

    async def stop(self) -> None:
        """Stop the queue processing task and clean up."""
        self.running = False
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass

        # Cancel all pending futures
        async with self.lock:
            for api_name in self.queues:
                for _, _, request in self.queues[api_name]:
                    if hasattr(request, "_future") and not request._future.done():
                        request._future.cancel()
