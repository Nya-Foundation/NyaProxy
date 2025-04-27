import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call

import pytest

# Adjust imports based on potential refactoring
from nya_proxy.services.key_manager import KeyManager
from nya_proxy.services.load_balancer import LoadBalancer
from nya_proxy.services.rate_limiter import RateLimiter
from nya_proxy.common.exceptions import (
    APIKeyExhaustedError,
    VariablesConfigurationError,
)


@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)


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
def key_manager(mock_load_balancers, mock_rate_limiters, mock_logger):
    return KeyManager(
        load_balancers=mock_load_balancers,
        rate_limiters=mock_rate_limiters,
        logger=mock_logger,
    )


# --- Test Cases ---


def test_init(key_manager, mock_load_balancers, mock_rate_limiters, mock_logger):
    assert key_manager.load_balancers == mock_load_balancers
    assert key_manager.rate_limiters == mock_rate_limiters
    assert key_manager.logger == mock_logger
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

    with pytest.raises(APIKeyExhaustedError, match="No available API keys for api1"):
        await key_manager.get_available_key("api1")

    # get_next called for each key
    assert mock_load_balancers["api1"].get_next.call_count == 2
    mock_rate_limiters["api1_key1_1"].allow_request.assert_called_once()
    mock_rate_limiters["api1_key1_2"].allow_request.assert_called_once()


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


def test_mark_key_rate_limited(key_manager, mock_rate_limiters, mock_logger):
    reset_duration = 30.0
    key_manager.mark_key_rate_limited("api1", "key1_1", reset_duration)
    mock_rate_limiters["api1_key1_1"].mark_rate_limited.assert_called_once_with(
        reset_duration
    )
    mock_logger.info.assert_called_with(
        f"Manually marked key key1... for api1 as rate limited for {reset_duration:.1f}s"
    )


def test_mark_key_rate_limited_no_limiter(key_manager, mock_logger):
    key_manager.mark_key_rate_limited("api1", "non_existent_key", 30.0)
    mock_logger.warning.assert_called_with(
        "Cannot mark key non_... for api1 as rate limited: no rate limiter found"
    )


def test_reset_rate_limits_all(key_manager, mock_rate_limiters, mock_logger):
    key_manager.reset_rate_limits()
    for limiter in mock_rate_limiters.values():
        limiter.reset.assert_called_once()
    mock_logger.info.assert_called_with("Reset all rate limits")


def test_reset_rate_limits_specific_api(key_manager, mock_rate_limiters, mock_logger):
    key_manager.reset_rate_limits("api1")
    # Check that only api1 limiters were reset
    mock_rate_limiters["api1_endpoint"].reset.assert_called_once()
    mock_rate_limiters["api1_key1_1"].reset.assert_called_once()
    mock_rate_limiters["api1_key1_2"].reset.assert_called_once()
    # Check that api2 limiter was NOT reset
    mock_rate_limiters["api2_key2_1"].reset.assert_not_called()
    mock_logger.info.assert_called_with("Reset rate limits for api1")
