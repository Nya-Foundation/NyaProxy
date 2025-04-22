"""
Proxy handler for intercepting and forwarding HTTP requests with token rotation.
"""

import asyncio
import json
import logging
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import httpx
from fastapi import Request
from starlette.responses import JSONResponse, Response

from .config_manager import ConfigManager
from .constants import API_PATH_PREFIX
from .exceptions import ApiKeyRateLimitExceededError, EndpointRateLimitExceededError
from .header_processor import HeaderProcessor
from .key_manager import KeyManager
from .load_balancer import LoadBalancer
from .metrics import MetricsCollector
from .models import NyaRequest
from .request_executor import RequestExecutor
from .request_queue import RequestQueue
from .response_processor import ResponseProcessor

if TYPE_CHECKING:
    from .rate_limiter import RateLimiter  # Avoid circular import issues


class ProxyHandler:
    """
    Handles proxy requests, token rotation, and load balancing.
    """

    def __init__(
        self,
        config: ConfigManager,
        logger: Optional[logging.Logger] = None,
        request_queue: Optional[RequestQueue] = None,
        metrics_collector: Optional[MetricsCollector] = None,
    ):
        """
        Initialize the proxy handler.

        Args:
            config: Configuration manager instance
            logger: Logger instance
            request_queue: Request queue instance (optional)
            metrics_collector: Metrics collector instance (optional)
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.request_queue = request_queue
        self.metrics_collector = metrics_collector

        # Initialize helper components
        self.header_processor = HeaderProcessor(logger=self.logger)
        self.response_processor = ResponseProcessor(logger=self.logger)

        # Initialize HTTP client, load balancers, and rate limiters
        self.client = self._setup_client()
        self.load_balancers = self._initialize_load_balancers()
        self.rate_limiters = self._initialize_rate_limiters()

        # Create key manager
        self.key_manager = KeyManager(
            self.load_balancers, self.rate_limiters, logger=self.logger
        )

        # Create request executor
        self.request_executor = RequestExecutor(
            self.client,
            self.config,
            self.logger,
            self.metrics_collector,
        )

        # Register request processor with queue if present
        if self.request_queue:
            self.request_queue.register_processor(self._process_queued_request)

        # Start metrics logging task if available
        if self.metrics_collector:
            self._start_metrics_logging()

    def _setup_client(self) -> httpx.AsyncClient:
        """Set up the HTTP client with appropriate configuration."""
        proxy_settings = self.config.get_proxy_settings()

        # Configure client with appropriate settings
        client_kwargs = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(60.0),  # Default timeout of 60 seconds
        }

        if proxy_settings["enabled"] and proxy_settings["address"]:
            client_kwargs["proxies"] = proxy_settings["address"]
            self.logger.info(f"Using proxy: {proxy_settings['address']}")

        return httpx.AsyncClient(**client_kwargs)

    def _initialize_load_balancers(self) -> Dict[str, LoadBalancer]:
        """Initialize load balancers for each API endpoint."""
        load_balancers = {}
        apis = self.config.get_apis()
        default_settings = self.config.get_default_settings()

        default_strategy = default_settings.get(
            "load_balancing_strategy", "round_robin"
        )

        for api_name, api_config in apis.items():
            strategy = api_config.get("load_balancing_strategy", default_strategy)
            key_variable = api_config.get("key_variable", "keys")

            # Get tokens/keys for this API
            keys = self.config.get_api_variables(api_name, key_variable)
            if not keys:
                self.logger.warning(f"No keys/tokens found for API: {api_name}")
                continue

            # Create load balancer for this API
            load_balancers[api_name] = LoadBalancer(keys, strategy, self.logger)

            # Initialize other variables if needed
            variables = api_config.get("variables", {})
            for variable_name in variables.keys():
                if variable_name != key_variable:
                    values = self.config.get_api_variables(api_name, variable_name)
                    if values:
                        load_balancers[f"{api_name}_{variable_name}"] = LoadBalancer(
                            values, strategy, self.logger
                        )

        return load_balancers

    def _initialize_rate_limiters(self) -> Dict[str, Any]:
        """Initialize rate limiters for each API endpoint."""
        rate_limiters = {}
        apis = self.config.get_apis()
        default_settings = self.config.get_default_settings()
        default_endpoint_limit = default_settings.get("rate_limit", {}).get(
            "endpoint_rate_limit", "0"
        )
        default_key_limit = default_settings.get("rate_limit", {}).get(
            "key_rate_limit", "0"
        )

        for api_name, api_config in apis.items():
            # Get rate limit settings for this API endpoint
            rate_limit_config = api_config.get("rate_limit", {})
            endpoint_limit = rate_limit_config.get(
                "endpoint_rate_limit", default_endpoint_limit
            )
            key_limit = rate_limit_config.get("key_rate_limit", default_key_limit)

            # Create endpoint rate limiter
            rate_limiters[f"{api_name}_endpoint"] = self._create_rate_limiter(
                endpoint_limit
            )

            # Create rate limiter for each key
            key_variable = api_config.get("key_variable", "keys")
            keys = self.config.get_api_variables(api_name, key_variable)

            for key in keys:
                key_id = f"{api_name}_{key}"
                rate_limiters[key_id] = self._create_rate_limiter(key_limit)

        return rate_limiters

    def _create_rate_limiter(self, rate_limit: str) -> Any:
        """Create a rate limiter with the specified limit."""
        from .rate_limiter import RateLimiter

        return RateLimiter(rate_limit, logger=self.logger)

    def _start_metrics_logging(self) -> None:
        """Start a background task to log metrics periodically for monitoring."""

        async def log_metrics_task():
            while True:
                try:
                    # Log metrics every 5 minutes
                    await asyncio.sleep(300)

                    if self.metrics_collector:
                        metrics = self.metrics_collector.get_summary()
                        self.logger.info(f"Metrics summary: {json.dumps(metrics)}")

                        # Log individual API stats
                        for api_name, stats in metrics.get("apis", {}).items():
                            self.logger.info(
                                f"API {api_name}: {stats['total_requests']} requests, "
                                f"{stats['success_rate']:.1f}% success rate, "
                                f"{stats['avg_response_time']:.2f}ms avg response time"
                            )

                        # Log queue stats if available
                        if self.request_queue:
                            queue_metrics = self.request_queue.get_metrics()
                            self.logger.info(
                                f"Queue metrics: {json.dumps(queue_metrics)}"
                            )

                except Exception as e:
                    self.logger.error(f"Error in metrics logging task: {str(e)}")
                    await asyncio.sleep(60)  # Retry after a minute if there's an error

        # Start the background task
        asyncio.create_task(log_metrics_task())

    async def handle_request(self, request: Request) -> Response:
        """
        Handle an incoming proxy request.

        Args:
            request: FastAPI Request object

        Returns:
            Response to the client
        """
        start_time = time.time()

        # Identify target API based on path
        api_name, _ = self.parse_request(request)
        api_config = self.config.get_api_config(api_name)

        if not api_name:
            return JSONResponse(
                status_code=404, content={"error": "Unknown API endpoint"}
            )

        try:
            # Check endpoint-level rate limiting
            self._check_endpoint_rate_limit(api_name)

            # Get target endpoint configuration
            if not api_config.get("endpoint"):
                self.logger.error(f"No target endpoint configured for API: {api_name}")
                return JSONResponse(
                    status_code=500, content={"error": "API endpoint not configured"}
                )

            # Prepare and execute request
            request_data = await self._prepare_request(request)

            # Process request and handle response
            return await self._process_request_and_return_response(
                request_data, start_time
            )

        except EndpointRateLimitExceededError as e:
            return await self._handle_rate_limit_exceeded(request, api_name)
        except ApiKeyRateLimitExceededError:
            return await self._handle_rate_limit_exceeded(request, api_name)
        except Exception as e:
            return self._handle_request_exception(
                e, start_time, api_name, request_data.api_key if request_data else None
            )

    def _check_endpoint_rate_limit(self, api_name: str) -> None:
        """
        Check if the endpoint rate limit is exceeded.

        Args:
            api_name: Name of the API

        Raises:
            RateLimitExceededError: If rate limit is exceeded
        """
        endpoint_limiter: RateLimiter = self.rate_limiters.get(f"{api_name}_endpoint")

        if endpoint_limiter and not endpoint_limiter.allow_request():
            remaining = endpoint_limiter.get_reset_time()
            self.logger.warning(
                f"Endpoint rate limit exceeded for {api_name}, reset in {remaining:.2f}s"
            )
            raise EndpointRateLimitExceededError(api_name, reset_in_seconds=remaining)

    async def _process_request_and_return_response(
        self,
        r: NyaRequest,
        start_time: float,
    ) -> Response:
        """
        Process the prepared request and handle the response.

        Args:
            r: Prepared NyaRequest object
            start_time: Request start time

        Returns:
            Response to the client
        """
        self.logger.debug(f"Processing request to {r.api_name}: {r.url}")

        # Get API request settings]

        api_config = self.config.get_api_config(r.api_name)
        retry_config: Dict = api_config.get("retry", {})
        retry_enabled = retry_config.get("enabled", True)
        retry_mode = retry_config.get("mode", "default")

        if not retry_enabled:
            retry_attempts = 1
            retry_delay = 0
        else:
            retry_attempts = retry_config.get("attempts", 3)
            retry_delay = retry_config.get("retry_after_seconds", 10)

        # Execute the request with retries if configured
        httpx_response = await self.request_executor.execute_with_retry(
            r=r,
            max_attempts=retry_attempts,
            retry_delay=retry_delay,
            retry_mode=retry_mode,
        )

        # If rate limit exceeded, queue the request if enabled
        if (
            httpx_response
            and httpx_response.status_code == 429
            and self.config.get_queue_enabled()
            and self.request_queue
        ):
            return await self._handle_rate_limit_exceeded(
                request=r._raw_request,
                api_name=r.api_name,
            )

        # Process and return the response
        return await self.response_processor.process_response(
            httpx_response, start_time, r.api_name, r.api_key, self.metrics_collector
        )

    def _handle_request_exception(
        self,
        exception: Exception,
        start_time: float,
        api_name: str,
        api_key: Optional[str] = None,
    ) -> Response:
        """
        Handle any other exception that occurs during request processing.

        Args:
            exception: The exception that was raised
            start_time: Request start time for timing calculation
            api_name: Name of the API being accessed

        Returns:
            Error response
        """
        elapsed = time.time() - start_time
        self.logger.error(f"Error handling request to {api_name}: {str(exception)}")
        self.logger.debug(traceback.format_exc())

        # Record error in metrics if available
        if self.metrics_collector:
            self.metrics_collector.record_response(
                api_name, api_key if api_key else "unknown", 500, elapsed
            )

        return self.response_processor.create_error_response(
            exception, status_code=500, api_name=api_name
        )

    async def _handle_rate_limit_exceeded(
        self,
        request: Request,
        api_name: str,
    ) -> Response:
        """
        Handle a rate-limited request, queueing it if enabled.

        Args:
            request: Original request
            api_name: Name of the API

        Returns:
            Response to the client
        """
        # If queueing is enabled, try to queue and process the request
        if self.request_queue and self.config.get_queue_enabled():
            try:
                # Calculate appropriate reset time based on rate limit and queue wait time
                reset_in_seconds = int(
                    max(
                        self.key_manager.get_rate_limit_reset_time(api_name),
                        self.request_queue.get_estimated_wait_time(api_name),
                    )
                )
                try:
                    self.logger.info(
                        f"Queueing request to {api_name} due to rate limiting"
                    )

                    # Record queue hit in metrics
                    if self.metrics_collector:
                        self.metrics_collector.record_queue_hit(api_name)
                        self.metrics_collector.record_rate_limit_hit(
                            api_name, "unknown"
                        )

                    request_data = NyaRequest(
                        method=request.method,
                        url=str(request.url),
                        _raw_request=request,
                        api_name=api_name,
                    )

                    # Enqueue the request and wait for response
                    future = await self.request_queue.enqueue_request(
                        r=request_data,
                        reset_in_seconds=reset_in_seconds,
                    )

                    self.logger.info(
                        f"Waiting for queued request to {api_name} to complete"
                    )

                    api_timeout = self.config.get_api_default_timeout(api_name)
                    timeout = reset_in_seconds + api_timeout

                    return await asyncio.wait_for(future, timeout=timeout)

                except asyncio.TimeoutError:
                    return self.response_processor.create_error_response(
                        Exception(f"Request timed out after {timeout} seconds"),
                        status_code=504,
                        api_name=api_name,
                    )
                except ValueError as ve:
                    # Queue full or other queue errors
                    self.logger.warning(f"Request queuing failed: {str(ve)}")
                    return self.response_processor.create_error_response(
                        ve, status_code=429, api_name=api_name
                    )
                except Exception as e:
                    self.logger.error(f"Error processing queued request: {str(e)}")
                    return self.response_processor.create_error_response(
                        e, status_code=500, api_name=api_name
                    )

            except Exception as queue_error:
                self.logger.error(
                    f"Error queueing request: {str(queue_error)}, {traceback.format_exc() if self.config.get_debug_level().upper() == 'DEBUG' else ''}"
                )
                # Continue to normal rate limit response

        # Default rate limit response if queueing is disabled or failed
        return JSONResponse(
            status_code=429, content={"error": "Rate limit exceeded for this endpoint"}
        )

    async def _prepare_request(
        self,
        request: Request,
    ) -> NyaRequest:
        """
        Prepare the request for forwarding to the target API.

        Args:
            request: Original request

        Returns:
            NyaRequest object or Response if error

        Raises:
            NoAvailableKeysError: If no API keys are available
        """

        # Identify target API based on path
        api_name, trail_path = self.parse_request(request)
        api_config = self.config.get_api_config(api_name)

        # Get the load balancer for this API
        key_variable = api_config.get("key_variable", "keys")
        load_balancer = self.load_balancers.get(api_name)

        if not load_balancer:
            self.logger.error(f"No load balancer found for API: {api_name}")
            raise ValueError(f"API configuration error for {api_name}")

        # Get the next key/token and check its rate limit
        api_key = await self.key_manager.get_available_key(api_name, load_balancer)

        if api_key is None:
            raise ApiKeyRateLimitExceededError(api_name)

        # Read request body
        body = await request.body()

        # Apply path rewriting if configured
        target_path = self._rewrite_path(trail_path, api_config)

        # Construct target api endpoint URL
        target_endpoint: str = api_config.get("endpoint", "")
        target_url = f"{target_endpoint}{target_path}"

        # Prepare headers with variable substitution
        headers = await self._prepare_custom_headers(
            request, api_name, api_config, key_variable, api_key
        )

        # Create NyaRequest object
        req = NyaRequest(
            method=request.method,
            url=target_url,
            _raw_request=request,
            headers=headers,
            content=body or None,
            api_name=api_name,
            api_key=api_key,
        )

        # Record request metrics
        if self.metrics_collector:
            self.metrics_collector.record_request(api_name, api_key)
            load_balancer.record_request_count(api_key)

        return req

    def _rewrite_path(self, path: str, api_config: Dict[str, Any]) -> str:
        """
        Apply path rewriting based on configuration.

        Args:
            path: Original path
            api_config: API configuration

        Returns:
            Rewritten path
        """
        # Check for path_rewrites in configuration
        path_rewrites = api_config.get("path_rewrites", {})

        if not path_rewrites:
            # No rewrites, handle base_path
            base_path = api_config.get("base_path", "")
            if base_path:
                # Ensure base_path starts with a slash but doesn't end with one
                if not base_path.startswith("/"):
                    base_path = "/" + base_path
                if base_path.endswith("/"):
                    base_path = base_path[:-1]

                # Combine base path with original path
                return f"{base_path}{path}"
            return path

        # Apply path rewriting rules
        rewritten_path = path

        # Sort rules by specificity (longer patterns first)
        sorted_rules = sorted(
            path_rewrites.items(), key=lambda x: len(x[0]), reverse=True
        )

        # Apply the first matching rule
        for pattern, replacement in sorted_rules:
            if pattern in path:
                rewritten_path = path.replace(pattern, replacement)
                self.logger.debug(f"Rewriting path: {path} -> {rewritten_path}")
                break

        return rewritten_path

    async def _prepare_custom_headers(
        self,
        request: Request,
        api_name: str,
        api_config: Dict[str, Any],
        key_variable: str,
        key: str,
    ) -> Dict[str, str]:
        """
        Prepare headers with variable substitution

        Args:
            request: Original request
            api_name: Name of the API
            api_config: API configuration
            key_variable: Name of the key variable
            key: The selected API key/token

        Returns:
            Headers dictionary
        """
        # Get configured headers
        header_config: Dict[str, Any] = api_config.get("headers", {})

        # Identify all variables needed in headers
        required_vars = self.header_processor.extract_required_variables(header_config)

        # Prepare variable values
        var_values = {key_variable: key}

        # Get values for other variables from load balancers
        for var in required_vars:
            if var == key_variable:
                continue

            variable_balancer = self.load_balancers.get(f"{api_name}_{var}")
            if variable_balancer:
                variable_value = variable_balancer.get_next()
                var_values[var] = variable_value
            else:
                # Try to get from single-value variables in config
                variables = api_config.get("variables", {})
                if var in variables and not isinstance(variables[var], list):
                    var_values[var] = variables[var]
                else:
                    var_values[var] = var  # Fallback to variable name

        # Process headers with variable substitution
        return self.header_processor._process_headers(
            header_templates=header_config,
            variable_values=var_values,
            original_headers=dict(request.headers),
        )

    async def _process_queued_request(self, r: NyaRequest) -> Response:
        """
        Process a request from the queue.

        Args:
            r: NyaRequest object containing the queued request data

        Returns:
            Response from the target API
        """
        return await self.handle_request(r._raw_request)

    def parse_request(self, request: Request) -> Tuple[Optional[str], Optional[str]]:
        """
        Determine which API to route to based on the request path.

        Args:
            request: FastAPI request object

        Returns:
            Tuple of (api_name, remaining_path)

        Examples:
            /api/openai/v1/chat/completions -> ("openai", "/v1/chat/completions")

            if api has aliases (/reddit, /r):
                /api/r/v1/messages -> ("reddit", "/v1/messages")
        """
        path = request.url.path
        apis_config = self.config.get_apis()
        self.logger.debug(f"Identifying target API for path: {path}")

        # Handle non-API paths or malformed requests
        if not path or not path.startswith(API_PATH_PREFIX):
            return None, None

        # Extract parts after "/api/"
        api_path = path[len(API_PATH_PREFIX) :]

        # Handle empty path after prefix
        if not api_path:
            return None, None

        # Split into endpoint and trail path
        parts = api_path.split("/", 1)
        endpoint = parts[0]
        trail_path = "/" + parts[1] if len(parts) > 1 else "/"

        # Direct match with API name
        if endpoint in apis_config:
            return endpoint, trail_path

        # Check for aliases in each API config
        for api_name, config in apis_config.items():
            aliases = config.get("aliases", [])
            if aliases and endpoint in aliases:
                return api_name, trail_path

        # No match found
        self.logger.warning(f"No API configuration found for endpoint: {endpoint}")
        return None, None, None

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
