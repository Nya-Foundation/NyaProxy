"""
Utility functions for NyaProxy.
"""

import gzip
import json
import re
import zlib
from collections.abc import Mapping
from typing import Any, Dict, List, Optional, Union

import brotli
import jmespath
import orjson  # Faster JSON library
from jmespath.exceptions import JMESPathError

__all__ = [
    "mask_secret",
    "format_elapsed_time",
    "decode_content",
    "json_safe_dumps",
    "apply_body_substitutions",
]


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
        res = json.dumps(
            obj, indent=indent, ensure_ascii=ensure_ascii, default=bytes_converter
        )
        return res
    except Exception as e:
        return str(obj)


def mask_secret(secret: Optional[str]) -> str:
    """
    Get a key identifier for metrics that doesn't expose the full key.

    Creates a partially obfuscated version of the API key suitable for
    use in logs and metrics without exposing sensitive information.

    Args:
        key: The API key or token to obfuscate

    Returns:
        A truncated version of the key for metrics
    """
    if not secret:
        return "unknown_secret"

    # For very short keys, return a masked version
    if len(secret) <= 8:
        return "*" * len(secret)

    # For longer keys, show first and last 4 characters
    return f"{secret[:4]}...{secret[-4:]}"


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
    if not encoding or not content:
        return content

    # Magic bytes for different compression formats
    GZIP_MAGIC = b"\x1f\x8b"  # gzip
    ZLIB_MAGIC_1 = b"\x78\x01"  # zlib no compression
    ZLIB_MAGIC_2 = b"\x78\x9c"  # zlib default compression
    ZLIB_MAGIC_3 = b"\x78\xda"  # zlib best compression
    BROTLI_MAGIC = b"\xce\xb2\xcf\x81"  # Not strict but common brotli signature

    # Check for plaintext JSON content
    is_plaintext_json = content and content.startswith((b"{", b"[", b'"'))

    # Check for compression signatures
    has_gzip_signature = len(content) >= 2 and content[:2] == GZIP_MAGIC
    has_zlib_signature = len(content) >= 2 and content[:2] in (
        ZLIB_MAGIC_1,
        ZLIB_MAGIC_2,
        ZLIB_MAGIC_3,
    )
    has_br_signature = len(content) >= 4 and content[:4] == BROTLI_MAGIC

    # If content appears to be plaintext JSON and doesn't have compression signatures
    if is_plaintext_json and not (
        has_gzip_signature or has_zlib_signature or has_br_signature
    ):
        # Content appears to be plaintext JSON but has compression encoding header
        # Return it unchanged rather than trying to decompress
        return content

    try:
        for enc in reversed(encoding.split(",")):
            enc = enc.strip().lower()
            original_content = content

            try:
                if enc == "gzip":
                    # Only attempt gzip decompression if it has gzip signature or we're not sure
                    if has_gzip_signature or not is_plaintext_json:
                        content = gzip.decompress(content)
                elif enc == "deflate":
                    # Only attempt deflate if it has zlib signature or we're not sure
                    if has_zlib_signature or not is_plaintext_json:
                        try:
                            content = zlib.decompress(content)
                        except zlib.error:
                            content = zlib.decompress(content, -zlib.MAX_WBITS)
                elif enc == "br":
                    # Only attempt brotli if it doesn't look like plaintext JSON
                    if not is_plaintext_json:
                        content = brotli.decompress(content)
                elif enc == "identity":
                    continue
                else:
                    # Unknown encoding; stop decoding
                    break
            except Exception as e:
                # If decompression fails, keep original content and continue
                content = original_content
                print(
                    f"Failed to decode content with encoding '{enc}': {e}, keeping original content."
                )

        return content

    except Exception as e:
        print(f"Failed to process content with encoding '{encoding}': {e}")
        return content


