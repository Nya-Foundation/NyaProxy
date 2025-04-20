"""
Request executor for handling API requests with retry logic.
"""

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from .models import NyaRequest


class RequestExecutorError(Exception):
    """Exception raised for request executor errors."""

    pass


class RequestExecutor:
    """
    Executes HTTP requests with retry logic.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        default_settings: Dict[str, Any],
        logger: logging.Logger,
        metrics_collector: Optional[Any] = None,
    ):
        """
        Initialize the request executor.

        Args:
            client: HTTP client
            default_settings: Default settings for the executor
            logger: Logger instance
            metrics_collector: Optional metrics collector
        """
        self.client = client
        self.logger = logger
        self.metrics_collector = metrics_collector

        # Extract settings from config
        self._init_timeout_settings(default_settings)
        self._init_retry_settings(default_settings)
        self._init_error_handling(default_settings)

        # Stats
        self.total_requests = 0
        self.total_retries = 0
        self.total_failures = 0

    def _init_timeout_settings(self, default_settings: Dict[str, Any]) -> None:
        """Initialize timeout settings from config."""
        timeout_settings = default_settings.get("timeouts", {})
        self.default_timeout = timeout_settings.get("request_timeout_seconds", 30.0)
        self.max_timeout = (
            self.default_timeout * 2
        )  # Maximum timeout is double the default

    def _init_retry_settings(self, default_settings: Dict[str, Any]) -> None:
        """Initialize retry settings from config."""
        retry_settings: Dict = default_settings.get("retry", {})
        self.default_max_attempts = retry_settings.get("attempts", 3)
        self.default_retry_delay = retry_settings.get("retry_after_seconds", 10.0)
        self.default_retry_mode = retry_settings.get("mode", "default")

    def _init_error_handling(self, default_settings: Dict[str, Any]) -> None:
        """Initialize error handling settings from config."""
        error_handling = default_settings.get("error_handling", {})
        self.retry_status_codes = error_handling.get(
            "retry_status_codes", [429, 500, 502, 503, 504, 507, 524]
        )

    def _debug_request(self, request: Dict[str, Any]) -> None:
        """Debug the request by logging its content and headers."""
        headers: Dict = request.get("headers", {})

        content_type = headers.get("content-type", None)
        content = request.get("content", {})

        if content_type == "application/json":
            # Handle potential bytes content
            if isinstance(content, bytes):
                try:
                    content = json.loads(content.decode("utf-8"))
                except:
                    content = f"<binary data: {len(content)} bytes>"
            self.logger.debug(
                f"Prepared Request JSON: {json.dumps(content, indent=4, ensure_ascii=False)}"
            )
        else:
            # Handle different content types safely
            if isinstance(content, bytes):
                content = f"<binary data: {len(content)} bytes>"
            self.logger.debug(
                f"Prepared Request Content: {content if content else 'No Content Available'}"
            )

        self.logger.debug(f"Prepared Request Headers: {headers}")

    async def execute_with_retry(
        self,
        r: NyaRequest,
        max_attempts: Optional[int] = None,
        retry_delay: Optional[float] = None,
        retry_mode: Optional[str] = None,
    ) -> httpx.Response:
        """
        Execute a request with retry logic.

        Args:
            r: NyaRequest object containing request data
            max_attempts: Maximum number of retry attempts (defaults to config value)
            retry_delay: Base delay between retries in seconds (defaults to config value)

        Returns:
            Response from the API

        Raises:
            RequestExecutorError: If all retry attempts fail
        """
        # Use provided values or fall back to instance defaults from config
        max_attempts = max_attempts or self.default_max_attempts
        retry_delay = retry_delay or self.default_retry_delay
        retry_mode = retry_mode or self.default_retry_mode

        attempt = 0
        last_error = None
        self.total_requests += 1
        api_name = r.api_name

        # Prepare the request
        request = self._prepare_request(r)

        # debug log the request
        self._debug_request(request)

        while attempt < max_attempts:
            attempt += 1
            try:
                # Apply waiting period for retries
                if attempt > 1:
                    await self._handle_retry_wait(
                        attempt, max_attempts, retry_delay, api_name
                    )

                # Execute the request
                self.logger.debug(
                    f"Executing request to {request['url']} (attempt {attempt}/{max_attempts})"
                )

                response = await self.client.request(
                    **request,  # Pass all remaining parameters
                )

                # Check if we need to retry based on status
                if self._should_default_retry(
                    response, attempt, max_attempts, retry_mode
                ):
                    retry_delay = self._get_retry_delay(response, retry_delay)
                    self.logger.warning(
                        f"Got status {response.status_code} from {api_name}, will retry after {retry_delay:.2f}s"
                    )
                    await asyncio.sleep(retry_delay)
                    continue

                # If we get here, we've got a response we can use, skip retries
                return response

            except httpx.TimeoutException as e:
                self._log_request_error("Timeout", api_name, attempt, max_attempts, e)
                last_error = e

            except httpx.NetworkError as e:
                self._log_request_error(
                    "Network Error", api_name, attempt, max_attempts, e
                )
                last_error = e
                break  # Don't retry on network errors

            except Exception as e:
                self.logger.error(
                    f"Unexpected error during request to {api_name}: {str(e)}"
                )
                last_error = e
                break  # Don't retry on unexpected errors

        # If we get here, all retries failed
        self._handle_retry_failure(attempt, api_name, last_error)
        raise RequestExecutorError(
            f"Max retry attempts ({attempt}) reached for {api_name}"
        )

    def _prepare_request(self, request_data: NyaRequest) -> Dict[str, Any]:
        """Prepare the request by cleaning headers and internal fields."""
        # Convert RequestData to dictionary for backward compatibility
        request = request_data.to_dict()

        # Handle headers and host
        headers = request.get("headers", {}) or {}

        # Normalize headers to lowercase, and remove duplicates, removing x-forwarded headers
        clean_headers = {
            k.lower(): v
            for k, v in headers.items()
            if not k.startswith("x-forwarded") and k != "x-real-ip"
        }

        # If URL is present, extract the host from it and set in headers
        if "url" in request and request["url"]:
            try:
                # Parse the requets URL to extract host
                parsed_url = urlparse(request["url"])
                target_host = parsed_url.netloc

                # Remove port if present in netloc
                if ":" in target_host:
                    target_host = target_host.split(":", 1)[0]

                # Update headers with proper host if not already set or different
                if target_host and (
                    "host" not in clean_headers or clean_headers["host"] != target_host
                ):
                    clean_headers["host"] = target_host

            except Exception as e:
                self.logger.warning(
                    f"Failed to extract host from URL {request['url']}: {e}"
                )

        # Set updated headers back to request
        request["headers"] = clean_headers
        return request

    async def _handle_retry_wait(
        self, attempt: int, max_attempts: int, retry_delay: float, api_name: str
    ) -> None:
        """Handle waiting between retry attempts with jitter."""
        jitter = random.uniform(0.8, 1.2)  # 20% jitter
        wait_time = retry_delay * jitter
        self.logger.info(
            f"Retry attempt {attempt}/{max_attempts} for {api_name}, waiting {wait_time:.2f}s"
        )
        await asyncio.sleep(wait_time)
        self.total_retries += 1

    def _should_default_retry(
        self, response: httpx.Response, attempt: int, max_attempts: int, retry_mode: str
    ) -> bool:
        """Determine if a request should be retried based on its status code."""

        self.logger.debug(
            f"Checking if response status {response.status_code} should be handled with default retry policy, current attempt {attempt}/{max_attempts}, try mode: {retry_mode}"
        )
        return (
            response.status_code in self.retry_status_codes
            and attempt < max_attempts
            and retry_mode == "default"
        )

    def _get_retry_delay(self, response: httpx.Response, default_delay: float) -> float:
        """Extract retry delay from response headers or use default."""
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                wait_time = float(retry_after)
                self.logger.info(f"Got retry-after header: {wait_time}s")
                # Cap the wait time to something reasonable
                return min(wait_time, 60.0)
            except (ValueError, TypeError):
                pass
        return default_delay

    def _log_request_error(
        self,
        error_type: str,
        api_name: str,
        attempt: int,
        max_attempts: int,
        error: Exception,
    ) -> None:
        """Log a request error with consistent format."""
        self.logger.warning(
            f"{error_type} during request to {api_name} (attempt {attempt}/{max_attempts}): {str(error)}"
        )

    def _handle_retry_failure(
        self, attempts: int, api_name: str, last_error: Optional[Exception]
    ) -> None:
        """Handle the case when all retries have failed."""
        self.total_failures += 1

        if attempts >= self.default_max_attempts:
            error_message = f"Max retry attempts ({attempts}) reached for {api_name}"
        else:
            error_message = f"Request failed for {api_name} with non-retryable error"

        if last_error:
            error_message += f": {str(last_error)}"

        self.logger.error(error_message)

    async def execute_batch(
        self,
        requests: List[NyaRequest],
        concurrency: int = 5,
    ) -> List[Tuple[Optional[httpx.Response], Optional[Exception]]]:
        """
        Execute a batch of requests with concurrency control.

        Args:
            requests: List of RequestData objects
            concurrency: Maximum number of concurrent requests

        Returns:
            List of (response, error) tuples for each request
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def execute_with_semaphore(
            r: NyaRequest,
        ) -> Tuple[Optional[httpx.Response], Optional[Exception]]:
            async with semaphore:
                try:
                    # Execute the request
                    retry_config: Dict = r.api_config.get("retry", {})
                    max_attempts = retry_config.get("attempts", 1)
                    retry_delay = retry_config.get("retry_after_seconds", 0)
                    retry_mode = retry_config.get("mode", "default")

                    response = await self.execute_with_retry(
                        r, max_attempts, retry_delay, retry_mode
                    )
                    return response, None
                except Exception as e:
                    return None, e

        # Create tasks for all requests
        tasks = [execute_with_semaphore(request) for request in requests]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=False)

        return results

    def get_stats(self) -> Dict[str, int]:
        """
        Get executor statistics.

        Returns:
            Dictionary with executor statistics
        """
        return {
            "total_requests": self.total_requests,
            "total_retries": self.total_retries,
            "total_failures": self.total_failures,
        }
