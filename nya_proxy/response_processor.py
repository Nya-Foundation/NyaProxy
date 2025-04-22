"""
Response processing utilities for NyaProxy.
"""

import json
import logging
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import Response
from starlette.responses import JSONResponse, StreamingResponse

from .utils import decode_content


class ResponseProcessor:
    """
    Processes API responses, handling content encoding, streaming, and errors.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the response processor.

        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

    async def process_response(
        self,
        httpx_response: Optional[httpx.Response],
        start_time: float,
        api_name: str,
        api_key: str,
        metrics_collector: Any = None,
    ) -> Response:
        """
        Process an API response.

        Args:
            httpx_response: Response from httpx client
            start_time: Request start time
            api_name: Name of the API
            api_key: API key used for the request
            metrics_collector: Metrics collector (optional)

        Returns:
            Processed response for the client
        """
        # Calculate elapsed time
        elapsed = time.time() - start_time
        status_code = httpx_response.status_code if httpx_response else 502

        self.logger.debug(
            f"Received response from {api_name} with status {status_code} in {elapsed:.2f}s"
        )

        # Record metrics
        if metrics_collector:
            metrics_collector.record_response(api_name, api_key, status_code, elapsed)

        # Handle missing response
        if not httpx_response:
            return JSONResponse(
                status_code=502,
                content={"error": "Bad Gateway: No response from target API"},
            )

        # Filter out unwanted headers
        headers = dict(httpx_response.headers)
        headers_to_remove = ["server", "date", "transfer-encoding"]

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

        # Handle content encoding
        content_encoding = httpx_response.headers.get("content-encoding", "identity")
        headers.pop("content-encoding", None)  # Remove encoding header

        # Decode response body using utility function
        raw_content = decode_content(httpx_response.content, content_encoding)

        # Return response
        return Response(
            content=raw_content,
            status_code=status_code,
            media_type=content_type,
            headers=headers,
        )

    def _handle_streaming_response(
        self, httpx_response: httpx.Response, headers: Dict[str, str], status_code: int
    ) -> StreamingResponse:
        """
        Handle a streaming response (SSE).

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
        headers.pop("transfer-encoding", None)
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
        self.logger.error(f"Error handling request to {api_name}: {str(error)}")

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
