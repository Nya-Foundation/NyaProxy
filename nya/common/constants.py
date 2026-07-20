"""
Constants used throughout the NyaProxy application.
"""

# Default Config File Name
DEFAULT_CONFIG_NAME = "config.yaml"

# Default Config Validation Schema
DEFAULT_SCHEMA_NAME = "schema.json"  # Previously schema.json, now using yaml format

# Default Host and Port
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

# API paths
API_PATH_PREFIX = "/api/"

# Hop-by-hop headers belong to one transport connection and must never be
# copied through a proxy.  ``connection`` may nominate additional headers at
# runtime; the static names cover the standard set.
HOP_BY_HOP_HEADERS = {
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

# Request headers that describe the connection between the client and
# NyaProxy, rather than the request NyaProxy sends upstream.
EXCLUDED_REQUEST_HEADERS = HOP_BY_HOP_HEADERS | {
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

WATCH_FILE = "watch.txt"

# A single save in the config UI can emit several change events. Restarts drop
# in-flight requests, so a burst of edits is collapsed into one reload.
RELOAD_DEBOUNCE_SECONDS = 2.0

# Ceiling on one event-wait interval in the queue. Waits are computed from
# real limiter deadlines and cut short by release notifications; this cap is
# insurance so a future release path that forgets to notify costs at most one
# late wake-up instead of a stall.
QUEUE_WAIT_HEARTBEAT_SECONDS = 30.0
