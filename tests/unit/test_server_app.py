import argparse
import contextlib
import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

from nya.server import app as server_app
from nya.server.app import NyaProxyApp


class AppConfig:
    def __init__(self):
        self.server = SimpleNamespace(app=FastAPI())
        self.dashboard_enabled = True
        self.apis = {
            "mock": {
                "name": "Mock API",
                "endpoint": "https://upstream.test",
                "aliases": ["alias"],
            }
        }

    def get_cors_allow_origins(self):
        return ["*"]

    def get_cors_allow_methods(self):
        return ["GET", "POST"]

    def get_cors_allow_headers(self):
        return ["authorization"]

    def get_cors_allow_credentials(self):
        return False

    def get_api_key(self):
        return None

    def get_apis(self):
        return self.apis

    def get_logging_config(self):
        return {"level": "INFO", "log_file": os.devnull}

    def get_host(self):
        return "127.0.0.1"

    def get_port(self):
        return 9876

    def get_dashboard_enabled(self):
        return self.dashboard_enabled


class FakeCore:
    def __init__(self, config, metrics_collector):
        self.config = config
        self.metrics_collector = metrics_collector
        self.request_queue = object()
        self.request_executor = SimpleNamespace(close=self.close)
        self.closed = False

    async def close(self):
        self.closed = True

    async def handle_request(self, request):
        return JSONResponse({"path": str(request._url.path), "ip": request.ip})


class FakeMetricsCollector:
    def __init__(self):
        self.rendered = "nya_requests_total 1\n"

    def render_prometheus(self):
        return self.rendered


class FakeDashboard:
    def __init__(self, enable_control):
        self.enable_control = enable_control
        self.app = FastAPI()
        self.metrics_collector = None
        self.request_queue = None
        self.config_manager = None

    def set_metrics_collector(self, metrics):
        self.metrics_collector = metrics

    def set_request_queue(self, queue):
        self.request_queue = queue

    def set_config_manager(self, config):
        self.config_manager = config


_DEFAULT_CONFIG = object()


def make_app_instance(config=_DEFAULT_CONFIG):
    app = object.__new__(NyaProxyApp)
    app.config = AppConfig() if config is _DEFAULT_CONFIG else config
    app.core = None
    app.auth = SimpleNamespace(get_api_key=lambda: None, is_auth_disabled=lambda: True)
    app.dashboard = None
    app.metrics_collector = None
    return app


def test_create_main_app_registers_public_routes_and_metrics():
    instance = make_app_instance()
    instance.metrics_collector = FakeMetricsCollector()

    client = TestClient(instance._create_main_app())

    assert client.get("/").json() == {"message": "Welcome to NyaProxy!"}
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/info").json()["apis"]["mock"]["aliases"] == ["alias"]
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.text == "nya_requests_total 1\n"


def test_constructor_and_auth_logging_metric_initializers(monkeypatch):
    class FakeConfigManager(AppConfig):
        def __init__(self, **kwargs):
            super().__init__()

    monkeypatch.setattr(server_app, "ConfigManager", FakeConfigManager)
    created = NyaProxyApp(config_path="config.yaml", schema_path="schema.json")

    assert isinstance(created.config, FakeConfigManager)
    assert created.core is None
    assert created.dashboard is None
    created.init_logging()
    created.init_metrics_collector()
    assert created.metrics_collector is not None


def test_metrics_route_reports_unavailable_without_collector():
    instance = make_app_instance()
    client = TestClient(instance._create_main_app())

    assert client.get("/metrics").status_code == 503


@pytest.mark.asyncio
async def test_lifespan_initializes_and_shuts_down_services():
    instance = make_app_instance()
    calls = []

    async def init_services():
        calls.append("init")

    async def shutdown():
        calls.append("shutdown")

    instance.init_nya_services = init_services
    instance.shutdown = shutdown

    async with instance.lifespan(FastAPI()):
        calls.append("inside")

    assert calls == ["init", "inside", "shutdown"]


@pytest.mark.asyncio
async def test_generic_proxy_request_handles_unready_and_ready_core():
    instance = make_app_instance()
    app = FastAPI()

    @app.get("/api/{path:path}")
    async def route(request: Request):
        return await instance.generic_proxy_request(request)

    assert TestClient(app).get("/api/mock").status_code == 503

    instance.core = FakeCore(instance.config, FakeMetricsCollector())
    response = TestClient(app).get("/api/mock", headers={"x-real-ip": "203.0.113.5"})
    assert response.status_code == 200
    assert response.json()["path"] == "/api/mock"


