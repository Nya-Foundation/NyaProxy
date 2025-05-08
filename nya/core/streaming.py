"""
Streaming response handling utilities for NyaProxy.
"""

import asyncio
import logging
import time
import traceback
from typing import TYPE_CHECKING, Dict, Optional

import httpx
from starlette.responses import StreamingResponse

from ..integrations.openai import simulate_stream_from_chat_completion

if TYPE_CHECKING:
    from ..common.models import NyaRequest


class StreamingHandler:
    """
    Handles streaming responses, including both real and simulated streaming.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the streaming handler.

        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

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
        self.logger.debug(
            f"Handling streaming response with status {httpx_response.status_code}"
        )
        headers = dict(httpx_response.headers)
        status_code = httpx_response.status_code
        content_type = httpx_response.headers.get("content-type", "").lower()

        # Process headers for streaming by removing unnecessary ones
        headers = self._prepare_streaming_headers(headers)

        async def event_generator():
            try:
                async for chunk in httpx_response.aiter_bytes():
                    if chunk:
                        self.logger.debug(
                            f"Forwarding stream chunk: {len(chunk)} bytes"
                        )
                        await asyncio.sleep(0.05)  # Yield control to event loop
                        yield chunk
            except Exception as e:
                self.logger.error(f"Error in streaming response: {str(e)}")
                self.logger.debug(f"Stream error trace: {traceback.format_exc()}")
            finally:
                if hasattr(httpx_response, "_stream_ctx"):
                    await httpx_response._stream_ctx.__aexit__(None, None, None)

        return StreamingResponse(
            content=event_generator(),
            status_code=status_code,
            media_type=content_type or "application/octet-stream",
            headers=headers,
        )

    async def handle_simulated_streaming(
        self, request: "NyaRequest", httpx_response: httpx.Response
    ) -> StreamingResponse:
        """
        Handle simulated streaming responses with chunked data.

        Args:
            request: NyaRequest object containing request data
            httpx_response: Response from httpx client

        Returns:
            StreamingResponse for FastAPI
        """
        headers = dict(httpx_response.headers)
        status_code = httpx_response.status_code

        # Store the full content for simulated streaming
        full_content = httpx_response._content

        # Process headers for simulated streaming
        headers = self._prepare_streaming_headers(headers)

        # Obtain the original content type
        content_type = headers.get("content-type", "application/octet-stream").lower()

        # Get appropriate streaming media type
        streaming_media_type = self._determine_streaming_media_type(content_type)

        self.logger.debug(
            f"Handling simulated streaming response with status {httpx_response.status_code}, "
            f"remapping content type from {content_type} to {streaming_media_type}"
        )

        # Get streaming configuration
        delay_seconds = request._config.delay_seconds or 0.2
        chunk_size_bytes = request._config.chunk_size_bytes or 256
        init_delay_seconds = request._config.init_delay_seconds or 0.5

        # Generate a boundary once for multipart responses
        boundary = (
            f"frame-{int(time.time())}"
            if streaming_media_type == "multipart/x-mixed-replace"
            else None
        )

        # Create event generator based on content type
        generator_fn = (
            self._create_multipart_generator
            if streaming_media_type.startswith("multipart")
            else self._create_sse_generator
        )

        event_generator = generator_fn(
            full_content=full_content,
            content_type=content_type,
            boundary=boundary,
            delay_seconds=delay_seconds,
            chunk_size_bytes=chunk_size_bytes,
            init_delay_seconds=init_delay_seconds,
        )

        # For multipart responses, add boundary to content type
        if streaming_media_type == "multipart/x-mixed-replace" and boundary:
            streaming_media_type = f"{streaming_media_type}; boundary={boundary}"

        return StreamingResponse(
            content=event_generator,
            status_code=status_code,
            media_type=streaming_media_type,
            headers=headers,
        )

    async def _create_multipart_generator(
        self, full_content, content_type, boundary, **kwargs
    ):
        """Create a generator for multipart content (images, etc.)."""
        try:
            await asyncio.sleep(kwargs.get("init_delay_seconds", 0.5))
            yield f"--{boundary}\r\n".encode("utf-8")
            yield f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
            yield full_content
            yield f"\r\n--{boundary}--\r\n".encode("utf-8")
        except Exception as e:
            self.logger.error(f"Error in multipart streaming: {str(e)}")
            self.logger.debug(f"Multipart stream error trace: {traceback.format_exc()}")

    async def _create_sse_generator(self, full_content, **kwargs):
        """Create a generator for Server-Sent Events."""
        try:
            await asyncio.sleep(kwargs.get("init_delay_seconds", 0.5))
            stream_generator = simulate_stream_from_chat_completion(
                full_content,
                chunk_size_bytes=kwargs.get("chunk_size_bytes", 256),
                delay_seconds=kwargs.get("delay_seconds", 0.2),
                init_delay_seconds=0.0,
            )

            async for chunk in stream_generator:
                self.logger.debug(
                    f"Yielding simulated stream chunk: {len(chunk)} bytes, at {time.time()}s"
                )
                yield chunk
        except Exception as e:
            self.logger.error(f"Error in SSE streaming: {str(e)}")
            self.logger.debug(f"SSE stream error trace: {traceback.format_exc()}")

    def _prepare_streaming_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Prepare headers for streaming responses with SSE best practices.

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

    def _determine_streaming_media_type(self, content_type: str) -> str:
        """
        Determine appropriate streaming media type based on content type.

        Args:
            content_type: Original content type

        Returns:
            Appropriate streaming media type
        """
        # Map content types to appropriate streaming media types
        content_type_mapping = {
            "application/json": "text/event-stream",
            "application/xml": "text/event-stream",
            "text/plain": "text/event-stream",
            "application/x-ndjson": "application/x-ndjson",
            "image/png": "multipart/x-mixed-replace",
            "image/jpeg": "multipart/x-mixed-replace",
            "image/gif": "multipart/x-mixed-replace",
            "image/webp": "multipart/x-mixed-replace",
        }

        # Get appropriate streaming media type or default to the original if not in mapping
        for ct in content_type_mapping:
            if ct in content_type:
                return content_type_mapping[ct]

        # If no specific mapping found, use text/event-stream as default
        return "text/event-stream"

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
