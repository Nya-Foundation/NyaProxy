"""
Tests for the metrics collector component.

This module tests the MetricsCollector class, which is responsible for
tracking various metrics about API usage and performance.
"""

import json
from unittest.mock import patch

import pytest

from nya_proxy.metrics import MetricsCollector


@pytest.mark.unit
class TestMetricsCollectorInit:
    """Tests for MetricsCollector initialization."""

    def test_initialization(self, test_logger):
        """Test the initialization of the metrics collector."""
        collector = MetricsCollector(test_logger)

        # Check that metrics are initialized properly
        metrics = collector.get_all_metrics()
        assert "global" in metrics
        assert "apis" in metrics
        assert "timestamp" in metrics

        # Check global metrics are initialized to 0
        global_metrics = metrics["global"]
        assert global_metrics["total_requests"] == 0
        assert global_metrics["total_errors"] == 0
        assert global_metrics["total_rate_limit_hits"] == 0
        assert "uptime_seconds" in global_metrics


@pytest.mark.unit
class TestMetricsCollectorBasics:
    """Basic tests for the MetricsCollector class."""

    def test_record_response(self, metrics_collector):
        """Test recording a response."""
        # Record a successful response
        metrics_collector.record_response("test_api", 200, 0.5)

        # Record an error
        metrics_collector.record_response("test_api", 500, 0.8)

        # Get metrics and check values
        metrics = metrics_collector.get_all_metrics()
        api_metrics = metrics["apis"]["test_api"]

        # Check that both responses were recorded
        assert api_metrics["requests"] == 2
        assert api_metrics["errors"] == 1
        assert api_metrics["success_rate"] == 0.5  # 1/2 = 50%

        # Check response time metrics
        assert 0.5 <= api_metrics["avg_response_time"] <= 0.8
        assert api_metrics["min_response_time"] == 0.5
        assert api_metrics["max_response_time"] == 0.8

        # Check global metrics
        global_metrics = metrics["global"]
        assert global_metrics["total_requests"] == 2
        assert global_metrics["total_errors"] == 1

    def test_record_rate_limit_hit(self, metrics_collector):
        """Test recording a rate limit hit."""
        # Record rate limit hits
        metrics_collector.record_rate_limit_hit("test_api")
        metrics_collector.record_rate_limit_hit("test_api")

        # Get metrics and check values
        metrics = metrics_collector.get_all_metrics()
        api_metrics = metrics["apis"]["test_api"]

        # Check that rate limit hits were recorded
        assert api_metrics["rate_limit_hits"] == 2

        # Check global metrics
        global_metrics = metrics["global"]
        assert global_metrics["total_rate_limit_hits"] == 2

    def test_record_queue_hit(self, metrics_collector):
        """Test recording a queue hit."""
        # Record queue hits
        metrics_collector.record_queue_hit("test_api")
        metrics_collector.record_queue_hit("test_api")
        metrics_collector.record_queue_hit("other_api")

        # Get metrics and check values
        metrics = metrics_collector.get_all_metrics()
        api_metrics = metrics["apis"]["test_api"]
        other_api_metrics = metrics["apis"]["other_api"]

        # Check that queue hits were recorded
        assert api_metrics["queue_hits"] == 2
        assert other_api_metrics["queue_hits"] == 1

        # Check global metrics
        global_metrics = metrics["global"]
        assert global_metrics["total_queue_hits"] == 3

    def test_record_key_usage(self, metrics_collector):
        """Test recording key usage."""
        # Record key usage
        metrics_collector.record_key_usage("test_api", "key1")
        metrics_collector.record_key_usage("test_api", "key2")
        metrics_collector.record_key_usage("test_api", "key1")  # Used twice

        # Get metrics and check values
        metrics = metrics_collector.get_all_metrics()
        api_metrics = metrics["apis"]["test_api"]

        # Check key usage
        assert api_metrics["key_usage"]["key1"] == 2
        assert api_metrics["key_usage"]["key2"] == 1


