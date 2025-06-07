"""
Simplified key manager that focuses on key availability and rate limiting.
"""

import asyncio
from typing import Dict, Optional, Tuple, Union

from ..common.exceptions import APIKeyNotConfiguredError
from ..config.manager import ConfigManager
from ..services.lb import LoadBalancer
from ..services.limit import RateLimiter


class TrafficManager:
    """
    Simple key manager that provides available keys and endpoint rate limits.

    Rate Limiter Name Format:
    - `[API_NAME]_endpoint`: Rate limiter for the API endpoint
    - `[API_NAME]_key_[KEY]`: Rate limiter for a specific API key
    - `[API_NAME]_ip_[IP]`: Rate limiter for a specific IP address
    - `[API_NAME]_user_[USER]`: Rate limiter for a specific User

    Load Balancer Name Format:
    - `[API_NAME]`: Load balancer for the API, containing all keys
    """

    def __init__(self, config: ConfigManager):
        """
        Initialize the simple key manager.
        """
        self.config = config or ConfigManager.get_instance()
        self.load_balancers: Dict[str, LoadBalancer] = {}
        self.rate_limiters: Dict[str, RateLimiter] = {}

        self._lock = asyncio.Lock()

    def get_load_balancer(self, api_name: str) -> LoadBalancer:
        """
        Get or create a load balancer for the API.
        """
        lb = self.load_balancers.get(api_name)
        if not lb:
            strategy = self.config.get_api_load_balancing_strategy(api_name)
            key_variable = self.config.get_api_key_variable(api_name)

            keys = self.config.get_api_variable_values(api_name, key_variable)
            lb = LoadBalancer(keys, strategy)
            self.load_balancers[api_name] = lb
        return lb

    def get_or_create_limiter(self, name: str, rate_limit) -> RateLimiter:
        """
        Get or create a rate limiter by name.
        """
        limiter = self.rate_limiters.get(name)
        if not limiter:
            limiter = RateLimiter(rate_limit=rate_limit)
            self.rate_limiters[name] = limiter
        return limiter

    def get_ip_limiter(self, api_name: str, ip: str) -> RateLimiter:
        """
        Get or create a rate limiter for a specific IP address.
        """
        rate_limit = self.config.get_api_ip_rate_limit(api_name)
        return self.get_or_create_limiter(f"{api_name}_ip_{ip}", rate_limit)

    def get_key_limiter(self, api_name: str, key: str) -> RateLimiter:
        """
        Get or create a rate limiter for a specific API key.
        """
        rate_limit = self.config.get_api_key_rate_limit(api_name)
        return self.get_or_create_limiter(f"{api_name}_key_{key}", rate_limit)

    def get_user_limiter(self, api_name: str, user: str) -> RateLimiter:
        """
        Get or create a rate limiter for a specific User.
        """
        rate_limit = self.config.get_api_user_rate_limit(api_name)
        return self.get_or_create_limiter(f"{api_name}_user_{user}", rate_limit)

    def get_endpoint_limiter(self, api_name: str) -> RateLimiter:
        """
        Get or create a rate limiter for the API endpoint.
        """
        rate_limit = self.config.get_api_endpoint_rate_limit(api_name)
        return self.get_or_create_limiter(f"{api_name}_endpoint", rate_limit)

    def has_keys_available(self, api_name: str) -> bool:
        """
        Check if any keys are available for the API.
        """
        lb = self.get_load_balancer(api_name)
        if not lb:
            return False

        # Check if any key is actually available
        for key in lb.values:
            key_limiter = self.get_key_limiter(api_name, key)
            if not key_limiter or not key_limiter.is_limited():
                return True

        return False

    def time_to_ip_ready(self, api_name: str, ip: str) -> float:
        """
        Check if the IP address is ready for requests.
        """
        ip_limiter = self.get_ip_limiter(api_name, ip)
        return ip_limiter.time_until_reset()

    def record_key_usage(self, api_name: str, key: str) -> None:
        """
        Record a request for the specific API key.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        key_limiter.record()

    def record_ip_request(self, api_name: str, ip: str) -> None:
        """
        Record a request for the specific IP address.
        """
        ip_limiter = self.get_ip_limiter(api_name, ip)
        ip_limiter.record()

    def record_user_request(self, api_name: str, user: str) -> None:
        """
        Record a request for the specific User.
        """
        user_limiter = self.get_user_limiter(api_name, user)
        user_limiter.record()

    def record_endpoint_request(self, api_name: str) -> None:
        """
        Record a request for the API endpoint.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)
        endpoint_limiter.record()

    def time_to_endpoint_ready(self, api_name: str) -> float:
        """
        Check if the API endpoint is available.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)
        return endpoint_limiter.time_until_reset()

    def time_to_user_ready(self, api_name: str, user: str) -> float:
        """
        Check if the User is ready for requests.
        """
        user_limiter = self.get_user_limiter(api_name, user)
        return user_limiter.time_until_reset()

    async def acquire_key(self, api_name: str) -> Tuple[Union[str, None], float]:
        """
        Atomically acquire a key if endpoint allows.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)

        key_concurrency = self.config.get_api_key_concurrency(api_name)

        endpoint_wait_time = endpoint_limiter.time_until_reset()
        key_wait_time = self.time_to_key_ready(api_name)

        if endpoint_wait_time > 0 or key_wait_time > 0:
            return None, max(endpoint_wait_time, key_wait_time)

        key, limiter = await self.select_key(api_name)
        if key is None:  # handle race condition
            return None, 1.0

        limiter.record()
        endpoint_limiter.record()

        # Lock key if concurrency is not allowed
        if not key_concurrency:
            limiter.lock()

        return key, 0

    def select_any_key(self, api_name: str) -> Optional[str]:
        """
        Select a random key for the API bypassing rate limits.
        """
        lb = self.get_load_balancer(api_name)

        # Select a random key from the load balancer
        key = lb.next(strategy="random")
        if not key:
            raise APIKeyNotConfiguredError(api_name)

        return key

    async def select_key(self, api_name: str) -> Tuple[Optional[str], RateLimiter]:
        """
        Select a available key for the API endpoint.
        """
        lb = self.get_load_balancer(api_name)

        async with self._lock:
            # Use load balancer to select next key, then check if it's available
            for _ in range(len(lb.values)):
                key = lb.next()
                key_limiter = self.get_key_limiter(api_name, key)

                if not key_limiter.is_limited():
                    return key, key_limiter

            return None, None

    def release_key(self, api_name: str, key: str) -> None:
        """
        Release a key that was previously used.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        key_limiter.release()
        key_limiter.unlock()

    def release_ip(self, api_name: str, ip: str) -> None:
        """
        Release the most recent request for a specific IP address.
        """
        ip_limiter = self.get_ip_limiter(api_name, ip)
        ip_limiter.release()

    def release_user(self, api_name: str, user: str) -> None:
        """
        Release the most recent request for a specific User.
        """
        user_limiter = self.get_user_limiter(api_name, user)
        user_limiter.release()

    def release_endpoint(self, api_name: str) -> None:
        """
        Release the most recent request for the API endpoint.
        """
        endpoint_limiter = self.get_endpoint_limiter(api_name)
        endpoint_limiter.release()

    def block_key(self, api_name: str, key: str, duration: float) -> None:
        """
        Mark a key as exhausted for a duration.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        key_limiter.block_for(duration)

    def lock_key(self, api_name: str, key: str) -> None:
        """
        Lock a key to prevent any further requests.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        key_limiter.lock()

    def unlock_key(self, api_name: str, key: str) -> None:
        """
        Unlock a key to allow requests again.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        key_limiter.unlock()

    def time_to_key_ready(self, api_name: str) -> float:
        """
        Get time until next key becomes available.
        """
        lb = self.get_load_balancer(api_name)

        # Find the minimum reset time across actual API keys
        min_reset = float("inf")

        for key in lb.values:
            key_limiter = self.get_key_limiter(api_name, key)
            if key_limiter:
                reset_time = (
                    key_limiter.time_until_reset()
                    if not key_limiter.locked
                    else float("inf")
                )
                if reset_time == 0:
                    return 0  # At least one key is available
                min_reset = min(min_reset, reset_time)

        if min_reset == float("inf"):
            return 1.0

        return min_reset
