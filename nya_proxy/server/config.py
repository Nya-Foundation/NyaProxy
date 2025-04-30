"""
Configuration manager for NyaProxy using NekoConf.
"""

import logging
import os
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, cast

from nekoconf import NekoConfigClient, NekoConfigServer


class ConfigError(Exception):
    """Exception raised for configuration errors."""

    pass


T = TypeVar("T")


class ApiSettingDescriptor(Generic[T]):
    """Descriptor for API settings that reduces duplication in ConfigManager."""

    def __init__(
        self, setting_path: str, value_type: str = "str", doc: Optional[str] = None
    ):
        """
        Args:
            setting_path: Path to the setting within the API config
            value_type: Type of value ("str", "int", "bool", "list", "dict")
            doc: Docstring for the getter method
        """
        self.setting_path = setting_path
        self.value_type = value_type
        self.doc = doc
        self.name = ""

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None) -> Callable[[str], T]:
        if instance is None:
            return self

        def getter(api_name: str) -> T:
            return cast(
                T,
                instance.get_api_setting(
                    api_name=api_name,
                    setting_path=self.setting_path,
                    value_type=self.value_type,
                ),
            )

        getter.__doc__ = self.doc
        getter.__name__ = self.name
        getter.__qualname__ = f"{owner.__name__}.{self.name}"

        return getter


