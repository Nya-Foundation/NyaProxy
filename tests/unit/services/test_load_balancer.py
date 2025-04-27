import logging
import random
from unittest.mock import MagicMock

import pytest

# Assuming the refactored structure, adjust import if needed
from nya_proxy.services.load_balancer import LoadBalancer


@pytest.fixture
def mock_logger():
    return MagicMock(spec=logging.Logger)


@pytest.fixture
def values():
    return ["key1", "key2", "key3"]


# --- Test Cases ---


def test_init(values, mock_logger):
    lb = LoadBalancer(values, strategy="random", logger=mock_logger)
    assert lb.values == values
    assert lb.strategy_name == "random"
    assert lb.logger == mock_logger
    assert lb.current_index == 0
    assert list(lb.requests_count.keys()) == values
    assert list(lb.response_times.keys()) == values
    mock_logger.debug.assert_called()


def test_init_empty_values(mock_logger):
    lb = LoadBalancer([], logger=mock_logger)
    assert lb.values == [""]  # Should default to one empty string
    assert lb.strategy_name == "round_robin"
    assert lb.requests_count == {"": 0}
    assert lb.response_times == {"": []}


def test_init_invalid_strategy(values, mock_logger):
    lb = LoadBalancer(values, strategy="invalid_strategy", logger=mock_logger)
    assert lb.strategy_name == "invalid_strategy"
    # Should default to round_robin internally when getting function
    assert lb._get_strategy_function().__name__ == "_round_robin_select"
    mock_logger.warning.assert_called_with(
        "Unknown strategy 'invalid_strategy', using round_robin instead"
    )


# --- Strategy Tests ---


def test_round_robin_select(values, mock_logger):
    lb = LoadBalancer(values, strategy="round_robin", logger=mock_logger)
    assert lb.get_next() == "key1"
    assert lb.get_next() == "key2"
    assert lb.get_next() == "key3"
    assert lb.get_next() == "key1"  # Wraps around
    assert lb.current_index == 1


def test_random_select(values, mock_logger, monkeypatch):
    lb = LoadBalancer(values, strategy="random", logger=mock_logger)
    # Ensure random.choice is called and returns a valid value
    mock_choice = MagicMock(side_effect=["key2", "key1", "key3"])
    monkeypatch.setattr(random, "choice", mock_choice)

    assert lb.get_next() == "key2"
    assert lb.get_next() == "key1"
    assert lb.get_next() == "key3"
    assert mock_choice.call_count == 3
    # Check if requests_count is updated (implicitly tested via get_next)
    assert lb.requests_count["key2"] > 0
    assert lb.requests_count["key1"] > 0
    assert lb.requests_count["key3"] > 0


def test_least_requests_select(values, mock_logger):
    lb = LoadBalancer(values, strategy="least_requests", logger=mock_logger)

    # Initially, all counts are 0, should select randomly among them (or first)
    first = lb.get_next()
    assert first in values
    assert lb.requests_count[first] == 1

    # Make key1 have the most requests
    lb.requests_count = {"key1": 5, "key2": 1, "key3": 1}
    next_val = lb.get_next()
    # Should select either key2 or key3
    assert next_val in ["key2", "key3"]
    assert lb.requests_count[next_val] == 2  # Incremented after selection

    # Make key3 the least
    lb.requests_count = {"key1": 5, "key2": 3, "key3": 2}
    assert lb.get_next() == "key3"
    assert lb.requests_count["key3"] == 3


def test_fastest_response_select(values, mock_logger):
    lb = LoadBalancer(values, strategy="fastest_response", logger=mock_logger)

    # Initially no response times, should select randomly (or first)
    first = lb.get_next()
    assert first in values

    # Record some response times
    lb.record_response_time("key1", 0.5)  # Slowest
    lb.record_response_time("key2", 0.1)  # Fastest
    lb.record_response_time("key3", 0.3)

    # Should select the fastest (key2)
    assert lb.get_next() == "key2"

    # Add more times, make key3 fastest avg
    lb.record_response_time("key1", 0.6)  # Avg 0.55
    lb.record_response_time("key2", 0.2)  # Avg 0.15
    lb.record_response_time(
        "key3", 0.05
    )  # Avg 0.175 -> Error in manual calc, let's re-evaluate
    # key1: [0.5, 0.6] -> avg 0.55
    # key2: [0.1, 0.2] -> avg 0.15
    # key3: [0.3, 0.05] -> avg 0.175
    # So key2 is still fastest avg
    assert lb.get_next() == "key2"

    # Add a time for key3 to make it fastest
    lb.record_response_time("key3", 0.01)  # key3 avg: (0.3 + 0.05 + 0.01) / 3 = 0.12
    assert lb.get_next() == "key3"

    # Test case where one key has no data - should be preferred
    lb.response_times = {"key1": [0.5], "key2": [0.6], "key3": []}
    assert lb.get_next() == "key3"


