"""
Unit tests for ``nya.services.limit.RateLimiter``.

Time-sensitive behaviour is exercised by manipulating the internal
timestamp deque directly rather than sleeping, so the suite stays fast
and deterministic.
"""

import time

import pytest

from nya.common.exceptions import ConfigurationError
from nya.services.limit import RateLimiter

# --------------------------------------------------------------------------
# Rate-limit string parsing
# --------------------------------------------------------------------------


def test_parse_simple_format():
    limiter = RateLimiter("100/m")
    assert limiter.requests_limit == 100
    assert limiter.window_seconds == 60


def test_parse_compound_format():
    limiter = RateLimiter("1/10s")
    assert limiter.requests_limit == 1
    assert limiter.window_seconds == 10


def test_parse_each_time_unit():
    assert RateLimiter("5/s").window_seconds == 1
    assert RateLimiter("5/m").window_seconds == 60
    assert RateLimiter("5/h").window_seconds == 3600
    assert RateLimiter("5/d").window_seconds == 86400


def test_parse_zero_means_unlimited():
    limiter = RateLimiter("0")
    assert limiter.requests_limit == 0
    assert limiter.window_seconds == 0


def test_parse_none_means_unlimited():
    limiter = RateLimiter(None)
    assert limiter.requests_limit == 0
    assert limiter.rate_limit == "0/s"


@pytest.mark.parametrize("bad", ["garbage", "10/min", "ten/m", "10", "/m", "10/"])
def test_parse_invalid_format_raises_configuration_error(bad):
    """A malformed rate limit must fail loudly, not silently disable limiting."""
    with pytest.raises(ConfigurationError):
        RateLimiter(bad)


def test_zero_window_is_treated_as_unlimited():
    """A degenerate '5/0s' has a quota but a zero window -> never limits."""
    limiter = RateLimiter("5/0s")
    assert limiter.window_seconds == 0
    for _ in range(50):
        assert limiter.is_limited() is False
        limiter.record()
    assert limiter.is_limited() is False


# --------------------------------------------------------------------------
# is_limited / record core flow
# --------------------------------------------------------------------------


def test_unlimited_limiter_never_limits():
    limiter = RateLimiter("0/s")
    for _ in range(1000):
        assert limiter.is_limited() is False
        limiter.record()
    assert limiter.is_limited() is False


def test_limiter_blocks_after_quota_exhausted():
    limiter = RateLimiter("3/m")
    for _ in range(3):
        assert limiter.is_limited() is False
        limiter.record()
    # Fourth request within the same window is rejected.
    assert limiter.is_limited() is True


def test_old_timestamps_expire_and_free_quota():
    limiter = RateLimiter("2/m")
    # Two requests that "happened" 61s ago — outside the 60s window.
    stale = time.time() - 61
    limiter.request_timestamps.extend([stale, stale])
    assert limiter.is_limited() is False
    limiter.record()
    assert limiter.is_limited() is False


# --------------------------------------------------------------------------
# lock / unlock
# --------------------------------------------------------------------------


def test_lock_forces_limited_regardless_of_quota():
    limiter = RateLimiter("100/m")
    assert limiter.is_limited() is False
    limiter.lock()
    assert limiter.is_limited() is True
    limiter.unlock()
    assert limiter.is_limited() is False


def test_time_until_reset_on_locked_empty_limiter_does_not_crash():
    """Regression: locked + empty deque used to raise IndexError."""
    limiter = RateLimiter("5/m")
    limiter.lock()
    assert limiter.time_until_reset() == 0.0


# --------------------------------------------------------------------------
# release / record / clear
# --------------------------------------------------------------------------


def test_release_refunds_most_recent_request():
    limiter = RateLimiter("1/m")
    limiter.record()
    assert limiter.is_limited() is True
    limiter.release()
    assert limiter.is_limited() is False


def test_release_on_empty_limiter_is_noop():
    limiter = RateLimiter("1/m")
    limiter.release()  # must not raise
    assert len(limiter.request_timestamps) == 0


def test_clear_resets_all_recorded_requests():
    limiter = RateLimiter("2/m")
    limiter.record()
    limiter.record()
    limiter.clear()
    assert len(limiter.request_timestamps) == 0
    assert limiter.is_limited() is False


# --------------------------------------------------------------------------
# block_for / time_until_reset
# --------------------------------------------------------------------------


def test_block_for_makes_limiter_limited_until_duration_passes():
    limiter = RateLimiter("5/m")
    limiter.block_for(30)
    assert limiter.is_limited() is True
    reset = limiter.time_until_reset()
    assert 0 < reset <= 30


def test_time_until_reset_zero_when_not_limited():
    limiter = RateLimiter("5/m")
    assert limiter.time_until_reset() == 0.0


def test_repr_includes_rate_limit():
    assert "10/m" in repr(RateLimiter("10/m"))