def apply_body_substitutions(
    body: Union[Dict, List, str, bytes], rules: List[Dict]
) -> Dict:
    """
    Apply JMESPath-based substitution rules to modify a JSON request body.

    Args:
        body: The JSON request body as a dict, list, bytes, or JSON string
        rules: List of substitution rule dictionaries with the following structure:
               {
                   "name": "Rule name",
                   "operation": "set|remove",
                   "path": "path.to.field",
                   "value": Any (optional, required for set),
                   "conditions": [
                       {
                           "field": "path.to.condition.field",
                           "operator": "eq|ne|gt|lt|ge|le|in|nin|like|nlike|contains|ncontains|
                                       between|nbetween|startswith|endswith|exists|nexists|isnull|notnull",
                           "value": Any (optional, depends on operator)
                       }
                   ]
               }

    Returns:
        The modified JSON body as a dict or list
    """
    # If body is a string, parse it to a dict
    if isinstance(body, str) or isinstance(body, bytes):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            # If the body isn't valid JSON, return it unchanged
            return body

    # If no rules or body isn't a dict/list, return unchanged
    if not rules or not isinstance(body, (dict, list)):
        return body

    # Make a deep copy of the body to avoid unexpected side effects
    result = orjson.loads(orjson.dumps(body))

    # Apply each rule in sequence
    for rule in rules:
        # Skip rules that don't have the required fields
        if not all(k in rule for k in ["name", "operation", "path"]):
            continue

        # Skip rules where value is missing for set operation
        if rule["operation"] == "set" and "value" not in rule:
            continue

        # Check conditions (if any)
        if "conditions" in rule and rule["conditions"]:
            if not _check_rule_conditions(result, rule["conditions"]):
                continue  # Skip this rule if conditions aren't met

        # Apply the rule based on operation type
        operation = rule["operation"]
        path = rule["path"]

        try:
            if operation == "set":
                result = _set_field(result, path, rule.get("value"))
            elif operation == "remove":
                result = _remove_field(result, path)
            # Handle legacy operation types for backward compatibility
            elif operation == "add":
                result = _set_field(result, path, rule.get("value"))
            elif operation == "replace":
                result = _set_field(result, path, rule.get("value"))
        except Exception:
            # If any operation fails, continue to the next rule
            continue

    return result


def _check_rule_conditions(body: Union[Dict, List], conditions: List[Dict]) -> bool:
    """
    Check if all conditions are met for a rule to be applied.

    Args:
        body: The JSON request body
        conditions: List of condition dictionaries

    Returns:
        True if all conditions are met, False otherwise
    """
    for condition in conditions:
        if not all(k in condition for k in ["field", "operator"]):
            continue  # Skip malformed conditions

        try:
            field_path = condition["field"]
            operator = condition["operator"]

            # Extract the value at the specified path
            try:
                field_value = jmespath.search(field_path, body)
                field_exists = field_value is not None or jmespath.search(
                    f"length({field_path}) > `0`", body
                )
            except (JMESPathError, KeyError, IndexError):
                field_value = None
                field_exists = False

            # Now evaluate the condition based on the operator
            if operator == "eq" and "value" in condition:
                if field_value != condition["value"]:
                    return False

            elif operator == "ne" and "value" in condition:
                if field_value == condition["value"]:
                    return False

            elif operator == "gt" and "value" in condition:
                if (
                    not isinstance(field_value, (int, float))
                    or field_value <= condition["value"]
                ):
                    return False

            elif operator == "lt" and "value" in condition:
                if (
                    not isinstance(field_value, (int, float))
                    or field_value >= condition["value"]
                ):
                    return False

            elif operator == "ge" and "value" in condition:
                if (
                    not isinstance(field_value, (int, float))
                    or field_value < condition["value"]
                ):
                    return False

            elif operator == "le" and "value" in condition:
                if (
                    not isinstance(field_value, (int, float))
                    or field_value > condition["value"]
                ):
                    return False

            elif operator == "in" and "value" in condition:
                if (
                    not isinstance(condition["value"], (list, tuple))
                    or field_value not in condition["value"]
                ):
                    return False

            elif operator == "nin" and "value" in condition:
                if (
                    not isinstance(condition["value"], (list, tuple))
                    or field_value in condition["value"]
                ):
                    return False

            elif operator == "like" and "value" in condition:
                if not isinstance(field_value, str) or not _like_match(
                    field_value, str(condition["value"])
                ):
                    return False

            elif operator == "nlike" and "value" in condition:
                if not isinstance(field_value, str) or _like_match(
                    field_value, str(condition["value"])
                ):
                    return False

            elif operator == "contains" and "value" in condition:
                if not _contains_value(field_value, condition["value"]):
                    return False

            elif operator == "ncontains" and "value" in condition:
                if _contains_value(field_value, condition["value"]):
                    return False

            elif operator == "between" and "value" in condition:
                if (
                    not isinstance(condition["value"], (list, tuple))
                    or len(condition["value"]) != 2
                ):
                    return False
                if not isinstance(field_value, (int, float)) or not (
                    condition["value"][0] <= field_value <= condition["value"][1]
                ):
                    return False

            elif operator == "nbetween" and "value" in condition:
                if (
                    not isinstance(condition["value"], (list, tuple))
                    or len(condition["value"]) != 2
                ):
                    return False
                if not isinstance(field_value, (int, float)) or (
                    condition["value"][0] <= field_value <= condition["value"][1]
                ):
                    return False

            elif operator == "startswith" and "value" in condition:
                if not isinstance(field_value, str) or not field_value.startswith(
                    str(condition["value"])
                ):
                    return False

            elif operator == "endswith" and "value" in condition:
                if not isinstance(field_value, str) or not field_value.endswith(
                    str(condition["value"])
                ):
                    return False

            elif operator == "exists":
                if not field_exists:
                    return False

            elif operator == "nexists":
                if field_exists:
                    return False

            elif operator == "isnull":
                # Simply check if the field value is None (null in JSON)
                if field_value is not None:
                    return False

            elif operator == "notnull":
                # Simply check if the field value is not None
                if field_value is None:
                    return False

        except Exception:
            # If evaluation fails, consider the condition not met
            return False

    # All conditions passed
    return True