def test_weighted_select(values, mock_logger, monkeypatch):
    lb = LoadBalancer(values, strategy="weighted", logger=mock_logger)
    weights = [1, 5, 10]  # key1: 1, key2: 5, key3: 10
    lb.set_weights(weights)
    assert lb.weights == weights

    # Mock random.uniform to control selection
    # Total weight = 16
    # key1: 0 <= r <= 1
    # key2: 1 < r <= 6
    # key3: 6 < r <= 16
    mock_uniform = MagicMock(
        side_effect=[
            0.5,  # selects key1
            3.0,  # selects key2
            10.0,  # selects key3
            15.9,  # selects key3
            5.5,  # selects key2
        ]
    )
    monkeypatch.setattr(random, "uniform", mock_uniform)

    assert lb.get_next() == "key1"
    assert lb.get_next() == "key2"
    assert lb.get_next() == "key3"
    assert lb.get_next() == "key3"
    assert lb.get_next() == "key2"
    assert mock_uniform.call_count == 5


def test_weighted_select_zero_weights(values, mock_logger, monkeypatch):
    lb = LoadBalancer(values, strategy="weighted", logger=mock_logger)
    weights = [0, 0, 0]
    lb.set_weights(weights)

    # Should fall back to random choice
    mock_choice = MagicMock(return_value="key2")
    monkeypatch.setattr(random, "choice", mock_choice)
    assert lb.get_next() == "key2"
    mock_choice.assert_called_once_with(values)


def test_set_weights_value_error(values, mock_logger):
    lb = LoadBalancer(values, strategy="weighted", logger=mock_logger)
    with pytest.raises(
        ValueError, match="Weights length \(2\) must match values length \(3\)"
    ):
        lb.set_weights([1, 2])


# --- Metrics Recording Tests ---


def test_record_request_count(values, mock_logger):
    lb = LoadBalancer(values, strategy="least_requests", logger=mock_logger)
    assert lb.requests_count["key1"] == 0
    lb.record_request_count("key1", active=True)
    assert lb.requests_count["key1"] == 1
    lb.record_request_count("key1", active=True)
    assert lb.requests_count["key1"] == 2
    lb.record_request_count("key1", active=False)
    assert lb.requests_count["key1"] == 1
    lb.record_request_count("key1", active=False)
    assert lb.requests_count["key1"] == 0
    # Should not go below 0
    lb.record_request_count("key1", active=False)
    assert lb.requests_count["key1"] == 0
    # Test unknown key
    lb.record_request_count("unknown_key", active=True)  # Should not raise error


def test_record_response_time(values, mock_logger):
    lb = LoadBalancer(values, strategy="fastest_response", logger=mock_logger)
    assert lb.response_times["key2"] == []
    lb.record_response_time("key2", 0.123)
    assert lb.response_times["key2"] == [0.123]
    lb.record_response_time("key2", 0.456)
    assert lb.response_times["key2"] == [0.123, 0.456]
    # Test unknown key
    lb.record_response_time("unknown_key", 0.1)  # Should not raise error


def test_record_response_time_limit(values, mock_logger, monkeypatch):
    # Mock MAX_QUEUE_SIZE for this test if it's imported from constants
    monkeypatch.setattr("nya_proxy.services.load_balancer.MAX_QUEUE_SIZE", 3)
    lb = LoadBalancer(values, strategy="fastest_response", logger=mock_logger)

    lb.record_response_time("key1", 0.1)
    lb.record_response_time("key1", 0.2)
    lb.record_response_time("key1", 0.3)
    assert lb.response_times["key1"] == [0.1, 0.2, 0.3]

    # Add one more, should remove the oldest (0.1)
    lb.record_response_time("key1", 0.4)
    assert lb.response_times["key1"] == [0.2, 0.3, 0.4]

    # Add another
    lb.record_response_time("key1", 0.5)
    assert lb.response_times["key1"] == [0.3, 0.4, 0.5]
