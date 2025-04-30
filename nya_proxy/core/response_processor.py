"""
Response processing utilities for NyaProxy.
"""

import asyncio
import logging
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

import httpx
import orjson
from fastapi import Response
from starlette.responses import JSONResponse, StreamingResponse

from ..common.utils import decode_content, json_safe_dumps
from ..integrations.openai import simulate_stream_from_completion

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
        metrics_collector: Optional["MetricsCollector"] = None,
        load_balancer: Optional[Dict[str, "LoadBalancer"]] = {},
        logger: Optional[logging.Logger] = None,
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
        elapsed = now - r._added_at
        response_time = now - start_time
        status_code = response.status_code if response else 502

        self.logger.debug(
            f"Received response from {api_name} with status {status_code} in {elapsed:.2f}s"
        )

        if self.metrics_collector and r._apply_rate_limit:
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
    ) -> Union[Response, JSONResponse, StreamingResponse]:
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

        # handle streaming responses
        if is_streaming:
            return await self._handle_streaming_response(httpx_response)

        # If non-streaming reeponses
        content_chunks = []

        async for chunk in httpx_response.aiter_bytes():
            content_chunks.append(chunk)
        raw_content = b"".join(content_chunks)

        httpx_response._content = raw_content  # Store raw content in httpx response

        # handle simulated streaming, iof all the following conditions are met:
        # - simulated streaming enabled
        # - user requested it as streaming
        # - content type matches
        if (
            r._is_streaming
            and r._config.simulated_stream_enabled
            and content_type in r._config.apply_to
        ):
            return await self._handle_simulated_streaming(r, httpx_response)

        # Decode content if encoded
        content_encoding = headers.get("content-encoding", "")
        raw_content = decode_content(raw_content, content_encoding)
        headers["content-encoding"] = ""

        # HTML specific handling, rarely used (some user might want this)
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

    # Add base tag to HTML content for relative links
    def add_base_tag(self, html_content: str, original_host: str):
        head_pos = html_content.lower().find("<head>")
        if head_pos > -1:
            head_end = head_pos + 6  # length of '<head>'
            base_tag = f'<base href="{original_host}/">'
            modified_html = html_content[:head_end] + base_tag + html_content[head_end:]
            return modified_html
        return html_content

    async def _handle_streaming_response(
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
        headers = self._handle_streaming_header(headers)

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

    async def _handle_simulated_streaming(
        self, r: "NyaRequest", httpx_response: httpx.Response
    ) -> StreamingResponse:
        """
        Handle simulated streaming responses with chunked data.

        Args:
            r: NyaRequest object containing request data
            httpx_response: Response from httpx client

        Returns:
            StreamingResponse for FastAPI
        """
        headers = dict(httpx_response.headers)
        status_code = httpx_response.status_code

        # Store the full content for simulated streaming
        full_content = httpx_response._content

        # Process headers for simulated streaming
        headers = self._handle_streaming_header(headers)

        # Obtain the original content type
        content_type = headers.get("content-type", "application/octet-stream").lower()

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
        streaming_media_type = None
        for ct in content_type_mapping:
            if ct in content_type:
                streaming_media_type = content_type_mapping[ct]
                break

        # If no specific mapping found, keep the original content type
        if not streaming_media_type:
            streaming_media_type = "text/event-stream"

        self.logger.debug(
            f"Handling simulated streaming response with status {httpx_response.status_code}, remapping content type from {content_type} to {streaming_media_type}"
        )

        delay_seconds = r._config.delay_seconds or 0.2
        chunk_size_bytes = r._config.chunk_size_bytes or 256
        init_delay_seconds = r._config.init_delay_seconds or 0.5

        # Generate a boundary once for multipart responses
        boundary = (
            f"frame-{int(time.time())}"
            if streaming_media_type == "multipart/x-mixed-replace"
            else None
        )

        async def event_generator():
            try:
                await asyncio.sleep(init_delay_seconds)  # Initial delay

                # Special handling for multipart content (images)
                if streaming_media_type.startswith("multipart/x-mixed-replace"):
                    # Support for multiple images if present (e.g., animated GIF or multi-frame)
                    # For now, treat as a single image, but allow for future extension
                    yield f"--{boundary}\r\n".encode("utf-8")
                    yield f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
                    image_data = full_content
                    yield image_data
                    yield f"\r\n--{boundary}--\r\n".encode("utf-8")
                    return

                # For text/event-stream format (JSON, XML, text)
                elif streaming_media_type == "text/event-stream":
                    stream_generator = simulate_stream_from_completion(
                        full_content,
                        chunk_size_bytes=chunk_size_bytes,
                        delay_seconds=delay_seconds,
                        init_delay_seconds=0.0,
                    )

                    async for chunk in stream_generator:
                        self.logger.debug(
                            f"Yielding simulated stream chunk: {len(chunk)} bytes, at {time.time()}s"
                        )
                        yield chunk

            except Exception as e:
                self.logger.error(f"Error in simulated streaming response: {str(e)}")
                self.logger.debug(
                    f"Simulated stream error trace: {traceback.format_exc()}"
                )

        # For multipart responses, add boundary to content type
        if streaming_media_type == "multipart/x-mixed-replace" and boundary:
            streaming_media_type = f"{streaming_media_type}; boundary={boundary}"

        return StreamingResponse(
            content=event_generator(),
            status_code=status_code,
            media_type=streaming_media_type,
            headers=headers,
        )

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
