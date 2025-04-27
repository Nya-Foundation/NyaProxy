"""
Header processing utilities for NyaProxy.
"""

import logging
import re
from typing import Any, Dict, Optional, Set

from ..common.constants import EXCLUDED_REQUEST_HEADERS


class HeaderProcessor:
    """
    Processes API request headers with variable substitution.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the header processor.

        Args:
            logger: Logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self._variable_pattern = re.compile(r"\$\{\{([^}]+)\}\}")
        self.excluded_headers = EXCLUDED_REQUEST_HEADERS

    def extract_required_variables(self, header_templates: Dict[str, Any]) -> Set[str]:
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
            for match in self._variable_pattern.finditer(header_value):
                required_vars.add(match.group(1).strip())

        return required_vars

    def _process_headers(
        self,
        header_templates: Dict[str, Any],
        variable_values: Dict[str, Any],
        original_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """
        Process headers with variable substitution.

        Args:
            header_templates: Dictionary of header templates with variables
            variable_values: Dictionary of variable values
            original_headers: Original request headers to merge with (optional)

        Returns:
            Processed headers with variables substituted
        """
        # Start with a copy of filtered original headers
        final_headers = {}
        if original_headers:

            final_headers = {
                k.lower(): v
                for k, v in original_headers.items()
                if k.lower() not in self.excluded_headers
            }

        # Process each header template
        for header_name, template in header_templates.items():
            if template is None:
                continue

            # Convert template to string if it's not already
            template_str = str(template) if not isinstance(template, str) else template

            # Replace variables in the template
            header_value = self._substitute_variables(template_str, variable_values)

            # Use the lowercase header name for case-insensitivity
            final_headers[header_name.lower()] = header_value

            # patch accept-encoding header to avoid issues with httpx
            if header_name.lower() == "accept-encoding":
                final_headers[header_name.lower()] = "identity"

        return final_headers

    def _substitute_variables(
        self, template: str, variable_values: Dict[str, Any]
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
        if not self._variable_pattern.search(template):
            return template

        # Find all matches and process from end to start to avoid position shifts
        matches = list(self._variable_pattern.finditer(template))
        result = template

        for match in reversed(matches):
            var_name = match.group(1).strip()
            start, end = match.span()

            if var_name in variable_values:
                value = self._get_variable_value(variable_values[var_name])
                # Replace just this match
                result = result[:start] + value + result[end:]
            else:
                self.logger.warning(
                    f"Variable '{var_name}' not found in variable values"
                )

        return result

    def _get_variable_value(self, value: Any) -> str:
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

    def merge_headers(
        self, base_headers: Dict[str, str], override_headers: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Merge two sets of headers, with override_headers taking precedence.

        Args:
            base_headers: Base headers dictionary
            override_headers: Headers that will override base headers

        Returns:
            Merged headers dictionary
        """
        # Make a copy of base headers (normalized to lowercase)
        result = {k.lower(): v for k, v in base_headers.items()}

        # Merge in override headers
        for key, value in override_headers.items():
            result[key.lower()] = value

        # Remove excluded headers
        for header in self.excluded_headers:
            result.pop(header, None)

        return result
