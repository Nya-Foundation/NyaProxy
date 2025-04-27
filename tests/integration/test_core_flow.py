import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx  # For creating mock responses
import pytest
from fastapi.responses import JSONResponse

from nya_proxy.common.exceptions import QueueFullError
from nya_proxy.common.models import NyaRequest
from nya_proxy.core.handler import NyaProxyCore
from nya_proxy.core.header_processor import HeaderProcessor
from nya_proxy.core.request_executor import RequestExecutor
from nya_proxy.core.response_processor import ResponseProcessor

# Adjust imports based on potential refactoring
from nya_proxy.server.config import ConfigManager
from nya_proxy.services.key_manager import KeyManager
from nya_proxy.services.load_balancer import LoadBalancer
from nya_proxy.services.metrics import MetricsCollector
from nya_proxy.services.rate_limiter import RateLimiter
from nya_proxy.services.request_queue import RequestQueue


# --- Fixtures ---
@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager with a sample API config."""
    config = MagicMock(spec=ConfigManager)
    api_name = "test_api"
    key_variable = "api_keys"
    keys = ["key1", "key2"]

    # Basic NyaProxy settings
    config.get_debug_level.return_value = "INFO"
    config.get_queue_enabled.return_value = True  # Enable queue for some tests
    config.get_queue_size.return_value = 10
    config.get_queue_expiry.return_value = 30

    # API specific settings
    config.get_apis.return_value = {api_name: {"name": "Test API"}}
    config.get_api_endpoint.return_value = f"http://mock-backend.test/{api_name}"
    config.get_api_key_variable.return_value = key_variable
    config.get_api_variable_values.side_effect = lambda name, var: (
        keys if name == api_name and var == key_variable else []
    )
    config.get_api_load_balancing_strategy.return_value = "round_robin"
    config.get_api_endpoint_rate_limit.return_value = "10/m"  # Sample limits
    config.get_api_key_rate_limit.return_value = "5/m"
    config.get_api_rate_limit_paths.return_value = ["*"]  # Apply to all paths
    config.get_api_custom_headers.return_value = {
        "Authorization": "Bearer ${{api_keys}}"
    }
    config.get_api_retry_enabled.return_value = (
        False  # Disable retry for simplicity here
    )
    config.get_api_default_timeout.return_value = 10
    config.get_api_retry_status_codes.return_value = [429, 500, 503]
    config.get_api_retry_request_methods.return_value = [
        "GET",
        "POST",
    ]  # Methods to allow retry

    return config


@pytest.fixture
def mock_nya_request():
    """Factory for creating NyaRequest objects."""

    def _factory(api_name="test_api", path="/v1/test", method="GET", content=b""):
        # Create a mock URL object
        mock_url = MagicMock()
        mock_url.path = f"/api/{api_name}{path}"  # Simulate incoming path to NyaProxy
        mock_url.query = ""
        return NyaRequest(
            method=method,
            _url=mock_url,  # Original incoming URL
            url=None,  # Core should populate this
            headers={"x-client-header": "client-val"},
            content=content,
            api_name=api_name,  # Core should populate this too, but set for clarity
        )

    return _factory


@pytest.fixture
def nya_proxy_core(mock_config_manager, mock_logger):
    """Provides an instance of NyaProxyCore with mocked dependencies."""
    # Mock dependencies that NyaProxyCore initializes internally
    with patch("nya_proxy.core.handler.KeyManager") as MockKeyManager, patch(
        "nya_proxy.core.handler.RequestExecutor"
    ) as MockRequestExecutor, patch(
        "nya_proxy.core.handler.ResponseProcessor"
    ) as MockResponseProcessor, patch(
        "nya_proxy.core.handler.RequestQueue"
    ) as MockRequestQueue, patch(
        "nya_proxy.core.handler.HeaderProcessor"
    ) as MockHeaderProcessor, patch(
        "nya_proxy.core.handler.LoadBalancer"
    ) as MockLoadBalancer, patch(
        "nya_proxy.core.handler.MetricsCollector"
    ) as MockMetricsCollector, patch(
        "nya_proxy.services.rate_limiter.RateLimiter"
    ) as MockRateLimiter:  # Mock RateLimiter creation

        # Configure mocks created during NyaProxyCore.__init__
        mock_metrics = MockMetricsCollector.return_value
        mock_lb = MockLoadBalancer.return_value
        mock_key_manager = MockKeyManager.return_value
        mock_request_queue = MockRequestQueue.return_value
        mock_header_processor = MockHeaderProcessor.return_value
        mock_request_executor = MockRequestExecutor.return_value
        mock_response_processor = MockResponseProcessor.return_value

        # Mock specific behaviors needed for tests
        mock_key_manager.has_available_keys = AsyncMock(return_value=True)
        mock_key_manager.get_available_key = AsyncMock(return_value="key1")
        mock_key_manager.get_api_rate_limiter = MagicMock(
            return_value=MockRateLimiter.return_value
        )  # Return the mock RL
        MockRateLimiter.return_value.allow_request.return_value = True  # Default allow
        MockRateLimiter.return_value.is_rate_limited.return_value = False
        mock_header_processor.extract_required_variables = MagicMock(
            return_value={"api_keys"}
        )
        mock_header_processor._process_headers.return_value = {
            "Authorization": "Bearer key1",
            "host": "mock-backend.test",
        }  # Simulate processed headers
        mock_request_executor.execute_with_retry = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"data": "success"},
                request=httpx.Request("GET", "http://mock"),
            )
        )
        mock_response_processor.process_response = AsyncMock(
            return_value=MagicMock(spec=httpx.Response)
        )  # Return a mock response object

        # Instantiate NyaProxyCore - this will use the patched classes
        core = NyaProxyCore(config=mock_config_manager, logger=mock_logger)

        # Store mocks on the core instance for easy access in tests
        core.mock_key_manager = mock_key_manager
        core.mock_request_executor = mock_request_executor
        core.mock_response_processor = mock_response_processor
        core.mock_request_queue = mock_request_queue
        core.mock_header_processor = mock_header_processor
        core.mock_metrics_collector = mock_metrics
        core.mock_endpoint_limiter = (
            MockRateLimiter.return_value
        )  # The one created for the endpoint

        yield core


# --- Test Cases ---


@pytest.mark.asyncio
async def test_handle_request_success_flow(nya_proxy_core, mock_nya_request):
    """Test the standard successful request path through handle_request."""
    request = mock_nya_request()
    start_time = time.time()

    # Mock time.time() for consistent elapsed time calculation if needed
    with patch("time.time", return_value=start_time + 1.0):
        response = await nya_proxy_core.handle_request(request)

    # 1. Check preparation steps
    # parse_request is called internally by _prepare_request
    # _prepare_request sets api_name and url on the request object
    assert request.api_name == "test_api"
    assert request.url == "http://mock-backend.test/test_api/v1/test"

    # 2. Check rate limit check (should allow)
    nya_proxy_core.mock_key_manager.has_available_keys.assert_awaited_once_with(
        "test_api"
    )
    nya_proxy_core.mock_key_manager.get_api_rate_limiter.assert_called_once_with(
        "test_api"
    )
    nya_proxy_core.mock_endpoint_limiter.allow_request.assert_called_once()  # From _check_endpoint_rate_limit

    # 3. Check header processing
    # _set_custom_request_headers is called within _process_request
    nya_proxy_core.mock_header_processor.extract_required_variables.assert_called_once()
    nya_proxy_core.mock_header_processor._process_headers.assert_called_once()
    # Check that the processed headers were assigned back to the request
    assert request.headers["Authorization"] == "Bearer key1"

    # 4. Check request execution
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_awaited_once()
    # Verify the request object passed to executor has updated headers/url
    call_args, _ = nya_proxy_core.mock_request_executor.execute_with_retry.await_args
    executed_request = call_args[0]
    assert executed_request == request  # Should be the same modified request object
    assert executed_request.url == "http://mock-backend.test/test_api/v1/test"
    assert executed_request.headers["Authorization"] == "Bearer key1"

    # 5. Check response processing
    nya_proxy_core.mock_response_processor.process_response.assert_awaited_once()
    call_args, _ = nya_proxy_core.mock_response_processor.process_response.await_args
    assert call_args[0] == request  # Check request object
    assert call_args[1].status_code == 200  # Check httpx_response passed

    # 6. Check final response
    assert isinstance(response, MagicMock)  # We mocked the final response object


@pytest.mark.asyncio
async def test_handle_request_unknown_api(
    nya_proxy_core, mock_nya_request, mock_config_manager
):
    """Test handling a request for an API not in the config."""
    # Make config return empty dict for get_apis
    mock_config_manager.get_apis.return_value = {}
    # Re-initialize core or mock the parse_request part if possible
    # For simplicity, let's assume parse_request will return None, None

    request = mock_nya_request(api_name="unknown", path="/path")

    # Patch the internal parse_request method result
    with patch.object(nya_proxy_core, "parse_request", return_value=(None, None)):
        response = await nya_proxy_core.handle_request(request)

    assert response.status_code == 404
    assert response.body == b'{"error":"Unknown API endpoint"}'
    # Ensure executor and response processor were not called
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_not_awaited()
    nya_proxy_core.mock_response_processor.process_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_request_endpoint_rate_limited_no_queue(
    nya_proxy_core, mock_nya_request, mock_config_manager
):
    """Test endpoint rate limit hit when queueing is disabled."""
    mock_config_manager.get_queue_enabled.return_value = False  # Disable queue
    nya_proxy_core.request_queue = None  # Ensure queue is None

    request = mock_nya_request()

    # Simulate endpoint rate limit hit
    nya_proxy_core.mock_endpoint_limiter.allow_request.return_value = False
    nya_proxy_core.mock_endpoint_limiter.get_reset_time.return_value = (
        5.0  # Example reset time
    )

    response = await nya_proxy_core.handle_request(request)

    assert response.status_code == 429
    assert "Rate limit exceeded" in response.body.decode()
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_not_awaited()
    nya_proxy_core.mock_response_processor.process_response.assert_not_awaited()
    # Since request_queue is None, we don't need to assert anything about it


@pytest.mark.asyncio
async def test_handle_request_endpoint_rate_limited_with_queue(
    nya_proxy_core, mock_nya_request
):
    """Test endpoint rate limit hit when queueing is enabled."""
    request = mock_nya_request()

    # Simulate endpoint rate limit hit
    nya_proxy_core.mock_endpoint_limiter.allow_request.return_value = False
    nya_proxy_core.mock_endpoint_limiter.get_reset_time.return_value = 5.0

    # Mock queue behavior
    mock_future = asyncio.Future()
    nya_proxy_core.mock_request_queue.enqueue_request = AsyncMock(
        return_value=mock_future
    )
    nya_proxy_core.mock_request_queue.get_estimated_wait_time = AsyncMock(
        return_value=2.0
    )
    nya_proxy_core.mock_key_manager.get_api_rate_limit_reset = AsyncMock(
        return_value=5.0
    )  # Endpoint reset

    # Simulate the queued request eventually completing
    async def resolve_future():
        await asyncio.sleep(0.01)  # Short delay
        mock_future.set_result(
            JSONResponse(content={"queued": "response"}, status_code=200)
        )

    asyncio.create_task(resolve_future())

    response = await nya_proxy_core.handle_request(request)

    # Check that queue was called
    nya_proxy_core.mock_request_queue.enqueue_request.assert_awaited_once()
    kwargs = nya_proxy_core.mock_request_queue.enqueue_request.await_args.kwargs
    assert kwargs["r"] == request
    assert kwargs["reset_in_seconds"] == 5  # max(key_reset, queue_wait) -> 5.0

    # Check that the final response is the one from the queue future
    assert response.status_code == 200
    assert response.body == b'{"queued":"response"}'

    # Ensure executor and response processor were not called directly by handle_request
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_not_awaited()
    nya_proxy_core.mock_response_processor.process_response.assert_not_awaited()
    # Ensure metrics recorded queue hit
    nya_proxy_core.mock_metrics_collector.record_queue_hit.assert_called_once_with(
        request.api_name
    )
    nya_proxy_core.mock_metrics_collector.record_rate_limit_hit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_request_key_exhausted_no_queue(
    nya_proxy_core, mock_nya_request, mock_config_manager
):
    """Test API key exhaustion when queueing is disabled."""
    mock_config_manager.get_queue_enabled.return_value = False
    nya_proxy_core.request_queue = None

    request = mock_nya_request()

    # Simulate key exhaustion
    nya_proxy_core.mock_key_manager.has_available_keys = AsyncMock(return_value=False)

    response = await nya_proxy_core.handle_request(request)

    assert response.status_code == 429  # Should still be 429
    assert "Rate limit exceeded" in response.body.decode()  # Or similar message
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_not_awaited()
    nya_proxy_core.mock_response_processor.process_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_request_key_exhausted_with_queue(
    nya_proxy_core, mock_nya_request
):
    """Test API key exhaustion when queueing is enabled."""
    request = mock_nya_request()

    # Simulate key exhaustion
    nya_proxy_core.mock_key_manager.has_available_keys = AsyncMock(return_value=False)

    # Mock queue behavior (similar to endpoint rate limit)
    mock_future = asyncio.Future()
    nya_proxy_core.mock_request_queue.enqueue_request = AsyncMock(
        return_value=mock_future
    )
    nya_proxy_core.mock_request_queue.get_estimated_wait_time = AsyncMock(
        return_value=3.0
    )
    # Simulate key reset time being the limiting factor
    nya_proxy_core.mock_key_manager.get_api_rate_limit_reset = AsyncMock(
        return_value=8.0
    )  # Key reset time

    async def resolve_future():
        await asyncio.sleep(0.01)
        mock_future.set_result(
            JSONResponse(content={"queued_key": "response"}, status_code=200)
        )

    asyncio.create_task(resolve_future())

    response = await nya_proxy_core.handle_request(request)

    # Check queue was called
    nya_proxy_core.mock_request_queue.enqueue_request.assert_awaited_once()
    kwargs = nya_proxy_core.mock_request_queue.enqueue_request.await_args.kwargs
    assert kwargs["r"] == request
    assert kwargs["reset_in_seconds"] == 8  # max(key_reset, queue_wait) -> 8.0

    assert response.status_code == 200
    assert response.body == b'{"queued_key":"response"}'
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_not_awaited()
    nya_proxy_core.mock_response_processor.process_response.assert_not_awaited()
    nya_proxy_core.mock_metrics_collector.record_queue_hit.assert_called_once_with(
        request.api_name
    )
    nya_proxy_core.mock_metrics_collector.record_rate_limit_hit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_request_queue_full(nya_proxy_core, mock_nya_request):
    """Test when the queue is full."""
    request = mock_nya_request()

    # Simulate endpoint rate limit hit to trigger queue path
    nya_proxy_core.mock_endpoint_limiter.allow_request.return_value = False
    nya_proxy_core.mock_endpoint_limiter.get_reset_time.return_value = 5.0

    # Mock queue to raise QueueFullError
    nya_proxy_core.mock_request_queue.enqueue_request.side_effect = QueueFullError(
        "test_api", 10
    )

    response = await nya_proxy_core.handle_request(request)

    # Should return 429 as queueing failed
    assert response.status_code == 429
    assert "Rate limit exceeded" in response.body.decode()
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_not_awaited()
    nya_proxy_core.mock_response_processor.process_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_request_skip_rate_limit_path(
    nya_proxy_core, mock_nya_request, mock_config_manager
):
    """Test that rate limiting is skipped for non-matching paths."""
    # Configure only specific paths for rate limiting
    mock_config_manager.get_api_rate_limit_paths.return_value = ["/v1/limited/*"]

    # Create a request that *doesn't* match the limited path
    request = mock_nya_request(path="/v1/unlimited")

    # Ensure endpoint limiter *would* block if checked
    nya_proxy_core.mock_endpoint_limiter.allow_request.return_value = False

    # Set apply_rate_limit to False since the path doesn't match
    # This is normally done by _should_apply_rate_limit which we're testing
    request.apply_rate_limit = False

    # Mock key manager to prevent awaiting MagicMock issue
    nya_proxy_core.mock_key_manager.get_available_key = AsyncMock(
        return_value="test-key"
    )

    # Mock executor and response processor for success path
    nya_proxy_core.mock_request_executor.execute_with_retry = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"data": "unlimited_success"},
            request=httpx.Request("GET", "http://mock"),
        )
    )
    nya_proxy_core.mock_response_processor.process_response = AsyncMock(
        return_value=JSONResponse({"final": "response"})
    )

    # Patch the _should_apply_rate_limit method to return False
    with patch.object(nya_proxy_core, "_should_apply_rate_limit", return_value=False):
        response = await nya_proxy_core.handle_request(request)

    # Verify rate limit checks were skipped
    nya_proxy_core.mock_key_manager.get_api_rate_limiter.assert_not_called()  # Should not be called
    nya_proxy_core.mock_endpoint_limiter.allow_request.assert_not_called()  # Should not be called

    # Verify the request went through the execution path
    nya_proxy_core.mock_request_executor.execute_with_retry.assert_awaited_once()
    nya_proxy_core.mock_response_processor.process_response.assert_awaited_once()
    assert response.body == b'{"final":"response"}'
    assert request.apply_rate_limit is False  # Check flag was set
