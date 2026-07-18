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
    """Minimal stand-in for ConfigManager exposing only ``get_api_key``."""

    def __init__(self, api_key):
        self._api_key = api_key

    def get_api_key(self):
        return self._api_key


def make_manager(api_key):
    return AuthManager(config=FakeConfig(api_key))


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


def build_client(api_key):
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
    app.add_middleware(AuthMiddleware, auth=make_manager(api_key))
    return TestClient(app)


def test_middleware_allows_options_requests():
    client = build_client("secret")
    assert client.options("/api/v1/thing").status_code != 403


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


def test_login_page_returns_500_when_template_missing(monkeypatch):
    """A missing login template degrades to a JSON 500, not a crash."""
    import importlib.resources

    def boom(_package):
        raise FileNotFoundError("login.html missing")

    monkeypatch.setattr(importlib.resources, "files", boom)
    client = build_client("secret")
    resp = client.get("/dashboard")
    assert resp.status_code == 500
