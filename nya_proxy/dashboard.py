"""
Dashboard API for NyaProxy.
"""

import importlib.resources
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .metrics import MetricsCollector

if TYPE_CHECKING:
    from .config_manager import ConfigManager
    from .request_queue import RequestQueue


class DashboardAPI:
    """
    Dashboard API for monitoring and controlling NyaProxy.
    """

    def __init__(
        self,
        logger: logging.Logger,
        port: int = 8082,
        enable_control: bool = True,
        metrics_path: str = "./.metrics",
    ):
        """
        Initialize the dashboard API.

        Args:
            logger: Logger instance
            port: Port to run the dashboard on
            enable_control: Whether to enable control API routes
            metrics_path: Path to store metrics data
        """
        self.logger = logger
        self.port = port
        self.enable_control = enable_control
        self.metrics_path = metrics_path

        # Set up template directory
        self.template_dir = self.get_template_directory()
        self.logger.info(
            f"Dashboard Template directory resolved to: {self.template_dir}"
        )

        # Ensure static directory exists, create it if not
        static_dir = self.template_dir / "static"
        os.makedirs(static_dir, exist_ok=True)

        # Dependencies
        self.metrics_collector: "MetricsCollector" = None
        self.request_queue: "RequestQueue" = None
        self.config_manager: "ConfigManager" = None

        # Initialize FastAPI
        self.app = FastAPI(
            title="NyaProxy Dashboard",
            description="Dashboard for monitoring and controlling NyaProxy",
            version="0.1.0",
        )

        # Set up templates for HTML views
        self.templates = Jinja2Templates(directory=str(self.template_dir))

        # Serve static files
        if static_dir.exists():
            self.app.mount(
                "/static",
                StaticFiles(directory=str(static_dir)),
                name="static",
            )
        else:
            self.logger.warning(f"Static directory not found at {static_dir}")

        # Set up routes
        self._setup_routes()

        # Set up control routes if enabled
        if enable_control:
            self._setup_control_routes()

    def get_template_directory(self) -> Path:
        """Get the template directory path."""
        try:
            # Try the new-style importlib.resources API
            return Path(importlib.resources.files("nya_proxy") / "templates")
        except (AttributeError, ImportError):
            # Fall back to package_data-based path resolution for older Python versions
            package_dir = Path(__file__).parent
            return package_dir / "templates"

    def set_metrics_collector(self, metrics_collector: MetricsCollector):
        """Set the metrics collector."""
        self.metrics_collector = metrics_collector

    def set_request_queue(self, request_queue):
        """Set the request queue."""
        self.request_queue = request_queue

    def set_config_manager(self, config_manager):
        """Set the config manager."""
        self.config_manager = config_manager

    def _setup_routes(self):
        """Set up API routes for the dashboard."""

        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            """Render the dashboard HTML."""

            # Default metrics to make sure the page loads even if metrics are not available
            metrics = {
                "global": {
                    "total_requests": 0,
                    "total_errors": 0,
                    "total_rate_limit_hits": 0,
                    "total_queue_hits": 0,
                    "uptime_seconds": 0,
                },
                "apis": {},
                "timestamp": 0,
            }
            queue_sizes = {}

            if self.metrics_collector:
                metrics = self.metrics_collector.get_all_metrics()
                # Add timestamp if not present
                if "timestamp" not in metrics:
                    import time

                    metrics["timestamp"] = time.time()

            if self.request_queue:
                queue_sizes = self.request_queue.get_all_queue_sizes()

            return self.templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "enable_control": self.enable_control,
                },
            )

        @self.app.get("/api/metrics")
        async def get_metrics():
            """Get all metrics as JSON."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            metrics = self.metrics_collector.get_all_metrics()
            # Add timestamp if not present
            if "timestamp" not in metrics:
                import time

                metrics["timestamp"] = time.time()

            return metrics

        @self.app.get("/api/metrics/{api_name}")
        async def get_api_metrics(api_name: str):
            """Get metrics for a specific API."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            metrics = self.metrics_collector.get_all_metrics()

            if api_name not in metrics["apis"]:
                return JSONResponse(
                    status_code=404, content={"error": f"API '{api_name}' not found"}
                )

            return metrics["apis"][api_name]

        @self.app.get("/api/history")
        async def get_request_history():
            """Get recent request history."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                history = self.metrics_collector.get_recent_history(count=2000)
                return {"history": history}
            except Exception as e:
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error retrieving history: {str(e)}"},
                )

        @self.app.get("/api/queue")
        async def get_queue_status():
            """Get queue status."""
            if not self.request_queue:
                return JSONResponse(
                    status_code=503, content={"error": "Request queue not available"}
                )

            queue_sizes = self.request_queue.get_all_queue_sizes()

            if hasattr(self.request_queue, "get_metrics"):
                queue_metrics = self.request_queue.get_metrics()
                return {"queue_sizes": queue_sizes, "metrics": queue_metrics}

            return {"queue_sizes": queue_sizes}

    def _setup_control_routes(self):
        """Set up control API routes for the dashboard."""

        @self.app.post("/api/queue/clear/{api_name}")
        async def clear_queue(api_name: str):
            """Clear the queue for a specific API."""
            if not self.request_queue:
                return JSONResponse(
                    status_code=503, content={"error": "Request queue not available"}
                )

            cleared_count = self.request_queue.clear_queue(api_name)
            return {"cleared_count": cleared_count}

        @self.app.post("/api/queue/clear")
        async def clear_all_queues():
            """Clear all queues."""
            if not self.request_queue:
                return JSONResponse(
                    status_code=503, content={"error": "Request queue not available"}
                )

            cleared_count = self.request_queue.clear_all_queues()
            return {"cleared_count": cleared_count}

        @self.app.post("/api/metrics/reset")
        async def reset_metrics():
            """Reset all metrics."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            self.metrics_collector.reset()
            return {"status": "ok", "message": "Metrics reset successfully"}

    async def start_background(self, host: str = "0.0.0.0"):
        """Start the dashboard server in the background."""
        config = uvicorn.Config(
            app=self.app, host=host, port=self.port, log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

    def run(self, host: str = "0.0.0.0"):
        """Run the dashboard server in a separate process."""
        uvicorn.run(self.app, host=host, port=self.port, log_level="info")
