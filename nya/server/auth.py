"""
Authentication module for NyaProxy.
Provides authentication mechanisms and middleware.
"""

import importlib.resources
import secrets
from typing import TYPE_CHECKING, Optional

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse

if TYPE_CHECKING:
    from nya.config import ConfigManager  # pragma: no cover


class AuthManager:
    """
    Centralized authentication manager for NyaProxy
    """

    def __init__(self, config: "ConfigManager" = None):
        """
        Initialize the authentication manager.

        Args:
            config: The configuration manager instance
        """
        self.config = config
        self._auto_generated_key: Optional[str] = None

    def get_api_key(self):
        """
        Get the configured API key
        """
        return self.config.get_api_key()

    def ensure_admin_key(self) -> str:
        """
        Ensure an admin key exists for management interfaces.
        Auto-generates one if no API key is configured.
        """
        configured_key = self.get_api_key()
        if configured_key and not (
            isinstance(configured_key, str) and not configured_key.strip()
        ):
            if isinstance(configured_key, list):
                return configured_key[0].strip()
            return configured_key.strip()

        if self._auto_generated_key is None:
            self._auto_generated_key = secrets.token_urlsafe(32)
            logger.warning(
                "=" * 60 + "\n"
                "SECURITY NOTICE: No API key configured.\n"
                "A random admin key has been generated for /config and /dashboard:\n"
                f"  {self._auto_generated_key}\n"
                "Use this key in the Authorization header to access management interfaces.\n"
                "Set 'server.api_key' in your config file for persistent configuration.\n"
                + "=" * 60
            )
        return self._auto_generated_key

    def verify_api_key(self, key: str, verify_master: bool = False) -> bool:
        """
        Verify if the provided key matches the configured API key.

        Args:
            key: The api key to verify
            verify_master: If True, only verify against the master key

        Returns:
            bool: True if valid, False otherwise
        """
        if not isinstance(key, str):
            raise ValueError("API key must be a string")

        # Strip the key to ensure consistent comparison
        key = key.strip()

        # Get the configured key (can be None, str, or List[str])
        configured_key = self.get_api_key()

        # If no API key is configured, allow all keys
        if configured_key is None:
            return True

        # Handle string case
        if isinstance(configured_key, str):
            # Empty config key or special values mean no auth
            if not configured_key.strip() or configured_key.strip().lower() in [
                "none",
                "null",
            ]:
                return True
            return key == configured_key.strip()

        # Handle list case
        if isinstance(configured_key, list):
            # Empty list means no auth
            if not configured_key:
                return True

            if verify_master:
                # Only check first key if verify_master is True and list is not empty
                return configured_key and key == configured_key[0].strip()

            # Check all keys if verify_master is False
            return any(key == k.strip() for k in configured_key)

        # If we reach here, configured_key is an unexpected type
        return False

    def verify_session_cookie(self, request: Request):
        """
        Verify if the session cookie contains a valid API key.

        Args:
            request: The FastAPI request

        Returns:
            bool: True if valid, False otherwise
        """

        # Get API key from session cookie
        cookie_key = request.cookies.get("nyaproxy_api_key", "")

        # Trim any whitespace that might be added by some browsers
        cookie_key = cookie_key.strip() if cookie_key else ""

        # Log keys for debugging - remove in production
        # print(f"Cookie key: '{cookie_key}', Configured key: '{configured_key}'")

        # Verify the cookie key against the configured master key only
        return self.verify_api_key(cookie_key, verify_master=True)

    def verify_api_key_header(self, request: Request):
        """
        Verify the API key from the Authorization header.

        Args:
            request: The FastAPI request

        Returns:
            bool: True if valid, False otherwise
        """
        api_key = request.headers.get("Authorization", "")
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]

        return self.verify_api_key(api_key)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware for FastAPI applications
    """

    def __init__(self, app, auth: AuthManager):
        super().__init__(app)
        self.auth = auth

    async def dispatch(self, request: Request, call_next):

        # skip OPTIONS requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for specific paths if needed
        excluded_paths = [
            "/",
            "/info",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/dashboard/static/logo.svg",
            "/dashboard/favicon.ico",
        ]
        if any(request.url.path == path for path in excluded_paths):
            return await call_next(request)

        is_dashboard = request.url.path.startswith("/dashboard")
        is_config = request.url.path.startswith("/config")

        configured_key = self.auth.get_api_key()
        key_is_unset = configured_key is None or (
            isinstance(configured_key, (str, list)) and not configured_key
        )

        # Management interfaces (/config, /dashboard) ALWAYS require auth
        if is_dashboard or is_config:
            if key_is_unset:
                admin_key = self.auth.ensure_admin_key()
                provided = ""
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    provided = auth_header[7:]
                cookie_key = request.cookies.get("nyaproxy_api_key", "")
                if secrets.compare_digest(admin_key, provided) or \
                   secrets.compare_digest(admin_key, cookie_key.strip()):
                    return await call_next(request)
            else:
                if self.auth.verify_session_cookie(request):
                    return await call_next(request)
                if self.auth.verify_api_key_header(request):
                    return await call_next(request)
            return self._generate_login_page(request)

        # For proxy routes: no auth needed if API key is not set
        if key_is_unset:
            return await call_next(request)

        # First, check for valid session cookie
        if self.auth.verify_session_cookie(request):
            return await call_next(request)

        # Then, check for valid Authorization header
        if self.auth.verify_api_key_header(request):
            return await call_next(request)

        # For API and other paths, return JSON error
        return JSONResponse(
            status_code=403,
            content={"error": "Unauthorized: NyaProxy - Invalid API key"},
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

        # Replace placeholders in the HTML template
        html_content = html_content.replace("{{ return_path }}", return_path)

        return HTMLResponse(content=html_content, status_code=401)
