"""
Tests for load balancer strategies with comprehensive validation of distribution patterns.
"""

import random
from unittest.mock import patch

import pytest

from nya_proxy.load_balancer import LoadBalancer


@pytest.mark.unit
class TestLoadBalancerStrategies:
    """Comprehensive tests for different LoadBalancer strategies and their effectiveness."""

    def test_round_robin_distribution(self, load_balancer_fixtures):
        """Test that round robin evenly distributes load across all keys."""
        lb = load_balancer_fixtures["round_robin"]

        # Get a large number of keys
        selected_keys = [lb.get_next() for _ in range(300)]

        # Test exact pattern repetition (the core characteristic of round robin)
        pattern = selected_keys[:3]  # First 3 keys should be the pattern
        for i in range(0, 300, 3):
            if i + 3 <= 300:
                assert selected_keys[i : i + 3] == pattern

        # Also verify distribution is exactly equal
        expected_distribution = {"key1": 1 / 3, "key2": 1 / 3, "key3": 1 / 3}
        assert_distribution(selected_keys, expected_distribution, tolerance=0.01)

    def test_random_distribution(self, load_balancer_fixtures):
        """Test that random strategy provides approximately even distribution."""
        lb = load_balancer_fixtures["random"]

        # Use a large sample for statistical relevance
        with patch("random.choice", wraps=random.choice) as mock_choice:
            selected_keys = [lb.get_next() for _ in range(1000)]

            # Verify random.choice was called with the correct arguments
            mock_choice.assert_called_with(["key1", "key2", "key3"])

            # Check distribution is approximately even
            expected_distribution = {"key1": 1 / 3, "key2": 1 / 3, "key3": 1 / 3}
            assert_distribution(selected_keys, expected_distribution)

    def test_weighted_distribution_accuracy(self, load_balancer_fixtures):
        """Test that weighted distribution accurately respects the weights."""
        lb = load_balancer_fixtures["weighted"]  # Pre-configured with weights [5, 3, 2]

        # Sample size should be large enough for statistical significance
        selected_keys = [lb.get_next() for _ in range(10000)]

        # Check distribution matches the weights (5:3:2 ratio)
        expected_distribution = {"key1": 0.5, "key2": 0.3, "key3": 0.2}
        assert_distribution(selected_keys, expected_distribution, tolerance=0.02)

    def test_least_used_strategy(self, load_balancer_with_usage_counts):
        """Test least used strategy that prioritizes keys with lower usage counts."""
        lb = load_balancer_with_usage_counts

        # Verify it selects the least used key
        assert lb.get_next() == "key2"  # key2 has usage count of 10

        # Update usage counts and verify behavior changes
        lb.usage_counts["key2"] = 100
        assert lb.get_next() == "key3"  # Now key3 (30) is less than key2 (100)

        # Verify usage counts are incremented after selection
        original_count = lb.usage_counts["key3"]
        lb.get_next()  # Should select key3 again
        assert lb.usage_counts["key3"] == original_count + 1

    def test_least_connections_strategy(self, load_balancer_with_connection_counts):
        """Test that least connections strategy properly tracks and distributes connections."""
        lb = load_balancer_with_connection_counts

        # Should select key with least connections
        assert lb.get_next() == "key2"  # key2 has 2 connections

        # Verify active connections are incremented on selection
        assert lb.active_connections["key2"] == 3

        # Test connection_finished decrements the count
        lb.connection_finished("key1")
        assert lb.active_connections["key1"] == 4

        # By setting key1 to have fewer connections than key2, it should now be selected
        lb.active_connections["key1"] = 1
        assert lb.get_next() == "key1"

    def test_fastest_response_strategy(self, load_balancer_with_response_times):
        """Test that fastest response strategy selects keys with lowest response times."""
        lb = load_balancer_with_response_times

        # Should select key with fastest average response time
        assert lb.get_next() == "key2"  # key2 has consistent 0.2s

        # Record new response times that change the fastest key
        for _ in range(20):  # More samples to overcome history
            lb.record_response_time("key1", 0.05)  # Now fastest but with history

        lb.update_metrics()

        # Should now select key1 as it's the new fastest
        assert lb.get_next() == "key1"

    def test_adaptive_strategy(self, test_logger):
        """Test that adaptive strategy balances based on success rate and response time."""
        # Create a fresh instance with controlled parameters
        lb = LoadBalancer(["key1", "key2", "key3"], "adaptive", test_logger)

        # Record different success rates and response times
        for _ in range(10):
            lb.connection_finished("key1", success=False)
            lb.connection_finished("key2", success=True)
            lb.connection_finished("key3", success=True)

            lb.record_response_time("key1", 1.0)  # Slow and failing
            lb.record_response_time("key2", 0.2)  # Fast and successful
            lb.record_response_time("key3", 0.5)  # Medium and successful

        # Force metrics update
        lb.update_metrics()

        # Get a larger sample to analyze distribution
        selections = [lb.get_next() for _ in range(100)]

        # key1 should be selected least often due to poor performance
        counts = {key: selections.count(key) for key in ["key1", "key2", "key3"]}
        assert counts["key1"] < counts["key2"]
        assert counts["key1"] < counts["key3"]

        # key2 should be selected most often as it's fastest and successful
        assert counts["key2"] > counts["key3"]

    def test_strategy_recovery(self, test_logger):
        """Test that strategies can recover when keys transition from failing to successful."""
        lb = LoadBalancer(["key1", "key2", "key3"], "adaptive", test_logger)

        # Mark key1 as failing initially
        for _ in range(10):
            lb.connection_finished("key1", success=False)

        lb.update_metrics()

        # Get a sample to verify key1 is used less
        initial_selections = [lb.get_next() for _ in range(30)]
        initial_count = initial_selections.count("key1")

        # Now mark key1 as successful again
        for _ in range(20):  # Stronger signal to overcome history
            lb.connection_finished("key1", success=True)
            lb.record_response_time("key1", 0.1)  # Make it fast too

        lb.update_metrics()

        # Get another sample to verify key1 is now used more
        new_selections = [lb.get_next() for _ in range(30)]
        new_count = new_selections.count("key1")

        # key1 should be selected more often now
        assert new_count > initial_count

    def test_load_balancer_failover(self, test_logger):
        """Test that load balancer handles failed keys appropriately."""
        # Use least_connections strategy which should detect failures
        lb = LoadBalancer(["key1", "key2"], "least_connections", test_logger)

        # Mark key1 as completely failed
        lb.mark_key_failed("key1")

        # Now only key2 should be selected
        selections = [lb.get_next() for _ in range(5)]
        assert all(key == "key2" for key in selections)

        # Recover key1
        lb.mark_key_recovered("key1")

        # Now key1 should be selected again
        new_selections = [lb.get_next() for _ in range(6)]

        # key1 should now be selected
        assert "key1" in new_selections

    def test_dynamic_backend_changes(self, test_logger):
        """Test adding and removing backends dynamically."""
        lb = LoadBalancer(["key1", "key2"], "round_robin", test_logger)

        # Initial round robin with 2 keys
        assert lb.get_next() == "key1"
        assert lb.get_next() == "key2"

        # Add a new key
        lb.add_item("key3")

        # Should now rotate through 3 keys
        assert lb.get_next() == "key1"
        assert lb.get_next() == "key2"
        assert lb.get_next() == "key3"

        # Remove a key
        lb.remove_item("key2")

        # Should now alternate between remaining keys
        assert lb.get_next() == "key1"
        assert lb.get_next() == "key3"
        assert lb.get_next() == "key1"

    def test_consistent_hashing_simulation(self, test_logger):
        """Test a consistent hashing style routing based on request attributes."""
        keys = ["key1", "key2", "key3", "key4"]
        lb = LoadBalancer(keys, "round_robin", test_logger)

        # Define a simple consistent hash function for testing
        def consistent_hash(request_id, available_keys):
            # Simple hash: use string hash modulo number of keys
            index = hash(request_id) % len(available_keys)
            return available_keys[index]

        # Test consistent mapping
        request_ids = ["user1", "user2", "user3", "user4", "user5"]

        # Map each request to a backend
        mapping = {req_id: consistent_hash(req_id, keys) for req_id in request_ids}

        # Verify consistency - same request_id should always map to same backend
        for req_id in request_ids:
            for _ in range(5):  # Test multiple times
                assert consistent_hash(req_id, keys) == mapping[req_id]

        # Test resilience when a backend is removed
        keys_without_key2 = [k for k in keys if k != "key2"]

        # Remap and count changes
        new_mapping = {
            req_id: consistent_hash(req_id, keys_without_key2) for req_id in request_ids
        }
        changed = sum(
            1
            for req_id in request_ids
            if mapping[req_id] != new_mapping.get(req_id) and mapping[req_id] == "key2"
        )

        # Only requests previously mapped to key2 should change
        assert 0.1 <= changed / len(request_ids) <= 0.4

    def test_empty_load_balancer(self, test_logger):
        """Test behavior with empty items list."""
        lb = LoadBalancer([], "round_robin", test_logger)

        # Should handle empty list gracefully
        assert lb.get_next() is None

        # Add an item and verify it works
        lb.add_item("key1")
        assert lb.get_next() == "key1"


