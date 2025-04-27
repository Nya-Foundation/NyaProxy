#!/usr/bin/env python3
"""
NyaProxy - A simple low-level API proxy with dynamic token rotation.
"""
import argparse
import contextlib
import logging
import os
import sys
import time

import uvicorn
from fastapi import Depends, FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from ..common.constants import (
    DEFAULT_CONFIG_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCHEMA_NAME,
)
from ..common.models import NyaRequest
from ..core.handler import NyaProxyCore
from ..dashboard.api import DashboardAPI
from .auth import AuthManager, AuthMiddleware
from .config import ConfigAPI, ConfigManager
from .logger import setup_logger


class RootPathMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, root_path: str):
        super().__init__(app)
        self.root_path = root_path

    async def dispatch(self, request: Request, call_next):
        request.scope["root_path"] = self.root_path
        return await call_next(request)


class NyaProxyApp:
    """Main NyaProxy application class"""

    def __init__(self, config_path=None):
        """Initialize the NyaProxy application"""
        # Initialize instance variables
        self.config = None
        self.logger = None
        self.core = None
        self.metrics_collector = None
        self.request_queue = None
        self.auth_manager = AuthManager()
        self.dashboard = None

        # Load config early to allow configuration of middleware
        self._init_config(config_path)

        # Set up the auth manager with config
        self._init_auth()

        # Create FastAPI app with middleware pre-configured
        self.app = self._create_main_app()

    def _create_main_app(self):
        """Create the main FastAPI application with middleware pre-configured"""
        app = FastAPI(
            title="NyaProxy",
            description="A simple low-level API proxy with dynamic token rotation and load balancing",
            version="0.0.5",
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Add auth middleware
        app.add_middleware(AuthMiddleware, auth_manager=self.auth_manager)

        # Set up basic routes
        self._setup_routes(app)

        return app

    @contextlib.asynccontextmanager
    async def lifespan(self, app):
        """Lifespan context manager for FastAPI"""
        await self.initialize_proxy_services()
        yield
        await self.shutdown()

    def _setup_routes(self, app):
        """Set up FastAPI routes"""

        @app.get("/", include_in_schema=False)
        async def root():
            """Root endpoint"""
            return JSONResponse(
                content={"message": "Welcome to NyaProxy!"},
                status_code=200,
            )

        # Info endpoint
        @app.get("/info")
        async def info(api_key_valid: bool = Depends(self.auth_manager.verify_api_key)):
            """Get information about the proxy."""
            apis = {}
            if self.config:
                for name, config in self.config.get_apis().items():
                    apis[name] = {
                        "name": config.get("name", name),
                        "endpoint": config.get("endpoint", ""),
                        "aliases": config.get("aliases", []),
                    }

            return {"status": "running", "version": "0.0.5", "apis": apis}

    async def generic_proxy_request(self, request: Request):
        """Generic handler for all proxy requests."""
        if not self.core:
            return JSONResponse(
                status_code=503,
                content={"error": "Proxy service is starting up or unavailable"},
            )

        req = NyaRequest(
            method=request.method,
            headers=dict(request.headers),
            _url=request.url,
            _raw=request,
            content=await request.body(),
            added_at=time.time(),
        )

        return await self.core.handle_request(req)

    async def initialize_proxy_services(self):
        """Initialize the proxy services."""
        try:
            # Initialize logging after config is available
            self._init_logging()

            # Initialize core components
            self._init_core()

            # Mount sub-applications for NyaProxy
            self._init_config_server()
            self._init_dashboard()

            # Initialize proxy routes last to act as a catch-all
            self._setup_proxy_routes()

        except Exception as e:
            # Log startup error
            logging.error(f"Error during startup: {str(e)}")
            if self.logger:
                self.logger.error(f"Error during startup: {str(e)}")
            raise

    def _init_config(self, config_path=None):
        """Initialize configuration manager."""

        self.config = ConfigManager(config_path=config_path, logger=self.logger)
        return self.config

    def _init_logging(self):
        """Initialize logging."""
        log_config = self.config.get_logging_config()
        self.logger = setup_logger(log_config)
        self.logger.info(
            f"Logging initialized with level {log_config.get('level', 'INFO')}"
        )
        return self.logger

    def _init_auth(self):
        """Initialize authentication manager."""
        self.auth_manager.set_config_manager(self.config)
        return self.auth_manager

    def _init_core(self):
        """Initialize the core proxy handler."""
        if not self.config:
            raise RuntimeError(
                "Config manager must be initialized before proxy handler"
            )

        if not self.logger:
            logging.warning(
                "Logger not initialized, proxy handler will use default logging"
            )

        self.core = NyaProxyCore(
            config=self.config,
            logger=self.logger or logging.getLogger("nyaproxy"),
        )

        if self.logger:
            self.logger.info("Proxy handler initialized")
        return self.core

    def _init_config_server(self):
        """Initialize and mount configuration web server if available."""
        if not self.config:
            if self.logger:
                self.logger.warning(
                    "Config manager not initialized, config server disabled"
                )
            return False

        if not hasattr(self.config, "server") or not hasattr(self.config.server, "app"):
            if self.logger:
                self.logger.warning("Configuration web server not available")
            return False

        # Get the config server app and apply auth middleware before mounting
        config_app = self.config.server.app

        # Add auth middleware to config app
        config_app.add_middleware(AuthMiddleware, auth_manager=self.auth_manager)

        # Mount the config server app
        host = self.config.get_host()
        port = self.config.get_port()
        self.app.mount("/config", config_app)

        if self.logger:
            self.logger.info(
                f"Configuration web server mounted at http://{host}:{port}/config"
            )
        return True

    def _init_dashboard(self):
        """Initialize and mount dashboard if enabled."""
        if not self.config:
            if self.logger:
                self.logger.warning(
                    "Config manager not initialized, dashboard disabled"
                )
            return False

        if not self.config.get_dashboard_enabled():
            if self.logger:
                self.logger.info("Dashboard disabled in configuration")
            return False

        host = self.config.get_host()
        port = self.config.get_port()

        try:
            self.dashboard = DashboardAPI(
                logger=self.logger or logging.getLogger("nyaproxy"),
                port=port,
                enable_control=True,
            )

            # Set dependencies
            self.dashboard.set_metrics_collector(self.core.metrics_collector)
            self.dashboard.set_request_queue(self.core.request_queue)
            self.dashboard.set_config_manager(self.config)

            # Get the dashboard app and apply auth middleware before mounting
            dashboard_app = self.dashboard.app

            # Add auth middleware to dashboard app
            dashboard_app.add_middleware(AuthMiddleware, auth_manager=self.auth_manager)

            # Mount the dashboard app
            self.app.mount("/dashboard", dashboard_app, name="dashboard_app")

            if self.logger:
                self.logger.info(f"Dashboard mounted at http://{host}:{port}/dashboard")
            return True

        except Exception as e:
            error_msg = f"Failed to initialize dashboard: {str(e)}"
            if self.logger:
                self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _setup_proxy_routes(self):
        """Set up routes for proxying requests"""
        if self.logger:
            self.logger.info("Setting up generic proxy routes")

        @self.app.get("/api/{path:path}", name="proxy_get")
        async def proxy_get_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.auth_manager.verify_api_key),
        ):
            return await self.generic_proxy_request(request)

        @self.app.post("/api/{path:path}", name="proxy_post")
        async def proxy_post_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.auth_manager.verify_api_key),
        ):
            return await self.generic_proxy_request(request)

        @self.app.put("/api/{path:path}", name="proxy_put")
        async def proxy_put_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.auth_manager.verify_api_key),
        ):
            return await self.generic_proxy_request(request)

        @self.app.delete("/api/{path:path}", name="proxy_delete")
        async def proxy_delete_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.auth_manager.verify_api_key),
        ):
            return await self.generic_proxy_request(request)

        @self.app.patch("/api/{path:path}", name="proxy_patch")
        async def proxy_patch_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.auth_manager.verify_api_key),
        ):
            return await self.generic_proxy_request(request)

        @self.app.head("/api/{path:path}", name="proxy_head")
        async def proxy_head_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.auth_manager.verify_api_key),
        ):
            return await self.generic_proxy_request(request)

        @self.app.options("/api/{path:path}", name="proxy_options")
        async def proxy_options_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.auth_manager.verify_api_key),
        ):
            return await self.generic_proxy_request(request)

    async def shutdown(self):
        """Clean up resources on shutdown."""
        if self.logger:
            self.logger.info("Shutting down NyaProxy")

        # Close proxy handler client
        if self.core:
            await self.core.request_executor.close()


