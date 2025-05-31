"""
Rate limiting implementation for API requests.
"""

import re
import time
from typing import List, Optional, Tuple

from loguru import logger


class RateLimiter:
    """
    Rate limiter for throttling requests to comply with API limits.

    Supports time-based rate limits in the format "X/Y" where:
    - X is the number of requests allowed
    - Y is the time unit (s=seconds, m=minutes, h=hours, d=days) or
    - Y is a number followed by time unit (e.g., 10s, 30m, 2h)

    Example rate limits:
    - "100/m": 100 requests per minute
    - "5/s": 5 requests per second
    - "1000/h": 1000 requests per hour
    - "1/10s": 1 request per 10 seconds
    - "5/30m": 5 requests per 30 minutes
    """

    # Time unit to seconds conversion
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
            rate_limit: Rate limit string in format "X/Y"
        """

        # Parse rate limit
        self.requests_limit, self.window_seconds = self._parse_rate_limit(rate_limit)

        # Initialize timestamps with fixed-size list
        self.request_timestamps: List[float] = []
        self.last_cleanup_time = 0

    def _parse_rate_limit(self, rate_limit: str) -> Tuple[int, int]:
        """
        Parse rate limit string into numeric values.

        Args:
            rate_limit: Rate limit string in format "X/Y" or "X/Ys"

        Returns:
            Tuple of (requests_limit, window_seconds)
        """
        # Handle empty or zero rate limit (no limit)
        if not rate_limit or rate_limit == "0":
            return 0, 0

        # Try parsing compound time units first (e.g., "1/10s", "5/30m")
        compound_pattern = r"^(\d+)/(\d+)([smhd])$"
        compound_match = re.match(compound_pattern, rate_limit)

        if compound_match:
            requests_limit = int(compound_match.group(1))
            time_value = int(compound_match.group(2))
            time_unit = compound_match.group(3)
            unit_seconds = self.TIME_UNITS.get(time_unit, 0)
            window_seconds = time_value * unit_seconds
            return requests_limit, window_seconds

        # Fall back to simple format (e.g., "100/m")
        simple_pattern = r"^(\d+)/([smhd])$"
        simple_match = re.match(simple_pattern, rate_limit)

        if simple_match:
            requests_limit = int(simple_match.group(1))
            time_unit = simple_match.group(2)
            window_seconds = self.TIME_UNITS.get(time_unit, 0)
            return requests_limit, window_seconds

        logger.warning(f"Invalid rate limit format: {rate_limit}, using no limit")
        return 0, 0

    def is_rate_limited(self) -> bool:
        """
        Check if a request would be rate limited without recording it.

        Returns:
            True if rate limited, False if request would be allowed
        """
        # If no limit is set, never rate limited
        if self.requests_limit == 0 or self.window_seconds == 0:
            return False

        current_time = time.time()

        # Clean up timestamps outside the current window
        self._clean_old_timestamps(current_time)

        # Check if we've hit the limit
        return len(self.request_timestamps) >= self.requests_limit

    def record_request(self) -> None:
        """
        Record a request without checking rate limits.
        This should be called after checking is_rate_limited() returns False.
        """
        current_time = time.time()
        self.request_timestamps.append(current_time)

    def mark_rate_limited(self, duration: float) -> None:
        """
        Explicitly mark this rate limiter as rate limited for a specific duration.

        This is useful when receiving a 429 response from an API to avoid sending
        requests for the specified time period.

        Args:
            duration: Number of seconds to mark as rate limited
        """
        current_time = time.time()

        # Clear existing timestamps to avoid accumulation
        self.request_timestamps = []

        # Fill with enough timestamps to exceed the limit
        # Use timestamps that will expire after the specified duration
        expiry_time = current_time - self.window_seconds + duration
        for _ in range(self.requests_limit):
            self.request_timestamps.append(expiry_time)

        self.last_cleanup_time = current_time

    def allow_request(self) -> bool:
        """
        Check if a request is allowed under the rate limit and record it if allowed.

        Returns:
            True if request is allowed, False if rate limited
        """
        # Check if rate limited
        if self.is_rate_limited():
            return False

        # Record this request
        self.record_request()
        return True

    def _clean_old_timestamps(self, current_time: float) -> None:
        """
        Remove timestamps that are outside the current window.

        Args:
            current_time: Current time in seconds
        """
        window_start = current_time - self.window_seconds
        self.request_timestamps = [
            t for t in self.request_timestamps if t >= window_start
        ]
        self.last_cleanup_time = current_time

    def get_reset_time(self) -> float:
        """
        Get the time in seconds until the rate limit resets.

        Returns:
            Time in seconds until reset
        """
        # If no limit or no timestamps, no reset needed
        if self.window_seconds == 0 or not self.request_timestamps:
            return 0

        current_time = time.time()

        # If we haven't hit the limit, no reset needed
        if len(self.request_timestamps) < self.requests_limit:
            return 0

        # Calculate when the oldest timestamp will leave the window
        oldest_timestamp = min(self.request_timestamps)
        reset_time = oldest_timestamp + self.window_seconds - current_time

        return max(0, reset_time)

    def get_remaining_requests(self) -> int:
        """
        Get the number of remaining requests in the current window.

        Returns:
            Number of remaining requests
        """
        # If no limit, return a large number
        if self.requests_limit == 0:
            return 999

        # Clean up old timestamps
        self._clean_old_timestamps(time.time())

        return max(0, self.requests_limit - len(self.request_timestamps))

    def reset(self) -> None:
        """
        Reset the rate limiter state.
        """
        self.request_timestamps = []
        self.last_cleanup_time = 0
