"""
Advanced tests for metrics analytics with comprehensive coverage of analytics functionality.

This module tests analytical capabilities built on top of the metrics collection system.
"""

import json

import pytest


@pytest.mark.unit
class TestMetricsAnalyticsSuccess:
    """Tests for success rate and error analysis."""

    def test_success_rate_calculation(self, metrics_collector_with_data):
        """Test calculation of success rates with complex data."""
        metrics = metrics_collector_with_data.get_all_metrics()

        # API 1: 80 successes out of 100 requests = 80%
        assert 0.79 <= metrics["apis"]["api1"]["success_rate"] <= 0.81

        # API 2: 50 successes out of 100 requests = 50%
        assert 0.49 <= metrics["apis"]["api2"]["success_rate"] <= 0.51

        # API 3: 90 successes out of 100 requests = 90%
        assert 0.89 <= metrics["apis"]["api3"]["success_rate"] <= 0.91

        # Global success rate: 220 successes out of 300 requests = 73.33%
        assert 0.73 <= metrics["global"]["success_rate"] <= 0.74

    def test_error_distribution(self, metrics_collector_with_data):
        """Test analysis of error distribution by status code."""
        # Get raw history data to analyze errors
        history = metrics_collector_with_data.get_recent_history(count=1000)

        # Count status codes for each API
        status_counts = {"api1": {}, "api2": {}, "api3": {}}

        for entry in history:
            api_name = entry["api_name"]
            status = entry["status_code"]
            if api_name in status_counts:
                if status not in status_counts[api_name]:
                    status_counts[api_name][status] = 0
                status_counts[api_name][status] += 1

        # Check error distribution matches what we set up in the fixture
        assert status_counts["api1"][200] == 80
        assert status_counts["api1"][429] == 15
        assert status_counts["api1"][500] == 5

        assert status_counts["api2"][200] == 50
        assert status_counts["api2"][500] == 50

        assert status_counts["api3"][200] == 90
        assert status_counts["api3"][400] == 10


@pytest.mark.unit
class TestMetricsAnalyticsPerformance:
    """Tests for performance metrics analysis."""

    def test_response_time_analytics(self, metrics_collector_with_data):
        """Test detailed response time analytics."""
        metrics = metrics_collector_with_data.get_all_metrics()

        # Check average response times
        assert 0.09 <= metrics["apis"]["api1"]["avg_response_time"] <= 0.11  # ~0.1s
        assert 0.6 <= metrics["apis"]["api2"]["avg_response_time"] <= 0.7  # ~0.65s
        assert 1.9 <= metrics["apis"]["api3"]["avg_response_time"] <= 2.1  # ~2.0s

        # Check min/max values
        assert metrics["apis"]["api1"]["min_response_time"] <= 0.05
        assert metrics["apis"]["api1"]["max_response_time"] >= 0.4

        assert metrics["apis"]["api3"]["min_response_time"] >= 1.7
        assert metrics["apis"]["api3"]["max_response_time"] >= 1.9

        # Check global average (weighted by API usage)
        assert 0.8 <= metrics["global"]["avg_response_time"] <= 1.0

    def test_percentile_calculations(self, metrics_collector_with_data):
        """Test percentile calculations for response time analysis."""
        # Extract response times from raw history
        history = metrics_collector_with_data.get_recent_history(count=1000)

        api1_times = [
            entry["response_time"] for entry in history if entry["api_name"] == "api1"
        ]
        api3_times = [
            entry["response_time"] for entry in history if entry["api_name"] == "api3"
        ]

        # Calculate 90th percentile manually
        api1_p90 = sorted(api1_times)[int(len(api1_times) * 0.9)]
        api3_p90 = sorted(api3_times)[int(len(api3_times) * 0.9)]

        # For API1, p90 should be around 0.1s (mostly fast responses)
        assert api1_p90 <= 0.5

        # For API3, p90 should be around 2.0s (all responses slow)
        assert api3_p90 >= 1.9