# Global app variable for ASGI
app = None


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="NyaProxy - API proxy with dynamic token rotation"
    )
    parser.add_argument("--config", "-c", help="Path to configuration file")
    parser.add_argument("--port", "-p", type=int, help="Port to run the proxy on")
    parser.add_argument("--host", "-H", type=str, help="Host to run the proxy on")
    return parser.parse_args()


def reload_server():
    """
    Reload the uvicorn server programmatically.
    This can be called from other parts of the application to trigger a server reload.

    Note: This should be used carefully as it will interrupt all current connections.
    """
    try:
        import signal

        print("[NyaProxy] Configuration changed.. Attempting to reload server...")

        # Send SIGUSR1 signal to the main process which uvicorn's reloader watches for
        os.kill(os.getpid(), signal.SIGUSR1)
        exit(0)

        # Log the reload attempt
        print("[NyaProxy] Server reload signal sent")

        return True
    except Exception as e:
        error_msg = f"Failed to reload server: {str(e)}"
        logging.error(error_msg)
        return False


def create_app(config_path=None):
    """Create the FastAPI application with the NyaProxy app"""
    global app
    nya_proxy_app = NyaProxyApp(config_path)
    app = nya_proxy_app.app
    app.router.lifespan_context = nya_proxy_app.lifespan
    return app


