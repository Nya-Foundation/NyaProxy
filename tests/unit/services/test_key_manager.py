import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from nya.common.exceptions import APIKeyExhaustedError, VariablesConfigurationError

# Adjust imports based on potential refactoring
from nya.services.key import KeyManager
from nya.services.lb import LoadBalancer
from nya.services.limit import RateLimiter


@pytest.fixture
def mock_load_balancers():
    # Mock LoadBalancer instances
    lb_api1 = MagicMock(spec=LoadBalancer)
    lb_api1.values = ["key1_1", "key1_2"]
    lb_api1.get_next.side_effect = ["key1_1", "key1_2", "key1_1"]  # Cycle through keys

    lb_api2 = MagicMock(spec=LoadBalancer)
    lb_api2.values = ["key2_1"]
    lb_api2.get_next.return_value = "key2_1"

    lb_empty = MagicMock(spec=LoadBalancer)
    lb_empty.values = []  # No keys configured

    return {
        "api1": lb_api1,
        "api2": lb_api2,
        "empty_api": lb_empty,
    }


@pytest.fixture
def mock_rate_limiters():
    # Mock RateLimiter instances
    rl_endpoint_api1 = MagicMock(spec=RateLimiter)
    rl_endpoint_api1.is_rate_limited.return_value = False
    rl_endpoint_api1.get_reset_time.return_value = 0.0

    rl_key1_1 = MagicMock(spec=RateLimiter)
    rl_key1_1.is_rate_limited.return_value = False
    rl_key1_1.allow_request.return_value = True
    rl_key1_1.get_reset_time.return_value = 0.0

    rl_key1_2 = MagicMock(spec=RateLimiter)
    rl_key1_2.is_rate_limited.return_value = False
    rl_key1_2.allow_request.return_value = True
    rl_key1_2.get_reset_time.return_value = 0.0

    rl_key2_1 = MagicMock(spec=RateLimiter)
    rl_key2_1.is_rate_limited.return_value = False
    rl_key2_1.allow_request.return_value = True
    rl_key2_1.get_reset_time.return_value = 0.0

    return {
        "api1_endpoint": rl_endpoint_api1,
        "api1_key1_1": rl_key1_1,
        "api1_key1_2": rl_key1_2,
        "api2_key2_1": rl_key2_1,
        # No endpoint limiter for api2 intentionally
    }


@pytest.fixture
def key_manager(mock_load_balancers, mock_rate_limiters):
    with patch("nya.services.key.logger") as mock_logger:
        km = KeyManager(
            load_balancers=mock_load_balancers,
            rate_limiters=mock_rate_limiters,
        )
        km._mock_logger = mock_logger  # Store reference for test assertions
        yield km


@pytest.fixture
def rate_limited_key_manager(mock_load_balancers):
    """Fixture for key manager with all keys rate limited"""
    # Create rate limiters where all keys are rate limited
    rl_key1_1 = MagicMock(spec=RateLimiter)
    rl_key1_1.is_rate_limited.return_value = True
    rl_key1_1.allow_request.return_value = False
    rl_key1_1.get_reset_time.return_value = 5.0

    rl_key1_2 = MagicMock(spec=RateLimiter)
    rl_key1_2.is_rate_limited.return_value = True
    rl_key1_2.allow_request.return_value = False
    rl_key1_2.get_reset_time.return_value = 10.0

    rate_limiters = {
        "api1_key1_1": rl_key1_1,
        "api1_key1_2": rl_key1_2,
    }

    with patch("nya.services.key.logger") as mock_logger:
        km = KeyManager(
            load_balancers=mock_load_balancers,
            rate_limiters=rate_limiters,
        )
        km._mock_logger = mock_logger
        yield km


# --- Test Cases ---


def test_init(key_manager, mock_load_balancers, mock_rate_limiters):
    assert key_manager.load_balancers == mock_load_balancers
    assert key_manager.rate_limiters == mock_rate_limiters
    assert isinstance(key_manager.lock, asyncio.Lock)


