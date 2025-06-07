"""
Configuration manager for NyaProxy using NekoConf.
"""

import os
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from loguru import logger
from nekoconf import NekoConf, NekoConfOrchestrator
from nekoconf.storage import FileStorageBackend, RemoteStorageBackend

from nya.common.exceptions import ConfigurationError

T = TypeVar("T")


class ConfigManager:
    """
    Manages configuration for NyaProxy using NekoConf.
    Implements the singleton pattern to ensure only one instance exists.
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """
        Create a singleton instance.
        """
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
        """
        Reset the singleton instance (useful for testing).
        """
        cls._instance = None
        cls._initialized = False

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        """
        Get the singleton instance, creating it if needed.
        """
        if cls._instance is None:
            cls._instance = ConfigManager()
        return cls._instance

    def init_config_client(self) -> NekoConf:
        """
        Initialize the NekoConf.
        """

        storage: Union[FileStorageBackend, RemoteStorageBackend, None] = None

        if self.remote_url:
            logger.info(f"Using remote configuration server: {self.remote_url}")
            storage = RemoteStorageBackend(
                remote_url=self.remote_url,
                api_key=self.remote_api_key,
                app_name=self.remote_app_name or "default",
                logger=logger,
            )
        else:
            logger.info(f"Using local configuration file: {self.config_path}")
            storage = FileStorageBackend(config_path=self.config_path, logger=logger)

        if self.callback:
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
            event_emission_enabled=True,
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

    def get_debug_level(self) -> str:
        """
        Get the debug level for logging.
        """
        return self.config.get_str("server.debug_level", "INFO")

    def get_dashboard_enabled(self) -> bool:
        """
        Check if dashboard is enabled.
        """
        return self.config.get_bool("server.dashboard.enabled", True)

    def get_retry_mode(self) -> str:
        """
        Get the retry mode for failed requests.
        """
        return self.config.get_str("server.retry.mode", "default")

    def get_retry_config(self) -> Dict[str, Any]:
        """
        Get the retry configuration.
        """
        return self.config.get_dict("server.retry", {})

    def get_api_key(self) -> Union[None, str, List[str]]:
        """
        Get the API key(s) for authenticating with the proxy.
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
        """
        apis = self.config.get_dict("apis", {})
        if not apis:
            raise ConfigurationError("No APIs configured. Please add at least one API.")

        return apis

    def get_api_config(self, api_name: str) -> Optional[Dict[str, Any]]:
        """
        Get the configuration for a specific API.
        """
        apis = self.get_apis()
        return apis.get(api_name, None)

    def get_logging_config(self) -> Dict[str, Any]:
        """
        Get the logging configuration.
        """
        return {
            "enabled": self.config.get_bool("server.logging.enabled", True),
            "level": self.config.get_str("server.logging.level", "INFO"),
            "log_file": self.config.get_str("server.logging.log_file", "app.log"),
        }

    def get_proxy_enabled(self) -> bool:
        """
        Check if the proxy is enabled.
        """
        return self.config.get_bool("server.proxy.enabled", False)

    def get_proxy_address(self) -> str:
        """
        Get the proxy address.
        """
        return self.config.get_str("server.proxy.address", "")

    def get_cors_allow_origins(self) -> List[str]:
        """
        Get the CORS allow origin for the proxy.
        """
        return self.config.get_list("server.cors.allow_origins", "*")

    def get_cors_allow_methods(self) -> List[str]:
        """
        Get the CORS allow methods for the proxy.
        """
        return self.config.get_list(
            "server.cors.allow_methods", "GET, POST, PUT, DELETE, OPTIONS"
        )

    def get_cors_allow_headers(self) -> List[str]:
        """
        Get the CORS allow headers for the proxy.
        """
        return self.config.get_list(
            "server.cors.allow_headers", "Content-Type, Authorization"
        )

    def get_cors_allow_credentials(self) -> bool:
        """
        Check if CORS allow credentials is enabled for the proxy.
        """
        return self.config.get_bool("server.cors.allow_credentials", False)

    def get_default_settings(self) -> Dict[str, Any]:
        """
        Get the default settings for endpoints.
        """
        return self.config.get_dict("default_settings", {})

    def get_default_timeout(self) -> int:
        """
        Get the default timeout for API requests.
        """
        return self.config.get_int("server.timeouts.request_timeout_seconds", 30)

    def get_default_setting(self, setting_path: str, default_value: Any = None) -> Any:
        """
        Get a default setting value.
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
        elif value_type == "float":
            return self.config.get_float(
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

    def get_api_request_body_substitution_enabled(self, api_name: str) -> bool:
        """
        Get whether request body substitution is enabled for an API.
        """
        return self.get_api_setting(
            api_name, "request_body_substitution.enabled", "bool"
        )

    def get_api_request_body_substitution_rules(
        self, api_name: str
    ) -> List[Dict[str, Any]]:
        """
        Get request body substitution rules.
        """
        return self.get_api_setting(api_name, "request_body_substitution.rules", "list")

    def get_api_default_timeout(self, api_name: str) -> int:
        """
        Get default timeout for API requests.
        """
        return self.get_api_setting(api_name, "timeouts.request_timeout_seconds", "int")

    def get_api_key_variable(self, api_name: str) -> str:
        """
        Get key variable name.
        """
        return self.get_api_setting(api_name, "key_variable", "str")

    def get_api_key_concurrency(self, api_name: str) -> bool:
        """
        Get key concurrency setting.
        """
        return self.get_api_setting(api_name, "key_concurrency", "bool")

    def get_api_random_delay(self, api_name: str) -> float:
        """
        Get randomness setting for API key selection.
        """
        return self.get_api_setting(api_name, "randomness", "float")

    def get_api_custom_headers(self, api_name: str) -> Dict[str, Any]:
        """
        Get custom headers.
        """
        return self.get_api_setting(api_name, "headers", "dict")

    def get_api_endpoint(self, api_name: str) -> str:
        """
        Get API endpoint URL.
        """
        return self.get_api_setting(api_name, "endpoint", "str")

    def get_api_load_balancing_strategy(self, api_name: str) -> str:
        """
        Get load balancing strategy.
        """
        return self.get_api_setting(api_name, "load_balancing_strategy", "str")

    def get_api_queue_size(self, api_name: str) -> int:
        """
        Get the queue size for the API.
        """
        return self.get_api_setting(api_name, "queue.max_size", "int")

    def get_api_queue_expiry(self, api_name: str) -> float:
        """
        Get the queue expiry time for the API.
        """
        return self.get_api_setting(api_name, "queue.expiry_seconds", "float")

    def get_api_rate_limit_enabled(self, api_name: str) -> bool:
        """
        Get rate limit enabled status.
        """
        return self.get_api_setting(api_name, "rate_limit.enabled", "bool")

    def get_api_endpoint_rate_limit(self, api_name: str) -> str:
        """
        Get endpoint rate limit.
        """
        return self.get_api_setting(api_name, "rate_limit.endpoint_rate_limit", "str")

    def get_api_key_rate_limit(self, api_name: str) -> str:
        """
        Get key rate limit.
        """
        return self.get_api_setting(api_name, "rate_limit.key_rate_limit", "str")

    def get_api_ip_rate_limit(self, api_name: str) -> str:
        """
        Get IP rate limit.
        """
        return self.get_api_setting(api_name, "rate_limit.ip_rate_limit", "str")

    def get_api_user_rate_limit(self, api_name: str) -> str:
        """
        Get user rate limit.
        """
        return self.get_api_setting(api_name, "rate_limit.user_rate_limit", "str")

    def get_api_retry_enabled(self, api_name: str) -> bool:
        """
        Get retry enabled status.
        """
        return self.get_api_setting(api_name, "retry.enabled", "bool")

    def get_api_retry_mode(self, api_name: str) -> str:
        """
        Get retry mode.
        """
        return self.get_api_setting(api_name, "retry.mode", "str")

    def get_api_retry_attempts(self, api_name: str) -> int:
        """
        Get retry attempts count.
        """
        return self.get_api_setting(api_name, "retry.attempts", "int")

    def get_api_retry_after_seconds(self, api_name: str) -> float:
        """
        Get retry delay in seconds.
        """
        return self.get_api_setting(api_name, "retry.retry_after_seconds", "float")

    def get_api_retry_status_codes(self, api_name: str) -> List[int]:
        """
        Get retry status codes.
        """
        return self.get_api_setting(api_name, "retry.retry_status_codes", "list")

    def get_api_retry_request_methods(self, api_name: str) -> List[str]:
        """
        Get retry request methods.
        """
        return self.get_api_setting(api_name, "retry.retry_request_methods", "list")

    def get_api_rate_limit_paths(self, api_name: str) -> List[str]:
        """
        Get rate limit path patterns.
        """
        return self.get_api_setting(api_name, "rate_limit.rate_limit_paths", "list")

    def get_api_variables(self, api_name: str) -> Dict[str, List[Any]]:
        """
        Get all variables defined for an API.
        """
        return self.get_api_config(api_name).get("variables", {})

    def get_api_aliases(self, api_name: str) -> List[str]:
        """
        Get the aliases defined for an API.
        """
        return self.get_api_config(api_name).get("aliases", [])

    def get_api_variable_values(self, api_name: str, variable_name: str) -> List[Any]:
        """
        Get variable values for an API.
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

    def get_api_request_subst_rules(self, api_name: str) -> Dict[str, Any]:
        """
        Get request body substitution rules if enabled.
        """

        enable = self.get_api_request_body_substitution_enabled(api_name)

        if not enable:
            return {}
        return self.get_api_request_body_substitution_rules(api_name)

    def reload(self) -> None:
        """
        Reload the configuration from disk.
        """
        try:
            self.config = self.init_config_client()

            nya_app = [{"NyaProxy": self.config}]
            self.server = NekoConfOrchestrator(apps=nya_app, logger=logger)

            logger.info("Configuration reloaded successfully")
        except Exception as e:
            logger.error(f"Failed to reload configuration: {str(e)}")
            raise ConfigurationError(f"Failed to reload configuration: {str(e)}")
