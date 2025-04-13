"""
Tests for the load balancer component.

This module contains tests for the LoadBalancer class, organized by
feature and strategy type.
"""

from unittest.mock import patch

import pytest

from nya_proxy.load_balancer import LoadBalancer


@pytest.mark.unit
class TestLoadBalancerBasics:
    """Basic tests for LoadBalancer functionality."""

    def test_initialization(self, test_logger):
        """Test basic initialization of load balancer."""
        lb = LoadBalancer(["key1", "key2", "key3"], "round_robin", test_logger)
        assert len(lb.items) == 3
        assert lb.strategy == "round_robin"
        assert lb.logger == test_logger

    def test_empty_load_balancer(self, test_logger):
        """Test behavior with empty items list."""
        lb = LoadBalancer([], "round_robin", test_logger)

        # Should handle empty list gracefully
        assert lb.get_next() is None

        # Add an item and verify it works
        lb.add_item("key1")
        assert lb.get_next() == "key1"

    def test_add_item(self, test_logger):
        """Test adding a new item to the load balancer."""
        lb = LoadBalancer(["key1", "key2"], "round_robin", test_logger)

        # Add key3
        lb.add_item("key3")

        # key3 should be in items
        assert "key3" in lb.items

        # Round robin should now include key3
        keys = []
        for _ in range(6):
            keys.append(lb.get_next())

        assert "key3" in keys

        # Adding duplicate item should not create duplicates
        lb.add_item("key1")
        assert lb.items.count("key1") == 1

    def test_remove_item(self, test_logger):
        """Test removing an item from the load balancer."""
        lb = LoadBalancer(["key1", "key2", "key3"], "round_robin", test_logger)

        # Remove key2
        result = lb.remove_item("key2")
        assert result is True

        # key2 should no longer be in items
        assert "key2" not in lb.items

        # Round robin should now only alternate between key1 and key3
        keys = []
        for _ in range(4):
            keys.append(lb.get_next())

        assert keys == ["key1", "key3", "key1", "key3"]

        # Removing a non-existent key should return False
        result = lb.remove_item("nonexistent")
        assert result is False

    def test_connection_tracking(self, test_logger):
        """Test that connections are properly tracked."""
        lb = LoadBalancer(["key1", "key2"], "round_robin", test_logger)

        # Should start with 0 connections
        assert lb.active_connections["key1"] == 0

        # Get a key and verify connection count increases
        key = lb.get_next()
        assert lb.active_connections[key] == 1

        # Finish the connection and verify count decreases
        lb.connection_finished(key)
        assert lb.active_connections[key] == 0


@pytest.mark.unit
class TestLoadBalancerStrategies:
    """Tests for different load balancing strategies."""

    def test_round_robin_strategy(self, load_balancer_round_robin):
        """Test that round robin strategy cycles through keys in order."""
        keys = []
        for _ in range(5):
            keys.append(load_balancer_round_robin.get_next())

        # With 3 keys, we should see a repeating pattern
        assert keys == ["key1", "key2", "key3", "key1", "key2"]

    def test_random_strategy(self, load_balancer_random, mocker):
        """Test that random strategy selects keys randomly."""
        # Mock random.choice to return predictable values
        mocker.patch(
            "random.choice", side_effect=["key2", "key1", "key3", "key2", "key1"]
        )

        keys = []
        for _ in range(5):
            keys.append(load_balancer_random.get_next())

        assert keys == ["key2", "key1", "key3", "key2", "key1"]

    def test_weighted_strategy(self, load_balancer_weighted):
        """Test that weighted strategy distributes according to weights."""
        # Collect a large sample to test distribution
        keys = []
        for _ in range(500):
            keys.append(load_balancer_weighted.get_next())

        counts = {key: keys.count(key) for key in ["key1", "key2", "key3"]}

        # key1 should have roughly 5x the count of key3 and 5/3x of key2
        assert counts["key1"] > counts["key2"] * 1.3
        assert counts["key1"] > counts["key3"] * 1.8

        # key2 should have roughly 1.5x the count of key3
        ratio = counts["key2"] / max(counts["key3"], 1)  # Avoid division by zero
        assert 1.2 < ratio < 1.8

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

    def test_least_used_strategy(self, load_balancer_with_usage_counts):
        """Test least used strategy that prioritizes keys with lower usage counts."""
        lb = load_balancer_with_usage_counts

        # Should select key with lowest usage count
        assert lb.get_next() == "key2"  # key2 has count of 20
        assert lb.usage_counts["key2"] == 21  # Incremented after selection

        # After artificially updating usage count, selection should change
        lb.usage_counts["key2"] = 100
        assert lb.get_next() == "key3"  # Now key3 has lowest count (30)

    def test_fastest_response_strategy(self, load_balancer_with_response_times):
        """Test that fastest response strategy selects keys with lowest response times."""
        lb = load_balancer_with_response_times

        # Should select key with fastest average response time
        assert lb.get_next() == "key2"  # key2 has avg of 0.2s

        # Record new response times that change the fastest key
        for _ in range(10):
            lb.record_response_time("key1", 0.1)  # Make key1 the fastest

        # Update metrics
        lb.update_metrics()

        # Should now select key1 as it's the new fastest
        assert lb.get_next() == "key1"


@pytest.mark.unit
class TestLoadBalancerMetrics:
    """Tests for metrics tracking in the load balancer."""

    def test_success_rate_tracking(self, test_logger):
        """Test success rate tracking and adaptive balancing."""
        # Create a load balancer with adaptive strategy
        lb = LoadBalancer(["key1", "key2"], "adaptive", test_logger)

        # Simulate successful and failed requests
        lb.connection_finished("key1", success=True)
        lb.connection_finished("key1", success=True)
        lb.connection_finished("key2", success=False)
        lb.connection_finished("key2", success=False)

        # Force metrics update
        lb.update_metrics()

        # Check success rates are tracked
        assert lb.success_rates["key1"] > lb.success_rates["key2"]

        # When using adaptive strategy, keys with higher success rates should be preferred
        most_selected = None
        counts = {"key1": 0, "key2": 0}

        for _ in range(10):
            key = lb.get_next()
            counts[key] += 1

        assert counts["key1"] > counts["key2"]

    def test_response_time_tracking(self, test_logger):
        """Test tracking of response times."""
        lb = LoadBalancer(["key1", "key2"], "fastest", test_logger)

        # Add some response times
        lb.record_response_time("key1", 0.5)
        lb.record_response_time("key1", 0.3)
        lb.record_response_time("key2", 0.8)

        # Force metrics update
        lb.update_metrics()

        # Check averages
        assert 0.3 < lb.average_response_times["key1"] < 0.5
        assert lb.average_response_times["key2"] == 0.8

        # key1 should be preferred as fastest
        assert lb.get_next() == "key1"

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


@pytest.mark.unit
class TestLoadBalancerResilience:
    """Tests for load balancer resilience features."""

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
        assert "key1" in new_selections

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
