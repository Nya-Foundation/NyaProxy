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
from loguru import logger
from starlette.responses import JSONResponse, Response, StreamingResponse

from ..common.exceptions import APIKeyExhaustedError
from ..common.models import ProxyRequest
from ..utils.helper import (
    _mask_api_key,
    apply_body_substitutions,
    format_elapsed_time,
    json_safe_dumps,
)

if TYPE_CHECKING:
    from ..config.manager import ConfigManager
    from ..services.key import KeyManager
    from ..services.metrics import MetricsCollector


class RequestExecutor:
    """
    Executes HTTP requests with customizable retry logic.
    """

    def __init__(
        self,
        config: "ConfigManager",
        metrics_collector: Optional["MetricsCollector"] = None,
        key_manager: Optional["KeyManager"] = None,
    ):
        """
        Initialize the request executor.

        Args:
            config: Configuration manager instance
            metrics_collector: Metrics collector (optional)
            key_manager: Key manager instance (optional)
        """
        self.config = config
        self.metrics_collector = metrics_collector
        self.key_manager = key_manager
        self.client = self._setup_client()
        self.response_processor = None  # Will be registered later

    def _setup_client(self) -> httpx.AsyncClient:
        """
        Set up the HTTP client with appropriate configuration.

        Returns:
            Configured HTTPX AsyncClient
        """
        proxy_enabled = self.config.get_proxy_enabled()
        proxy_address = self.config.get_proxy_address()
        proxy_timeout = self.config.get_default_timeout()

        # Create a composite timeout object with different phases
        timeout = httpx.Timeout(
            connect=5.0,  # Connection timeout
            read=proxy_timeout * 0.95,  # Read timeout
            write=min(60.0, proxy_timeout * 0.2),  # Write timeout
            pool=10.0,  # Pool timeout
        )

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
                logger.info(f"Using SOCKS proxy: {proxy_address}")
            else:
                # For HTTP/HTTPS proxies
                client_kwargs["proxies"] = proxy_address
                logger.info(f"Using HTTP(S) proxy: {proxy_address}")

        return httpx.AsyncClient(**client_kwargs)

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()

    def _calculate_timeout(self, api_name: Optional[str] = None) -> httpx.Timeout:
        """
        Calculate the timeout settings for the request based on API configuration.

        Args:
            api_name: Name of the API to get specific timeout settings

        Returns:
            httpx.Timeout object with connect, read, write, and pool timeouts
        """
        # Get the base timeout value from config
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

    async def execute_request(
        self, r: ProxyRequest
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Execute a single request to the target API.

        Args:
            r: ProxyRequest object with request details

        Returns:
            Response object from the HTTPX client, which can be a JSONResponse,
            StreamingResponse, or a regular Response based on the request type.
        """
        api_name = r.api_name
        key_id = _mask_api_key(r.api_key)
        start_time = time.time()

        logger.debug(
            f"Executing request to {r.url} with key_id {key_id} (attempt {r._attempts})"
        )

        # Process the request body before sending
        self._preprocess_request_body(r)

        # Record request metrics
        if self.metrics_collector and r._apply_rate_limit:
            self.metrics_collector.record_request(api_name, r.api_key)

        try:
            # Get API-specific timeout
            timeout = self._calculate_timeout(api_name)

            # Execute the HTTP request
            httpx_response = await self._execute_http_request(r, timeout)

            # Process the response using the response processor
            if self.response_processor:
                endpoint = self.config.get_api_endpoint(api_name)
                return await self.response_processor.process_response(
                    r, httpx_response, start_time, endpoint
                )
            else:
                return self._create_error_response(
                    r,
                    Exception("Response processor not configured"),
                    "configuration error",
                    500,
                    start_time,
                )

        except httpx.ReadError as e:
            return self._create_error_response(r, e, "read error", 502, start_time)
        except httpx.ConnectError as e:
            return self._create_error_response(
                r, e, "connection error", 502, start_time
            )
        except httpx.TimeoutException as e:
            return self._create_error_response(r, e, "timeout", 504, start_time)
        except Exception as e:
            return self._create_error_response(
                r, e, "unexpected error", 500, start_time
            )

    async def _execute_http_request(
        self, r: ProxyRequest, timeout: httpx.Timeout
    ) -> httpx.Response:
        """
        Execute the actual HTTP request with proper error handling.

        Args:
            r: ProxyRequest object
            timeout: httpx.Timeout object

        Returns:
            httpx.Response object

        Raises:
            Various httpx exceptions if request fails
        """
        # Log request details at debug level
        logger.debug(f"Request Content:\n{json_safe_dumps(r.content)}")
        logger.debug(f"Request Headers:\n{json_safe_dumps(r.headers)}")

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

        return httpx_response

    def _preprocess_request_body(self, r: ProxyRequest) -> None:
        """
        Preprocess the request body, applying substitutions and streaming settings.

        Args:
            r: ProxyRequest object
        """
        # Apply request body substitutions
        self._apply_body_substitutions(r)

    def _apply_body_substitutions(self, r: ProxyRequest) -> None:
        """
        Apply configured body substitutions to the request.

        Args:
            r: ProxyRequest object
        """
        content_type = r.headers.get("content-type", "").lower()

        if "application/json" not in content_type:
            return

        # Apply request body substitution rules
        if r._config.req_body_subst_enabled and r._config.subst_rules:
            try:
                modified_content = apply_body_substitutions(
                    r.content, r._config.subst_rules
                )
                r.content = orjson.dumps(modified_content)
                logger.debug(f"Request body substitutions applied successfully")
            except Exception as e:
                logger.warning(f"Error applying body substitutions: {str(e)}")

    def _create_error_response(
        self,
        request: ProxyRequest,
        error: Exception,
        error_type: str,
        status_code: int,
        start_time: float,
        extra_details: Optional[str] = None,
    ) -> JSONResponse:
        """
        Create a standardized error response.

        Args:
            request: ProxyRequest object
            error: Exception that occurred
            error_type: Type of error (connection, timeout, etc.)
            status_code: HTTP status code to return
            start_time: When the request started
            extra_details: Optional additional details

        Returns:
            JSONResponse with error details
        """
        elapsed = time.time() - start_time

        # Add more details for ReadError since it's common
        if isinstance(error, httpx.ReadError):
            error_msg = (
                str(error) if str(error) else "Connection closed while reading response"
            )
            logger.error(
                f"{error_type.capitalize()} to {request.url}: {error_msg} after {format_elapsed_time(elapsed)}"
            )
        else:
            logger.error(
                f"{error_type.capitalize()} to {request.url}: {str(error)} after {format_elapsed_time(elapsed)}"
            )

        logger.debug(traceback.format_exc())

        # Record error metrics if available
        if (
            self.metrics_collector
            and request._apply_rate_limit
            and hasattr(request, "api_key")
        ):
            self.metrics_collector.record_response(
                request.api_name, request.api_key, status_code, elapsed
            )

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
        r: ProxyRequest,
        max_attempts: int = 3,
        retry_delay: float = 10.0,
    ) -> Union[Response, JSONResponse, StreamingResponse]:
        """
        Execute a request with retry logic based on configured strategy.

        Args:
            r: ProxyRequest object with request details
            max_attempts: Maximum number of retry attempts
            retry_delay: Base delay in seconds between retries

        Returns:
            Response object (JSONResponse, StreamingResponse, or regular Response)
        """
        # Skip retry logic if method is not configured for retries
        if not self._validate_retry_request_methods(r.api_name, r.method):
            logger.debug(
                f"Skipping retry logic for {r.api_name}, {r.method} was not configured for retries."
            )
            return await self.execute_request(r)

        # Get retry status codes from API config
        retry_status_codes = self.config.get_api_retry_status_codes(r.api_name)

        # Get retry mode from API config
        retry_mode = self.config.get_api_retry_mode(r.api_name)

        # Execute request with retries
        current_delay = retry_delay
        res = None

        for attempt in range(1, max_attempts + 1):
            r._attempts = attempt

            # Use key rotation strategy if configured
            if retry_mode == "key_rotation" and attempt > 1:
                await self._rotate_api_key(r)

            # Execute the request
            res = await self.execute_request(r)

            # Check if the request succeeded or should be retried
            if res and 200 <= res.status_code < 300:
                logger.debug(
                    f"Request to {r.api_name} succeeded on attempt {attempt} with status {res.status_code}"
                )
                break

            # Verify if we should retry based on the response status
            if not self._should_retry(res, retry_status_codes):
                break

            # If this was the last attempt, don't wait
            if attempt >= max_attempts:
                logger.warning(
                    f"Max retry attempts ({max_attempts}) reached for {r.api_name}"
                )
                break

            # Calculate delay for next attempt
            next_delay = self._calculate_retry_delay(
                res, current_delay, retry_mode, retry_delay, attempt
            )

            # Mark the current key as rate limited for unsuccessful attempts
            if self.key_manager and hasattr(r, "api_key"):
                self.key_manager.mark_key_rate_limited(
                    r.api_name, r.api_key, next_delay
                )

            logger.info(
                f"Retrying request to {r.api_name} in {next_delay:.1f}s "
                f"(attempt {attempt}/{max_attempts}, status {res.status_code if res else 'no response'})"
            )

            # Wait before retry
            await asyncio.sleep(next_delay)
            current_delay = next_delay

        return res

    async def _rotate_api_key(self, r: ProxyRequest) -> None:
        """
        Rotate the API key for a request during retry.

        Args:
            r: ProxyRequest object

        Returns:
            None - the request object is updated in place
        """
        if not self.key_manager:
            return

        try:
            key = await self.key_manager.get_available_key(
                r.api_name, r._apply_rate_limit
            )
            logger.info(
                f"Rotating API key for {r.api_name} from {_mask_api_key(r.api_key)} to {_mask_api_key(key)}"
            )
            r.api_key = key
        except APIKeyExhaustedError as e:
            logger.error(
                f"API key exhausted for {r.api_name}, will use the same key for this attempt: {str(e)}"
            )

    def _validate_retry_request_methods(self, api_name: str, method: str) -> bool:
        """
        Validate if an HTTP method should use retry logic.

        Args:
            api_name: Name of the API
            method: HTTP method (GET, POST, etc.)

        Returns:
            True if method should be retried, False otherwise
        """
        retry_methods = self.config.get_api_retry_request_methods(api_name)
        return method.upper() in retry_methods

    def _should_retry(
        self, response: Optional[Response], retry_status_codes: List[int]
    ) -> bool:
        """
        Determine if a request should be retried based on the response.

        Args:
            response: FastAPI/Starlette response or None
            retry_status_codes: List of status codes that should trigger a retry

        Returns:
            True if request should be retried, False otherwise
        """
        # Retry if no response or connection error
        if response is None:
            return True

        # Retry if status code is in retry list
        if (
            hasattr(response, "status_code")
            and response.status_code in retry_status_codes
        ):
            return True

        return False

    def _calculate_retry_delay(
        self,
        response: Optional[Response],
        current_delay: float,
        retry_mode: str,
        base_delay: float,
        attempt: int,
    ) -> float:
        """
        Calculate the delay before next retry attempt.

        Args:
            response: FastAPI/Starlette response object
            current_delay: Current delay in seconds
            retry_mode: Retry mode (default, backoff, key_rotation)
            base_delay: Base delay in seconds
            attempt: Current attempt number

        Returns:
            Delay in seconds for next retry
        """
        # Check for Retry-After header in response
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
            return base_delay
        else:
            # Default linear strategy
            return current_delay

    def _get_retry_after(self, response: Optional[Response]) -> Optional[float]:
        """
        Extract Retry-After header value from response.

        Args:
            response: FastAPI/Starlette response object

        Returns:
            Delay in seconds or None if not present
        """
        if not response or not hasattr(response, "headers"):
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
                logger.debug(f"Could not parse Retry-After header: {retry_after}")
                return None
