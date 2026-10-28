"""
Unit tests for the authentication layer (``nya.server.auth``).

Covers credential verification (``AuthManager``) and the request gate
(``AuthMiddleware``). Auth is security-critical, so every branch of the
configured-key handling is exercised explicitly.
"""

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from nya.server.auth import AuthManager, AuthMiddleware


class FakeConfig:
    """Minimal stand-in for ConfigManager: the two key getters auth reads."""

    def __init__(self, api_key, dashboard_key=None):
        self._api_key = api_key
        self._dashboard_key = dashboard_key

    def get_api_key(self):
        return self._api_key

    def get_dashboard_api_key(self):
        return self._dashboard_key


def make_manager(api_key, dashboard_key=None):
    return AuthManager(config=FakeConfig(api_key, dashboard_key))


# --------------------------------------------------------------------------
# AuthManager.verify_api_key
# --------------------------------------------------------------------------


def test_verify_api_key_rejects_non_string():
    with pytest.raises(ValueError):
        make_manager("secret").verify_api_key(12345)


@pytest.mark.parametrize("configured", [None, "", "   ", "none", "NULL", "Null"])
def test_verify_api_key_open_when_no_key_configured(configured):
    """None, blank, or the sentinel words mean 'auth disabled'."""
    assert make_manager(configured).verify_api_key("anything") is True


def test_verify_api_key_string_match_and_mismatch():
    manager = make_manager("super-secret")
    assert manager.verify_api_key("super-secret") is True
    assert manager.verify_api_key("wrong") is False


def test_verify_api_key_strips_whitespace_on_both_sides():
    manager = make_manager("  padded-key  ")
    assert manager.verify_api_key("  padded-key  ") is True


def test_verify_api_key_empty_list_is_open():
    assert make_manager([]).verify_api_key("anything") is True


def test_verify_api_key_list_matches_any_key():
    manager = make_manager(["key-a", "key-b", "key-c"])
    assert manager.verify_api_key("key-b") is True
    assert manager.verify_api_key("key-c") is True
    assert manager.verify_api_key("key-x") is False


def test_verify_api_key_master_only_accepts_first_key():
    """verify_master restricts the match to the first (master) key."""
    manager = make_manager(["master-key", "secondary-key"])
    assert manager.verify_api_key("master-key", verify_master=True) is True
    assert manager.verify_api_key("secondary-key", verify_master=True) is False


def test_verify_api_key_unexpected_config_type_denies():
    assert make_manager(42).verify_api_key("anything") is False


def test_verify_api_key_non_ascii_does_not_raise():
    """Constant-time compare rejects non-ASCII input instead of crashing."""
    assert make_manager("ascii-key").verify_api_key("nya-ñ") is False


# --------------------------------------------------------------------------
# AuthManager.verify_session_cookie / verify_api_key_header
# --------------------------------------------------------------------------


class FakeRequest:
    """Minimal request exposing only cookies and headers."""

    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


def test_verify_session_cookie_valid_and_invalid():
    manager = make_manager(["master-key", "other"])
    valid = FakeRequest(cookies={"nyaproxy_api_key": "master-key"})
    invalid = FakeRequest(cookies={"nyaproxy_api_key": "other"})
    assert manager.verify_session_cookie(valid) is True
    # 'other' is a valid key but not the master key -> cookie auth fails
    assert manager.verify_session_cookie(invalid) is False


def test_verify_session_cookie_missing_cookie():
    manager = make_manager("master-key")
    assert manager.verify_session_cookie(FakeRequest()) is False


def test_verify_api_key_header_strips_bearer_prefix():
    manager = make_manager("token-123")
    bearer = FakeRequest(headers={"Authorization": "Bearer token-123"})
    raw = FakeRequest(headers={"Authorization": "token-123"})
    assert manager.verify_api_key_header(bearer) is True
    assert manager.verify_api_key_header(raw) is True


def test_verify_api_key_header_missing_is_rejected():
    assert make_manager("token-123").verify_api_key_header(FakeRequest()) is False


# --------------------------------------------------------------------------
# AuthMiddleware.dispatch
# --------------------------------------------------------------------------


