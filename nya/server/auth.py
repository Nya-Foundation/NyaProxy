"""
Authentication module for NyaProxy.
Provides authentication mechanisms and middleware.
"""

import hmac
import importlib.resources
import json
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import unquote

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse

if TYPE_CHECKING:
    from nya.config import ConfigManager  # pragma: no cover


class AuthManager:
    """
    Centralized authentication manager for NyaProxy
    """

    def __init__(self, config: Optional["ConfigManager"] = None):
        """
        Initialize the authentication manager.

        Args:
            config: The configuration manager instance
        """
        self.config = config

    def get_api_key(self):
        """
        Get the configured API key
        """
        return self.config.get_api_key()

    def usable_keys(self) -> List[str]:
        """
        Configured keys that can actually authenticate, in configured order.

        Reads ONLY ``server.api_key``: dedicated dashboard keys must never
        reach the proxy. Blank and non-string entries are dropped: an unset
        ``${VAR}`` or a stray ``-`` in YAML must never authenticate anything.
        Returns an empty list for an unrecognised config shape, which callers
        treat as "nothing matches" rather than "no auth".
        """
        return self._normalize_key_entries(self.get_api_key())

    @staticmethod
    def _normalize_key_entries(configured_key) -> List[str]:
        """
        Normalize a raw ``None | str | list`` key setting into usable entries.

        Shared by ``usable_keys`` and ``dashboard_keys`` so both surfaces
        apply exactly the same blank/non-string filtering.
        """
        if isinstance(configured_key, str):
            configured_key = [configured_key]
        elif not isinstance(configured_key, list):
            return []

        return [
            entry.strip()
            for entry in configured_key
            if isinstance(entry, str) and entry.strip()
        ]

    def dashboard_keys(self) -> List[str]:
        """
        Dedicated admin-login keys from ``server.dashboard.api_key``.

        Normalized exactly like ``usable_keys``. These keys are accepted ONLY
        on the admin surfaces (dashboard, config UI) — the proxy never takes
        them, which is the point of decoupling admin login from client keys.
        """
        if self.config is None:
            return []
        return self._normalize_key_entries(self.config.get_dashboard_api_key())

    def dashboard_configured(self) -> bool:
        """
        True when at least one dedicated dashboard login key is configured.
        """
        return bool(self.dashboard_keys())

    def master_key(self) -> Optional[str]:
        """
        The single credential allowed on the admin surfaces.

        This is the *first configured entry*, not the first usable one: if the
        operator left it blank, the admin surfaces lock rather than silently
        promoting a proxy key to master.
        """
        configured_key = self.get_api_key()
        if isinstance(configured_key, str):
            first = configured_key
        elif isinstance(configured_key, list) and configured_key:
            first = configured_key[0]
        else:
            return None

        return first.strip() if isinstance(first, str) and first.strip() else None

    def is_auth_disabled(self) -> bool:
        """
        True when no usable API key is configured, i.e. every request is allowed.
        """
        configured_key = self.get_api_key()
        if configured_key is None:
            return True
        if isinstance(configured_key, str):
            stripped = configured_key.strip()
            return not stripped or stripped.lower() in ("none", "null")
        if isinstance(configured_key, list):
            # A list holding only blank entries is the same as no key at all.
            return not self.usable_keys()
        return False

    def verify_api_key(self, key: str, verify_master: bool = False) -> bool:
        """
        Verify if the provided key matches the configured API key.

        Args:
            key: The api key to verify
            verify_master: If True, verify against the admin-login credential:
                the dedicated ``server.dashboard.api_key`` entries when set,
                otherwise the first ``server.api_key`` entry (master)

        Returns:
            bool: True if valid, False otherwise
        """
        if not isinstance(key, str):
            raise ValueError("API key must be a string")

        # Strip the key to ensure consistent comparison
        key = key.strip()

        if verify_master:
            # A dedicated dashboard key decouples admin login from the proxy
            # keys: when configured, ONLY those keys administer the surfaces —
            # not even the master entry of server.api_key, and regardless of
            # whether proxy auth is disabled.
            if self.dashboard_configured():
                return any(self._secrets_equal(key, k) for k in self.dashboard_keys())

            if self.is_auth_disabled():
                return True

            # Fallback: the first configured key administers the proxy; a blank
            # master entry locks the admin surfaces instead of opening them.
            master = self.master_key()
            if not master:
                return False
            return self._secrets_equal(key, master)

        if self.is_auth_disabled():
            return True

        return any(self._secrets_equal(key, k) for k in self.usable_keys())

    @staticmethod
    def _secrets_equal(provided: str, expected: str) -> bool:
        """
        Compare two secrets in constant time to avoid timing attacks.

        ``hmac.compare_digest`` only accepts ASCII strings; a non-ASCII key
        cannot match an ASCII-only configured key anyway, so treat it as a
        mismatch instead of raising.
        """
        try:
            return hmac.compare_digest(provided, expected)
        except TypeError:
            return False

    def verify_session_cookie(self, request: Request):
        """
        Verify if the session cookie contains a valid API key.

        Args:
            request: The FastAPI request

        Returns:
            bool: True if valid, False otherwise
        """

        # Get API key from session cookie. The login page URI-encodes the
        # value so keys containing ';', ',' or non-ASCII survive the cookie
        # grammar — decode before comparing.
        cookie_key = request.cookies.get("nyaproxy_api_key", "")

        # Trim any whitespace that might be added by some browsers
        cookie_key = unquote(cookie_key).strip() if cookie_key else ""

        # Verify the cookie key against the admin-login credential only
        # (dedicated dashboard key when set, else the master key)
        return self.verify_api_key(cookie_key, verify_master=True)

    def verify_api_key_header(self, request: Request, verify_master: bool = False):
        """
        Verify the API key from the Authorization header.

        Args:
            request: The FastAPI request
            verify_master: If True, only the master key is accepted. Admin
                surfaces (dashboard, config UI) pass True; proxy traffic
                accepts any configured key.

        Returns:
            bool: True if valid, False otherwise
        """
        api_key = request.headers.get("Authorization", "")
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]

        return self.verify_api_key(api_key, verify_master=verify_master)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware for FastAPI applications
    """

    def __init__(self, app, auth: AuthManager):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request: Request, call_next):

        # Browsers need unauthenticated CORS preflight, but an ordinary
        # OPTIONS request is a proxy request and must follow normal auth.
        is_cors_preflight = (
            request.method == "OPTIONS"
            and "origin" in request.headers
            and "access-control-request-method" in request.headers
        )
        if is_cors_preflight:
            return await call_next(request)

        # Skip auth for specific paths if needed
        excluded_paths = [
            "/",
            "/health",
            "/info",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        # Public assets the pre-auth login page needs; suffix match so they
        # stay reachable behind any reverse-proxy path prefix.
        excluded_asset_suffixes = (
            "/dashboard/static/logo.svg",
            "/dashboard/favicon.ico",
            "/dashboard/static/fonts/SpaceGrotesk-var.woff2",
        )
        if request.url.path in excluded_paths or request.url.path.endswith(
            excluded_asset_suffixes
        ):
            return await call_next(request)

        # The dashboard and the config UI are administrative surfaces: only the
        # admin credential reaches them (a dedicated server.dashboard.api_key,
        # or the master key when none is set). Every other path is proxy
        # traffic, which any configured key may use.
        is_admin_surface = self._is_admin_surface(request)

        # Proxy auth is disabled (no server.api_key): all proxy traffic is
        # open. A dedicated dashboard key still locks the admin surfaces, so
        # those must fall through to the credential checks below instead of
        # being passed early.
        if self.auth.is_auth_disabled():
            if not (is_admin_surface and self.auth.dashboard_configured()):
                return await call_next(request)

        # First, check for valid session cookie (admin credential only)
        if self.auth.verify_session_cookie(request):
            return await call_next(request)

        # Then, check for valid Authorization header
        if self.auth.verify_api_key_header(request, verify_master=is_admin_surface):
            return await call_next(request)

        # For dashboard and config paths, redirect to login page
        if is_admin_surface:
            return self._generate_login_page(request)

        # For API and other paths, return JSON error
        return JSONResponse(
            status_code=403,
            content={"error": "Unauthorized: NyaProxy - Invalid API key"},
        )

    @staticmethod
    def _is_admin_surface(request: Request) -> bool:
        """
        True for the dashboard and config UI, which require the master key.

        The mount prefix is stripped first so the check still holds when the
        app is served under a reverse-proxy path prefix. A mounted admin
        sub-app also carries its mount prefix in root_path, so that value is
        checked as an additional candidate surface name.
        """
        path = request.url.path
        root_path = request.scope.get("root_path", "")

        def _matches(candidate: str) -> bool:
            return any(
                candidate == prefix or candidate.startswith(f"{prefix}/")
                for prefix in ("/dashboard", "/config")
            )

        if root_path and path.startswith(root_path):
            path = path[len(root_path) :] or "/"

        # The root/mount prefix may itself name the surface: a mounted
        # admin sub-app (dashboard, config) carries its mount prefix in
        # root_path, and a reverse proxy may prepend its own segment
        # ("/proxy/dashboard"). root_path is server configuration, and each
        # prefix starts with "/", so endswith() stays segment-safe.
        return _matches(path) or any(
            root_path == prefix or root_path.endswith(prefix)
            for prefix in ("/dashboard", "/config")
        )

    def _generate_login_page(self, request: Request):
        """
        Generate a login page for the dashboard or config app
        """
        return_path = request.url.path

        # load the login HTML template using importlib.resources
        try:
            template_path = importlib.resources.files("nya") / "html" / "login.html"
            with template_path.open("r") as f:
                html_content = f.read()
        except (FileNotFoundError, TypeError, ImportError):
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error: Login page unavailable"},
            )

        # The template quotes the placeholder ("{{ return_path }}") inside JS
        # string literals; substitute a JSON-escaped literal so a crafted
        # percent-encoded path cannot break out of the string (reflected XSS).
        # \u-escape <> as well so '</script>' cannot terminate the block.
        safe_return_path = (
            json.dumps(return_path).replace("<", "\\u003c").replace(">", "\\u003e")
        )
        asset_root = request.scope.get("root_path", "") + "/dashboard"
        html_content = html_content.replace(
            '"{{ return_path }}"', safe_return_path
        ).replace("{{ asset_root }}", asset_root)

        return HTMLResponse(content=html_content, status_code=401)