def test_get_key_rate_limiter(key_manager, mock_rate_limiters):
    assert (
        key_manager.get_key_rate_limiter("api1", "key1_1")
        == mock_rate_limiters["api1_key1_1"]
    )
    assert (
        key_manager.get_key_rate_limiter("api2", "key2_1")
        == mock_rate_limiters["api2_key2_1"]
    )
    assert key_manager.get_key_rate_limiter("api1", "non_existent_key") is None
    assert key_manager.get_key_rate_limiter("non_existent_api", "key1_1") is None


def test_get_api_rate_limiter(key_manager, mock_rate_limiters):
    assert (
        key_manager.get_api_rate_limiter("api1") == mock_rate_limiters["api1_endpoint"]
    )
    assert key_manager.get_api_rate_limiter("api2") is None  # Not configured
    assert key_manager.get_api_rate_limiter("non_existent_api") is None


@pytest.mark.asyncio
async def test_is_api_available(key_manager, mock_rate_limiters):
    # API1 endpoint limiter allows
    mock_rate_limiters["api1_endpoint"].is_rate_limited.return_value = False
    assert await key_manager.is_api_available("api1") is True

    # API1 endpoint limiter blocks
    mock_rate_limiters["api1_endpoint"].is_rate_limited.return_value = True
    assert await key_manager.is_api_available("api1") is False

    # API2 has no endpoint limiter, should be available
    assert await key_manager.is_api_available("api2") is True

    # Non-existent API
    assert (
        await key_manager.is_api_available("non_existent_api") is True
    )  # No limiter means available


@pytest.mark.asyncio
async def test_has_available_keys_success(key_manager, mock_rate_limiters):
    # Both keys for api1 are available
    mock_rate_limiters["api1_key1_1"].is_rate_limited.return_value = False
    mock_rate_limiters["api1_key1_2"].is_rate_limited.return_value = False
    assert await key_manager.has_available_keys("api1") is True

    # Only one key for api1 is available
    mock_rate_limiters["api1_key1_1"].is_rate_limited.return_value = True
    mock_rate_limiters["api1_key1_2"].is_rate_limited.return_value = False
    assert await key_manager.has_available_keys("api1") is True

    # API2 key is available
    mock_rate_limiters["api2_key2_1"].is_rate_limited.return_value = False
    assert await key_manager.has_available_keys("api2") is True


@pytest.mark.asyncio
async def test_has_available_keys_failure(key_manager, mock_rate_limiters):
    # Both keys for api1 are rate limited
    mock_rate_limiters["api1_key1_1"].is_rate_limited.return_value = True
    mock_rate_limiters["api1_key1_2"].is_rate_limited.return_value = True
    assert await key_manager.has_available_keys("api1") is False

    # API2 key is rate limited
    mock_rate_limiters["api2_key2_1"].is_rate_limited.return_value = True
    assert await key_manager.has_available_keys("api2") is False

    # API with no keys configured
    assert await key_manager.has_available_keys("empty_api") is False

    # Non-existent API (no load balancer)
    assert await key_manager.has_available_keys("non_existent_api") is False


@pytest.mark.asyncio
async def test_get_available_key_success(
    key_manager, mock_load_balancers, mock_rate_limiters
):
    # First call gets key1_1, which is allowed
    mock_rate_limiters["api1_key1_1"].allow_request.return_value = True
    key = await key_manager.get_available_key("api1")
    assert key == "key1_1"
    mock_load_balancers["api1"].get_next.assert_called_once()
    mock_rate_limiters["api1_key1_1"].allow_request.assert_called_once()

    # Second call gets key1_2, which is allowed
    mock_rate_limiters["api1_key1_2"].allow_request.return_value = True
    key = await key_manager.get_available_key("api1")
    assert key == "key1_2"
    assert mock_load_balancers["api1"].get_next.call_count == 2
    mock_rate_limiters["api1_key1_2"].allow_request.assert_called_once()


