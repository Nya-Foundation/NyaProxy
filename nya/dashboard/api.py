"""
Dashboard API for NyaProxy.
"""

import importlib.resources
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

from .._version import __version__

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
        port: int = 8082,
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

        # Set up template directory
        self.www_dir = self.get_html_directory()

        # Ensure static directory exists, create it if not
        static_dir = self.www_dir / "static"
        os.makedirs(static_dir, exist_ok=True)

        # Ensure CSS and JS directories exist
        css_dir = static_dir / "css"
        js_dir = static_dir / "js"
        os.makedirs(css_dir, exist_ok=True)
        os.makedirs(js_dir, exist_ok=True)

        # Dependencies
        self.metrics_collector: Optional["MetricsCollector"] = None
        self.request_queue = None
        self.config_manager = None

        # Initialize FastAPI
        self.app = FastAPI(
            title="NyaProxy Dashboard",
            description="Dashboard for monitoring and controlling NyaProxy",
            version=__version__,
        )

        # Set up templates for HTML views
        self.templates = Jinja2Templates(directory=str(self.www_dir))

        # Serve static files
        if static_dir.exists():
            self.app.mount(
                "/static",
                StaticFiles(directory=str(static_dir)),
                name="static",
            )
        else:
            logger.warning(f"Static directory not found at {static_dir}")

        # Set up routes
        self._setup_routes()

        # Set up control routes if enabled
        if enable_control:
            self._setup_control_routes()

    def get_html_directory(self) -> Path:
        """Get the html directory path."""
        try:
            # Try the new-style importlib.resources API
            return Path(importlib.resources.files("nya") / "html")
        except (AttributeError, ImportError):
            # Fall back to package_data-based path resolution for older Python versions
            package_dir = Path(__file__).parent
            return package_dir / "html"

    def set_metrics_collector(self, metrics_collector: "MetricsCollector"):
        """Set the metrics collector."""
        self.metrics_collector = metrics_collector

    def set_request_queue(self, request_queue: "RequestQueue"):
        """Set the request queue."""
        self.request_queue = request_queue

    def set_config_manager(self, config_manager: "ConfigManager"):
        """Set the config manager."""
        self.config_manager = config_manager

    def _setup_routes(self):
        """Set up API routes for the dashboard."""

        @self.app.get("/")
        async def index(request: Request):
            """Render the dashboard HTML."""
            return self.templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "enable_control": self.enable_control,
                },
            )

        @self.app.get("/favicon.ico")
        async def favicon():
            """Serve the favicon."""
            favicon_path = self.www_dir / "favicon.ico"
            return FileResponse(favicon_path)

        @self.app.get("/api/metrics")
        async def get_metrics():
            """Get all metrics as JSON."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                metrics = self.metrics_collector.get_all_metrics()
                return metrics
            except Exception as e:
                logger.error(f"Error retrieving metrics: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error retrieving metrics: {str(e)}"},
                )

        @self.app.get("/api/metrics/{api_name}")
        async def get_api_metrics(api_name: str):
            """Get metrics for a specific API."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                metrics = self.metrics_collector.get_api_metrics(api_name)

                if not metrics or metrics.get("total_requests", 0) == 0:
                    return JSONResponse(
                        status_code=404,
                        content={"error": f"No metrics found for API: {api_name}"},
                    )
                return metrics
            except Exception as e:
                logger.error(f"Error retrieving API metrics: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error retrieving API metrics: {str(e)}"},
                )

        @self.app.get("/api/history")
        async def get_request_history(
            api_name: Optional[str] = None,
            key_id: Optional[str] = None,
            status_code: Optional[int] = None,
            min_response_time: Optional[float] = None,
            max_response_time: Optional[float] = None,
            count: int = Query(2000, gt=0, le=5000),
            type: Optional[str] = "response",
        ):
            """
            Get recent request history with advanced filtering options.

            Args:
                api_name: Filter by API name
                key_id: Filter by API key ID
                status_code: Filter by status code
                min_response_time: Filter by minimum response time (ms)
                max_response_time: Filter by maximum response time (ms)
                count: Maximum number of history entries to return
                type: Filter by entry type ('request' or 'response')
            """
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                # Get raw history
                history = self.metrics_collector.get_recent_history(count=count)

                # Apply filters
                filtered_history = []
                for entry in history:
                    # Skip if doesn't match the type filter
                    if type and entry.get("type") != type:
                        continue

                    # Skip if doesn't match the API name filter
                    if api_name and entry.get("api_name") != api_name:
                        continue

                    # Skip if doesn't match the key ID filter
                    if key_id and entry.get("key_id") != key_id:
                        continue

                    # Skip if doesn't match the status code filter
                    if status_code and entry.get("status_code") != status_code:
                        continue

                    # Skip if response time is less than minimum
                    if min_response_time and (
                        "elapsed_ms" not in entry
                        or entry.get("elapsed_ms", 0) < min_response_time
                    ):
                        continue

                    # Skip if response time is more than maximum
                    if max_response_time and (
                        "elapsed_ms" not in entry
                        or entry.get("elapsed_ms", 0) > max_response_time
                    ):
                        continue

                    filtered_history.append(entry)

                return {"history": filtered_history}
            except Exception as e:
                logger.error(f"Error retrieving history: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error retrieving history: {str(e)}"},
                )

        @self.app.get("/api/history/{api_name}")
        async def get_api_history(api_name: str):
            """Get recent request history for a specific API."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                all_history = self.metrics_collector.get_recent_history(count=2000)
                api_history = [
                    entry for entry in all_history if entry["api_name"] == api_name
                ]
                return {"history": api_history}
            except Exception as e:
                logger.error(f"Error retrieving API history: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error retrieving API history: {str(e)}"},
                )

        @self.app.get("/api/analytics")
        async def get_analytics(
            api_name: Optional[str] = None,
            key_id: Optional[str] = None,
            time_range: str = "24h",
        ):
            """
            Get analytics data for visualization.

            Args:
                api_name: Filter by API name
                key_id: Filter by API key ID
                time_range: Time range for analytics (1h, 24h, 7d, 30d, all)
            """
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                # Get history data
                history = self.metrics_collector.get_recent_history(count=5000)

                # Calculate time cutoff based on time_range
                import time

                now = time.time()
                cutoff_time = 0

                if time_range == "1h":
                    cutoff_time = now - 3600
                elif time_range == "24h":
                    cutoff_time = now - 86400
                elif time_range == "7d":
                    cutoff_time = now - 604800
                elif time_range == "30d":
                    cutoff_time = now - 2592000

                # Filter history by time range, API name, and key ID
                filtered_history = []
                for entry in history:
                    if entry.get("type") != "response":
                        continue

                    if entry["timestamp"] < cutoff_time:
                        continue

                    if api_name and entry.get("api_name") != api_name:
                        continue

                    if key_id and entry.get("key_id") != key_id:
                        continue

                    filtered_history.append(entry)

                # Prepare analytics result
                analytics = {
                    "time_range": time_range,
                    "api_name": api_name,
                    "key_id": key_id,
                    "data": self._calculate_analytics(filtered_history, time_range),
                    "filters": {
                        "apis": sorted(
                            list(
                                set(
                                    e.get("api_name")
                                    for e in filtered_history
                                    if "api_name" in e
                                )
                            )
                        ),
                        "keys": sorted(
                            list(
                                set(
                                    e.get("key_id")
                                    for e in filtered_history
                                    if "key_id" in e
                                )
                            )
                        ),
                    },
                }

                return analytics
            except Exception as e:
                logger.error(f"Error generating analytics: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error generating analytics: {str(e)}"},
                )

        @self.app.get("/api/queue")
        async def get_queue_status():
            """Get queue status."""
            if not self.request_queue:
                return JSONResponse(
                    status_code=503, content={"error": "Request queue not available"}
                )

            try:
                queue_sizes = self.request_queue.get_all_queue_sizes()

                if hasattr(self.request_queue, "get_metrics"):
                    queue_metrics = self.request_queue.get_metrics()
                    return {"queue_sizes": queue_sizes, "metrics": queue_metrics}

                return {"queue_sizes": queue_sizes}
            except Exception as e:
                logger.error(f"Error retrieving queue status: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error retrieving queue status: {str(e)}"},
                )

        @self.app.get("/api/key-usage")
        async def get_key_usage():
            """Get API key usage statistics."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                metrics = self.metrics_collector.get_all_metrics()
                key_usage = {}

                # Extract key usage per API
                for api_name, api_data in metrics["apis"].items():
                    if "key_usage" in api_data:
                        key_usage[api_name] = api_data["key_usage"]

                return {"key_usage": key_usage}
            except Exception as e:
                logger.error(f"Error retrieving key usage: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error retrieving key usage: {str(e)}"},
                )

    def _calculate_analytics(
        self, history: List[Dict[str, Any]], time_range: str
    ) -> Dict[str, Any]:
        """
        Calculate analytics data from history entries.

        Args:
            history: List of history entries
            time_range: Time range for analytics

        Returns:
            Dictionary with analytics data
        """
        import time
        from collections import defaultdict

        # Get current time
        now = time.time()

        # Define time intervals based on time_range
        intervals = []
        interval_seconds = 0

        if time_range == "1h":
            # 5-minute intervals for 1 hour
            interval_seconds = 300
            num_intervals = 12
        elif time_range == "24h":
            # 1-hour intervals for 24 hours
            interval_seconds = 3600
            num_intervals = 24
        elif time_range == "7d":
            # 1-day intervals for 7 days
            interval_seconds = 86400
            num_intervals = 7
        elif time_range == "30d":
            # 1-day intervals for 30 days
            interval_seconds = 86400
            num_intervals = 30
        else:
            # Default to 1-hour intervals for last 24 hours
            interval_seconds = 3600
            num_intervals = 24

        # Generate time intervals
        for i in range(num_intervals):
            end_time = now - (i * interval_seconds)
            start_time = end_time - interval_seconds
            intervals.append(
                {
                    "start": start_time,
                    "end": end_time,
                    "label": self._format_interval_label(end_time, time_range),
                }
            )

        # Reverse intervals to be in chronological order
        intervals.reverse()

        # Initialize data structures for analytics
        requests_by_interval = [0] * len(intervals)
        errors_by_interval = [0] * len(intervals)
        response_times_by_interval = [[] for _ in range(len(intervals))]
        status_code_counts = defaultdict(int)
        api_request_counts = defaultdict(int)
        key_request_counts = defaultdict(int)

        # Process history entries
        for entry in history:
            # Skip non-response entries for some metrics
            is_response = entry.get("type") == "response"
            timestamp = entry.get("timestamp", 0)

            # Count by API and key for all entries
            if "api_name" in entry:
                api_request_counts[entry["api_name"]] += 1

            if "key_id" in entry:
                key_request_counts[entry["key_id"]] += 1

            # Find which interval this entry belongs to
            for i, interval in enumerate(intervals):
                if interval["start"] <= timestamp <= interval["end"]:
                    # Count requests (all entry types)
                    requests_by_interval[i] += 1

                    # Process response-specific data
                    if is_response:
                        # Count errors
                        status = entry.get("status_code", 0)
                        if status >= 400:
                            errors_by_interval[i] += 1

                        # Track status codes
                        status_code_counts[status] += 1

                        # Track response times
                        if "elapsed_ms" in entry:
                            response_times_by_interval[i].append(entry["elapsed_ms"])

                    break

        # Calculate average response times
        avg_response_times = []
        for times in response_times_by_interval:
            if times:
                avg_response_times.append(sum(times) / len(times))
            else:
                avg_response_times.append(0)

        # Prepare the final analytics data
        return {
            "time_intervals": [interval["label"] for interval in intervals],
            "requests_over_time": requests_by_interval,
            "errors_over_time": errors_by_interval,
            "avg_response_times": avg_response_times,
            "status_code_distribution": dict(status_code_counts),
            "api_distribution": dict(api_request_counts),
            "key_distribution": dict(key_request_counts),
        }

    def _format_interval_label(self, timestamp: float, time_range: str) -> str:
        """
        Format a timestamp as a human-readable interval label.

        Args:
            timestamp: Unix timestamp
            time_range: Time range context

        Returns:
            Formatted time label
        """
        from datetime import datetime

        dt = datetime.fromtimestamp(timestamp)

        if time_range == "1h":
            # For 1-hour range, show hour:minute
            return dt.strftime("%H:%M")
        elif time_range == "24h":
            # For 24-hour range, show hour
            return dt.strftime("%H:%M")
        elif time_range in ("7d", "30d"):
            # For multi-day ranges, show month-day
            return dt.strftime("%m-%d")
        else:
            # Default format
            return dt.strftime("%m-%d %H:%M")

    def _setup_control_routes(self):
        """Set up control API routes for the dashboard."""

        @self.app.post("/api/queue/clear/{api_name}")
        async def clear_queue(api_name: str):
            """Clear the queue for a specific API."""
            if not self.request_queue:
                return JSONResponse(
                    status_code=503, content={"error": "Request queue not available"}
                )

            try:
                cleared_count = await self.request_queue.clear_queue(api_name)
                return {"cleared_count": cleared_count}
            except Exception as e:
                logger.error(f"Error clearing queue: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error clearing queue: {str(e)}"},
                )

        @self.app.post("/api/queue/clear")
        async def clear_all_queues():
            """Clear all queues."""
            if not self.request_queue:
                return JSONResponse(
                    status_code=503, content={"error": "Request queue not available"}
                )

            try:
                cleared_count = self.request_queue.clear_all_queues()
                return {"cleared_count": cleared_count}
            except Exception as e:
                logger.error(f"Error clearing all queues: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error clearing all queues: {str(e)}"},
                )

        @self.app.post("/api/metrics/reset")
        async def reset_metrics():
            """Reset all metrics."""
            if not self.metrics_collector:
                return JSONResponse(
                    status_code=503,
                    content={"error": "Metrics collector not available"},
                )

            try:
                self.metrics_collector.reset()
                return {"status": "ok", "message": "Metrics reset successfully"}
            except Exception as e:
                logger.error(f"Error resetting metrics: {str(e)}")
                return JSONResponse(
                    status_code=500,
                    content={"error": f"Error resetting metrics: {str(e)}"},
                )

    async def start_background(self, host: str = "0.0.0.0"):
        """Start the dashboard server in the background."""
        config = uvicorn.Config(
            app=self.app, host=host, port=self.port, log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

    def run(self, host: str = "0.0.0.0"):
        """Run the dashboard server in a separate process."""
        uvicorn.run(self.app, host=host, port=self.port, log_config=None)
