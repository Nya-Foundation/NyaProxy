"""
Rate limiter for API requests.
"""

import re
import threading
import time
from typing import Dict, Tuple


class RateLimitError(Exception):
    """Exception raised for rate limit parsing errors."""

    pass


class RateLimiter:
    """
    Rate limiter for API requests.
    """

    def __init__(self, rate_limit: str = "0"):
        """
        Initialize the rate limiter.

        Args:
            rate_limit: Rate limit as a string in the format "count/period"
                       where period is one of s (seconds), m (minutes), h (hours), d (days)
                       Examples: "10/s", "100/m", "1000/h"
                       Use "0" for no limit
        """
        self.rate_limit = rate_limit
        self.count, self.period = self._parse_rate_limit(rate_limit)
        self.requests = []
        self.lock = threading.RLock()

        # Keep track of when the next request will be allowed
        self.next_request_time = 0.0

        # Statistics
        self.allowed_count = 0
        self.rejected_count = 0
        self.last_reset_time = time.time()

    def _parse_rate_limit(self, rate_limit: str) -> Tuple[int, float]:
        """
        Parse the rate limit string.

        Args:
            rate_limit: Rate limit string

        Returns:
            Tuple of (count, period in seconds)
        """
        # No limit
        if rate_limit == "0":
            return 0, 0

        # Parse rate limit string
        match = re.match(r"(\d+)/([smhd])", rate_limit)
        if not match:
            # Invalid format, default to no limit
            return 0, 0

        count = int(match.group(1))
        period_unit = match.group(2)

        # Convert period to seconds
        period_seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(period_unit, 0)

        return count, period_seconds

    def allow_request(self) -> bool:
        """
        Check if a request is allowed under the current rate limit.

        Returns:
            True if the request is allowed, False otherwise
        """
        with self.lock:
            # No limit
            if self.count == 0:
                self.allowed_count += 1
                return True

            current_time = time.time()

            # Clean up old requests
            threshold = current_time - self.period
            self.requests = [t for t in self.requests if t > threshold]

            # Update next request time
            if len(self.requests) >= self.count:
                # Calculate when the next slot will be available
                self.next_request_time = self.requests[0] + self.period

            # Check if we're under the limit
            if len(self.requests) < self.count:
                self.requests.append(current_time)
                self.allowed_count += 1
                return True
            else:
                self.rejected_count += 1
                return False

    def get_remaining(self) -> int:
        """
        Get the number of remaining requests allowed.

        Returns:
            Number of remaining requests
        """
        with self.lock:
            if self.count == 0:
                return -1  # No limit

            current_time = time.time()
            threshold = current_time - self.period
            valid_requests = [t for t in self.requests if t > threshold]

            return max(0, self.count - len(valid_requests))

    def get_reset_time(self) -> float:
        """
        Get the time in seconds until the rate limit resets.

        Returns:
            Seconds until reset (0 if no limit or already reset)
        """
        with self.lock:
            if self.count == 0 or not self.requests:
                return 0.0

            current_time = time.time()

            # If we're not at the limit, return 0
            if len(self.requests) < self.count:
                return 0.0

            # Calculate time until oldest request expires
            return max(0.0, (self.requests[0] + self.period) - current_time)

    def get_limit_details(self) -> Dict[str, float]:
        """
        Get detailed information about the rate limit.

        Returns:
            Dictionary with rate limit details
        """
        with self.lock:
            remaining = self.get_remaining()
            reset_time = self.get_reset_time()

            return {
                "limit": self.count,
                "remaining": remaining,
                "reset_after": reset_time,
                "allowed_count": self.allowed_count,
                "rejected_count": self.rejected_count,
            }

    def reset(self):
        """Reset the rate limiter state."""
        with self.lock:
            self.requests = []
            self.next_request_time = 0.0
            self.last_reset_time = time.time()

    def update_limit(self, rate_limit: str):
        """
        Update the rate limit.

        Args:
            rate_limit: New rate limit string
        """
        with self.lock:
            old_count = self.count
            old_period = self.period

            self.rate_limit = rate_limit
            self.count, self.period = self._parse_rate_limit(rate_limit)

            # If the period changed, we need to reset
            if old_period != self.period:
                self.reset()

            # If only the count changed, keep the existing requests
            # but make sure we're not over the new limit
            elif self.count < old_count and len(self.requests) > self.count:
                # Keep only the most recent requests up to the new count
                self.requests = self.requests[-self.count :]
