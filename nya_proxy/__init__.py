"""
NyaProxy - A cute and simple low-level API proxy with dynamic token rotation.
"""

__version__ = "0.1.0"

# Import key components for easier access
# from .app import NyaProxyApp, app, main
from .config import ConfigError, ConfigManager
from .core import NyaProxyCore
from .dashboard import DashboardAPI
from .header_processor import HeaderProcessor
from .key_manager import KeyManager
from .load_balancer import LoadBalancer
from .logger import setup_logger
from .metrics import MetricsCollector
from .models import NyaRequest
from .rate_limiter import RateLimiter
from .request_executor import RequestExecutor
from .request_queue import RequestQueue
from .response_processor import ResponseProcessor
from .utils import format_elapsed_time

# Define __all__ to control what is imported with "from nya_proxy import *"
__all__ = [
    # Core application
    # "NyaProxyApp",
    # "app",
    # "main",
    # Main components
    "ConfigManager",
    "ConfigError",
    "DashboardAPI",
    "HeaderProcessor",
    "KeyManager",
    "LoadBalancer",
    "MetricsCollector",
    "NyaRequest",
    "NyaProxyCore",
    "RateLimiter",
    "RequestExecutor",
    "RequestQueue",
    "ResponseProcessor",
    # Utilities
    "format_elapsed_time",
    "setup_logger",
    # Version
    "__version__",
]
