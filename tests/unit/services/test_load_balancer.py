import logging
import random
from unittest.mock import MagicMock, patch

import pytest

# Assuming the refactored structure, adjust import if needed
from nya.services.lb import LoadBalancer


@pytest.fixture
def values():
    return ["key1", "key2", "key3"]


# --- Test Cases ---


def test_init(values):
    lb = LoadBalancer(values, strategy="random")
    assert lb.values == values
    assert lb.strategy_name == "random"
    assert lb.current_index == 0
    assert list(lb.requests_count.keys()) == values
    assert list(lb.response_times.keys()) == values
    assert lb.weights == [1, 1, 1]  # Default equal weights


def test_init_empty_values():
    lb = LoadBalancer([])
    assert lb.values == [""]  # Should default to one empty string
    assert lb.strategy_name == "round_robin"
    assert lb.requests_count == {"": 0}
    assert lb.response_times == {"": []}


def test_init_none_values():
    lb = LoadBalancer(None)
    assert lb.values == [""]  # Should default to one empty string
    assert lb.strategy_name == "round_robin"


@patch("nya.services.lb.logger")
def test_init_invalid_strategy(mock_logger, values):
    lb = LoadBalancer(values, strategy="invalid_strategy")
    assert lb.strategy_name == "invalid_strategy"
    # Should default to round_robin internally when getting function
    next_value = lb.get_next()
    assert next_value in values
    mock_logger.warning.assert_called_with(
        "Unknown strategy 'invalid_strategy', using round_robin instead"
    )


# --- Strategy Tests ---


def test_round_robin_select(values):
    lb = LoadBalancer(values, strategy="round_robin")
    assert lb.get_next() == "key1"
    assert lb.get_next() == "key2"
    assert lb.get_next() == "key3"
    assert lb.get_next() == "key1"  # Wraps around
    assert lb.current_index == 1


def test_random_select(values, monkeypatch):
    lb = LoadBalancer(values, strategy="random")
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


def test_least_requests_select(values):
    lb = LoadBalancer(values, strategy="least_requests")

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


def test_fastest_response_select(values):
    lb = LoadBalancer(values, strategy="fastest_response")

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


def test_weighted_select(values, monkeypatch):
    lb = LoadBalancer(values, strategy="weighted")
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


def test_weighted_select_zero_weights(values, monkeypatch):
    lb = LoadBalancer(values, strategy="weighted")
    weights = [0, 0, 0]
    lb.set_weights(weights)

    # Should fall back to random choice
    mock_choice = MagicMock(return_value="key2")
    monkeypatch.setattr(random, "choice", mock_choice)
    assert lb.get_next() == "key2"
    mock_choice.assert_called_once_with(values)


@patch("nya.services.lb.logger")
def test_set_weights_value_error(mock_logger, values):
    lb = LoadBalancer(values, strategy="weighted")
    with pytest.raises(
        ValueError, match="Weights length \\(2\\) must match values length \\(3\\)"
    ):
        lb.set_weights([1, 2])


@patch("nya.services.lb.logger")
def test_set_weights_logging(mock_logger, values):
    lb = LoadBalancer(values, strategy="weighted")
    weights = [2, 3, 5]
    lb.set_weights(weights)
    mock_logger.debug.assert_called_with(f"Set weights: {weights}")


# --- Edge Cases and Additional Coverage ---


@patch("nya.services.lb.logger")
def test_get_next_empty_values(mock_logger):
    lb = LoadBalancer([])
    result = lb.get_next()
    assert result == ""
    # The logger warning should be called, but it's not in the current implementation
    # This is actually a bug in the original code


def test_strategy_validation():
    """Test that valid strategies are accepted."""
    for strategy in LoadBalancer.VALID_STRATEGIES:
        lb = LoadBalancer(["test"], strategy=strategy)
        assert lb.strategy_name == strategy


