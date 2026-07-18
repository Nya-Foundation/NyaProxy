"""
Streaming response handling utilities for NyaProxy.
"""

import traceback
from collections.abc import Callable
from typing import Awaitable, Optional

import httpx
from loguru import logger
from starlette.responses import StreamingResponse

__all__ = [
    "handle_streaming_response",
    "detect_streaming_content",
]


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

    logger.debug(f"Handling streaming response: {response.status_code} {media_type}, ")
    finalizers = []
    finalized = False

    async def finalize() -> None:
        nonlocal finalized
        if finalized:
            return
        finalized = True
        if hasattr(response, "_stream_ctx") and response._stream_ctx:
            await response._stream_ctx.__aexit__(None, None, None)
            response._stream_ctx = None
        for callback in finalizers:
            result = callback()
            if result is not None:
                await result

    def add_finalizer(
        callback: Callable[[], Optional[Awaitable[None]]],
    ) -> None:
        finalizers.append(callback)

    async def event_generator():
        try:
            async for chunk in response.aiter_raw():
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error(
                f"Error in streaming response: {str(e)}, traceback: {traceback.format_exc()}"
            )
            raise
        finally:
            await finalize()

    streaming = StreamingResponse(
        content=event_generator(),
        status_code=status_code,
        media_type=media_type,
    )
    apply_response_headers(streaming, response.headers, streaming=True)
    streaming._nya_add_finalizer = add_finalizer
    streaming._nya_close = finalize
    return streaming


_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def apply_response_headers(
    response, headers: httpx.Headers, *, streaming: bool
) -> None:
    """
    Prepare headers for streaming responses with SSE best practices.

    Args:
        headers: Headers from the httpx response

    Returns:
        Processed headers for streaming
    """

    connection_tokens = {
        token.strip().lower()
        for token in headers.get("connection", "").split(",")
        if token.strip()
    }
    excluded = _HOP_BY_HOP_HEADERS | connection_tokens
    if streaming:
        excluded.add("content-length")

    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in headers.multi_items()
        if name.lower() not in excluded
    ]
    present = {name for name, _ in raw_headers}

    # Keep Starlette's computed content-type/content-length only when the
    # upstream did not provide an end-to-end value.
    for name, value in response.raw_headers:
        if name not in present and name not in excluded:
            raw_headers.append((name, value))
            present.add(name)

    if streaming:
        if b"cache-control" not in present:
            raw_headers.append((b"cache-control", b"no-cache"))
        if b"x-accel-buffering" not in present:
            raw_headers.append((b"x-accel-buffering", b"no"))

    response.raw_headers = raw_headers


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

    exceptions = ("application/json",)

    media_prefixes = (
        "video/",
        "audio/",
    )
    other_media_cts = {
        "application/vnd.apple.mpegurl",  # .m3u8 (HLS)
        "application/dash+xml",  # .mpd (DASH)
        "application/zip",
        "application/gzip",
        "application/pdf",
    }

    is_media = any(ct.startswith(prefix) for prefix in media_prefixes) or (
        ct in other_media_cts
    )

    if ct in exceptions:
        return False

    if no_length or uses_chunked:
        return True

    if is_media and (uses_chunked or supports_range):
        return True

    return False
