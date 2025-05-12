#!/usr/bin/env python3
"""
NyaProxy - A simple low-level API proxy with dynamic token rotation.
"""
import argparse
import contextlib
import logging
import os

import uvicorn
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from .. import __version__
from ..common.constants import (
    DEFAULT_CONFIG_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCHEMA_NAME,
)
from ..common.logger import getLogger
from ..common.models import NyaRequest
from ..config.manager import ConfigManager
from ..core.factory import ServiceFactory
from ..core.proxy import NyaProxyCore
from ..dashboard.api import DashboardAPI
from .auth import AuthManager, AuthMiddleware


class RootPathMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, root_path: str):
        super().__init__(app)
        self.root_path = root_path

    async def dispatch(self, request: Request, call_next):
        request.scope["root_path"] = self.root_path
        return await call_next(request)


class NyaProxyApp:
    """Main NyaProxy application class"""

    def __init__(self, config_path=None, schema_path=None):
        """Initialize the NyaProxy application"""

        # Initialize instance variables
        self.config: ConfigManager = None
        self.logger: logging.Logger = None

        self._init_config(config_path=config_path, schema_path=schema_path)
        self.auth = AuthManager()

        self.factory = None
        self.core = None
        self.dashboard = None

        # Create FastAPI app with middleware pre-configured
        self.app = self._create_main_app()

    def _init_config(self, config_path=None, schema_path=None) -> None:
        """Initialize the configuration manager"""

        config_path = config_path or os.environ.get("CONFIG_PATH")
        schema_path = schema_path or os.environ.get("SCHEMA_PATH")
        remote_url = os.environ.get("CONFIG_REMOTE_URL")
        remote_api_key = os.environ.get("CONFIG_REMOTE_API_KEY")

        # if not config_path:
        #     raise ValueError("Configuration path is required")

        # if not schema_path:
        #     raise ValueError("Schema path is required")

        config = ConfigManager(
            config_path=config_path,
            schema_path=schema_path,
            remote_url=remote_url or None,
            remote_api_key=remote_api_key or None,
        )
        if not config:
            raise RuntimeError("Failed to initialize config manager")
        self.config = config

    def _init_auth(self):
        """Initialize the authentication manager"""
        auth = AuthManager(
            config=self.config,
            logger=self.logger,
        )
        if not auth:
            raise RuntimeError("Failed to initialize auth manager")
        return auth

    def _create_main_app(self):
        """Create the main FastAPI application with middleware pre-configured"""
        app = FastAPI(
            title="NyaProxy",
            description="A simple low-level API proxy with dynamic token rotation and load balancing",
            version=__version__,
        )

        allow_origins = self.config.get_cors_allow_origins()
        allow_methods = self.config.get_cors_allow_methods()
        allow_headers = self.config.get_cors_allow_headers()
        allow_credentials = self.config.get_cors_allow_credentials()

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=allow_credentials,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
        )

        if not self.auth:
            raise RuntimeError(
                "Auth manager must be initialized before adding middleware"
            )

        # Add auth middleware
        app.add_middleware(AuthMiddleware, auth=self.auth)

        # Set up basic routes
        self._setup_routes(app)

        return app

    @contextlib.asynccontextmanager
    async def lifespan(self, app):
        """Lifespan context manager for FastAPI"""
        await self.init_nya_services()
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
        async def info():
            """Get information about the proxy."""
            apis = {}
            if self.config:
                for name, config in self.config.get_apis().items():
                    apis[name] = {
                        "name": config.get("name", name),
                        "endpoint": config.get("endpoint", ""),
                        "aliases": config.get("aliases", []),
                    }

            return {"status": "running", "version": __version__, "apis": apis}

    async def generic_proxy_request(self, request: Request):
        """Generic handler for all proxy requests."""
        if not self.core:
            return JSONResponse(
                status_code=503,
                content={"error": "Proxy service is starting up or unavailable"},
            )

        req = await NyaRequest.from_request(request)
        return await self.core.handle_request(req)

    async def init_nya_services(self):
        """Initialize services for NyaProxy"""
        try:

            self._init_logging()
            # Create FastAPI app with middleware pre-configured

            self._init_factory()

            self._init_core()
            # Mount sub-applications for NyaProxy if available
            self._init_config_server()

            # Initialize dashboard if enabled
            self._init_dashboard()
            # Initialize proxy routes last to act as a catch-all
            self._setup_proxy_routes()

        except Exception as e:
            self.logger.error(f"Error during startup: {str(e)}")
            raise

    def _init_logging(self) -> None:
        """Initialize logging."""
        log_config = self.config.get_logging_config()
        logger = getLogger(name=__name__, log_config=log_config)
        logger.info(f"Logging initialized with level {log_config.get('level', 'INFO')}")

        self.logger = logger or logging.getLogger(__name__)

    def _init_factory(self) -> ServiceFactory:
        """Initialize service factory."""
        factory = ServiceFactory(config_manager=self.config, logger=self.logger)
        self.logger.info("Service factory initialized")
        self.factory = factory

    def _init_core(self) -> NyaProxyCore:
        """Initialize the core proxy handler."""
        if not self.config:
            raise RuntimeError(
                "Config manager must be initialized before proxy handler"
            )

        if not self.logger:
            logging.warning(
                "Logger not initialized, proxy handler will use default logging"
            )

        if not self.factory:
            raise RuntimeError("Service factory must be initialized before core")

        # Use the service factory to create the core
        core = NyaProxyCore(
            logger=self.logger, config=self.config, factory=self.factory
        )
        self.logger.info("Proxy handler initialized")
        self.core = core

    def _init_config_server(self):
        """Initialize and mount configuration web server if available."""
        if not self.config:
            self.logger.warning(
                "Config manager not initialized, config server disabled"
            )
            return False

        if not hasattr(self.config, "server") or not hasattr(self.config.server, "app"):
            self.logger.warning("Configuration web server not available")
            return False

        host = os.environ.get("NYA_SERVER_HOST") or self.config.get_host()
        port = os.environ.get("NYA_SERVER_PORT") or self.config.get_port()
        remote_url = os.environ.get("CONFIG_REMOTE_URL")

        if remote_url:
            self.logger.info(
                "Configuration web server disabled since remote config url is set"
            )
            return False

        # Get the config server app and apply auth middleware before mounting
        config_app = self.config.server.app

        # Add auth middleware to config app
        config_app.add_middleware(AuthMiddleware, auth=self.auth)

        # Mount the config server app
        self.app.mount("/config", config_app, name="config_app")

        self.logger.info(
            f"Configuration web server mounted at http://{host}:{port}/config"
        )
        return True

    def _init_dashboard(self):
        """Initialize and mount dashboard if enabled."""
        if not self.config:
            self.logger.warning("Config manager not initialized, dashboard disabled")
            return False

        if not self.config.get_dashboard_enabled():
            self.logger.info("Dashboard disabled in configuration")
            return False

        host = os.environ.get("NYA_SERVER_HOST") or self.config.get_host()
        port = os.environ.get("NYA_SERVER_PORT") or self.config.get_port()

        try:
            self.dashboard = DashboardAPI(
                logger=self.logger,
                port=port,
                enable_control=True,
            )

            # Set dependencies from the core
            self.dashboard.set_metrics_collector(self.core.metrics_collector)
            self.dashboard.set_request_queue(self.core.request_queue)
            self.dashboard.set_config_manager(self.config)

            # Get the dashboard app and apply auth middleware before mounting
            dashboard_app = self.dashboard.app

            # Add auth middleware to dashboard app
            dashboard_app.add_middleware(AuthMiddleware, auth=self.auth)

            # Mount the dashboard app
            self.app.mount("/dashboard", dashboard_app, name="dashboard_app")

            self.logger.info(f"Dashboard mounted at http://{host}:{port}/dashboard")
            return True

        except Exception as e:
            error_msg = f"Failed to initialize dashboard: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _setup_proxy_routes(self):
        """Set up routes for proxying requests"""
        if self.logger:
            self.logger.info("Setting up generic proxy routes")

        @self.app.get("/api/{path:path}", name="proxy_get")
        async def proxy_get_request(request: Request):
            return await self.generic_proxy_request(request)

        @self.app.post("/api/{path:path}", name="proxy_post")
        async def proxy_post_request(request: Request):
            return await self.generic_proxy_request(request)

        @self.app.put("/api/{path:path}", name="proxy_put")
        async def proxy_put_request(request: Request):
            return await self.generic_proxy_request(request)

        @self.app.delete("/api/{path:path}", name="proxy_delete")
        async def proxy_delete_request(request: Request):
            return await self.generic_proxy_request(request)

        @self.app.patch("/api/{path:path}", name="proxy_patch")
        async def proxy_patch_request(request: Request):
            return await self.generic_proxy_request(request)

        @self.app.head("/api/{path:path}", name="proxy_head")
        async def proxy_head_request(request: Request):
            return await self.generic_proxy_request(request)

        @self.app.options("/api/{path:path}", name="proxy_options")
        async def proxy_options_request(request: Request):
            #  hijack the options request to handle CORS preflight requests
            origin = request.headers.get("origin", "*")
            acr_headers = request.headers.get(
                "access-control-request-headers", "Content-Type, Authorization"
            )

            self.logger.debug(
                f"Handling CORS preflight request from {origin} with headers {request.headers}"
            )

            return Response(
                content="",
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Headers": acr_headers,
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS",
                    "Access-Control-Max-Age": "86400",
                },
            )

    async def shutdown(self):
        """Clean up resources on shutdown."""
        self.logger.info("Shutting down NyaProxy")

        # Close proxy handler client
        if self.core and hasattr(self.core, "request_executor"):
            await self.core.request_executor.close()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="NyaProxy - API proxy with dynamic token rotation"
    )
    parser.add_argument("--config", "-c", help="Path to configuration file")
    parser.add_argument("--port", "-p", type=int, help="Port to run the proxy on")
    parser.add_argument("--host", "-H", type=str, help="Host to run the proxy on")

    parser.add_argument(
        "--remote-url",
        "-r",
        type=str,
        help="Remote URL for the config server [optional]",
    )
    parser.add_argument(
        "--remote-api-key",
        "-k",
        type=str,
        help="API key for the remote config server [optional]",
    )

    parser.add_argument(
        "--version", action="version", version=f"NyaProxy {__version__}"
    )
    return parser.parse_args()


