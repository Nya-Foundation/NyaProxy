"""
NyaProxy - A cute and simple low-level API proxy with dynamic token rotation.
"""

from ._version import __version__
from .common.exceptions import (
    ConfigurationError,
    NyaProxyStatus,
    QueueFullError,
    RequestExpiredError,
    VariablesConfigurationError,
)
from .common.models import ProxyRequest

# Import key components for easier access
from .config.manager import ConfigManager
from .core.proxy import NyaProxyCore
from .dashboard.api import DashboardAPI
from .services.lb import LoadBalancer
from .services.limit import RateLimiter
from .services.metrics import MetricsCollector
from .utils.formatting import format_elapsed_time
from .utils.header import HeaderUtils

# Define __all__ to control what is imported with "from nya import *"
__all__ = [
    # Core application
    "ConfigManager",
    "DashboardAPI",
    "HeaderUtils",
    "LoadBalancer",
    "MetricsCollector",
    "ProxyRequest",
    "NyaProxyCore",
    "RateLimiter",
    # Utilities
    "format_elapsed_time",
    # Exceptions
    "NyaProxyStatus",
    "ConfigurationError",
    "VariablesConfigurationError",
    "QueueFullError",
    "RequestExpiredError",
    # Version
    "__version__",
]
