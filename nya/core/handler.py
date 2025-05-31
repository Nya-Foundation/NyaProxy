"""
Proxy handler for intercepting and forwarding HTTP requests with token rotation.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

from ..common.constants import API_PATH_PREFIX
from ..common.exceptions import (
    EndpointRateLimitExceededError,
    VariablesConfigurationError,
)
from ..common.models import AdvancedConfig, ProxyRequest
from ..config.manager import ConfigManager
from ..utils.header import HeaderUtils

if TYPE_CHECKING:
    from ..services.key import KeyManager
    from ..services.limit import RateLimiter
    from ..services.metrics import MetricsCollector


class RequestHandler:
    """
    Handles the processing of individual requests including preparation,
    validation, and key management.
    """

    def __init__(
        self,
        config: ConfigManager,
        key_manager: "KeyManager",
        metrics_collector: Optional["MetricsCollector"] = None,
    ):
        """
        Initialize the request handler.

        Args:
            config: Configuration manager instance
            key_manager: Key manager instance
            metrics_collector: Metrics collector instance (optional)
        """
        self.config = config
        self.key_manager = key_manager
        self.metrics_collector = metrics_collector
        self.load_balancers = {}  # Will be set from outside

    def prepare_request(self, request: ProxyRequest) -> Tuple[str, str, str]:
        """
        Prepare a request for forwarding by identifying target API and setting config.

        Args:
            request: ProxyRequest object to prepare

        Returns:
            Tuple of (api_name, trail_path, target_url)
        """
        # Identify target API based on path
        api_name, trail_path = self.parse_request(request)

        # Construct target api endpoint URL
        target_endpoint: str = self.config.get_api_endpoint(api_name)
        target_url = f"{target_endpoint}{trail_path}"

        request.api_name = api_name
        request.url = target_url

        # Map advanced configurations for the request
        kwargs = self.config.get_api_advanced_configs(api_name)
        adv_config = AdvancedConfig(**kwargs)
        request._config = adv_config

        return api_name, trail_path, target_url

    def parse_request(
        self, request: ProxyRequest
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Determine which API to route to based on the request path.

        Args:
            request: ProxyRequest object

        Returns:
            Tuple of (api_name, remaining_path)
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
        logger.warning(f"No API configuration found for endpoint: {api_name}")
        return None, None

    def should_apply_rate_limit(self, api_name: str, path: str) -> bool:
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
        logger.debug(
            f"Path {path} not in rate_limit_paths for {api_name}, skipping rate limiting"
        )
        return False

    def check_endpoint_rate_limit(self, api_name: str) -> None:
        """
        Check if the endpoint rate limit is exceeded.

        Args:
            api_name: Name of the API

        Raises:
            EndpointRateLimitExceededError: If rate limit is exceeded
        """
        endpoint_limiter: Optional[RateLimiter] = self.key_manager.get_api_rate_limiter(
            api_name
        )

        if endpoint_limiter and not endpoint_limiter.allow_request():
            remaining = endpoint_limiter.get_reset_time()
            logger.warning(
                f"Endpoint rate limit exceeded for {api_name}, reset in {remaining:.2f}s"
            )
            raise EndpointRateLimitExceededError(api_name, reset_in_seconds=remaining)

    async def set_request_headers(self, request: ProxyRequest) -> None:
        """
        Set headers for the request, including API key and custom headers.

        Args:
            request: ProxyRequest object

        Raises:
            VariablesConfigurationError: If variable configuration is incorrect
            APIKeyExhaustedError: If no API keys are available
        """
        api_name = request.api_name

        # if api_key is not set, get an available key from the key manager
        request.api_key = (
            request.api_key
            if request.api_key
            else await self.key_manager.get_available_key(
                api_name, request._apply_rate_limit
            )
        )

        # Get key variable for the API
        key_variable = self.config.get_api_key_variable(api_name)

        # Get custom headers configuration for the API
        header_config: Dict[str, Any] = self.config.get_api_custom_headers(api_name)

        # Identify all template variables in headers that needs to be substituted
        required_vars = HeaderUtils.extract_required_variables(header_config)

        var_values: Dict[str, Any] = {key_variable: request.api_key}

        # Get values for other variables from load_balancers
        for var in required_vars:
            if var == key_variable:
                continue

            variable_balancer = self.load_balancers.get(f"{api_name}_{var}")
            if not variable_balancer:
                raise VariablesConfigurationError(
                    f"Variable configuration error for {var} in {api_name}"
                )

            variable_value = variable_balancer.get_next()
            var_values[var] = variable_value

        # Process headers with variable substitution
        headers = HeaderUtils.process_headers(
            header_templates=header_config,
            variable_values=var_values,
            original_headers=dict(request.headers),
        )

        parsed_url = urlparse(request.url)
        headers["host"] = parsed_url.netloc

        request.headers = headers