def build_client(api_key, dashboard_key=None):
    """Build a TestClient for a tiny app guarded by AuthMiddleware."""

    async def ok(request):
        return PlainTextResponse("ok")

    routes = [
        Route("/", ok),
        Route("/api/v1/thing", ok),
        Route("/dashboard", ok),
        Route("/dashboard/api/metrics", ok),
        Route("/config", ok),
        Route("/config/api/apps", ok),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(AuthMiddleware, auth=make_manager(api_key, dashboard_key))
    return TestClient(app)


def test_middleware_allows_cors_preflight_requests():
    client = build_client("secret")
    response = client.options(
        "/api/v1/thing",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code != 403


def test_middleware_authenticates_non_preflight_options_requests():
    client = build_client("secret")
    assert client.options("/api/v1/thing").status_code == 403


def test_middleware_allows_excluded_paths_without_auth():
    client = build_client("secret")
    assert client.get("/").status_code == 200


def test_middleware_open_when_no_key_configured():
    client = build_client(None)
    assert client.get("/api/v1/thing").text == "ok"


def test_middleware_accepts_valid_authorization_header():
    client = build_client("secret")
    resp = client.get("/api/v1/thing", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_middleware_accepts_valid_session_cookie():
    client = build_client("secret")
    client.cookies.set("nyaproxy_api_key", "secret")
    assert client.get("/dashboard").status_code == 200


def test_middleware_rejects_api_path_with_json_403():
    client = build_client("secret")
    resp = client.get("/api/v1/thing")
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_middleware_redirects_dashboard_to_login_page():
    client = build_client("secret")
    resp = client.get("/dashboard")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("text/html")


def test_middleware_redirects_config_to_login_page():
    client = build_client("secret")
    resp = client.get("/config")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("text/html")


# --------------------------------------------------------------------------
# Blank / malformed key entries
#
# An unset "${MASTER_KEY}" or a stray '-' in YAML yields a blank entry. Such an
# entry must never authenticate anything, and must never silently promote a
# proxy key to master.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_master_entry_never_authenticates(blank):
    """Regression: an empty bearer token used to match a blank master key."""
    manager = make_manager([blank, "app-key"])

    # Auth is still on: other keys are usable, so this is not "no auth".
    assert manager.is_auth_disabled() is False
    assert manager.master_key() is None

    # The empty credential that used to pass as master is now rejected.
    assert manager.verify_api_key("", verify_master=True) is False
    assert manager.verify_api_key("   ", verify_master=True) is False
    # ...and a proxy key is not quietly promoted to master either.
    assert manager.verify_api_key("app-key", verify_master=True) is False
    # ...while it still works for proxy traffic.
    assert manager.verify_api_key("app-key") is True


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_entries_are_not_usable_keys(blank):
    manager = make_manager(["master", blank, "app-key"])
    assert manager.usable_keys() == ["master", "app-key"]
    assert manager.master_key() == "master"
    assert manager.verify_api_key("") is False
    assert manager.verify_api_key(str(blank or "").strip()) is False


def test_none_entry_does_not_crash():
    """Regression: None entries raised AttributeError on every auth check."""
    manager = make_manager([None, "app-key"])
    assert manager.verify_api_key("app-key") is True
    assert manager.verify_api_key("anything", verify_master=True) is False


@pytest.mark.parametrize("configured", [["", "  "], [None], [None, ""]])
def test_list_of_only_blank_entries_is_auth_disabled(configured):
    """Equivalent to no key at all — open, and the startup warning fires."""
    manager = make_manager(configured)
    assert manager.is_auth_disabled() is True
    assert manager.usable_keys() == []


def test_blank_master_locks_admin_surface_end_to_end():
    client = build_client(["", "app-key"])
    for creds in ("", "app-key"):
        resp = client.get("/dashboard", headers={"Authorization": f"Bearer {creds}"})
        assert resp.status_code == 401
    # bare "Bearer" with nothing after it
    assert (
        client.get("/dashboard", headers={"Authorization": "Bearer "}).status_code
        == 401
    )
    # proxying is unaffected
    assert (
        client.get(
            "/api/v1/thing", headers={"Authorization": "Bearer app-key"}
        ).status_code
        == 200
    )


def test_usable_keys_ignores_unexpected_config_shape():
    """An unrecognised shape denies rather than opening."""
    manager = make_manager(42)
    assert manager.usable_keys() == []
    assert manager.master_key() is None
    assert manager.is_auth_disabled() is False
    assert manager.verify_api_key("anything") is False


# --------------------------------------------------------------------------
# Master-key separation: only the first configured key reaches the admin
# surfaces (dashboard, config UI); every configured key may use the proxy.
# --------------------------------------------------------------------------


ADMIN_PATHS = ["/dashboard", "/dashboard/api/metrics", "/config", "/config/api/apps"]


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_non_master_key_cannot_reach_admin_surfaces(path):
    """Regression: a proxy-only key must not open the dashboard or config UI."""
    client = build_client(["master", "app-key"])
    resp = client.get(path, headers={"Authorization": "Bearer app-key"})
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("text/html")  # login page


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_master_key_reaches_admin_surfaces(path):
    client = build_client(["master", "app-key"])
    resp = client.get(path, headers={"Authorization": "Bearer master"})
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_non_master_key_still_allowed_for_proxy_traffic():
    """The whole point of the extra keys: proxying, just not administration."""
    client = build_client(["master", "app-key"])
    resp = client.get("/api/v1/thing", headers={"Authorization": "Bearer app-key"})
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_non_master_session_cookie_cannot_reach_admin_surfaces():
    client = build_client(["master", "app-key"])
    client.cookies.set("nyaproxy_api_key", "app-key")
    assert client.get("/dashboard").status_code == 401


def test_single_string_key_is_its_own_master():
    """With one configured key there is no distinction to enforce."""
    client = build_client("solo")
    resp = client.get("/dashboard", headers={"Authorization": "Bearer solo"})
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("path", "root_path", "expected"),
    [
        # ASGI servers disagree on whether `path` includes the mount prefix,
        # so both conventions must resolve to the same answer.
        ("/dashboard", "/prefix", True),  # path excludes root_path
        ("/prefix/dashboard", "/prefix", True),  # path includes root_path
        ("/config/api/apps", "/prefix", True),
        ("/prefix/config/api/apps", "/prefix", True),
        ("/dashboard", "", True),
        ("/api/svc/thing", "", False),
        # 'dashboard' appearing inside a proxied upstream path is not admin
        ("/api/svc/dashboard/widget", "", False),
        # a sibling path that merely shares the prefix string is not admin
        ("/dashboard-public", "", False),
        # a mounted admin sub-app carries its mount prefix in root_path
        ("/api/config/clients", "/dashboard", True),
        ("/anything", "/dashboard", True),
        # reverse proxy prepending its own segment: composite root_path
        ("/api/x", "/proxy/dashboard", True),
        # siblings / unrelated prefixes must not match via endswith
        ("/api/x", "/dashboard-public", False),
        ("/api/x", "/prefix", False),
    ],
)
def test_is_admin_surface_path_resolution(path, root_path, expected):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "root_path": root_path,
            "headers": [],
            "query_string": b"",
        }
    )
    assert AuthMiddleware._is_admin_surface(request) is expected


