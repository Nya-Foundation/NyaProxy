"""
Simple rate limiting with time-based recovery.
"""

import re
import time
from collections import deque
from typing import Deque, Optional, Tuple

from loguru import logger


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

    def __init__(self, rate_limit: str = None):
        """
        Initialize rate limiter.

        Args:
            rate_limit: Rate limit string (e.g., "10/m", "1/5s")
        """
        self.rate_limit = rate_limit or "0/s"
        self.requests_limit, self.window_seconds = self._parse_rate_limit(rate_limit)
        self.request_timestamps: Deque[float] = deque()

    def __repr__(self):
        return f"<RateLimiter rate_limit={self.rate_limit}>"

    def _parse_rate_limit(self, rate_limit: str) -> Tuple[int, int]:
        """
        Parse rate limit string into numeric values.
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

        logger.warning(f"Invalid rate limit format: {rate_limit}")
        return 0, 0

    def is_limited(self) -> bool:
        """
        Check if currently at rate limit.
        """
        if self.requests_limit == 0:
            return False

        self._clean_old_timestamps()
        return len(self.request_timestamps) >= self.requests_limit

    def can_proceed(self) -> bool:
        """
        Check if request can proceed and record it if allowed.
        """
        if self.is_limited():
            return False

        self.record()
        return True

    def record(self) -> None:
        """
        Record a request timestamp.
        """
        self.request_timestamps.append(time.time())

    def release(self) -> None:
        """
        Refund the most recent request if possible.
        """
        if not self.request_timestamps:
            return
        # Remove the most recent timestamp
        self.request_timestamps.pop()

    def block_for(self, duration: float) -> None:
        """
        Block requests for specific duration.
        """
        current_time = time.time()
        self.request_timestamps = deque()

        # Fill with timestamps that expire after duration
        expiry_time = current_time - self.window_seconds + duration
        for _ in range(self.requests_limit):
            self.request_timestamps.append(expiry_time)

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
        if self.window_seconds == 0:
            return 0

        self._clean_old_timestamps()
        if not self.request_timestamps:
            return 0

        if len(self.request_timestamps) < self.requests_limit:
            return 0

        current_time = time.time()
        oldest_timestamp = self.request_timestamps[0]
        reset_time = oldest_timestamp + self.window_seconds - current_time
        return max(0, reset_time)

    def remaining_quota(self) -> int:
        """
        Get remaining requests in current window.
        """
        if self.requests_limit == 0:
            return 999
        self._clean_old_timestamps()
        return max(0, self.requests_limit - len(self.request_timestamps))

    def clear(self) -> None:
        """
        Clear rate limiter state.
        """
        self.request_timestamps = deque()
