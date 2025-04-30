"""
Request execution with retry logic.
"""

import asyncio
import logging
import random
import time
import traceback
from typing import TYPE_CHECKING, List, Optional, Union

import httpx
import orjson
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..common.exceptions import APIKeyExhaustedError
from ..common.models import NyaRequest
from ..common.utils import (
    _mask_api_key,
    apply_body_substitutions,
    format_elapsed_time,
    json_safe_dumps,
)

if TYPE_CHECKING:
    from ..server.config import ConfigManager
    from ..services.key_manager import KeyManager
    from ..services.metrics import MetricsCollector
    from .response_processor import ResponseProcessor


class RequestExecutor:
    """
    Executes HTTP requests with customizable retry logic.
    """

    def __init__(
        self,
        config: "ConfigManager",
        metrics_collector: Optional["MetricsCollector"] = None,
        key_manager: Optional["KeyManager"] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the request executor.

        Args:
            client: HTTPX client for making requests
            config: Configuration manager instance
            metrics_collector: Metrics collector (optional)
            logger: Logger instance (optional)
        """
        self.config = config
        self.client = self._setup_client()
        self.logger = logger or logging.getLogger(__name__)
        self.metrics_collector = metrics_collector
        self.key_manager = key_manager

    def _setup_client(self) -> httpx.AsyncClient:
        """Set up the HTTP client with appropriate configuration."""
        proxy_enabled = self.config.get_proxy_enabled()
        proxy_address = self.config.get_proxy_address()
        proxy_timeout = self.config.get_default_timeout()

        # Create a composite timeout object with different phases
        timeout = self._calculate_timeout()

        # Configure client with appropriate settings
        client_kwargs = {
            "follow_redirects": True,
            "timeout": timeout,
            "limits": httpx.Limits(
                max_connections=2000,
                max_keepalive_connections=500,
                keepalive_expiry=min(120.0, proxy_timeout),
            ),
        }

        if proxy_enabled and proxy_address:
            if proxy_address.startswith("socks5://") or proxy_address.startswith(
                "socks4://"
            ):
                # For SOCKS proxies
                from httpx_socks import AsyncProxyTransport

                transport = AsyncProxyTransport.from_url(proxy_address)
                client_kwargs["transport"] = transport
                self.logger.info(f"Using SOCKS proxy: {proxy_address}")
            else:
                # For HTTP/HTTPS proxies
                client_kwargs["proxies"] = proxy_address
                self.logger.info(f"Using HTTP(S) proxy: {proxy_address}")

        return httpx.AsyncClient(**client_kwargs)

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()

    def _process_request_body_similated_streaming(self, r: NyaRequest) -> None:
        """
        Process the request body for simulated streaming, OpenAI-compatable API support.

        Args:
            r: NyaRequest object with request details
        """
        content_type = r.headers.get("content-type", "").lower()

        if "application/json" not in content_type:
            return

        # Apply simulated streaming rules
        if r._config.simulated_stream_enabled and r._config.apply_to:
            if not any(ct in content_type for ct in r._config.apply_to):
                return

            try:
                if isinstance(r.content, bytes):
                    data = orjson.loads(r.content)
                    if "stream" not in data or data["stream"] is not True:
                        return

                    # mark the original request as streaming
                    r._is_streaming = True

                    # patch the request body to disable streaming
                    del data["stream"]
                    r.content = orjson.dumps(data)

                    self.logger.debug(
                        f"Simulated streaming patch applied to request body"
                    )
            except (orjson.JSONDecodeError, TypeError):
                self.logger.debug(
                    f"Could not parse request body as JSON for stream simulation {str(r.content)}, skipping patching"
                )

    def _calculate_timeout(self, api_name: Optional[str] = None) -> httpx.Timeout:
        """
        Calculate the timeout settings for the request based on API configuration.
        Args:
            api_name: Name of the API to get specific timeout settings
        Returns:
            httpx.Timeout object with connect, read, write, and pool timeouts
        """

        api_timeout = (
            self.config.get_api_default_timeout(api_name)
            if api_name
            else self.config.get_default_timeout()
        )

        return httpx.Timeout(
            connect=5,  # Connection timeout
            read=api_timeout * 0.95,  # Read timeout
            write=min(60.0, api_timeout * 0.2),  # Write timeout
            pool=10.0,  # Pool timeout
        )

    def _process_request_body_subst(self, r: NyaRequest) -> None:
        """
        Process the request body for variable substitution.

        Args:
            r: NyaRequest object with request details
        """

        content_type = r.headers.get("content-type", "").lower()

        if "application/json" not in content_type:
            return

        # apply request body substitutions rules
        if r._config.req_body_subst_enabled and r._config.subst_rules:
            modified_content = apply_body_substitutions(
                r.content, r._config.subst_rules
            )

            self.logger.debug(
                f"Request body substitutions have been applied: {modified_content}"
            )
            r.content = orjson.dumps(modified_content)

    async def execute_request(
        self, r: NyaRequest
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Execute a single request to the target API.

        Args:
            r: NyaRequest object with request details

        Returns:
            Response object from the HTTPX client, which can be a JSONResponse,
            StreamingResponse, or a regular Response based on the request type.
        """
        api_name = r.api_name
        key_id = _mask_api_key(r.api_key)
        start_time = time.time()

        self.logger.debug(
            f"Executing request to {r.url} with key_id {key_id} (attempt {r._attempts})"
        )

        # Record request metrics
        if self.metrics_collector and r._apply_rate_limit:
            self.metrics_collector.record_request(api_name, r.api_key)

        try:
            endpoint = self.config.get_api_endpoint(api_name)

            # Request Body Substitution
            self._process_request_body_subst(r)
            # Patch Simulated Streaming
            self._process_request_body_similated_streaming(r)

            # Log request details
            self.logger.debug(f"Request Content:\n{json_safe_dumps(r.content)}")
            self.logger.debug(f"Request Header\n: {json_safe_dumps(r.headers)}")

            timeout = self._calculate_timeout(api_name)

            # Send the request and handle stream-specific errors
            stream = self.client.stream(
                method=r.method,
                url=r.url,
                headers=r.headers,
                content=r.content,
                timeout=timeout,
            )

            httpx_response = await stream.__aenter__()
            httpx_response._stream_ctx = stream

            # Process the response immediately after getting the connectio
            res = await self.response_processor.process_response(
                r, httpx_response, start_time, endpoint
            )

            elapsed = time.time() - start_time
            self.logger.debug(
                f"Response from {r.url}: status={httpx_response.status_code}, time={format_elapsed_time(elapsed)}"
            )
            return res

        except httpx.ReadError as e:
            return self._handle_request_error(r, e, "read error", 502, start_time)
        except httpx.ConnectError as e:
            return self._handle_request_error(r, e, "connection error", 502, start_time)
        except httpx.TimeoutException as e:
            return self._handle_request_error(r, e, "timeout", 504, start_time)
        except Exception as e:
            return self._handle_request_error(r, e, "unexpected error", 500, start_time)

    def regiser_response_processor(self, processor: "ResponseProcessor") -> None:
        """
        Register a response processor to handle responses after execution.

        Args:
            processor: ResponseProcessor instance
        """
        self.response_processor: "ResponseProcessor" = processor
        self.logger.debug(
            f"Response processor {processor.__class__.__name__} registered."
        )

    def _handle_request_error(
        self,
        request: NyaRequest,
        error: Exception,
        error_type: str,
        status_code: int,
        start_time: float,
        extra_details: Optional[str] = None,
    ) -> JSONResponse:
        """
        Handle request errors uniformly.

        Args:
            r: NyaRequest object
            error: Exception that occurred
            error_type: Type of error (connection, timeout, etc.)
            status_code: Status code to record (0 for errors)
            start_time: When the request execution started, excluding the time taken for retries and inside the request queue
            extra_details: Additional details about the error
        """
        elapsed = time.time() - start_time

        # Add more details for ReadError
        if isinstance(error, httpx.ReadError):
            error_msg = (
                str(error) if str(error) else "Connection closed while reading response"
            )
            self.logger.error(
                f"{error_type.capitalize()} to {request.url}: {error_msg} after {format_elapsed_time(elapsed)}"
            )
        else:
            self.logger.error(
                f"{error_type.capitalize()} to {request.url}: {str(error)} after {format_elapsed_time(elapsed)}"
            )

        self.logger.debug(traceback.format_exc())

        return JSONResponse(
            status_code=status_code,
            content={
                "error": f"{error_type.capitalize()} occurred while processing request",
                "details": str(error),
                "elapsed": format_elapsed_time(elapsed),
                "extra_details": extra_details,
            },
        )

    async def execute_with_retry(
        self,
        r: NyaRequest,
        max_attempts: int = 3,
        retry_delay: float = 10.0,
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Execute a request with retry logic.

        Args:
            r: NyaRequest object with request details
            max_attempts: Maximum number of retry attempts
            retry_delay: Base delay in seconds between retries


        Returns:
            HTTPX response or None if all attempts failed
        """
        # Skip retry logic if method is not configured for retries
        if not self._validate_retry_request_methods(r.api_name, r.method):
            self.logger.debug(
                f"Ignore retry logic for {r.api_name}, {r.method} was not configured for retries."
            )
            return await self.execute_request(r)

        # Get retry status codes from API config or default
        retry_status_codes = self.config.get_api_retry_status_codes(r.api_name)

        # Get retry mode from API config, expecting 'default', 'backoff', or 'key_rotation'
        retry_mode = self.config.get_api_retry_mode(r.api_name)

        # Execute request with retries
        res = None
        current_delay = retry_delay

        for attempt in range(1, max_attempts + 1):
            r._attempts = attempt

            # Rotating api key if needed
            if retry_mode == "key_rotation" and r._attempts > 1:
                try:
                    r.api_key = await self.key_manager.get_available_key(
                        r.api_name, r._apply_rate_limit
                    )
                except APIKeyExhaustedError as e:
                    self.logger.error(
                        f"API key exhausted for {r.api_name}, will use the same key for this attempt: {str(e)}"
                    )
                    pass

            # Execute the request
            res = await self.execute_request(r)

            # If we got a successful response, break out of the loop
            if res and 200 <= res.status_code < 300:
                self.logger.info(
                    f"Request to {r.api_name} succeeded on attempt {r._attempts} with status {res.status_code}"
                )
                break

            # Skip retry logic if response status code is not configured for retries
            if not self._should_retry(res, retry_status_codes):
                break

            # Else, start retry logic, and calculate next delay
            next_delay = self._calculate_retry_delay(
                res, current_delay, retry_mode, retry_delay, r._attempts
            )

            # mark the current key as rate limited for unsuccessful attempts
            self.key_manager.mark_key_rate_limited(r.api_name, r.api_key, next_delay)

            # If this was our last attempt, don't wait
            if r._attempts >= max_attempts:
                self.logger.warning(
                    f"Max retry attempts ({max_attempts}) reached for {r.api_name}"
                )
                break

            self.logger.info(
                f"Retrying request to {r.api_name} in {next_delay:.1f}s "
                f"(attempt {r._attempts}/{max_attempts}, status {res.status_code if res else 'no response'})"
            )

            # Wait before retry
            await asyncio.sleep(next_delay)
            current_delay = next_delay

        return res

    def _validate_retry_request_methods(self, api_name: str, method: str) -> bool:
        """
        Determine if an HTTP method should be retried.

        Args:
            api_name: Name of the API (for logging)
            method: HTTP method (GET, POST, etc.)

        Returns:
            True if method needs retry logic, False otherwise
        """

        retry_methods = self.config.get_api_retry_request_methods(api_name)

        # request methods specified in config should provide retry logic
        if method.upper() in retry_methods:
            return True

        return False

    def _should_retry(
        self, response: Optional[httpx.Response], retry_status_codes: List[int]
    ) -> bool:
        """
        Determine if a request should be retried based on the response.

        Args:
            response: HTTPX response or None
            retry_status_codes: List of status codes that should trigger a retry

        Returns:
            True if request should be retried
        """
        # Retry if no response (connection error)
        if response is None:
            return True

        # Retry if status code is in retry list
        if response.status_code in retry_status_codes:
            return True

        return False

    def _calculate_retry_delay(
        self,
        response: Optional[httpx.Response],
        current_delay: float,
        retry_mode: str,
        retry_delay: float,
        attempt: int,
    ) -> float:
        """
        Calculate delay for next retry attempt.

        Args:
            response: HTTPX response
            current_delay: Current delay in seconds
            retry_mode: Retry mode (default, backoff, key_rotation)
            retry_delay: Base delay in seconds for retries
            attempt: Current attempt number

        Returns:
            Delay in seconds for next retry
        """
        # Check for Retry-After header
        retry_after = self._get_retry_after(response)
        if retry_after:
            return retry_after

        # Apply different retry strategies based on mode
        if retry_mode == "backoff":
            # Exponential backoff with jitter
            jitter = random.uniform(0.75, 1.25)
            return current_delay * (1.5 ** (attempt - 1)) * jitter
        elif retry_mode == "key_rotation":
            # Minimal delay for key rotation strategy
            return retry_delay
        else:
            # Default linear strategy
            return current_delay

    def _get_retry_after(self, response: Optional[httpx.Response]) -> Optional[float]:
        """
        Extract Retry-After header value from response.

        Args:
            response: HTTPX response

        Returns:
            Delay in seconds or None if not present
        """
        if not response:
            return None

        # Check for Retry-After header
        retry_after = response.headers.get("Retry-After")
        if not retry_after:
            return None

        try:
            # Parse as integer seconds
            return float(retry_after)
        except ValueError:
            try:
                # Try to parse as HTTP date format
                from datetime import datetime
                from email.utils import parsedate_to_datetime

                retry_date = parsedate_to_datetime(retry_after)
                delta = retry_date - datetime.now(retry_date.tzinfo)
                return max(0.1, delta.total_seconds())
            except Exception:
                self.logger.debug(f"Could not parse Retry-After header: {retry_after}")
                return None