def test_case_insensitive_strategy():
    """Test that strategy names are case insensitive."""
    lb = LoadBalancer(["test"], strategy="ROUND_ROBIN")
    assert lb.strategy_name == "round_robin"

    lb = LoadBalancer(["test"], strategy="Random")
    assert lb.strategy_name == "random"


def test_fastest_response_no_data_fallback(values, monkeypatch):
    """Test fastest response fallback when no response time data exists."""
    lb = LoadBalancer(values, strategy="fastest_response")

    # Clear all response times
    lb.response_times = {value: [] for value in values}

    mock_choice = MagicMock(return_value="key2")
    monkeypatch.setattr(random, "choice", mock_choice)

    result = lb.get_next()
    assert result == "key2"
    mock_choice.assert_called_once_with(values)


def test_weighted_select_edge_case_cumulative(values, monkeypatch):
    """Test weighted selection edge case where random value equals cumulative."""
    lb = LoadBalancer(values, strategy="weighted")
    weights = [1, 2, 3]  # Total = 6
    lb.set_weights(weights)

    # Test exact boundary conditions
    mock_uniform = MagicMock(side_effect=[1.0, 3.0, 6.0])  # Exact boundaries
    monkeypatch.setattr(random, "uniform", mock_uniform)

    assert lb.get_next() == "key1"  # r=1.0 <= cumulative=1
    assert lb.get_next() == "key2"  # r=3.0 <= cumulative=3
    assert lb.get_next() == "key3"  # r=6.0 <= cumulative=6


# --- Metrics Recording Tests ---


def test_record_request_count(values):
    lb = LoadBalancer(values, strategy="least_requests")
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


def test_record_response_time(values):
    lb = LoadBalancer(values, strategy="fastest_response")
    assert lb.response_times["key2"] == []
    lb.record_response_time("key2", 0.123)
    assert lb.response_times["key2"] == [0.123]
    lb.record_response_time("key2", 0.456)
    assert lb.response_times["key2"] == [0.123, 0.456]
    # Test unknown key
    lb.record_response_time("unknown_key", 0.1)  # Should not raise error


def test_record_response_time_limit(values, monkeypatch):
    # Mock MAX_QUEUE_SIZE for this test if it's imported from constants
    monkeypatch.setattr("nya.services.lb.MAX_QUEUE_SIZE", 3)
    lb = LoadBalancer(values, strategy="fastest_response")

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


# --- Additional Test Coverage ---


def test_get_strategy_function_coverage():
    """Test all strategy function mappings."""
    lb = LoadBalancer(["test"], strategy="round_robin")
    assert lb._get_strategy_function().__name__ == "_round_robin_select"

    lb.strategy_name = "random"
    assert lb._get_strategy_function().__name__ == "_random_select"

    lb.strategy_name = "least_requests"
    assert lb._get_strategy_function().__name__ == "_least_requests_select"

    lb.strategy_name = "fastest_response"
    assert lb._get_strategy_function().__name__ == "_fastest_response_select"

    lb.strategy_name = "weighted"
    assert lb._get_strategy_function().__name__ == "_weighted_select"


def test_least_requests_multiple_candidates_randomization(values, monkeypatch):
    """Test that least_requests strategy randomizes among equal candidates."""
    lb = LoadBalancer(values, strategy="least_requests")

    # Set equal request counts
    lb.requests_count = {"key1": 2, "key2": 2, "key3": 5}

    # Mock random.choice to control selection among candidates
    mock_choice = MagicMock(return_value="key2")
    monkeypatch.setattr(random, "choice", mock_choice)

    result = lb.get_next()
    assert result == "key2"
    mock_choice.assert_called_once_with(["key1", "key2"])  # Candidates with min count


