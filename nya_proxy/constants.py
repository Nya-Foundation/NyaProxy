"""
Constants used throughout the NyaProxy application.
"""

# API paths
API_PATH_PREFIX = "/api/"

# Header handling
EXCLUDED_HEADERS = {
    "host",
    "content-length",
    "connection",
    "transfer-encoding",
    "upgrade-insecure-requests",
    "proxy-connection",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
}

# Metrics
METRICS_HISTORY_SIZE = 100
