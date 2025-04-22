"""
Request queue for managing rate-limited requests.
"""

import asyncio
import heapq
import logging
import time
import traceback
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar

from .exceptions import QueueFullError, RequestExpiredError
from .models import NyaRequest
from .utils import format_elapsed_time

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
        self, logger: logging.Logger, max_size: int = 100, expiry_seconds: int = 300
    ):
        """
        Initialize the request queue.

        Args:
            logger: Logger instance
            max_size: Maximum queue size per API
            expiry_seconds: Default expiry time for queued requests in seconds
        """
        self.logger = logger
        self.max_size = max_size
        self.default_expiry = expiry_seconds

        # Use a priority queue (min heap) for each API
        # Each queue entry is a tuple of (scheduled_time, request_id, NyaRequest)
        self.queues: Dict[str, List[Tuple[float, str, NyaRequest]]] = {}

        # Track queue sizes for quick access
        self.sizes: Dict[str, int] = {}

        # Lock to protect queue operations
        self.lock = asyncio.Lock()

        # Request processor callback
        self.processor: Optional[Callable[[NyaRequest], Awaitable[Any]]] = None

        # Metrics for monitoring
        self.metrics = {
            "total_enqueued": 0,
            "total_processed": 0,
            "total_expired": 0,
            "total_failed": 0,
        }

        # Start processing task
        self.running = True
        self.processing_task = asyncio.create_task(self._process_queue_task())

    def register_processor(
        self, processor: Callable[[NyaRequest], Awaitable[Any]]
    ) -> None:
        """
        Register a callback function to process queued requests.

        Args:
            processor: Async callback function that processes a request
        """
        self.processor = processor
        self.logger.debug("Request processor registered")

    async def enqueue_request(
        self,
        r: NyaRequest,
        reset_in_seconds: Optional[int] = None,
    ) -> asyncio.Future:
        """
        Add a request to the queue and return a future that will resolve with the response.

        Args:
            r: NyaRequest object to enqueue
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
                self.logger.warning(
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
            r.added_at = time.time()
            r.expiry = scheduled_time
            r.attempts = 0
            r.future = response_future

            # Add to priority queue (min heap based on scheduled time)
            heapq.heappush(self.queues[r.api_name], (scheduled_time, request_id, r))
            self.sizes[r.api_name] += 1
            self.metrics["total_enqueued"] += 1

            self.logger.info(
                f"Request enqueued for {r.api_name}, queue size: {self.get_queue_size(r.api_name)}, "
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

    def get_estimated_wait_time(self, api_name: str) -> float:
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
        return max(0.0, wait_time)

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
        while self.running:
            try:
                await self._process_all_queues()
                await asyncio.sleep(1.0)  # Check queues every second
            except Exception as e:
                self.logger.error(f"Error in queue processing task: {str(e)}")
                await asyncio.sleep(5.0)  # Backoff if there are errors

    async def _process_all_queues(self) -> None:
        """Process all queues for all APIs."""
        current_time = time.time()

        # Process each API queue
        for api_name in list(self.queues.keys()):
            await self._process_api_queue(api_name, current_time)

    async def _process_api_queue(self, api_name: str, current_time: float) -> None:
        """
        Process the queue for a specific API.

        Args:
            api_name: Name of the API to process
            current_time: Current timestamp
        """
        if not self.queues[api_name]:
            return

        async with self.lock:
            # Check if the next request is ready to be processed (scheduled_time <= current_time)
            while self.queues[api_name] and self.queues[api_name][0][0] <= current_time:
                # Pop the next request
                scheduled_time, _, request = heapq.heappop(self.queues[api_name])
                self.sizes[api_name] -= 1

                # Check if the request is expired
                wait_time = current_time - request.added_at
                if wait_time > self.default_expiry * 2:
                    # Handle expired request
                    await self._handle_expired_request(request, wait_time)
                    continue

                # Process the request outside the lock
                asyncio.create_task(self._process_request_item(request))

    async def _handle_expired_request(
        self, request: NyaRequest, wait_time: float
    ) -> None:
        """
        Handle an expired request by completing its future with an error.

        Args:
            request: The expired request
            wait_time: How long the request has been waiting
        """
        self.logger.warning(
            f"Request in queue for {request.api_name} expired after waiting {format_elapsed_time(wait_time)}"
        )
        self.metrics["total_expired"] += 1

        if hasattr(request, "future") and not request.future.done():
            request.future.set_exception(
                RequestExpiredError(request.api_name, wait_time)
            )

    async def _process_request_item(self, request: NyaRequest) -> None:
        """
        Process a single request item from the queue.

        Args:
            request: NyaRequest object with request details
        """
        if not self.processor:
            self.logger.error("No request processor registered")
            self._fail_request(request, RuntimeError("No request processor registered"))
            return

        api_name = request.api_name
        max_attempts = 3  # Maximum number of retry attempts

        try:
            # Increment attempts counter
            request.attempts += 1

            # Process the request
            self.logger.info(
                f"Processing queued request for {api_name} (attempt {request.attempts}/{max_attempts})"
            )
            response = await self.processor(request)

            # Set the result on the future
            if hasattr(request, "future") and not request.future.done():
                request.future.set_result(response)

            # Successfully processed
            self.metrics["total_processed"] += 1
            self.logger.info(f"Successfully processed queued request for {api_name}")

        except Exception as e:
            await self._handle_request_error(request, e, max_attempts)

    async def _handle_request_error(
        self, request: NyaRequest, error: Exception, max_attempts: int
    ) -> None:
        """
        Handle errors during request processing.

        Args:
            request: The request that failed
            error: The exception that occurred
            max_attempts: Maximum number of retry attempts
        """
        api_name = request.api_name
        self.logger.warning(
            f"Error processing queued request for {api_name}: {str(error)}, traceback: {traceback.format_exc()}"
        )

        # If we haven't exceeded max attempts, requeue with a delay
        if request.attempts < max_attempts:
            await self._requeue_request_with_backoff(request)
        else:
            # If we've exceeded max attempts, fail the request
            self.logger.error(
                f"Max retry attempts ({max_attempts}) reached for queued request to {api_name}"
            )
            self.metrics["total_failed"] += 1
            self._fail_request(request, error)

    def _fail_request(self, request: NyaRequest, error: Exception) -> None:
        """
        Fail a request by setting an exception on its future.

        Args:
            request: The request to fail
            error: The error to set
        """
        if hasattr(request, "future") and not request.future.done():
            request.future.set_exception(error)

    async def _requeue_request_with_backoff(self, request: NyaRequest) -> None:
        """
        Requeue a failed request with exponential backoff.

        Args:
            request: The request to requeue
        """
        # Calculate backoff delay based on attempt number (exponential with jitter)
        base_delay = 2.0
        attempt = request.attempts
        max_jitter = 0.25  # 25% jitter

        # Exponential backoff formula: base_delay * (2 ^ attempt) with jitter
        import random

        delay = base_delay * (2**attempt)
        jitter = random.uniform(-max_jitter * delay, max_jitter * delay)
        delay = max(0.1, delay + jitter)  # Ensure minimum delay of 0.1s

        self.logger.info(
            f"Requeueing request for {request.api_name} with {format_elapsed_time(delay)} delay "
            f"(attempt {request.attempts})"
        )

        # Set new scheduled time with backoff
        scheduled_time = time.time() + delay
        request.expiry = scheduled_time

        # Generate a new request ID
        request_id = str(uuid.uuid4())

        # Add to queue and update metrics
        async with self.lock:
            # Ensure queue exists (it might have been cleared)
            self._ensure_queue_exists(request.api_name)

            heapq.heappush(
                self.queues[request.api_name], (scheduled_time, request_id, request)
            )
            self.sizes[request.api_name] += 1

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
                if hasattr(request, "future") and not request.future.done():
                    request.future.set_exception(
                        RuntimeError(f"Request was cleared from {api_name} queue")
                    )
                    failed_count += 1

            # Reset queue
            self.queues[api_name] = []
            self.sizes[api_name] = 0

            self.metrics["total_failed"] += failed_count
            self.logger.info(
                f"Cleared {failed_count} requests from queue for {api_name}"
            )

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

        self.logger.info(
            f"Cleared all queues, total of {total_cleared} requests removed"
        )
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
                    if hasattr(request, "future") and not request.future.done():
                        request.future.cancel()
