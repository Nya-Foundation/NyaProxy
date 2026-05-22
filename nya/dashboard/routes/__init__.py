"""
Dashboard route groups.

Each module exposes a ``register_*_routes(app, dashboard)`` function that
attaches one cohesive group of endpoints to the dashboard's FastAPI app.
Routes read their dependencies (metrics collector, request queue) from the
``dashboard`` object at request time, so wiring order does not matter.
"""

from .control import register_control_routes
from .history import register_history_routes
from .metrics import register_metrics_routes
from .pages import register_page_routes
from .queue import register_queue_routes

__all__ = [
    "register_control_routes",
    "register_history_routes",
    "register_metrics_routes",
    "register_page_routes",
    "register_queue_routes",
]
