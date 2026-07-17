"""
Simplified key manager that focuses on key availability and rate limiting.
"""

import asyncio
import time
from typing import TYPE_CHECKING, Dict, Optional, Tuple, Union

from ..common.exceptions import APIKeyNotConfiguredError
from ..services.lb import LoadBalancer
from ..services.limit import RateLimiter

if TYPE_CHECKING:
    from ..config.manager import ConfigManager


class TrafficManager:
    """
    Provides traffic management for APIs, including load balancing and rate limiting.

    Rate Limiter Name Format:
    - `[API_NAME]_endpoint`: Rate limiter for the API endpoint
    - `[API_NAME]_key_[KEY]`: Rate limiter for a specific API key
    - `[API_NAME]_ip_[IP]`: Rate limiter for a specific IP address
    - `[API_NAME]_user_[USER]`: Rate limiter for a specific User

    Load Balancer Name Format:
    - `[API_NAME]`: Load balancer for the API, containing all keys
    """

    def __init__(self, config: "ConfigManager"):
        """
        Initialize the TrafficManager with the given configuration.

        Args:
            config: Configuration manager instance
        """
        self.config = config
        self.load_balancers: Dict[str, LoadBalancer] = {}
        self.rate_limiters: Dict[str, RateLimiter] = {}
        self._limiter_prune_interval_seconds = 60.0
        self._last_limiter_prune = 0.0

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

            weights = self.config.get_api_key_weights(api_name)
            if weights:
                lb.set_weights([int(w) for w in weights])

            self.load_balancers[api_name] = lb
        return lb

    def get_or_create_limiter(self, name: str, rate_limit) -> RateLimiter:
        """
        Get or create a rate limiter by name.
        """
        self._prune_idle_limiters()
        limiter = self.rate_limiters.get(name)
        if not limiter:
            limiter = RateLimiter(rate_limit=rate_limit)
            self.rate_limiters[name] = limiter
        else:
            limiter.touch()
        return limiter

    def _prune_idle_limiters(self) -> None:
        """
        Remove stale per-client limiters to avoid unbounded growth.
        """
        current_time = time.time()
        if (
            current_time - self._last_limiter_prune
            < self._limiter_prune_interval_seconds
        ):
            return

        self._last_limiter_prune = current_time
        stale_names = []
        for name, limiter in self.rate_limiters.items():
            if "_ip_" not in name and "_user_" not in name:
                continue

            idle_ttl = max(float(limiter.window_seconds or 0) * 2, 60.0)
            if current_time - limiter.last_accessed > idle_ttl:
                stale_names.append(name)

        for name in stale_names:
            self.rate_limiters.pop(name, None)

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

        key_concurrency = self.config.get_api_key_concurrency(api_name)
        # Lock key if per-key concurrency is not allowed
        if not key_concurrency:
            key_limiter.lock()

        # additional metrics update to support the key selection (least_requests)
        key_lb = self.get_load_balancer(api_name)
        key_lb.update_request_count(key, 1)

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
        Atomically acquire a key if both the endpoint and key are available.

        Args:
            api_name: The name of the API to acquire a key for.
        """
        async with self._lock:
            endpoint_limiter = self.get_endpoint_limiter(api_name)

            endpoint_wait_time = endpoint_limiter.time_until_reset()
            key_wait_time = self.time_to_key_ready(api_name)

            # If endpoint or key is not available, return None and wait time
            if endpoint_wait_time > 0 or key_wait_time > 0:
                return None, max(endpoint_wait_time, key_wait_time)

            lb = self.get_load_balancer(api_name)
            for _ in range(len(lb.keys)):
                key = lb.next()
                key_limiter = self.get_key_limiter(api_name, key)

                if key_limiter.is_limited():
                    continue

                self.record_key_usage(api_name, key)
                endpoint_limiter.record()
                return key, 0

            return None, 1.0

    def select_any_key(self, api_name: str) -> Optional[str]:
        """
        Select a random key for the API bypassing rate limits.

        Args:
            api_name: The name of the API to select a key for.

        Returns:
            Optional[str]: The selected key if available, otherwise raises APIKeyNotConfiguredError.
        """
        lb = self.get_load_balancer(api_name)

        # Select a random key from the load balancer
        key = lb.next(strategy="random")
        if not key:
            raise APIKeyNotConfiguredError(api_name)

        return key

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

        for key in lb.keys:
            key_limiter = self.get_key_limiter(api_name, key)
            if not key_limiter:
                continue

            reset_time = (
                key_limiter.time_until_reset()
                if not key_limiter.locked
                else float("inf")
            )
            # return 0 immediately if any key is available
            if reset_time == 0:
                return 0

            min_reset = min(min_reset, reset_time)

        if min_reset == float("inf"):
            return 1.0

        return min_reset
