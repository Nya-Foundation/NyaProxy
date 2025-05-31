"""
Streaming response handling utilities for NyaProxy.
"""

import asyncio
import traceback
from typing import Dict

import httpx
from loguru import logger
from starlette.responses import StreamingResponse


class StreamingHandler:
    """
    Handles streaming responses
    """

    def __init__(self):
        """
        Initialize the streaming handler.
        """

    async def handle_streaming_response(
        self, httpx_response: httpx.Response
    ) -> StreamingResponse:
        """
        Handle a streaming response (SSE) with industry best practices.

        Args:
            httpx_response: Response from httpx client

        Returns:
            StreamingResponse for FastAPI
        """
        logger.debug(
            f"Handling streaming response with status {httpx_response.status_code}"
        )
        headers = httpx.Headers(httpx_response.headers)
        status_code = httpx_response.status_code
        content_type = httpx_response.headers.get("content-type", "").lower()

        # Process headers for streaming by removing unnecessary ones
        headers = self._prepare_streaming_headers(headers)

        async def event_generator():
            try:
                async for chunk in httpx_response.aiter_bytes():
                    if chunk:
                        logger.debug(f"Forwarding stream chunk: {len(chunk)} bytes")
                        await asyncio.sleep(0.05)  # Yield control to event loop
                        yield chunk
            except Exception as e:
                logger.error(f"Error in streaming response: {str(e)}")
                logger.debug(f"Stream error trace: {traceback.format_exc()}")
            finally:
                if hasattr(httpx_response, "_stream_ctx"):
                    await httpx_response._stream_ctx.__aexit__(None, None, None)

        return StreamingResponse(
            content=event_generator(),
            status_code=status_code,
            media_type=content_type or "application/octet-stream",
            headers=headers,
        )

    def _prepare_streaming_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Prepare headers for streaming responses with SSE best practices.

        Args:
            headers: Headers from the httpx response

        Returns:
            Processed headers for streaming
        """
        if not isinstance(headers, httpx.Headers):
            headers = httpx.Headers(headers)
        # Headers to remove for streaming responses
        headers_to_remove = [
            "content-encoding",
            "content-length",
            "connection",
        ]

        for header in headers_to_remove:
            if header.lower() in headers:
                del headers[header.lower()]

        # Set SSE-specific headers according to standards
        headers["cache-control"] = "no-cache, no-transform"
        headers["connection"] = "keep-alive"
        headers["x-accel-buffering"] = "no"  # Prevent Nginx buffering
        headers["transfer-encoding"] = "chunked"

        return headers

    def detect_streaming_content(
        self, content_type: str, headers: Dict[str, str]
    ) -> bool:
        """
        Determine if response should be treated as streaming based on headers.

        Args:
            content_type: Content type header value
            headers: Response headers

        Returns:
            True if content should be treated as streaming
        """
        stream_content_types = [
            "text/event-stream",
            "application/octet-stream",
            "application/x-ndjson",
            "multipart/x-mixed-replace",
            "video/",
            "audio/",
        ]

        # Check if it's streaming based on headers
        return headers.get("transfer-encoding", "") == "chunked" or any(
            ct in content_type for ct in stream_content_types
        )
