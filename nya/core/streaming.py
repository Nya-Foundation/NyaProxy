"""
Streaming response handling utilities for NyaProxy.
"""

import traceback

import httpx
from loguru import logger
from starlette.responses import StreamingResponse


class StreamingHandler:
    """
    Utility class for handling streaming responses in NyaProxy.
    """

    @staticmethod
    async def handle_streaming_response(response: httpx.Response) -> StreamingResponse:
        """
        Handle a streaming response (SSE)

        Args:
            httpx_response: Response from httpx client

        Returns:
            StreamingResponse for FastAPI
        """

        status_code = response.status_code
        content_type = response.headers.get("content-type", "")
        media_type = (
            content_type.split(";")[0].strip().lower()
            if content_type
            else "application/octet-stream"
        )

        logger.debug(
            f"Handling streaming response: {response.status_code} {media_type}, "
        )
        # Process headers for streaming by removing unnecessary ones
        StreamingHandler._prepare_streaming_headers(response.headers)

        async def event_generator():
            try:
                async for chunk in response.aiter_bytes():
                    if chunk:
                        logger.debug(f"Forwarding stream chunk: {len(chunk)} bytes")
                        yield chunk
            except Exception as e:
                logger.error(
                    f"Error in streaming response: {str(e)}, traceback: {traceback.format_exc()}"
                )
            finally:
                if hasattr(response, "_stream_ctx") and response._stream_ctx:
                    await response._stream_ctx.__aexit__(None, None, None)
                    response._stream_ctx = None

        return StreamingResponse(
            content=event_generator(),
            status_code=status_code,
            media_type=media_type,
            headers=response.headers,
        )

    @staticmethod
    def _prepare_streaming_headers(headers: httpx.Headers) -> None:
        """
        Prepare headers for streaming responses with SSE best practices.

        Args:
            headers: Headers from the httpx response

        Returns:
            Processed headers for streaming
        """

        for header in ["content-encoding", "content-length", "accept-encoding"]:
            if header in headers:
                del headers[header]

        # Set SSE-specific headers according to standards
        headers["cache-control"] = "no-cache, no-transform"
        headers["connection"] = "keep-alive"
        headers["x-accel-buffering"] = "no"
        headers["transfer-encoding"] = "chunked"

    @staticmethod
    def detect_streaming_content(headers: httpx.Headers) -> bool:
        """
        Determine if a response should be treated as streaming (i.e.,
        processed chunk-by-chunk rather than buffered to completion).
        """
        # 1. Normalize header values
        te = headers.get("transfer-encoding", "").lower()
        cl = headers.get("content-length")
        ar = headers.get("accept-ranges", "").lower()

        ct_full = headers.get("content-type", "").lower()
        ct: str = ct_full.split(";")[0].strip()

        uses_chunked = "chunked" in te
        no_length = cl is None
        supports_range = "bytes" in ar

        sse_cts = {
            "text/event-stream",
            "application/x-ndjson",
            "multipart/x-mixed-replace",
        }

        media_prefixes = ("video/", "audio/")
        other_media_cts = {
            "application/vnd.apple.mpegurl",  # .m3u8 (HLS)
            "application/dash+xml",  # .mpd (DASH)
        }

        is_sse = ct in sse_cts
        is_media = any(ct.startswith(prefix) for prefix in media_prefixes) or (
            ct in other_media_cts
        )

        if uses_chunked and is_sse:
            return True

        if is_media and (uses_chunked or supports_range or no_length):
            return True

        return False
