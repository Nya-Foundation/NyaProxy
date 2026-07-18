#!/usr/bin/env python3
"""
NyaProxy - A lightweight, header-based API proxy for managing authenticated upstream services.
"""

import argparse
import contextlib
import os
import sys

import uvicorn
from fastapi import FastAPI, Request
from loguru import logger
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

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
from ..services.metrics import PROMETHEUS_CONTENT_TYPE, MetricsCollector
from .auth import AuthManager, AuthMiddleware

logger.remove()
logger.add(sys.stderr, level="INFO")


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

        self.core = None
        self.metrics_collector = None
        self.auth = AuthManager(config=self.config)
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
        remote_app_name = os.environ.get("REMOTE_CONFIG_APP_NAME", "default")

        try:
            config = ConfigManager(
                config_path=config_path,
                schema_path=schema_path,
                remote_url=remote_url or None,
                remote_api_key=remote_api_key or None,
                remote_app_name=remote_app_name or None,
                callback=trigger_reload,
            )
        except Exception as e:
            logger.error(f"Failed to initialize config manager: {e}")
            raise

        self.config = config

    def _create_main_app(self):
        """
        Create the main FastAPI application with middleware pre-configured
        """
        app = FastAPI(
            title="NyaProxy",
            description="A lightweight, header-based API proxy for managing authenticated upstream services",
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

        # Liveness endpoint for load balancers / container orchestrators
        @app.get("/health", include_in_schema=False)
        async def health():
            return {"status": "ok"}

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

        # Prometheus metrics exposition endpoint
        @app.get("/metrics", include_in_schema=False)
        async def metrics():
            """
            Expose all metrics in the Prometheus exposition format.
            """
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )
            return Response(
                content=self.metrics_collector.render_prometheus(),
                media_type=PROMETHEUS_CONTENT_TYPE,
            )

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

    def _server_address(self):
        """
        Resolve the effective host/port, preferring the launcher's env overrides.
        """
        host = os.environ.get("SERVER_HOST") or self.config.get_host()
        port = os.environ.get("SERVER_PORT") or self.config.get_port()
        return host, port

    def _warn_if_unauthenticated(self):
        host, _ = self._server_address()
        if self.auth.is_auth_disabled():
            if host not in ("127.0.0.1", "localhost", "::1"):
                logger.warning(
                    f"server.api_key is not set and NyaProxy is bound to {host}: "
                    "the proxy, dashboard, and config UI are reachable WITHOUT authentication. "
                    "Set server.api_key or bind to 127.0.0.1."
                )
            return

        # Auth is on, but a blank first entry (an unset ${VAR}, a stray '-' in
        # YAML) leaves no master key. Proxying still works; the dashboard and
        # config UI are locked, which is safe but baffling without a warning.
        if self.auth.master_key() is None:
            logger.warning(
                "The first entry of server.api_key is empty, so no master key is "
                "configured: the dashboard and config UI will reject every key. "
                "Proxy traffic still works with the remaining keys."
            )

    async def init_nya_services(self):
        """
        Initialize services for NyaProxy
        """
        try:
            self.init_logging()
            self._warn_if_unauthenticated()
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
        if not log_config.get("enabled", True):
            return

        logger.add(
            sys.stderr,
            level=log_config.get("level", "INFO").upper(),
        )
        logger.add(
            log_config.get("log_file", "app.log"),
            level=log_config.get("level", "INFO").upper(),
            rotation="10 MB",
            retention=5,
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

        host, port = self._server_address()
        remote_url = os.environ.get("REMOTE_CONFIG_URL")

        if remote_url:
            logger.info(
                "Configuration web server disabled since remote config url is set"
            )
            return False

        # Get the config server app and apply auth middleware before mounting
        config_app = self.config.server.app

        # Mount the config server app
        self.app.mount("/config", config_app, name="config_app")

        logger.info(
            f"Configuration web server mounted at http://{host}:{port}/config/ui"
        )
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

        host, port = self._server_address()

        try:
            self.dashboard = DashboardAPI(enable_control=True)

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

        @self.app.api_route(
            "/api/{path:path}",
            methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
            name="proxy_request",
        )
        async def proxy_request(request: Request):
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
        "--no-reload",
        action="store_true",
        help="Disable the file-watch supervisor; config changes then require a manual restart",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration and exit without starting the server",
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
    Trigger a reload of the application by touching the file uvicorn watches.
    """
    if os.environ.get("DISABLE_HOT_RELOAD"):
        logger.warning(
            "Configuration changed but hot-reload is disabled; "
            "restart NyaProxy to apply the new settings"
        )
        return
    logger.info("Configuration changed, triggering reload...")
    with open(WATCH_FILE, "a") as f:
        f.write("reload\n")


def main():
    """
    Main entry point for NyaProxy.
    """
    args = parse_args()

    # Bind address priority: CLI, environment, built-in loopback default.
    # The configuration source is selected independently by CLI/environment.

    requested_config = args.config or os.environ.get("CONFIG_PATH")
    host = args.host or os.environ.get("SERVER_HOST") or DEFAULT_HOST
    port = args.port or os.environ.get("SERVER_PORT") or DEFAULT_PORT
    remote_url = args.remote_url or os.environ.get("REMOTE_CONFIG_URL")
    remote_api_key = args.remote_api_key or os.environ.get("REMOTE_CONFIG_API_KEY")
    remote_app_name = args.remote_app_name or os.environ.get("REMOTE_CONFIG_APP_NAME")
    config_path = requested_config
    schema_path = None

    import importlib.resources as pkg_resources

    import nya

    with pkg_resources.path(nya, DEFAULT_SCHEMA_NAME) as default_schema:
        schema_path = str(default_schema)

    check_config = getattr(args, "check_config", False)

    if requested_config and not os.path.isfile(requested_config) and not remote_url:
        raise SystemExit(f"Configuration file not found: {requested_config}")

    if check_config and not config_path and not remote_url:
        candidate = os.path.join(os.getcwd(), DEFAULT_CONFIG_NAME)
        if not os.path.isfile(candidate):
            raise SystemExit(
                "No configuration file to validate; pass --config or create config.yaml"
            )
        config_path = candidate

    # Create a starter config only for a normal first run with no source selected.
    if not check_config and not config_path and not remote_url:
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
    if args.no_reload:
        os.environ["DISABLE_HOT_RELOAD"] = "1"

    if check_config:
        ConfigManager(
            config_path=config_path,
            schema_path=schema_path,
            remote_url=remote_url or None,
            remote_api_key=remote_api_key or None,
            remote_app_name=remote_app_name or None,
        )
        source = remote_url or config_path
        print(f"Configuration valid: {source}")
        return

    uvicorn.run(
        "nya.server.app:create_app",
        host=host,
        port=int(port),
        reload=not args.no_reload,
        reload_includes=None if args.no_reload else [WATCH_FILE],
        timeout_keep_alive=30,
        server_header=False,
        # Forwarded client addresses are resolved by NyaProxy after checking
        # server.trusted_proxies. Letting Uvicorn do this first would allow a
        # direct client to influence request.client.host.
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
