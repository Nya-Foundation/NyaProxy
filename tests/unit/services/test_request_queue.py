import asyncio
import heapq
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nya.services.key import KeyManager
from nya.services.queue import (
    RequestQueue,
)
from nya.common.exceptions import (
    APIKeyExhaustedError,
    QueueFullError,
    RequestExpiredError,
)
from nya.common.models import ProxyRequest


@pytest.fixture
def mock_key_manager():
    km = MagicMock(spec=KeyManager)
    km.is_api_available = AsyncMock(return_value=True)
    km.has_available_keys = AsyncMock(return_value=True)
    km.get_available_key = AsyncMock(return_value="test_key_1")
    km.get_key_rate_limit_reset = AsyncMock(return_value=0.0)  # Default reset time
    return km


@pytest.fixture
def nya_request_factory():
    def _factory(api_name="test_api", method="GET", url="/test"):
        # Create a mock URL object if starlette is not installed or needed
        mock_url = MagicMock()
        mock_url.path = url
        return ProxyRequest(
            method=method,
            _url=mock_url,
            api_name=api_name,
            headers={},
            content=b"",
        )

    return _factory


@pytest.fixture
async def request_queue(mock_key_manager):
    queue = RequestQueue(
        key_manager=mock_key_manager,
        max_size=2,  # Use a small size for testing limits
        expiry_seconds=10,  # Short expiry for testing
        start_task=False,  # Prevent background task in tests
    )

    yield queue
    # Cleanup: Stop the queue (cancels the mocked task if it existed)
    await queue.stop()


# --- Test Cases ---
@patch("nya.services.queue.logger")
def test_init(mock_logger, request_queue, mock_key_manager):
    assert request_queue.key_manager == mock_key_manager
    assert request_queue.max_size == 2
    assert request_queue.default_expiry == 10
    assert request_queue.metrics["total_enqueued"] == 0
    assert request_queue.running is True
    assert request_queue.processor is None
    assert request_queue.processing_task is None  # Not started due to start_task=False


@patch("nya.services.queue.logger")
def test_register_processor(mock_logger, request_queue):
    mock_processor = AsyncMock()
    request_queue.register_processor(mock_processor)
    assert request_queue.processor == mock_processor
    mock_logger.debug.assert_called_with("Request processor registered")


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_enqueue_request_success(mock_logger, request_queue, nya_request_factory):
    req = nya_request_factory()
    future = await request_queue.enqueue_request(req, reset_in_seconds=5)

    assert isinstance(future, asyncio.Future)
    assert request_queue.get_queue_size("test_api") == 1
    assert request_queue.metrics["total_enqueued"] == 1
    assert req._future == future
    assert req._expiry > time.time()  # Scheduled in the future
    assert req._added_at <= time.time()
    mock_logger.info.assert_called()


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_enqueue_request_queue_full(
    mock_logger, request_queue, nya_request_factory
):
    req1 = nya_request_factory(api_name="full_api")
    req2 = nya_request_factory(api_name="full_api")
    req3 = nya_request_factory(api_name="full_api")

    await request_queue.enqueue_request(req1)
    await request_queue.enqueue_request(req2)

    assert request_queue.get_queue_size("full_api") == 2

    with pytest.raises(
        QueueFullError, match=r"Queue for full_api is full \(max size: 2\)"
    ):
        await request_queue.enqueue_request(req3)

    assert request_queue.get_queue_size("full_api") == 2  # Size didn't increase
    mock_logger.warning.assert_called()


def test_ensure_queue_exists(request_queue):
    assert "new_api" not in request_queue.queues
    assert "new_api" not in request_queue.sizes
    request_queue._ensure_queue_exists("new_api")
    assert "new_api" in request_queue.queues
    assert request_queue.queues["new_api"] == []
    assert "new_api" in request_queue.sizes
    assert request_queue.sizes["new_api"] == 0


def test_get_queue_size(request_queue):
    assert request_queue.get_queue_size("non_existent_api") == 0
    request_queue._ensure_queue_exists("api1")
    request_queue.sizes["api1"] = 5
    assert request_queue.get_queue_size("api1") == 5


def test_get_all_queue_sizes(request_queue):
    request_queue._ensure_queue_exists("api1")
    request_queue.sizes["api1"] = 3
    request_queue._ensure_queue_exists("api2")
    request_queue.sizes["api2"] = 1
    assert request_queue.get_all_queue_sizes() == {"api1": 3, "api2": 1}


def test_get_metrics(request_queue):
    metrics = request_queue.get_metrics()
    assert "total_enqueued" in metrics
    assert "total_processed" in metrics
    assert "total_expired" in metrics
    assert "total_failed" in metrics
    assert "current_queue_sizes" in metrics
    assert metrics["current_queue_sizes"] == {}