def test_service_initializers_mount_config_ui_dashboard_and_proxy_routes(monkeypatch):
    config = AppConfig()
    instance = make_app_instance(config)
    instance.app = FastAPI()
    instance.metrics_collector = FakeMetricsCollector()
    instance.auth = SimpleNamespace(get_api_key=lambda: None)
    instance.core = FakeCore(config, instance.metrics_collector)

    monkeypatch.setattr(server_app, "DashboardAPI", FakeDashboard)

    assert instance.init_config_ui() is True
    assert instance.init_dashboard() is True
    instance.setup_proxy_routes()

    client = TestClient(instance.app)
    assert client.get("/api/mock").status_code == 200
    assert client.post("/api/mock").status_code == 200
    assert client.put("/api/mock").status_code == 200
    assert client.delete("/api/mock").status_code == 200
    assert client.patch("/api/mock").status_code == 200
    assert client.head("/api/mock").status_code == 200


def test_config_ui_and_dashboard_skip_when_dependencies_are_missing(monkeypatch):
    instance = make_app_instance(None)
    assert instance.init_config_ui() is False
    assert instance.init_dashboard() is False

    config = AppConfig()
    config.server = object()
    instance = make_app_instance(config)
    instance.app = FastAPI()
    assert instance.init_config_ui() is False

    config = AppConfig()
    config.dashboard_enabled = False
    instance = make_app_instance(config)
    assert instance.init_dashboard() is False

    monkeypatch.setenv("REMOTE_CONFIG_URL", "https://remote.test")
    instance = make_app_instance(AppConfig())
    instance.app = FastAPI()
    assert instance.init_config_ui() is False


def test_dashboard_initialization_wraps_failures(monkeypatch):
    def bad_dashboard(*args, **kwargs):
        raise RuntimeError("boom")

    instance = make_app_instance(AppConfig())
    instance.app = FastAPI()
    instance.metrics_collector = FakeMetricsCollector()
    instance.core = SimpleNamespace(request_queue=object())
    monkeypatch.setattr(server_app, "DashboardAPI", bad_dashboard)

    with pytest.raises(RuntimeError, match="Failed to initialize dashboard"):
        instance.init_dashboard()


@pytest.mark.asyncio
async def test_init_services_calls_each_initializer_in_order(monkeypatch):
    instance = make_app_instance()
    calls = []

    instance.init_logging = lambda: calls.append("logging")
    instance.init_metrics_collector = lambda: calls.append("metrics")
    instance.init_core = lambda: calls.append("core")
    instance.init_config_ui = lambda: calls.append("config")
    instance.init_dashboard = lambda: calls.append("dashboard")
    instance.setup_proxy_routes = lambda: calls.append("routes")

    await instance.init_nya_services()

    assert calls == ["logging", "metrics", "core", "config", "dashboard", "routes"]


def test_warn_if_unauthenticated_fires_only_on_public_bind(monkeypatch):
    from loguru import logger

    messages = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        instance = make_app_instance()

        monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
        instance._warn_if_unauthenticated()
        assert any("WITHOUT authentication" in m for m in messages)

        messages.clear()
        monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
        instance._warn_if_unauthenticated()
        assert not messages

        # Auth enabled: never warn, even on a public bind
        messages.clear()
        instance.auth = SimpleNamespace(is_auth_disabled=lambda: False)
        monkeypatch.setenv("SERVER_HOST", "0.0.0.0")
        instance._warn_if_unauthenticated()
        assert not messages
    finally:
        logger.remove(sink_id)


