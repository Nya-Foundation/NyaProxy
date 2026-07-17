"""
Simple rate limiting with time-based recovery.
"""

import re
import time
from collections import deque
from typing import Deque, Optional, Tuple

from ..common.exceptions import ConfigurationError


class RateLimiter:
    """
    Simple rate limiter that tracks request timestamps.
    """

    TIME_UNITS = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    def __init__(self, rate_limit: Optional[str] = None):
        """
        Initialize rate limiter.

        Args:
            rate_limit: Rate limit string (e.g., "10/m", "1/5s")
        """
        self.rate_limit = rate_limit or "0/s"
        self.requests_limit, self.window_seconds = self._parse_rate_limit(rate_limit)
        self.request_timestamps: Deque[float] = deque()
        self.last_accessed = time.time()

        self.locked = False
        # Explicit cool-down deadline (block_for), independent of the
        # request-window limit so it also works on unlimited limiters.
        self.blocked_until = 0.0

    def __repr__(self):
        return f"<RateLimiter rate_limit={self.rate_limit}>"

    def _parse_rate_limit(self, rate_limit: Optional[str]) -> Tuple[int, int]:
        """
        Parse a rate limit string into ``(requests, window_seconds)``.

        ``None``, an empty string, or ``"0"`` mean "no rate limit". Any other
        value that does not match a supported format raises
        ``ConfigurationError`` so a typo cannot silently disable rate
        limiting.
        """
        if not rate_limit or rate_limit == "0":
            return 0, 0

        # Try compound format first (e.g., "1/10s")
        compound_pattern = r"^(\d+)/(\d+)([smhd])$"
        compound_match = re.match(compound_pattern, rate_limit)

        if compound_match:
            requests = int(compound_match.group(1))
            multiplier = int(compound_match.group(2))
            unit = compound_match.group(3)
            return requests, multiplier * self.TIME_UNITS[unit]

        # Simple format (e.g., "100/m")
        simple_pattern = r"^(\d+)/([smhd])$"
        simple_match = re.match(simple_pattern, rate_limit)

        if simple_match:
            requests = int(simple_match.group(1))
            unit = simple_match.group(2)
            return requests, self.TIME_UNITS[unit]

        raise ConfigurationError(
            [
                f"Invalid rate limit format: {rate_limit!r}. "
                "Expected a value like '10/m', '100/h', or '1/5s' "
                "(or '0' for no limit)."
            ]
        )

    def is_limited(self) -> bool:
        """
        Check if currently at rate limit.
        """
        self.touch()

        if self.locked:
            return True

        if time.time() < self.blocked_until:
            return True

        if self.requests_limit == 0:
            return False

        if self.window_seconds == 0:
            return False

        self._clean_old_timestamps()
        return len(self.request_timestamps) >= self.requests_limit

    def record(self) -> None:
        """
        Record a request timestamp.
        """
        self.touch()
        self.request_timestamps.append(time.time())

    def touch(self) -> None:
        """
        Update the last access timestamp for cache eviction.
        """
        self.last_accessed = time.time()

    def release(self) -> None:
        """
        Refund the most recent request if possible.
        """
        self.touch()
        if not self.request_timestamps:
            return
        # Remove the most recent timestamp
        self.request_timestamps.pop()

    def lock(self) -> None:
        """
        Lock the rate limiter to prevent any further requests.
        """
        self.touch()
        self.locked = True

    def unlock(self) -> None:
        """
        Unlock the rate limiter to allow requests again.
        """
        self.touch()
        self.locked = False

    def block_for(self, duration: float) -> None:
        """
        Block requests for a specific duration (e.g. key cool-down after a
        retryable upstream status). Works even when no rate limit is set.
        """
        self.touch()
        self.blocked_until = max(self.blocked_until, time.time() + duration)

    def _clean_old_timestamps(self, current_time: Optional[float] = None) -> None:
        """
        Remove timestamps outside current window.
        """
        current_time = current_time or time.time()
        window_start = current_time - self.window_seconds
        while self.request_timestamps and self.request_timestamps[0] < window_start:
            self.request_timestamps.popleft()

    def time_until_reset(self) -> float:
        """
        Get time until rate limit resets.
        """

        if not self.is_limited():
            return 0.0

        current_time = time.time()
        blocked_wait = max(0.0, self.blocked_until - current_time)

        # A locked limiter has no natural reset time and may hold no
        # timestamps at all; guard against indexing an empty deque.
        if not self.request_timestamps:
            return blocked_wait

        oldest_timestamp = self.request_timestamps[0]
        reset_time = oldest_timestamp + self.window_seconds - current_time
        return max(blocked_wait, reset_time, 0.0)

    def clear(self) -> None:
        """
        Clear rate limiter state.
        """
        self.touch()
        self.request_timestamps = deque()
        self.blocked_until = 0.0