def _like_match(value: str, pattern: str) -> bool:
    """
    Implement SQL-like LIKE operator for string matching with wildcards.

    Args:
        value: The string to check
        pattern: The pattern with % as wildcards and _ as single character

    Returns:
        True if pattern matches, False otherwise
    """
    # Convert SQL LIKE pattern to regex
    regex_pattern = "^" + re.escape(pattern).replace("%", ".*").replace("_", ".") + "$"
    return bool(re.match(regex_pattern, value, re.DOTALL))


def _contains_value(field_value: Any, target_value: Any) -> bool:
    """
    Check if a field contains a value, handling different data types.

    Args:
        field_value: The value to check within
        target_value: The value to check for

    Returns:
        True if field_value contains target_value, False otherwise
    """
    # String check
    if isinstance(field_value, str):
        return str(target_value) in field_value

    # List/tuple/set check
    if isinstance(field_value, (list, tuple, set)):
        return target_value in field_value

    # Dict check (key existence)
    if isinstance(field_value, dict):
        return target_value in field_value

    # For other types, equality is the best we can do
    return field_value == target_value


def _set_field(body: Union[Dict, List], path: str, value: Any) -> Union[Dict, List]:
    """
    Set a field in the JSON body at the specified path.
    Creates the field if it doesn't exist, or replaces it if it does.

    Args:
        body: The JSON request body
        path: JMESPath expression for the target field
        value: Value to set

    Returns:
        The modified JSON body
    """
    # Make a copy to avoid side effects
    result = orjson.loads(orjson.dumps(body))

    # Special case for root replacement
    if path == "" or path == "$":
        processed_value = _process_value_references(value, body)
        return processed_value

    # Process any value references
    processed_value = _process_value_references(value, body)

    # Split path into segments for navigation
    segments = path.replace("[", ".").replace("]", "").split(".")
    segments = [s for s in segments if s]  # Remove empty segments

    # Handle empty path
    if not segments:
        return result

    # Navigate/create path
    current = result
    for i, segment in enumerate(segments[:-1]):
        next_segment = segments[i + 1] if i + 1 < len(segments) - 1 else segments[-1]

        # Determine if next segment is array index
        is_next_array = next_segment.isdigit()

        if isinstance(current, dict):
            # Create node if it doesn't exist
            if segment not in current:
                if is_next_array:
                    current[segment] = []
                else:
                    current[segment] = {}
            current = current[segment]
        elif isinstance(current, list):
            if segment.isdigit():
                idx = int(segment)
                # Extend list if needed
                while len(current) <= idx:
                    if is_next_array:
                        current.append([])
                    else:
                        current.append({})
                current = current[idx]
            else:
                # Can't navigate non-numeric segment in a list
                return result
        else:
            # Can't navigate further
            return result

    # Process the last segment
    last_segment = segments[-1]

    if isinstance(current, dict):
        current[last_segment] = processed_value
    elif isinstance(current, list):
        if last_segment.isdigit():
            idx = int(last_segment)
            # Extend list if needed
            while len(current) <= idx:
                current.append(None)
            # Insert at specific position
            if idx < len(current):
                current[idx] = processed_value  # Replace
            else:
                current.append(processed_value)  # Append
        else:
            # Can't add non-numeric segment to list
            return result

    return result


