"""
Simplified key manager that focuses on key availability and rate limiting.
"""

import asyncio
from typing import Dict, Optional, Tuple, Union

from loguru import logger

from ..common.exceptions import APIKeyNotConfiguredError, ConfigurationError
from ..utils.helper import mask_secret
from .lb import LoadBalancer
from .limit import RateLimiter


class TrafficManager:
    """
    Simple key manager that provides available keys and endpoint rate limits.

    Rate Limiter Name Format:
    - `[API_NAME]_endpoint`: Rate limiter for the API endpoint
    - `[API_NAME]_[KEY]`: Rate limiter for a specific API key
    - `[API_NAME]_[IP]`: Rate limiter for a specific IP address

    Load Balancer Name Format:
    - `[API_NAME]`: Load balancer for the API, containing all keys
    """

    def __init__(
        self,
        load_balancers: Dict[str, LoadBalancer],
        rate_limiters: Dict[str, RateLimiter],
    ):
        """
        Initialize the simple key manager.
        """
        self.load_balancers = load_balancers
        self.rate_limiters = rate_limiters
        self._lock = asyncio.Lock()

    def get_or_create_limiter(self, name: str, rate_limit) -> RateLimiter:
        """
        Get or create a rate limiter by name.
        """
        limiter = self.rate_limiters.get(name)
        if not limiter:
            limiter = RateLimiter(rate_limit=rate_limit)
            self.rate_limiters[name] = limiter
        return limiter

    def get_or_create_ip_limiter(
        self, api_name: str, ip: str, rate_limit: str
    ) -> RateLimiter:
        """
        Get or create a rate limiter for a specific IP address.
        """
        return self.get_or_create_limiter(f"{api_name}_{ip}", rate_limit)

    def get_or_create_key_limiter(
        self, api_name: str, key: str, rate_limit: str
    ) -> RateLimiter:
        """
        Get or create a rate limiter for a specific API key.
        """
        return self.get_or_create_limiter(f"{api_name}_{key}", rate_limit)

    def get_or_create_endpoint_limiter(
        self, api_name: str, rate_limit: str
    ) -> RateLimiter:
        """
        Get or create a rate limiter for the API endpoint.
        """
        return self.get_or_create_limiter(f"{api_name}_endpoint", rate_limit)

    def get_endpoint_limiter(self, api_name: str) -> Optional[RateLimiter]:
        """
        Get the rate limiter for an API endpoint.
        """
        name = f"{api_name}_endpoint"
        assert name in self.rate_limiters, f"Endpoint Rate limiter for {name} not found"
        return self.rate_limiters.get(name)

    def get_key_limiter(self, api_name: str, api_key: str) -> Optional[RateLimiter]:
        """
        Get the rate limiter for a specific API key.
        """
        name = f"{api_name}_{api_key}"
        assert name in self.rate_limiters, f"Key Rate limiter for {name} not found"
        return self.rate_limiters.get(name)

    def get_ip_limiter(self, api_name: str, ip: str) -> Optional[RateLimiter]:
        """
        Get the rate limiter for a specific IP address.
        """
        name = f"{api_name}_{ip}"
        assert name in self.rate_limiters, f"IP Rate limiter for {name} not found"
        return self.rate_limiters.get(name)

    def has_keys_available(self, api_name: str) -> bool:
        """
        Check if any keys are available for the API.
        """
        lb = self.load_balancers.get(api_name)
        if not lb:
            return False

        # Check if any key is actually available
        for key in lb.values:
            key_limiter = self.get_key_limiter(api_name, key)
            if not key_limiter or not key_limiter.is_limited():
                return True

        return False

    def time_to_ip_ready(self, api_name: str, ip: str, rate_limit: str) -> float:
        """
        Check if the IP address is ready for requests.
        """
        ip_limiter = self.get_or_create_ip_limiter(api_name, ip, rate_limit)
        return ip_limiter.time_until_reset()

    def record_ip_request(self, api_name: str, ip: str) -> None:
        """
        Record a request for the specific IP address.
        """
        ip_limiter = self.get_ip_limiter(api_name, ip)
        if not ip_limiter:
            return
        ip_limiter.record()

    def record_endpoint_request(self, api_name: str) -> None:
        """
        Record a request for the API endpoint.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)
        if not endpoint_limiter:
            return
        endpoint_limiter.record()

    def time_to_endpoint_ready(self, api_name: str) -> float:
        """
        Check if the API endpoint is available.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)
        if not endpoint_limiter:
            return 0
        return endpoint_limiter.time_until_reset()

    async def acquire_key(self, api_name: str) -> Tuple[Union[str, None], float]:
        """
        Atomically acquire a key if endpoint allows.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)
        if not endpoint_limiter:
            raise ConfigurationError("NyaProxy: API endpoint not configured.")

        endpoint_wait_time = endpoint_limiter.time_until_reset()
        key_wait_time = self.time_to_key_ready(api_name)

        if endpoint_wait_time == 0:
            key = await self.select_key(api_name)
            if key:
                return key, 0.0
            else:
                return None, key_wait_time

        return None, max(endpoint_wait_time, key_wait_time)

    def select_any_key(self, api_name: str) -> Optional[str]:
        """
        Select a random key for the API bypassing rate limits.
        """
        lb = self.load_balancers.get(api_name)
        if not lb:
            raise APIKeyNotConfiguredError(api_name)

        # Select a random key from the load balancer
        key = lb.next(strategy="random")
        if not key:
            raise APIKeyNotConfiguredError(api_name)

        return key

    async def select_key(self, api_name: str) -> str:
        """
        Atomically select a key for the API endpoint.
        """
        lb = self.load_balancers.get(api_name)
        if not lb:
            raise APIKeyNotConfiguredError(api_name)
        async with self._lock:
            # Use load balancer to select next key, then check if it's available
            for _ in range(len(lb.values)):
                selected_key = lb.next()
                key_limiter = self.get_key_limiter(api_name, selected_key)

                if key_limiter.can_proceed():
                    lb.record_request_count(selected_key)
                    return selected_key

            return None

    def release_key(self, api_name: str, key: str) -> None:
        """
        Release a key that was previously used.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        if not key_limiter:
            return
        key_limiter.release()

    def release_ip(self, api_name: str, ip: str) -> None:
        """
        Release the most recent request for a specific IP address.
        """
        ip_limiter = self.get_ip_limiter(api_name, ip)
        if not ip_limiter:
            return
        ip_limiter.release()

    def release_endpoint(self, api_name: str) -> None:
        """
        Release the most recent request for the API endpoint.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)
        if not endpoint_limiter:
            return
        endpoint_limiter.release()

    def block_key(self, api_name: str, key: str, duration: float) -> None:
        """
        Mark a key as exhausted for a duration.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        key_limiter.block_for(duration)

        logger.debug(
            f"[Rate Limit] Marked key {mask_secret(key)}... as exhausted for {duration}s"
        )

    def time_to_key_ready(self, api_name: str) -> float:
        """
        Get time until next key becomes available.
        """
        lb = self.load_balancers.get(api_name)
        if not lb:
            logger.warning(f"No load balancer found for API: {api_name}")
            return 5.0

        # Find the minimum reset time across actual API keys
        min_reset = float("inf")

        for key in lb.values:
            key_limiter = self.get_key_limiter(api_name, key)
            if key_limiter:
                reset_time = key_limiter.time_until_reset()
                if reset_time == 0:
                    return 0  # At least one key is available
                min_reset = min(min_reset, reset_time)

        if min_reset == float("inf"):
            logger.warning(f"No key limiters found for API: {api_name}")
            return 5.0

        return min_reset
