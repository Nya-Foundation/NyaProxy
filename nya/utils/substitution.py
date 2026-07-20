"""
JMESPath-based request body substitution engine.

``apply_body_substitutions`` is the public entry point; it walks a list of
rules and conditionally mutates a JSON body. Everything else in this module
is an internal helper for that engine.
"""

import json
import logging
import re
from typing import Any, Dict, List, Union

import jmespath
import orjson
from jmespath.exceptions import JMESPathError

logger = logging.getLogger(__name__)

__all__ = ["apply_body_substitutions"]


def apply_body_substitutions(
    body: Union[Dict, List, str, bytes], rules: List[Dict]
) -> Union[Dict, List, str, bytes]:
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
            body = orjson.loads(body)
        except orjson.JSONDecodeError:
            # If the body isn't valid JSON, return it unchanged
            logger.warning("Failed to decode body as JSON, returning unchanged.")
            return body

    # If no rules or body isn't a dict/list, return unchanged
    if not rules or not isinstance(body, (dict, list)):
        return body

    result = body

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
        return _process_value_references(value, body)

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
        for segment in segments[:-1]:
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
        return {
            k: _process_value_references(v, original_body) for k, v in value.items()
        }

    # Handle list values
    if isinstance(value, list):
        return [_process_value_references(item, original_body) for item in value]

    # Non-string scalars are returned unchanged
    if not isinstance(value, str):
        return value

    # The entire string is a single reference -> return the resolved value as-is
    if value.startswith("${{") and value.endswith("}}"):
        try:
            path = value[3:-2].strip()
            return jmespath.search(path, original_body)
        except JMESPathError:
            return None  # Return null if reference processing fails

    # Embedded references within a larger string -> interpolate
    if "${{" in value and "}}" in value:
        try:

            def replace_match(match: "re.Match") -> str:
                path = match.group(1).strip()
                try:
                    result = jmespath.search(path, original_body)
                    if result is None:
                        return ""  # Missing values replaced with empty string
                    if isinstance(result, (dict, list)):
                        # Objects and arrays are JSON-serialized
                        return json.dumps(result)
                    return str(result)
                except JMESPathError:
                    return ""  # Return empty string if path is invalid

            return re.sub(r"\$\{\{([^}]*)\}\}", replace_match, value)
        except Exception:
            return value  # Return unchanged if string interpolation fails

    # No references found
    return value
