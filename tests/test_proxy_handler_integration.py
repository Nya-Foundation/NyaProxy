"""
Integration tests for the proxy handler focusing on end-to-end request handling.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from nya_proxy.proxy_handler import ProxyHandler


class MockResponse:
    """Mock HTTP response for testing."""

    def __init__(self, status_code=200, content=None, headers=None):
        self.status_code = status_code
        self.content = content or b'{"status": "ok"}'
        self.headers = headers or {"Content-Type": "application/json"}
        self.elapsed = MagicMock()
        self.elapsed.total_seconds = lambda: 0.1

    async def json(self):
        return json.loads(self.content)

    async def read(self):
        return self.content


@pytest.mark.integration
class TestProxyHandlerIntegration:
    """Integration test cases for the ProxyHandler class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration for testing."""
        config = {
            "apis": {
                "test_api": {
                    "name": "Test API",
                    "endpoint": "https://test-api.example.com",
                    "headers": {
                        "Authorization": "Bearer ${{keys}}",
                        "User-Agent": "${{agents}}",
                    },
                    "variables": {
                        "keys": ["test_key_1", "test_key_2"],
                        "agents": ["TestAgent/1.0", "TestAgent/2.0"],
                    },
                },
                "api_with_complex_path": {
                    "name": "Complex Path API",
                    "endpoint": "https://api.complex-path.com",
                    "aliases": ["complex", "complex-path"],
                    "headers": {"Authorization": "Bearer ${{keys}}"},
                    "variables": {"keys": ["complex_key_1", "complex_key_2"]},
                },
                "api_with_templates": {
                    "name": "Template API",
                    "endpoint": "https://${{domain}}/api",
                    "headers": {
                        "Authorization": "Bearer ${{keys}}",
                        "Accept": "application/json",
                    },
                    "variables": {
                        "keys": ["template_key_1", "template_key_2"],
                        "domain": ["api1.example.com", "api2.example.com"],
                    },
                },
            },
            "default_settings": {
                "rate_limit": {"endpoint_rate_limit": "10/s", "key_rate_limit": "5/s"},
                "load_balancing_strategy": "round_robin",
                "timeout_seconds": 30,
            },
        }
        return config

    @pytest.fixture
    def mock_request_factory(self):
        """Create a factory for mock requests."""

        def create_request(
            path="/api/test_api/v1/endpoint", method="GET", headers=None, body=None
        ):
            mock_req = MagicMock(spec=Request)
            mock_req.method = method
            mock_req.url = MagicMock()
            mock_req.url.path = path
            mock_req.headers = headers or {"Content-Type": "application/json"}
            mock_req.body = AsyncMock(return_value=body or b'{"key": "value"}')
            return mock_req

        return create_request

    @pytest.fixture
    def proxy_handler(self, mock_config, test_logger, request_queue, metrics_collector):
        """Create a ProxyHandler instance for testing with mock config."""
        config_manager = MagicMock()
        config_manager.get_config.return_value = mock_config
        config_manager.get_queue_enabled.return_value = True

        handler = ProxyHandler(
            config_manager=config_manager,
            logger=test_logger,
            request_queue=request_queue,
            metrics_collector=metrics_collector,
        )

        # Run the init method to set up everything
        asyncio.run(handler.init())

        # Return the handler
        yield handler

        # Clean up
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.run_until_complete(handler.close())
        else:
            asyncio.run(handler.close())

    @pytest.mark.asyncio
    async def test_end_to_end_request_handling_success(
        self, proxy_handler, mock_request_factory
    ):
        """Test end-to-end request handling with successful response."""
        request = mock_request_factory("/api/test_api/v1/chat/completions")

        # Mock the HTTP client send method
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            # Configure mock to return a successful response
            mock_response = MockResponse(
                status_code=200,
                content=b'{"id":"test-id","choices":[{"message":{"content":"Test response"}}]}',
                headers={"Content-Type": "application/json"},
            )
            mock_send.return_value = mock_response

            # Make the request through the handler
            response = await proxy_handler.handle_request(request)

            # Verify response
            assert response.status_code == 200
            assert json.loads(response.body)["id"] == "test-id"

            # Verify proper API key rotation and request formatting
            assert mock_send.call_count == 1
            args, kwargs = mock_send.call_args
            assert "Authorization" in kwargs["headers"]
            assert kwargs["headers"]["Authorization"].startswith("Bearer test_key_")

    @pytest.mark.asyncio
    async def test_error_handling_and_retries(
        self, proxy_handler, mock_request_factory
    ):
        """Test error handling and retry logic."""
        request = mock_request_factory("/api/test_api/v1/endpoint")

        # Mock the HTTP client send method to fail initially then succeed
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            # First call returns 502 error
            error_response = MockResponse(
                status_code=502,
                content=b'{"error": "Bad Gateway"}',
            )
            # Second call succeeds
            success_response = MockResponse(
                status_code=200,
                content=b'{"success": true}',
            )

            mock_send.side_effect = [error_response, success_response]

            # Mock retry settings
            with patch.object(
                proxy_handler.config_manager, "get_retry_enabled"
            ) as mock_retry_enabled:
                with patch.object(
                    proxy_handler.config_manager, "get_retry_attempts"
                ) as mock_retry_attempts:
                    with patch.object(
                        proxy_handler.config_manager, "get_retry_after_seconds"
                    ) as mock_retry_after:
                        mock_retry_enabled.return_value = True
                        mock_retry_attempts.return_value = 3
                        mock_retry_after.return_value = 0.1  # Short delay for tests

                        # Make the request through the handler
                        response = await proxy_handler.handle_request(request)

                        # Verify response is the successful one
                        assert response.status_code == 200
                        assert json.loads(response.body)["success"] is True

                        # Verify send was called twice (error + success)
                        assert mock_send.call_count == 2

    @pytest.mark.asyncio
    async def test_complex_path_routing(self, proxy_handler, mock_request_factory):
        """Test routing with complex path structures."""
        # Test the API with complex path
        request = mock_request_factory("/api/complex-path/v2/data")

        # Mock the HTTP client send method
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_response = MockResponse(status_code=200)
            mock_send.return_value = mock_response

            # Make the request through the handler
            await proxy_handler.handle_request(request)

            # Verify the request was parsed correctly and sent to the right endpoint
            args, kwargs = mock_send.call_args
            assert kwargs["url"] == "https://api.complex-path.com/v2/data"
            assert "Authorization" in kwargs["headers"]
            assert kwargs["headers"]["Authorization"][7:] in [
                "complex_key_1",
                "complex_key_2",
            ]

    @pytest.mark.asyncio
    async def test_template_variable_substitution(
        self, proxy_handler, mock_request_factory
    ):
        """Test template variable substitution in URLs and headers."""
        # Test the API with template variables
        request = mock_request_factory("/api/api_with_templates/v1/data")

        # Mock the HTTP client send method
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_response = MockResponse(status_code=200)
            mock_send.return_value = mock_response

            # Make the request through the handler
            await proxy_handler.handle_request(request)

            # Verify template variables were substituted correctly
            args, kwargs = mock_send.call_args
            assert kwargs["url"].startswith("https://api")
            assert kwargs["url"].endswith(".example.com/api/v1/data")
            assert "Authorization" in kwargs["headers"]
            assert kwargs["headers"]["Authorization"].startswith("Bearer template_key_")
            assert kwargs["headers"]["Accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_rate_limit_handling(self, proxy_handler, mock_request_factory):
        """Test handling of rate limited requests."""
        request = mock_request_factory("/api/test_api/v1/endpoint")

        # Mock the rate limiter to deny the request
        with patch.object(
            proxy_handler, "_check_endpoint_rate_limit"
        ) as mock_rate_check:
            mock_rate_check.return_value = False

            # Make the request through the handler
            response = await proxy_handler.handle_request(request)

            # Verify response indicates rate limiting
            assert response.status_code in (429, 202)  # 429 if rejected, 202 if queued

            response_data = json.loads(response.body)
            if response.status_code == 429:
                assert "rate limit exceeded" in response_data.get("error", "").lower()
            else:
                assert "queued" in response_data.get("status", "").lower()

    @pytest.mark.asyncio
    async def test_request_queuing(
        self, proxy_handler, mock_request_factory, request_queue
    ):
        """Test queuing of rate limited requests."""
        request = mock_request_factory("/api/test_api/v1/endpoint")

        # Mock the rate limiter to deny the request
        with patch.object(
            proxy_handler, "_check_endpoint_rate_limit"
        ) as mock_rate_check:
            mock_rate_check.return_value = False

            # Mock queue enabled check
            with patch.object(
                proxy_handler.config_manager, "get_queue_enabled"
            ) as mock_queue_enabled:
                mock_queue_enabled.return_value = True

                # Make the request through the handler
                response = await proxy_handler.handle_request(request)

                # Verify response indicates queuing
                assert response.status_code == 202
                assert json.loads(response.body)["status"] == "queued"

                # Verify the request was actually queued
                queue_sizes = request_queue.get_all_queue_sizes()
                assert "test_api" in queue_sizes
                assert queue_sizes["test_api"] > 0

    @pytest.mark.asyncio
    async def test_multiple_api_key_rotation(self, proxy_handler, mock_request_factory):
        """Test rotation through multiple API keys."""
        request = mock_request_factory("/api/test_api/v1/endpoint")

        # Mock the HTTP client send method
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_response = MockResponse(status_code=200)
            mock_send.return_value = mock_response

            # Make several requests
            used_keys = set()
            for _ in range(5):  # Should use all keys at least once
                await proxy_handler.handle_request(request)
                args, kwargs = mock_send.call_args
                auth_header = kwargs["headers"]["Authorization"]
                key = auth_header.split("Bearer ")[1]
                used_keys.add(key)

            # Should have used both test keys
            assert "test_key_1" in used_keys
            assert "test_key_2" in used_keys

    @pytest.mark.asyncio
    async def test_content_streaming(self, proxy_handler, mock_request_factory):
        """Test handling of streaming API responses."""
        request = mock_request_factory("/api/test_api/v1/chat/completions?stream=true")

        # Mock streaming response
        stream_chunks = [
            b'{"id":"chunk1","choices":[{"delta":{"content":"Hello"}}]}',
            b'{"id":"chunk2","choices":[{"delta":{"content":" world"}}]}',
            b'{"id":"chunk3","choices":[{"delta":{"content":"!"}}]}',
        ]

        # Create a mock for streaming response
        mock_streaming_response = MagicMock()
        mock_streaming_response.status_code = 200
        mock_streaming_response.headers = {"Content-Type": "text/event-stream"}
        mock_streaming_response.elapsed = MagicMock()
        mock_streaming_response.elapsed.total_seconds = lambda: 0.3

        # Configure async iterator for the response
        mock_streaming_response.__aiter__.return_value = [
            chunk for chunk in stream_chunks
        ]

        # Mock the HTTP client send method
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_streaming_response

            # Make the request through the handler
            response = await proxy_handler.handle_request(request)

            # For streaming responses, should return a streaming response
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("Content-Type", "")

    @pytest.mark.asyncio
    async def test_response_transformation(self, proxy_handler, mock_request_factory):
        """Test transformation of API responses."""
        request = mock_request_factory("/api/test_api/v1/endpoint")

        # Mock response
        original_response = {
            "id": "test-id",
            "model": "test-model",
            "sensitive_data": "should-not-be-exposed",
            "choices": [{"text": "Test response"}],
        }

        # Mock the HTTP client send method
        with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
            mock_response = MockResponse(
                status_code=200, content=json.dumps(original_response).encode()
            )
            mock_send.return_value = mock_response

            # Mock transform function to remove sensitive data
            with patch.object(
                proxy_handler.config_manager, "get_response_transformation"
            ) as mock_transform:

                def transform_func(response_data, api_name):
                    if "sensitive_data" in response_data:
                        del response_data["sensitive_data"]
                    return response_data

                mock_transform.return_value = transform_func

                # Make the request through the handler
                response = await proxy_handler.handle_request(request)

                # Verify response transformation
                assert response.status_code == 200
                response_data = json.loads(response.body)
                assert "id" in response_data
                assert "sensitive_data" not in response_data
