"""
Unit tests for multi-window per-key rate limiting.

A single key can carry several quotas at once (for example a per-minute and
a per-day limit). Every window is enforced independently, so a key is only
usable while all of them have room.
"""

import time

import pytest

from nya.common.exceptions import ConfigurationError
from nya.core.control import TrafficManager
from nya.services.limit import RateLimiter
from tests.unit.core_helpers import CoreConfig


def test_list_limit_exposes_widest_window_as_summary():
    limiter = RateLimiter(["40/m", "1000/d"])

    assert limiter.windows == [(40, 60), (1000, 86400)]
    assert limiter.window_seconds == 86400
    assert limiter.requests_limit == 1000


def test_minute_window_blocks_even_when_daily_has_room():
    limiter = RateLimiter(["2/m", "1000/d"])
    limiter.record()
    limiter.record()

    assert limiter.is_limited() is True


def test_daily_window_blocks_even_when_minute_has_room():
    now = time.time()
    limiter = RateLimiter(["1000/m", "2/d"])
    # Two requests from two minutes ago: outside the minute window but still
    # inside the day.
    limiter.request_timestamps.extend([now - 120, now - 120])

    assert limiter.is_limited() is True


def test_expired_minute_window_does_not_clear_the_daily_quota():
    now = time.time()
    limiter = RateLimiter(["2/m", "5/d"])
    limiter.request_timestamps.extend([now - 61, now - 61])

    # Minute window has room again, and the daily quota is far from full.
    assert limiter.is_limited() is False


def test_reset_waits_for_the_slowest_exhausted_window():
    now = time.time()
    limiter = RateLimiter(["1/m", "1/d"])
    limiter.request_timestamps.append(now - 30)

    reset = limiter.time_until_reset()
    assert reset > 3600


def test_unlimited_entries_in_a_list_are_ignored():
    limiter = RateLimiter(["0", "5/d"])

    assert limiter.windows == [(5, 86400)]
    assert limiter.is_limited() is False


def test_invalid_entry_in_a_list_is_rejected():
    with pytest.raises(ConfigurationError):
        RateLimiter(["10/m", "nonsense"])


def test_multi_window_state_round_trips_through_export():
    limiter = RateLimiter(["2/m", "5/d"])
    limiter.record()

    restored = RateLimiter(["2/m", "5/d"])
    restored.restore_state(limiter.export_state())

    assert len(restored.request_timestamps) == 1


def test_release_refunds_every_window():
    limiter = RateLimiter(["1/m", "1/d"])
    limiter.record()
    assert limiter.is_limited() is True

    limiter.release()
    assert limiter.is_limited() is False


def test_traffic_manager_uses_multi_window_key_limits():
    config = CoreConfig()
    config.get_api_key_rate_limits = lambda api_name: ["100/m", "1/d"]
    control = TrafficManager(config)

    first, _ = control.try_acquire_key("mock")
    second, _ = control.try_acquire_key("mock")
    third, wait = control.try_acquire_key("mock")

    assert first is not None
    assert second is not None
    # Each of the two keys has spent its single daily request.
    assert third is None
    assert wait > 0