@pytest.mark.asyncio
async def test_get_available_key_rate_limited_key(
    key_manager, mock_load_balancers, mock_rate_limiters
):
    # First call gets key1_1, but it's rate limited
    mock_rate_limiters["api1_key1_1"].allow_request.return_value = False
    # Second call (internal retry) gets key1_2, which is allowed
    mock_rate_limiters["api1_key1_2"].allow_request.return_value = True

    key = await key_manager.get_available_key("api1")
    assert key == "key1_2"
    # get_next called twice (once for key1_1, once for key1_2)
    assert mock_load_balancers["api1"].get_next.call_count == 2
    mock_rate_limiters["api1_key1_1"].allow_request.assert_called_once()
    mock_rate_limiters["api1_key1_2"].allow_request.assert_called_once()


@pytest.mark.asyncio
async def test_get_available_key_all_keys_rate_limited(
    key_manager, mock_load_balancers, mock_rate_limiters
):
    # Both keys are rate limited
    mock_rate_limiters["api1_key1_1"].allow_request.return_value = False
    mock_rate_limiters["api1_key1_2"].allow_request.return_value = False

    with pytest.raises(APIKeyExhaustedError, match="api1"):
        await key_manager.get_available_key("api1")

    # get_next called for each key
    assert mock_load_balancers["api1"].get_next.call_count == 2
    mock_rate_limiters["api1_key1_1"].allow_request.assert_called_once()
    mock_rate_limiters["api1_key1_2"].allow_request.assert_called_once()
    # Check that warning was logged
    key_manager._mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_get_available_key_no_rate_limit_check(
    key_manager, mock_load_balancers, mock_rate_limiters
):
    # Even if keys are rate limited, should return the next one
    mock_rate_limiters["api1_key1_1"].allow_request.return_value = False

    key = await key_manager.get_available_key("api1", apply_rate_limit=False)
    assert key == "key1_1"
    mock_load_balancers["api1"].get_next.assert_called_once()
    # allow_request should NOT be called
    mock_rate_limiters["api1_key1_1"].allow_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_available_key_no_load_balancer(key_manager):
    with pytest.raises(
        VariablesConfigurationError,
        match="No load balancer configured for API: non_existent_api",
    ):
        await key_manager.get_available_key("non_existent_api")


@pytest.mark.asyncio
async def test_get_available_key_no_keys_configured(key_manager):
    with pytest.raises(
        APIKeyExhaustedError, match="No API keys configured for empty_api"
    ):
        await key_manager.get_available_key("empty_api")

    # Check that error was logged
    key_manager._mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_get_api_rate_limit_reset(key_manager, mock_rate_limiters):
    mock_rate_limiters["api1_endpoint"].get_reset_time.return_value = 15.5
    assert await key_manager.get_api_rate_limit_reset("api1") == 15.5

    # API2 has no endpoint limiter, should use default
    assert await key_manager.get_api_rate_limit_reset("api2", default=5.0) == 5.0
    assert await key_manager.get_api_rate_limit_reset("api2") == 1.0  # Default default


@pytest.mark.asyncio
async def test_get_key_rate_limit_reset(key_manager, mock_rate_limiters):
    mock_rate_limiters["api1_key1_1"].get_reset_time.return_value = 10.0
    mock_rate_limiters["api1_key1_2"].get_reset_time.return_value = (
        5.0  # Earliest reset
    )
    assert await key_manager.get_key_rate_limit_reset("api1") == 5.0

    # Only one key for api2
    mock_rate_limiters["api2_key2_1"].get_reset_time.return_value = 20.0
    assert await key_manager.get_key_rate_limit_reset("api2") == 20.0


@pytest.mark.asyncio
async def test_get_key_rate_limit_reset_no_limiters(key_manager, mock_load_balancers):
    # Remove limiters for api1 keys
    key_manager.rate_limiters.pop("api1_key1_1", None)
    key_manager.rate_limiters.pop("api1_key1_2", None)

    with pytest.raises(
        VariablesConfigurationError,
        match="Bad API key Configuration, or no rate limiters configured for API: api1",
    ):
        await key_manager.get_key_rate_limit_reset("api1")


