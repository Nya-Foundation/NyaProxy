"""
Request queue for managing rate-limited requests.
"""

import asyncio
import heapq
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set


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
        self.queues: Dict[str, List[Dict[str, Any]]] = {}

        # Track queue sizes
        self.sizes: Dict[str, int] = {}

        # Track request IDs to avoid duplicates
        self.request_ids: Set[str] = set()

        # Request processor callback
        self.processor: Optional[Callable[[Dict[str, Any]], Awaitable[Any]]] = None

        # Counters for metrics
        self.total_enqueued = 0
        self.total_processed = 0
        self.total_expired = 0
        self.total_failed = 0

        # Start processing task
        self.running = True
        self.processing_task = asyncio.create_task(self._process_queue_task())

    def register_processor(self, processor: Callable[[Dict[str, Any]], Awaitable[Any]]):
        """
        Register a callback function to process queued requests.

        Args:
            processor: Async callback function that processes a request
        """
        self.processor = processor

    def enqueue_request(
        self,
        api_name: str,
        request_data: Dict[str, Any],
        expiry_seconds: Optional[int] = None,
    ) -> bool:
        """
        Add a request to the queue.

        Args:
            api_name: Name of the API
            request_data: Request data
            expiry_seconds: Optional custom expiry time in seconds

        Returns:
            True if the request was enqueued, False otherwise
        """
        # Initialize queue for this API if it doesn't exist
        if api_name not in self.queues:
            self.queues[api_name] = []
            self.sizes[api_name] = 0

        # Check if queue is full
        if self.sizes[api_name] >= self.max_size:
            self.logger.warning(f"Queue for {api_name} is full, rejecting request")
            return False

        # Generate unique request ID and check for duplicates
        request_id = f"{api_name}_{int(time.time())}_{hash(str(request_data))}"
        if request_id in self.request_ids:
            self.logger.warning(
                f"Duplicate request detected for {api_name}, not enqueueing"
            )
            return False

        # Calculate expiry time
        expiry = time.time() + (
            expiry_seconds if expiry_seconds is not None else self.default_expiry
        )

        # Add request to queue
        queue_item = {
            "expiry": expiry,
            "added_at": time.time(),
            "request_data": request_data,
            "api_name": api_name,
            "request_id": request_id,
            "attempts": 0,
        }

        # Add to priority queue (min heap based on expiry time)
        heapq.heappush(self.queues[api_name], (expiry, queue_item))
        self.sizes[api_name] += 1
        self.request_ids.add(request_id)
        self.total_enqueued += 1

        self.logger.info(
            f"Request enqueued for {api_name}, queue size: {self.sizes[api_name]}"
        )
        return True

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
                _, item = heapq.heappop(self.queues[api_name])
                self.sizes[api_name] -= 1

                # Remove from request ID tracking
                if item["request_id"] in self.request_ids:
                    self.request_ids.remove(item["request_id"])

                # Check if the request is expired
                if (current_time - item["added_at"]) > 2 * self.default_expiry:
                    self.logger.warning(
                        f"Request in queue for {api_name} expired after waiting too long"
                    )
                    self.total_expired += 1
                    continue

                # Process the request
                await self._process_request_item(item)

    async def _process_request_item(self, item: Dict[str, Any]):
        """
        Process a single request item from the queue.

        Args:
            item: Queue item with request data
        """
        if not self.processor:
            self.logger.error("No request processor registered")
            return

        api_name = item["api_name"]
        request_data = item["request_data"]

        try:
            # Increment attempts counter
            item["attempts"] += 1
            max_attempts = 3  # Maximum number of retry attempts

            # Process the request
            self.logger.info(
                f"Processing queued request for {api_name} (attempt {item['attempts']})"
            )
            await self.processor(request_data)

            # Successfully processed
            self.total_processed += 1
            self.logger.info(f"Successfully processed queued request for {api_name}")

        except Exception as e:
            self.logger.warning(
                f"Error processing queued request for {api_name}: {str(e)}"
            )

            # If we haven't exceeded max attempts, requeue with a delay
            if item["attempts"] < max_attempts:
                # Re-add to the queue with a delay
                delay = 10 * (2 ** (item["attempts"] - 1))  # Exponential backoff
                new_expiry = time.time() + delay

                # Generate new request ID
                item["request_id"] = (
                    f"{api_name}_{int(time.time())}_{hash(str(request_data))}"
                )

                # Re-add to queue
                if api_name in self.queues:
                    heapq.heappush(self.queues[api_name], (new_expiry, item))
                    self.sizes[api_name] += 1
                    self.request_ids.add(item["request_id"])
                    self.logger.info(
                        f"Requeued request for {api_name} with {delay}s delay (attempt {item['attempts']})"
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
        for _, item in self.queues[api_name]:
            if item["request_id"] in self.request_ids:
                self.request_ids.remove(item["request_id"])

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
        """Stop the queue processing task."""
        self.running = False
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass
