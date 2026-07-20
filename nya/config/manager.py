"""
Configuration manager for NyaProxy using Nacho.
"""

import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from nacho import FileStorageBackend, Nacho, NachoOrchestrator, RemoteStorageBackend

from nya.common.constants import DEFAULT_HOST, DEFAULT_PORT
from nya.common.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

T = TypeVar("T")

BUILTIN_API_DEFAULTS: Dict[str, Any] = {
    "key_variable": "keys",
    "key_concurrency": True,
    "randomness": 0.0,
    "load_balancing_strategy": "round_robin",
    "allowed_paths.enabled": False,
    "allowed_paths.mode": "whitelist",
    "allowed_paths.paths": ["*"],
    "allowed_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    "queue.max_size": 200,
    "queue.max_workers": 10,
    "queue.expiry_seconds": 300,
    "rate_limit.enabled": False,
    "rate_limit.endpoint_rate_limit": "0",
    "rate_limit.key_rate_limit": "0",
    "rate_limit.ip_rate_limit": "0",
    "rate_limit.user_rate_limit": "0",
    "rate_limit.rate_limit_paths": ["*"],
    "retry.enabled": True,
    "retry.attempts": 3,
    "retry.retry_after_seconds": 1.0,
    "retry.retry_status_codes": [429, 500, 502, 503, 504],
    "retry.retry_request_methods": ["GET", "POST", "PUT", "DELETE", "PATCH"],
    "key_blocking.enabled": False,
    "key_blocking.status_codes": [403],
    "key_blocking.duration_seconds": 300.0,
    "timeouts.request_timeout_seconds": 300,
    "request_body_substitution.enabled": False,
    "request_body_substitution.rules": [],
}


