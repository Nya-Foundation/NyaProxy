"""
Proxy handler for intercepting and forwarding HTTP requests with token rotation.
"""

import gzip
import json
import logging
import time
import traceback
import zlib
from typing import Any, Dict, Optional, Tuple, Union

import brotli
import httpx
from fastapi import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .config_manager import ConfigManager
from .load_balancer import LoadBalancer
from .metrics import MetricsCollector
from .rate_limiter import RateLimiter
from .request_executor import RequestExecutor
from .request_queue import RequestQueue


class ProxyHandler:
    """
    Handles proxy requests, token rotation, and load balancing.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        logger: logging.Logger,
        request_queue: Optional[RequestQueue] = None,
        metrics_collector: Optional[MetricsCollector] = None,
    ):
        """
        Initialize the proxy handler.

        Args:
            config_manager: Configuration manager instance
            logger: Logger instance
            request_queue: Request queue instance (optional)
            metrics_collector: Metrics collector instance (optional)
        """
        self.config_manager = config_manager
        self.logger = logger
        self.request_queue = request_queue
        self.metrics_collector = metrics_collector

        # Initialize dictionaries for load balancers and rate limiters
        self.load_balancers: Dict[str, LoadBalancer] = {}
        self.rate_limiters: Dict[str, RateLimiter] = {}

        # Set up HTTP client
        self.client = None
        self.setup_client()

        # Initialize load balancers and rate limiters
        self.initialize_load_balancers()
        self.initialize_rate_limiters()

        # Create request executor
        self.request_executor = RequestExecutor(
            self.client,
            self.config_manager.get_default_settings(),
            self.logger,
            self.metrics_collector,
        )

        # Register request processor with queue if present
        if self.request_queue:
            self.request_queue.register_processor(self._process_queued_request)

    def setup_client(self):
        """Set up the HTTP client with proxy configuration if enabled."""
        proxy_settings = self.config_manager.get_proxy_settings()

        # Configure client with appropriate settings
        client_kwargs = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(60.0),  # Default timeout of 60 seconds
        }

        if proxy_settings["enabled"] and proxy_settings["address"]:
            client_kwargs["proxies"] = proxy_settings["address"]
            self.logger.info(f"Using proxy: {proxy_settings['address']}")

        self.client = httpx.AsyncClient(**client_kwargs)

    def initialize_load_balancers(self):
        """Initialize load balancers for each API endpoint."""
        apis = self.config_manager.get_apis()
        default_settings = self.config_manager.get_default_settings()

        default_strategy = default_settings.get(
            "load_balancing_strategy", "round_robin"
        )

        for api_name, api_config in apis.items():

            strategy = api_config.get("load_balancing_strategy", default_strategy)
            key_variable = api_config.get("key_variable", "keys")

            # Get tokens/keys for this API
            keys = self.config_manager.get_api_variables(api_name, key_variable)
            if not keys:
                self.logger.warning(f"No keys/tokens found for API: {api_name}")
                continue

            # Create load balancer for this API
            self.load_balancers[api_name] = LoadBalancer(keys, strategy, self.logger)

            # Initialize other variables if needed
            for variable_name in api_config.get("variables", {}).keys():
                if variable_name != key_variable:
                    values = self.config_manager.get_api_variables(
                        api_name, variable_name
                    )
                    if values:
                        self.load_balancers[f"{api_name}_{variable_name}"] = (
                            LoadBalancer(values, strategy, self.logger)
                        )

    def initialize_rate_limiters(self):
        """Initialize rate limiters for each API endpoint."""
        apis = self.config_manager.get_apis()
        default_settings = self.config_manager.get_default_settings()
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
            self.rate_limiters[f"{api_name}_endpoint"] = RateLimiter(endpoint_limit)

            # Create rate limiter for each key
            key_variable = api_config.get("key_variable", "keys")
            keys = self.config_manager.get_api_variables(api_name, key_variable)

            for key in keys:
                self.rate_limiters[f"{api_name}_{key}"] = RateLimiter(key_limit)

    async def handle_request(self, request: Request) -> Response:
        """
        Handle an incoming proxy request.

        Args:
            request: FastAPI Request object

        Returns:
            Response to the client
        """
        start_time = time.time()
        path = request.url.path

        # Identify target API based on path
        api_name, trail_path, api_config = self._parse_request(path)

        if not api_name:
            return JSONResponse(
                status_code=404, content={"error": "Unknown API endpoint"}
            )

        try:
            # Check endpoint-level rate limiting
            is_endpoint_allowed = await self._check_endpoint_rate_limit(
                api_name, api_config, path
            )

            if not is_endpoint_allowed:
                self.logger.warning(f"Rate limit exceeded for endpoint: {api_name}")
                return await self._handle_rate_limit_exceeded(
                    request,
                    api_name,
                    trail_path,
                    api_config,
                )

            # Get target endpoint configuration
            target_endpoint = api_config.get("endpoint")
            if not target_endpoint:
                self.logger.error(f"No target endpoint configured for API: {api_name}")
                return JSONResponse(
                    status_code=500, content={"error": "API endpoint not configured"}
                )

            # Prepare and execute request
            request_data = await self._prepare_request(
                request, api_name, trail_path, api_config
            )

            if isinstance(request_data, Response):  # Error occurred during preparation
                return request_data

            # Process request and handle response
            return await self._process_and_handle_response(
                request_data, api_name, api_config, start_time
            )

        except Exception as e:
            return self._handle_request_exception(
                e, start_time, api_name if "api_name" in locals() else "unknown"
            )

    async def _process_and_handle_response(
        self,
        request_data: Dict[str, Any],
        api_name: str,
        api_config: Dict[str, Any],
        start_time: float,
    ) -> Response:
        """
        Process the prepared request and handle the response.

        Args:
            request_data: Prepared request data
            api_name: Name of the API
            api_config: API configuration
            start_time: Request start time

        Returns:
            Response to the client
        """
        self.logger.debug(f"Processing and handle request to {api_name}")

        # Record request metrics
        if self.metrics_collector:
            key_id = self._get_key_id_for_metrics(
                request_data.get("_key_used", "unknown")
            )
            self.metrics_collector.record_request(api_name, key_id)

        # Get API request settings
        retry_config: Dict = api_config.get("retry", api_config.get("retry", {}))
        retry_enabled = retry_config.get("enabled", True)

        if not retry_enabled:
            retry_attempts = 1
            retry_delay = 0
        else:
            retry_attempts = retry_config.get("attempts", None)
            retry_delay = retry_config.get("retry_after_seconds", None)

        # Execute the request with retries if configured
        httpx_response = await self.request_executor.execute_with_retry(
            request_data=request_data,
            max_attempts=retry_attempts,
            retry_delay=retry_delay,
            api_name=api_name,
        )

        # Log request timing and record metrics
        elapsed = time.time() - start_time
        status_code = httpx_response.status_code if httpx_response else 502

        self.logger.debug(
            f"Received response from {api_name} with status {status_code} in {elapsed:.2f}s"
        )

        if self.metrics_collector:
            self.metrics_collector.record_response(api_name, status_code, elapsed)

        if not httpx_response:
            return JSONResponse(
                status_code=502,
                content={"error": "Bad Gateway: No response from target API"},
            )

        # Check if response is JSON for debug logging
        if httpx_response.headers.get("content-type", "").startswith(
            "application/json"
        ):
            try:
                self.logger.debug(
                    f"Response content:\n{json.dumps(httpx_response.json(), indent=4, ensure_ascii=False)}"
                )
            except Exception:
                self.logger.debug("Response contains non-JSON content")
        else:
            self.logger.debug(
                f"Response content type: {httpx_response.headers.get('content-type')}"
            )

        self.logger.debug(f"Response status code: {httpx_response.status_code}")
        self.logger.debug(f"Response headers: {httpx_response.headers}")

        # Filter out unwanted headers
        filtered_headers = dict(httpx_response.headers)
        headers_to_remove = ["server", "date", "transfer-encoding"]

        for header in headers_to_remove:
            if header.lower() in filtered_headers:
                del filtered_headers[header.lower()]

        # Determine the response content type
        content_type = httpx_response.headers.get("content-type", "application/json")
        content_encoding = httpx_response.headers.get("content-encoding", "identity")
        filtered_headers.pop("content-encoding", None)

        # Handle streaming response for event-stream
        if "text/event-stream" in content_type:
            self.logger.debug("Detected streaming response, forwarding as event-stream")

            return StreamingResponse(
                content=httpx_response.aiter_bytes(),
                status_code=status_code,
                media_type="text/event-stream",
                headers=filtered_headers,
            )

        # Decode response body for normal responses (non-streaming)
        raw_content = self.decode_content(httpx_response.content, content_encoding)

        # Handle normal JSON response
        return Response(
            content=raw_content,
            status_code=status_code,
            media_type="application/json",
            headers=filtered_headers,
        )

    def decode_content(self, content: bytes, encoding: str) -> bytes:
        try:
            if encoding == "gzip" and content and content[:2] == b"\x1f\x8b":
                # GZIP magic number: 1f 8b
                return gzip.decompress(content)
            elif encoding == "deflate" and content and content[0] == 0x78:
                # Zlib-wrapped deflate typically starts with 0x78
                return zlib.decompress(content)
            elif encoding == "br":
                # No strict magic number for Brotli, but try-catch should works
                return brotli.decompress(content)
        except Exception as e:
            self.logger.warning(f"Decompression failed for encoding '{encoding}': {e}")

        return content  # fallback to raw

    def _parse_request(
        self, path: str
    ) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """
        Determine which API to route to based on path and parse the remaining path.

        Args:
            path: Request path

        Returns:
            Tuple of (api_name, remaining_path, api_config)

        Examples:
            /api/openai/v1/chat/completions -> ("openai", "/v1/chat/completions", config_for_openai)

            if api has aliases (/reddit, /r):
                /api/r/v1/messages -> ("reddit", "/v1/messages", config_for_reddit)
        """
        self.logger.debug(f"Identifying target API for path: {path}")
        apis = self.config_manager.get_apis()

        # Handle non-API paths or malformed requests
        if not path.startswith("/api/"):
            return None, None, None

        # Extract parts after "/api/"
        api_path = path.removeprefix("/api/")
        parts = api_path.split("/", 1)

        endpoint = parts[0]
        trail_path = "/" + parts[1] if len(parts) > 1 else ""

        # Direct match with API name
        if endpoint in apis:
            return endpoint, trail_path, apis[endpoint]

        # Check for aliases in aliases
        for api_name, config in apis.items():
            aliases = config.get("aliases", [])
            if aliases and endpoint in aliases:
                return api_name, trail_path, apis[api_name]

        # No match found
        return None, None, None

    async def _check_endpoint_rate_limit(
        self, api_name: str, api_config: Dict[str, Any], path: str
    ) -> bool:
        """
        Check if endpoint rate limit is exceeded.

        Args:
            api_name: Name of the API
            api_config: API configuration
            path: Request path

        Returns:
            True if request is allowed, False if rate limited
        """
        endpoint_limiter = self.rate_limiters.get(f"{api_name}_endpoint")
        if endpoint_limiter and not endpoint_limiter.allow_request():
            self.logger.warning(f"Endpoint rate limit exceeded for {api_name}")
            return False
        return True

    def _get_key_id_for_metrics(self, key: str) -> str:
        """
        Get a key identifier for metrics that doesn't expose the full key.

        Args:
            key: The API key or token

        Returns:
            A truncated version of the key for metrics
        """
        return key[:5] + "..." if len(key) > 5 else key

    def _handle_request_exception(
        self, exception: Exception, start_time: float, api_name: str
    ) -> Response:
        """
        Handle any exception that occurs during request processing.

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
            self.metrics_collector.record_response(api_name, 500, elapsed)

        return JSONResponse(
            status_code=500,
            content={"error": f"Internal proxy error: {str(exception)}"},
        )

    async def _handle_rate_limit_exceeded(
        self,
        request: Request,
        api_name: str,
        trail_path: str,
        api_config: Dict[str, Any],
    ) -> Response:
        """
        Handle a rate-limited request, queueing it if enabled.

        Args:
            request: Original request
            api_name: Name of the API
            trail_path: The remaining path after the API name
            api_config: API configuration


        Returns:
            Response to the client
        """
        # If queueing is enabled, try to queue the request
        if self.request_queue and self.config_manager.get_queue_enabled():
            try:
                # First, prepare the request as we would for direct execution
                processed_request = await self._prepare_request(
                    request, api_name, trail_path, api_config
                )
                if isinstance(processed_request, Response):  # Error during preparation
                    return processed_request

                # Calculate appropriate expiry time based on rate limit reset
                endpoint_limiter = self.rate_limiters.get(f"{api_name}_endpoint")
                expiry_seconds = endpoint_limiter.get_reset_time() + 5.0  # Add a buffer

                # Queue the request
                queued = self.request_queue.enqueue_request(
                    api_name=api_name,
                    request_data=processed_request,
                    expiry_seconds=expiry_seconds,
                )

                if queued:
                    # Record queue hit in metrics
                    if self.metrics_collector:
                        self.metrics_collector.record_queue_hit(api_name)

                    self.logger.info(
                        f"Request to {api_name} queued due to rate limiting"
                    )
                    queue_size = self.request_queue.get_queue_size(api_name)
                    return JSONResponse(
                        status_code=202,  # Accepted
                        content={
                            "status": "queued",
                            "message": f"Request queued due to rate limiting (queue position: {queue_size})",
                            "queue_size": queue_size,
                            "estimated_wait": expiry_seconds,
                        },
                    )
            except Exception as queue_error:
                self.logger.error(f"Error queuing request: {str(queue_error)}")
                # Continue to normal rate limit response if queuing fails

        return JSONResponse(
            status_code=429, content={"error": "Rate limit exceeded for this endpoint"}
        )

    async def _prepare_request(
        self,
        request: Request,
        api_name: str,
        trail_path: str,
        api_config: Dict[str, Any],
    ) -> Union[Dict[str, Any], Response]:
        """
        Prepare the request for forwarding to the target API.

        Args:
            request: Original request
            api_name: Name of the API
            trail_path: the remaining path after the API name
            api_config: API configuration

        Returns:
            Dictionary with request data or Response if error
        """
        # Get the load balancer for this API
        key_variable = api_config.get("key_variable", "keys")
        load_balancer = self.load_balancers.get(api_name)

        if not load_balancer:
            self.logger.error(f"No load balancer found for API: {api_name}")
            return JSONResponse(
                status_code=500, content={"error": "API configuration error"}
            )

        # Get the next key/token and check its rate limit
        key = await self._get_available_key(api_name, load_balancer)

        if key is None:
            if self.metrics_collector:
                self.metrics_collector.record_rate_limit_hit(api_name)

            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded for all available keys"},
            )

        # Read request body
        body = await request.body()

        # Construct target api endpoint URL
        target_endpoint: str = api_config.get("endpoint", "")
        target_url = f"{target_endpoint}{trail_path}"

        # Prepare headers with variable substitution
        headers = await self._prepare_custom_headers(
            request, api_name, api_config, key_variable, key
        )

        # Prepare the request data
        request_data = {
            "method": request.method,
            "url": target_url,
            "headers": headers,
            "content": body or None,
            "_key_used": key,  # Store the key for metrics tracking
            "_api_name": api_name,  # Store API name for queued requests
        }

        return request_data

    async def _get_available_key(
        self, api_name: str, load_balancer: LoadBalancer
    ) -> Optional[str]:
        """
        Get an available key that hasn't exceeded its rate limit.

        Args:
            api_name: Name of the API
            load_balancer: Load balancer for the API

        Returns:
            An available key or None if all keys are rate limited
        """
        # Try to find a key that isn't rate limited
        tried_keys = set()
        key = load_balancer.get_next()

        while key not in tried_keys:
            tried_keys.add(key)
            key_limiter = self.rate_limiters.get(f"{api_name}_{key}")

            if not key_limiter or key_limiter.allow_request():
                return key

            # Try the next key
            key = load_balancer.get_next()

        # If we've tried all keys and none are available, return None
        return None

    def identify_template_variables(self, template_string: str) -> list:
        """
        Identify all dynamic variables in a template string using ${{var}} syntax.

        Args:
            template_string (str): The string containing potential template variables

        Returns:
            list: List of variable names found in the template
        """
        variables = []
        i = 0
        while i < len(template_string):
            start_idx = template_string.find("${{", i)
            if start_idx == -1:
                break

            end_idx = template_string.find("}}", start_idx)
            if end_idx == -1:
                break

            var_name = template_string[start_idx + 3 : end_idx].strip()
            variables.append(var_name)
            i = end_idx + 2

        return variables

    def replace_template_variables(
        self, template_string: str, replacements: Dict[str, str]
    ) -> str:
        """
        Replace all template variables in a string with their values.

        Args:
            template_string (str): The template string containing variables like ${{variable_name}}
            replacements (dict): Dictionary mapping variable names to their values

        Returns:
            str: The template with all variables replaced
        """
        result = template_string
        for var_name, value in replacements.items():
            placeholder = f"${{{{{var_name}}}}}"
            result = result.replace(placeholder, str(value))
        return result

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
        # Start with configured headers
        custom_headers = {}
        header_config: Dict[str, Any] = api_config.get("headers", {})

        vars_set = set()
        # Replace variables in headers
        for header_name, header_value in header_config.items():
            vars = self.identify_template_variables(header_value)
            vars_set.update(vars)

        vars_value = {}
        for var in vars_set:
            # Skip the key/token variable
            if var == key_variable:
                vars_value[var] = key
                continue
            # Get the load balancer for this variable
            variable_balancer = self.load_balancers.get(f"{api_name}_{var}")
            if variable_balancer:
                variable_value = variable_balancer.get_next()
                vars_value[var] = variable_value
            else:
                vars_value[var] = var

        # Replace template variables in custom headers
        for header_name, header_value in header_config.items():
            replaced_value = self.replace_template_variables(header_value, vars_value)
            custom_headers[header_name] = replaced_value

        # Copy original headers but allow config headers to override
        for k, v in request.headers.items():
            if k.lower() not in [h.lower() for h in custom_headers.keys()]:
                custom_headers[k] = v

        return custom_headers

    def _get_target_path(
        self, original_path: str, api_name: str, api_config: Dict[str, Any]
    ) -> str:
        """
        Get the path to use for the target API, removing proxy routing prefixes.

        Args:
            original_path: Original request path
            api_name: Name of the API
            api_config: API configuration

        Returns:
            Target path for the API request
        """
        original_path = original_path.lstrip("/")

        # Check if the path starts with the API name
        if original_path.startswith(api_name):
            return original_path[len(api_name) :]

        # Check if path starts with any of the configured aliases
        aliases = api_config.get("aliases", [])
        for subpath in aliases:
            subpath = subpath.lstrip("/")
            if original_path.startswith(subpath):
                return original_path[len(subpath) :]

        # If no match found, return the original path
        return original_path

    async def _process_queued_request(self, request_data: Dict[str, Any]) -> Response:
        """
        Process a request from the queue.

        Args:
            request_data: Request data dictionary

        Returns:
            Response from the target API
        """
        try:
            api_name = request_data.pop("_api_name", "unknown")
            key = request_data.pop("_key_used", None)

            # Execute the request
            return await self.request_executor.execute_request(request_data)
        except Exception as e:
            self.logger.error(f"Error processing queued request: {str(e)}")
            raise  # Re-raise to allow the queue to handle retry logic

    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
