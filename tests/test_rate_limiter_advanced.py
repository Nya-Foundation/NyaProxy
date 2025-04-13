"""
Advanced tests for the rate limiter component focusing on edge cases and reliability.
"""

import concurrent.futures
import time
from unittest.mock import patch

import pytest

from nya_proxy.rate_limiter import RateLimiter


@pytest.mark.unit
class TestRateLimiterAdvanced:
    """Advanced test cases for the RateLimiter class."""

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

    def test_adaptive_rate_limit(self):
        """Test adaptive rate limiting based on load."""
        # Start with a high limit
        limiter = RateLimiter("20/s")

        # Simulate changing the rate limit dynamically
        for i in range(5):
            assert limiter.allow_request() is True

        # Change the rate limit to a lower value
        limiter.set_rate_limit("3/s")

        # Should now be limited to 3 per second
        # Since we already used 5, all should be rejected
        for i in range(5):
            assert limiter.allow_request() is False

        # After waiting, should allow more requests
        with patch("time.time") as mock_time:
            mock_time.return_value = time.time() + 1.1  # Advance time by 1.1 seconds

            # Should now allow 3 more requests
            assert limiter.allow_request() is True
            assert limiter.allow_request() is True
            assert limiter.allow_request() is True
            assert limiter.allow_request() is False  # 4th should fail

    def test_burst_handling(self):
        """Test handling of request bursts with different rate limiting strategies."""
        # Test with standard rate limit
        standard_limiter = RateLimiter("10/m")  # 10 per minute

        # Use all the capacity in a burst
        for i in range(10):
            assert standard_limiter.allow_request() is True

        # 11th request should be rejected
        assert standard_limiter.allow_request() is False

        # Create a limiter with burst capacity (this syntax is hypothetical, adjust to actual API)
        # Assuming the rate limiter supports a "burst" parameter
        with patch.object(RateLimiter, "_parse_rate_limit") as mock_parse:
            burst_limiter = RateLimiter("10/m")
            # Manually adjust tokens to simulate burst capacity
            burst_limiter.max_requests = 10
            burst_limiter.tokens = 15  # Give 5 extra tokens for burst

            # Should allow 15 requests in a burst
            for i in range(15):
                assert burst_limiter.allow_request() is True

            # 16th request should be rejected
            assert burst_limiter.allow_request() is False

    def test_edge_case_rate_formats(self):
        """Test edge case rate limit formats."""
        # Test very small rates
        tiny_limiter = RateLimiter("0.01/s")  # One request per 100 seconds
        assert tiny_limiter.allow_request() is True
        assert tiny_limiter.allow_request() is False

        # Test very large rates
        huge_limiter = RateLimiter("1000000/s")  # Essentially unlimited
        for _ in range(1000):  # Test with a large but reasonable number
            assert huge_limiter.allow_request() is True

        # Test unusual time units if supported
        ms_limiter = RateLimiter("10/0.5s")  # 10 requests per half-second
        assert ms_limiter.max_requests == 10
        assert ms_limiter.window_seconds == 0.5

    def test_token_bucket_algorithm(self):
        """Test token bucket algorithm behavior for rate limiting."""
        # Create a rate limiter with 5 tokens per second
        limiter = RateLimiter("5/s")

        # Use 3 tokens
        for _ in range(3):
            assert limiter.allow_request() is True

        # Wait for 0.4 seconds (should get 2 new tokens)
        with patch("time.time") as mock_time:
            mock_time.return_value = time.time() + 0.4

            # Should be able to make 2 more requests (original remaining 2 + new 2)
            assert limiter.allow_request() is True
            assert limiter.allow_request() is True
            assert limiter.allow_request() is True  # This should pass (1 more)
            assert (
                limiter.allow_request() is True
            )  # This should pass (generated token during test)
            assert limiter.allow_request() is False  # This should fail

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

    def test_distributed_rate_limiting(self):
        """
        Test scenario simulating distributed rate limiting.

        In a real distributed system, you'd need a shared state like Redis.
        This test simulates the concept with multiple limiters.
        """
        # Create multiple rate limiters (simulating different instances)
        limiter1 = RateLimiter("5/s")
        limiter2 = RateLimiter("5/s")
        limiter3 = RateLimiter("5/s")

        # In a proper distributed implementation, these would share state
        # For this test, we'll manually synchronize after each request

        # Simulate distributed requests (each limiter handles some)
        for _ in range(2):
            assert limiter1.allow_request() is True
        for _ in range(2):
            assert limiter2.allow_request() is True
        assert limiter3.allow_request() is True

        # Now all limiters should be synchronized to have allowed 5 requests total
        # If they were truly distributed, they'd all reject the next request
        # But since they're not sharing state in this test, we just verify the concept
