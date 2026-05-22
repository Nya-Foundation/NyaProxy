"""
Unit tests for ``nya.services.lb.LoadBalancer``.

Each strategy is exercised for its selection rule plus the bookkeeping
helpers (request counts, response times, weights).
"""

import pytest

from nya.services.lb import LoadBalancer

# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def test_empty_key_list_defaults_to_single_blank_key():
    lb = LoadBalancer(keys=[])
    assert lb.keys == [""]


def test_strategy_name_is_lowercased():
    assert LoadBalancer(["a"], strategy="ROUND_ROBIN").strategy_name == "round_robin"


# --------------------------------------------------------------------------
# round_robin
# --------------------------------------------------------------------------


def test_round_robin_cycles_through_keys_in_order():
    lb = LoadBalancer(["a", "b", "c"], strategy="round_robin")
    assert [lb.next() for _ in range(6)] == ["a", "b", "c", "a", "b", "c"]


# --------------------------------------------------------------------------
# random
# --------------------------------------------------------------------------


def test_random_always_returns_a_known_key():
    lb = LoadBalancer(["a", "b", "c"], strategy="random")
    for _ in range(50):
        assert lb.next() in {"a", "b", "c"}


# --------------------------------------------------------------------------
# least_requests
# --------------------------------------------------------------------------


def test_least_requests_picks_the_least_used_key():
    lb = LoadBalancer(["a", "b", "c"], strategy="least_requests")
    lb.update_request_count("a", 5)
    lb.update_request_count("b", 2)
    # 'c' has zero requests and must be chosen.
    assert lb.next() == "c"


# --------------------------------------------------------------------------
# fastest_response
# --------------------------------------------------------------------------


def test_fastest_response_picks_lowest_average_latency():
    lb = LoadBalancer(["a", "b"], strategy="fastest_response")
    lb.record_response_time("a", 1.0)
    lb.record_response_time("a", 1.0)
    lb.record_response_time("b", 0.1)
    assert lb.next() == "b"


def test_fastest_response_prioritises_unused_keys():
    """A key with no recorded times is treated as 0 (highest priority)."""
    lb = LoadBalancer(["a", "b"], strategy="fastest_response")
    lb.record_response_time("a", 5.0)
    assert lb.next() == "b"


# --------------------------------------------------------------------------
# weighted
# --------------------------------------------------------------------------


def test_weighted_only_returns_keys_with_nonzero_weight():
    lb = LoadBalancer(["a", "b"], strategy="weighted")
    lb.set_weights([1, 0])  # 'b' can never be chosen
    for _ in range(50):
        assert lb.next() == "a"


def test_set_weights_pads_missing_weights_with_one():
    lb = LoadBalancer(["a", "b", "c"], strategy="weighted")
    lb.set_weights([5])
    assert lb.weights == [5, 1, 1]


def test_set_weights_truncates_extra_weights():
    lb = LoadBalancer(["a", "b"], strategy="weighted")
    lb.set_weights([1, 2, 3, 4])
    assert lb.weights == [1, 2]


# --------------------------------------------------------------------------
# strategy resolution
# --------------------------------------------------------------------------


def test_unknown_strategy_falls_back_to_round_robin():
    lb = LoadBalancer(["a", "b"], strategy="does_not_exist")
    assert [lb.next() for _ in range(4)] == ["a", "b", "a", "b"]


def test_next_accepts_a_per_call_strategy_override():
    lb = LoadBalancer(["a", "b", "c"], strategy="round_robin")
    # Override to random for one call; result must still be a known key.
    assert lb.next(strategy="random") in {"a", "b", "c"}


# --------------------------------------------------------------------------
# bookkeeping helpers
# --------------------------------------------------------------------------


def test_update_request_count_ignores_unknown_keys():
    lb = LoadBalancer(["a"], strategy="round_robin")
    lb.update_request_count("ghost", 10)  # must not raise or register
    assert "ghost" not in lb.requests_count


def test_record_response_time_registers_unknown_keys():
    """Unlike update_request_count, response-time recording auto-registers."""
    lb = LoadBalancer(["a"], strategy="fastest_response")
    lb.record_response_time("late-key", 0.5)
    assert lb.response_times["late-key"] == [0.5]


def test_record_response_time_caps_history_length():
    from nya.common.constants import MAX_QUEUE_SIZE

    lb = LoadBalancer(["a"], strategy="fastest_response")
    for i in range(MAX_QUEUE_SIZE + 50):
        lb.record_response_time("a", float(i))
    assert len(lb.response_times["a"]) == MAX_QUEUE_SIZE
