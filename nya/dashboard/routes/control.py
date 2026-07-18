"""
Mutating control routes: clearing queues and resetting metrics.

These are only registered when the dashboard is started with
``enable_control=True``.
"""

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from loguru import logger

if TYPE_CHECKING:
    from ..api import DashboardAPI


def register_control_routes(app: FastAPI, dashboard: "DashboardAPI") -> None:
    """Attach the queue-control and metrics-reset routes to ``app``."""

    @app.post("/api/queue/clear/{api_name}")
    async def clear_queue(api_name: str):
        """Clear the queue for a specific API."""
        if not dashboard.request_queue:
            return JSONResponse(
                status_code=503, content={"error": "Request queue not available"}
            )
        try:
            cleared_count = await dashboard.request_queue.clear_queue(api_name)
            return {"cleared_count": cleared_count}
        except Exception as e:
            logger.error(f"Error clearing queue: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error clearing queue: {str(e)}"},
            )

    @app.post("/api/queue/clear")
    async def clear_all_queues():
        """Clear all queues."""
        if not dashboard.request_queue:
            return JSONResponse(
                status_code=503, content={"error": "Request queue not available"}
            )
        try:
            cleared_count = await dashboard.request_queue.clear_all_queues()
            return {"cleared_count": cleared_count}
        except Exception as e:
            logger.error(f"Error clearing all queues: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error clearing all queues: {str(e)}"},
            )

    @app.post("/api/metrics/reset")
    async def reset_metrics():
        """Reset all metrics."""
        if not dashboard.metrics_collector:
            return JSONResponse(
                status_code=503,
                content={"error": "Metrics collector not available"},
            )
        try:
            dashboard.metrics_collector.reset()
            return {"status": "ok", "message": "Metrics reset successfully"}
        except Exception as e:
            logger.error(f"Error resetting metrics: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error resetting metrics: {str(e)}"},
            )
