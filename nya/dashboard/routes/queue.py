"""
Read-only queue-status route.
"""

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from loguru import logger

if TYPE_CHECKING:
    from ..api import DashboardAPI


def register_queue_routes(app: FastAPI, dashboard: "DashboardAPI") -> None:
    """Attach the queue-status route to ``app``."""

    @app.get("/api/queue")
    async def get_queue_status():
        """Get queue status."""
        if not dashboard.request_queue:
            return JSONResponse(
                status_code=503, content={"error": "Request queue not available"}
            )
        try:
            queue_sizes = dashboard.request_queue.get_all_queue_sizes()
            if hasattr(dashboard.request_queue, "get_metrics"):
                queue_metrics = dashboard.request_queue.get_metrics()
                return {"queue_sizes": queue_sizes, "metrics": queue_metrics}
            return {"queue_sizes": queue_sizes}
        except Exception as e:
            logger.error(f"Error retrieving queue status: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error retrieving queue status: {str(e)}"},
            )
