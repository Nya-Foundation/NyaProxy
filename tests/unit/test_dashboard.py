"""
Smoke tests for the dashboard HTTP API (``nya.dashboard``).

These tests pin the externally visible behaviour of every route so the
675-line ``DashboardAPI`` class can be split into route modules safely.
Dependencies (metrics collector, request queue) are replaced with light
fakes exposing only the methods the routes actually call.
"""

import time

import pytest
from starlette.testclient import TestClient

from nya.dashboard.api import DashboardAPI

# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeMetricsCollector:
    def __init__(self):
        self.reset_called = False

    def get_all_metrics(self):
        return {
            "apis": {
                "openai": {"key_usage": {"key-1": 3, "key-2": 1}},
            }
        }

    def get_api_metrics(self, api_name):
        if api_name == "openai":
            return {"total_requests": 4, "errors": 0}
        return {"total_requests": 0}

    def get_recent_history(self, count=100):
        now = time.time()
        return [
            {
                "type": "response",
                "api_name": "openai",
                "key_id": "key-1",
                "status_code": 200,
                "elapsed_ms": 120,
                "timestamp": now - 10,
            },
            {
                "type": "response",
                "api_name": "gemini",
                "key_id": "key-9",
                "status_code": 500,
                "elapsed_ms": 800,
                "timestamp": now - 20,
            },
        ]

    def reset(self):
        self.reset_called = True


class FakeRequestQueue:
    def get_all_queue_sizes(self):
        return {"openai": 2, "gemini": 0}

    async def clear_queue(self, api_name):
        return 2

    def clear_all_queues(self):
        return 5


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def make_dashboard(*, with_deps=True, enable_control=True):
    dashboard = DashboardAPI(port=0, enable_control=enable_control)
    if with_deps:
        dashboard.set_metrics_collector(FakeMetricsCollector())
        dashboard.set_request_queue(FakeRequestQueue())
    return dashboard


@pytest.fixture
def client():
    return TestClient(make_dashboard().app)


@pytest.fixture
def bare_client():
    """Dashboard with no metrics collector / queue wired in."""
    return TestClient(make_dashboard(with_deps=False).app)


# --------------------------------------------------------------------------
# Static pages
# --------------------------------------------------------------------------


def test_index_renders_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_favicon_is_served(client):
    assert client.get("/favicon.ico").status_code == 200


# --------------------------------------------------------------------------
# Metrics routes
# --------------------------------------------------------------------------


def test_metrics_returns_503_without_collector(bare_client):
    assert bare_client.get("/api/metrics").status_code == 503


def test_key_usage_returns_503_without_collector(bare_client):
    assert bare_client.get("/api/key-usage").status_code == 503


def test_metrics_returns_payload_with_collector(client):
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "apis" in resp.json()


def test_api_metrics_found(client):
    resp = client.get("/api/metrics/openai")
    assert resp.status_code == 200
    assert resp.json()["total_requests"] == 4


def test_api_metrics_not_found_returns_404(client):
    assert client.get("/api/metrics/ghost").status_code == 404


def test_key_usage_returns_per_api_breakdown(client):
    resp = client.get("/api/key-usage")
    assert resp.status_code == 200
    assert "openai" in resp.json()["key_usage"]


# --------------------------------------------------------------------------
# History & analytics routes
# --------------------------------------------------------------------------


def test_history_returns_all_entries(client):
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert len(resp.json()["history"]) == 2


def test_history_filters_by_api_name(client):
    resp = client.get("/api/history", params={"api_name": "openai"})
    history = resp.json()["history"]
    assert len(history) == 1
    assert history[0]["api_name"] == "openai"


def test_history_filters_by_status_code(client):
    resp = client.get("/api/history", params={"status_code": 500})
    assert all(e["status_code"] == 500 for e in resp.json()["history"])


def test_history_filters_by_key_and_response_time(client):
    resp = client.get(
        "/api/history",
        params={"key_id": "key-1", "min_response_time": 100, "max_response_time": 200},
    )
    history = resp.json()["history"]
    assert len(history) == 1
    assert history[0]["key_id"] == "key-1"


def test_api_history_scoped_to_one_api(client):
    resp = client.get("/api/history/gemini")
    assert resp.status_code == 200
    assert {e["api_name"] for e in resp.json()["history"]} == {"gemini"}


# --------------------------------------------------------------------------
# Queue routes
# --------------------------------------------------------------------------


def test_queue_status_returns_sizes(client):
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    assert resp.json()["queue_sizes"]["openai"] == 2


def test_queue_status_503_without_queue(bare_client):
    assert bare_client.get("/api/queue").status_code == 503


