"""
Request-history routes for the dashboard.

Time-series analytics deliberately do not live here: the dashboard shows
current state only, and historical trends are served by Prometheus/Grafana
via the ``/metrics`` endpoint.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from loguru import logger

if TYPE_CHECKING:
    from ..api import DashboardAPI


def _no_collector() -> JSONResponse:
    """503 response used when the metrics collector is not wired in."""
    return JSONResponse(
        status_code=503, content={"error": "Metrics collector not available"}
    )


def register_history_routes(app: FastAPI, dashboard: "DashboardAPI") -> None:
    """Attach the request-history routes to ``app``."""

    @app.get("/api/history")
    async def get_request_history(
        api_name: Optional[str] = None,
        key_id: Optional[str] = None,
        status_code: Optional[int] = None,
        min_response_time: Optional[float] = None,
        max_response_time: Optional[float] = None,
        count: int = Query(2000, gt=0, le=5000),
        type: Optional[str] = "response",
    ):
        """Get recent request history with advanced filtering options."""
        if not dashboard.metrics_collector:
            return _no_collector()
        try:
            history = dashboard.metrics_collector.get_recent_history(count=count)
            filtered_history = [
                entry
                for entry in history
                if _history_entry_matches(
                    entry,
                    type=type,
                    api_name=api_name,
                    key_id=key_id,
                    status_code=status_code,
                    min_response_time=min_response_time,
                    max_response_time=max_response_time,
                )
            ]
            return {"history": filtered_history}
        except Exception as e:
            logger.error(f"Error retrieving history: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error retrieving history: {str(e)}"},
            )

    @app.get("/api/history/{api_name}")
    async def get_api_history(api_name: str):
        """Get recent request history for a specific API."""
        if not dashboard.metrics_collector:
            return _no_collector()
        try:
            all_history = dashboard.metrics_collector.get_recent_history(count=2000)
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


def _history_entry_matches(
    entry: Dict[str, Any],
    *,
    type: Optional[str],
    api_name: Optional[str],
    key_id: Optional[str],
    status_code: Optional[int],
    min_response_time: Optional[float],
    max_response_time: Optional[float],
) -> bool:
    """Return True if a history entry passes every active filter."""
    if type and entry.get("type") != type:
        return False
    if api_name and entry.get("api_name") != api_name:
        return False
    if key_id and entry.get("key_id") != key_id:
        return False
    if status_code and entry.get("status_code") != status_code:
        return False
    # When a response-time filter is active, entries with no recorded
    # elapsed_ms are excluded (preserving the original route behaviour).
    if min_response_time and (
        "elapsed_ms" not in entry or entry.get("elapsed_ms", 0) < min_response_time
    ):
        return False
    if max_response_time and (
        "elapsed_ms" not in entry or entry.get("elapsed_ms", 0) > max_response_time
    ):
        return False
    return True
