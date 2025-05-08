"""
NyaProxy - A cute and simple low-level API proxy with dynamic token rotation.
"""

from ._version import __version__
from .common.logger import getLogger
from .common.models import NyaRequest

# Import key components for easier access
from .config.manager import ConfigError, ConfigManager
from .core.proxy import NyaProxyCore
from .core.request import RequestExecutor
from .core.response import ResponseProcessor
from .dashboard.api import DashboardAPI
from .services.key import KeyManager
from .services.lb import LoadBalancer
from .services.limit import RateLimiter
from .services.metrics import MetricsCollector
from .services.queue import RequestQueue
from .utils.header import HeaderUtils
from .utils.helper import format_elapsed_time

# Define __all__ to control what is imported with "from nya import *"
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
