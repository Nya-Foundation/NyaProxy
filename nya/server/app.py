#!/usr/bin/env python3
"""
NyaProxy - A simple low-level API proxy with dynamic token rotation.
"""


import argparse
import contextlib
import os
import sys

import uvicorn
from fastapi import FastAPI, Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from .. import __version__
from ..common.constants import (
    DEFAULT_CONFIG_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCHEMA_NAME,
    WATCH_FILE,
)
from ..common.models import ProxyRequest
from ..config.manager import ConfigManager
from ..core.proxy import NyaProxyCore
from ..dashboard.api import DashboardAPI
from ..services.metrics import MetricsCollector
from .auth import AuthManager, AuthMiddleware

logger.remove()
logger.add(sys.stderr, level="INFO")


class RootPathMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, root_path: str):
        super().__init__(app)
        self.root_path = root_path

    async def dispatch(self, request: Request, call_next):
        request.scope["root_path"] = self.root_path
        return await call_next(request)


class NyaProxyApp:
    """
    Main NyaProxy application class
    """

    def __init__(self, config_path=None, schema_path=None):
        """
        Initialize the NyaProxy application
        """

        # Initialize instance variables
        self.config: ConfigManager = None

        self._init_config(config_path=config_path, schema_path=schema_path)
        self.auth = AuthManager()

        self.core = None
        self.dashboard = None

        # Create FastAPI app with middleware pre-configured
        self.app = self._create_main_app()

    def _init_config(self, config_path=None, schema_path=None) -> None:
        """
        Initialize the configuration manager
        """

        config_path = config_path or os.environ.get("CONFIG_PATH")
        schema_path = schema_path or os.environ.get("SCHEMA_PATH")
        remote_url = os.environ.get("REMOTE_CONFIG_URL")
        remote_api_key = os.environ.get("REMOTE_CONFIG_API_KEY")
        remote_app_name = os.environ.get("REMOTE_CONFIG_APP_NAME")

        config = ConfigManager(
            config_path=config_path,
            schema_path=schema_path,
            remote_url=remote_url or None,
            remote_api_key=remote_api_key or None,
            remote_app_name=remote_app_name or None,
            callback=trigger_reload,
        )
        if not config:
            raise RuntimeError("Failed to initialize config manager")
        self.config = config

    def _init_auth(self):
        """
        Initialize the authentication manager
        """
        auth = AuthManager(
            config=self.config,
        )
        if not auth:
            raise RuntimeError("Failed to initialize auth manager")
        return auth

    def _create_main_app(self):
        """
        Create the main FastAPI application with middleware pre-configured
        """
        app = FastAPI(
            title="NyaProxy",
            description="A simple low-level API proxy with dynamic token rotation and load balancing",
            lifespan=self.lifespan,
            version=__version__,
        )

        allow_origins = self.config.get_cors_allow_origins()
        allow_methods = self.config.get_cors_allow_methods()
        allow_headers = self.config.get_cors_allow_headers()
        allow_credentials = self.config.get_cors_allow_credentials()

        logger.info(
            f"CORS settings: origins={allow_origins}, methods={allow_methods}, headers={allow_headers}, credentials={allow_credentials}"
        )

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
        self.setup_routes(app)

        return app

    @contextlib.asynccontextmanager
    async def lifespan(self, app):
        """
        Lifespan context manager for FastAPI
        """
        logger.info("Starting NyaProxy...")
        await self.init_nya_services()
        yield
        logger.info("NyaProxy is shutting down...")
        await self.shutdown()

    def setup_routes(self, app):
        """
        Set up FastAPI routes
        """

        @app.get("/", include_in_schema=False)
        async def root():
            """
            Root endpoint
            """
            return JSONResponse(
                content={"message": "Welcome to NyaProxy!"},
                status_code=200,
            )

        # Info endpoint
        @app.get("/info")
        async def info():
            """
            Get information about the proxy.
            """
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
        """
        Generic handler for all proxy requests.
        """
        if not self.core:
            return JSONResponse(
                status_code=503,
                content={"error": "Proxy service is starting up or unavailable"},
            )

        req = await ProxyRequest.from_request(request)
        return await self.core.handle_request(req)

    async def init_nya_services(self):
        """
        Initialize services for NyaProxy
        """
        try:

            self.init_logging()
            # Create FastAPI app with middleware pre-configured

            # Initialize metrics collector
            self.init_metrics_collector()

            self.init_core()
            # Mount sub-applications for NyaProxy if available
            self.init_config_ui()

            # Initialize dashboard if enabled
            self.init_dashboard()
            # Initialize proxy routes last to act as a catch-all
            self.setup_proxy_routes()

        except Exception as e:
            logger.error(f"Error during startup: {str(e)}")
            raise

    def init_logging(self) -> None:
        """
        Initialize logging.
        """
        log_config = self.config.get_logging_config()
        logger.remove()  # Remove default logger
        logger.add(
            sys.stderr,
            level=log_config.get("level", "INFO").upper(),
        )
        logger.add(
            log_config.get("log_file", "app.log"),
            level=log_config.get("level", "INFO").upper(),
        )

    def init_metrics_collector(self) -> None:
        """
        Initialize metrics collector.
        """
        self.metrics_collector = MetricsCollector()

    def init_core(self) -> NyaProxyCore:
        """
        Initialize the core proxy handler.
        """
        if not self.config:
            raise RuntimeError(
                "Config manager must be initialized before proxy handler"
            )

        # Use the service factory to create the core
        core = NyaProxyCore(
            config=self.config,
            metrics_collector=self.metrics_collector,
        )
        logger.info("Proxy handler initialized")
        self.core = core

    def init_config_ui(self):
        """
        Initialize and mount configuration web server if available.
        """
        if not self.config:
            logger.warning("Config manager not initialized, config server disabled")
            return False

        if not hasattr(self.config, "server") or not hasattr(self.config.server, "app"):
            logger.warning("Configuration web server not available")
            return False

        host = os.environ.get("SERVER_HOST") or self.config.get_host()
        port = os.environ.get("SERVER_PORT") or self.config.get_port()
        remote_url = os.environ.get("REMOTE_CONFIG_URL")

        if remote_url:
            logger.info(
                "Configuration web server disabled since remote config url is set"
            )
            return False

        # Get the config server app and apply auth middleware before mounting
        config_app = self.config.server.app

        # Add auth middleware to config app
        config_app.add_middleware(AuthMiddleware, auth=self.auth)

        # Mount the config server app
        self.app.mount("/config", config_app, name="config_app")

        logger.info(f"Configuration web server mounted at http://{host}:{port}/config")
        return True

    def init_dashboard(self):
        """
        Initialize and mount dashboard if enabled.
        """
        if not self.config:
            logger.warning("Config manager not initialized, dashboard disabled")
            return False

        if not self.config.get_dashboard_enabled():
            logger.info("Dashboard disabled in configuration")
            return False

        host = os.environ.get("SERVER_HOST") or self.config.get_host()
        port = os.environ.get("SERVER_PORT") or self.config.get_port()

        try:
            self.dashboard = DashboardAPI(
                port=port,
                enable_control=True,
            )

            # Set dependencies from the core
            self.dashboard.set_metrics_collector(self.metrics_collector)
            self.dashboard.set_request_queue(self.core.request_queue)
            self.dashboard.set_config_manager(self.config)

            # Get the dashboard app and apply auth middleware before mounting
            dashboard_app = self.dashboard.app

            # Add auth middleware to dashboard app
            dashboard_app.add_middleware(AuthMiddleware, auth=self.auth)

            # Mount the dashboard app
            self.app.mount("/dashboard", dashboard_app, name="dashboard_app")

            logger.info(f"Dashboard mounted at http://{host}:{port}/dashboard")
            return True

        except Exception as e:
            error_msg = f"Failed to initialize dashboard: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def setup_proxy_routes(self):
        """
        Set up routes for proxying requests
        """
        if logger:
            logger.info("Setting up generic proxy routes")

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

    async def shutdown(self):
        """
        Clean up resources on shutdown.
        """

        logger.info("Shutting down NyaProxy")

        # Close proxy handler client
        if self.core and hasattr(self.core, "request_executor"):
            try:
                await self.core.request_executor.close()
                logger.info("Request executor closed successfully")
            except Exception as e:
                logger.error(f"Error closing request executor: {e}")


