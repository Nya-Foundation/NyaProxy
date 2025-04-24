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
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from .config_manager import ConfigAPI, ConfigManager
from .dashboard import DashboardAPI
from .logger import setup_logger
from .core import NyaProxyCore
from .models import NyaRequest


class RootPathMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, root_path: str):
        super().__init__(app)
        self.root_path = root_path

    async def dispatch(self, request: Request, call_next):
        request.scope["root_path"] = self.root_path
        return await call_next(request)


class NyaProxyApp:
    """Main NyaProxy application class"""

    def __init__(self):
        """Initialize the NyaProxy application"""
        # Create FastAPI app
        self.app = FastAPI(
            title="NyaProxy",
            description="A simple low-level API proxy with dynamic token rotation and load balancing",
            version="0.1.0",
        )

        # Initialize instance variables
        self.config = None
        self.logger = None
        self.core = None
        self.metrics_collector = None
        self.request_queue = None
        self.api_key_header = APIKeyHeader(name="Authorization", auto_error=False)
        self.dashboard = None

        # Set up application components
        self._setup_middleware()
        self._setup_routes()

    @contextlib.asynccontextmanager
    async def lifespan(self, app):
        """Lifespan context manager for FastAPI"""
        await self.initialize_proxy_services()
        yield
        await self.shutdown()

    def _setup_middleware(self):
        """Set up FastAPI middleware"""
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        """Set up FastAPI routes"""

        @self.app.get("/", include_in_schema=False)
        async def root():
            """Root endpoint"""
            return JSONResponse(
                content={"message": "Welcome to NyaProxy!"},
                status_code=200,
            )

        # Info endpoint
        @self.app.get("/info")
        async def info(api_key_valid: bool = Depends(self.verify_api_key)):
            """Get information about the proxy."""
            if not api_key_valid:
                return JSONResponse(
                    status_code=403, content={"error": "Invalid API key"}
                )

            apis = {}
            if self.config:
                for name, config in self.config.get_apis().items():
                    apis[name] = {
                        "name": config.get("name", name),
                        "endpoint": config.get("endpoint", ""),
                        "aliases": config.get("aliases", []),
                    }

            return {"status": "running", "version": "0.1.0", "apis": apis}

    async def verify_api_key(
        self,
        api_key: str = Depends(APIKeyHeader(name="Authorization", auto_error=False)),
    ):
        """Verify the API key if one is configured."""
        configured_key = self.config.get_api_key() if self.config else ""

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

    async def generic_proxy_request(
        self, request: Request, path: str, api_key_valid: bool
    ):
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
            self._init_config()
            self._init_logging()
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

    def _init_config(self):
        """Initialize configuration manager."""
        config_path = os.environ.get("CONFIG_PATH", "config.yaml")
        self.config = ConfigManager(config_file=config_path, logger=self.logger)

        if self.logger:
            self.logger.info(f"Configuration loaded from {config_path}")
        return self.config

    def _init_logging(self):
        """Initialize logging."""
        log_config = self.config.get_logging_config()
        self.logger = setup_logger(log_config)
        self.logger.info(
            f"Logging initialized with level {log_config.get('level', 'INFO')}"
        )
        return self.logger

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

        if not hasattr(self.config, "web_server") or not hasattr(
            self.config.web_server, "app"
        ):
            if self.logger:
                self.logger.warning("Configuration web server not available")
            return False

        # Mount the config server app
        host = self.config.get_host()
        port = self.config.get_port()

        nekoconf = self.config.web_server.app
        self.app.mount("/config", nekoconf)

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

            # Mount the dashboard app
            self.app.mount("/dashboard", self.dashboard.app, name="dashboard_app")

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
            api_key_valid: bool = Depends(self.verify_api_key),
        ):
            return await self.generic_proxy_request(request, path, api_key_valid)

        @self.app.post("/api/{path:path}", name="proxy_post")
        async def proxy_post_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.verify_api_key),
        ):
            return await self.generic_proxy_request(request, path, api_key_valid)

        @self.app.put("/api/{path:path}", name="proxy_put")
        async def proxy_put_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.verify_api_key),
        ):
            return await self.generic_proxy_request(request, path, api_key_valid)

        @self.app.delete("/api/{path:path}", name="proxy_delete")
        async def proxy_delete_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.verify_api_key),
        ):
            return await self.generic_proxy_request(request, path, api_key_valid)

        @self.app.patch("/api/{path:path}", name="proxy_patch")
        async def proxy_patch_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.verify_api_key),
        ):
            return await self.generic_proxy_request(request, path, api_key_valid)

        @self.app.head("/api/{path:path}", name="proxy_head")
        async def proxy_head_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.verify_api_key),
        ):
            return await self.generic_proxy_request(request, path, api_key_valid)

        @self.app.options("/api/{path:path}", name="proxy_options")
        async def proxy_options_request(
            request: Request,
            path: str,
            api_key_valid: bool = Depends(self.verify_api_key),
        ):
            return await self.generic_proxy_request(request, path, api_key_valid)

    async def shutdown(self):
        """Clean up resources on shutdown."""
        if self.logger:
            self.logger.info("Shutting down NyaProxy")

        # Close proxy handler client
        if self.core:
            await self.core.request_executor.close()


# Create a single instance of the application
nya_proxy_app = NyaProxyApp()
app = nya_proxy_app.app
app.router.lifespan_context = nya_proxy_app.lifespan


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

        # Send SIGUSR1 signal to the main process which uvicorn's reloader watches for
        os.kill(os.getpid(), signal.SIGUSR1)
        exit(0)

        # Log the reload attempt
        print("[NyaProxy] Server reload signal sent")

        return True
    except Exception as e:
        error_msg = f"Failed to reload server: {str(e)}"
        if nya_proxy_app.logger:
            nya_proxy_app.logger.error(error_msg)
        else:
            logging.error(error_msg)
        return False


def main():
    """Main entry point for NyaProxy."""
    args = parse_args()

    # Set config path from args
    if args.config:
        os.environ["CONFIG_PATH"] = args.config

    config_path = os.environ.get("CONFIG_PATH", "config.yaml")

    # Initialize configuration to get port
    port = 8080
    host = "0.0.0.0"
    try:
        config = ConfigAPI(config_path)
        port = config.get_int("nya_proxy.port", 8080)
        host = config.get_str("nya_proxy.host", "0.0.0.0")

        print(f"Configuration loaded from {config_path}")

    except Exception as e:
        print(f"Error loading configuration: {str(e)}")
        sys.exit(1)

    # Override port with command line argument if provided
    if args.port:
        port = args.port
        print(f"Port overridden to {port}")

    if args.host:
        host = args.host
        print(f"Host overridden to {host}")

    # Run the server
    uvicorn.run(
        "nya_proxy.app:app",
        host=host,
        port=port,
        reload=True,
        reload_includes=[config_path],  # Reload on config changes
    )


if __name__ == "__main__":
    main()
