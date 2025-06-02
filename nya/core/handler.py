"""
Request handler for intercepting and forwarding HTTP requests with token rotation.
"""

import random
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import orjson
from loguru import logger

from ..common.constants import API_PATH_PREFIX
from ..common.exceptions import MissingAPIKeyError, VariablesConfigurationError
from ..common.models import ProxyRequest
from ..config.manager import ConfigManager
from ..utils.header import HeaderUtils
from ..utils.helper import apply_body_substitutions


class RequestHandler:
    """
    Handles the processing of individual requests including preparation,
    validation, and key management.
    """

    def __init__(
        self,
    ):
        """
        Initialize the request handler.

        Args:
            key_manager: Key manager instance
        """
        self.config = ConfigManager.get_instance()

        if not self.config:
            raise ValueError("ConfigManager instance is not initialized.")

    def prepare_request(self, request: ProxyRequest) -> None:
        """
        Prepare a request for forwarding by identifying target API and setting config.

        Args:
            request: ProxyRequest object to prepare
        """
        # Identify target API based on path
        api_name, trail_path = self.parse_request(request)

        # Construct target api endpoint URL
        target_endpoint: str = self.config.get_api_endpoint(api_name)
        target_url = f"{target_endpoint}{trail_path}"

        request.url = target_url
        request.api_name = api_name

        request._rate_limited = self.should_enforce_rate_limit(api_name, trail_path)

        # parse the original request ip from proxy headers
        proxy_ip = HeaderUtils.parse_source_ip_address(request.headers)
        request.ip = proxy_ip if proxy_ip else request.ip

        # Set request priority based on Master API key presence
        self.check_priority_request(request)

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
            if aliases and parts[0] in aliases:
                return api_name, trail_path

        # No match found
        logger.warning(f"No API configuration found for endpoint: {api_name}")
        return None, None

    def check_priority_request(self, request: ProxyRequest) -> None:
        """
        Handle priority requests that require immediate processing.

        Args:
            request: ProxyRequest object to process
        """
        authorization_header = request.headers.get("Authorization")

        token = (
            authorization_header.split("Bearer ")[-1] if authorization_header else None
        )
        if not token:
            return

        keys = self.config.get_api_key()
        if not keys:
            return

        if (isinstance(keys, str) and token == keys) or (
            isinstance(keys, list) and token == keys[0]
        ):
            request.priority = 2

    def should_enforce_rate_limit(self, api_name: str, path: str) -> bool:
        """
        Check if rate limiting should be applied for the given API and path.

        Args:
            api_name: Name of the API endpoint
            path: Request path to check

        Returns:
            bool: True if rate limiting should be applied, False otherwise
        """

        rate_limit_enabled = self.config.get_api_rate_limit_enabled(api_name)

        if not rate_limit_enabled:
            return False

        # Get rate limit paths from config, default to ['*'] (all paths)
        rate_limit_paths = self.config.get_api_rate_limit_paths(api_name)

        # If no paths are specified or '*' is in the list, apply to all paths
        if not rate_limit_paths or "*" in rate_limit_paths:
            return True

        # Check each pattern against the path
        for pattern in rate_limit_paths:
            if pattern == path or path.startswith(pattern.rstrip("*")):
                return True

        return False

    def process_request_body(self, request: ProxyRequest) -> None:
        """
        Modify the request body if needed.

        This method can be overridden to implement custom request body modifications.
        """
        body_subst_enabled = self.config.get_api_request_body_substitution_enabled(
            request.api_name
        )

        if not body_subst_enabled:
            return

        content_type = request.headers.get("content-type", "").lower()
        if "application/json" not in content_type:
            return

        rules = self.config.get_api_request_subst_rules(request.api_name)
        if not rules:
            return

        modified_content = apply_body_substitutions(request.content, rules)
        request.content = orjson.dumps(modified_content)

        logger.debug("Request body substitutions applied successfully")

    async def process_request_headers(self, request: ProxyRequest) -> None:
        """
        Set headers for the request, including API key and custom headers.

        Args:
            request: ProxyRequest object

        Raises:
            VariablesConfigurationError: If variable configuration is incorrect
        """
        api_name = request.api_name

        # Ensure we have an API key
        if not request.api_key:
            raise MissingAPIKeyError(f"Missing API key for {api_name}")

        # Get key variable for the API
        key_variable = self.config.get_api_key_variable(api_name)

        # Get custom headers configuration for the API
        header_config: Dict[str, Any] = self.config.get_api_custom_headers(api_name)

        # Identify all template variables in headers that needs to be substituted
        required_vars = HeaderUtils.extract_required_variables(header_config)

        required_vars.remove(key_variable)  # Remove key variable if present
        var_values: Dict[str, Any] = {key_variable: request.api_key}

        # Ensure host header set to the target URL's host
        parsed_url = urlparse(request.url)
        request.headers["host"] = parsed_url.netloc

        try:
            # Get values for other variables from load_balancers
            for var in required_vars:
                # randomly select a value for the variable from the configured values
                variables = self.config.get_api_variable_values(api_name, var)
                value = random.choice(variables) if variables else None
                var_values[var] = value

            # Process headers with variable substitution
            processed_headers = HeaderUtils.process_headers(
                header_config, var_values, original_headers=dict(request.headers)
            )
            request.headers = HeaderUtils.merge_headers(
                request.headers, processed_headers
            )

        except Exception as e:
            raise VariablesConfigurationError(
                f"Header processing failed for {api_name}: {str(e)}"
            )