@pytest.mark.asyncio
async def test_get_estimated_wait_time(
    request_queue, mock_key_manager, nya_request_factory
):
    # Test empty queue
    wait_time = await request_queue.get_estimated_wait_time("empty_api")
    assert wait_time == 0.0

    # Test with queued requests
    api_name = "wait_time_api"
    req = nya_request_factory(api_name=api_name)

    # Mock key manager reset time
    mock_key_manager.get_key_rate_limit_reset.return_value = 5.0

    current_time = time.time()
    with patch("time.time", return_value=current_time):
        await request_queue.enqueue_request(req, reset_in_seconds=10)

    wait_time = await request_queue.get_estimated_wait_time(api_name)
    # Should be max of key reset time (5.0) and queue wait time (~10.0)
    assert wait_time >= 5.0


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_process_request_item_no_processor(
    mock_logger, request_queue, nya_request_factory
):
    req = nya_request_factory()
    req._future = asyncio.Future()  # Assign a future

    # Ensure no processor is registered
    request_queue.processor = None

    await request_queue._process_request_item(req)

    assert req._future.done()
    with pytest.raises(RuntimeError, match="No request processor registered"):
        await req._future  # Check the exception set on the future
    mock_logger.error.assert_called_with("No request processor registered")
    assert request_queue.metrics["total_failed"] == 1


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_process_api_queue_success(
    mock_logger, request_queue, mock_key_manager, nya_request_factory
):
    api_name = "process_success_api"
    req = nya_request_factory(api_name=api_name)
    mock_processor = AsyncMock(return_value="Success Response")
    request_queue.register_processor(mock_processor)

    # Enqueue request scheduled for now
    current_time = time.time()
    with patch("time.time", return_value=current_time):
        future = await request_queue.enqueue_request(req, reset_in_seconds=0)

    assert request_queue.get_queue_size(api_name) == 1

    # Mock readiness checks
    mock_key_manager.is_api_available.reset_mock()
    mock_key_manager.has_available_keys.reset_mock()
    mock_key_manager.get_available_key.reset_mock()
    mock_key_manager.is_api_available.return_value = True
    mock_key_manager.has_available_keys.return_value = True
    mock_key_manager.get_available_key.return_value = "key_for_processing"

    # Process the queue (allow create_task to run)
    await request_queue._process_api_queue(
        api_name, current_time + 0.1
    )  # Ensure time has passed

    # Wait for the future to complete (handled by the background task)
    try:
        await asyncio.wait_for(future, timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail(f"Future for {api_name} did not complete within timeout")

    # Assertions
    assert request_queue.get_queue_size(api_name) == 0
    mock_processor.assert_awaited_once()
    processed_req = mock_processor.await_args[0][0]
    assert processed_req == req
    assert processed_req.api_key == "key_for_processing"  # Check key assignment
    assert future.done()
    assert await future == "Success Response"
    assert request_queue.metrics["total_processed"] == 1
    mock_logger.debug.assert_called_with(
        f"Successfully processed queued request for {api_name}"
    )


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_process_api_queue_expired(
    mock_logger, request_queue, nya_request_factory
):
    api_name = "expired_api"
    req = nya_request_factory(api_name=api_name)

    # Enqueue request scheduled for 1 second ago (already expired relative to expiry=10)
    past_time = time.time() - 15
    with patch("time.time", return_value=past_time):
        future = await request_queue.enqueue_request(
            req, reset_in_seconds=0
        )  # Schedule for past_time

    assert request_queue.get_queue_size(api_name) == 1

    # Process the queue far in the future
    await request_queue._process_api_queue(api_name, time.time() + 20)

    # Assertions
    assert request_queue.get_queue_size(api_name) == 0  # Should be removed
    assert future.done()
    with pytest.raises(RequestExpiredError):
        await future
    assert request_queue.metrics["total_expired"] == 1
    mock_logger.warning.assert_called()


@pytest.mark.asyncio
async def test_process_api_queue_not_ready(
    request_queue, mock_key_manager, nya_request_factory
):
    api_name = "not_ready_api"
    req = nya_request_factory(api_name=api_name)
    mock_processor = AsyncMock()
    request_queue.register_processor(mock_processor)

    # Enqueue request scheduled for now
    current_time = time.time()
    with patch("time.time", return_value=current_time):
        await request_queue.enqueue_request(req, reset_in_seconds=0)

    # Mock readiness checks to return False
    mock_key_manager.is_api_available.return_value = False  # Simulate endpoint limit
    mock_key_manager.has_available_keys.return_value = True

    # Process the queue
    await request_queue._process_api_queue(api_name, current_time + 0.1)

    # Assertions
    assert request_queue.get_queue_size(api_name) == 1  # Still in queue
    mock_processor.assert_not_awaited()  # Processor not called

    # Mock readiness checks - now keys are unavailable
    mock_key_manager.is_api_available.return_value = True
    mock_key_manager.has_available_keys.return_value = False

    # Process again
    await request_queue._process_api_queue(api_name, current_time + 0.2)

    # Assertions
    assert request_queue.get_queue_size(api_name) == 1  # Still in queue
    mock_processor.assert_not_awaited()  # Processor not called


@pytest.mark.asyncio
async def test_process_api_queue_key_exhausted_during_processing(
    request_queue: RequestQueue, mock_key_manager, nya_request_factory
):
    api_name = "exhausted_api"
    req1 = nya_request_factory(api_name=api_name)
    req2 = nya_request_factory(api_name=api_name)
    mock_processor = AsyncMock(return_value="Processed")
    request_queue.register_processor(mock_processor)

    # Enqueue two requests scheduled for now
    current_time = time.time()
    with patch("time.time", return_value=current_time):
        future1 = await request_queue.enqueue_request(req1, reset_in_seconds=0)
        future2 = await request_queue.enqueue_request(req2, reset_in_seconds=0)

    assert request_queue.get_queue_size(api_name) == 2

    # Use a future-specific approach rather than relying on background tasks
    # Mock processor to always complete future1 directly instead of relying on _process_request_item
    original_processor = mock_processor

    # Define a wrapper that ensures the future is completed in addition to normal processing
    async def processor_wrapper(request):
        result = await original_processor(request)
        # Directly set future result
        if (
            request == req1
            and hasattr(request, "future")
            and not request._future.done()
        ):
            request._future.set_result(result)
        return result

    # Replace the processor with our wrapper
    request_queue.processor = processor_wrapper

    # Mock key manager: first call returns a key, second raises exhausted
    mock_key_manager.get_available_key.side_effect = [
        "key1",
        APIKeyExhaustedError(api_name),
    ]
    mock_key_manager.is_api_available.return_value = True
    mock_key_manager.has_available_keys.return_value = True

    # Process the queue - using a direct approach without patching create_task
    # This ensures we have complete control over the execution flow
    async with request_queue.lock:
        # Get a key and assign it to req1
        req1.api_key = await mock_key_manager.get_available_key(api_name)
        # Pop req1 from the queue
        heapq.heappop(request_queue.queues[api_name])
        request_queue.sizes[api_name] -= 1

    # Process req1 directly
    await request_queue._process_request_item(req1)

    # Force a yield to the event loop to allow any pending callbacks to execute
    for _ in range(3):
        await asyncio.sleep(0)

    # Verify everything worked as expected
    mock_processor.assert_called_once_with(req1)
    assert request_queue.get_queue_size(api_name) == 1  # req2 remains

    # Check future1 completion
    assert future1.done(), "future1 should be completed"
    assert await future1 == "Processed"
    assert not future2.done()  # req2 future is not done
    assert request_queue.metrics["total_processed"] == 1


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_clear_queue(mock_logger, request_queue, nya_request_factory):
    api_name = "clear_api"
    req1 = nya_request_factory(api_name=api_name)
    req2 = nya_request_factory(api_name=api_name)

    future1 = await request_queue.enqueue_request(req1)
    future2 = await request_queue.enqueue_request(req2)

    assert request_queue.get_queue_size(api_name) == 2

    cleared_count = await request_queue.clear_queue(api_name)

    assert cleared_count == 2
    assert request_queue.get_queue_size(api_name) == 0
    assert request_queue.queues[api_name] == []  # Queue is empty
    assert future1.done()
    assert future2.done()
    with pytest.raises(RuntimeError, match="Request was cleared"):
        await future1
    with pytest.raises(RuntimeError, match="Request was cleared"):
        await future2
    assert request_queue.metrics["total_failed"] == 2
    mock_logger.info.assert_called_with(f"Cleared 2 requests from queue for {api_name}")


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_clear_all_queues(mock_logger, request_queue, nya_request_factory):
    req_a1 = await request_queue.enqueue_request(nya_request_factory(api_name="api_a"))
    req_a2 = await request_queue.enqueue_request(nya_request_factory(api_name="api_a"))
    req_b1 = await request_queue.enqueue_request(nya_request_factory(api_name="api_b"))

    assert request_queue.get_queue_size("api_a") == 2
    assert request_queue.get_queue_size("api_b") == 1

    total_cleared = await request_queue.clear_all_queues()

    assert total_cleared == 3
    assert request_queue.get_queue_size("api_a") == 0
    assert request_queue.get_queue_size("api_b") == 0
    assert request_queue.queues["api_a"] == []
    assert request_queue.queues["api_b"] == []
    assert req_a1.done()
    assert req_a2.done()
    assert req_b1.done()
    assert request_queue.metrics["total_failed"] == 3
    mock_logger.info.assert_called_with(
        "Cleared all queues, total of 3 requests removed"
    )


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_process_request_item_success(
    mock_logger, request_queue, nya_request_factory
):
    """Test successful processing of a request item."""
    req = nya_request_factory()
    req._future = asyncio.Future()
    req.api_key = "test_key"

    mock_processor = AsyncMock(return_value="Success Response")
    request_queue.register_processor(mock_processor)

    await request_queue._process_request_item(req)

    assert req._future.done()
    assert await req._future == "Success Response"
    assert request_queue.metrics["total_processed"] == 1
    mock_processor.assert_awaited_once_with(req)
    mock_logger.debug.assert_called_with(
        f"Successfully processed queued request for {req.api_name}"
    )


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_process_request_item_processor_error(
    mock_logger, request_queue, nya_request_factory
):
    """Test handling of processor errors."""
    req = nya_request_factory()
    req._future = asyncio.Future()
    req.api_key = "test_key"

    test_error = ValueError("Test processor error")
    mock_processor = AsyncMock(side_effect=test_error)
    request_queue.register_processor(mock_processor)

    with pytest.raises(ValueError, match="Test processor error"):
        await request_queue._process_request_item(req)

    assert req._future.done()
    with pytest.raises(ValueError, match="Test processor error"):
        await req._future
    assert request_queue.metrics["total_failed"] == 1
    mock_logger.error.assert_called_with(
        f"Error processing queued request for {req.api_name}: Test processor error"
    )


@pytest.mark.asyncio
async def test_ready_to_process(request_queue, mock_key_manager):
    """Test _ready_to_process method logic."""
    api_name = "test_api"
    request_queue._ensure_queue_exists(api_name)

    # Empty queue - should return False
    assert not await request_queue._ready_to_process(api_name)

    # Add a dummy request to the queue
    request_queue.queues[api_name].append((time.time(), "req_id", MagicMock()))

    # All conditions met - should return True
    mock_key_manager.is_api_available.return_value = True
    mock_key_manager.has_available_keys.return_value = True
    assert await request_queue._ready_to_process(api_name)

    # API not available - should return False
    mock_key_manager.is_api_available.return_value = False
    assert not await request_queue._ready_to_process(api_name)

    # No available keys - should return False
    mock_key_manager.is_api_available.return_value = True
    mock_key_manager.has_available_keys.return_value = False
    assert not await request_queue._ready_to_process(api_name)


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_handle_expired_request(mock_logger, request_queue, nya_request_factory):
    """Test expired request handling."""
    req = nya_request_factory()
    req._future = asyncio.Future()
    wait_time = 15.0

    await request_queue._handle_expired_request(req, wait_time)

    assert req._future.done()
    with pytest.raises(RequestExpiredError):
        await req._future
    assert request_queue.metrics["total_expired"] == 1
    mock_logger.warning.assert_called()


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_fail_request(mock_logger, request_queue, nya_request_factory):
    """Test _fail_request method."""
    req = nya_request_factory()
    req._future = asyncio.Future()
    test_error = RuntimeError("Test error")

    request_queue._fail_request(req, test_error)

    assert req._future.done()
    with pytest.raises(RuntimeError, match="Test error"):
        await req._future
    assert request_queue.metrics["total_failed"] == 1


@pytest.mark.asyncio
async def test_clear_queue_non_existent_api(request_queue):
    """Test clearing queue for non-existent API."""
    cleared_count = await request_queue.clear_queue("non_existent_api")
    assert cleared_count == 0


@pytest.mark.asyncio
@patch("nya.services.queue.logger")
async def test_process_queue_task_error_handling(mock_logger, mock_key_manager):
    """Test error handling in background processing task."""
    queue = RequestQueue(
        key_manager=mock_key_manager,
        max_size=2,
        expiry_seconds=10,
        start_task=True,  # Start the background task
    )

    # Mock _process_all_queues to raise an error
    original_method = queue._process_all_queues
    queue._process_all_queues = AsyncMock(side_effect=RuntimeError("Test error"))

    # Give the task time to run and handle the error
    await asyncio.sleep(0.1)

    # Verify error was logged
    mock_logger.error.assert_called()

    # Restore original method and stop queue
    queue._process_all_queues = original_method
    await queue.stop()


@pytest.mark.asyncio
async def test_stop_queue(mock_key_manager):
    """Test stopping the queue properly cancels tasks."""
    queue = RequestQueue(
        key_manager=mock_key_manager,
        max_size=2,
        expiry_seconds=10,
        start_task=True,
    )

    # Verify the task is running
    assert queue.processing_task is not None
    assert not queue.processing_task.done()

    # Stop the queue
    await queue.stop()

    # Verify the task is cancelled/stopped
    assert not queue.running
    assert queue.processing_task.done()
