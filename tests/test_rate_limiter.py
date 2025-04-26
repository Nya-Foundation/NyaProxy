import pytest
import time
import re
from nya_proxy.rate_limiter import RateLimiter


@pytest.fixture
def rate_limiter():
    # Create a rate limiter with 3 requests per second
    return RateLimiter("3/s")


class TestRateLimiter:
    def test_parse_rate_limit(self):
        # Test valid rate limit formats
        limiter_s = RateLimiter("5/s")
        assert limiter_s.requests_limit == 5
        assert limiter_s.window_seconds == 1

        limiter_m = RateLimiter("10/m")
        assert limiter_m.requests_limit == 10
        assert limiter_m.window_seconds == 60

        limiter_h = RateLimiter("100/h")
        assert limiter_h.requests_limit == 100
        assert limiter_h.window_seconds == 3600

        limiter_d = RateLimiter("1000/d")
        assert limiter_d.requests_limit == 1000
        assert limiter_d.window_seconds == 86400

        # Test invalid formats
        zero_limiter = RateLimiter("0")
        assert zero_limiter.requests_limit == 0
        assert zero_limiter.window_seconds == 0

        empty_limiter = RateLimiter("")
        assert empty_limiter.requests_limit == 0
        assert empty_limiter.window_seconds == 0

        # Invalid format should default to no limit
        invalid_limiter = RateLimiter("invalid")
        assert invalid_limiter.requests_limit == 0
        assert invalid_limiter.window_seconds == 0

    def test_allow_request_within_limit(self, rate_limiter):
        # First 3 requests should be allowed (limit is 3/second)
        assert rate_limiter.allow_request() is True
        assert rate_limiter.allow_request() is True
        assert rate_limiter.allow_request() is True
        # Fourth request should be denied
        assert rate_limiter.allow_request() is False

    def test_is_rate_limited(self, rate_limiter):
        # Check initial state
        assert rate_limiter.is_rate_limited() is False

        # Add max requests
        for _ in range(3):
            rate_limiter.record_request()

        # Should now be rate limited
        assert rate_limiter.is_rate_limited() is True

    def test_rate_limit_with_reset(self, rate_limiter):
        # Exhaust the rate limit
        assert rate_limiter.allow_request() is True
        assert rate_limiter.allow_request() is True
        assert rate_limiter.allow_request() is True
        assert rate_limiter.allow_request() is False

        # Manually set timestamps to be outside the window
        current_time = time.time()
        rate_limiter.request_timestamps = [current_time - 2]  # 2 seconds ago

        # After window passes, should allow requests again
        assert rate_limiter.allow_request() is True
        assert rate_limiter.allow_request() is True

    def test_mark_rate_limited(self, rate_limiter: RateLimiter):
        # Initially not rate limited
        assert rate_limiter.is_rate_limited() is False

        # Mark as rate limited for 0.5 seconds
        rate_limiter.mark_rate_limited(0.5)

        # Should be rate limited now
        assert rate_limiter.is_rate_limited() is True

        # Wait for 0.6 seconds to ensure the rate limit expires
        time.sleep(0.6)

        # Should no longer be rate limited
        assert rate_limiter.is_rate_limited() is False

    def test_get_reset_time(self, rate_limiter):
        # Initially no reset time needed
        assert rate_limiter.get_reset_time() == 0

        # Add timestamps just at the limit
        now = time.time()
        rate_limiter.request_timestamps = [now, now, now]  # 3 requests

        # Should have reset time close to 1 second
        reset_time = rate_limiter.get_reset_time()
        assert 0.9 <= reset_time <= 1.0

        # Set oldest timestamp to 0.5 seconds ago
        rate_limiter.request_timestamps = [now - 0.5, now, now]
        reset_time = rate_limiter.get_reset_time()
        assert 0.4 <= reset_time <= 0.6

    def test_remaining_requests(self, rate_limiter):
        # Initially all requests available
        assert rate_limiter.get_remaining_requests() == 3

        # Use one request
        rate_limiter.allow_request()
        assert rate_limiter.get_remaining_requests() == 2

        # Use another
        rate_limiter.allow_request()
        assert rate_limiter.get_remaining_requests() == 1

        # Use the last one
        rate_limiter.allow_request()
        assert rate_limiter.get_remaining_requests() == 0

        # Should stay at 0 not go negative
        rate_limiter.allow_request()  # This will be denied
        assert rate_limiter.get_remaining_requests() == 0

    def test_no_limit(self):
        # Test no rate limit behavior
        no_limit = RateLimiter("0")

        # Should always allow requests
        for _ in range(100):
            assert no_limit.allow_request() is True

        # Should report many remaining requests
        assert no_limit.get_remaining_requests() == 999

        # Should report no reset time
        assert no_limit.get_reset_time() == 0

    def test_clean_old_timestamps(self, rate_limiter):
        # Add some timestamps
        now = time.time()
        rate_limiter.request_timestamps = [
            now - 5,  # 5 seconds ago (outside window)
            now - 0.5,  # 0.5 seconds ago (inside window)
            now,  # Just now (inside window)
        ]

        # Clean up old timestamps
        rate_limiter._clean_old_timestamps(now)

        # Should only have 2 timestamps left
        assert len(rate_limiter.request_timestamps) == 2

    def test_reset(self, rate_limiter):
        # Use some requests
        rate_limiter.allow_request()
        rate_limiter.allow_request()

        # Should have used 2 requests
        assert rate_limiter.get_remaining_requests() == 1

        # Reset the limiter
        rate_limiter.reset()

        # Should be back to initial state
        assert rate_limiter.get_remaining_requests() == 3
        assert len(rate_limiter.request_timestamps) == 0