def test_proxy_path_containing_dashboard_segment_is_not_admin():
    """A proxied upstream path that merely contains 'dashboard' stays open."""

    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/api/svc/dashboard/widget", ok)])
    app.add_middleware(AuthMiddleware, auth=make_manager(["master", "app-key"]))
    client = TestClient(app)

    resp = client.get(
        "/api/svc/dashboard/widget", headers={"Authorization": "Bearer app-key"}
    )
    assert resp.status_code == 200


def test_mounted_admin_sub_app_accepts_dashboard_key_end_to_end():
    """Two AuthMiddlewares (outer + mounted sub), as wired in app.py.

    Regression for the 403 on mounted admin sub-apps: the inner middleware
    sees the full path but root_path="/dashboard", which used to strip the
    admin prefix away and turn the dashboard key into a proxy-key check.
    """

    async def ok(request):
        return PlainTextResponse("ok")

    auth = make_manager(["master-key", "client-key"], dashboard_key=["dash-1"])

    # Inner app: its own AuthMiddleware, routes relative to the mount (like
    # dashboard_app) -> answers GET /dashboard/api/ping from the outside.
    sub = Starlette(routes=[Route("/api/ping", ok)])
    sub.add_middleware(AuthMiddleware, auth=auth)

    # Outer app: its own AuthMiddleware + a proxy route and a plain probe.
    outer = Starlette(
        routes=[Route("/api/proxy/thing", ok), Route("/dashboard_probe", ok)]
    )
    outer.add_middleware(AuthMiddleware, auth=auth)
    outer.mount("/dashboard", sub)
    client = TestClient(outer)

    # The bug itself: the dashboard key must pass BOTH middleware layers.
    assert (
        client.get(
            "/dashboard/api/ping", headers={"Authorization": "dash-1"}
        ).status_code
        == 200
    )
    # A proxy key is stopped by the outer admin gate (login page, 401).
    resp = client.get("/dashboard/api/ping", headers={"Authorization": "client-key"})
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("text/html")
    # The dashboard key must not reach proxy routes outside the mount.
    resp = client.get("/api/proxy/thing", headers={"Authorization": "dash-1"})
    assert resp.status_code == 403
    assert "error" in resp.json()
    # Proxy traffic is unaffected by the fix.
    assert (
        client.get(
            "/api/proxy/thing", headers={"Authorization": "client-key"}
        ).status_code
        == 200
    )