def test_scoped_history_and_control_routes_report_missing_dependencies(bare_client):
    assert bare_client.get("/api/history/openai").status_code == 503
    assert bare_client.post("/api/queue/clear/openai").status_code == 503
    assert bare_client.post("/api/queue/clear").status_code == 503
    assert bare_client.post("/api/metrics/reset").status_code == 503


# --------------------------------------------------------------------------
# Control routes
# --------------------------------------------------------------------------


def test_clear_queue_for_one_api(client):
    resp = client.post("/api/queue/clear/openai")
    assert resp.status_code == 200
    assert resp.json()["cleared_count"] == 2


def test_clear_all_queues(client):
    resp = client.post("/api/queue/clear")
    assert resp.status_code == 200
    assert resp.json()["cleared_count"] == 5


def test_reset_metrics(client):
    resp = client.post("/api/metrics/reset")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_control_routes_absent_when_disabled():
    """With enable_control=False the control routes must not be registered.

    ``/api/queue/clear`` has no GET twin, so an unregistered POST yields a
    clean 404 (unlike ``/api/metrics/reset``, which collides with the GET
    ``/api/metrics/{api_name}`` route and would return 405).
    """
    client = TestClient(make_dashboard(enable_control=False).app)
    assert client.post("/api/queue/clear").status_code == 404


def test_queue_status_includes_optional_queue_metrics():
    class QueueWithMetrics(FakeRequestQueue):
        def get_metrics(self):
            return {"oldest_wait_seconds": 1.5}

    dashboard = DashboardAPI(port=0)
    dashboard.set_request_queue(QueueWithMetrics())
    resp = TestClient(dashboard.app).get("/api/queue")

    assert resp.status_code == 200
    assert resp.json()["metrics"] == {"oldest_wait_seconds": 1.5}


def test_dashboard_html_directory_fallback(monkeypatch):
    monkeypatch.setattr(
        "nya.dashboard.api.importlib.resources.files",
        lambda package: (_ for _ in ()).throw(AttributeError("old python")),
    )
    dashboard = object.__new__(DashboardAPI)

    assert dashboard.get_html_directory().name == "html"


def test_dashboard_index_template_failure_returns_500(monkeypatch):
    def broken_open_text(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(
        "nya.dashboard.routes.pages.importlib.resources.open_text", broken_open_text
    )

    assert TestClient(DashboardAPI(port=0).app).get("/").status_code == 500


@pytest.mark.asyncio
async def test_dashboard_start_background_and_run_delegate_to_uvicorn(monkeypatch):
    calls = {}

    class FakeServer:
        def __init__(self, config):
            calls["config"] = config

        async def serve(self):
            calls["served"] = True

    monkeypatch.setattr("nya.dashboard.api.uvicorn.Server", FakeServer)
    dashboard = DashboardAPI(port=1234)

    await dashboard.start_background(host="127.0.0.1")
    assert calls["config"].host == "127.0.0.1"
    assert calls["config"].port == 1234
    assert calls["served"] is True

    monkeypatch.setattr(
        "nya.dashboard.api.uvicorn.run",
        lambda app, host, port, log_config: calls.update(
            {"run_host": host, "run_port": port, "log_config": log_config}
        ),
    )
    dashboard.run(host="127.0.0.2")
    assert calls["run_host"] == "127.0.0.2"
    assert calls["run_port"] == 1234
    assert calls["log_config"] is None


def test_dashboard_route_failures_return_500():
    class BrokenMetrics(FakeMetricsCollector):
        def get_all_metrics(self):
            raise RuntimeError("metrics failed")

        def get_api_metrics(self, api_name):
            raise RuntimeError("api metrics failed")

        def get_recent_history(self, count=100):
            raise RuntimeError("history failed")

        def reset(self):
            raise RuntimeError("reset failed")

    class BrokenQueue(FakeRequestQueue):
        def get_all_queue_sizes(self):
            raise RuntimeError("queue failed")

        async def clear_queue(self, api_name):
            raise RuntimeError("clear one failed")

        def clear_all_queues(self):
            raise RuntimeError("clear all failed")

    dashboard = DashboardAPI(port=0, enable_control=True)
    dashboard.set_metrics_collector(BrokenMetrics())
    dashboard.set_request_queue(BrokenQueue())
    client = TestClient(dashboard.app)

    assert client.get("/api/metrics").status_code == 500
    assert client.get("/api/metrics/openai").status_code == 500
    assert client.get("/api/key-usage").status_code == 500
    assert client.get("/api/history").status_code == 500
    assert client.get("/api/history/openai").status_code == 500
    assert client.get("/api/queue").status_code == 500
    assert client.post("/api/queue/clear/openai").status_code == 500
    assert client.post("/api/queue/clear").status_code == 500
    assert client.post("/api/metrics/reset").status_code == 500
