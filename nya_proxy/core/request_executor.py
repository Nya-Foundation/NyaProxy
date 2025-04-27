"""
Request execution with retry logic.
"""

import asyncio
import json
import logging
import random
import time
import traceback
from typing import TYPE_CHECKING, List, Optional

import httpx
from starlette.responses import JSONResponse

from ..common.exceptions import APIKeyExhaustedError
from ..common.models import NyaRequest
from ..common.utils import _mask_api_key, format_elapsed_time, json_safe_dumps

if TYPE_CHECKING:
    from ..server.config import ConfigManager
    from ..services.key_manager import KeyManager
    from ..services.metrics import MetricsCollector


class RequestExecutor:
    """
    Executes HTTP requests with customizable retry logic.
    """

    def __init__(
        self,
        config: "ConfigManager",
        logger: Optional[logging.Logger] = None,
        metrics_collector: Optional["MetricsCollector"] = None,
        key_manager: Optional["KeyManager"] = None,
    ):
        """
        Initialize the request executor.

        Args:
            client: HTTPX client for making requests
            config: Configuration manager instance
            logger: Logger instance
            metrics_collector: Metrics collector (optional)
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

        # Configure client with appropriate settings
        client_kwargs = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(60.0),  # Default timeout of 60 seconds
        }

        if proxy_enabled and proxy_address:
            client_kwargs["proxies"] = proxy_address
            self.logger.info(f"Using proxy: {proxy_address}")

        return httpx.AsyncClient(**client_kwargs)

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()

    async def execute_request(self, r: NyaRequest) -> Optional[httpx.Response]:
        """
        Execute a single request to the target API.

        Args:
            r: NyaRequest object with request details

        Returns:
            HTTPX response or None if request failed
        """
        api_name = r.api_name
        key_id = _mask_api_key(r.api_key)
        start_time = time.time()

        self.logger.debug(
            f"Executing request to {r.url} with key_id {key_id} (attempt {r.attempts})"
        )

        # Record request metrics
        if self.metrics_collector and r.apply_rate_limit:
            self.metrics_collector.record_request(api_name, r.api_key)

        try:
            # Get timeout from configuration
            timeout_secs = self.config.get_api_default_timeout(api_name)

            # Create a composite timeout object
            timeout = httpx.Timeout(
                connect=timeout_secs,  # Connection timeout
                read=timeout_secs,  # Read timeout
                write=timeout_secs,  # Write timeout
                pool=timeout_secs,  # Pool timeout
            )

            self.logger.debug(f"Request Content:\n{json_safe_dumps(r.content)}")
            self.logger.debug(f"Request Header\n: {json_safe_dumps(r.headers)}")

            # Send the request
            stream = self.client.stream(
                method=r.method,
                url=r.url,
                headers=r.headers,
                content=r.content,
                timeout=timeout,
            )
            response = await stream.__aenter__()
            response._stream_ctx = stream
            elapsed = time.time() - start_time
            self.logger.debug(
                f"Response from {r.url}: status={response.status_code}, time={format_elapsed_time(elapsed)}"
            )
            return response

        except httpx.ConnectError as e:
            return self._handle_request_error(r, e, "connection error", 502, start_time)
        except httpx.TimeoutException as e:
            return self._handle_request_error(r, e, "timeout", 504, start_time)
        except Exception as e:
            return self._handle_request_error(r, e, "unexpected error", 500, start_time)

    def _handle_request_error(
        self,
        request: NyaRequest,
        error: Exception,
        error_type: str,
        status_code: int,
        start_time: float,
    ) -> None:
        """
        Handle request errors uniformly.

        Args:
            r: NyaRequest object
            error: Exception that occurred
            error_type: Type of error (connection, timeout, etc.)
            status_code: Status code to record (0 for errors)
            start_time: When the request started
        """
        elapsed = time.time() - start_time
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
            },
        )

    async def execute_with_retry(
        self,
        r: NyaRequest,
        max_attempts: int = 3,
        retry_delay: float = 10.0,
    ) -> Optional[httpx.Response]:
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
        response = None
        current_delay = retry_delay

        for attempt in range(1, max_attempts + 1):
            r.attempts = attempt

            # Rotating api key if needed
            if retry_mode == "key_rotation" and r.attempts > 1:
                try:
                    r.api_key = await self.key_manager.get_available_key(
                        r.api_name, r.apply_rate_limit
                    )
                except APIKeyExhaustedError as e:
                    pass

            # Execute the request
            response = await self.execute_request(r)

            # If we got a successful response, break out of the loop
            if response and 200 <= response.status_code < 300:
                self.logger.info(
                    f"Request to {r.api_name} succeeded on attempt {r.attempts} with status {response.status_code}"
                )
                break

            # Skip retry logic if response status code is not configured for retries
            if not self._should_retry(response, retry_status_codes):
                break

            # Else, start retry logic, and calculate next delay
            next_delay = self._calculate_retry_delay(
                response, current_delay, retry_mode, retry_delay, r.attempts
            )

            # mark the current key as rate limited for unsuccessful attempts
            self.key_manager.mark_key_rate_limited(r.api_name, r.api_key, next_delay)

            # If this was our last attempt, don't wait
            if r.attempts >= max_attempts:
                self.logger.warning(
                    f"Max retry attempts ({max_attempts}) reached for {r.api_name}"
                )
                break

            self.logger.info(
                f"Retrying request to {r.api_name} in {next_delay:.1f}s "
                f"(attempt {attempt}/{max_attempts})"
            )

            # Wait before retry
            await asyncio.sleep(next_delay)
            current_delay = next_delay

        return response

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