def test_login_page_returns_500_when_template_missing(monkeypatch):
    """A missing login template degrades to a JSON 500, not a crash."""
    import importlib.resources

    def boom(_package):
        raise FileNotFoundError("login.html missing")

    monkeypatch.setattr(importlib.resources, "files", boom)
    client = build_client("secret")
    resp = client.get("/dashboard")
    assert resp.status_code == 500


# --------------------------------------------------------------------------
# Dedicated dashboard keys (server.dashboard.api_key): admin login is
# decoupled from the client keys the proxy accepts. Rotating a client key
# must never log the operator out, and a dashboard key must never proxy.
# --------------------------------------------------------------------------


def test_dashboard_keys_take_over_admin_and_exclude_proxy_keys():
    """List form: only dashboard keys administer; proxy keys unchanged."""
    manager = make_manager(
        ["master-key", "app-key"], dashboard_key=["dash-1", "dash-2"]
    )
    assert manager.dashboard_configured() is True

    # both dashboard keys reach the admin surfaces
    assert manager.verify_api_key("dash-1", verify_master=True) is True
    assert manager.verify_api_key("dash-2", verify_master=True) is True
    # the old master and every client key stop administering the UI
    assert manager.verify_api_key("master-key", verify_master=True) is False
    assert manager.verify_api_key("app-key", verify_master=True) is False

    # proxy traffic is untouched: client keys work, dashboard keys do not
    assert manager.verify_api_key("master-key") is True
    assert manager.verify_api_key("app-key") is True
    assert manager.verify_api_key("dash-1") is False
    assert manager.verify_api_key("dash-2") is False
    # usable_keys reads ONLY server.api_key — the core of the decoupling
    assert manager.usable_keys() == ["master-key", "app-key"]


def test_dashboard_key_string_form():
    manager = make_manager("master-key", dashboard_key="dash-only")
    assert manager.verify_api_key("dash-only", verify_master=True) is True
    assert manager.verify_api_key("master-key", verify_master=True) is False


def test_blank_dashboard_entries_fall_back_to_master():
    """A blank-only dashboard setting must not lock the admin surfaces."""
    manager = make_manager(["first", "second"], dashboard_key=["", "   "])
    assert manager.dashboard_configured() is False
    assert manager.verify_api_key("first", verify_master=True) is True
    assert manager.verify_api_key("second", verify_master=True) is False


def test_fallback_to_master_when_dashboard_key_unset():
    """Unset dashboard key = today's behaviour: first api_key entry admins."""
    manager = make_manager(["first", "second"])
    assert manager.dashboard_configured() is False
    assert manager.dashboard_keys() == []
    assert manager.master_key() == "first"
    assert manager.verify_api_key("first", verify_master=True) is True
    assert manager.verify_api_key("second", verify_master=True) is False


def test_dashboard_key_never_authenticates_proxy_traffic():
    """Requirement: the proxy does not accept dashboard keys (verify_master=False)."""
    manager = make_manager(["app-key"], dashboard_key="dash-only")
    assert manager.verify_api_key("dash-only", verify_master=False) is False
    assert manager.verify_api_key("app-key", verify_master=False) is True


