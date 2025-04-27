"""
Response processing utilities for NyaProxy.
"""

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Dict, Optional

import httpx
from fastapi import Response
from starlette.responses import JSONResponse, StreamingResponse

from ..common.utils import decode_content, json_safe_dumps

if TYPE_CHECKING:
    from ..common.models import NyaRequest
    from ..services.load_balancer import LoadBalancer
    from ..services.metrics import MetricsCollector


class ResponseProcessor:
    """
    Processes API responses, handling content encoding, streaming, and errors.
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        metrics_collector: Optional["MetricsCollector"] = None,
        load_balancer: Optional[Dict[str, "LoadBalancer"]] = {},
    ):
        """
        Initialize the response processor.

        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        self.metrics_collector = metrics_collector
        self.load_balancer = load_balancer

    def record_lb_stats(self, api_name: str, api_key: str, elapsed: float) -> None:
        """
        Record load balancer statistics for the API key.

        Args:
            api_key: API key used for the request
            elapsed: Time taken to process the request
        """
        load_balancer = self.load_balancer.get(api_name)

        if not load_balancer:
            return

        load_balancer.record_response_time(api_key, elapsed)

    def record_response_metrics(
        self,
        r: "NyaRequest",
        response: Optional[httpx.Response],
        start_time: float = 0.0,
    ) -> None:
        """
        Record response metrics for the API.
        Args:
            r: NyaRequest object containing request data
            response: Response from httpx client
            start_time: Request start time
        """

        api_name = r.api_name
        api_key = r.api_key or "unknown"

        now = time.time()

        # Calculate elapsed time
        elapsed = now - r.added_at
        response_time = now - start_time
        status_code = response.status_code if response else 502

        self.logger.debug(
            f"Received response from {api_name} with status {status_code} in {elapsed:.2f}s"
        )

        if self.metrics_collector and r.apply_rate_limit:
            self.metrics_collector.record_response(
                api_name, api_key, status_code, elapsed
            )

        self.record_lb_stats(api_name, api_key, response_time)

    async def process_response(
        self,
        r: "NyaRequest",
        httpx_response: Optional[httpx.Response],
        start_time: float,
        original_host: str = "",
    ) -> Response:
        """
        Process an API response.

        Args:
            request: NyaRequest object containing request data
            httpx_response: Response from httpx client
            start_time: Request start time
            original_host: Original host for HTML responses

        Returns:
            Processed response for the client
        """
        # Handle missing response
        if not httpx_response:
            return JSONResponse(
                status_code=502,
                content={"error": "Bad Gateway: No response from target API"},
            )

        # Record metrics for successful responses
        self.record_response_metrics(r, httpx_response, start_time)

        # lowercase all headers and remove unnecessary ones
        headers = {k.lower(): v for k, v in httpx_response.headers.items()}
        headers_to_remove = ["server", "date", "transfer-encoding", "content-length"]

        for header in headers_to_remove:
            if header in headers:
                del headers[header]

        # Determine the response content type
        content_type = httpx_response.headers.get("content-type", "application/json")

        self.logger.debug(f"Response status code: {httpx_response.status_code}")
        self.logger.debug(f"Response Headers\n: {json_safe_dumps(headers)}")

        # Handle streaming response (event-stream)
        stream_content_types = [
            "text/event-stream",
            "application/octet-stream",
            "application/x-ndjson",
            "multipart/x-mixed-replace ",
            "video/*",
            "audio/*",
        ]

        # Check if it's streaming based on headers
        is_streaming = headers.get("transfer-encoding", "") == "chunked" or any(
            ct in content_type for ct in stream_content_types
        )

        if is_streaming:
            return await self._handle_streaming_response(httpx_response)

        # If non-streaming, accumulate content
        content_chunks = []
        async for chunk in httpx_response.aiter_bytes():
            content_chunks.append(chunk)
        raw_content = b"".join(content_chunks)

        # Decode content if encoded
        content_encoding = headers.get("content-encoding", "")
        raw_content = decode_content(raw_content, content_encoding)
        headers["content-encoding"] = ""

        # HTML specific handling
        if "text/html" in content_type:
            raw_content = raw_content.decode("utf-8", errors="replace")
            raw_content = self.add_base_tag(raw_content, original_host)
            raw_content = raw_content.encode("utf-8")

        self.logger.debug(f"Response Content: {json_safe_dumps(raw_content)}")

        return Response(
            content=raw_content,
            status_code=httpx_response.status_code,
            media_type=content_type,
            headers=headers,
        )

    def add_base_tag(self, html_content: str, original_host: str):
        head_pos = html_content.lower().find("<head>")
        if head_pos > -1:
            head_end = head_pos + 6  # length of '<head>'
            base_tag = f'<base href="{original_host}/">'
            modified_html = html_content[:head_end] + base_tag + html_content[head_end:]
            return modified_html
        return html_content

    def _handle_streaming_header(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Handle headers for streaming responses with SSE best practices.

        Args:
            headers: Headers from the httpx response

        Returns:
            Processed headers for streaming
        """
        # Headers to remove for streaming responses
        headers_to_remove = [
            "content-encoding",
            "content-length",
            "connection",
        ]

        for header in headers_to_remove:
            if header in headers:
                del headers[header]

        # Set SSE-specific headers according to standards
        headers["cache-control"] = "no-cache, no-transform"
        headers["connection"] = "keep-alive"
        headers["x-accel-buffering"] = "no"  # Prevent Nginx buffering
        headers["transfer-encoding"] = "chunked"

        return headers

    async def _handle_streaming_response(
        self, httpx_response: httpx.Response
    ) -> StreamingResponse:
        """
        Handle a streaming response (SSE) with industry best practices.

        Args:
            httpx_response: Response from httpx client

        Returns:
            Streaming response
        """
        self.logger.debug(
            f"Handling streaming response with status {httpx_response.status_code}"
        )
        headers = dict(httpx_response.headers)
        status_code = httpx_response.status_code
        content_type = httpx_response.headers.get("content-type", "").lower()

        # Process headers for streaming
        headers = self._handle_streaming_header(headers)

        async def event_generator():
            try:
                async for chunk in httpx_response.aiter_bytes():
                    if chunk:
                        self.logger.debug(
                            f"Forwarding stream chunk: {len(chunk)} bytes"
                        )
                        await asyncio.sleep(0.01)  # Yield control to event loop
                        yield chunk
            except Exception as e:
                self.logger.error(f"Error in streaming response: {str(e)}")
            finally:
                if hasattr(httpx_response, "_stream_ctx"):
                    await httpx_response._stream_ctx.__aexit__(None, None, None)

        return StreamingResponse(
            content=event_generator(),
            status_code=status_code,
            media_type=content_type or "application/octet-stream",
            headers=headers,
        )

    def create_error_response(
        self, error: Exception, status_code: int = 500, api_name: str = "unknown"
    ) -> JSONResponse:
        """
        Create an error response for the client.

        Args:
            error: Exception that occurred
            status_code: HTTP status code to return
            api_name: Name of the API

        Returns:
            Error response
        """

        error_message = str(error)
        if status_code == 429:
            message = f"Rate limit exceeded: {error_message}"
        elif status_code == 504:
            message = f"Gateway timeout: {error_message}"
        else:
            message = f"Internal proxy error: {error_message}"

        return JSONResponse(
            status_code=status_code,
            content={"error": message},
        )
