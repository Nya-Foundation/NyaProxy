"""
Read-only queue-status route.
"""

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

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
            # queue_sizes counts requests still in the priority queue;
            # waiting counts requests a worker has claimed and is holding
            # until a key or quota frees up. Both are work that has not
            # reached the upstream yet.
            queue = dashboard.request_queue
            waiting = (
                queue.get_all_waiting_counts()
                if hasattr(queue, "get_all_waiting_counts")
                else {}
            )
            return {
                "queue_sizes": queue.get_all_queue_sizes(),
                "waiting": waiting,
            }
        except Exception as e:
            logger.error(f"Error retrieving queue status: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error retrieving queue status: {str(e)}"},
            )
