"""
Utility functions for NyaProxy.
"""

import gzip
import json
import zlib
from typing import Any, Optional

import brotli

__all__ = ["_mask_api_key", "format_elapsed_time", "decode_content", "json_safe_dumps"]


def json_safe_dumps(
    obj: Any, indent: str = 4, ensure_ascii: bool = False, **kwargs
) -> str:
    """
    Safely serialize any Python object to a JSON-formatted string.
    If the object is not JSON serializable, it falls back to a string representation.

    Args:
        obj: Any Python object to serialize.
        **kwargs: Optional keyword arguments for json.dumps (e.g., indent, separators).

    Returns:
        A JSON-formatted string or raw string representation if serialization fails.
    """
    try:
        json_data = json.loads(obj)
        return json.dumps(
            json_data,
            default=str(obj),
            indent=indent,
            ensure_ascii=ensure_ascii,
            **kwargs,
        )
    except (TypeError, ValueError) as e:
        return str(obj)


def _mask_api_key(key: Optional[str]) -> str:
    """
    Get a key identifier for metrics that doesn't expose the full key.

    Creates a partially obfuscated version of the API key suitable for
    use in logs and metrics without exposing sensitive information.

    Args:
        key: The API key or token to obfuscate

    Returns:
        A truncated version of the key for metrics
    """
    if not key:
        return "unknown"

    try:
        # For very short keys, return a masked version
        if len(key) <= 8:
            return "*" * len(key)

        # For longer keys, show first and last 4 characters
        return f"{key[:4]}...{key[-4:]}"
    except (TypeError, AttributeError):
        # Handle case where key is not a string
        return "invalid_key_format"


def format_elapsed_time(elapsed_seconds: float) -> str:
    """
    Format elapsed time in a human-readable format.

    Args:
        elapsed_seconds: Time in seconds

    Returns:
        Formatted time string (e.g., "1.23s" or "123ms")
    """
    if elapsed_seconds < 0.001:
        return f"{elapsed_seconds * 1000000:.0f}μs"
    elif elapsed_seconds < 1:
        return f"{elapsed_seconds * 1000:.0f}ms"
    elif elapsed_seconds < 60:
        return f"{elapsed_seconds:.2f}s"
    elif elapsed_seconds < 3600:
        minutes = int(elapsed_seconds // 60)
        seconds = elapsed_seconds % 60
        return f"{minutes}m {seconds:.1f}s"
    else:
        hours = int(elapsed_seconds // 3600)
        minutes = int((elapsed_seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def decode_content(content: bytes, encoding: Optional[str]) -> bytes:
    """
    Decode response content based on encoding.

    Args:
        content: Encoded content bytes
        encoding: Content encoding (gzip, deflate, br, identity)

    Returns:
        Decoded content bytes
    """
    try:

        if not encoding:
            return content

        # Normalize encoding name to lowercase
        encoding = encoding.lower()

        if encoding == "gzip":
            return gzip.decompress(content)
        elif encoding == "deflate":
            return zlib.decompress(content)
        elif encoding == "br":
            return brotli.decompress(content)
        elif encoding == "identity" or not encoding:
            # No decoding needed
            return content
        else:
            # Unknown encoding, return as-is
            return content

    except Exception as e:
        # Return raw content if decoding fails
        return content
