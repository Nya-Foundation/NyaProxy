"""
Proxy handler for intercepting and forwarding HTTP requests with token rotation.
"""

import asyncio
import json
import logging
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from starlette.responses import JSONResponse, Response

from ..common.constants import API_PATH_PREFIX
from ..common.exceptions import (
    APIKeyExhaustedError,
    EndpointRateLimitExceededError,
    RequestExpiredError,
    VariablesConfigurationError,
)
from ..common.models import NyaRequest
from ..common.utils import json_safe_dumps
from ..server.config import ConfigManager
from ..services.key_manager import KeyManager
from ..services.load_balancer import LoadBalancer
from ..services.metrics import MetricsCollector
from ..services.request_queue import RequestQueue
from .header_processor import HeaderProcessor
from .request_executor import RequestExecutor
from .response_processor import ResponseProcessor

if TYPE_CHECKING:
    from ..services.rate_limiter import RateLimiter  # Avoid circular import issues


class NyaProxyCore:
    """
    Handles main proxy logic, including requests, token rotation, and rate limiting.
    """

    def __init__(
        self,
        config: ConfigManager,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the proxy handler.

        Args:
            config: Configuration manager instance
            logger: Logger instance

        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Initialize HTTP client, load balancers, and rate limiters
        self.load_balancers = self._initialize_load_balancers()
        self.rate_limiters = self._initialize_rate_limiters()
        self.metrics_collector = self._init_metrics()

        # Create key manager
        self.key_manager = KeyManager(
            self.load_balancers, self.rate_limiters, logger=self.logger
        )

        self.request_queue = self._init_request_queue(self.key_manager)

        # Initialize helper components
        self.header_processor = HeaderProcessor(logger=self.logger)

        # Create request executor
        self.request_executor = RequestExecutor(
            self.config,
            self.logger,
            self.metrics_collector,
            self.key_manager,
        )

        self.response_processor = ResponseProcessor(
            self.logger, self.metrics_collector, self.load_balancers
        )

        # Register request processor with queue if present
        if self.request_queue:
            self.request_queue.register_processor(self._process_queued_request)

    def _init_metrics(self):
        """Initialize metrics collector."""
        if not self.logger:
            logging.warning("Logger not initialized, metrics collection may be limited")

        self.metrics_collector = MetricsCollector(
            self.logger or logging.getLogger("nyaproxy")
        )
        if self.logger:
            self.logger.info("Metrics collector initialized")
        return self.metrics_collector

    def _init_request_queue(
        self, key_manager: Optional[KeyManager] = None
    ) -> Optional[RequestQueue]:
        """Initialize request queue if enabled."""
        if not self.config:
            if self.logger:
                self.logger.warning(
                    "Config manager not initialized, request queue disabled"
                )
            return None

        if not self.config.get_queue_enabled():
            if self.logger:
                self.logger.info("Request queuing disabled in configuration")
            return None

        queue_size = self.config.get_queue_size()
        queue_expiry = self.config.get_queue_expiry()

        self.request_queue = RequestQueue(
            key_manager=key_manager,
            max_size=queue_size,
            expiry_seconds=queue_expiry,
            logger=self.logger,
        )

        if self.logger:
            self.logger.info(
                f"Request queue initialized (size={queue_size}, expiry={queue_expiry}s)"
            )
        return self.request_queue

    def _initialize_load_balancers(self) -> Dict[str, LoadBalancer]:
        """Initialize load balancers for each API endpoint."""
        load_balancers = {}
        apis = self.config.get_apis()

        for api_name in apis.keys():
            strategy = self.config.get_api_load_balancing_strategy(api_name)
            key_variable = self.config.get_api_key_variable(api_name)

            # Get tokens/keys for this API
            keys = self.config.get_api_variable_values(api_name, key_variable)
            if not keys:
                raise VariablesConfigurationError(
                    f"No values found for key variable '{key_variable}' in API '{api_name}'"
                )

            # Initialize load balancer for this API per key level
            load_balancers[api_name] = LoadBalancer(keys, strategy, self.logger)

            # Initialize load balancers for other variables if they exist
            variables = self.config.get_api_variables(api_name)
            for variable_name in variables.keys():

                # Skip the key variable itself
                if variable_name == key_variable:
                    continue

                values = self.config.get_api_variable_values(api_name, variable_name)

                # Skip if no values are found for this variable
                if not values:
                    raise VariablesConfigurationError(
                        f"No values found for variable '{variable_name}' in API '{api_name}'"
                    )

                load_balancers[f"{api_name}_{variable_name}"] = LoadBalancer(
                    values, strategy, self.logger
                )

        return load_balancers

    def _initialize_rate_limiters(self) -> Dict[str, Any]:
        """Initialize rate limiters for each API endpoint."""
        rate_limiters = {}
        apis = self.config.get_apis()

        for api_name in apis.keys():
            # Get rate limit settings for this API endpoint
            endpoint_limit = self.config.get_api_endpoint_rate_limit(api_name)
            key_limit = self.config.get_api_key_rate_limit(api_name)

            # Create endpoint rate limiter
            rate_limiters[f"{api_name}_endpoint"] = self._create_rate_limiter(
                endpoint_limit
            )

            # Create rate limiter for each key
            key_variable = self.config.get_api_key_variable(api_name)
            keys = self.config.get_api_variable_values(api_name, key_variable)

            for key in keys:
                key_id = f"{api_name}_{key}"
                rate_limiters[key_id] = self._create_rate_limiter(key_limit)

        return rate_limiters

    def _create_rate_limiter(self, rate_limit: str) -> Any:
        """Create a rate limiter with the specified limit."""
        from ..services.rate_limiter import RateLimiter

        return RateLimiter(rate_limit, logger=self.logger)

    async def handle_request(self, request: NyaRequest) -> Response:
        """
        Handle an incoming proxy request.

        Args:
            request: FastAPI Request object

        Returns:
            Response to the client
        """
        # Prepare the request for forwarding
        api_name, path, _ = await self._prepare_request(request)

        if not api_name:
            return JSONResponse(
                status_code=404, content={"error": "Unknown API endpoint"}
            )

        # Skip rate limit verification if path is not rate-limited
        if not self._should_apply_rate_limit(api_name, path):
            request.apply_rate_limit = False
            return await self._process_request(request)

        if not await self.key_manager.has_available_keys(api_name):
            self.logger.debug(
                f"No available API keys for {api_name}, rate limit exceeded or no keys configured."
            )
            return await self._handle_rate_limit_exceeded(request)

        try:
            # Check endpoint-level rate limiting
            self._check_endpoint_rate_limit(api_name)

            # Process request and handle response
            return await self._process_request(request)

        except EndpointRateLimitExceededError as e:
            return await self._handle_rate_limit_exceeded(request)
        except APIKeyExhaustedError:
            return await self._handle_rate_limit_exceeded(request)
        except Exception as e:
            return self._handle_request_exception(request, 500, e)

    def _check_endpoint_rate_limit(self, api_name: str) -> None:
        """
        Check if the endpoint rate limit is exceeded.

        Args:
            api_name: Name of the API

        Raises:
            RateLimitExceededError: If rate limit is exceeded
        """
        endpoint_limiter: RateLimiter = self.key_manager.get_api_rate_limiter(api_name)

        if endpoint_limiter and not endpoint_limiter.allow_request():
            remaining = endpoint_limiter.get_reset_time()
            self.logger.warning(
                f"Endpoint rate limit exceeded for {api_name}, reset in {remaining:.2f}s"
            )
            raise EndpointRateLimitExceededError(api_name, reset_in_seconds=remaining)

    async def _process_request(
        self,
        r: NyaRequest,
    ) -> Response:
        """
        Process the prepared request and handle the response.

        Args:
            r: Prepared NyaRequest object
            start_time: Request start time

        Returns:
            Response to the client
        """
        start_time = time.time()
        self.logger.debug(f"Processing request to {r.api_name}: {r.url}")

        # Get API configuration
        retry_enabled = self.config.get_api_retry_enabled(r.api_name)
        retry_attempts = self.config.get_api_retry_attempts(r.api_name)
        retry_delay = self.config.get_api_retry_after_seconds(r.api_name)

        endpoint = self.config.get_api_endpoint(r.api_name)

        if not retry_enabled:
            retry_attempts = 1
            retry_delay = 0

        # Configure custom headers for the proxied request
        await self._set_custom_request_headers(r)

        # Execute the request with retries if configured
        httpx_response = await self.request_executor.execute_with_retry(
            r, retry_attempts, retry_delay
        )

        # Process and return the response
        return await self.response_processor.process_response(
            r,
            httpx_response,
            start_time,
            endpoint,
        )

    def _handle_request_exception(
        self,
        r: NyaRequest,
        status_code: int = 500,
        exception: Exception = Exception("Unknown error"),
    ) -> Response:
        """
        Handle any other exception that occurs during request processing and record it in metrics.

        Args:
            r: NyaRequest object containing request data
            status_code: HTTP status code to return (default is 500)
            exception: The exception that was raised

        Returns:
            Error response
        """

        api_name = r.api_name
        api_key = r.api_key if r.api_key else "unknown"

        elapsed = time.time() - r.added_at
        self.logger.error(f"Error handling request to {api_name}: {str(exception)}")
        self.logger.debug(traceback.format_exc())

        # Record error in metrics if available
        if self.metrics_collector and r.apply_rate_limit:
            self.metrics_collector.record_response(
                api_name, api_key, status_code, elapsed
            )

        return self.response_processor.create_error_response(
            exception, status_code=status_code, api_name=api_name
        )

    async def _handle_rate_limit_exceeded(
        self,
        request: NyaRequest,
    ) -> Response:
        """
        Handle a rate-limited request, queueing it if enabled.

        Args:
            request: NyaRequest object containing the request data

        Returns:
            Response to the client
        """
        api_name = request.api_name

        # If queueing is enabled, try to queue and process the request
        if self.request_queue and self.config.get_queue_enabled():
            try:
                retry_delay = self.config.get_api_retry_after_seconds(api_name)

                # Calculate appropriate reset time based on rate limit and queue wait time
                next_api_key_reset = await self.key_manager.get_api_rate_limit_reset(
                    api_name, retry_delay
                )
                queue_reset = await self.request_queue.get_estimated_wait_time(api_name)
                reset_in_seconds = int(max(next_api_key_reset, queue_reset))

                try:
                    # Record queue hit in metrics
                    if self.metrics_collector:
                        self.metrics_collector.record_queue_hit(api_name)
                        self.metrics_collector.record_rate_limit_hit(
                            api_name, request.api_key if request.api_key else "unknown"
                        )

                    # Enqueue the request and wait for response
                    future = await self.request_queue.enqueue_request(
                        r=request,
                        reset_in_seconds=reset_in_seconds,
                    )

                    api_timeout = self.config.get_api_default_timeout(api_name)
                    timeout = reset_in_seconds + api_timeout

                    return await asyncio.wait_for(future, timeout=timeout)

                except asyncio.TimeoutError as e:
                    return self._handle_request_exception(request, 504, e)

                except RequestExpiredError as e:
                    return self._handle_request_exception(request, 504, e)

                except Exception as e:
                    return self._handle_request_exception(request, 500, e)

            except Exception as queue_error:
                self.logger.error(
                    f"Error queueing request: {str(queue_error)}, {traceback.format_exc() if self.config.get_debug_level().upper() == 'DEBUG' else ''}"
                )

        # Default rate limit response if queueing is disabled or failed
        return JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded for this endpoint or not available api keys."
            },
        )

    async def _prepare_request(
        self,
        r: NyaRequest,
    ) -> Tuple[str, str, str]:
        """
        Prepare the proxy request by identifying the target API

        Args:
            r: NyaRequest object containing the request data

        Returns:
            Tuple of (api_name, trail_path, target_url)
        """

        # Identify target API based on path
        api_name, trail_path = self.parse_request(r)

        # Construct target api endpoint URL
        target_endpoint: str = self.config.get_api_endpoint(api_name)
        target_url = f"{target_endpoint}{trail_path}"

        r.api_name = api_name
        r.url = target_url

        return api_name, trail_path, target_url

    async def _set_custom_request_headers(
        self,
        r: NyaRequest,
    ) -> Dict[str, str]:
        """
        Prepare headers with variable substitution

        Args:
            r: NyaRequest object containing the request data

        Returns:
            Headers dictionary

        Raises:
            VariablesConfigurationError: If variable configuration is incorrect
            APIKeyExhaustedError: If no API keys are available
        """
        api_name = r.api_name

        # if api_key is not set, get an available key from the key manager
        r.api_key = (
            r.api_key
            if r.api_key
            else await self.key_manager.get_available_key(api_name, r.apply_rate_limit)
        )

        # Get key variable for the API
        key_variable = self.config.get_api_key_variable(api_name)

        # Get custom headers configuration for the API
        header_config: Dict[str, Any] = self.config.get_api_custom_headers(api_name)

        # Identify all template variables in headers that needs to be substituted
        required_vars = self.header_processor.extract_required_variables(header_config)

        var_values: Dict[str, Any] = {key_variable: r.api_key}

        # Get values for other variables from load balancers
        for var in required_vars:
            if var == key_variable:
                continue

            variable_balancer = self.load_balancers.get(f"{api_name}_{var}")
            if not variable_balancer:
                raise ValueError(
                    f"Variable configuration error for {var} in {api_name}"
                )

            variable_value = variable_balancer.get_next()
            var_values[var] = variable_value

        # Process headers with variable substitution
        headers = self.header_processor._process_headers(
            header_templates=header_config,
            variable_values=var_values,
            original_headers=dict(r.headers),
        )

        parsed_url = urlparse(r.url)
        headers["host"] = parsed_url.netloc

        r.headers = headers

    async def _process_queued_request(self, r: NyaRequest) -> Response:
        """
        Process a request from the queue.

        Args:
            r: NyaRequest object containing the queued request data

        Returns:
            Response from the target API
        """
        return await self._process_request(r)

    def parse_request(self, request: NyaRequest) -> Tuple[Optional[str], Optional[str]]:
        """
        Determine which API to route to based on the request path.

        Args:
            request: FastAPI request object

        Returns:
            Tuple of (api_name, remaining_path)

        Examples:
            /api/openai/v1/chat/completions -> ("openai", "/v1/chat/completions")

            if api has aliases (/reddit, /r):
                /api/reddit/v1/messages & /api/r/v1/messages -> ("reddit", "/v1/messages")
        """
        path = request._url.path
        apis_config = self.config.get_apis()

        # Handle non-API paths or malformed requests
        if not path or not path.startswith(API_PATH_PREFIX):
            return None, None

        # Extract parts after API_PATH_PREFIX, e.g., "/api/"
        api_path = path[len(API_PATH_PREFIX) :]

        # Handle empty path after prefix
        if not api_path:
            return None, None

        # Split into endpoint and trail path
        parts = api_path.split("/", 1)
        api_name = parts[0]
        trail_path = "/" + parts[1] if len(parts) > 1 else "/"

        # Direct match with API name
        if api_name in apis_config:
            return api_name, trail_path

        # Check for aliases in each API config
        for api_name in apis_config.keys():
            aliases = self.config.get_api_aliases(api_name)
            if aliases and api_name in aliases:
                return api_name, trail_path

        # No match found
        self.logger.warning(f"No API configuration found for endpoint: {api_name}")
        return None, None

    def _should_apply_rate_limit(self, api_name: str, path: str) -> bool:
        """
        Check if rate limiting should be applied to the given path.

        Args:
            api_name: Name of the API endpoint
            path: Request path to check

        Returns:
            bool: True if rate limiting should be applied, False otherwise
        """
        # Get rate limit paths from config, default to ['*'] (all paths)
        rate_limit_paths = self.config.get_api_rate_limit_paths(api_name)

        # If no paths are specified or '*' is in the list, apply to all paths
        if not rate_limit_paths or "*" in rate_limit_paths:
            return True

        # Check each pattern against the path
        for pattern in rate_limit_paths:
            # Simple wildcard matching (could be extended to use regex)
            if pattern.endswith("*"):
                # Check if path starts with the pattern minus the '*'
                prefix = pattern[:-1]
                if path.startswith(prefix):
                    return True
            # Exact match
            elif pattern == path:
                return True

        # No matches found, don't apply rate limiting
        self.logger.debug(
            f"Path {path} not in rate_limit_paths for {api_name}, skipping rate limiting"
        )
        return False