def parse_args():
    """
    Parse command line arguments.
    """
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
        "--remote-app-name",
        "-a",
        type=str,
        help="Name of the remote application for config [optional]",
    )

    parser.add_argument(
        "--version", action="version", version=f"NyaProxy {__version__}"
    )
    return parser.parse_args()


def create_app():
    """
    Create the FastAPI application with the NyaProxy app
    """
    nya_proxy_app = NyaProxyApp()
    return nya_proxy_app.app


def trigger_reload(**kwargs):
    """
    Trigger a reload of the application.
    """
    logger.info("[Info] Configuration changed, triggering reload...")
    if os.path.exists(WATCH_FILE):
        with open(WATCH_FILE, "a") as f:
            f.write("\n")  # Append a newline to trigger reload
    else:
        with open(WATCH_FILE, "w") as f:
            f.write("Reload triggered\n")  # Create the file if it doesn't exist


def main():
    """
    Main entry point for NyaProxy.
    """
    args = parse_args()

    # Priority order for configuration:
    # 1. Command line arguments (--host, --port, --config)
    # 2. Environment variables (CONFIG_PATH, SERVER_HOST, SERVER_PORT)
    # 3. Configuration file (DEFAULT_CONFIG_PATH)
    # 4. Default values (DEFAULT_HOST, DEFAULT_PORT)

    config_path = args.config or os.environ.get("CONFIG_PATH")
    host = args.host or os.environ.get("SERVER_HOST") or DEFAULT_HOST
    port = args.port or os.environ.get("SERVER_PORT") or DEFAULT_PORT
    remote_url = args.remote_url or os.environ.get("REMOTE_CONFIG_URL")
    remote_api_key = args.remote_api_key or os.environ.get("REMOTE_CONFIG_API_KEY")
    remote_app_name = args.remote_app_name or os.environ.get("REMOTE_CONFIG_APP_NAME")
    schema_path = None

    import importlib.resources as pkg_resources

    import nya

    with pkg_resources.path(nya, DEFAULT_SCHEMA_NAME) as default_schema:
        schema_path = str(default_schema)

    # Create copy of the default config to the current directory
    if (not config_path or not os.path.exists(config_path)) and not remote_url:
        cwd = os.getcwd()
        config_path = os.path.join(cwd, DEFAULT_CONFIG_NAME)

        # if config file does not exist, copy the default config from package resources to current directory
        if not os.path.exists(config_path):
            import shutil

            # Import the nya module to access the default config file
            with pkg_resources.path(nya, DEFAULT_CONFIG_NAME) as default_config:
                shutil.copy(default_config, config_path)
            logger.warning(
                f"No config file provided, create default configuration at {config_path}"
            )

    os.environ["SCHEMA_PATH"] = schema_path
    os.environ["SERVER_HOST"] = host
    os.environ["SERVER_PORT"] = str(port)

    if config_path:
        os.environ["CONFIG_PATH"] = config_path
    if remote_url:
        os.environ["REMOTE_CONFIG_URL"] = remote_url
    if remote_api_key:
        os.environ["REMOTE_CONFIG_API_KEY"] = remote_api_key
    if remote_app_name:
        os.environ["REMOTE_CONFIG_APP_NAME"] = remote_app_name

    uvicorn.run(
        "nya.server.app:create_app",
        host=host,
        port=int(port),
        reload=True,
        reload_includes=[WATCH_FILE],
        timeout_keep_alive=30,
        server_header=False,
    )


if __name__ == "__main__":
    main()
