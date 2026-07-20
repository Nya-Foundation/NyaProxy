"""
Simplified key manager that focuses on key availability and rate limiting.
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

from ..common.exceptions import APIKeyNotConfiguredError
from ..services.lb import LoadBalancer
from ..services.limit import DEFAULT_LOCK_TTL_SECONDS, RateLimiter
from ..services.state import state_key

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
        # Limiter state carried over from a previous process, applied lazily
        # as each limiter is recreated. See import_state.
        self._restorable_state: Dict[str, Any] = {}

        self._lock = asyncio.Lock()
        # One wakeup channel per API, sharing the traffic lock so that a
        # waiter's check-then-wait and a releaser's grant-then-notify are
        # serialized: a release can never slip between the two.
        self._wait_conditions: Dict[str, asyncio.Condition] = {}

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
            # The rate always comes from the current configuration; only the
            # consumed window and cool-down are carried over from a previous
            # run, so a limit edited across a restart takes effect.
            limiter = RateLimiter(rate_limit=rate_limit)
            restored = self._restorable_state.pop(state_key(name), None)
            if restored:
                limiter.restore_state(restored)
            self.rate_limiters[name] = limiter
        else:
            limiter.touch()
        return limiter

    def export_state(self) -> Dict[str, Any]:
        """
        Snapshot limiter state for the next process.

        Restarting is how NyaProxy applies configuration changes, so without
        this every edit would hand out a fresh burst allowance and release
        every quarantined key.

        Entries are keyed by a hash of the limiter name, because the name
        itself contains the upstream credential or a client IP.
        """
        limiters = {}
        for name, limiter in self.rate_limiters.items():
            state = limiter.export_state()
            if state:
                limiters[state_key(name)] = state
        return {"rate_limiters": limiters}

    def import_state(self, state: Dict[str, Any]) -> int:
        """
        Stage limiter state from a previous run.

        Nothing is applied here: limiters are rebuilt lazily on first use so
        they pick up the current configuration, and the staged entry is
        applied at that point. Entries for limiters that are never touched
        again are simply dropped.
        """
        staged = state.get("rate_limiters") or {}
        if not isinstance(staged, dict):
            return 0
        self._restorable_state = {
            name: value for name, value in staged.items() if isinstance(value, dict)
        }
        return len(self._restorable_state)

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

    def record_key_usage(
        self, api_name: str, key: str, *, enforce_rate_limit: bool = True
    ) -> None:
        """
        Record a request for the specific API key.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        if enforce_rate_limit:
            key_limiter.record()

        key_concurrency = self.config.get_api_key_concurrency(api_name)
        # Lock key if per-key concurrency is not allowed
        if not key_concurrency:
            key_limiter.lock(self._lock_ttl(api_name))

        # additional metrics update to support the key selection (least_requests)
        key_lb = self.get_load_balancer(api_name)
        key_lb.update_request_count(key, 1)

    def _lock_ttl(self, api_name: str) -> float:
        """
        Ceiling on how long one request may hold a key exclusively.

        Generous on purpose: releasing a key that is still in use would put
        two requests on one credential, which is the very thing
        key_concurrency: false exists to prevent. A streamed response can also
        outlive the request timeout, since that bounds only the upstream call.
        This is a safety net for a missed release, not a scheduling knob.
        """
        try:
            timeout = float(self.config.get_api_default_timeout(api_name))
        except Exception:
            return DEFAULT_LOCK_TTL_SECONDS
        if timeout <= 0:
            return DEFAULT_LOCK_TTL_SECONDS
        return max(timeout * 2, 60.0)

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

    def get_wait_condition(self, api_name: str) -> asyncio.Condition:
        """
        The condition a queued request waits on for this API's capacity.

        Built over the traffic lock itself, so holding the condition is
        holding the lock: try_acquire_key can be called directly and a
        release cannot race the decision to wait.
        """
        cond = self._wait_conditions.get(api_name)
        if cond is None:
            cond = asyncio.Condition(lock=self._lock)
            self._wait_conditions[api_name] = cond
        return cond

    def notify_key_released(self, api_name: str) -> None:
        """
        Wake waiters after a key was explicitly freed.

        Release paths are synchronous, and notifying requires the condition's
        lock, so the notification is scheduled as a task. Callers outside an
        event loop (tests, shutdown stragglers) have no waiters to wake.

        Only *explicit* releases need this. Every other wait — rate-limit
        windows, cool-downs, lock TTLs — has a computable deadline, and
        waiters already sleep exactly that long.
        """
        cond = self._wait_conditions.get(api_name)
        if cond is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _notify() -> None:
            async with cond:
                cond.notify_all()

        loop.create_task(_notify())

    async def acquire_key(
        self, api_name: str, *, enforce_rate_limits: bool = True
    ) -> Tuple[Union[str, None], float]:
        """
        Atomically acquire a key if both the endpoint and key are available.

        Args:
            api_name: The name of the API to acquire a key for.
        """
        async with self._lock:
            return self.try_acquire_key(
                api_name, enforce_rate_limits=enforce_rate_limits
            )

    def try_acquire_key(
        self, api_name: str, *, enforce_rate_limits: bool = True
    ) -> Tuple[Union[str, None], float]:
        """
        Acquire attempt for callers already holding the wait condition.

        The caller MUST hold the traffic lock (via ``get_wait_condition`` or
        ``acquire_key``); nothing here awaits, so the check and the grant are
        one atomic step.
        """
        endpoint_limiter = (
            self.get_endpoint_limiter(api_name) if enforce_rate_limits else None
        )

        endpoint_wait_time = (
            endpoint_limiter.time_until_reset() if endpoint_limiter else 0.0
        )
        key_wait_time = self.time_to_key_ready(
            api_name, enforce_rate_limits=enforce_rate_limits
        )

        # If endpoint or key is not available, return None and wait time
        if endpoint_wait_time > 0 or key_wait_time > 0:
            return None, max(endpoint_wait_time, key_wait_time)

        lb = self.get_load_balancer(api_name)
        for _ in range(len(lb.keys)):
            key = lb.next()
            key_limiter = self.get_key_limiter(api_name, key)

            if self._key_is_unavailable(
                key_limiter, enforce_rate_limits=enforce_rate_limits
            ):
                continue

            self.record_key_usage(api_name, key, enforce_rate_limit=enforce_rate_limits)
            if endpoint_limiter:
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

    def release_key(
        self, api_name: str, key: str, *, refund_rate_limit: bool = True
    ) -> None:
        """
        Release a key that was previously used.
        """
        key_limiter = self.get_key_limiter(api_name, key)
        if refund_rate_limit:
            key_limiter.release()
        key_limiter.unlock()
        self.notify_key_released(api_name)

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
        self.notify_key_released(api_name)

    @staticmethod
    def _key_is_unavailable(key_limiter, *, enforce_rate_limits: bool) -> bool:
        """Check concurrency/cool-down state and, optionally, window quota."""
        if key_limiter.locked or time.time() < key_limiter.blocked_until:
            return True
        return enforce_rate_limits and key_limiter.is_limited()

    def time_to_key_ready(
        self, api_name: str, *, enforce_rate_limits: bool = True
    ) -> float:
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

            if enforce_rate_limits:
                reset_time = key_limiter.time_until_reset()
            else:
                reset_time = max(0.0, key_limiter.blocked_until - time.time())
            if key_limiter.locked:
                # A held key is a timed wait too: the TTL is its worst case,
                # and an explicit release wakes waiters earlier. This is what
                # replaced the old hardcoded 1.0-second guess.
                reset_time = max(reset_time, key_limiter.time_until_unlocked())
            # return 0 immediately if any key is available
            if reset_time == 0:
                return 0

            min_reset = min(min_reset, reset_time)

        if min_reset == float("inf"):
            return 1.0

        return min_reset