class ConfigManager:
    """
    Manages configuration for NyaProxy using NekoConf.
    Provides helper methods to access configuration values.
    """

    def __init__(
        self,
        config_path: str,
        schema_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the configuration manager.

        Args:
            config_file: Path to the configuration file
            logger: Optional logger instance
        """
        self.config: NekoConfigClient = None
        self.server: NekoConfigServer = None

        self.config_path = config_path
        self.schema_path = schema_path

        self.logger = logger or logging.getLogger(__name__)

        if not os.path.exists(config_path):
            raise ConfigError(f"Configuration file not found: {config_path}")

        try:
            self.config = self._init_config_client()
            self.server = NekoConfigServer(
                config=self.config.config, logger=self.logger
            )
        except Exception as e:
            error_msg = f"Failed to load configuration from {config_path}: {str(e)}"
            self.logger.error(f"Failed to load configuration: {error_msg}")
            raise ConfigError(error_msg)

    def _init_config_client(self) -> NekoConfigClient:
        """Initialize the NekoConfigClient."""
        client = NekoConfigClient(
            config_path=self.config_path,
            schema_path=self.schema_path,
            logger=self.logger,
        )

        # Validate against the schema
        results = client.validate()
        if results:
            raise ConfigError(f"Configuration validation failed: {results}")

        self.logger.info("Configuration loaded and validated successfully")
        return client

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

    # API Setting Descriptors
    get_api_simulated_streaming_enabled = ApiSettingDescriptor[bool](
        "simulated_streaming.enabled",
        "bool",
        """Get simulated streaming enabled status for an API.
        Args:
            api_name: Name of the API
        Returns:
            Boolean indicating if simulated streaming is enabled
        """,
    )

    get_api_simulated_streaming_delay = ApiSettingDescriptor[int](
        "simulated_streaming.delay_seconds",
        "int",
        """Get simulated streaming delay in seconds.
        Args:
            api_name: Name of the API
        Returns:
            Delay in seconds
        """,
    )

    get_api_simulated_streaming_init_delay = ApiSettingDescriptor[int](
        "simulated_streaming.init_delay_seconds",
        "int",
        """Get initial delay for simulated streaming.
        Args:
            api_name: Name of the API
        Returns:
            Initial delay in seconds
        """,
    )

    get_api_simulated_streaming_chunk_size = ApiSettingDescriptor[int](
        "simulated_streaming.chunk_size_bytes",
        "int",
        """Get chunk size for simulated streaming.
        Args:
            api_name: Name of the API
        Returns:
            Chunk size in bytes
        """,
    )

    get_api_simulated_streaming_apply_to = ApiSettingDescriptor[List[str]](
        "simulated_streaming.apply_to",
        "list",
        """Get endpoints for simulated streaming.
        Args:
            api_name: Name of the API
        Returns:
            List of endpoint paths
        """,
    )

    get_api_request_body_substitution_enabled = ApiSettingDescriptor[bool](
        "request_body_substitution.enabled",
        "bool",
        """Get request body substitution enabled status.
        Args:
            api_name: Name of the API
        Returns:
            Boolean indicating if substitution is enabled
        """,
    )

    get_api_request_body_substitution_rules = ApiSettingDescriptor[
        List[Dict[str, Any]]
    ](
        "request_body_substitution.rules",
        "list",
        """Get request body substitution rules.
        Args:
            api_name: Name of the API
        Returns:
            List of substitution rules
        """,
    )

    get_api_default_timeout = ApiSettingDescriptor[int](
        "timeouts.request_timeout_seconds",
        "int",
        """Get default timeout for API requests.
        Args:
            api_name: Name of the API
        Returns:
            Timeout in seconds
        """,
    )

    get_api_key_variable = ApiSettingDescriptor[str](
        "key_variable",
        "str",
        """Get key variable name.
        Args:
            api_name: Name of the API
        Returns:
            Key variable name
        """,
    )

    get_api_custom_headers = ApiSettingDescriptor[Dict[str, Any]](
        "headers",
        "dict",
        """Get custom headers.
        Args:
            api_name: Name of the API
        Returns:
            Dictionary of headers
        """,
    )

    get_api_endpoint = ApiSettingDescriptor[str](
        "endpoint",
        "str",
        """Get API endpoint URL.
        Args:
            api_name: Name of the API
        Returns:
            Endpoint URL
        """,
    )

    get_api_load_balancing_strategy = ApiSettingDescriptor[str](
        "load_balancing_strategy",
        "str",
        """Get load balancing strategy.
        Args:
            api_name: Name of the API
        Returns:
            Load balancing strategy
        """,
    )

    get_api_endpoint_rate_limit = ApiSettingDescriptor[str](
        "rate_limit.endpoint_rate_limit",
        "str",
        """Get endpoint rate limit.
        Args:
            api_name: Name of the API
        Returns:
            Endpoint rate limit
        """,
    )

    get_api_key_rate_limit = ApiSettingDescriptor[str](
        "rate_limit.key_rate_limit",
        "str",
        """Get key rate limit.
        Args:
            api_name: Name of the API
        Returns:
            Key rate limit
        """,
    )

    get_api_retry_enabled = ApiSettingDescriptor[bool](
        "retry.enabled",
        "bool",
        """Get retry enabled status.
        Args:
            api_name: Name of the API
        Returns:
            Boolean indicating if retry is enabled
        """,
    )

    get_api_retry_mode = ApiSettingDescriptor[str](
        "retry.mode",
        "str",
        """Get retry mode.
        Args:
            api_name: Name of the API
        Returns:
            Retry mode
        """,
    )

    get_api_retry_attempts = ApiSettingDescriptor[int](
        "retry.attempts",
        "int",
        """Get retry attempts count.
        Args:
            api_name: Name of the API
        Returns:
            Number of retry attempts
        """,
    )

    get_api_retry_after_seconds = ApiSettingDescriptor[int](
        "retry.retry_after_seconds",
        "int",
        """Get retry delay.
        Args:
            api_name: Name of the API
        Returns:
            Retry delay in seconds
        """,
    )

    get_api_retry_status_codes = ApiSettingDescriptor[List[int]](
        "retry.retry_status_codes",
        "list",
        """Get retry status codes.
        Args:
            api_name: Name of the API
        Returns:
            List of status codes to retry on
        """,
    )

    get_api_retry_request_methods = ApiSettingDescriptor[List[str]](
        "retry.retry_request_methods",
        "list",
        """Get retry request methods.
        Args:
            api_name: Name of the API
        Returns:
            List of request methods to retry
        """,
    )

    get_api_rate_limit_paths = ApiSettingDescriptor[List[str]](
        "rate_limit.rate_limit_paths",
        "list",
        """Get rate limit path patterns.
        Args:
            api_name: Name of the API
        Returns:
            List of path patterns for rate limiting
        """,
    )

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

    def get_api_advanced_configs(self, api_name: str) -> Dict[str, Any]:
        """
        Get advanced configuration settings for an API.

        Args:
            api_name: Name of the API

        Returns:
            Dictionary of advanced settings or empty dict if not specified
        """
        return {
            "simulated_stream_enabled": self.get_api_simulated_streaming_enabled(
                api_name
            ),
            "delay_seconds": self.get_api_simulated_streaming_delay(api_name),
            "init_delay_seconds": self.get_api_simulated_streaming_init_delay(api_name),
            "chunk_size_bytes": self.get_api_simulated_streaming_chunk_size(api_name),
            "apply_to": self.get_api_simulated_streaming_apply_to(api_name),
            "req_body_subst_enabled": self.get_api_request_body_substitution_enabled(
                api_name
            ),
            "subst_rules": self.get_api_request_body_substitution_rules(api_name),
        }

    def reload(self) -> None:
        """Reload the configuration from disk."""
        try:
            self.config = self._init_config_client()
            self.server = NekoConfigServer(
                config=self.config.config, llogger=self.logger
            )

            self.logger.info("Configuration reloaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {str(e)}")
            raise ConfigError(f"Failed to reload configuration: {str(e)}")
