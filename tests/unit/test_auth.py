"""
Unit tests for the authentication layer (``nya.server.auth``).

Covers credential verification (``AuthManager``) and the request gate
(``AuthMiddleware``). Auth is security-critical, so every branch of the
configured-key handling is exercised explicitly.
"""

import pytest
from starlette.applications import Starlette
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
        Route("/config", ok),
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


def test_login_page_returns_500_when_template_missing(monkeypatch):
    """A missing login template degrades to a JSON 500, not a crash."""
    import importlib.resources

    def boom(_package):
        raise FileNotFoundError("login.html missing")

    monkeypatch.setattr(importlib.resources, "files", boom)
    client = build_client("secret")
    resp = client.get("/dashboard")
    assert resp.status_code == 500
