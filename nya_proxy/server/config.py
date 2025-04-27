"""
Configuration manager for NyaProxy using NekoConf.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from nekoconf import ConfigAPI, NekoConf

from ..common.constants import DEFAULT_SCHEMA_NAME


class ConfigError(Exception):
    """Exception raised for configuration errors."""

    pass


class ConfigManager:
    """
    Manages configuration for NyaProxy using NekoConf.
    Provides helper methods to access configuration values.
    """

    def __init__(
        self,
        config_path: str,
        logger: Optional[logging.Logger] = None,
        callback: Optional[callable] = None,
    ):
        """
        Initialize the configuration manager.

        Args:
            config_file: Path to the configuration file
            logger: Optional logger instance
        """
        self.config: ConfigAPI = None
        self.server: NekoConf = None

        self.config_file = config_path
        self.logger = logger or logging.getLogger("nya_proxy")

        if not os.path.exists(config_path):
            raise ConfigError(f"Configuration file not found: {config_path}")

        try:
            self.config = ConfigAPI(
                config_path=config_path, schema_path=DEFAULT_SCHEMA_NAME
            )

            # Validate against the schema
            results = self.config.validate()

            if results:
                raise ConfigError(f"Configuration validation failed: {results}")
            self.server = NekoConf(self.config.config_manager)

            if callback:
                self.config.observe(callback)

        except Exception as e:
            raise ConfigError(f"Failed to load configuration: {str(e)}")

    def get_port(self) -> int:
        """Get the port for the proxy server."""
        return self.config.get_int("nya_proxy.port", 8080)

    def get_host(self) -> str:
        """Get the host for the proxy server."""
        return self.config.get_str("nay_proxy.host", "0.0.0.0")

    def get_debug_level(self) -> str:
        """Get the debug level for logging."""
        return self.config.get_str("nya_proxy.debug_level", "INFO")

    def get_dashboard_enabled(self) -> bool:
        """Check if dashboard is enabled."""
        return self.config.get_bool("nya_proxy.dashboard.enabled", True)

    def get_queue_enabled(self) -> bool:
        """Check if request queuing is enabled."""
        return self.config.get_bool("nya_proxy.queue.enabled", True)

    def get_retry_mode(self) -> str:
        """Get the retry mode for failed requests."""
        return self.config.get_str("nya_proxy.retry.mode", "default")

    def get_retry_config(self) -> Dict[str, Any]:
        """Get the retry configuration."""
        return self.config.get_dict("nya_proxy.retry", {})

    def get_queue_size(self) -> int:
        """Get the maximum queue size."""
        return self.config.get_int("nya_proxy.queue.max_size", 100)

    def get_queue_expiry(self) -> int:
        """Get the default expiry time for queued requests in seconds."""
        return self.config.get_int("nya_proxy.queue.expiry_seconds", 300)

    def get_api_key(self) -> str:
        """Get the API key for authenticating with the proxy."""
        return self.config.get_str("nya_proxy.api_key", "")

    def get_apis(self) -> Dict[str, Any]:
        """
        Get the configured APIs.

        Returns:
            Dictionary of API names and their configurations
        """
        apis = self.config.get_dict("apis", {})
        if not apis:
            raise ConfigError("No APIs configured. Please add at least one API.")

        return apis

    def get_api_config(self, api_name: str) -> Optional[Dict[str, Any]]:
        """
        Get the configuration for a specific API.

        Args:
            api_name: Name of the API

        Returns:
            Dictionary with API configuration or None if not found
        """
        apis = self.get_apis()
        return apis.get(api_name, None)

    def get_logging_config(self) -> Dict[str, Any]:
        """Get the logging configuration."""
        return {
            "enabled": self.config.get_bool("nya_proxy.logging.enabled", True),
            "level": self.config.get_str("nya_proxy.logging.level", "INFO"),
            "log_file": self.config.get_str("nya_proxy.logging.log_file", "app.log"),
        }

    def get_proxy_enabled(self) -> bool:
        """Check if the proxy is enabled."""
        return self.config.get_bool("nya_proxy.proxy.enabled", False)

    def get_proxy_address(self) -> str:
        """Get the proxy address."""
        return self.config.get_str("nya_proxy.proxy.address", "")

    def get_default_settings(self) -> Dict[str, Any]:
        """Get the default settings for endpoints."""
        return self.config.get_dict("default_settings", {})

    def get_default_timeout(self) -> int:
        """
        Get the default timeout for API requests.

        Returns:
            Default timeout in seconds or 10 if not specified
        """
        return self.config.get_int("nya_proxy.timeouts.request_timeout_seconds", 30)

    def get_default_setting(self, setting_path: str, default_value: Any = None) -> Any:
        """
        Get a default setting value.

        Args:
            setting_path: Path to the setting within default_settings
            default_value: Default value if not specified

        Returns:
            The setting value or default if not specified
        """
        return self.config.get(f"default_settings.{setting_path}", default_value)

    def get_api_setting(
        self, api_name: str, setting_path: str, value_type: str = "str"
    ) -> Any:
        """
        Get a setting value for an API with fallback to default settings.

        Args:
            api_name: Name of the API
            setting_path: Path to the setting within the API config
            value_type: Type of value to get (str, int, bool, list, dict)

        Returns:
            The setting value from API config or default settings
        """

        # Get the default value first
        default_value = self.get_default_setting(setting_path)

        # Get the correct getter method based on value_type
        if value_type == "int":
            return self.config.get_int(f"apis.{api_name}.{setting_path}", default_value)
        elif value_type == "bool":
            return self.config.get_bool(
                f"apis.{api_name}.{setting_path}", default_value
            )
        elif value_type == "list":
            return self.config.get_list(
                f"apis.{api_name}.{setting_path}", default_value
            )
        elif value_type == "dict":
            return self.config.get_dict(
                f"apis.{api_name}.{setting_path}", default_value
            )
        else:  # Default to string
            return self.config.get_str(f"apis.{api_name}.{setting_path}", default_value)

    def get_api_default_timeout(self, api_name: str) -> int:
        """
        Get the default timeout for an API.

        Args:
            api_name: Name of the API

        Returns:
            Default timeout in seconds or fallback to global default
        """
        return self.get_api_setting(api_name, "timeouts.request_timeout_seconds", "int")

    def get_api_key_variable(self, api_name: str) -> str:
        """
        Get the key variable name for an API.

        Args:
            api_name: Name of the API

        Returns:
            Key variable name or default if not specified
        """
        return self.get_api_setting(api_name, "key_variable")

    def get_api_custom_headers(self, api_name: str) -> Dict[str, Any]:
        """
        Get the custom headers for an API.

        Args:
            api_name: Name of the API

        Returns:
            Dictionary of headers or empty dict if not specified
        """
        return self.get_api_setting(api_name, "headers", "dict") or {}

    def get_api_endpoint(self, api_name: str) -> str:
        """
        Get the endpoint URL for an API.

        Args:
            api_name: Name of the API

        Returns:
            Endpoint URL or default if not specified
        """
        return self.get_api_setting(api_name, "endpoint").rstrip("/")

    def get_api_load_balancing_strategy(self, api_name: str) -> str:
        """
        Get the load balancing strategy for an API.

        Args:
            api_name: Name of the API

        Returns:
            Load balancing strategy or default if not specified
        """
        return self.get_api_setting(api_name, "load_balancing_strategy")

    def get_api_endpoint_rate_limit(self, api_name: str) -> str:
        """
        Get the endpoint rate limit for an API.

        Args:
            api_name: Name of the API

        Returns:
            Endpoint rate limit or default if not specified
        """
        return self.get_api_setting(api_name, "rate_limit.endpoint_rate_limit")

    def get_api_key_rate_limit(self, api_name: str) -> str:
        """
        Get the key rate limit for an API.

        Args:
            api_name: Name of the API

        Returns:
            Key rate limit or default if not specified
        """
        return self.get_api_setting(api_name, "rate_limit.key_rate_limit")

    def get_api_retry_enabled(self, api_name: str) -> bool:
        """
        Get the retry enabled setting for an API.

        Args:
            api_name: Name of the API

        Returns:
            Retry enabled setting or default if not specified
        """
        return self.get_api_setting(api_name, "retry.enabled", "bool")

    def get_api_retry_mode(self, api_name: str) -> str:
        """
        Get the retry mode for an API.

        Args:
            api_name: Name of the API

        Returns:
            Retry mode or default if not specified
        """
        return self.get_api_setting(api_name, "retry.mode")

    def get_api_retry_attempts(self, api_name: str) -> int:
        """
        Get the number of retry attempts for an API.

        Args:
            api_name: Name of the API

        Returns:
            Number of retry attempts or default if not specified
        """
        return self.get_api_setting(api_name, "retry.attempts", "int")

    def get_api_retry_after_seconds(self, api_name: str) -> int:
        """
        Get the retry delay in seconds for an API.

        Args:
            api_name: Name of the API

        Returns:
            Retry delay in seconds or default if not specified
        """
        return self.get_api_setting(api_name, "retry.retry_after_seconds", "int")

    def get_api_retry_status_codes(self, api_name: str) -> List[int]:
        """
        Get the retry status codes for an API.

        Args:
            api_name: Name of the API

        Returns:
            Retry status codes or default if not specified
        """
        return self.get_api_setting(api_name, "retry.retry_status_codes", "list")

    def get_api_retry_request_methods(self, api_name: str) -> List[str]:
        """
        Get the retry request methods for an API.

        Args:
            api_name: Name of the API

        Returns:
            List of request methods that should be retried or default if not specified
        """
        return self.get_api_setting(api_name, "retry.retry_request_methods", "list")

    def get_api_variables(self, api_name: str) -> Dict[str, List[Any]]:
        """
        Get the names of all variables defined for an API.

        Args:
            api_name: Name of the API

        Returns:
            List of variable names or empty list if not found
        """
        return self.get_api_config(api_name).get("variables", {})

    def get_api_aliases(self, api_name: str) -> List[str]:
        """
        Get the aliases defined for an API.

        Args:
            api_name: Name of the API

        Returns:
            Dictionary of aliases or empty dict if not found
        """
        return self.get_api_config(api_name).get("aliases", [])

    def get_api_variable_values(self, api_name: str, variable_name: str) -> List[Any]:
        """
        Get variable values for an API.

        Args:
            api_name: Name of the API
            variable_name: Name of the variable

        Returns:
            List of variable values or empty list if not found
        """
        api_config = self.get_api_config(api_name)
        if not api_config:
            return []

        variables = self.get_api_variables(api_name)
        values = variables.get(variable_name, [])

        if isinstance(values, list):
            # handle list of integers or strings
            return [v for v in values if v is not None]
        elif isinstance(values, str):
            # Split comma-separated string values if provided as string
            return [v.strip() for v in values.split(",")]
        else:
            # If it's not a list or string, try to convert to string
            return [str(values)]

    def get_api_rate_limit_paths(self, api_name: str) -> List[str]:
        """
        Get list of path patterns to which rate limiting should be applied.

        Args:
            api_name: Name of the API

        Returns:
            List of path patterns, defaults to ['*'] (all paths)
        """
        # Default to ['*'] if not specified
        default_paths = ["*"]

        # Try to get paths from API-specific config
        api_rate_limit = self.get_api_setting(
            api_name, "rate_limit.rate_limit_paths", "list"
        )

        # If it's a string, convert to list
        if isinstance(api_rate_limit, str):
            return [api_rate_limit]

        return api_rate_limit or default_paths

    def reload(self) -> None:
        """Reload the configuration from disk."""
        try:
            self.config = NekoConf(self.config_file)
            self.logger.info("Configuration reloaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {str(e)}")
            raise ConfigError(f"Failed to reload configuration: {str(e)}")
