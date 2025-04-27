"""
Authentication module for NyaProxy.
Provides authentication mechanisms and middleware.
"""

import importlib.resources

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse


class AuthManager:
    """Centralized authentication manager for NyaProxy"""

    def __init__(self, config_manager=None):
        """
        Initialize the authentication manager.

        Args:
            config_manager: The configuration manager instance
        """
        self.config = config_manager
        self.header = APIKeyHeader(name="Authorization", auto_error=False)

    def set_config_manager(self, config_manager):
        """Set the configuration manager"""
        self.config = config_manager

    def get_api_key(self):
        """Get the configured API key"""
        if not self.config:
            return ""
        return self.config.get_api_key()

    async def verify_api_key(
        self,
        api_key: str = Depends(APIKeyHeader(name="Authorization", auto_error=False)),
    ):
        """
        Verify the API key if one is configured.

        Returns:
            bool: True if valid or no key configured, False otherwise
        """
        configured_key = self.get_api_key()

        # No API key required if none is configured
        if not configured_key:
            return True

        # API key required but not provided
        if not api_key:
            raise HTTPException(
                status_code=401, detail="Unauthorized: API key required"
            )

        # Strip "Bearer " prefix if present
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]

        # API key provided but invalid
        if api_key != configured_key:
            raise HTTPException(
                status_code=403, detail="Unauthorized: Insufficient Permissions"
            )

        return True

    def create_middleware(self):
        """
        Create a new instance of AuthMiddleware.

        Returns:
            AuthMiddleware: A middleware instance configured with this auth manager
        """
        return lambda app: AuthMiddleware(app, self)

    def verify_session_cookie(self, request: Request):
        """
        Verify if the session cookie contains a valid API key.

        Args:
            request: The FastAPI request

        Returns:
            bool: True if valid, False otherwise
        """

    def verify_session_cookie(self, request: Request):
        """
        Verify if the session cookie contains a valid API key.

        Args:
            request: The FastAPI request

        Returns:
            bool: True if valid, False otherwise
        """
        configured_key = self.get_api_key()
        if not configured_key:
            return True

        # Get API key from session cookie
        cookie_key = request.cookies.get("nyaproxy_api_key", "")

        # Trim any whitespace that might be added by some browsers
        cookie_key = cookie_key.strip() if cookie_key else ""

        # Log keys for debugging - remove in production
        # print(f"Cookie key: '{cookie_key}', Configured key: '{configured_key}'")

        # Validate the key
        return cookie_key == configured_key


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for FastAPI applications"""

    def __init__(self, app, auth_manager: AuthManager):
        super().__init__(app)
        self.auth_manager = auth_manager

    async def dispatch(self, request: Request, call_next):
        # Skip auth for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for specific paths if needed
        excluded_paths = ["/docs", "/redoc", "/openapi.json", "/auth/login"]
        if any(request.url.path.startswith(path) for path in excluded_paths):
            return await call_next(request)

        configured_key = self.auth_manager.get_api_key()

        # No API key required if none is configured
        if not configured_key:
            return await call_next(request)

        # Check if this is a login form submission
        if request.url.path.endswith("/auth/verify") and request.method == "POST":
            return await call_next(request)

        # First, check for valid session cookie
        if self.auth_manager.verify_session_cookie(request):
            return await call_next(request)

        # Then, check for valid Authorization header
        api_key = request.headers.get("Authorization", "")
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]

        if api_key and api_key == configured_key:
            return await call_next(request)

        # If no valid auth found, determine response based on path
        is_dashboard = request.url.path.startswith("/dashboard")
        is_config = request.url.path.startswith("/config")

        # For dashboard and config paths, redirect to login page
        if is_dashboard or is_config:
            return self._generate_login_page(request)

        # For API and other paths, return JSON error
        return JSONResponse(
            status_code=403, content={"error": "Unauthorized: Invalid API key"}
        )

    def _generate_login_page(self, request: Request):
        """Generate a login page for the dashboard or config app"""
        return_path = request.url.path

        # load the login HTML template using importlib.resources
        try:
            template_path = (
                importlib.resources.files("nya_proxy") / "templates" / "login.html"
            )
            with template_path.open("r") as f:
                html_content = f.read()
        except (FileNotFoundError, TypeError, ImportError):
            # Log an error and return a generic error response
            # Consider adding logging here if self.logger is available or passed
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error: Login page unavailable"},
            )

        # Replace placeholders in the HTML template
        html_content = html_content.replace("{{ return_path }}", return_path)

        return HTMLResponse(content=html_content, status_code=401)
