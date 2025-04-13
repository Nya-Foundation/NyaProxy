"""
Tests for the rate limiter component with comprehensive coverage.

This module contains tests for the RateLimiter class, organized into
logical sections by complexity and feature area.
"""

import concurrent.futures
import time
from unittest.mock import patch

import pytest

from nya_proxy.rate_limiter import RateLimiter


@pytest.mark.unit
class TestRateLimiterInit:
    """Tests for RateLimiter initialization and configuration parsing."""

    def test_parse_rate_limit_formats(self):
        """Test correct parsing of various rate limit formats."""
        # Test seconds format
        limiter = RateLimiter("10/s")
        assert limiter.max_requests == 10
        assert limiter.window_seconds == 1
        assert limiter.enabled is True

        # Test minutes format
        limiter = RateLimiter("60/m")
        assert limiter.max_requests == 60
        assert limiter.window_seconds == 60
        assert limiter.enabled is True

        # Test hours format
        limiter = RateLimiter("120/h")
        assert limiter.max_requests == 120
        assert limiter.window_seconds == 3600
        assert limiter.enabled is True

        # Test days format
        limiter = RateLimiter("1000/d")
        assert limiter.max_requests == 1000
        assert limiter.window_seconds == 86400
        assert limiter.enabled is True

    def test_invalid_rate_limits(self):
        """Test handling of invalid rate limit inputs."""
        # Invalid format should disable rate limiting
        limiter = RateLimiter("invalid")
        assert limiter.enabled is False

        # Empty string
        limiter = RateLimiter("")
        assert limiter.enabled is False

        # None
        limiter = RateLimiter(None)
        assert limiter.enabled is False

        # Negative values
        limiter = RateLimiter(-10)
        assert limiter.enabled is False

    def test_edge_case_rate_formats(self):
        """Test edge case rate limit formats."""
        # Very small rate (0.01/s = 1 request per 100 seconds)
        tiny_limiter = RateLimiter("0.01/s")
        assert tiny_limiter.max_requests == 0.01
        assert tiny_limiter.window_seconds == 1
        assert tiny_limiter.allow_request() is True
        assert tiny_limiter.allow_request() is False

        # Very large rates (effectively unlimited)
        huge_limiter = RateLimiter("1000000/s")
        for _ in range(1000):  # Test with a large but reasonable number
            assert huge_limiter.allow_request() is True

        # Test unusual time formats if supported
        ms_limiter = RateLimiter("10/0.5s")  # 10 requests per half-second
        assert ms_limiter.max_requests == 10
        assert ms_limiter.window_seconds == 0.5


@pytest.mark.unit
class TestRateLimiterBasicBehavior:
    """Basic tests for rate limiter behavior."""

    def test_allow_request_basic(self, rate_limiters):
        """Test basic rate limiting behavior."""
        # Use standard limiter (10/s)
        limiter = rate_limiters["standard"]

        # First 10 requests should be allowed
        for i in range(10):
            assert limiter.allow_request() is True, f"Request {i} should be allowed"

        # 11th request should be denied
        assert limiter.allow_request() is False

    def test_disabled_limiter(self, rate_limiters):
        """Test that disabled limiter allows all requests."""
        limiter = rate_limiters["disabled"]

        # Should allow many requests
        for _ in range(100):
            assert limiter.allow_request() is True

    def test_unlimited_limiter(self, rate_limiters):
        """Test that very high rate limits effectively act unlimited."""
        limiter = rate_limiters["unlimited"]

        # Should allow many requests
        for _ in range(1000):
            assert limiter.allow_request() is True

    def test_fractional_rate_limit(self, rate_limiters):
        """Test with a fractional rate limit (less than 1 request per time unit)."""
        limiter = rate_limiters["fractional"]  # 0.5/s = 1 request per 2 seconds

        # First request should be allowed
        assert limiter.allow_request() is True

        # Second request should be denied
        assert limiter.allow_request() is False

        # After waiting >2s, should allow another
        with patch("time.time") as mock_time:
            mock_time.return_value = time.time() + 2.1
            assert limiter.allow_request() is True


@pytest.mark.unit
class TestRateLimiterWithMockTime:
    """Tests for rate limiter behavior with mocked time."""

    def test_rate_limit_with_time_passage(self, mock_time):
        """Test precise rate limiting behavior with controlled time."""
        mock_time.return_value = 1000
        limiter = RateLimiter("5/10s")  # 5 requests per 10 seconds

        # First 5 requests should be allowed
        for i in range(5):
            assert limiter.allow_request() is True, f"Request {i} should be allowed"

        # 6th request should be denied
        assert limiter.allow_request() is False

        # Advance time by 2 seconds (not enough for reset)
        mock_time.return_value = 1002
        assert limiter.allow_request() is False

        # Advance time by remaining 8 seconds (total 10s, should reset)
        mock_time.return_value = 1010
        assert limiter.allow_request() is True

        # Test partial window recovery
        mock_time.return_value = 1015  # 5 seconds after last reset (half window)

        # Should have recovered approximately half the capacity
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True

    def test_sliding_window(self, mock_time):
        """Test the sliding window behavior of the rate limiter."""
        mock_time.return_value = 1000
        # 2 requests per second
        limiter = RateLimiter("2/s")

        # First 2 requests should be allowed
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True

        # 3rd request should be denied immediately
        assert limiter.allow_request() is False

        # Wait for window to slide partially (600ms)
        mock_time.return_value = 1000.6

        # Should now be able to make 1 more request (proportional refill)
        assert limiter.allow_request() is True

        # But not 2 more
        assert limiter.allow_request() is False

    def test_remaining_requests(self, mock_time):
        """Test the remaining_requests method."""
        mock_time.return_value = 1000
        limiter = RateLimiter("5/s")

        # Initially should have 5 remaining
        assert limiter.remaining_requests() == 5

        # After using 3, should have 2 remaining
        limiter.allow_request()
        limiter.allow_request()
        limiter.allow_request()
        assert limiter.remaining_requests() == 2

        # Use up the remainder
        limiter.allow_request()
        limiter.allow_request()
        assert limiter.remaining_requests() == 0

        # After partial window, should have some partial recovery
        mock_time.return_value = 1000.5  # 0.5s later

        # Should have ~2.5 tokens (half of capacity recovered)
        expected_tokens = 2.5
        tolerance = 0.1
        assert abs(limiter.remaining_requests() - expected_tokens) <= tolerance

    def test_get_reset_time(self, mock_time):
        """Test that reset time is calculated correctly."""
        mock_time.return_value = 1000
        limiter = RateLimiter("3/s")

        # Use up all tokens
        limiter.allow_request()
        limiter.allow_request()
        limiter.allow_request()

        # Should be reset in 1 second
        assert 0.9 <= limiter.get_reset_time() <= 1.1

        # Advance time partially
        mock_time.return_value = 1000.5

        # Reset time should now be lower
        assert 0.4 <= limiter.get_reset_time() <= 0.6