@pytest.mark.asyncio
async def test_get_key_rate_limit_reset_no_keys(key_manager):
    with pytest.raises(
        VariablesConfigurationError,
        match="Bad API key Configuration, or no rate limiters configured for API: empty_api",
    ):
        await key_manager.get_key_rate_limit_reset("empty_api")


def test_mark_key_rate_limited(key_manager, mock_rate_limiters):
    reset_duration = 30.0
    key_manager.mark_key_rate_limited("api1", "key1_1", reset_duration)
    mock_rate_limiters["api1_key1_1"].mark_rate_limited.assert_called_once_with(
        reset_duration
    )
    key_manager._mock_logger.info.assert_called_with(
        f"Manually marked key key1... for api1 as rate limited for {reset_duration:.1f}s"
    )


def test_mark_key_rate_limited_no_limiter(key_manager):
    key_manager.mark_key_rate_limited("api1", "non_existent_key", 30.0)
    key_manager._mock_logger.warning.assert_called_with(
        "Cannot mark key non_... for api1 as rate limited: no rate limiter found"
    )


def test_reset_rate_limits_all(key_manager, mock_rate_limiters):
    key_manager.reset_rate_limits()
    for limiter in mock_rate_limiters.values():
        limiter.reset.assert_called_once()
    key_manager._mock_logger.info.assert_called_with("Reset all rate limits")


def test_reset_rate_limits_specific_api(key_manager, mock_rate_limiters):
    key_manager.reset_rate_limits("api1")
    # Check that only api1 limiters were reset
    mock_rate_limiters["api1_endpoint"].reset.assert_called_once()
    mock_rate_limiters["api1_key1_1"].reset.assert_called_once()
    mock_rate_limiters["api1_key1_2"].reset.assert_called_once()
    # Check that api2 limiter was NOT reset
    mock_rate_limiters["api2_key2_1"].reset.assert_not_called()
    key_manager._mock_logger.info.assert_called_with("Reset rate limits for api1")


# --- Additional Test Cases for Better Coverage ---


@pytest.mark.asyncio
async def test_has_available_keys_with_mixed_key_limiters(
    key_manager, mock_rate_limiters
):
    """Test has_available_keys when some keys have no rate limiters"""
    # Remove one key's rate limiter
    key_manager.rate_limiters.pop("api1_key1_1", None)

    # Other key is rate limited
    mock_rate_limiters["api1_key1_2"].is_rate_limited.return_value = True

    # Should still return True because key1_1 has no limiter (considered available)
    assert await key_manager.has_available_keys("api1") is True


@pytest.mark.asyncio
async def test_get_available_key_with_no_key_limiter(key_manager, mock_rate_limiters):
    """Test get_available_key when a key has no rate limiter"""
    # Remove the rate limiter for the first key
    key_manager.rate_limiters.pop("api1_key1_1", None)

    key = await key_manager.get_available_key("api1")
    assert key == "key1_1"

    # Should not check allow_request for non-existent limiter
    mock_rate_limiters["api1_key1_2"].allow_request.assert_not_called()


@pytest.mark.asyncio
async def test_get_available_key_cycle_through_all_keys(
    key_manager, mock_load_balancers, mock_rate_limiters
):
    """Test that get_available_key cycles through all keys when first ones are rate limited"""
    # First key is rate limited, second key is available
    mock_rate_limiters["api1_key1_1"].allow_request.return_value = False
    mock_rate_limiters["api1_key1_2"].allow_request.return_value = True

    # Reset the side_effect to ensure we get the expected sequence
    mock_load_balancers["api1"].get_next.side_effect = ["key1_1", "key1_2"]

    key = await key_manager.get_available_key("api1")
    assert key == "key1_2"

    # Should have tried both keys
    assert mock_load_balancers["api1"].get_next.call_count == 2