@pytest.mark.unit
class TestMetricsCollectorQueries:
    """Tests for metrics query functionality."""

    def test_get_api_metrics(self, metrics_collector):
        """Test getting metrics for a specific API."""
        # Record data for two APIs
        metrics_collector.record_response("api1", 200, 0.5)
        metrics_collector.record_response("api2", 200, 0.3)

        # Get metrics for api1
        api1_metrics = metrics_collector.get_api_metrics("api1")

        # Check that only api1 metrics are returned
        assert api1_metrics["requests"] == 1
        assert api1_metrics["avg_response_time"] == 0.5

        # Check that api2 metrics are not included
        assert "api2" not in api1_metrics

    def test_get_recent_history(self, metrics_collector):
        """Test getting recent request history."""
        # Record some responses with different timestamps
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000
            metrics_collector.record_response("api1", 200, 0.5)

            mock_time.return_value = 1001
            metrics_collector.record_response("api2", 500, 0.8)

            mock_time.return_value = 1002
            metrics_collector.record_response("api1", 429, 0.2)

        # Get recent history
        history = metrics_collector.get_recent_history(count=10)

        # Should have 3 items in reverse chronological order
        assert len(history) == 3
        assert history[0]["timestamp"] == 1002
        assert history[0]["api_name"] == "api1"
        assert history[0]["status_code"] == 429

        assert history[1]["timestamp"] == 1001
        assert history[1]["api_name"] == "api2"
        assert history[1]["status_code"] == 500

        assert history[2]["timestamp"] == 1000
        assert history[2]["api_name"] == "api1"
        assert history[2]["status_code"] == 200

    def test_limiting_history_size(self, metrics_collector):
        """Test that history size is limited correctly."""
        # Add more items than the default history size
        for i in range(1000):
            metrics_collector.record_response(f"api{i % 3}", 200, 0.1)

        # Get recent history with a limit
        history = metrics_collector.get_recent_history(count=50)

        # Should only return the requested number of items
        assert len(history) == 50


@pytest.mark.unit
class TestMetricsCollectorAdvanced:
    """Advanced tests for the MetricsCollector class."""

    def test_reset(self, metrics_collector):
        """Test resetting all metrics."""
        # Record some data
        metrics_collector.record_response("test_api", 200, 0.5)
        metrics_collector.record_rate_limit_hit("test_api")

        # Reset metrics
        metrics_collector.reset()

        # Check that metrics were reset
        metrics = metrics_collector.get_all_metrics()
        assert "test_api" not in metrics["apis"]
        assert metrics["global"]["total_requests"] == 0
        assert metrics["global"]["total_errors"] == 0
        assert metrics["global"]["total_rate_limit_hits"] == 0

    def test_uptime_calculation(self, test_logger):
        """Test that uptime is calculated correctly."""
        # Create collector with a known start time
        with patch("time.time") as mock_time:
            mock_time.return_value = 1000
            collector = MetricsCollector(test_logger)

            # Check initial uptime
            metrics = collector.get_all_metrics()
            assert metrics["global"]["uptime_seconds"] == 0

            # Advance time and check uptime
            mock_time.return_value = 1060  # 60 seconds later
            metrics = collector.get_all_metrics()
            assert metrics["global"]["uptime_seconds"] == 60

    def test_success_rate_calculation(self, metrics_collector):
        """Test that success rate is calculated correctly."""
        # Record some responses
        metrics_collector.record_response("test_api", 200, 0.5)  # Success
        metrics_collector.record_response("test_api", 201, 0.5)  # Success
        metrics_collector.record_response("test_api", 400, 0.5)  # Error
        metrics_collector.record_response("test_api", 500, 0.5)  # Error
        metrics_collector.record_response("test_api", 200, 0.5)  # Success

        # Get metrics
        metrics = metrics_collector.get_all_metrics()
        api_metrics = metrics["apis"]["test_api"]

        # Check success rate: 3 successes out of 5 = 60%
        assert api_metrics["success_rate"] == 0.6

        # Check global success rate
        global_metrics = metrics["global"]
        assert global_metrics["success_rate"] == 0.6

    def test_serialization(self, metrics_collector):
        """Test that metrics can be serialized to JSON."""
        # Record some data
        metrics_collector.record_response("test_api", 200, 0.5)
        metrics_collector.record_rate_limit_hit("test_api")

        # Get metrics
        metrics = metrics_collector.get_all_metrics()

        # Should be serializable to JSON
        json_str = json.dumps(metrics)
        parsed = json.loads(json_str)

        # Check that data survived serialization
        assert parsed["apis"]["test_api"]["requests"] == 1
        assert parsed["apis"]["test_api"]["rate_limit_hits"] == 1
        assert parsed["global"]["total_requests"] == 1
        assert parsed["global"]["total_rate_limit_hits"] == 1
