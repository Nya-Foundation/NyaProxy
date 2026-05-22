"""
Metrics routes: aggregate metrics, per-API metrics, and key-usage stats.
"""

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from loguru import logger

if TYPE_CHECKING:
    from ..api import DashboardAPI


def _no_collector() -> JSONResponse:
    """503 response used when the metrics collector is not wired in."""
    return JSONResponse(
        status_code=503, content={"error": "Metrics collector not available"}
    )


def register_metrics_routes(app: FastAPI, dashboard: "DashboardAPI") -> None:
    """Attach the metrics and key-usage routes to ``app``."""

    @app.get("/api/metrics")
    async def get_metrics():
        """Get all metrics as JSON."""
        if not dashboard.metrics_collector:
            return _no_collector()
        try:
            return dashboard.metrics_collector.get_all_metrics()
        except Exception as e:
            logger.error(f"Error retrieving metrics: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error retrieving metrics: {str(e)}"},
            )

    @app.get("/api/metrics/{api_name}")
    async def get_api_metrics(api_name: str):
        """Get metrics for a specific API."""
        if not dashboard.metrics_collector:
            return _no_collector()
        try:
            metrics = dashboard.metrics_collector.get_api_metrics(api_name)
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

    @app.get("/api/key-usage")
    async def get_key_usage():
        """Get API key usage statistics."""
        if not dashboard.metrics_collector:
            return _no_collector()
        try:
            metrics = dashboard.metrics_collector.get_all_metrics()
            key_usage = {
                api_name: api_data["key_usage"]
                for api_name, api_data in metrics["apis"].items()
                if "key_usage" in api_data
            }
            return {"key_usage": key_usage}
        except Exception as e:
            logger.error(f"Error retrieving key usage: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"error": f"Error retrieving key usage: {str(e)}"},
            )