@pytest.mark.asyncio
async def test_init_services_logs_and_reraises_initializer_failure():
    instance = make_app_instance()
    instance.init_logging = lambda: (_ for _ in ()).throw(
        RuntimeError("startup failed")
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        await instance.init_nya_services()


@pytest.mark.asyncio
async def test_shutdown_closes_request_executor_and_logs_close_errors():
    instance = make_app_instance()
    core = FakeCore(instance.config, FakeMetricsCollector())
    instance.core = core

    await instance.shutdown()
    assert core.closed is True

    async def bad_close():
        raise RuntimeError("boom")

    instance.core = SimpleNamespace(request_executor=SimpleNamespace(close=bad_close))
    await instance.shutdown()


def test_init_config_reads_environment_and_auth_guard(monkeypatch):
    captured = {}

    class FakeConfigManager(AppConfig):
        def __init__(self, **kwargs):
            super().__init__()
            captured.update(kwargs)

    monkeypatch.setenv("CONFIG_PATH", "config.yaml")
    monkeypatch.setenv("SCHEMA_PATH", "schema.json")
    monkeypatch.setenv("REMOTE_CONFIG_URL", "https://remote.test")
    monkeypatch.setenv("REMOTE_CONFIG_API_KEY", "secret")
    monkeypatch.setenv("REMOTE_CONFIG_APP_NAME", "nya")
    monkeypatch.setattr(server_app, "ConfigManager", FakeConfigManager)

    instance = make_app_instance()
    instance._init_config()

    assert captured["config_path"] == "config.yaml"
    assert captured["schema_path"] == "schema.json"
    assert captured["remote_url"] == "https://remote.test"
    assert instance.config is not None


def test_init_config_wraps_config_manager_failures(monkeypatch):
    class BrokenConfigManager:
        def __init__(self, **kwargs):
            raise RuntimeError("bad config")

    monkeypatch.setattr(server_app, "ConfigManager", BrokenConfigManager)
    instance = make_app_instance()

    with pytest.raises(RuntimeError, match="bad config"):
        instance._init_config(config_path="bad.yaml")


def test_init_core_requires_config_and_wires_core(monkeypatch):
    instance = make_app_instance(None)
    with pytest.raises(RuntimeError):
        instance.init_core()

    instance = make_app_instance(AppConfig())
    instance.metrics_collector = FakeMetricsCollector()
    monkeypatch.setattr(server_app, "NyaProxyCore", FakeCore)

    instance.init_core()

    assert isinstance(instance.core, FakeCore)


def test_parse_args_and_trigger_reload(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        ["nyaproxy", "--config", "c.yaml", "--port", "9000", "--host", "127.0.0.1"],
    )
    args = server_app.parse_args()
    assert args.config == "c.yaml"
    assert args.port == 9000
    assert args.host == "127.0.0.1"

    watch_file = tmp_path / "reload.watch"
    monkeypatch.setattr(server_app, "WATCH_FILE", str(watch_file))
    monkeypatch.delenv("DISABLE_HOT_RELOAD", raising=False)

    server_app.trigger_reload()
    server_app.trigger_reload()

    assert watch_file.read_text() == "reload\nreload\n"

    # With hot-reload disabled the watch file must stay untouched
    monkeypatch.setenv("DISABLE_HOT_RELOAD", "1")
    server_app.trigger_reload()
    assert watch_file.read_text() == "reload\nreload\n"


def test_parse_args_supports_remote_options(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "nyaproxy",
            "--remote-url",
            "https://remote.test",
            "--remote-api-key",
            "secret",
            "--remote-app-name",
            "nya",
        ],
    )

    args = server_app.parse_args()

    assert args.remote_url == "https://remote.test"
    assert args.remote_api_key == "secret"
    assert args.remote_app_name == "nya"


def test_create_app_instantiates_nya_proxy_app(monkeypatch):
    fake_fastapi = FastAPI()

    class FakeNyaProxyApp:
        def __init__(self):
            self.app = fake_fastapi

    monkeypatch.setattr(server_app, "NyaProxyApp", FakeNyaProxyApp)

    assert server_app.create_app() is fake_fastapi


def test_main_sets_environment_and_runs_uvicorn(monkeypatch, tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text("{}")
    captured = {}

    @contextlib.contextmanager
    def fake_resource_path(package, name):
        yield schema

    monkeypatch.setattr(
        server_app,
        "parse_args",
        lambda: argparse.Namespace(
            config="config.yaml",
            host="127.0.0.2",
            port=9911,
            remote_url="https://remote.test",
            remote_api_key="secret",
            remote_app_name="nya",
            no_reload=False,
        ),
    )
    monkeypatch.setattr(
        server_app.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr("importlib.resources.path", fake_resource_path)

    server_app.main()

    assert os.environ["CONFIG_PATH"] == "config.yaml"
    assert os.environ["SCHEMA_PATH"] == str(schema)
    assert os.environ["SERVER_HOST"] == "127.0.0.2"
    assert os.environ["SERVER_PORT"] == "9911"
    assert os.environ["REMOTE_CONFIG_URL"] == "https://remote.test"
    assert captured["host"] == "127.0.0.2"
    assert captured["port"] == 9911


def test_main_copies_default_config_when_no_config_is_available(monkeypatch, tmp_path):
    schema = tmp_path / "schema.json"
    default_config = tmp_path / "package-config.yaml"
    workdir = tmp_path / "work"
    workdir.mkdir()
    schema.write_text("{}")
    default_config.write_text("server: {}\n")
    captured = {}

    @contextlib.contextmanager
    def fake_resource_path(package, name):
        yield schema if name == server_app.DEFAULT_SCHEMA_NAME else default_config

    monkeypatch.chdir(workdir)
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.delenv("REMOTE_CONFIG_URL", raising=False)
    monkeypatch.delenv("SERVER_HOST", raising=False)
    monkeypatch.delenv("SERVER_PORT", raising=False)
    monkeypatch.setattr(
        server_app,
        "parse_args",
        lambda: argparse.Namespace(
            config=None,
            host=None,
            port=None,
            remote_url=None,
            remote_api_key=None,
            remote_app_name=None,
            no_reload=False,
        ),
    )
    monkeypatch.setattr(
        server_app.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr("importlib.resources.path", fake_resource_path)

    server_app.main()

    copied = workdir / server_app.DEFAULT_CONFIG_NAME
    assert copied.read_text() == "server: {}\n"
    assert os.environ["CONFIG_PATH"] == str(copied)
    assert captured["host"] == server_app.DEFAULT_HOST