def test_clean_rate_limited_keys(key_manager, mock_rate_limiters):
    """Test the _clean_rate_limited_keys method"""
    key_manager._clean_rate_limited_keys("api1")

    # Should reset both key limiters but not the endpoint limiter
    mock_rate_limiters["api1_key1_1"].reset.assert_called_once()
    mock_rate_limiters["api1_key1_2"].reset.assert_called_once()
    mock_rate_limiters["api1_endpoint"].reset.assert_not_called()

    # Should log info for each reset
    assert key_manager._mock_logger.info.call_count == 2


@pytest.mark.asyncio
async def test_get_key_rate_limit_reset_with_missing_load_balancer(key_manager):
    """Test get_key_rate_limit_reset when load balancer doesn't exist"""
    with pytest.raises(AttributeError):
        await key_manager.get_key_rate_limit_reset("non_existent_api")


@pytest.mark.asyncio
async def test_get_key_rate_limit_reset_mixed_limiters(key_manager, mock_rate_limiters):
    """Test get_key_rate_limit_reset when some keys have no limiters"""
    # Remove one key's rate limiter
    key_manager.rate_limiters.pop("api1_key1_1", None)

    # Set reset time for remaining key
    mock_rate_limiters["api1_key1_2"].get_reset_time.return_value = 10.0

    result = await key_manager.get_key_rate_limit_reset("api1")
    assert result == 10.0


def test_reset_rate_limits_specific_api_no_endpoint_limiter(
    key_manager, mock_rate_limiters
):
    """Test reset_rate_limits for API without endpoint limiter"""
    key_manager.reset_rate_limits("api2")

    # api2 has no endpoint limiter, so only key limiter should be reset
    mock_rate_limiters["api2_key2_1"].reset.assert_called_once()
    key_manager._mock_logger.info.assert_called_with("Reset rate limits for api2")


def test_mark_key_rate_limited_key_truncation(key_manager, mock_rate_limiters):
    """Test that mark_key_rate_limited properly truncates long keys in log"""
    # First add a rate limiter for this test
    long_key = "very_long_key_name_that_should_be_truncated"
    mock_limiter = MagicMock(spec=RateLimiter)
    key_manager.rate_limiters[f"api1_{long_key}"] = mock_limiter

    key_manager.mark_key_rate_limited("api1", long_key, 30.0)

    # Should log with truncated key (first 4 chars + ...)
    key_manager._mock_logger.info.assert_called_with(
        "Manually marked key very... for api1 as rate limited for 30.0s"
    )


@pytest.mark.asyncio
async def test_concurrent_key_access(
    key_manager, mock_rate_limiters, mock_load_balancers
):
    """Test that concurrent access to keys is properly synchronized"""
    # Set up keys to be available
    mock_rate_limiters["api1_key1_1"].allow_request.return_value = True
    mock_rate_limiters["api1_key1_2"].allow_request.return_value = True

    # Reset the load balancer to provide a predictable sequence
    mock_load_balancers["api1"].get_next.side_effect = None
    mock_load_balancers["api1"].get_next.return_value = "key1_1"

    # Run multiple concurrent get_available_key calls
    tasks = [key_manager.get_available_key("api1") for _ in range(5)]
    results = await asyncio.gather(*tasks)

    # All should succeed and return valid keys
    assert all(key in ["key1_1", "key1_2"] for key in results)
    assert len(results) == 5


@pytest.mark.asyncio
async def test_api_availability_with_rate_limited_endpoint(
    key_manager, mock_rate_limiters
):
    """Test is_api_available when endpoint is rate limited"""
    mock_rate_limiters["api1_endpoint"].is_rate_limited.return_value = True

    result = await key_manager.is_api_available("api1")
    assert result is False

    # Verify the endpoint limiter was checked
    mock_rate_limiters["api1_endpoint"].is_rate_limited.assert_called_once()


