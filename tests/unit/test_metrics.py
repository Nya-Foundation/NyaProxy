"""
Unit tests for ``nya.services.metrics.MetricsCollector``.

Each ``MetricsCollector`` owns a private ``CollectorRegistry``, so tests are
fully isolated without touching the global Prometheus registry.
"""

from nya.services.metrics import PROMETHEUS_CONTENT_TYPE, MetricsCollector


def make_collector() -> MetricsCollector:
    return MetricsCollector()


# --------------------------------------------------------------------------
# record_request / record_response
# --------------------------------------------------------------------------


def test_record_request_counts_request_and_marks_active():
    mc = make_collector()
    mc.record_request("openai", "sk-secret-key-123")

    api = mc.get_api_metrics("openai")
    assert api["total_requests"] == 1
    assert api["active_requests"] == 1


def test_record_response_clears_active_and_records_status():
    mc = make_collector()
    mc.record_request("openai", "sk-secret-key-123")
    mc.record_response("openai", "sk-secret-key-123", 200, 0.5)

    api = mc.get_api_metrics("openai")
    assert api["active_requests"] == 0
    assert api["status_codes"] == {200: 1}
    assert api["success_count"] == 1


def test_success_and_error_counts_and_rate():
    mc = make_collector()
    for status in (200, 200, 200, 500):
        mc.record_request("openai", "key")
        mc.record_response("openai", "key", status, 0.1)

    api = mc.get_api_metrics("openai")
    assert api["success_count"] == 3
    assert api["error_count"] == 1
    assert api["success_rate"] == 75.0


def test_avg_response_time_is_reported_in_milliseconds():
    mc = make_collector()
    mc.record_response("openai", "key", 200, 0.2)
    mc.record_response("openai", "key", 200, 0.4)

    api = mc.get_api_metrics("openai")
    # mean of 200ms and 400ms
    assert abs(api["avg_response_time"] - 300.0) < 1.0


def test_transport_failure_counts_as_error_and_balances_active():
    """Status 0 is the sentinel for an upstream call that never responded."""
    mc = make_collector()
    mc.record_request("openai", "key")
    mc.record_response("openai", "key", 0, 0.1)

    api = mc.get_api_metrics("openai")
    assert api["active_requests"] == 0  # gauge balanced, no leak
    assert api["error_count"] == 1
    assert api["success_count"] == 0


def test_unknown_api_returns_zeroed_summary():
    api = make_collector().get_api_metrics("ghost")
    assert api["total_requests"] == 0
    assert api["success_rate"] == 100.0
    assert api["status_codes"] == {}


# --------------------------------------------------------------------------
# rate-limit / queue counters
# --------------------------------------------------------------------------


def test_rate_limit_and_queue_hits_are_counted():
    mc = make_collector()
    mc.record_rate_limit_hit("openai")
    mc.record_rate_limit_hit("openai")
    mc.record_queue_hit("openai")

    api = mc.get_api_metrics("openai")
    assert api["rate_limit_hits"] == 2
    assert api["queue_hits"] == 1


# --------------------------------------------------------------------------
# key usage
# --------------------------------------------------------------------------


def test_key_usage_is_tracked_per_masked_key():
    mc = make_collector()
    mc.record_request("openai", "sk-aaaaaaaaaaaa")
    mc.record_request("openai", "sk-aaaaaaaaaaaa")
    mc.record_request("openai", "sk-bbbbbbbbbbbb")

    key_usage = mc.get_all_metrics()["apis"]["openai"]["key_usage"]
    # Two distinct masked keys, with 2 and 1 requests.
    assert sorted(key_usage.values()) == [1, 2]


# --------------------------------------------------------------------------
# get_all_metrics
# --------------------------------------------------------------------------


def test_get_all_metrics_aggregates_global_totals():
    mc = make_collector()
    mc.record_request("openai", "key")
    mc.record_response("openai", "key", 200, 0.1)
    mc.record_request("gemini", "key")
    mc.record_response("gemini", "key", 503, 0.1)

    metrics = mc.get_all_metrics()
    assert metrics["global"]["total_requests"] == 2
    assert metrics["global"]["total_errors"] == 1
    assert set(metrics["apis"]) == {"gemini", "openai"}
    assert metrics["global"]["uptime_seconds"] >= 0


def test_get_all_metrics_reports_last_request_time():
    mc = make_collector()
    mc.record_request("openai", "key")
    assert mc.get_all_metrics()["apis"]["openai"]["last_request_time"] is not None


# --------------------------------------------------------------------------
# recent history
# --------------------------------------------------------------------------


def test_recent_history_records_requests_and_responses():
    mc = make_collector()
    mc.record_request("openai", "key")
    mc.record_response("openai", "key", 200, 0.1)

    history = mc.get_recent_history()
    assert [e["type"] for e in history] == ["request", "response"]
    assert history[1]["status_code"] == 200


def test_recent_history_respects_count_limit():
    mc = make_collector()
    for _ in range(10):
        mc.record_request("openai", "key")
    assert len(mc.get_recent_history(count=3)) == 3


def test_recorded_keys_in_history_are_masked():
    mc = make_collector()
    mc.record_request("openai", "sk-supersecretvalue")
    assert "supersecret" not in mc.get_recent_history()[0]["key_id"]


# --------------------------------------------------------------------------
# reset
# --------------------------------------------------------------------------


def test_reset_clears_all_metrics_and_history():
    mc = make_collector()
    mc.record_request("openai", "key")
    mc.record_response("openai", "key", 200, 0.1)
    mc.record_queue_hit("openai")

    mc.reset()

    assert mc.get_all_metrics()["global"]["total_requests"] == 0
    assert mc.get_recent_history() == []
    assert mc.get_api_metrics("openai")["total_requests"] == 0


# --------------------------------------------------------------------------
# Prometheus exposition
# --------------------------------------------------------------------------


def test_render_prometheus_emits_exposition_text():
    mc = make_collector()
    mc.record_request("openai", "key")
    mc.record_response("openai", "key", 200, 0.3)

    body = mc.render_prometheus().decode()
    assert "nyaproxy_requests_total" in body
    assert "nyaproxy_request_duration_seconds_bucket" in body
    assert 'api="openai"' in body


def test_prometheus_content_type_is_exported():
    assert "text/plain" in PROMETHEUS_CONTENT_TYPE