@pytest.mark.unit
class TestMetricsAnalyticsUsage:
    """Tests for usage pattern analysis."""

    def test_key_usage_distribution(self, metrics_collector_with_data):
        """Test key usage distribution analytics."""
        metrics = metrics_collector_with_data.get_all_metrics()

        # Check key usage by API
        api1_keys = metrics["apis"]["api1"]["key_usage"]
        assert api1_keys["key1"] == 2
        assert api1_keys["key2"] == 1
        assert api1_keys["key3"] == 1

        api2_keys = metrics["apis"]["api2"]["key_usage"]
        assert api2_keys["key1"] == 1
        assert api2_keys["key2"] == 3

        api3_keys = metrics["apis"]["api3"]["key_usage"]
        assert api3_keys["key3"] == 4

    def test_time_series_analysis(self, time_series_metrics_collector):
        """Test time series analysis of metrics over a period."""
        # Get raw history data from our time series fixture
        history = time_series_metrics_collector.get_recent_history(count=100)

        # Group by hour
        hour_data = {}
        for entry in history:
            hour = entry["timestamp"] // 3600
            if hour not in hour_data:
                hour_data[hour] = {"total": 0, "errors": 0}
            hour_data[hour]["total"] += 1
            if entry["status_code"] >= 400:
                hour_data[hour]["errors"] += 1

        # Check hourly metrics
        assert hour_data[1]["total"] == 10
        assert hour_data[1]["errors"] == 0

        assert hour_data[2]["total"] == 20
        assert hour_data[2]["errors"] == 5  # 429 responses

        assert hour_data[3]["total"] == 20
        assert hour_data[3]["errors"] == 5  # 500 responses

        assert hour_data[4]["total"] == 45
        assert hour_data[4]["errors"] == 15  # 429 + 500 responses

        # Verify increasing trend
        hourly_totals = [hour_data[i]["total"] for i in sorted(hour_data.keys())]
        for i in range(len(hourly_totals) - 1):
            if i > 0:  # Skip comparison with hour 0 (might be partial)
                assert hourly_totals[i] <= hourly_totals[i + 1]


@pytest.mark.unit
class TestMetricsAnalyticsExport:
    """Tests for metrics export and serialization."""

    def test_export_metrics(self, metrics_collector_with_data):
        """Test exporting metrics to JSON format."""
        # Get metrics as JSON string
        metrics_json = metrics_collector_with_data.export_metrics_json()

        # Should be valid JSON
        parsed_metrics = json.loads(metrics_json)

        # Check structure
        assert "apis" in parsed_metrics
        assert "global" in parsed_metrics
        assert "timestamp" in parsed_metrics

        # Check content
        assert "api1" in parsed_metrics["apis"]
        assert "api2" in parsed_metrics["apis"]
        assert "api3" in parsed_metrics["apis"]

        # Global metrics should include totals
        assert parsed_metrics["global"]["total_requests"] == 300

        # API specific metrics should be accurate
        assert parsed_metrics["apis"]["api1"]["requests"] == 100
        assert parsed_metrics["apis"]["api2"]["requests"] == 100
        assert parsed_metrics["apis"]["api3"]["requests"] == 100


@pytest.mark.unit
class TestMetricsAnalyticsAdaptive:
    """Tests for adaptive behavior based on metrics."""

    def test_adaptive_rate_limiting_analysis(self, adaptive_rate_limit_metrics):
        """Test metrics useful for adaptive rate limiting."""
        metrics = adaptive_rate_limit_metrics.get_all_metrics()

        # Check that rate limit hits increase over time as configured in fixture
        assert metrics["apis"]["api1"]["rate_limit_hits"] == 0 + 10 + 20 + 30 + 40 + 50

        # Record additional metrics for analysis
        history = adaptive_rate_limit_metrics.get_recent_history(count=1000)

        # Group by 10-minute periods
        period_data = {}
        for entry in history:
            period = entry["timestamp"] // 600  # 10-minute periods
            if period not in period_data:
                period_data[period] = {"total": 0, "rate_limited": 0}
            period_data[period]["total"] += 1
            if entry["status_code"] == 429:
                period_data[period]["rate_limited"] += 1

        # Check that rate limited responses increase over time
        limited_counts = [
            period_data[p]["rate_limited"] for p in sorted(period_data.keys())
        ]
        assert all(
            limited_counts[i] <= limited_counts[i + 1]
            for i in range(len(limited_counts) - 1)
        )
