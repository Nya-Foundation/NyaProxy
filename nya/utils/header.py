"""
Header processing utilities for NyaProxy.
"""

import ipaddress
import re
from typing import Any, Dict, Optional, Set, Union

from httpx import Headers
from loguru import logger

from ..common.constants import EXCLUDED_REQUEST_HEADERS


class HeaderUtils:
    """
    Utility class for processing API request headers with variable substitution.
    All methods are static and have no instance state.
    """

    # Compiled regex pattern for variable detection
    _VARIABLE_PATTERN = re.compile(r"\$\{\{([^}]+)\}\}")
    _EXCLUDED_HEADERS = EXCLUDED_REQUEST_HEADERS

    @staticmethod
    def parse_source_ip_address(headers: Headers) -> Optional[str]:
        """
        Extract the source IP address from request headers.

        Args:
            headers: Request headers

        Returns:
            Source IP address if found, otherwise None
        """
        # Check for common headers that may contain the source IP
        for header in [
            "x-forwarded-for",
            "x-real-ip",
            "cf-connecting-ip",
            "true-client-ip",
            "fastly-client-ip",
            "x-client-ip",
            "x-forwarded",
        ]:
            proxy_info = headers.get(header)
            if proxy_info:
                # Extract first IP and validate it
                first_ip = proxy_info.split(",")[0].strip()
                if ipaddress.ip_address(first_ip):
                    return first_ip

        if "forwarded" in headers:
            # Handle the Forwarded header which may contain multiple values
            forwarded = headers["forwarded"]
            result = re.search(r"for=([^;,]+)", forwarded)
            if result:
                ip = result.group(1).strip('"').strip("[]")  # Handle IPv6 brackets
                if ipaddress.ip_address(ip):
                    return ip

        return None

    @staticmethod
    def extract_required_variables(header_templates: Dict[str, Any]) -> Set[str]:
        """
        Extract variable names required by header templates.

        Args:
            header_templates: Dictionary of header templates

        Returns:
            Set of variable names required by the templates
        """
        required_vars = set()

        for header_value in header_templates.values():
            if not isinstance(header_value, str):
                continue

            # Find all ${{variable}} patterns in header templates
            for match in HeaderUtils._VARIABLE_PATTERN.finditer(header_value):
                required_vars.add(match.group(1).strip())

        return required_vars

    @staticmethod
    def process_headers(
        header_templates: Dict[str, Any],
        variable_values: Dict[str, Any],
        original_headers: Optional[Dict[str, str]] = None,
    ) -> Headers:
        """
        Process headers with variable substitution.

        Args:
            header_templates: Dictionary of header templates with variables
            variable_values: Dictionary of variable values
            original_headers: Original request headers to merge with (optional)

        Returns:
            Processed headers with variables substituted
        """

        # Use CaseInsensitiveDict to maintain case-insensitive lookups but preserve original case
        final_headers = Headers()

        # Start with original headers, filtering out excluded ones
        if original_headers:
            for k, v in original_headers.items():
                if k.lower() not in HeaderUtils._EXCLUDED_HEADERS:
                    final_headers[k] = v  # This preserves the original case

        # Process each header template
        for header_name, template in header_templates.items():
            if template is None:
                continue

            # Convert template to string if it's not already
            template_str = str(template) if not isinstance(template, str) else template

            # Replace variables in the template
            header_value = HeaderUtils._substitute_variables(
                template_str, variable_values
            )

            # Set header with original casing preserved
            final_headers[header_name] = header_value

        return final_headers

    @staticmethod
    def _substitute_variables(
        template: str,
        variable_values: Dict[str, Any],
    ) -> str:
        """
        Substitute variables in a template string.

        Args:
            template: Template string with variables
            variable_values: Dictionary of variable values

        Returns:
            Template with variables substituted
        """

        # Quick check if there are any variables to substitute
        if not HeaderUtils._VARIABLE_PATTERN.search(template):
            return template

        # Find all matches and process from end to start to avoid position shifts
        matches = list(HeaderUtils._VARIABLE_PATTERN.finditer(template))
        result = template

        for match in reversed(matches):
            var_name = match.group(1).strip()
            start, end = match.span()

            if var_name in variable_values:
                value = HeaderUtils._get_variable_value(variable_values[var_name])
                # Replace just this match
                result = result[:start] + value + result[end:]
            else:
                logger.warning(
                    f"Variable '{var_name}' not found in variable values {variable_values}"
                )

        return result

    @staticmethod
    def _get_variable_value(value: Any) -> str:
        """
        Convert a variable value to string representation.

        Args:
            value: Variable value (string, list, or other type)

        Returns:
            String representation of the value
        """
        if isinstance(value, list):
            # For lists, use the first value if available
            return str(value[0]) if value else ""
        else:
            # Convert any other type to string
            return str(value)

    @staticmethod
    def merge_headers(
        base_headers: Union[Dict[str, str], Headers], override_headers: Dict[str, str]
    ) -> Headers:
        """
        Merge two sets of headers, with override_headers taking precedence.

        Args:
            base_headers: Base headers dictionary
            override_headers: Headers that will override base headers

        Returns:
            Merged headers dictionary
        """
        # Use CaseInsensitiveDict to handle case-insensitive lookups but preserve casing
        result = Headers(base_headers)

        # Merge in override headers
        for key, value in override_headers.items():
            result[key] = value  # Will override case-insensitively but preserve case

        # Remove excluded headers
        for header in EXCLUDED_REQUEST_HEADERS:
            if header.lower() in result:  # Case-insensitive check
                del result[header.lower()]

        return result  # Convert back to regular dict for compatibility
