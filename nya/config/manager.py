"""
Configuration manager for NyaProxy using NekoConf.
"""

import os
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, Union, cast

from loguru import logger
from nekoconf import NekoConf, NekoConfOrchestrator
from nekoconf.storage import FileStorageBackend, RemoteStorageBackend

from nya.common.exceptions import ConfigurationError

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

    def __get__(
        self, instance: Union["ConfigManager", object], owner=None
    ) -> Callable[[str], T]:
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
    Implements the singleton pattern to ensure only one instance exists.
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """Create a singleton instance."""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(
        self,
        config_path: Optional[str] = None,
        schema_path: Optional[str] = None,
        remote_url: Optional[str] = None,
        remote_api_key: Optional[str] = None,
        remote_app_name: Optional[str] = None,
        callback: Optional[Callable] = None,
    ):
        """
        Initialize the configuration manager (once).

        Args:
            config_file: Path to the configuration file
            schema_file: Path to the schema file for validation (optional)
            remote_url: URL for remote configuration (optional)
            remote_api_key: API key for remote configuration (optional)
            remote_app_name: Name of the application for remote configuration (optional)
            callback: Callback function to call after configuraiton is updated (optional)
        """
        # Skip initialization if already initialized
        if self._initialized:
            return

        self.config: NekoConf = None
        self.server: NekoConfOrchestrator = None

        self.config_path = config_path
        self.schema_path = schema_path
        self.remote_url = remote_url
        self.remote_api_key = remote_api_key
        self.remote_app_name = remote_app_name

        self.callback = callback

        if config_path and not os.path.exists(config_path):
            raise ConfigurationError(f"Configuration file not found: {config_path}")

        self.config = self.init_config_client()
        self.server = self.init_config_server()

        # Mark as initialized
        ConfigManager._initialized = True

    @classmethod
    def reset(cls):
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None
        cls._initialized = False

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        """Get the singleton instance, creating it if needed."""
        if cls._instance is None:
            cls._instance = ConfigManager()
        return cls._instance

    def init_config_client(self) -> NekoConf:
        """Initialize the NekoConf."""

        storage: Union[FileStorageBackend, RemoteStorageBackend, None] = None

        if self.remote_url:
            storage = RemoteStorageBackend(
                remote_url=self.remote_url,
                api_key=self.remote_api_key,
                app_name=self.remote_app_name or "default",
                logger=logger,
            )

        else:
            storage = FileStorageBackend(config_path=self.config_path, logger=logger)

        storage.set_change_callback(self.callback)

        if not storage:
            raise ConfigurationError(
                "No storage backend configured. Please set a config path or remote URL."
            )

        client = NekoConf(
            storage=storage,
            schema_path=self.schema_path,
            logger=logger,
            env_override_enabled=True,
            env_prefix="NYA",
        )

        # Validate against the schema
        results = client.validate()
        if results:
            raise ConfigurationError(f"Configuration validation failed: {results}")

        logger.info("Configuration loaded and validated successfully")
        return client

    def init_config_server(self) -> NekoConfOrchestrator:

        if self.remote_url is not None:
            logger.warning(
                "Remote Config URL is set. NekoConfOrchestrator will not be initialized on this local instance."
            )
            return None

        if self.config is None:
            logger.debug("ConfigManager is not initialized. skipping server init.")
            return None

        try:
            nya_app = {"NyaProxy": self.config}
            server = NekoConfOrchestrator(apps=nya_app, logger=logger)
        except Exception as e:
            error_msg = f"Failed to load configuration: {str(e)}"
            logger.error(error_msg)
            raise ConfigurationError(error_msg)

        return server

    def get_port(self) -> int:
        """Get the port for the proxy server."""
        return self.config.get_int("server.port", 8080)

    def get_host(self) -> str:
        """Get the host for the proxy server."""
        return self.config.get_str("server.host", "0.0.0.0")

    def get_debug_level(self) -> str:
        """Get the debug level for logging."""
        return self.config.get_str("server.debug_level", "INFO")

    def get_dashboard_enabled(self) -> bool:
        """Check if dashboard is enabled."""
        return self.config.get_bool("server.dashboard.enabled", True)

    def get_queue_enabled(self) -> bool:
        """Check if request queuing is enabled."""
        return self.config.get_bool("server.queue.enabled", True)

    def get_retry_mode(self) -> str:
        """Get the retry mode for failed requests."""
        return self.config.get_str("server.retry.mode", "default")

    def get_retry_config(self) -> Dict[str, Any]:
        """Get the retry configuration."""
        return self.config.get_dict("server.retry", {})

    def get_queue_size(self) -> int:
        """Get the maximum queue size."""
        return self.config.get_int("server.queue.max_size", 100)

    def get_queue_expiry(self) -> int:
        """Get the default expiry time for queued requests in seconds."""
        return self.config.get_int("server.queue.expiry_seconds", 300)

    def get_api_key(self) -> Union[None, str, List[str]]:
        """
        Get the API key(s) for authenticating with the proxy.

        Returns:
            None if no API key is configured, a string for a single key,
            or a list of strings for multiple keys
        """

        api_key = self.config.get("server.api_key", None)

        if api_key is None:
            return None
        elif isinstance(api_key, list):
            return api_key
        else:
            return str(api_key)

    def get_apis(self) -> Dict[str, Any]:
        """
        Get the configured APIs.

        Returns:
            Dictionary of API names and their configurations
        """
        apis = self.config.get_dict("apis", {})
        if not apis:
            raise ConfigurationError("No APIs configured. Please add at least one API.")

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
            "enabled": self.config.get_bool("server.logging.enabled", True),
            "level": self.config.get_str("server.logging.level", "INFO"),
            "log_file": self.config.get_str("server.logging.log_file", "app.log"),
        }

    def get_proxy_enabled(self) -> bool:
        """Check if the proxy is enabled."""
        return self.config.get_bool("server.proxy.enabled", False)

    def get_proxy_address(self) -> str:
        """Get the proxy address."""
        return self.config.get_str("server.proxy.address", "")

    def get_cors_allow_origins(self) -> List[str]:
        """Get the CORS allow origin for the proxy."""
        return self.config.get_list("server.cors.allow_origins", "*")

    def get_cors_allow_methods(self) -> List[str]:
        """Get the CORS allow methods for the proxy."""
        return self.config.get_list(
            "server.cors.allow_methods", "GET, POST, PUT, DELETE, OPTIONS"
        )

    def get_cors_allow_headers(self) -> List[str]:
        """Get the CORS allow headers for the proxy."""
        return self.config.get_list(
            "server.cors.allow_headers", "Content-Type, Authorization"
        )

    def get_cors_allow_credentials(self) -> bool:
        """Check if CORS allow credentials is enabled for the proxy."""
        return self.config.get_bool("server.cors.allow_credentials", False)

    def get_default_settings(self) -> Dict[str, Any]:
        """Get the default settings for endpoints."""
        return self.config.get_dict("default_settings", {})

    def get_default_timeout(self) -> int:
        """
        Get the default timeout for API requests.

        Returns:
            Default timeout in seconds or 10 if not specified
        """
        return self.config.get_int("server.timeouts.request_timeout_seconds", 30)

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

    get_api_ip_rate_limit = ApiSettingDescriptor[str](
        "rate_limit.ip_rate_limit",
        "str",
        """Get IP rate limit.
        Args:
            api_name: Name of the API
        Returns:
            IP rate limit
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
            "req_body_subst_enabled": self.get_api_request_body_substitution_enabled(
                api_name
            ),
            "subst_rules": self.get_api_request_body_substitution_rules(api_name),
        }

    def reload(self) -> None:
        """Reload the configuration from disk."""
        try:
            self.config = self.init_config_client()

            nya_app = [{"NyaProxy": self.config}]
            self.server = NekoConfOrchestrator(apps=nya_app, logger=logger)

            logger.info("Configuration reloaded successfully")
        except Exception as e:
            logger.error(f"Failed to reload configuration: {str(e)}")
            raise ConfigurationError(f"Failed to reload configuration: {str(e)}")
