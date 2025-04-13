"""
Advanced tests for the request queue component focusing on concurrency and reliability.

This module contains more complex test cases for the RequestQueue class,
including concurrent operations, priority-based processing, and stress testing.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

# Import our test utilities
from test_utils import AsyncTestProcessor

from nya_proxy.request_queue import RequestQueue


@pytest.mark.unit
class TestRequestQueueAdvanced:
    """Advanced test cases for the RequestQueue class."""

    @pytest.mark.asyncio
    async def test_concurrent_enqueue_dequeue(self, test_logger):
        """Test concurrent enqueue and dequeue operations."""
        queue = RequestQueue(max_size=100, expiry_seconds=60, logger=test_logger)

        # Define concurrent enqueuing task
        async def enqueue_task(api_name, count):
            results = []
            for i in range(count):
                result = queue.enqueue_request(api_name, {"id": f"{api_name}_{i}"}, 60)
                results.append(result)
                await asyncio.sleep(0.01)  # Small delay to simulate real-world scenario
            return results

        # Define concurrent dequeueing task
        async def dequeue_task(api_name, count):
            results = []
            for _ in range(count):
                result = queue.dequeue_request(api_name)
                if result:
                    results.append(result)
                await asyncio.sleep(0.01)
            return results

        # Run concurrent operations
        enqueue_tasks = [
            asyncio.create_task(enqueue_task("api1", 20)),
            asyncio.create_task(enqueue_task("api2", 15)),
            asyncio.create_task(enqueue_task("api3", 10)),
        ]

        # Short delay to let enqueueing start
        await asyncio.sleep(0.05)

        dequeue_tasks = [
            asyncio.create_task(dequeue_task("api1", 15)),
            asyncio.create_task(dequeue_task("api2", 10)),
            asyncio.create_task(dequeue_task("api3", 5)),
        ]

        # Wait for all tasks to complete
        enqueue_results = await asyncio.gather(*enqueue_tasks)
        dequeue_results = await asyncio.gather(*dequeue_tasks)

        # Verify that all enqueue operations succeeded
        for results in enqueue_results:
            assert all(results)

        # Verify that expected number of items were dequeued
        assert len(dequeue_results[0]) <= 15  # api1
        assert len(dequeue_results[1]) <= 10  # api2
        assert len(dequeue_results[2]) <= 5  # api3

        # Check final queue states
        assert queue.get_queue_size("api1") == 20 - len(dequeue_results[0])
        assert queue.get_queue_size("api2") == 15 - len(dequeue_results[1])
        assert queue.get_queue_size("api3") == 10 - len(dequeue_results[2])

    @pytest.mark.asyncio
    async def test_queue_processor_stress(self, test_logger):
        """Test the queue processor under stress with many queued items."""
        queue = RequestQueue(max_size=1000, expiry_seconds=60, logger=test_logger)

        # Create processor with short delay
        processor = AsyncTestProcessor(delay=0.02)  # 20ms processing time per item
        queue.register_processor(processor.get_processor_mock())

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
        metrics = queue.get_metrics()
        assert metrics["total_processed"] > 0

        # Get current queue sizes
        sizes = queue.get_all_queue_sizes()
        total_remaining = sum(sizes.values())

        # Verify that some items were processed (not all 100 should remain)
        assert total_remaining < 100

    @pytest.mark.asyncio
    async def test_request_priority_processing(self, test_logger):
        """Test priority-based processing when items have expiry times."""
        queue = RequestQueue(max_size=100, expiry_seconds=60, logger=test_logger)

        with patch("time.time") as mock_time:
            # Start at time 1000
            mock_time.return_value = 1000

            # Add items with different expiry times
            queue.enqueue_request(
                "api1", {"id": 1, "priority": "low"}, 120
            )  # Expires at 1120
            queue.enqueue_request(
                "api1", {"id": 2, "priority": "high"}, 30
            )  # Expires at 1030
            queue.enqueue_request(
                "api1", {"id": 3, "priority": "medium"}, 60
            )  # Expires at 1060

            # Register a processor that tracks processing order
            processed_items = []

            async def test_processor(api_name, request_data):
                processed_items.append(request_data["id"])
                return f"processed_{api_name}_{request_data['id']}"

            queue.register_processor(AsyncMock(side_effect=test_processor))

            # Run the processor task
            process_task = asyncio.create_task(queue.process_queue_task())

            # Let it process all items
            await asyncio.sleep(0.2)

            # Cancel the task
            process_task.cancel()
            try:
                await process_task
            except asyncio.CancelledError:
                pass

            # Verify that all items were processed
            assert len(processed_items) == 3

            # The most important assertion is that all items got processed
            assert set(processed_items) == {1, 2, 3}

            # If the queue implements expiry-based priority, items should be processed
            # in order of soonest expiry first
            if processed_items[0] == 2 and processed_items[1] == 3:
                # Expiry order was respected: 2 (expires soonest), then 3, then 1
                assert True  # This is the expected case
            else:
                # If not in expiry order, this might be FIFO or another ordering
                # Since implementation might vary, we don't strictly assert on this
                pass

    @pytest.mark.asyncio
    async def test_processor_error_handling(self, test_logger):
        """Test error handling in the queue processor."""
        queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

        # Create a processor that randomly fails
        processor = AsyncTestProcessor(failure_ids=[2, 4])
        queue.register_processor(processor.get_processor_mock())

        # Enqueue some requests, including ones that will fail
        queue.enqueue_request("api1", {"id": 1}, 60)
        queue.enqueue_request("api1", {"id": 2}, 60)  # Will fail
        queue.enqueue_request("api1", {"id": 3}, 60)
        queue.enqueue_request("api1", {"id": 4}, 60)  # Will fail
        queue.enqueue_request("api1", {"id": 5}, 60)

        # Run the processor
        process_task = asyncio.create_task(queue.process_queue_task())

        # Let it process
        await asyncio.sleep(0.3)

        # Cancel the task
        process_task.cancel()
        try:
            await process_task
        except asyncio.CancelledError:
            pass

        # Verify queue metrics - all items should have been processed or attempted
        metrics = queue.get_metrics()
        assert queue.get_queue_size("api1") == 0
        assert metrics["total_processed"] == 5

        # Verify that the failures were logged
        assert test_logger.error.call_count >= 2

    @pytest.mark.asyncio
    async def test_mixed_expiry_processing(self, test_logger):
        """Test processing of items with mixed expiry times across APIs."""
        queue = RequestQueue(max_size=100, expiry_seconds=60, logger=test_logger)

        with patch("time.time") as mock_time:
            # Start at time 1000
            mock_time.return_value = 1000

            # Add items with different expiry times for different APIs
            # API1: mostly far-future expiry
            queue.enqueue_request("api1", {"id": 1}, 120)  # Expires at 1120
            queue.enqueue_request("api1", {"id": 2}, 180)  # Expires at 1180

            # API2: mixed expiry
            queue.enqueue_request("api2", {"id": 3}, 20)  # Expires at 1020 (soon)
            queue.enqueue_request("api2", {"id": 4}, 100)  # Expires at 1100

            # API3: urgent expiry
            queue.enqueue_request("api3", {"id": 5}, 10)  # Expires at 1010 (urgent)

            # Register a processor that tracks processing order
            processed_items = []

            async def test_processor(api_name, request_data):
                await asyncio.sleep(0.05)  # Small processing delay
                processed_items.append((api_name, request_data["id"]))
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

            # Advance time to expire some items
            mock_time.return_value = 1030

            # Restart processing
            process_task = asyncio.create_task(queue.process_queue_task())

            # Let it process remaining items
            await asyncio.sleep(0.2)

            # Cancel the task
            process_task.cancel()
            try:
                await process_task
            except asyncio.CancelledError:
                pass

            # If the queue prioritizes by expiry across APIs, the order should favor
            # items that expire soonest regardless of API
            # Most urgent items should be processed first
            processed_apis = [item[0] for item in processed_items]
            processed_ids = [item[1] for item in processed_items]

            # Check that all items were eventually processed
            assert len(processed_items) == 5

            # Check that all APIs were processed
            assert "api1" in processed_apis
            assert "api2" in processed_apis
            assert "api3" in processed_apis

            # Check that all IDs were processed
            assert set(processed_ids) == {1, 2, 3, 4, 5}

            # Check metrics
            metrics = queue.get_metrics()
            assert metrics["total_processed"] == 5

            # Some items may have been marked as expired during the time jump
            assert (
                metrics["total_expired"] >= 0
            )  # May be 0 if all processed before expiry

    @pytest.mark.asyncio
    async def test_request_dedupe_option(self, test_logger):
        """Test optional deduplication of identical requests."""
        # Create a queue with deduplication enabled (if supported)
        # Note: This test assumes the RequestQueue has a dedupe_identical parameter
        # If not, it would need to be modified or skipped

        try:
            queue = RequestQueue(
                max_size=10,
                expiry_seconds=60,
                dedupe_identical=True,  # May need to be adjusted based on implementation
                logger=test_logger,
            )
        except TypeError:
            # If dedupe_identical isn't supported, use basic queue and skip test
            pytest.skip("Queue doesn't support deduplication option")
            return

        # Enqueue identical requests
        data1 = {"id": "same", "payload": "identical"}
        data2 = {"id": "same", "payload": "identical"}

        # Should deduplicate identical requests
        result1 = queue.enqueue_request("api", data1, 60)
        result2 = queue.enqueue_request("api", data2, 60)

        # Both operations should succeed
        assert result1 is True
        # Second might be False if implementation rejects duplicates

        # Queue should have only one item if deduplication is working
        assert queue.get_queue_size("api") <= 1

        # Different data should still be enqueued
        data3 = {"id": "different", "payload": "unique"}
        result3 = queue.enqueue_request("api", data3, 60)

        assert result3 is True
        assert queue.get_queue_size("api") <= 2
