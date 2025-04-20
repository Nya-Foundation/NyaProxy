"""
Request queue for managing rate-limited requests.
"""

import asyncio
import heapq
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from .models import NyaRequest


class RequestQueue:
    """
    Queue for storing and processing rate-limited requests.
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
        # Each queue entry is a tuple of (expiry_time, RequestData)
        self.queues: Dict[str, List[Tuple[float, NyaRequest]]] = {}

        # Track queue sizes
        self.sizes: Dict[str, int] = {}

        # Track request IDs to avoid duplicates
        self.request_ids: Set[str] = set()

        # Track response futures for waiting clients
        self.response_futures: Dict[str, asyncio.Future] = {}

        # Request processor callback
        self.processor: Optional[Callable[[NyaRequest], Awaitable[Any]]] = None

        # Counters for metrics
        self.total_enqueued = 0
        self.total_processed = 0
        self.total_expired = 0
        self.total_failed = 0

        # Start processing task
        self.running = True
        self.processing_task = asyncio.create_task(self._process_queue_task())

    def register_processor(self, processor: Callable[[NyaRequest], Awaitable[Any]]):
        """
        Register a callback function to process queued requests.

        Args:
            processor: Async callback function that processes a request
        """
        self.processor = processor

    async def enqueue_request(
        self,
        r: NyaRequest,
        reset_in_seconds: Optional[int] = None,
    ) -> asyncio.Future:
        """
        Add a request to the queue.

        Args:
            r: NyaRequest object to enqueue
            reset_in_seconds: Optional time in seconds after which the rate limit will be reset.

        Returns:
            Future that will be resolved with the response, or None if enqueueing failed
        """
        # Initialize queue for this API if it doesn't exist
        if r.api_name not in self.queues:
            self.queues[r.api_name] = []
            self.sizes[r.api_name] = 0

        # Check if queue is full
        if self.sizes[r.api_name] >= self.max_size:
            self.logger.warning(f"Queue for {r.api_name} is full, rejecting request")
            raise ValueError("Queue is full")

        # Generate unique request ID and check for duplicates
        request_id = f"{r.api_name}_{int(time.time())}_{hash(str(r.to_dict()))}"
        if request_id in self.request_ids:
            self.logger.warning(
                f"Duplicate request detected for {r.api_name}, not enqueueing"
            )
            raise ValueError("Duplicate request")

        # Create a future for this request's response
        response_future = asyncio.Future()
        self.response_futures[request_id] = response_future

        # Calculate expiry time
        expiry = time.time() + (
            reset_in_seconds if reset_in_seconds is not None else self.default_expiry
        )

        # Update RequestData with queue-specific information
        r.request_id = request_id
        r.expiry = expiry
        r.added_at = time.time()
        r.attempts = 0

        # Add to priority queue (min heap based on expiry time)
        heapq.heappush(self.queues[r.api_name], (expiry, r))
        self.sizes[r.api_name] += 1
        self.request_ids.add(request_id)
        self.total_enqueued += 1

        self.logger.info(
            f"Request enqueued for {r.api_name}, queue size: {self.sizes[r.api_name]}"
        )
        return response_future

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
            "total_enqueued": self.total_enqueued,
            "total_processed": self.total_processed,
            "total_expired": self.total_expired,
            "total_failed": self.total_failed,
            "current_queue_sizes": self.get_all_queue_sizes(),
        }

    async def _process_queue_task(self):
        """Background task for processing queued requests."""
        while self.running:
            try:
                await self._process_all_queues()
                await asyncio.sleep(1.0)  # Check queues every second
            except Exception as e:
                self.logger.error(f"Error in queue processing task: {str(e)}")
                await asyncio.sleep(5.0)  # Backoff if there are errors

    async def _process_all_queues(self):
        """Process all queues for all APIs."""
        current_time = time.time()

        # Process each API queue
        for api_name in list(self.queues.keys()):
            if not self.queues[api_name]:
                continue

            # Check if the next request is ready to be processed (expiry <= current_time)
            while self.queues[api_name] and self.queues[api_name][0][0] <= current_time:
                # Pop the next request
                _, request_data = heapq.heappop(self.queues[api_name])
                self.sizes[api_name] -= 1

                # Remove from request ID tracking
                if request_data.request_id in self.request_ids:
                    self.request_ids.remove(request_data.request_id)

                # Check if the request is expired
                if (current_time - request_data.added_at) > 2 * self.default_expiry:
                    self.logger.warning(
                        f"Request in queue for {api_name} expired after waiting too long"
                    )
                    self.total_expired += 1
                    continue

                # Process the request
                await self._process_request_item(request_data)

    async def _process_request_item(self, request_data: NyaRequest):
        """
        Process a single request item from the queue.

        Args:
            request_data: RequestData object with request details
        """
        if not self.processor:
            self.logger.error("No request processor registered")
            return

        api_name = request_data.api_name

        try:
            # Increment attempts counter
            request_data.attempts += 1
            max_attempts = 3  # Maximum number of retry attempts

            # Process the request
            self.logger.info(
                f"Processing queued request for {api_name} (attempt {request_data.attempts})"
            )
            response = await self.processor(request_data)

            # Get and complete the response future
            if request_data.request_id in self.response_futures:
                future = self.response_futures[request_data.request_id]
                if not future.done():
                    future.set_result(response)
                del self.response_futures[request_data.request_id]

            # Successfully processed
            self.total_processed += 1
            self.logger.info(f"Successfully processed queued request for {api_name}")

        except Exception as e:
            self.logger.warning(
                f"Error processing queued request for {api_name}: {str(e)}"
            )

            # If we haven't exceeded max attempts, requeue with a delay
            if request_data.attempts < max_attempts:
                # Re-add to the queue with a delay
                delay = 10 * (2 ** (request_data.attempts - 1))  # Exponential backoff
                new_expiry = time.time() + delay

                # Generate new request ID
                request_data.request_id = (
                    f"{api_name}_{int(time.time())}_{hash(str(request_data.to_dict()))}"
                )

                # Re-add to queue
                if api_name in self.queues:
                    heapq.heappush(self.queues[api_name], (new_expiry, request_data))
                    self.sizes[api_name] += 1
                    self.request_ids.add(request_data.request_id)
                    self.logger.info(
                        f"Requeued request for {api_name} with {delay}s delay (attempt {request_data.attempts})"
                    )
            else:
                self.logger.error(
                    f"Failed to process queued request for {api_name} after {max_attempts} attempts"
                )
                self.total_failed += 1

    def clear_queue(self, api_name: str) -> int:
        """
        Clear the queue for a specific API.

        Args:
            api_name: Name of the API

        Returns:
            Number of items cleared
        """
        if api_name not in self.queues:
            return 0

        cleared_count = self.sizes[api_name]

        # Remove all request IDs for this API
        for _, request_data in self.queues[api_name]:
            if request_data.request_id in self.request_ids:
                self.request_ids.remove(request_data.request_id)

        # Clear the queue
        self.queues[api_name] = []
        self.sizes[api_name] = 0

        self.logger.info(f"Cleared {cleared_count} items from queue for {api_name}")
        return cleared_count

    def clear_all_queues(self) -> int:
        """
        Clear all queues.

        Returns:
            Total number of items cleared
        """
        total_cleared = sum(self.sizes.values())

        # Clear all queues
        self.queues = {}
        self.sizes = {}
        self.request_ids = set()

        self.logger.info(f"Cleared all queues, total items: {total_cleared}")
        return total_cleared

    async def stop(self):
        """Stop the queue processing task and clean up."""
        self.running = False
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass

        # Clean up any pending futures
        for future in self.response_futures.values():
            if not future.done():
                future.cancel()
        self.response_futures.clear()
