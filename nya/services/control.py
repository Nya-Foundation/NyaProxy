"""
Simplified key manager that focuses on key availability and rate limiting.
"""

import asyncio
from typing import Dict, Optional, Tuple, Union

from loguru import logger

from ..common.exceptions import APIKeyNotConfiguredError, ConfigurationError
from .lb import LoadBalancer
from .limit import RateLimiter


class TrafficManager:
    """
    Simple key manager that provides available keys and endpoint rate limits.
    """

    def __init__(
        self,
        load_balancers: Dict[str, LoadBalancer],
        rate_limiters: Dict[str, RateLimiter],
    ):
        """Initialize the simple key manager."""
        self.load_balancers = load_balancers
        self.rate_limiters = rate_limiters
        self._lock = asyncio.Lock()

    def has_available_keys(self, api_name: str) -> bool:
        """Check if any keys are available for the API."""
        lb = self.load_balancers.get(api_name)
        if not lb:
            return False

        # Check if any key is actually available
        for key in lb.values:
            key_limiter = self.rate_limiters.get(f"{api_name}_{key}")
            if not key_limiter or not key_limiter.is_rate_limited():
                return True

        return False

    def is_endpoint_available(self, api_name: str) -> bool:
        """Check if the API endpoint is available."""
        endpoint_limiter = self.get_api_rate_limiter(api_name)
        if not endpoint_limiter:
            return True
        return not endpoint_limiter.is_rate_limited()

    async def is_endpoint_ready(self, api_name: str) -> Tuple[Union[str, None], float]:
        """Check if the API endpoint is ready and key is available."""
        endpoint_limiter = self.get_api_rate_limiter(api_name)
        if not endpoint_limiter:
            raise ConfigurationError("NyaProxy: API endpoint not configured.")

        key = await self.get_available_key(api_name)

        if not endpoint_limiter.is_rate_limited() and key:
            endpoint_limiter.record_request()
            return key, 0

        return None, max(
            endpoint_limiter.get_reset_time(),
            self.get_next_key_reset_time(api_name),
        )

    def get_random_key(self, api_name: str) -> Optional[str]:
        """Get a random key for the API bypassing rate limits."""
        lb = self.load_balancers.get(api_name)
        if not lb:
            raise APIKeyNotConfiguredError(api_name)

        # Select a random key from the load balancer
        key = lb.get_next(strategy_name="random")
        if not key:
            raise APIKeyNotConfiguredError(api_name)

        return key

    async def get_available_key(self, api_name: str) -> str:
        """Get an available key for the API."""
        lb = self.load_balancers.get(api_name)
        if not lb:
            raise APIKeyNotConfiguredError(api_name)
        async with self._lock:
            # Use load balancer to select next key, then check if it's available
            for _ in range(len(lb.values)):
                selected_key = lb.get_next()
                key_limiter = self.rate_limiters.get(f"{api_name}_{selected_key}")

                if key_limiter.allow_request():
                    lb.record_request_count(selected_key)
                    return selected_key

            return None

    def mark_key_exhausted(self, api_name: str, key: str, duration: float) -> None:
        """Mark a key as exhausted for a duration."""
        key_limiter = self.rate_limiters.get(f"{api_name}_{key}")
        if key_limiter:
            key_limiter.mark_rate_limited(duration)
            logger.info(f"Marked key {key[:8]}... as exhausted for {duration}s")

    def get_api_rate_limiter(self, api_name: str) -> Optional[RateLimiter]:
        """Get the rate limiter for an API endpoint."""
        return self.rate_limiters.get(f"{api_name}_endpoint")

    def get_key_rate_limiter(
        self, api_name: str, api_key: str
    ) -> Optional[RateLimiter]:
        """Get the rate limiter for a specific API key."""
        return self.rate_limiters.get(f"{api_name}_{api_key}")

    async def get_api_rate_limit_reset(
        self, api_name: str, default: float = 1.0
    ) -> float:
        """Get time until API endpoint rate limit resets."""
        endpoint_limiter = self.get_api_rate_limiter(api_name)
        if endpoint_limiter:
            return endpoint_limiter.get_reset_time()
        return default

    def get_next_key_reset_time(self, api_name: str) -> float:
        """Get time until next key becomes available."""
        # Find the minimum reset time across all keys
        min_reset = float("inf")

        for key_id, limiter in self.rate_limiters.items():
            if key_id.startswith(f"{api_name}_") and key_id != f"{api_name}_endpoint":
                reset_time = limiter.get_reset_time()
                if reset_time == 0:
                    return 0
                min_reset = min(min_reset, reset_time)

        return min_reset if min_reset != float("inf") else 0
