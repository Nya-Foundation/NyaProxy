"""
Tests for the proxy handler component.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from starlette.responses import JSONResponse


@pytest.mark.unit
class TestProxyHandler:
    """Test cases for the ProxyHandler class."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock FastAPI request."""
        mock_req = MagicMock(spec=Request)
        mock_req.method = "GET"
        mock_req.url = MagicMock()
        mock_req.url.path = "/api/test_api/v1/endpoint"
        mock_req.headers = {"Content-Type": "application/json"}
        mock_req.body = AsyncMock(return_value=b'{"key": "value"}')
        return mock_req

    @pytest.mark.asyncio
    async def test_handle_request_basic(self, proxy_handler, mock_request):
        """Test basic request handling."""
        # Mock the _parse_request method to return a known API
        with patch.object(proxy_handler, "_parse_request") as mock_parse:
            mock_parse.return_value = (
                "test_api",
                "/v1/endpoint",
                {"name": "Test API", "endpoint": "https://test-api.example.com"},
            )

            # Mock the _prepare_request method
            with patch.object(proxy_handler, "_prepare_request") as mock_prepare:
                request_data = {
                    "method": "GET",
                    "url": "https://test-api.example.com/v1/endpoint",
                    "headers": {"Authorization": "Bearer test_key_1"},
                    "content": b'{"key": "value"}',
                    "_key_used": "test_key_1",
                    "_api_name": "test_api",
                }
                mock_prepare.return_value = request_data

                # Mock the _process_and_handle_response method
                with patch.object(
                    proxy_handler, "_process_and_handle_response"
                ) as mock_process:
                    mock_process.return_value = JSONResponse(
                        status_code=200, content={"success": True}
                    )

                    # Execute the request handler
                    response = await proxy_handler.handle_request(mock_request)

                    # Verify the response
                    assert response.status_code == 200
                    assert json.loads(response.body)["success"] is True

                    # Verify all methods were called with correct parameters
                    mock_parse.assert_called_once_with("/api/test_api/v1/endpoint")
                    mock_prepare.assert_called_once()
                    mock_process.assert_called_once_with(
                        request_data,
                        "test_api",
                        {
                            "name": "Test API",
                            "endpoint": "https://test-api.example.com",
                        },
                        mock_process.call_args[0][3],  # The start_time
                    )

    @pytest.mark.asyncio
    async def test_parse_request(self, proxy_handler):
        """Test parsing of request paths."""
        # Test direct API match
        api_name, trail_path, api_config = proxy_handler._parse_request(
            "/api/test_api/v1/chat"
        )
        assert api_name == "test_api"
        assert trail_path == "/v1/chat"
        assert api_config is not None

        # Test with subpath
        api_name, trail_path, api_config = proxy_handler._parse_request(
            "/api/api2/v1/chat"
        )
        assert api_name == "test_api_2"
        assert trail_path == "/v1/chat"
        assert api_config is not None

        # Test non-existent API
        api_name, trail_path, api_config = proxy_handler._parse_request(
            "/api/nonexistent/path"
        )
        assert api_name is None
        assert trail_path is None
        assert api_config is None

        # Test invalid path format
        api_name, trail_path, api_config = proxy_handler._parse_request("/invalid/path")
        assert api_name is None
        assert trail_path is None
        assert api_config is None

    @pytest.mark.asyncio
    async def test_handle_request_exception(self, proxy_handler):
        """Test handling of exceptions during request processing."""
        # Create a mock exception
        test_exception = Exception("Test error")
        start_time = 1000.0
        api_name = "test_api"

        # Call the exception handler
        response = proxy_handler._handle_request_exception(
            test_exception, start_time, api_name
        )

        # Verify the response
        assert response.status_code == 500
        assert "error" in json.loads(response.body)
        assert "Test error" in json.loads(response.body)["error"]

        # If metrics collector is available, it should record the error
        if proxy_handler.metrics_collector:
            proxy_handler.metrics_collector.record_response.assert_called_with(
                api_name, 500, pytest.approx(time.time() - start_time, 0.1)
            )

    @pytest.mark.asyncio
    async def test_handle_rate_limit_exceeded_with_queue(
        self, proxy_handler, mock_request
    ):
        """Test handling of rate limited requests with queuing enabled."""
        api_name = "test_api"
        trail_path = "/v1/endpoint"
        api_config = {"name": "Test API", "endpoint": "https://test-api.example.com"}

        # Mock the _prepare_request method to return request data
        with patch.object(proxy_handler, "_prepare_request") as mock_prepare:
            request_data = {
                "method": "GET",
                "url": "https://test-api.example.com/v1/endpoint",
                "headers": {"Authorization": "Bearer test_key"},
                "content": b'{"key": "value"}',
                "_key_used": "test_key",
                "_api_name": api_name,
            }
            mock_prepare.return_value = request_data

            # Mock queue enabled check
            with patch.object(
                proxy_handler.config_manager, "get_queue_enabled"
            ) as mock_queue_enabled:
                mock_queue_enabled.return_value = True

                # Mock the request queue's enqueue_request method
                with patch.object(
                    proxy_handler.request_queue, "enqueue_request"
                ) as mock_enqueue:
                    mock_enqueue.return_value = True

                    # Get queue size
                    with patch.object(
                        proxy_handler.request_queue, "get_queue_size"
                    ) as mock_queue_size:
                        mock_queue_size.return_value = 5

                        # Handle the rate limited request
                        response = await proxy_handler._handle_rate_limit_exceeded(
                            mock_request, api_name, trail_path, api_config
                        )

                        # Verify the response indicates queuing
                        assert response.status_code == 202  # Accepted
                        response_data = json.loads(response.body)
                        assert response_data["status"] == "queued"
                        assert response_data["queue_size"] == 5

    @pytest.mark.asyncio
    async def test_check_endpoint_rate_limit(self, proxy_handler):
        """Test checking of endpoint rate limits."""
        api_name = "test_api"
        api_config = {"name": "Test API", "endpoint": "https://test-api.example.com"}
        path = "/v1/chat/completions"

        # Mock the rate limiter to allow the request
        with patch.object(
            proxy_handler.rate_limiters[f"{api_name}_endpoint"], "allow_request"
        ) as mock_allow:
            mock_allow.return_value = True
            assert (
                await proxy_handler._check_endpoint_rate_limit(
                    api_name, api_config, path
                )
                is True
            )

            # Test rate limit exceeded
            mock_allow.return_value = False
            assert (
                await proxy_handler._check_endpoint_rate_limit(
                    api_name, api_config, path
                )
                is False
            )

    @pytest.mark.asyncio
    async def test_get_available_key(self, proxy_handler):
        """Test getting an available API key."""
        api_name = "test_api"
        load_balancer = proxy_handler.load_balancers[api_name]

        # Mock the load balancer's get_next method
        with patch.object(load_balancer, "get_next") as mock_get_next:
            mock_get_next.return_value = "test_key_1"

            # Mock the rate limiter's allow_request method
            with patch.object(
                proxy_handler.rate_limiters[f"{api_name}_test_key_1"], "allow_request"
            ) as mock_allow:
                mock_allow.return_value = True

                # Get an available key
                key = await proxy_handler._get_available_key(api_name, load_balancer)

                # Verify the key
                assert key == "test_key_1"
                mock_get_next.assert_called_once()
                mock_allow.assert_called_once()

    def test_identify_template_variables(self, proxy_handler):
        """Test identifying template variables in strings."""
        # Test template with one variable
        vars = proxy_handler.identify_template_variables("Bearer ${{token}}")
        assert vars == ["token"]

        # Test template with multiple variables
        vars = proxy_handler.identify_template_variables(
            "Header1: ${{var1}}, Header2: ${{var2}}"
        )
        assert sorted(vars) == sorted(["var1", "var2"])

        # Test template with repeated variables
        vars = proxy_handler.identify_template_variables(
            "${{token}} and also ${{token}} again"
        )
        assert vars == ["token", "token"]

        # Test template with no variables
        vars = proxy_handler.identify_template_variables("No variables here")
        assert vars == []

    def test_replace_template_variables(self, proxy_handler):
        """Test replacing template variables in strings."""
        # Simple replacement
        result = proxy_handler.replace_template_variables(
            "Bearer ${{token}}", {"token": "abc123"}
        )
        assert result == "Bearer abc123"

        # Multiple replacements
        result = proxy_handler.replace_template_variables(
            "Header1: ${{var1}}, Header2: ${{var2}}",
            {"var1": "value1", "var2": "value2"},
        )
        assert result == "Header1: value1, Header2: value2"

        # Replacement with missing variable
        result = proxy_handler.replace_template_variables("Bearer ${{token}}", {})
        assert result == "Bearer ${{token}}"

        # Mixed replacements
        result = proxy_handler.replace_template_variables(
            "Bearer ${{token}}, Agent: ${{agent}}", {"token": "abc123"}
        )
        assert result == "Bearer abc123, Agent: ${{agent}}"

    @pytest.mark.asyncio
    async def test_prepare_headers(self, proxy_handler, mock_request):
        """Test preparation of request headers with variable substitution."""
        api_name = "test_api"
        api_config = {
            "name": "Test API",
            "endpoint": "https://test-api.example.com",
            "headers": {
                "Authorization": "Bearer ${{keys}}",
                "User-Agent": "${{agents}}",
                "X-Custom": "static-value",
            },
        }
        key_variable = "keys"
        key = "test_key_1"

        # Mock the load balancer for agents variable
        with patch.object(proxy_handler, "load_balancers") as mock_load_balancers:
            mock_agents_lb = MagicMock()
            mock_agents_lb.get_next.return_value = "TestAgent/1.0"
            mock_load_balancers.get.return_value = mock_agents_lb

            # Prepare headers
            headers = await proxy_handler._prepare_headers(
                mock_request, api_name, api_config, key_variable, key
            )

            # Check headers
            assert headers["Authorization"] == "Bearer test_key_1"
            assert headers["User-Agent"] == "TestAgent/1.0"
            assert headers["X-Custom"] == "static-value"

            # Original request headers should be preserved if not overridden
            assert headers["Content-Type"] == "application/json"

    def test_get_target_path(self, proxy_handler):
        """Test constructing the target path for API requests."""
        # Test with basic path
        path = proxy_handler._get_target_path(
            "/test_api/v1/chat", "test_api", {"name": "Test API"}
        )
        assert path == "/v1/chat"

        # Test with subpath
        path = proxy_handler._get_target_path(
            "/api2/v1/data",
            "test_api_2",
            {"name": "Test API 2", "aliases": ["api2", "testapi2"]},
        )
        assert path == "/v1/data"

        # Test with path that doesn't match api or subpath
        path = proxy_handler._get_target_path(
            "/custom/path", "test_api", {"name": "Test API"}
        )
        assert path == "custom/path"
