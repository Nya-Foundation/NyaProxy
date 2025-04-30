"""
NyaProxy - A cute and simple low-level API proxy with dynamic token rotation.
"""

from ._version import __version__
from .common.logger import getLogger
from .common.models import NyaRequest
from .common.utils import format_elapsed_time
from .core.handler import NyaProxyCore
from .core.header_utils import HeaderUtils
from .core.request_executor import RequestExecutor
from .core.response_processor import ResponseProcessor
from .dashboard.api import DashboardAPI

# Import key components for easier access
from .server.config import ConfigError, ConfigManager
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
    "HeaderUtils",
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
    "getLogger",
    # Version
    "__version__",
]