def main():
    """Main entry point for NyaProxy."""
    args = parse_args()

    # Priority order for configuration:
    # 1. Command line arguments (--host, --port, --config)
    # 2. Environment variables (CONFIG_PATH, NYA_PROXY_HOST, NYA_PROXY_PORT)
    # 3. Configuration file (DEFAULT_CONFIG_PATH)
    # 4. Default values (DEFAULT_HOST, DEFAULT_PORT)

    config_path_abs = args.config or os.environ.get("CONFIG_PATH")
    host = args.host or os.environ.get("NYA_PROXY_HOST")
    port = args.port or os.environ.get("NYA_PROXY_PORT")

    import importlib.resources as pkg_resources

    import nya_proxy

    if not config_path_abs:
        # Create copies of the default config and schema in current directory
        import shutil

        cwd = os.getcwd()
        config_path_abs = os.path.join(cwd, DEFAULT_CONFIG_NAME)

        # if config file does not exist, copy the default config from package resources to current directory
        if not os.path.exists(config_path_abs):
            with pkg_resources.path(nya_proxy, DEFAULT_CONFIG_NAME) as default_config:
                shutil.copy(default_config, config_path_abs)
            print(
                f"No config file provided, create default configuration at {config_path_abs}"
            )

    try:

        config = None
        config_path_rel = os.path.relpath(config_path_abs, os.getcwd())

        print(f"Loading configuration from {config_path_abs}, cwd: {os.getcwd()}")
        # load validation schema from package resources
        with pkg_resources.path(nya_proxy, DEFAULT_SCHEMA_NAME) as default_schema:
            config = ConfigAPI(config_path_abs, default_schema)

        if not host:
            host = config.get_str("nya_proxy.host", DEFAULT_HOST)
        if not port:
            port = config.get_int("nya_proxy.port", DEFAULT_PORT)

        print(f"Configuration loaded from {config_path_abs}")

    except Exception as e:
        print(f"Error loading configuration: {str(e)}, invalid config file or schema.")
        sys.exit(1)

    # Create the app here instead of importing a global
    app_instance = create_app(config_path_abs)

    # Run the server
    uvicorn.run(
        app_instance,
        host=host,
        port=int(port),
        # reload=True,
        # reload_includes=[config_path_rel],  # Reload on config changes
    )


if __name__ == "__main__":
    main()
