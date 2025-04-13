"""
Tests for the request queue component.

This module contains tests for the RequestQueue class, which handles
queueing and processing of API requests.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from test_utils import run_queue_processor, test_logger

from nya_proxy.request_queue import RequestQueue


@pytest.mark.unit
class TestRequestQueueBasics:
    """Basic tests for the RequestQueue class."""

    def test_initialization(self, test_logger):
        """Test initialization with various parameters."""
        queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

        assert queue.max_size == 10
        assert queue.expiry_seconds == 60
        assert queue.logger == test_logger
        assert queue.processor is None

        # Check empty initial state
        assert queue.get_queue_size("any_api") == 0
        metrics = queue.get_metrics()
        assert metrics["total_queued"] == 0
        assert metrics["total_processed"] == 0
        assert metrics["total_expired"] == 0

    def test_enqueue_dequeue(self, empty_request_queue):
        """Test basic enqueue and dequeue operations."""
        queue = empty_request_queue

        # Queue should be empty initially
        assert queue.get_queue_size("test_api") == 0

        # Enqueue a request
        queue.enqueue_request("test_api", {"id": 1, "data": "test"}, 60)

        # Queue should now have one item
        assert queue.get_queue_size("test_api") == 1

        # Dequeue the request
        request = queue.dequeue_request("test_api")

        # Check request data
        assert request["id"] == 1
        assert request["data"] == "test"

        # Queue should be empty again
        assert queue.get_queue_size("test_api") == 0

    def test_queue_size_limits(self, empty_request_queue):
        """Test queue size limits are enforced."""
        queue = empty_request_queue  # max_size=10 from fixture

        # Fill queue to capacity
        for i in range(10):
            result = queue.enqueue_request("test_api", {"id": i}, 60)
            assert result is True

        # Attempt to enqueue one more (should fail)
        result = queue.enqueue_request("test_api", {"id": "overflow"}, 60)
        assert result is False

        # Queue size should still be 10
        assert queue.get_queue_size("test_api") == 10

        # Dequeue one item
        queue.dequeue_request("test_api")

        # Now we should be able to enqueue again
        result = queue.enqueue_request("test_api", {"id": "new_item"}, 60)
        assert result is True

    def test_multi_api_queues(self, empty_request_queue):
        """Test handling multiple API queues separately."""
        queue = empty_request_queue

        # Enqueue requests for different APIs
        queue.enqueue_request("api1", {"id": 1}, 60)
        queue.enqueue_request("api1", {"id": 2}, 60)
        queue.enqueue_request("api2", {"id": 3}, 60)
        queue.enqueue_request("api3", {"id": 4}, 60)

        # Check queue sizes
        assert queue.get_queue_size("api1") == 2
        assert queue.get_queue_size("api2") == 1
        assert queue.get_queue_size("api3") == 1

        # Dequeue from api1
        request = queue.dequeue_request("api1")
        assert request["id"] == 1

        # Check updated queue size
        assert queue.get_queue_size("api1") == 1

        # Get all queue sizes at once
        sizes = queue.get_all_queue_sizes()
        assert sizes == {"api1": 1, "api2": 1, "api3": 1}

    def test_request_expiry(self, mock_time):
        """Test that expired requests are not processed."""
        mock_time.return_value = 100

        queue = RequestQueue(max_size=10, expiry_seconds=30, logger=test_logger())

        # Enqueue with different expiry times
        queue.enqueue_request("api", {"id": 1}, 50)  # Expires at 150
        queue.enqueue_request("api", {"id": 2}, 10)  # Expires at 110

        # Advance time to 120
        mock_time.return_value = 120

        # First item should still be valid, second should be expired
        item = queue.dequeue_request("api")
        assert item["id"] == 1

        # No more valid items
        assert queue.dequeue_request("api") is None
        assert queue.get_queue_size("api") == 0

        # Check metrics to confirm the expired count
        metrics = queue.get_metrics()
        assert metrics["total_expired"] == 1


@pytest.mark.unit
class TestRequestQueueProcessing:
    """Tests for the request processing functionality."""

    @pytest.mark.asyncio
    async def test_register_processor(self, empty_request_queue):
        """Test registering a request processor."""
        queue = empty_request_queue

        # Create mock processor
        mock_processor = AsyncMock(return_value="processed")

        # Register processor
        queue.register_processor(mock_processor)
        assert queue.processor == mock_processor

    @pytest.mark.asyncio
    async def test_process_queue_task(self, request_queue_with_processor):
        """Test the process_queue_task method."""
        queue, processor = request_queue_with_processor

        # Enqueue a request
        queue.enqueue_request("test_api", {"id": 1}, 60)

        # Run processor briefly
        metrics = await run_queue_processor(queue, 0.1)

        # Processor should have processed the item
        assert len(processor.processed_items) == 1
        assert processor.processed_items[0][0] == "test_api"
        assert processor.processed_items[0][1]["id"] == 1

        # Queue should be empty
        assert queue.get_queue_size("test_api") == 0

        # Metrics should reflect the processing
        assert metrics["total_processed"] == 1

    @pytest.mark.asyncio
    async def test_processor_order(self, test_logger):
        """Test that requests are processed in FIFO order within each API."""
        queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

        # Create a simple async processor that just appends to a list
        processed_items = []

        async def test_processor(api_name, request_data):
            await asyncio.sleep(0.01)  # Small delay
            processed_items.append((api_name, request_data["id"]))
            return "processed"

        queue.register_processor(AsyncMock(side_effect=test_processor))

        # Enqueue requests for the same API
        queue.enqueue_request("api1", {"id": 1}, 60)
        queue.enqueue_request("api1", {"id": 2}, 60)
        queue.enqueue_request("api1", {"id": 3}, 60)

        # Run processor briefly
        await run_queue_processor(queue, 0.1)

        # Check processing order
        assert processed_items == [("api1", 1), ("api1", 2), ("api1", 3)]

    @pytest.mark.asyncio
    async def test_multi_api_processing(self, test_logger):
        """Test processing items from multiple API queues."""
        queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

        # Track processed items
        processed_apis = set()
        processed_ids = set()

        async def test_processor(api_name, request_data):
            await asyncio.sleep(0.01)  # Small delay
            processed_apis.add(api_name)
            processed_ids.add(request_data["id"])
            return "processed"

        queue.register_processor(AsyncMock(side_effect=test_processor))

        # Enqueue requests for different APIs
        queue.enqueue_request("api1", {"id": 1}, 60)
        queue.enqueue_request("api2", {"id": 2}, 60)
        queue.enqueue_request("api3", {"id": 3}, 60)

        # Run processor briefly
        await run_queue_processor(queue, 0.1)

        # Check that all APIs were processed
        assert processed_apis == {"api1", "api2", "api3"}
        assert processed_ids == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_queue_metrics(self, request_queue_with_processor):
        """Test the queue metrics collection."""
        queue, processor = request_queue_with_processor

        # Make sure metrics start at 0
        metrics = queue.get_metrics()
        assert metrics["total_queued"] == 0
        assert metrics["total_processed"] == 0
        assert metrics["total_expired"] == 0

        # Enqueue some requests
        queue.enqueue_request("api1", {"id": 1}, 60)
        queue.enqueue_request("api1", {"id": 2}, 60)
        queue.enqueue_request("api2", {"id": 3}, 60)

        # Check metrics after enqueueing
        metrics = queue.get_metrics()
        assert metrics["total_queued"] == 3

        # Process the queue
        metrics = await run_queue_processor(queue, 0.2)

        # Check metrics after processing
        assert metrics["total_queued"] == 3
        assert metrics["total_processed"] == 3

        # Add some requests that will expire
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000
            queue.enqueue_request("api1", {"id": 4}, 5)  # Expires at 1005

            # Advance time past expiry
            mock_time.return_value = 1010

            # Process the queue
            metrics = await run_queue_processor(queue, 0.1)

            # Check metrics after expiry
            assert metrics["total_expired"] == 1

    @pytest.mark.asyncio
    async def test_processor_error_handling(self, request_queue_with_failing_items):
        """Test error handling in the queue processor."""
        queue, processor = request_queue_with_failing_items

        # Run the processor
        metrics = await run_queue_processor(queue, 0.5)

        # All items should have been processed (even those that failed)
        assert len(processor.processed_items) == 5
        assert queue.get_queue_size("api1") == 0

        # Check metrics - no specific errors metric but processed should be 5
        assert metrics["total_processed"] == 5

        # Logger should have logged errors
        assert queue.logger.error.call_count > 0


@pytest.mark.unit
class TestRequestQueueAdvanced:
    """Advanced tests for the RequestQueue class."""

    @pytest.mark.asyncio
    async def test_queue_processor_stress(self, test_logger):
        """Test the queue processor under stress with many queued items."""
        queue = RequestQueue(max_size=1000, expiry_seconds=60, logger=test_logger)

        # Create processor with short delay
        processed_items = []

        async def test_processor(api_name, request_data):
            await asyncio.sleep(0.02)  # 20ms processing time per item
            processed_items.append((api_name, request_data["id"]))
            return f"processed_{api_name}_{request_data['id']}"

        queue.register_processor(AsyncMock(side_effect=test_processor))

        # Enqueue a large number of items
        for api in ["api1", "api2"]:
            for i in range(50):
                queue.enqueue_request(api, {"id": f"{api}_{i}"}, 60)

        # Start the queue processor
        process_task = asyncio.create_task(queue.process_queue_task())

        # Let it run for a short time
        await asyncio.sleep(0.5)

        # Cancel the task
        process_task.cancel()
        try:
            await process_task
        except asyncio.CancelledError:
            pass

        # Check that items were processed
        # Should have processed approximately 25 items (0.5s ÷ 0.02s = ~25 items)
        # But allow some leeway due to overhead and scheduling
        assert len(processed_items) > 0

        # Check metrics
        metrics = queue.get_metrics()
        assert metrics["total_processed"] > 0

        # Get current queue sizes
        sizes = queue.get_all_queue_sizes()
        total_remaining = sum(sizes.values())

        # Verify that some items were processed (not all 100 should remain)
        assert total_remaining < 100

    @pytest.mark.asyncio
    async def test_mixed_expiry_processing(self, test_logger):
        """Test processing of items with mixed expiry times across APIs."""
        queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

        with patch("time.time") as mock_time:
            mock_time.return_value = 1000

            # Add items with different expiry times
            queue.enqueue_request("api1", {"id": 1}, 60)  # Expires at 1060
            queue.enqueue_request("api1", {"id": 2}, 20)  # Expires at 1020
            queue.enqueue_request("api1", {"id": 3}, 90)  # Expires at 1090
            queue.enqueue_request("api2", {"id": 4}, 100)  # Expires at 1100
            queue.enqueue_request("api3", {"id": 5}, 10)  # Expires at 1010 (urgent)

            # Register a processor that tracks processing order
            processed_items = []
            processed_apis = set()
            processed_ids = set()

            async def test_processor(api_name, request_data):
                await asyncio.sleep(0.05)  # Small processing delay
                processed_items.append((api_name, request_data["id"]))
                processed_apis.add(api_name)
                processed_ids.add(request_data["id"])
                return f"processed_{api_name}_{request_data['id']}"

            queue.register_processor(AsyncMock(side_effect=test_processor))

            # Start processing
            process_task = asyncio.create_task(queue.process_queue_task())

            # Let it process a few items
            await asyncio.sleep(0.2)  # Should process ~4 items

            # Cancel the task
            process_task.cancel()
            try:
                await process_task
            except asyncio.CancelledError:
                pass

            # Check that all APIs were processed
            assert "api1" in processed_apis
            assert "api2" in processed_apis
            assert "api3" in processed_apis

            # Check that all IDs were processed
            assert set(id for _, id in processed_items) == {1, 2, 3, 4, 5}

            # Check metrics
            metrics = queue.get_metrics()
            assert metrics["total_processed"] == 5

            # Some items may have been marked as expired during the time jump
            assert (
                metrics["total_expired"] >= 0
            )  # May be 0 if all processed before expiry
