"""
Key management and selection for API requests.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

from .exceptions import ApiKeyRateLimitExceededError
from .load_balancer import LoadBalancer
from .rate_limiter import RateLimiter


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
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the key manager.

        Args:
            load_balancers: Dictionary of API load balancers
            rate_limiters: Dictionary of rate limiters
            logger: Logger instance
        """
        self.load_balancers = load_balancers
        self.rate_limiters = rate_limiters
        self.logger = logger or logging.getLogger(__name__)

        # Cache for rate limited keys (api_name -> dict of rate limited keys with expiry times)
        self.rate_limited_keys: Dict[str, Dict[str, float]] = {}

        # Lock to prevent race conditions in key selection
        self.key_selection_lock = asyncio.Lock()

    async def get_available_key(
        self, api_name: str, load_balancer: LoadBalancer
    ) -> Optional[str]:
        """
        Get an available key that hasn't exceeded its rate limit.

        Args:
            api_name: Name of the API
            load_balancer: Load balancer for the API

        Returns:
            An available key or None if all keys are rate limited

        Raises:
            NoAvailableKeysError: If all keys are rate limited
        """
        # Use a lock to prevent race conditions when multiple requests try to get a key
        async with self.key_selection_lock:
            # Initialize rate limited keys cache for this API if needed
            if api_name not in self.rate_limited_keys:
                self.rate_limited_keys[api_name] = {}

            # Clean up expired rate limits
            self._clean_rate_limited_keys(api_name)

            # Get all keys from the load balancer
            all_keys = set(load_balancer.values)
            if not all_keys:
                self.logger.warning(f"No API keys configured for {api_name}")
                raise ApiKeyRateLimitExceededError(api_name)

            # Get currently rate limited keys
            current_time = time.time()
            rate_limited = {
                k
                for k, expire_time in self.rate_limited_keys[api_name].items()
                if expire_time > current_time
            }

            # Available keys are those not in the rate limited set
            available_keys = all_keys - rate_limited

            # If no keys are available, raise exception immediately
            if not available_keys:
                self.logger.warning(
                    f"All API keys for {api_name} are rate limited by your configured limits (per key)"
                )
                raise ApiKeyRateLimitExceededError(api_name)

            # Try keys from the load balancer until we find one that isn't rate limited
            for _ in range(len(all_keys)):
                key = load_balancer.get_next()

                # Skip already known rate-limited keys
                if key in rate_limited:
                    continue

                # Check rate limit for this specific key
                key_limiter = self.rate_limiters.get(f"{api_name}_{key}")

                # If no limiter exists or it allows the request, return the key
                if not key_limiter or key_limiter.allow_request():
                    return key

                # Otherwise, mark this key as rate limited
                reset_time = key_limiter.get_reset_time()
                self.rate_limited_keys[api_name][key] = current_time + reset_time

                # Add to our local rate limited set for this iteration
                rate_limited.add(key)
                available_keys.discard(key)

                # If we've run out of available keys during this loop, break early
                if not available_keys:
                    break

            # If we've tried all keys and none are available, raise exception
            self.logger.warning(f"All checked API keys for {api_name} are rate limited")
            raise ApiKeyRateLimitExceededError(api_name)

    def _clean_rate_limited_keys(self, api_name: str) -> None:
        """
        Remove expired rate limits from the cache.

        Args:
            api_name: Name of the API
        """
        if api_name not in self.rate_limited_keys:
            return

        current_time = time.time()
        self.rate_limited_keys[api_name] = {
            k: expire_time
            for k, expire_time in self.rate_limited_keys[api_name].items()
            if expire_time > current_time
        }

    def get_rate_limit_reset_time(self, api_name: str) -> float:
        """
        Get the time in seconds until the rate limit resets.

        Args:
            api_name: Name of the API

        Returns:
            Time in seconds until reset, or 60.0 if unknown
        """
        endpoint_limiter = self.rate_limiters.get(f"{api_name}_endpoint")

        if endpoint_limiter:
            return endpoint_limiter.get_reset_time()

        # Default reset time if limiter not found
        return 60.0

    def get_remaining_quota(
        self, api_name: str, key: Optional[str] = None
    ) -> Tuple[int, float]:
        """
        Get the remaining quota for an API or specific key.

        Args:
            api_name: Name of the API
            key: Optional specific key to check

        Returns:
            Tuple of (remaining_requests, reset_in_seconds)
        """
        # Check endpoint level quota
        endpoint_limiter = self.rate_limiters.get(f"{api_name}_endpoint")
        if not endpoint_limiter:
            return (999, 0)  # No limit

        endpoint_remaining = endpoint_limiter.get_remaining_requests()
        endpoint_reset = endpoint_limiter.get_reset_time()

        # If no specific key requested, return endpoint level quota
        if not key:
            return (endpoint_remaining, endpoint_reset)

        # Check key level quota
        key_limiter = self.rate_limiters.get(f"{api_name}_{key}")
        if not key_limiter:
            return (endpoint_remaining, endpoint_reset)  # No key-specific limit

        key_remaining = key_limiter.get_remaining_requests()
        key_reset = key_limiter.get_reset_time()

        # Return the more restrictive of the two limits
        if key_remaining < endpoint_remaining:
            return (key_remaining, key_reset)
        else:
            return (endpoint_remaining, endpoint_reset)

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
        if api_name not in self.rate_limited_keys:
            self.rate_limited_keys[api_name] = {}

        current_time = time.time()
        self.rate_limited_keys[api_name][key] = current_time + reset_time

        self.logger.info(
            f"Manually marked key {key[:4]}... for {api_name} as rate limited for {reset_time:.1f}s"
        )

    def reset_rate_limits(self, api_name: Optional[str] = None) -> None:
        """
        Reset rate limit state.

        Args:
            api_name: Optional API name to reset, or all if None
        """
        if api_name:
            # Reset for specific API
            if api_name in self.rate_limited_keys:
                self.rate_limited_keys[api_name] = {}

            # Reset endpoint limiter
            endpoint_limiter = self.rate_limiters.get(f"{api_name}_endpoint")
            if endpoint_limiter:
                endpoint_limiter.reset()

            # Reset key limiters
            for name, limiter in self.rate_limiters.items():
                if name.startswith(f"{api_name}_") and name != f"{api_name}_endpoint":
                    limiter.reset()

            self.logger.info(f"Reset rate limits for {api_name}")
        else:
            # Reset all APIs
            self.rate_limited_keys = {}

            for _, limiter in self.rate_limiters.items():
                limiter.reset()

            self.logger.info("Reset all rate limits")
