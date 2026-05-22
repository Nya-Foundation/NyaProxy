"""
Dashboard API for NyaProxy.

``DashboardAPI`` owns the FastAPI app and the (late-bound) dependencies
the routes need. The routes themselves live in ``nya.dashboard.routes``;
this module only constructs the app and wires those route groups in.
"""

import importlib.resources
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .._version import __version__
from .routes import (
    register_control_routes,
    register_history_routes,
    register_metrics_routes,
    register_page_routes,
    register_queue_routes,
)

if TYPE_CHECKING:
    from ..config.manager import ConfigManager
    from ..core.queue import RequestQueue
    from ..services.metrics import MetricsCollector


class DashboardAPI:
    """
    Dashboard API for monitoring and controlling NyaProxy.
    """

    def __init__(
        self,
        port: int = 8080,
        enable_control: bool = True,
        metrics_path: str = "./.metrics",
    ):
        """
        Initialize the dashboard API.

        Args:
            port: Port to run the dashboard on
            enable_control: Whether to enable control API routes
            metrics_path: Path to store metrics data
        """
        self.port = port
        self.enable_control = enable_control
        self.metrics_path = metrics_path

        # Set up template / static directories.
        self.www_dir = self.get_html_directory()
        static_dir = self.www_dir / "static"
        os.makedirs(static_dir / "css", exist_ok=True)
        os.makedirs(static_dir / "js", exist_ok=True)

        # Dependencies, wired in later via the set_* methods.
        self.metrics_collector: Optional["MetricsCollector"] = None
        self.request_queue: Optional["RequestQueue"] = None
        self.config_manager: Optional["ConfigManager"] = None

        self.app = FastAPI(
            title="NyaProxy Dashboard",
            description="Dashboard for monitoring and controlling NyaProxy",
            version=__version__,
        )

        if static_dir.exists():
            self.app.mount(
                "/static",
                StaticFiles(directory=str(static_dir)),
                name="static",
            )
        else:
            logger.warning(f"Static directory not found at {static_dir}")

        self._register_routes()

    def _register_routes(self) -> None:
        """Wire every route group into the FastAPI app."""
        register_page_routes(self.app, self)
        register_metrics_routes(self.app, self)
        register_history_routes(self.app, self)
        register_queue_routes(self.app, self)
        if self.enable_control:
            register_control_routes(self.app, self)

    def get_html_directory(self) -> Path:
        """
        Get the html directory path.
        """
        try:
            # Try the new-style importlib.resources API
            return Path(str(importlib.resources.files("nya") / "html"))
        except (AttributeError, ImportError):
            # Fall back to package-relative resolution for older Python versions
            return Path(__file__).parent / "html"

    def set_metrics_collector(self, metrics_collector: "MetricsCollector") -> None:
        """Set the metrics collector."""
        self.metrics_collector = metrics_collector

    def set_request_queue(self, request_queue: "RequestQueue") -> None:
        """Set the request queue."""
        self.request_queue = request_queue

    def set_config_manager(self, config_manager: "ConfigManager") -> None:
        """Set the config manager."""
        self.config_manager = config_manager

    async def start_background(self, host: str = "0.0.0.0") -> None:
        """Start the dashboard server in the background."""
        config = uvicorn.Config(
            app=self.app, host=host, port=self.port, log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

    def run(self, host: str = "0.0.0.0") -> None:
        """Run the dashboard server."""
        uvicorn.run(self.app, host=host, port=self.port, log_config=None)
