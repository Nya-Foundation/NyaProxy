"""
Constants used throughout the NyaProxy application.
"""

# Default Config File Name
DEFAULT_CONFIG_NAME = "config.yaml"

# Default Config Validation Schema
DEFAULT_SCHEMA_NAME = "schema.json"  # Previously schema.json, now using yaml format

# Default Host and Port
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080

# API paths
API_PATH_PREFIX = "/api/"

# Request Header handling
EXCLUDED_REQUEST_HEADERS = {
    "content-length",
    "connection",
    "upgrade-insecure-requests",
    "proxy-connection",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-server",
    "x-real-ip",
    # Cloudflare headers
    "cf-connecting-ip",
    "cf-connecting-ipv6",
    "cf-ew-via",
    "cf-pseudo-ipv4",
    "true-client-ip",
    "cf-ray",
    "cf-ipcountry",
    "cf-visitor",
    "cdn-loop",
    "cf-worker",
}

# Metrics
MAX_QUEUE_SIZE = 200


WATCH_FILE = "watch_file.txt"