@pytest.mark.unit
class TestRateLimiterAdvanced:
    """Advanced tests for rate limiter behavior."""

    def test_adaptive_rate_limit(self, mock_time):
        """Test dynamically changing the rate limit during operation."""
        mock_time.return_value = 1000
        limiter = RateLimiter("3/s")

        # Use initial configuration - 3 requests allowed
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True
        assert limiter.allow_request() is False

        # Change rate limit to be more permissive
        limiter.set_rate_limit("5/s")

        # Reset tokens
        mock_time.return_value = 1001  # 1 second later

        # Now should allow 5 requests
        for i in range(5):
            assert limiter.allow_request() is True, f"Request {i} should be allowed"
        assert limiter.allow_request() is False

        # Change to a more restrictive limit
        limiter.set_rate_limit("2/s")

        # Reset tokens
        mock_time.return_value = 1002  # 1 second later

        # Now should only allow 2 requests
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True
        assert limiter.allow_request() is False

    def test_token_bucket_algorithm(self, mock_time):
        """Test token bucket behavior for rate limiting."""
        mock_time.return_value = 1000

        # Create limiter with 10 requests per second
        limiter = RateLimiter("10/s")

        # Use 6 tokens
        for _ in range(6):
            assert limiter.allow_request() is True

        # 4 tokens left, then wait 0.4s (which should add 4 more tokens)
        mock_time.return_value = 1000.4

        # Should be able to make 8 requests (4 leftover + 4 new tokens)
        for _ in range(8):
            assert limiter.allow_request() is True

        assert limiter.allow_request() is False  # 9th should fail

        # Wait for 0.2 more seconds (should generate 2 more tokens)
        mock_time.return_value = 1000.6

        # Should be able to make 2 more requests
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True
        assert limiter.allow_request() is False

    def test_rate_limiter_reset(self):
        """Test explicit reset of rate limiter state."""
        limiter = RateLimiter("3/m")

        # Use all capacity
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True
        assert limiter.allow_request() is False

        # Reset the limiter
        limiter.reset()

        # Should now allow more requests
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True
        assert limiter.allow_request() is True

    def test_burst_capacity(self, burst_rate_limiter):
        """Test handling of request bursts."""
        # Standard limiter - no burst capacity
        standard_limiter = RateLimiter("10/m")

        # Use all capacity
        for i in range(10):
            assert (
                standard_limiter.allow_request() is True
            ), f"Request {i} should be allowed"

        # 11th request should be rejected
        assert standard_limiter.allow_request() is False

        # Use the burst-capable limiter from the fixture
        burst_limiter, original_tokens = burst_rate_limiter

        # Should allow 15 requests (10 regular + 5 burst)
        for i in range(15):
            assert (
                burst_limiter.allow_request() is True
            ), f"Burst request {i} should be allowed"

        # 16th request should be denied
        assert burst_limiter.allow_request() is False

        # Reset for cleanup if needed
        if hasattr(burst_limiter, "tokens") and original_tokens is not None:
            burst_limiter.tokens = original_tokens


@pytest.mark.unit
class TestRateLimiterConcurrency:
    """Tests for rate limiter behavior under concurrent access."""

    def test_concurrent_rate_limiting(self):
        """Test rate limiter under concurrent load."""
        limiter = RateLimiter("5/s")

        # Use ThreadPoolExecutor to simulate concurrent requests
        def make_request():
            return limiter.allow_request()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Submit 10 concurrent requests
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [
                future.result() for future in concurrent.futures.as_completed(futures)
            ]

        # Should have exactly 5 True and 5 False results
        assert results.count(True) == 5
        assert results.count(False) == 5

    def test_distributed_rate_limiting(self):
        """Test conceptual distributed rate limiting."""
        # Create three separate rate limiters (simulating distributed services)
        limiter1 = RateLimiter("3/s")
        limiter2 = RateLimiter("3/s")
        limiter3 = RateLimiter("3/s")

        # Each limiter manages its own rate limit independently
        # In a real distributed system, they would need to share state
        # This test just verifies the concept

        # Each limiter allows 3 requests
        assert all(limiter1.allow_request() for _ in range(3))
        assert not limiter1.allow_request()  # 4th request denied

        assert all(limiter2.allow_request() for _ in range(3))
        assert not limiter2.allow_request()  # 4th request denied

        assert all(limiter3.allow_request() for _ in range(3))
        assert not limiter3.allow_request()  # 4th request denied