def test_verify_session_cookie_accepts_dashboard_key():
    manager = make_manager(["master-key", "app-key"], dashboard_key="dash-only")
    dash_cookie = FakeRequest(cookies={"nyaproxy_api_key": "dash-only"})
    master_cookie = FakeRequest(cookies={"nyaproxy_api_key": "master-key"})
    assert manager.verify_session_cookie(dash_cookie) is True
    # rotated/old client key no longer keeps an admin session alive
    assert manager.verify_session_cookie(master_cookie) is False


def test_middleware_admin_gated_by_dashboard_key_when_auth_disabled():
    """api_key unset + dashboard key set: proxy open, admin still guarded."""
    manager = make_manager(None, dashboard_key="dash-only")
    assert manager.is_auth_disabled() is True
    assert manager.dashboard_configured() is True

    # the combination the new dispatch logic must honour: a plain request on
    # an admin surface is NOT passed through just because auth is disabled
    assert manager.verify_api_key("", verify_master=True) is False
    assert manager.verify_api_key("anything", verify_master=True) is False
    assert manager.verify_api_key("dash-only", verify_master=True) is True

    client = build_client(None, dashboard_key="dash-only")
    # proxy path stays open
    assert client.get("/api/v1/thing").status_code == 200
    # admin surface without credentials -> login page, not a pass-through
    resp = client.get("/dashboard")
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("text/html")
    # ...with the dashboard key it opens
    assert (
        client.get(
            "/dashboard", headers={"Authorization": "Bearer dash-only"}
        ).status_code
        == 200
    )
    # ...and a session cookie with the dashboard key opens it too
    client.cookies.set("nyaproxy_api_key", "dash-only")
    assert client.get("/config").status_code == 200


def test_middleware_dashboard_key_decoupled_from_client_keys():
    """End-to-end: master locked out of admin, dashboard key locked out of proxy."""
    client = build_client(["master", "app-key"], dashboard_key="dash-key")

    # admin surfaces: dashboard key in, everyone else out (login page)
    assert (
        client.get(
            "/dashboard", headers={"Authorization": "Bearer dash-key"}
        ).status_code
        == 200
    )
    resp = client.get("/dashboard", headers={"Authorization": "Bearer master"})
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("text/html")

    # proxy: client key in, dashboard key out (JSON 403)
    assert (
        client.get(
            "/api/v1/thing", headers={"Authorization": "Bearer app-key"}
        ).status_code
        == 200
    )
    resp = client.get("/api/v1/thing", headers={"Authorization": "Bearer dash-key"})
    assert resp.status_code == 403
    assert "error" in resp.json()


def test_middleware_auth_disabled_without_dashboard_key_stays_open():
    """Regression: no api_key and no dashboard key = everything open."""
    manager = make_manager(None)
    assert manager.is_auth_disabled() is True
    assert manager.verify_api_key("anything", verify_master=True) is True

    client = build_client(None)
    assert client.get("/api/v1/thing").status_code == 200
    assert client.get("/dashboard").status_code == 200


def test_schema_accepts_server_dashboard_api_key():
    """server.dashboard.api_key validates against nya/schema.json (anyOf)."""
    import json
    from importlib import resources

    import jsonschema

    schema = json.loads(
        (resources.files("nya") / "schema.json").read_text(encoding="utf-8")
    )
    base_config = {
        "server": {"api_key": "proxy-key"},
        "default_settings": {},
        "apis": {
            "mock": {
                "name": "Mock API",
                "endpoint": "https://upstream.test",
                "headers": {"X-Key": "value"},
                "variables": {"keys": ["k"]},
            }
        },
    }

    for dashboard_api_key in ("dash-only", ["dash-1", "dash-2"]):
        config = json.loads(json.dumps(base_config))
        config["server"]["dashboard"] = {
            "enabled": True,
            "api_key": dashboard_api_key,
        }
        jsonschema.validate(config, schema)

    # blank keys stay rejected (minLength / minItems guards)
    config = json.loads(json.dumps(base_config))
    config["server"]["dashboard"] = {"api_key": ""}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(config, schema)
