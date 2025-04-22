"""
Rate limiting implementation for API requests.
"""

import logging
import re
import time
from typing import List, Optional, Tuple


class RateLimiter:
    """
    Rate limiter for throttling requests to comply with API limits.

    Supports time-based rate limits in the format "X/Y" where:
    - X is the number of requests allowed
    - Y is the time unit (s=seconds, m=minutes, h=hours, d=days)

    Example rate limits:
    - "100/m": 100 requests per minute
    - "5/s": 5 requests per second
    - "1000/h": 1000 requests per hour
    """

    # Time unit to seconds conversion
    TIME_UNITS = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    def __init__(self, rate_limit: str, logger: Optional[logging.Logger] = None):
        """
        Initialize rate limiter.

        Args:
            rate_limit: Rate limit string in format "X/Y"
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Parse rate limit
        self.requests_limit, self.window_seconds = self._parse_rate_limit(rate_limit)

        # Initialize timestamps with fixed-size list
        self.request_timestamps: List[float] = []
        self.last_cleanup_time = 0

    def _parse_rate_limit(self, rate_limit: str) -> Tuple[int, int]:
        """
        Parse rate limit string into numeric values.

        Args:
            rate_limit: Rate limit string in format "X/Y"

        Returns:
            Tuple of (requests_limit, window_seconds)
        """
        # Handle empty or zero rate limit (no limit)
        if not rate_limit or rate_limit == "0":
            return 0, 0

        # Parse rate limit string (e.g., "100/m")
        pattern = r"^(\d+)/([smhd])$"
        match = re.match(pattern, rate_limit)

        if not match:
            self.logger.warning(
                f"Invalid rate limit format: {rate_limit}, using no limit"
            )
            return 0, 0

        requests_limit = int(match.group(1))
        time_unit = match.group(2)
        window_seconds = self.TIME_UNITS.get(time_unit, 0)

        return requests_limit, window_seconds

    def allow_request(self) -> bool:
        """
        Check if a request is allowed under the rate limit.

        Returns:
            True if request is allowed, False if rate limited
        """
        # If no limit is set, always allow
        if self.requests_limit == 0 or self.window_seconds == 0:
            return True

        current_time = time.time()

        # Clean up timestamps outside the current window
        self._clean_old_timestamps(current_time)

        # Check if we've hit the limit
        if len(self.request_timestamps) >= self.requests_limit:
            return False

        # Record this request
        self.request_timestamps.append(current_time)
        return True

    def _clean_old_timestamps(self, current_time: float) -> None:
        """
        Remove timestamps that are outside the current window.

        Args:
            current_time: Current time in seconds
        """
        # Skip frequent cleanups (optimization)
        if current_time - self.last_cleanup_time < 1.0:
            return

        window_start = current_time - self.window_seconds

        # Use list comprehension for better performance
        self.request_timestamps = [
            t for t in self.request_timestamps if t >= window_start
        ]

        # Update last cleanup time
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
