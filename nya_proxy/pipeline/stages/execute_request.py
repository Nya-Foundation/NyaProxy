"""
Pipeline stage for executing the HTTP request to the target API with retries.
"""

import asyncio
import logging
import random
import time
import traceback
from typing import Any, Dict, List, Optional, Union
from email.utils import parsedate_to_datetime
from datetime import datetime

import httpx
from starlette.responses import JSONResponse

from ...common.exceptions import APIKeyExhaustedError
from ...common.utils import _mask_api_key, format_elapsed_time, json_safe_dumps
from ..context import RequestContext
from ..interfaces import (
    IConfigManager,
    IKeyManager,
    IMetricsCollector,
    IPipelineStage,
)


class ExecuteRequestStage(IPipelineStage):
    """
    Executes the HTTP request to the target URL specified in the context.
    Handles retries based on API configuration (attempts, delay, status codes, mode).
    Updates context with http_response, response_status_code, retry_attempt, error.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,  # Inject the shared client
        config_manager: IConfigManager,
        key_manager: IKeyManager,
        metrics: Optional[IMetricsCollector] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.http_client = http_client
        self.config_manager = config_manager
        self.key_manager = key_manager
        self.metrics = metrics
        self.logger = logger or logging.getLogger(__name__)

    async def __call__(self, context: RequestContext) -> RequestContext:
        """
        Executes the request sending and retry logic.

        Args:
            context: The current request context.

        Returns:
            The updated request context.
        """
        # Skip if pipeline terminated early
        if context.final_response or context.error:
            return context

        if (
            not context.api_name
            or not context.target_url
            or not context.original_request
        ):
            self.logger.error(
                f"[{context.request_id}] Missing required context for ExecuteRequestStage."
            )
            context.error = ValueError("Missing required context for request execution")
            context.final_response = JSONResponse(
                status_code=500, content={"error": "Internal Server Error"}
            )
            context.error_handled = True
            return context

        api_name = context.api_name
        request_id = context.request_id

        # --- Get Retry Configuration ---
        retry_enabled = self.config_manager.get_api_retry_enabled(api_name)
        max_attempts = (
            self.config_manager.get_api_retry_attempts(api_name) if retry_enabled else 1
        )
        base_retry_delay = (
            self.config_manager.get_api_retry_after_seconds(api_name)
            if retry_enabled
            else 0.0
        )
        retry_status_codes = (
            self.config_manager.get_api_retry_status_codes(api_name)
            if retry_enabled
            else []
        )
        retry_methods = (
            self.config_manager.get_api_retry_request_methods(api_name)
            if retry_enabled
            else []
        )
        retry_mode = (
            self.config_manager.get_api_retry_mode(api_name)
            if retry_enabled
            else "default"
        )

        # Skip retry logic if method is not configured for retries
        if context.original_request.method.upper() not in retry_methods:
            self.logger.debug(
                f"[{request_id}] Method {context.original_request.method} not configured for retries on API '{api_name}'. Setting max_attempts=1."
            )
            max_attempts = 1

        # --- Retry Loop ---
        last_response: Optional[httpx.Response] = None
        last_error: Optional[Exception] = None
        current_delay = base_retry_delay

        for attempt in range(1, max_attempts + 1):
            context.retry_attempt = attempt
            start_single_request_time = time.time()
            last_error = None  # Reset error for this attempt

            # --- Key Rotation Logic ---
            if retry_mode == "key_rotation" and attempt > 1:
                original_key = context.selected_key
                try:
                    # Get a new key - assume rate limit check was done initially or handled by KeyManager
                    context.selected_key = await self.key_manager.get_available_key(
                        api_name,
                        check_rate_limit=False,  # Avoid redundant checks within retry loop? Needs thought.
                    )
                    self.logger.info(
                        f"[{request_id}][Attempt {attempt}] Rotated key for '{api_name}': '{context.selected_key[:4]}...' (was '{original_key[:4]}...')"
                    )
                    # Re-process headers if key changed? This adds complexity.
                    # For now, assume headers were processed with placeholders or the initial key is sufficient
                    # OR ModifyRequestStage needs to run again? Pipeline design decision.
                    # Let's assume for now headers don't need reprocessing on key rotation only.

                except APIKeyExhaustedError:
                    self.logger.warning(
                        f"[{request_id}][Attempt {attempt}] Key rotation failed for '{api_name}': Keys exhausted. Reusing previous key."
                    )
                    context.selected_key = original_key  # Revert to previous key
                except Exception as key_err:
                    self.logger.error(
                        f"[{request_id}][Attempt {attempt}] Error rotating key for '{api_name}': {key_err}. Reusing previous key."
                    )
                    context.selected_key = original_key

            # --- Execute Single Request ---
            key_id = (
                _mask_api_key(context.selected_key) if context.selected_key else "N/A"
            )
            self.logger.info(
                f"[{request_id}][Attempt {attempt}/{max_attempts}] Executing request to {context.target_url} with key_id {key_id}"
            )

            # Record request metric for this attempt
            if self.metrics:
                self.metrics.record_request(api_name, context.selected_key)

            try:
                # Use the shared client, configure timeout per request
                timeout_config = self._calculate_timeout(api_name)

                # Send the request using stream to handle potential streaming responses later
                stream = self.http_client.stream(
                    method=context.original_request.method,
                    url=context.target_url,
                    headers=context.request_headers,
                    content=context.request_content,
                    timeout=timeout_config,
                )
                async with stream as response:
                    # Read the response body ONLY IF NOT STREAMING for retry logic check
                    # The ProcessResponseStage will handle actual streaming later
                    # This is a potential issue: we might consume the stream here.
                    # Alternative: Check only status code and headers for retry? Yes, better.

                    last_response = response  # Store the raw response object
                    context.http_response = response  # Make available to later stages

                    # Check if we should retry based on status code
                    if not self._should_retry(response, retry_status_codes):
                        self.logger.info(
                            f"[{request_id}][Attempt {attempt}] Request successful or non-retryable status ({response.status_code})."
                        )
                        last_error = None  # Clear last error on success/non-retryable
                        break  # Exit retry loop

                    # If retryable status code, log and prepare for next attempt
                    self.logger.warning(
                        f"[{request_id}][Attempt {attempt}] Received retryable status code: {response.status_code}"
                    )
                    last_error = httpx.HTTPStatusError(
                        f"Status code {response.status_code}",
                        request=response.request,
                        response=response,
                    )

            except httpx.TimeoutException as e:
                last_error = e
                self.logger.warning(
                    f"[{request_id}][Attempt {attempt}] Request timed out: {e}"
                )
            except httpx.ConnectError as e:
                last_error = e
                self.logger.warning(
                    f"[{request_id}][Attempt {attempt}] Connection error: {e}"
                )
            except httpx.ReadError as e:
                last_error = e
                self.logger.warning(
                    f"[{request_id}][Attempt {attempt}] Read error: {e}"
                )
            except Exception as e:
                last_error = e
                self.logger.error(
                    f"[{request_id}][Attempt {attempt}] Unexpected error during request execution: {e}"
                )
                self.logger.debug(traceback.format_exc())
                # Break loop on unexpected errors? Or allow retry? Let's break for now.
                break

            # --- Post-Attempt Logic ---
            elapsed_single_request = time.time() - start_single_request_time
            self.logger.debug(
                f"[{request_id}][Attempt {attempt}] Finished in {elapsed_single_request:.4f}s."
            )

            # If error occurred or status code was retryable, calculate delay
            if last_error:
                if attempt >= max_attempts:
                    self.logger.warning(
                        f"[{request_id}] Max retry attempts ({max_attempts}) reached."
                    )
                    break  # Exit loop

                next_delay = self._calculate_retry_delay(
                    last_response, current_delay, retry_mode, base_retry_delay, attempt
                )

                # Mark the key used in the failed attempt as rate limited (if applicable)
                if (
                    isinstance(last_error, httpx.HTTPStatusError)
                    and last_error.response.status_code == 429
                    and context.selected_key
                ):
                    self.logger.info(
                        f"[{request_id}][Attempt {attempt}] Marking key {key_id} as rate limited for {next_delay:.2f}s due to 429."
                    )
                    self.key_manager.mark_key_rate_limited(
                        api_name, context.selected_key, next_delay
                    )

                self.logger.info(f"[{request_id}] Retrying in {next_delay:.2f}s...")
                await asyncio.sleep(next_delay)
                current_delay = (
                    next_delay  # Update delay for potential backoff calculation
                )

        # --- Finalize Context ---
        if (
            last_error and not last_response
        ):  # If the last attempt failed without even getting a response object
            context.error = last_error
            self.logger.error(
                f"[{request_id}] Request execution failed after {context.retry_attempt} attempts with error: {last_error}"
            )
            # Don't set final_response here, let an error handler stage do it or the runner default.
        elif last_response:
            # Store the last obtained response, even if it was an error status
            context.http_response = last_response
            context.response_status_code = last_response.status_code
            context.response_headers = dict(last_response.headers)  # Store headers now
            if last_error:  # If we finished attempts on a retryable error
                context.error = last_error
                self.logger.warning(
                    f"[{request_id}] Request execution finished after {context.retry_attempt} attempts with retryable status: {last_response.status_code}"
                )
            else:
                self.logger.info(
                    f"[{request_id}] Request execution successful on attempt {context.retry_attempt}. Status: {last_response.status_code}"
                )
        else:
            # Should not happen if loop runs at least once, but handle defensively
            context.error = Exception("Unknown error during request execution")
            self.logger.error(
                f"[{request_id}] Request execution finished with unknown error after {context.retry_attempt} attempts."
            )

        return context

    def _calculate_timeout(self, api_name: str) -> httpx.Timeout:
        """Calculate timeout config based on API settings."""
        api_timeout = self.config_manager.get_api_default_timeout(api_name)
        # Using similar logic as original RequestExecutor
        return httpx.Timeout(
            connect=5,
            read=api_timeout * 0.95,
            write=min(60.0, api_timeout * 0.2),
            pool=10.0,
        )

    def _should_retry(
        self, response: Optional[httpx.Response], retry_status_codes: List[int]
    ) -> bool:
        """Determine if a request should be retried based on the response."""
        if response is None:  # Network error occurred before response object created
            return True
        if response.status_code in retry_status_codes:
            return True
        return False

    def _calculate_retry_delay(
        self,
        response: Optional[httpx.Response],
        current_delay: float,
        retry_mode: str,
        base_retry_delay: float,
        attempt: int,
    ) -> float:
        """Calculate delay for next retry attempt."""
        # Check for Retry-After header first
        retry_after = self._get_retry_after(response)
        if retry_after is not None:
            self.logger.debug(f"Using Retry-After header value: {retry_after}s")
            return max(0.1, retry_after)  # Ensure minimum delay

        # Apply different retry strategies based on mode
        if retry_mode == "backoff":
            # Exponential backoff with jitter
            jitter = random.uniform(0.75, 1.25)
            # Use base_retry_delay for calculation, not current_delay to avoid runaway times
            calculated_delay = base_retry_delay * (1.5 ** (attempt - 1)) * jitter
            # Cap the delay? e.g., max(base_retry_delay, min(calculated_delay, 60.0))
            return max(0.1, calculated_delay)
        elif retry_mode == "key_rotation":
            # Minimal delay for key rotation strategy
            return max(0.1, base_retry_delay)  # Use base delay, ensure minimum
        else:  # "default" or unknown
            # Default linear strategy (use base delay)
            return max(0.1, base_retry_delay)

    def _get_retry_after(self, response: Optional[httpx.Response]) -> Optional[float]:
        """Extract Retry-After header value from response."""
        if not response:
            return None
        retry_after_header = response.headers.get("Retry-After")
        if not retry_after_header:
            return None

        try:
            # Try parsing as integer seconds
            return float(retry_after_header)
        except ValueError:
            try:
                # Try parsing as HTTP date format
                retry_date = parsedate_to_datetime(retry_after_header)
                # Ensure timezone awareness comparison if possible
                now = datetime.now(retry_date.tzinfo)  # Use response tz for comparison
                delta = retry_date - now
                return delta.total_seconds()
            except Exception:
                self.logger.warning(
                    f"Could not parse Retry-After header value: {retry_after_header}"
                )
                return None
