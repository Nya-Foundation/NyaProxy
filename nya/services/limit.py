"""
Simple rate limiting with time-based recovery.
"""

import logging
import re
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple, Union

from ..common.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

#: Fallback ceiling on a concurrency lock when the caller names no deadline.
#: A lock is released explicitly when the request finishes; this only bounds
#: the damage when that release is missed.
DEFAULT_LOCK_TTL_SECONDS = 300.0


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

    def __init__(self, rate_limit: Optional[Union[str, List[str]]] = None):
        """
        Initialize rate limiter.

        Args:
            rate_limit: One rate limit string (e.g., "10/m", "1/5s") or a list
                of them. Every window in the list is enforced independently,
                which is what lets a single key carry both a per-minute and a
                per-day quota.
        """
        if isinstance(rate_limit, (list, tuple)):
            raw_limits: List[Optional[str]] = list(rate_limit) or [None]
        else:
            raw_limits = [rate_limit]

        parsed = [self._parse_rate_limit(item) for item in raw_limits]

        # Only windows with a positive quota and a positive length actually
        # limit. "0" and zero-length windows contribute nothing.
        self.windows: List[Tuple[int, int]] = [
            (limit, seconds) for limit, seconds in parsed if limit > 0 and seconds > 0
        ]

        if len(parsed) == 1:
            # Preserve the historical single-window attributes exactly.
            self.requests_limit, self.window_seconds = parsed[0]
        else:
            # Summary used for pruning and state filtering: the widest window.
            self.requests_limit, self.window_seconds = max(
                self.windows, key=lambda item: item[1], default=(0, 0)
            )

        self.rate_limit = self._format_rate_limit(rate_limit)
        self.request_timestamps: Deque[float] = deque()
        self.last_accessed = time.time()

        # Deadline for the concurrency lock, or None when unlocked. A lock
        # that could not expire took a credential out of rotation for the
        # lifetime of the process whenever a release was missed.
        self._locked_until: Optional[float] = None
        # Explicit cool-down deadline (block_for), independent of the
        # request-window limit so it also works on unlimited limiters.
        self.blocked_until = 0.0

    def __repr__(self):
        return f"<RateLimiter rate_limit={self.rate_limit}>"

    @staticmethod
    def _format_rate_limit(
        rate_limit: Optional[Union[str, List[str]]],
    ) -> str:
        """Human-readable form used by repr and the persisted state."""
        if rate_limit is None:
            return "0/s"
        if isinstance(rate_limit, (list, tuple)):
            return ",".join(str(item) for item in rate_limit) or "0/s"
        return str(rate_limit)

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

        With more than one window the limiter is at its limit as soon as any
        single window is exhausted.
        """
        self.touch()

        if self.locked:
            return True

        if time.time() < self.blocked_until:
            return True

        if not self.windows:
            return False

        self._clean_old_timestamps()
        now = time.time()
        for limit, seconds in self.windows:
            if self._count_within(now, seconds) >= limit:
                return True
        return False

    def _count_within(self, current_time: float, seconds: int) -> int:
        """
        Count recorded requests inside one window.

        Timestamps are kept in ascending order, so walking from the right
        stops at the first request that has aged out.
        """
        cutoff = current_time - seconds
        count = 0
        for timestamp in reversed(self.request_timestamps):
            if timestamp < cutoff:
                break
            count += 1
        return count

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

    @property
    def locked(self) -> bool:
        """
        Whether a request currently holds this limiter exclusively.

        The lock expires on its own. Every exit from a request releases it
        explicitly, so an expiry means a release was missed — a bug, but one
        that must not cost the credential permanently.
        """
        if self._locked_until is None:
            return False
        if time.time() >= self._locked_until:
            self._locked_until = None
            logger.warning(
                "Concurrency lock on %r expired without being released; "
                "returning the credential to rotation",
                self,
            )
            return False
        return True

    def lock(self, ttl: Optional[float] = None) -> None:
        """
        Take the limiter exclusively for at most ``ttl`` seconds.
        """
        self.touch()
        if ttl is None or ttl <= 0:
            ttl = DEFAULT_LOCK_TTL_SECONDS
        self._locked_until = time.time() + ttl

    def unlock(self) -> None:
        """
        Unlock the rate limiter to allow requests again.
        """
        self.touch()
        self._locked_until = None

    def time_until_unlocked(self) -> float:
        """
        Seconds until the concurrency lock expires on its own.

        This is what makes a locked key a *timed* wait rather than an unknown:
        a waiter can sleep exactly this long as its worst case, with an early
        wake-up when the holder releases first.
        """
        if self._locked_until is None:
            return 0.0
        return max(0.0, self._locked_until - time.time())

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

        With several windows the limiter only reopens once *every* exhausted
        window has room again, so the answer is the slowest wait among them.
        """

        if not self.is_limited():
            return 0.0

        current_time = time.time()
        blocked_wait = max(0.0, self.blocked_until - current_time)

        # A locked limiter has no natural reset time and may hold no
        # timestamps at all; guard against indexing an empty deque.
        if not self.windows or not self.request_timestamps:
            return blocked_wait

        timestamps = list(self.request_timestamps)
        waits: List[float] = []
        for limit, seconds in self.windows:
            window_start = current_time - seconds
            in_window = [
                timestamp for timestamp in timestamps if timestamp >= window_start
            ]
            if len(in_window) < limit:
                continue
            # The oldest requests beyond the quota must age out before the
            # window has room again.
            expire_index = min(len(in_window) - limit, len(in_window) - 1)
            waits.append(in_window[expire_index] + seconds - current_time)

        if not waits:
            return blocked_wait
        return max(blocked_wait, max(waits), 0.0)

    def clear(self) -> None:
        """
        Clear rate limiter state.
        """
        self.touch()
        self.request_timestamps = deque()
        self.blocked_until = 0.0

    def export_state(self) -> Optional[Dict[str, Any]]:
        """
        Snapshot the state worth surviving a restart, or ``None`` if there is
        nothing to keep.

        Only the consumed window and an active cool-down matter. ``locked``
        is deliberately excluded: it tracks in-flight concurrency for a
        process that is going away, so restoring it would strand a key.
        """
        now = time.time()
        if self.window_seconds:
            timestamps = [
                t for t in self.request_timestamps if now - t < self.window_seconds
            ]
        else:
            timestamps = []
        blocked_until = self.blocked_until if self.blocked_until > now else 0.0
        if not timestamps and not blocked_until:
            return None
        return {
            "rate_limit": self.rate_limit,
            "timestamps": timestamps,
            "blocked_until": blocked_until,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """
        Re-apply a snapshot from ``export_state``.

        The window is re-filtered against *this* limiter's configuration, so a
        rate limit edited while the process was down still applies. Timestamps
        in the future are dropped: a backwards clock change or a hand-edited
        state file must not be able to hold a limiter shut indefinitely.
        """
        now = time.time()
        timestamps = []
        for raw in state.get("timestamps") or []:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > now:
                continue
            if self.window_seconds and now - value >= self.window_seconds:
                continue
            timestamps.append(value)

        self.request_timestamps = deque(sorted(timestamps))

        try:
            blocked_until = float(state.get("blocked_until") or 0.0)
        except (TypeError, ValueError):
            blocked_until = 0.0
        self.blocked_until = blocked_until if blocked_until > now else 0.0
        self.touch()