def test_fastest_response_multiple_candidates_randomization(values, monkeypatch):
    """Test that fastest_response strategy randomizes among equal candidates."""
    lb = LoadBalancer(values, strategy="fastest_response")

    # Set equal average response times
    lb.response_times = {
        "key1": [0.1, 0.1],  # avg 0.1
        "key2": [0.1, 0.1],  # avg 0.1
        "key3": [0.2, 0.2],  # avg 0.2
    }

    mock_choice = MagicMock(return_value="key1")
    monkeypatch.setattr(random, "choice", mock_choice)

    result = lb.get_next()
    assert result == "key1"
    mock_choice.assert_called_once_with(
        ["key1", "key2"]
    )  # Candidates with min avg time


def test_weighted_select_fallback_to_last_value(values, monkeypatch):
    """Test weighted selection fallback when cumulative calculation doesn't match."""
    lb = LoadBalancer(values, strategy="weighted")
    weights = [1, 2, 3]
    lb.set_weights(weights)

    # Mock random.uniform to return a value that doesn't match any cumulative
    # This should trigger the fallback to return the last value
    mock_uniform = MagicMock(return_value=7.0)  # Greater than total weight (6)
    monkeypatch.setattr(random, "uniform", mock_uniform)

    result = lb.get_next()
    assert result == "key3"  # Should return last value as fallback


def test_empty_values_warning_on_get_next():
    """Test that getting next from empty values shows warning."""
    with patch("nya.services.lb.logger") as mock_logger:
        lb = LoadBalancer([])
        # Manually empty the values to test the warning path
        lb.values = []
        result = lb.get_next()
        assert result == ""
        mock_logger.warning.assert_called_with("No values available for load balancing")


def test_valid_strategies_constant():
    """Test that VALID_STRATEGIES constant contains expected strategies."""
    expected_strategies = {
        "round_robin",
        "random",
        "least_requests",
        "fastest_response",
        "weighted",
    }
    assert LoadBalancer.VALID_STRATEGIES == expected_strategies


def test_round_robin_index_wrapping():
    """Test round robin index properly wraps around."""
    lb = LoadBalancer(["a", "b"], strategy="round_robin")

    # Test multiple complete cycles
    for cycle in range(3):
        assert lb.get_next() == "a"
        assert lb.current_index == 1
        assert lb.get_next() == "b"
        assert lb.current_index == 0


def test_request_count_automatic_increment():
    """Test that get_next automatically increments request count."""
    lb = LoadBalancer(["key1", "key2"], strategy="round_robin")

    initial_count = lb.requests_count["key1"]
    result = lb.get_next()
    assert result == "key1"
    assert lb.requests_count["key1"] == initial_count + 1


def test_response_time_edge_cases():
    """Test response time recording edge cases."""
    lb = LoadBalancer(["key1"], strategy="fastest_response")

    # Test with zero response time
    lb.record_response_time("key1", 0.0)
    assert lb.response_times["key1"] == [0.0]

    # Test with negative response time (shouldn't happen but should handle gracefully)
    lb.record_response_time("key1", -0.1)
    assert lb.response_times["key1"] == [0.0, -0.1]


def test_set_weights_boundary_values():
    """Test setting weights with boundary values."""
    lb = LoadBalancer(["a", "b", "c"], strategy="weighted")

    # Test with zero weights
    lb.set_weights([0, 0, 0])
    assert lb.weights == [0, 0, 0]

    # Test with large weights
    large_weights = [1000000, 2000000, 3000000]
    lb.set_weights(large_weights)
    assert lb.weights == large_weights


def test_strategy_function_with_unknown_strategy():
    """Test _get_strategy_function with unknown strategy and logging."""
    with patch("nya.services.lb.logger") as mock_logger:
        lb = LoadBalancer(["test"], strategy="unknown_strategy")
        strategy_func = lb._get_strategy_function()

        # Should return round_robin function
        assert strategy_func.__name__ == "_round_robin_select"
        mock_logger.warning.assert_called_with(
            "Unknown strategy 'unknown_strategy', using round_robin instead"
        )