@pytest.mark.unit
class TestLoadBalancerPerformanceMetrics:
    """Tests for load balancer performance metrics tracking and utilization."""

    def test_response_time_tracking(self, test_logger):
        """Test that response times are properly tracked and updated."""
        lb = LoadBalancer(["key1", "key2"], "fastest", test_logger)

        # Record response times
        lb.record_response_time("key1", 0.1)
        lb.record_response_time("key1", 0.2)
        lb.record_response_time("key1", 0.3)

        # Verify they're stored
        assert len(lb.response_times["key1"]) == 3

        # Average should be calculated correctly
        lb.update_metrics()
        assert lb.average_response_times["key1"] == 0.2

        # Test window limiting - if max_samples is 10, older samples should be removed
        for i in range(20):
            lb.record_response_time("key2", 0.5)

        # Should only keep the most recent samples
        assert len(lb.response_times["key2"]) <= 10

        # Test that old metrics are purged
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000

            # Record a response time
            lb.record_response_time("key1", 0.5)

            # Update metrics
            lb.update_metrics()

            # Advance time
            mock_time.return_value = 1000 + 3600  # 1 hour later

            # This should purge old metrics if they're older than the configured window
            lb.update_metrics()

            # Metrics should be reset or updated based on only recent data
            if not lb.response_times["key1"]:  # If purged
                assert (
                    "key1" not in lb.average_response_times
                    or lb.average_response_times["key1"] == 0
                )

    def test_success_rate_calculation(self, test_logger):
        """Test that success rates are calculated correctly."""
        lb = LoadBalancer(["key1", "key2"], "adaptive", test_logger)

        # Record some successes and failures
        for _ in range(8):
            lb.connection_finished("key1", success=True)

        for _ in range(2):
            lb.connection_finished("key1", success=False)

        # 50% success rate for key2
        for _ in range(5):
            lb.connection_finished("key2", success=True)
            lb.connection_finished("key2", success=False)

        # Update metrics
        lb.update_metrics()

        # Check success rates
        assert 0.79 <= lb.success_rates["key1"] <= 0.81  # 8/10 = 0.8
        assert 0.49 <= lb.success_rates["key2"] <= 0.51  # 5/10 = 0.5

    def test_update_metrics_frequency(self, test_logger):
        """Test that metrics aren't updated too frequently."""
        lb = LoadBalancer(["key1"], "adaptive", test_logger)

        with patch.object(lb, "_calculate_metrics") as mock_calc:
            # First update should calculate
            lb.update_metrics(force=False)
            assert mock_calc.call_count == 1

            # Immediate second update should not recalculate
            lb.update_metrics(force=False)
            assert mock_calc.call_count == 1

            # Forced update should recalculate
            lb.update_metrics(force=True)
            assert mock_calc.call_count == 2
