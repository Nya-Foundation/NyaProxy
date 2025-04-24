"""
Response processing utilities for NyaProxy.
"""

import json
import logging
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

import httpx
from fastapi import Response
from starlette.responses import JSONResponse, StreamingResponse

from .utils import decode_content

if TYPE_CHECKING:
    from .metrics import MetricsCollector
    from .load_balancer import LoadBalancer
    from .models import NyaRequest


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
        api_name: str,
        api_key: str,
        status_code: int,
        elapsed: float = 0.0,
        response_time: float = 0.0,
    ) -> None:
        """
        Record response metrics for the API.
        Args:
            api_name: Name of the API
            api_key: API key used for the request
            status_code: HTTP status code of the response
            elapsed: Time taken to process the request
            response_time: Time taken to get the response
        """
        if self.metrics_collector:
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

        api_name = r.api_name
        api_key = r.api_key or "unknown"

        now = time.time()
        # Calculate elapsed time
        elapsed = now - r.added_at
        response_time = now - start_time
        status_code = httpx_response.status_code if httpx_response else 502

        self.logger.debug(
            f"Received response from {api_name} with status {status_code} in {elapsed:.2f}s"
        )

        # Handle missing response
        if not httpx_response:
            return JSONResponse(
                status_code=502,
                content={"error": "Bad Gateway: No response from target API"},
            )

        self.record_response_metrics(
            api_name, api_key, status_code, elapsed, response_time
        )

        # Filter out unwanted headers
        headers = dict(httpx_response.headers)
        headers_to_remove = ["server", "date", "transfer-encoding", "content-length"]

        for header in headers_to_remove:
            if header.lower() in headers:
                del headers[header.lower()]

        # Determine the response content type
        content_type = httpx_response.headers.get("content-type", "application/json")

        # Handle streaming response (event-stream)
        if "text/event-stream" in content_type:
            return self._handle_streaming_response(httpx_response, headers, status_code)

        # Debug log JSON responses
        if "application/json" in content_type:
            self._log_json_response(httpx_response)

        self.logger.debug(f"Response status code: {status_code}")
        self.logger.debug(f"Response headers: {httpx_response.headers}")

        # Handle content decoding if needed
        content_encoding = httpx_response.headers.get("content-encoding", "")
        raw_content = decode_content(httpx_response.content, content_encoding)
        headers["content-encoding"] = ""

        # broswer compatibility for HTML responses
        if "text/html" in content_type:
            # Ensure raw_content is decoded to string for HTML manipulation
            if isinstance(raw_content, bytes):
                raw_content = raw_content.decode("utf-8", errors="replace")
            raw_content = self.add_base_tag(raw_content, original_host)
            # Convert back to bytes if needed
            if isinstance(raw_content, str):
                raw_content = raw_content.encode("utf-8")

        # Return response
        return Response(
            content=raw_content,
            status_code=status_code,
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

    def _handle_streaming_response(
        self, httpx_response: httpx.Response, headers: Dict[str, str], status_code: int
    ) -> StreamingResponse:
        """
        Handle a streaming response (SSE), Not working need to be fixed.

        Args:
            httpx_response: Response from httpx client
            headers: Response headers
            status_code: Response status code

        Returns:
            Streaming response
        """
        self.logger.debug("Detected streaming response, forwarding as event-stream")

        async def event_generator():
            async for chunk in httpx_response.aiter_bytes():
                yield chunk

        # Stream-specific header setup
        headers["cache-control"] = "no-cache"  # Common in SSE

        return StreamingResponse(
            content=event_generator(),
            status_code=status_code,
            media_type="text/event-stream",
            headers=headers,
        )

    def _log_json_response(self, response: httpx.Response) -> None:
        """
        Log JSON response content for debugging.

        Args:
            response: API response
        """
        try:
            self.logger.debug(
                f"Response content:\n{json.dumps(response.json(), indent=4, ensure_ascii=False)}"
            )
        except Exception:
            self.logger.debug("Response contains non-JSON content")

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
