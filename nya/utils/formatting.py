"""
Formatting helpers: JSON serialization and human-readable durations.
"""

import json
from collections.abc import Mapping
from typing import Any, Optional

import orjson

__all__ = ["json_safe_dumps", "format_elapsed_time"]


def json_safe_dumps(
    obj: Any, indent: Optional[int] = 4, ensure_ascii: bool = False
) -> str:
    """
    Safely convert Python objects to a JSON string.

    Handles bytes objects by decoding them to UTF-8 strings and supports
    nested dictionaries and other common Python data types.

    Args:
        obj: The Python object to convert to JSON
        indent: Number of spaces for indentation (pretty-printing)
        ensure_ascii: If True, escape all non-ASCII characters

    Returns:
        A JSON-formatted string
    """

    if isinstance(obj, str):
        return obj

    # handle httpx.Headers and starlette.datastructures.Headers
    if isinstance(obj, Mapping):
        obj = dict(obj)

    def bytes_converter(o: Any) -> Any:
        if isinstance(o, bytes):
            try:
                return orjson.loads(o)
            except UnicodeDecodeError:
                return f"<binary data: {len(o)} bytes>"
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    # Pretty-print JSON with indentation and optional ASCII escaping
    try:
        return json.dumps(
            obj, indent=indent, ensure_ascii=ensure_ascii, default=bytes_converter
        )
    except Exception:
        return str(obj)


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