class ConfigManager:
    """
    Manages configuration for NyaProxy using Nacho.
    """

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

        self.config: Nacho = None
        self.server: NachoOrchestrator = None

        self.config_path = config_path
        self.schema_path = schema_path
        self.remote_url = remote_url
        self.remote_api_key = remote_api_key
        self.remote_app_name = remote_app_name
        self.callback = callback

        if config_path and not remote_url and not os.path.exists(config_path):
            raise ConfigurationError(f"Configuration file not found: {config_path}")

        self.config = self.init_config_client()
        self.server = self.init_config_server()

    def init_config_client(self) -> Nacho:
        """
        Initialize the Nacho configuration client.
        """

        storage: Union[FileStorageBackend, RemoteStorageBackend, None] = None

        if self.remote_url:
            logger.info(
                f"[NyaProxy] Using remote configuration server: {self.remote_url}"
            )
            storage = RemoteStorageBackend(
                url=self.remote_url,
                api_key=self.remote_api_key,
                app_name=self.remote_app_name,
                watch=True,
            )
        else:
            logger.info(
                f"[NyaProxy] Using local configuration file: {self.config_path}"
            )
            storage = FileStorageBackend(self.config_path)

        if not storage:
            raise ConfigurationError(
                "No storage backend configured. Please set a config path or remote URL."
            )

        client = Nacho(
            storage=storage,
            schema=self.schema_path,
            env_prefix="NYA",
            events=True,
        )

        if self.callback:
            client.on_change("@global", priority=10)(self.callback)

        # Validate against the schema
        results = client.validate()
        if not results:
            results = self._semantic_validation_errors(client)
        if results:
            logger.error("[NyaProxy] Configuration validation failed:")
            for error in results:
                logger.error(f"  - {error}")

            raise ConfigurationError(errors=results)

        logger.info("[NyaProxy] Nacho client configuration validated successfully")
        return client

    @staticmethod
    def _semantic_validation_errors(client: Nacho) -> List[str]:
        """Validate relationships that JSON Schema cannot express cleanly."""
        if not hasattr(client, "get_dict"):
            # Some lightweight integrations expose only Nacho's validation API.
            return []

        errors: List[str] = []
        server = client.get_dict("server", {})
        defaults = client.get_dict("default_settings", {})
        apis = client.get_dict("apis", {})

        cors = server.get("cors", {})
        if cors.get("allow_credentials") and "*" in cors.get("allow_origins", []):
            errors.append(
                "server.cors.allow_origins: wildcard origin cannot be used when "
                "allow_credentials is true"
            )

        claimed_routes = {route: route for route in apis}
        settings_scopes = [
            ("default_settings", defaults),
            *((f"apis.{api_name}", api) for api_name, api in apis.items()),
        ]
        for scope_name, settings in settings_scopes:
            key_blocking = settings.get("key_blocking", {})
            if not isinstance(key_blocking, dict):
                continue

            status_codes = key_blocking.get("status_codes")
            if status_codes is not None and (
                not isinstance(status_codes, list)
                or not status_codes
                or any(
                    isinstance(code, bool)
                    or not isinstance(code, int)
                    or not 400 <= code <= 599
                    for code in status_codes
                )
            ):
                errors.append(
                    f"{scope_name}.key_blocking.status_codes: use one or more "
                    "HTTP error statuses from 400 through 599"
                )

            duration = key_blocking.get("duration_seconds")
            if duration is not None and (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or duration <= 0
            ):
                errors.append(
                    f"{scope_name}.key_blocking.duration_seconds: must be greater than 0"
                )

        for api_name, api in apis.items():
            variables = api.get("variables", {})
            key_variable = api.get("key_variable", defaults.get("key_variable", "keys"))
            if not key_variable:
                errors.append(
                    f"apis.{api_name}.key_variable: set it here or in default_settings"
                )
            elif key_variable not in variables:
                errors.append(
                    f"apis.{api_name}.variables: missing key variable '{key_variable}'"
                )
            elif not variables.get(key_variable):
                errors.append(
                    f"apis.{api_name}.variables.{key_variable}: add at least one value"
                )

            for header_name, template in api.get("headers", {}).items():
                if not isinstance(template, str):
                    continue
                for variable in re.findall(r"\$\{\{([^}]+)\}\}", template):
                    variable = variable.strip()
                    if variable not in variables:
                        errors.append(
                            f"apis.{api_name}.headers.{header_name}: references undefined "
                            f"variable '{variable}'"
                        )

            strategy = api.get(
                "load_balancing_strategy",
                defaults.get("load_balancing_strategy", "round_robin"),
            )
            if strategy == "weighted" and key_variable in variables:
                keys = variables[key_variable]
                weights = api.get("key_weights", [])
                if len(weights) != len(keys):
                    errors.append(
                        f"apis.{api_name}.key_weights: expected {len(keys)} weights, "
                        f"got {len(weights)}"
                    )
                elif not any(weight > 0 for weight in weights):
                    errors.append(
                        f"apis.{api_name}.key_weights: at least one weight must be positive"
                    )

            for alias in api.get("aliases", []):
                normalized = alias.removeprefix("/")
                owner = claimed_routes.get(normalized)
                if owner is not None and owner != api_name:
                    errors.append(
                        f"apis.{api_name}.aliases: route '{normalized}' is already "
                        f"claimed by '{owner}'"
                    )
                claimed_routes[normalized] = api_name

        return errors

    def init_config_server(self) -> NachoOrchestrator:
        """
        Initialize the NachoOrchestrator WebUI for the server.
        """

        if self.remote_url is not None:
            logger.warning(
                "Remote Config URL is set. NachoOrchestrator will not be initialized on this local instance."
            )
            return None

        if self.config is None:
            logger.debug("ConfigManager is not initialized. skipping server init.")
            return None

        try:
            nya_app = {"NyaProxy": self.config}
            # Nacho's auth guard takes a single key string (it raises on any
            # other type). Hand it the master key only: the config editor is an
            # admin surface, so the additional proxy keys must not open it.
            # A blank master resolves to None, which is safe here because the
            # NyaProxy auth middleware in front of /config denies admin access
            # outright in that case.
            server = NachoOrchestrator(
                apps=nya_app, logger=logger, api_key=self._master_api_key()
            )
        except Exception as e:
            error_msg = f"Failed to load configuration: {str(e)}"
            logger.error(error_msg)
            raise ConfigurationError(error_msg)

        return server

    def get_host(self) -> str:
        """
        Get the server bind host (falls back to the built-in default).
        """
        return self.config.get_str("server.host", DEFAULT_HOST)

    def get_port(self) -> int:
        """
        Get the server bind port (falls back to the built-in default).
        """
        return self.config.get_int("server.port", DEFAULT_PORT)

    def get_dashboard_enabled(self) -> bool:
        """
        Check if dashboard is enabled.
        """
        return self.config.get_bool("server.dashboard.enabled", True)

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

    def _master_api_key(self) -> Optional[str]:
        """
        The first configured key, which is the only one allowed to administer
        the proxy. Returns None when it is absent or blank.

        Mirrors ``AuthManager.master_key``; kept here so the config server can
        be built before the auth layer exists.
        """
        api_key = self.get_api_key()
        if isinstance(api_key, str):
            first: Any = api_key
        elif isinstance(api_key, list) and api_key:
            first = api_key[0]
        else:
            return None

        return first.strip() if isinstance(first, str) and first.strip() else None

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

    def get_trusted_proxies(self) -> List[str]:
        """Get proxy addresses/networks trusted to supply client IP headers."""
        return self.config.get_list("server.trusted_proxies", [])

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

    def get_default_timeout(self) -> int:
        """
        Get the default timeout for API requests.
        """
        return self.config.get_int("server.timeouts.request_timeout_seconds", 300)

    def get_default_setting(self, setting_path: str, default_value: Any = None) -> Any:
        """
        Get a default setting value.
        """
        fallback = BUILTIN_API_DEFAULTS.get(setting_path, default_value)
        return self.config.get(f"default_settings.{setting_path}", fallback)

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

    def get_api_key_weights(self, api_name: str) -> List[int]:
        """
        Get key selection weights for the 'weighted' load balancing strategy.
        """
        return self.config.get_list(f"apis.{api_name}.key_weights", [])

    def get_api_allowed_paths(self, api_name: str) -> List[str]:
        """
        Get the list of allowed paths for the API.
        """
        return self.get_api_setting(api_name, "allowed_paths.paths", "list")

    def get_api_allowed_paths_enabled(self, api_name: str) -> bool:
        """
        Check if allowed paths are enabled for the API.
        """
        return self.get_api_setting(api_name, "allowed_paths.enabled", "bool")

    def get_api_allowed_paths_mode(self, api_name: str) -> str:
        """
        Get the mode for allowed paths for the API (whitelist/blacklist).
        """
        return self.get_api_setting(api_name, "allowed_paths.mode", "str")

    def get_api_allowed_methods(self, api_name: str) -> List[str]:
        """
        Get the list of allowed methods for the API.
        """
        return self.get_api_setting(api_name, "allowed_methods", "list")

    def get_api_queue_size(self, api_name: str) -> int:
        """
        Get the queue size for the API.
        """
        return self.get_api_setting(api_name, "queue.max_size", "int")

    def get_api_max_workers(self, api_name: str) -> int:
        """
        Get the maximum number of concurrent workers for processing requests for the API.
        """
        return self.get_api_setting(api_name, "queue.max_workers", "int")

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

    def get_api_key_blocking_enabled(self, api_name: str) -> bool:
        """Return whether configured upstream statuses quarantine API keys."""
        return self.get_api_setting(api_name, "key_blocking.enabled", "bool")

    def get_api_key_blocking_status_codes(self, api_name: str) -> List[int]:
        """Return upstream response statuses that quarantine their API key."""
        return self.get_api_setting(api_name, "key_blocking.status_codes", "list")

    def get_api_key_blocking_duration_seconds(self, api_name: str) -> float:
        """Return how long a key remains quarantined after a matching status."""
        return self.get_api_setting(api_name, "key_blocking.duration_seconds", "float")

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
        Get route-segment aliases, accepting the legacy leading-slash form.
        """
        return [
            alias.removeprefix("/")
            for alias in self.get_api_config(api_name).get("aliases", [])
        ]

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

    def get_api_request_subst_rules(self, api_name: str) -> List[Dict[str, Any]]:
        """
        Get request body substitution rules, or an empty list when disabled.
        """
        enabled = self.get_api_setting(
            api_name, "request_body_substitution.enabled", "bool"
        )
        if not enabled:
            return []
        return self.get_api_setting(api_name, "request_body_substitution.rules", "list")