def create_app():
    """Create the FastAPI application with the NyaProxy app"""

    nya_proxy_app = NyaProxyApp()
    app = nya_proxy_app.app
    app.router.lifespan_context = nya_proxy_app.lifespan
    return app


def main():
    """Main entry point for NyaProxy."""
    args = parse_args()

    # Priority order for configuration:
    # 1. Command line arguments (--host, --port, --config)
    # 2. Environment variables (CONFIG_PATH, NYA_SERVER_HOST, NYA_SERVER_PORT)
    # 3. Configuration file (DEFAULT_CONFIG_PATH)
    # 4. Default values (DEFAULT_HOST, DEFAULT_PORT)

    config_path_abs = args.config or os.environ.get("CONFIG_PATH")
    host = args.host or os.environ.get("NYA_SERVER_HOST")
    port = args.port or os.environ.get("NYA_SERVER_PORT")
    remote_url = args.remote_url or os.environ.get("CONFIG_REMOTE_URL")
    remote_api_key = args.remote_api_key or os.environ.get("CONFIG_REMOTE_API_KEY")
    schema_path = None

    import importlib.resources as pkg_resources

    import nya

    if not config_path_abs or not os.path.exists(config_path_abs):
        # Create copies of the default config and schema in current directory

        cwd = os.getcwd()
        config_path_abs = os.path.join(cwd, DEFAULT_CONFIG_NAME)

        # if config file does not exist, copy the default config from package resources to current directory
        if not os.path.exists(config_path_abs):
            import shutil

            # Import the nya module to access the default config file
            with pkg_resources.path(nya, DEFAULT_CONFIG_NAME) as default_config:
                shutil.copy(default_config, config_path_abs)
            print(
                f"[Warning] No config file provided, create default configuration at {config_path_abs}"
            )

    with pkg_resources.path(nya, DEFAULT_SCHEMA_NAME) as default_schema:
        schema_path = str(default_schema)

    config_path_rel = os.path.relpath(config_path_abs, os.getcwd())

    # load the config manager to get the host and port
    if port is None or host is None:
        config = ConfigManager(
            config_path=config_path_abs,
            schema_path=schema_path,
            remote_url=remote_url,
            remote_api_key=remote_api_key,
        )

        host = config.get_host() or DEFAULT_HOST
        port = config.get_port() or DEFAULT_PORT

    os.environ["CONFIG_PATH"] = config_path_abs
    os.environ["SCHEMA_PATH"] = schema_path
    os.environ["NYA_SERVER_HOST"] = host
    os.environ["NYA_SERVER_PORT"] = str(port)

    if remote_url:
        os.environ["CONFIG_REMOTE_URL"] = remote_url
    if remote_api_key:
        os.environ["CONFIG_REMOTE_API_KEY"] = remote_api_key

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            "uvicorn": {"level": "INFO", "propagate": True},
            "uvicorn.access": {"level": "INFO", "propagate": True},
            "uvicorn.error": {"level": "INFO", "propagate": True},
        },
    }

    # Run the server
    uvicorn.run(
        "nya.server.app:create_app",
        host=host,
        port=int(port),
        reload=True,
        reload_includes=[config_path_rel],  # Reload on config changes
        timeout_keep_alive=15,
        limit_concurrency=1000,
        log_config=log_config,
    )


if __name__ == "__main__":
    main()
