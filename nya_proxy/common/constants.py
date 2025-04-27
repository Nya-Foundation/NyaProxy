"""
Constants used throughout the NyaProxy application.
"""

# Default Config Oath
DEFAULT_CONFIG_PATH = "config.yaml"

# Default Config Validation Schema
DEFAULT_SCHEMA_PATH = "schema.yaml"

# Default Host and Port
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080

# API paths
API_PATH_PREFIX = "/api/"

# Request Header handling
EXCLUDED_REQUEST_HEADERS = {
    "content-length",
    "connection",
    "transfer-encoding",
    "upgrade-insecure-requests",
    "proxy-connection",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-server",
    "x-real-ip",
}

# Metrics
MAX_QUEUE_SIZE = 200
