"""
NyaProxy - A cute and simple low-level API proxy with dynamic token rotation.
"""

__version__ = "0.0.5"


from .common.models import NyaRequest
from .common.utils import format_elapsed_time
from .core.handler import NyaProxyCore
from .core.header_processor import HeaderProcessor
from .core.request_executor import RequestExecutor
from .core.response_processor import ResponseProcessor
from .dashboard.api import DashboardAPI

# Import key components for easier access
from .server.config import ConfigError, ConfigManager
from .server.logger import setup_logger
from .services.key_manager import KeyManager
from .services.load_balancer import LoadBalancer
from .services.metrics import MetricsCollector
from .services.rate_limiter import RateLimiter
from .services.request_queue import RequestQueue

# Define __all__ to control what is imported with "from nya_proxy import *"
__all__ = [
    # Core application
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
