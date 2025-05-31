"""
Response processing utilities for NyaProxy.
"""

import time
from typing import TYPE_CHECKING, Dict, Optional, Union

import httpx
from fastapi import Response
from loguru import logger
from starlette.responses import JSONResponse, StreamingResponse

from ..utils.helper import decode_content, json_safe_dumps
from .streaming import StreamingHandler

if TYPE_CHECKING:
    from ..common.models import ProxyRequest
    from ..services.lb import LoadBalancer
    from ..services.metrics import MetricsCollector


class ResponseProcessor:
    """
    Processes API responses, handling content encoding, streaming, and errors.
    """

    def __init__(
        self,
        metrics_collector: Optional["MetricsCollector"] = None,
        load_balancer: Optional[Dict[str, "LoadBalancer"]] = {},
    ):
        """
        Initialize the response processor.

        Args:
            logger: Logger instance
        """

        self.metrics_collector = metrics_collector
        self.load_balancer = load_balancer
        self.streaming_handler = StreamingHandler()

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
        r: "ProxyRequest",
        response: Optional[httpx.Response],
        start_time: float = 0.0,
    ) -> None:
        """
        Record response metrics for the API.
        Args:
            r: ProxyRequest object containing request data
            response: Response from httpx client
            start_time: Request start time
        """

        api_name = r.api_name
        api_key = r.api_key or "unknown"

        now = time.time()

        # Calculate elapsed time
        elapsed = now - r._added_at
        response_time = now - start_time
        status_code = response.status_code if response else 502

        logger.debug(
            f"Received response from {api_name} with status {status_code} in {elapsed:.2f}s"
        )

        if self.metrics_collector and r._apply_rate_limit:
            self.metrics_collector.record_response(
                api_name, api_key, status_code, elapsed
            )

        self.record_lb_stats(api_name, api_key, response_time)

    async def process_response(
        self,
        r: "ProxyRequest",
        httpx_response: Optional[httpx.Response],
        start_time: float,
        original_host: str = "",
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Process an API response.

        Args:
            request: ProxyRequest object containing request data
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

        # Use Headers to preserve case but allow case-insensitive operations
        headers = httpx.Headers(httpx_response.headers)
        headers_to_remove = ["server", "date", "transfer-encoding", "content-length"]

        for header in headers_to_remove:
            if header.lower() in headers:
                del headers[header.lower()]

        # Determine the response content type
        content_type = httpx_response.headers.get("content-type", "application/json")

        logger.debug(f"Response status code: {httpx_response.status_code}")
        logger.debug(f"Response Headers\n: {json_safe_dumps(dict(headers.items()))}")

        # Check if it's streaming based on headers
        is_streaming = self.streaming_handler.detect_streaming_content(
            content_type, headers
        )

        # Handle streaming responses
        if is_streaming:
            return await self.streaming_handler.handle_streaming_response(
                httpx_response
            )

        # If non-streaming responses
        content_chunks = []

        async for chunk in httpx_response.aiter_bytes():
            content_chunks.append(chunk)
        raw_content = b"".join(content_chunks)

        httpx_response._content = raw_content  # Store raw content in httpx response

        # Get content-encoding from upstream api, decode content if encoded
        content_encoding = headers.get("content-encoding", "")
        raw_content = decode_content(raw_content, content_encoding)

        # Remove content-encoding header if present
        if "content-encoding" in headers:
            del headers["content-encoding"]

        # HTML specific handling, rarely used (some user might want this)
        if "text/html" in content_type:
            raw_content = raw_content.decode("utf-8", errors="replace")
            raw_content = self.add_base_tag(raw_content, original_host)
            raw_content = raw_content.encode("utf-8")

        logger.debug(f"Response Content: {json_safe_dumps(raw_content)}")

        return Response(
            content=raw_content,
            status_code=httpx_response.status_code,
            media_type=content_type,
            headers=dict(headers.items()),
        )

    # Add base tag to HTML content for relative links
    def add_base_tag(self, html_content: str, original_host: str):
        head_pos = html_content.lower().find("<head>")
        if head_pos > -1:
            head_end = head_pos + 6  # length of '<head>'
            base_tag = f'<base href="{original_host}/">'
            modified_html = html_content[:head_end] + base_tag + html_content[head_end:]
            return modified_html
        return html_content
