"""
Service factory for creating and managing NyaProxy components.
"""

import logging
from typing import Any, Dict, Optional, Type

from loguru import logger

from ..common.exceptions import VariablesConfigurationError
from ..config.manager import ConfigManager
from ..services.key import KeyManager
from ..services.lb import LoadBalancer
from ..services.limit import RateLimiter
from ..services.metrics import MetricsCollector
from ..services.queue import RequestQueue
from .request import RequestExecutor
from .response import ResponseProcessor


class ServiceFactory:
    """
    Factory for creating and managing service components with proper dependency injection.

    This centralizes component creation logic and ensures dependencies are properly
    initialized and connected, improving modularity and testability.
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
    ):
        """
        Initialize the service factory.

        Args:
            config_manager: Configuration manager instance

        """
        self.config = config_manager or ConfigManager.get_instance()
        self._components = {}
        # Track component dependencies
        self._dependencies = {}

    def create_metrics_collector(self) -> MetricsCollector:
        """Create or return a metrics collector instance."""
        return self._get_or_create_component(
            "metrics_collector",
            MetricsCollector,
        )

    def create_load_balancers(self) -> Dict[str, LoadBalancer]:
        """Create load balancers for each API endpoint."""
        if "load_balancers" not in self._components:
            load_balancers = {}
            apis = self.config.get_apis()

            for api_name in apis.keys():
                strategy = self.config.get_api_load_balancing_strategy(api_name)
                key_variable = self.config.get_api_key_variable(api_name)

                # Get tokens/keys for this API
                keys = self.config.get_api_variable_values(api_name, key_variable)
                if not keys:
                    raise VariablesConfigurationError(
                        f"No values found for key variable '{key_variable}' in API '{api_name}'"
                    )

                # Initialize load balancer on the key variable
                load_balancers[api_name] = LoadBalancer(keys, strategy)

                # Initialize load balancers for other variables if they exist
                variables = self.config.get_api_variables(api_name)
                for variable_name in variables.keys():

                    # Skip the key variable itself
                    if variable_name == key_variable:
                        continue

                    values = self.config.get_api_variable_values(
                        api_name, variable_name
                    )

                    # Skip if no values are found for this variable
                    if not values:
                        raise VariablesConfigurationError(
                            f"No values found for variable '{variable_name}' in API '{api_name}'"
                        )

                    load_balancers[f"{api_name}_{variable_name}"] = LoadBalancer(
                        values, strategy
                    )

            self._components["load_balancers"] = load_balancers
            logger.debug(f"Created {len(load_balancers)} load balancers")

        return self._components["load_balancers"]

    def create_rate_limiters(self) -> Dict[str, RateLimiter]:
        """Create rate limiters for each API endpoint."""
        if "rate_limiters" not in self._components:
            rate_limiters = {}
            apis = self.config.get_apis()

            for api_name in apis.keys():
                # Get rate limit settings for this API endpoint
                endpoint_limit = self.config.get_api_endpoint_rate_limit(api_name)
                key_limit = self.config.get_api_key_rate_limit(api_name)

                # Create endpoint rate limiter
                rate_limiters[f"{api_name}_endpoint"] = RateLimiter(endpoint_limit)

                # Create rate limiter for each key
                key_variable = self.config.get_api_key_variable(api_name)
                keys = self.config.get_api_variable_values(api_name, key_variable)

                for key in keys:
                    key_id = f"{api_name}_{key}"
                    rate_limiters[key_id] = RateLimiter(key_limit)

            self._components["rate_limiters"] = rate_limiters
            logger.debug(f"Created {len(rate_limiters)} rate limiters")

        return self._components["rate_limiters"]

    def create_key_manager(self) -> KeyManager:
        """Create a key manager instance."""
        # Define dependencies
        dependencies = {
            "load_balancers": self.create_load_balancers(),
            "rate_limiters": self.create_rate_limiters(),
        }

        return self._get_or_create_component(
            "key_manager", KeyManager, constructor_args=dependencies
        )

    def create_request_queue(self) -> Optional[RequestQueue]:
        """Create a request queue if enabled in configuration."""
        if not self.config.get_queue_enabled():
            logger.debug("Request queue disabled in configuration")
            self._components["request_queue"] = None
            return None

        key_manager = self.create_key_manager()
        queue_size = self.config.get_queue_size()
        queue_expiry = self.config.get_queue_expiry()

        dependencies = {
            "key_manager": key_manager,
            "max_size": queue_size,
            "expiry_seconds": queue_expiry,
        }

        return self._get_or_create_component(
            "request_queue", RequestQueue, constructor_args=dependencies
        )

    def create_request_executor(self) -> RequestExecutor:
        """Create a request executor instance."""
        dependencies = {
            "config": self.config,
            "metrics_collector": self.create_metrics_collector(),
            "key_manager": self.create_key_manager(),
        }

        return self._get_or_create_component(
            "request_executor", RequestExecutor, constructor_args=dependencies
        )

    def create_response_processor(self) -> ResponseProcessor:
        """Create a response processor instance."""
        dependencies = {
            "metrics_collector": self.create_metrics_collector(),
            "load_balancer": self.create_load_balancers(),
        }

        return self._get_or_create_component(
            "response_processor", ResponseProcessor, constructor_args=dependencies
        )

    def connect_components(
        self,
    ) -> None:
        """Connect components together for proper operation."""
        # Connect request executor to response processor
        if (
            "request_executor" in self._components
            and "response_processor" in self._components
        ):
            self._components["request_executor"].response_processor = self._components[
                "response_processor"
            ]

            logger.debug("Connected request executor to response processor")

    def _get_or_create_component(
        self, name: str, cls_type: Type, constructor_args: Dict[str, Any] = None
    ) -> Any:
        """
        Get an existing component or create a new one if it doesn't exist.

        Args:
            name: Component name
            cls_type: Component class
            constructor_args: Arguments to pass to the constructor

        Returns:
            Component instance
        """
        if name not in self._components:
            if constructor_args is None:
                constructor_args = {}

            self._components[name] = cls_type(**constructor_args)
            self._dependencies[name] = list(constructor_args.keys())

        return self._components[name]

    def get_component(self, name: str) -> Any:
        """Get a component by name."""
        return self._components.get(name)

    def register_component(self, name: str, component: Any) -> None:
        """Register an external component."""
        self._components[name] = component
        logger.debug(f"Registered external component: {name}")

    def get_component_dependencies(self, name: str) -> list:
        """Get component dependencies."""
        return self._dependencies.get(name, [])
