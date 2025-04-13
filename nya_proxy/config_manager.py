"""
Configuration manager for NyaProxy using NekoConf.
"""

import logging
import os
from typing import Any, Dict, List, Optional

from nekoconf import ConfigAPI, NekoConf


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
        config_file: str,
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
        self.web_server: NekoConf = None

        self.config_file = config_file
        self.logger = logger or logging.getLogger("nya_proxy")

        if not os.path.exists(config_file):
            raise ConfigError(f"Configuration file not found: {config_file}")

        try:
            self.config = ConfigAPI(config_path=config_file, schema_path="schema.json")

            # Validate the configuration
            self.validate_config()

            # Validate against the schema
            results = self.config.validate()

            if results:
                raise ConfigError(f"Configuration validation failed: {results}")

            api_key = self.config.get("nya_proxy.api_key", None)
            self.web_server = NekoConf(
                self.config.config_manager, username="nya", password=api_key
            )

            if callback:
                self.config.observe(callback)

        except Exception as e:
            raise ConfigError(f"Failed to load configuration: {str(e)}")

    def validate_config(self) -> None:
        """Validate the configuration."""
        # Check if required sections exist
        if not self.config.get("nya_proxy"):
            raise ConfigError("Missing required section: nya_proxy")

        # Check if at least one API is configured
        apis = self.get_apis()
        if not apis:
            raise ConfigError(
                "No APIs configured. Please add at least one API configuration."
            )

        # Validate API configurations
        for api_name, api_config in apis.items():
            if "endpoint" not in api_config:
                self.logger.warning(
                    f"No endpoint specified for API '{api_name}'. Using default."
                )

            # Check if key variable exists and has associated values
            key_variable = api_config.get("key_variable", "keys")
            keys = self.get_api_variables(api_name, key_variable)
            if not keys:
                self.logger.warning(
                    f"No {key_variable} found for API '{api_name}'. This API may not work correctly."
                )

    def get_port(self) -> int:
        """Get the port for the proxy server."""
        return self.config.get_int("nya_proxy.port", 8080)

    def get_host(self) -> str:
        """Get the host for the proxy server."""
        return self.config.get_str("nay_proxy.host", "0.0.0.0")

    def get_dashboard_enabled(self) -> bool:
        """Check if dashboard is enabled."""
        return self.config.get_bool("nya_proxy.dashboard.enabled", True)

    def get_queue_enabled(self) -> bool:
        """Check if request queuing is enabled."""
        return self.config.get_bool("nya_proxy.queue.enabled", True)

    def get_queue_size(self) -> int:
        """Get the maximum queue size."""
        return self.config.get_int("nya_proxy.queue.max_size", 100)

    def get_queue_expiry(self) -> int:
        """Get the default expiry time for queued requests in seconds."""
        return self.config.get_int("nya_proxy.queue.expiry_seconds", 300)

    def get_api_key(self) -> str:
        """Get the API key for authenticating with the proxy."""
        return self.config.get_str("nya_proxy.api_key", "")

    def get_logging_config(self) -> Dict[str, Any]:
        """Get the logging configuration."""
        return {
            "enabled": self.config.get_bool("nya_proxy.logging.enabled", True),
            "level": self.config.get_str("nya_proxy.logging.level", "INFO"),
            "log_file": self.config.get_str(
                "nya_proxy.logging.log_file", "nya_proxy.log"
            ),
        }

    def get_proxy_settings(self) -> Dict[str, Any]:
        """Get the proxy settings."""
        return {
            "enabled": self.config.get_bool("nya_proxy.proxy.enabled", False),
            "address": self.config.get_str("nya_proxy.proxy.address", ""),
        }

    def get_default_settings(self) -> Dict[str, Any]:
        """Get the default settings for endpoints."""
        return self.config.get_dict("default_settings", {})

    def get_apis(self) -> Dict[str, Dict[str, Any]]:
        """Get all configured APIs."""
        return self.config.get_dict("apis", {})

    def get_api_config(self, api_name: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific API.

        Args:
            api_name: Name of the API

        Returns:
            API configuration dictionary or None if not found
        """
        apis = self.get_apis()
        return apis.get(api_name)

    def get_api_variables(self, api_name: str, variable_name: str) -> List[str]:
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

        variables = api_config.get("variables", {})
        values = variables.get(variable_name, [])

        if isinstance(values, list):
            return values
        elif isinstance(values, str):
            # Split comma-separated string values if provided as string
            return [v.strip() for v in values.split(",")]
        else:
            # If it's not a list or string, try to convert to string
            return [str(values)]

    def reload(self) -> None:
        """Reload the configuration from disk."""
        try:
            self.config = NekoConf(self.config_file)
            self.validate_config()
            self.logger.info("Configuration reloaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {str(e)}")
            raise ConfigError(f"Failed to reload configuration: {str(e)}")
