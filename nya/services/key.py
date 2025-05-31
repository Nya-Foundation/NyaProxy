"""
Key management and selection for API requests.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

from loguru import logger

from ..common.exceptions import APIKeyExhaustedError, VariablesConfigurationError
from .lb import LoadBalancer
from .limit import RateLimiter


class KeyManager:
    """
    Manages API keys, selection, and rate limiting.

    This class is responsible for selecting appropriate API keys based on
    load balancing strategies and rate limit constraints.
    """

    def __init__(
        self,
        load_balancers: Dict[str, LoadBalancer],
        rate_limiters: Dict[str, RateLimiter],
    ):
        """
        Initialize the key manager.

        Args:
            load_balancers: Dictionary of API key load balancers
            rate_limiters: Dictionary of API key rate limiters {api_}
        """
        self.load_balancers = load_balancers
        self.rate_limiters = rate_limiters

        # Lock to prevent race conditions in key selection
        self.lock = asyncio.Lock()

    def get_key_rate_limiter(
        self, api_name: str, api_key: str
    ) -> Optional[RateLimiter]:
        """
        Get the rate limiter for a specific API key.

        Args:
            api_name: Name of the API
            api_key: The API key to get the rate limiter for

        Returns:
            RateLimiter instance or None if not found
        """
        return self.rate_limiters.get(f"{api_name}_{api_key}")

    def get_api_rate_limiter(self, api_name: str) -> Optional[RateLimiter]:
        """
        Get the rate limiter for an API endpoint.

        Args:
            api_name: Name of the API

        Returns:
            RateLimiter instance or None if not found
        """
        return self.rate_limiters.get(f"{api_name}_endpoint")

    async def is_api_available(self, api_name: str) -> bool:
        """
        Check if the API endpoint is available for requests.

        Args:
            api_name: Name of the API

        Returns:
            True if the API endpoint is not rate limited, False otherwise
        """
        async with self.lock:
            endpoint_limiter = self.get_api_rate_limiter(api_name)
            # If there's no endpoint limiter, consider the API available
            if not endpoint_limiter:
                return True
            return not endpoint_limiter.is_rate_limited()

    async def has_available_keys(self, api_name: str) -> bool:
        """
        Check if there is an available key for the given API that hasn't exceeded its rate limit.

        Args:
            api_name: Name of the API

        Returns:
            True if an available key exists, False otherwise
        """

        async with self.lock:
            key_lb = self.load_balancers.get(api_name)

            if not key_lb:
                return False

            all_keys = set(key_lb.values)
            if not all_keys:
                return False

            # Check if any key is available
            for key in all_keys:
                key_limiter = self.get_key_rate_limiter(api_name, key)
                if not key_limiter or not key_limiter.is_rate_limited():
                    return True

            return False

    async def get_available_key(
        self, api_name: str, apply_rate_limit: bool = True
    ) -> Optional[str]:
        """
        Get an available key that hasn't exceeded its rate limit.

        Args:
            api_name: Name of the API
            apply_rate_limit: Whether to apply rate limit checks

        Returns:
            An available key or None if all keys are rate limited
        """
        key_lb = self.load_balancers.get(api_name)
        if not key_lb:
            raise VariablesConfigurationError(
                f"No load balancer configured for API: {api_name}"
            )

        # If rate limiting is not applied, just return the next key
        if not apply_rate_limit:
            return key_lb.get_next()

        # Use a lock to prevent race conditions
        async with self.lock:
            # Get all keys from the load balancer
            all_keys = set(key_lb.values)
            if not all_keys:
                logger.error(f"No API keys configured for {api_name}")
                raise APIKeyExhaustedError(f"No API keys configured for {api_name}")

            # Find a non-rate-limited key
            for _ in range(len(all_keys)):
                key = key_lb.get_next()
                key_limiter = self.get_key_rate_limiter(api_name, key)

                # If no limiter exists or it allows the request, return the key
                if not key_limiter or key_limiter.allow_request():
                    return key

            # If we've tried all keys and none are available, raise exception
            logger.warning(
                f"All API keys for {api_name} are exhausted or rate limited"
            )
            raise APIKeyExhaustedError(api_name)

    def _clean_rate_limited_keys(self, api_name: str) -> None:
        """
        Maunally reset rate limit for all keys rate limiters of an API.

        Args:
            api_name: Name of the API
        """

        for name, limiter in self.rate_limiters.items():
            if name.startswith(f"{api_name}_") and name != f"{api_name}_endpoint":
                # Reset the key limiter
                limiter.reset()
                logger.info(f"Reset rate limit for key {name}")

    async def get_api_rate_limit_reset(
        self, api_name: str, default: float = 1.0
    ) -> float:
        """
        Get the time in seconds until the rate limit resets on the endpoint level.

        Args:
            api_name: Name of the API
            default: Default reset time if no limiter is found

        Returns:
            Time in seconds until reset, or 60.0 if unknown
        """

        async with self.lock:
            endpoint_limiter = self.get_api_rate_limiter(api_name)

            if endpoint_limiter:
                return endpoint_limiter.get_reset_time()

            # Default reset time if limiter not found
            return default

    async def get_key_rate_limit_reset(self, api_name: str) -> float:
        """
        Fetch the earliest reset time for all keys of an API.

        Args:
            api_name: Name of the API
        Returns:
            Earliest reset time in seconds, or 60.0 if no keys are available
        """
        async with self.lock:

            # Get all keys from the load balancer
            key_lb = self.load_balancers.get(api_name)
            all_keys = set(key_lb.values)

            key_reset_times = []
            for key in all_keys:
                key_limiter = self.get_key_rate_limiter(api_name, key)
                if not key_limiter:
                    continue

                key_reset_times.append(key_limiter.get_reset_time())

            if not key_reset_times:
                raise VariablesConfigurationError(
                    f"Bad API key Configuration, or no rate limiters configured for API: {api_name}"
                )

            return min(key_reset_times)

    def mark_key_rate_limited(self, api_name: str, key: str, reset_time: float) -> None:
        """
        Explicitly mark a key as rate limited.

        This is useful when we receive a 429 response from an API and want to
        avoid using this key for a specific duration.

        Args:
            api_name: Name of the API
            key: The API key to mark
            reset_time: Seconds until the rate limit resets
        """
        key_limiter = self.get_key_rate_limiter(api_name, key)

        if not key_limiter:
            logger.warning(
                f"Cannot mark key {key[:4]}... for {api_name} as rate limited: no rate limiter found"
            )
            return

        key_limiter.mark_rate_limited(reset_time)

        logger.info(
            f"Manually marked key {key[:4]}... for {api_name} as rate limited for {reset_time:.1f}s"
        )

    def reset_rate_limits(self, api_name: Optional[str] = None) -> None:
        """
        Reset rate limit state.

        Args:
            api_name: Optional API name to reset, or all if None
        """
        if api_name:
            # Reset endpoint limiter
            endpoint_limiter = self.get_api_rate_limiter(api_name)
            if endpoint_limiter:
                endpoint_limiter.reset()

            # Reset key limiters
            for name, limiter in self.rate_limiters.items():
                if name.startswith(f"{api_name}_") and name != f"{api_name}_endpoint":
                    limiter.reset()

            logger.info(f"Reset rate limits for {api_name}")
        else:
            # Reset all limiters
            for _, limiter in self.rate_limiters.items():
                limiter.reset()

            logger.info("Reset all rate limits")