def _remove_field(body: Union[Dict, List], path: str) -> Union[Dict, List]:
    """
    Remove a field from the JSON body at the specified path.

    Args:
        body: The JSON request body
        path: JMESPath expression for the target field

    Returns:
        The modified JSON body
    """
    # Make a copy to avoid side effects
    result = orjson.loads(orjson.dumps(body))

    # Special case for root removal
    if path == "" or path == "$":
        return {} if isinstance(result, dict) else []

    try:
        # Check if path exists
        if jmespath.search(path, result) is None:
            # Nothing to remove
            return result

        # Split path into segments for navigation
        segments = path.replace("[", ".").replace("]", "").split(".")
        segments = [s for s in segments if s]  # Remove empty segments

        # Navigate to the parent of the target
        current = result
        for i, segment in enumerate(segments[:-1]):
            if isinstance(current, dict):
                if segment not in current:
                    # Path doesn't exist
                    return result
                current = current[segment]
            elif isinstance(current, list):
                if segment.isdigit():
                    idx = int(segment)
                    if idx >= len(current):
                        # Index out of bounds
                        return result
                    current = current[idx]
                else:
                    # Can't navigate non-numeric segment in a list
                    return result
            else:
                # Can't navigate further
                return result

        # Remove the field from its parent
        last_segment = segments[-1]

        if isinstance(current, dict):
            if last_segment in current:
                del current[last_segment]
        elif isinstance(current, list):
            if last_segment.isdigit():
                idx = int(last_segment)
                if 0 <= idx < len(current):
                    current.pop(idx)
                else:
                    # Index out of bounds
                    return result
            else:
                # Can't remove non-numeric segment from list
                return result

    except (JMESPathError, TypeError, ValueError, IndexError):
        # Path is invalid or doesn't exist
        return result

    return result


def _process_value_references(value: Any, original_body: Union[Dict, List]) -> Any:
    """
    Process a value for any references to the original body using ${{path}} notation.

    Examples:
    - ${{messages}} -> Entire messages array
    - ${{messages[0].content}} -> Content of first message
    - "Using model: ${{model}}" -> String interpolation

    Args:
        value: The value that may contain references
        original_body: The original JSON body

    Returns:
        The processed value with references resolved
    """
    # Handle dict values
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            result[k] = _process_value_references(v, original_body)
        return result

    # Handle list values
    elif isinstance(value, list):
        return [_process_value_references(item, original_body) for item in value]

    # Handle string values that might contain references
    elif isinstance(value, str):
        # Check for direct reference replacement (the entire string is a reference)
        if value.startswith("${{") and value.endswith("}}"):
            try:
                # Extract the path between ${{ and }}
                path = value[3:-2].strip()
                result = jmespath.search(path, original_body)
                # Return the actual value even if it's null
                return result
            except JMESPathError:
                return None  # Return null if reference processing fails

        # Check for embedded references within string
        elif "${{" in value and "}}" in value:
            try:
                import re

                pattern = r"\$\{\{([^}]*)\}\}"

                def replace_match(match):
                    path = match.group(1).strip()
                    try:
                        result = jmespath.search(path, original_body)
                        if result is None:
                            return ""  # Missing values replaced with empty string
                        elif isinstance(result, (dict, list)):
                            # Objects and arrays are JSON-serialized
                            return json.dumps(result)
                        else:
                            # Simple values converted to strings
                            return str(result)
                    except JMESPathError:
                        return ""  # Return empty string if path is invalid

                return re.sub(pattern, replace_match, value)
            except Exception:
                return value  # Return unchanged if string interpolation fails

        # No references found, return unchanged
        else:
            return value

    # Return other values unchanged
    else:
        return value


# Alias old function names to the new ones for backward compatibility
_add_field = _set_field
_replace_field = _set_field
