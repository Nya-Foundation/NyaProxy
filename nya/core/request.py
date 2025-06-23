"""
Simplified request executor focused on HTTP execution only.
"""

import time
from typing import Optional, Union

import httpx
from loguru import logger
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..common.models import ProxyRequest
from ..config.manager import ConfigManager
from ..services.metrics import MetricsCollector
from ..utils.helper import decode_content, format_elapsed_time, json_safe_dumps
from .streaming import StreamingHandler


class RequestExecutor:
    """
    Simple request executor that does one thing well: execute HTTP requests.

    All retry logic is moved to the queue system. This class focuses
    purely on making HTTP calls and returning responses.
    """

    def __init__(
        self,
        config: ConfigManager,
        metrics_collector: Optional[MetricsCollector] = None,
    ):
        """
        Initialize the simple request executor.
        """
        self.config = config or ConfigManager.get_instance()
        self.client = self._create_client()
        self.metrics_collector = metrics_collector

    def _create_client(self) -> httpx.AsyncClient:
        """
        Create HTTP client with optimized settings.
        """
        proxy_timeout = self.config.get_default_timeout()
        timeout = self._get_timeout()

        client_kwargs = {
            "follow_redirects": True,
            "timeout": timeout,
            "limits": httpx.Limits(
                max_connections=2000,
                max_keepalive_connections=500,
                keepalive_expiry=min(120.0, proxy_timeout),
            ),
        }

        # Add proxy support if configured
        if self.config.get_proxy_enabled():
            proxy_address = self.config.get_proxy_address()
            if proxy_address:
                if proxy_address.startswith(("socks5://", "socks4://")):
                    client_kwargs["proxies"] = {"all://": proxy_address}
                else:
                    client_kwargs["proxies"] = {
                        "http://": proxy_address,
                        "https://": proxy_address,
                    }

        return httpx.AsyncClient(**client_kwargs)

    async def execute(
        self, request: ProxyRequest
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Execute a single HTTP request.

        Any retries are handled by the queue system.
        """
        actual_start_time = time.time()
        api_name = request.api_name

        # Record request metrics
        if self.metrics_collector and request._rate_limited:
            self.metrics_collector.record_request(api_name, request.api_key)

        logger.debug(f"[Request] Method: {request.method.upper()}, URL: {request.url}")

        # Execute HTTP request
        response = await self.execute_request(request, self._get_timeout(api_name))

        # Log request/response details on error response
        if response.status_code >= 400:
            logger.debug(f"[Request] Content: {json_safe_dumps(request.content)}")

        logger.debug(f"[Request] Headers: {json_safe_dumps(request.headers)}")
        logger.debug(f"[Response] Headers: {json_safe_dumps(response.headers)}")

        logger.debug(
            f"[Response] URL: {request.url}, Status: {response.status_code} "
            f"({format_elapsed_time(time.time() - actual_start_time)})"
        )

        if self.metrics_collector and request._rate_limited:
            self.metrics_collector.record_response(
                api_name,
                request.api_key,
                response.status_code,
                time.time() - actual_start_time,
            )

        # process successful response
        return await self.process_response(response)

    async def execute_request(
        self, request: ProxyRequest, timeout: httpx.Timeout
    ) -> httpx.Response:
        """
        Execute the actual HTTP request.
        """
        stream = self.client.stream(
            method=request.method,
            url=request.url,
            headers=request.headers,
            content=request.content,
            timeout=timeout,
        )

        response = await stream.__aenter__()
        response._stream_ctx = stream
        return response

    def _get_timeout(self, api_name: Optional[str] = None) -> httpx.Timeout:
        """
        Get timeout configuration for API.
        """
        timeout = (
            self.config.get_api_default_timeout(api_name)
            if api_name
            else self.config.get_default_timeout()
        )
        return httpx.Timeout(
            connect=5.0,
            read=timeout * 0.95,
            write=min(60.0, timeout * 0.2),
            pool=10.0,
        )

    async def process_response(
        self,
        response: httpx.Response,
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Process and forward the response to the client.
        """
        try:
            if StreamingHandler.detect_streaming_content(response.headers):
                return await StreamingHandler.handle_streaming_response(response)

            return await self.handle_normal_response(response)
        except Exception:
            # Ensure cleanup happens even if processing fails
            if hasattr(response, "_stream_ctx") and response._stream_ctx:
                await response._stream_ctx.__aexit__(None, None, None)
            raise

    async def handle_normal_response(
        self,
        response: httpx.Response,
    ) -> Union[Response, JSONResponse]:
        """
        Create the response to send back to client.
        """
        try:
            content_type = response.headers.get("content-type", "")
            media_type = (
                content_type.split(";")[0].strip().lower()
                if content_type
                else "application/json"
            )

            logger.debug(
                f"Handling normal response: {response.status_code} {media_type}"
            )

            # Read raw bytes without any decoding/processing
            content = b""
            async for chunk in response.aiter_raw():
                content += chunk

            return Response(
                content=content,
                status_code=response.status_code,
                headers=response.headers,
                media_type=media_type,
            )

        finally:
            # Properly close the stream context if it exists
            if hasattr(response, "_stream_ctx") and response._stream_ctx:
                await response._stream_ctx.__aexit__(None, None, None)
                response._stream_ctx = None

    async def close(self):
        """
        Close the HTTP client.
        """
        if self.client:
            await self.client.aclose()
