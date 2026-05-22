"""
Static dashboard pages: the HTML index and the favicon.
"""

import importlib.resources
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse

if TYPE_CHECKING:
    from ..api import DashboardAPI


def register_page_routes(app: FastAPI, dashboard: "DashboardAPI") -> None:
    """Attach the index and favicon routes to ``app``."""

    @app.get("/")
    async def index(request: Request):
        """Render the dashboard HTML."""
        try:
            with importlib.resources.open_text("nya.html", "index.html") as f:
                html_content = f.read()
            html_content = html_content.replace(
                "{{ root_path }}", request.scope.get("root_path", "")
            ).replace(
                "{{ enable_control }}",
                "flex" if dashboard.enable_control else "none",
            )
            return HTMLResponse(html_content)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load index.html",
            )

    @app.get("/favicon.ico")
    async def favicon():
        """Serve the favicon."""
        return FileResponse(dashboard.www_dir / "favicon.ico")
