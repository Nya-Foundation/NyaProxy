"""
Request execution with retry logic.
"""

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, List, Optional

import httpx

from .models import NyaRequest
from .utils import _mask_api_key, format_elapsed_time

if TYPE_CHECKING:
    from .config_manager import ConfigManager
    from .metrics import MetricsCollector


class RequestExecutor:
    """
    Executes HTTP requests with customizable retry logic.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: "ConfigManager",
        logger: Optional[logging.Logger] = None,
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """
        Initialize the request executor.

        Args:
            client: HTTPX client for making requests
            config: Configuration manager instance
            logger: Logger instance
            metrics_collector: Metrics collector (optional)
        """
        self.client = client
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.metrics_collector = metrics_collector

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

        try:
            # Get timeout from configuration
            timeout_secs = self.config.get_api_default_timeout(r.api_name)

            # Create a composite timeout object
            timeout = httpx.Timeout(
                connect=min(10.0, timeout_secs / 2),  # Connection timeout
                read=timeout_secs,  # Read timeout
                write=timeout_secs,  # Write timeout
                pool=timeout_secs,  # Pool timeout
            )

            # Send the request
            response = await self.client.request(
                method=r.method,
                url=r.url,
                headers=r.headers,
                content=r.content,
                timeout=timeout,
            )

            # Log response time and status
            elapsed = time.time() - start_time
            self.logger.debug(
                f"Response from {r.url}: status={response.status_code}, time={format_elapsed_time(elapsed)}"
            )

            # Record key performance in metrics
            if self.metrics_collector:
                self.metrics_collector.record_key_usage(
                    api_name=api_name, key_id=key_id, status=response.status_code
                )

            return response

        except httpx.ConnectError as e:
            self._handle_request_error(r, e, "connection error", 0, start_time)
            return None
        except httpx.TimeoutException as e:
            self._handle_request_error(r, e, "timeout", 0, start_time)
            return None
        except Exception as e:
            self._handle_request_error(r, e, "unexpected error", 0, start_time)
            return None

    def _handle_request_error(
        self,
        r: NyaRequest,
        error: Exception,
        error_type: str,
        status: int,
        start_time: float,
    ) -> None:
        """
        Handle request errors uniformly.

        Args:
            r: NyaRequest object
            error: Exception that occurred
            error_type: Type of error (connection, timeout, etc.)
            status: Status code to record (0 for errors)
            start_time: When the request started
        """
        elapsed = time.time() - start_time
        self.logger.error(
            f"{error_type.capitalize()} to {r.url}: {str(error)} after {format_elapsed_time(elapsed)}"
        )

        if self.metrics_collector:
            self.metrics_collector.record_key_usage(
                api_name=r.api_name,
                key_id=_mask_api_key(r.api_key),
                status=status,
            )

    async def execute_with_retry(
        self,
        r: NyaRequest,
        max_attempts: int = 3,
        retry_delay: float = 10.0,
        retry_mode: str = "default",
    ) -> Optional[httpx.Response]:
        """
        Execute a request with retry logic.

        Args:
            r: NyaRequest object with request details
            max_attempts: Maximum number of retry attempts
            retry_delay: Base delay in seconds between retries
            retry_mode: Retry mode (default, backoff, key_rotation)

        Returns:
            HTTPX response or None if all attempts failed
        """
        # Don't retry non-idempotent methods unless explicitly configured
        if not self._is_method_retryable(r.method, retry_mode):
            self.logger.debug(f"Skipping retries for non-idempotent method {r.method}")
            return await self.execute_request(r)

        # Get retry status codes from API config or default
        retry_status_codes = self.config.get_api_retry_status_codes(r.api_name)

        # Execute request with retries
        response = None
        current_delay = retry_delay

        for attempt in range(1, max_attempts + 1):
            r.attempts = attempt

            # Execute the request
            response = await self.execute_request(r)

            # Stop if we got a successful response
            if not self._should_retry(response, retry_status_codes):
                break

            # If this was our last attempt, don't wait
            if attempt >= max_attempts:
                self.logger.warning(
                    f"Max retry attempts ({max_attempts}) reached for {r.api_name}"
                )
                break

            # Calculate delay for next attempt
            next_delay = self._calculate_retry_delay(
                response, current_delay, retry_mode, attempt
            )

            self.logger.info(
                f"Retrying request to {r.api_name} in {next_delay:.1f}s "
                f"(attempt {attempt}/{max_attempts})"
            )

            # Wait before retry
            await asyncio.sleep(next_delay)
            current_delay = next_delay

        return response

    def _is_method_retryable(self, method: str, retry_mode: str) -> bool:
        """
        Determine if an HTTP method should be retried.

        Args:
            method: HTTP method (GET, POST, etc.)
            retry_mode: Retry mode

        Returns:
            True if method is safe to retry
        """
        # Idempotent methods are always safe to retry
        idempotent_methods = ["GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"]
        if method.upper() in idempotent_methods:
            return True

        # Non-idempotent methods can be retried with key_rotation mode
        if retry_mode == "key_rotation":
            return True

        # Other non-idempotent methods should not be retried
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
        attempt: int,
    ) -> float:
        """
        Calculate delay for next retry attempt.

        Args:
            response: HTTPX response
            current_delay: Current delay in seconds
            retry_mode: Retry mode (default, backoff, key_rotation)
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
            return 1.0
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