@pytest.mark.asyncio
async def test_get_api_rate_limit_reset_with_various_defaults(
    key_manager, mock_rate_limiters
):
    """Test get_api_rate_limit_reset with different default values"""
    # Test with custom default
    result = await key_manager.get_api_rate_limit_reset("api2", default=10.0)
    assert result == 10.0

    # Test with standard default
    result = await key_manager.get_api_rate_limit_reset("api2")
    assert result == 1.0


def test_reset_rate_limits_nonexistent_api(key_manager):
    """Test reset_rate_limits with non-existent API"""
    # Should not raise an error, but also shouldn't reset anything
    key_manager.reset_rate_limits("non_existent_api")
    key_manager._mock_logger.info.assert_called_with(
        "Reset rate limits for non_existent_api"
    )


@pytest.mark.asyncio
async def test_has_available_keys_all_rate_limited(rate_limited_key_manager):
    """Test has_available_keys when all keys are rate limited"""
    result = await rate_limited_key_manager.has_available_keys("api1")
    assert result is False


@pytest.mark.asyncio
async def test_get_key_rate_limit_reset_returns_minimum(rate_limited_key_manager):
    """Test that get_key_rate_limit_reset returns the minimum reset time"""
    result = await rate_limited_key_manager.get_key_rate_limit_reset("api1")
    assert result == 5.0  # Should return the minimum (key1_1's reset time)


@pytest.mark.asyncio
async def test_load_balancer_integration(key_manager, mock_load_balancers):
    """Test integration with load balancer cycling"""
    # Reset side_effect and set up a cycling pattern
    mock_load_balancers["api1"].get_next.side_effect = None
    call_count = 0

    def cycling_get_next():
        nonlocal call_count
        keys = ["key1_1", "key1_2"]
        result = keys[call_count % 2]
        call_count += 1
        return result

    mock_load_balancers["api1"].get_next.side_effect = cycling_get_next

    # Test that load balancer cycling works correctly
    keys = []
    for _ in range(4):  # More than the number of keys to test cycling
        key = await key_manager.get_available_key("api1", apply_rate_limit=False)
        keys.append(key)

    # Should cycle through the keys
    assert keys == ["key1_1", "key1_2", "key1_1", "key1_2"]


@pytest.mark.asyncio
async def test_edge_case_empty_load_balancer_values(key_manager):
    """Test behavior when load balancer has empty values list"""
    # This tests the edge case where load balancer exists but has no keys
    result = await key_manager.has_available_keys("empty_api")
    assert result is False

    with pytest.raises(APIKeyExhaustedError):
        await key_manager.get_available_key("empty_api")


def test_rate_limiter_naming_convention(key_manager):
    """Test that rate limiter naming follows expected convention"""
    # Test key rate limiter naming
    assert key_manager.get_key_rate_limiter("api1", "key1_1") is not None
    assert key_manager.get_key_rate_limiter("api1", "key1_2") is not None

    # Test endpoint rate limiter naming
    assert key_manager.get_api_rate_limiter("api1") is not None
    assert (
        key_manager.get_api_rate_limiter("api2") is None
    )  # Intentionally not configured


@pytest.mark.asyncio
async def test_stress_test_key_selection(
    key_manager, mock_rate_limiters, mock_load_balancers
):
    """Stress test for rapid key selection"""
    # Set all keys as available
    for limiter in mock_rate_limiters.values():
        if hasattr(limiter, "allow_request"):
            limiter.allow_request.return_value = True

    # Reset the load balancer to provide a predictable sequence
    mock_load_balancers["api1"].get_next.side_effect = None
    mock_load_balancers["api1"].get_next.return_value = "key1_1"

    # Rapidly select keys
    keys = []
    for _ in range(20):
        key = await key_manager.get_available_key("api1")
        keys.append(key)

    # All selections should succeed
    assert len(keys) == 20
    assert all(key in ["key1_1", "key1_2"] for key in keys)
