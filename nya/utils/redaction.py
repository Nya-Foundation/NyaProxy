"""
Secret redaction helpers for safe logging and metrics.
"""

from collections.abc import Mapping
from typing import Any, Optional

__all__ = ["SENSITIVE_FIELD_NAMES", "mask_secret", "redact_sensitive_data"]

#: Field names whose values must never appear verbatim in logs or metrics.
SENSITIVE_FIELD_NAMES = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "apikey",
    "access-token",
    "x-access-token",
    "refresh-token",
    "token",
    "secret",
    "password",
}


def mask_secret(secret: Optional[str]) -> str:
    """
    Produce a non-reversible identifier for a secret, safe for logs/metrics.

    Args:
        secret: The API key or token to obfuscate

    Returns:
        A truncated version of the secret (e.g. ``"abcd...wxyz"``)
    """
    if not secret:
        return "unknown_secret"

    # For very short keys, return a fully masked version
    if len(secret) <= 8:
        return "*" * len(secret)

    # For longer keys, show first and last 4 characters
    return f"{secret[:4]}...{secret[-4:]}"


def redact_sensitive_data(value: Any) -> Any:
    """
    Return a copy of common structured values with sensitive fields masked.
    """
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            key_str = str(key)
            if key_str.lower() in SENSITIVE_FIELD_NAMES:
                redacted[key] = mask_secret(str(item)) if item else item
            else:
                redacted[key] = redact_sensitive_data(item)
        return redacted

    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)

    return value
