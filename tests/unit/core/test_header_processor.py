import re

from nya_proxy.core.header_utils import HeaderUtils


class TestHeaderUtils:
    def test_extract_required_variables(
        self,
    ):
        templates = {
            "Authorization": "Bearer ${{api_key}}",
            "User-Agent": "${{user_agent}}",
            "X-Static": "static-value",
            "X-Multi": "${{a}}-${{b}}",
        }

        pattern = HeaderUtils._VARIABLE_PATTERN
        assert pattern == re.compile(r"\$\{\{([^}]+)\}\}")

        assert HeaderUtils.extract_required_variables(templates) == {
            "api_key",
            "user_agent",
            "a",
            "b",
        }

    def test_substitute_variables(
        self,
    ):
        template = "Bearer ${{api_key}}"
        values = {"api_key": "KEY123"}
        assert HeaderUtils._substitute_variables(template, values) == "Bearer KEY123"
        # Missing variable
        assert (
            HeaderUtils._substitute_variables("Bearer ${{missing}}", {})
            == "Bearer ${{missing}}"
        )
        # No variables
        assert HeaderUtils._substitute_variables("static", {}) == "static"

    def test_substitute_multiple_variables_in_one_string(self):
        template = "Bearer ${{key}} with user ${{user}} and role ${{role}}"
        values = {"key": "abc123", "user": "john", "role": "admin"}
        result = HeaderUtils._substitute_variables(template, values)
        assert result == "Bearer abc123 with user john and role admin"

        # Missing some variables
        partial_values = {"key": "abc123", "role": "admin"}
        result2 = HeaderUtils._substitute_variables(template, partial_values)
        assert result2 == "Bearer abc123 with user ${{user}} and role admin"

        # Variables with special characters
        template3 = "${{prefix}}:${{value}}//${{suffix}}"
        special_values = {"prefix": "http", "value": "example.com", "suffix": "api/v1"}
        result3 = HeaderUtils._substitute_variables(template3, special_values)
        assert result3 == "http:example.com//api/v1"

    def test_get_variable_value(
        self,
    ):
        assert HeaderUtils._get_variable_value(["a", "b"]) == "a"
        assert HeaderUtils._get_variable_value([]) == ""
        assert HeaderUtils._get_variable_value(123) == "123"
        assert HeaderUtils._get_variable_value(None) == "None"

    def test_process_headers_merges_and_substitutes(
        self,
    ):
        templates = {"Authorization": "Bearer ${{api_key}}", "X-Static": "static"}
        values = {"api_key": "KEY"}
        orig = {"Accept": "application/json"}
        result = HeaderUtils.process_headers(templates, values, orig)
        assert result["authorization"] == "Bearer KEY"
        assert result["x-static"] == "static"
        assert result["accept"] == "application/json"
        assert "host" not in result

    def test_process_headers_with_multiple_variables(self):
        templates = {
            "Authorization": "Bearer ${{api_key}}",
            "User-Agent": "${{app_name}}/${{version}} (${{os}})",
            "X-Custom": "${{prefix}}-${{middle}}-${{suffix}}",
        }
        values = {
            "api_key": "secret123",
            "app_name": "NyaProxy",
            "version": "1.0",
            "os": "Linux",
            "prefix": "alpha",
            "middle": "beta",
            "suffix": "gamma",
        }
        result = HeaderUtils.process_headers(templates, values)
        assert result["authorization"] == "Bearer secret123"
        assert result["user-agent"] == "NyaProxy/1.0 (Linux)"
        assert result["x-custom"] == "alpha-beta-gamma"

    def test_merge_headers(
        self,
    ):
        base = {"A": "1", "B": "2"}
        override = {"B": "3", "C": "4"}
        merged = HeaderUtils.merge_headers(base, override)
        assert merged["a"] == "1"
        assert merged["b"] == "3"
        assert merged["c"] == "4"

    def test_merge_headers_with_complex_cases(self):
        # Test merging when headers have mixed case
        base = {"Content-Type": "application/json", "X-API-KEY": "123"}
        override = {"content-type": "text/plain", "x-custom": "value"}
        result = HeaderUtils.merge_headers(base, override)
        assert result["content-type"] == "text/plain"  # Override wins
        assert result["x-api-key"] == "123"  # Kept from base
        assert result["x-custom"] == "value"  # Added from override

        # Test with excluded headers in both
        base2 = {"X-Forwarded-For": "1.2.3.4", "Authorization": "Bearer base"}
        override2 = {"x-forwarded-for": "5.6.7.8", "authorization": "Bearer override"}
        result2 = HeaderUtils.merge_headers(base2, override2)
        assert "x-forwarded-for" not in result2  # Excluded
        assert result2["authorization"] == "Bearer override"  # Override wins

        # Test with empty headers
        assert HeaderUtils.merge_headers({}, {}) == {}
        assert HeaderUtils.merge_headers({"A": "1"}, {}) == {"a": "1"}
        assert HeaderUtils.merge_headers({}, {"B": "2"}) == {"b": "2"}

    def test_accept_encoding_patch(
        self,
    ):
        templates = {"Accept-Encoding": "gzip"}
        values = {}
        result = HeaderUtils.process_headers(templates, values)
        assert result["accept-encoding"] == "identity"

    def test_excluded_headers_are_removed(
        self,
    ):
        templates = {
            "Authorization": "Bearer ${{api_key}}",
        }
        values = {"api_key": "KEY"}
        orig = {
            "X-Forwarded-For": "1.2.3.4",
            "X-Real-Ip": "5.6.7.8",
            "Authorization": "Bearer ${{api_key}}",
        }
        result = HeaderUtils.process_headers(templates, values, orig)
        assert "x-forwarded-for" not in result
        assert "x-real-ip" not in result
        assert result["authorization"] == "Bearer KEY"

    def test_none_template_is_skipped(self):
        templates = {"Authorization": None, "User-Agent": "UA"}
        values = {}
        result = HeaderUtils.process_headers(templates, values)
        assert "authorization" not in result
        assert result["user-agent"] == "UA"

    def test_process_headers_with_special_values(self):
        # Test with empty list
        templates = {"X-Empty-List": "${{empty_list}}"}
        values = {"empty_list": []}
        result = HeaderUtils.process_headers(templates, values)
        assert result["x-empty-list"] == ""

        # Test with None value in list
        templates2 = {"X-None-List": "${{none_list}}"}
        values2 = {"none_list": [None]}
        result2 = HeaderUtils.process_headers(templates2, values2)
        assert result2["x-none-list"] == "None"

        # Test with number values
        templates3 = {"X-Number": "${{number}}", "X-Float": "${{float}}"}
        values3 = {"number": 123, "float": 45.67}
        result3 = HeaderUtils.process_headers(templates3, values3)
        assert result3["x-number"] == "123"
        assert result3["x-float"] == "45.67"

        # Test with boolean values
        templates4 = {"X-Bool-True": "${{true}}", "X-Bool-False": "${{false}}"}
        values4 = {"true": True, "false": False}
        result4 = HeaderUtils.process_headers(templates4, values4)
        assert result4["x-bool-true"] == "True"
        assert result4["x-bool-false"] == "False"

    def test_missing_variable_logs_warning(self, mocker):
        mock_logger = mocker.Mock()
        HeaderUtils._LOGGER = mock_logger
        template = "Bearer ${{missing}}"
        values = {}
        result = HeaderUtils._substitute_variables(template, values)
        assert result == "Bearer ${{missing}}"
        assert mock_logger.warning.called

    def test_process_headers_handles_excluded_headers_correctly(self, mocker):
        """Test that excluded headers are properly handled by _process_headers"""
        # Mock the excluded_headers list to ensure predictable behavior
        excluded = {"host", "x-forwarded-for", "x-real-ip"}

        mocker.patch.object(HeaderUtils, "_EXCLUDED_HEADERS", excluded)

        # Original headers contain some excluded headers
        original_headers = {
            "Host": "example.com",
            "X-Forwarded-For": "1.2.3.4",
            "Accept": "application/json",
            "User-Agent": "Test Agent",
        }

        templates = {
            "X-Real-IP": "5.6.7.8",  # Should override original even if excluded
            "Content-Type": "application/json",
            "Accept": "text/plain",  # Should override original
        }

        result = HeaderUtils.process_headers(templates, {}, original_headers)

        # Verify excluded headers are removed
        assert "host" not in result
        assert "x-forwarded-for" not in result
        assert "x-real-ip" in result

        # Verify other headers are processed correctly
        assert result["content-type"] == "application/json"
        assert result["accept"] == "text/plain"  # Override from template
        assert result["user-agent"] == "Test Agent"  # From original
        assert result["x-real-ip"] == "5.6.7.8"  # From template, not excluded

    def test_complex_variable_substitution_edge_cases(
        self,
    ):
        """Test various edge cases in variable substitution"""
        # Adjacent variables
        template1 = "${{var1}}${{var2}}"
        values1 = {"var1": "hello", "var2": "world"}
        assert HeaderUtils._substitute_variables(template1, values1) == "helloworld"

        # Nested variable-like syntax (not actually valid)
        template2 = "${{outer_$inner}}"
        values2 = {"outer_$inner": "not-nested", "inner": "value"}
        assert HeaderUtils._substitute_variables(template2, values2) == "not-nested"

        # Variable at start, middle, and end
        template3 = "${{start}} middle ${{end}}"
        values3 = {"start": "begin", "end": "finish"}
        assert (
            HeaderUtils._substitute_variables(template3, values3)
            == "begin middle finish"
        )

        # Multiple occurrences of same variable
        template4 = "${{repeat}} and ${{repeat}} and ${{repeat}}"
        values4 = {"repeat": "test"}
        assert (
            HeaderUtils._substitute_variables(template4, values4)
            == "test and test and test"
        )

        # Empty values
        template5 = "[${{empty}}]"
        values5 = {"empty": ""}
        assert HeaderUtils._substitute_variables(template5, values5) == "[]"

    def test_get_variable_value_special_cases(self):
        """Test special cases for getting variable values"""
        # Empty list
        assert HeaderUtils._get_variable_value([]) == ""

        # List with None
        assert HeaderUtils._get_variable_value([None]) == "None"

        # List with multiple values (should take first)
        assert HeaderUtils._get_variable_value([1, 2, 3]) == "1"

        # Complex object
        complex_obj = {"key": "value"}
        assert HeaderUtils._get_variable_value(complex_obj) == str(complex_obj)

        # Boolean values
        assert HeaderUtils._get_variable_value(True) == "True"
        assert HeaderUtils._get_variable_value(False) == "False"

    def test_case_insensitivity(self):
        """Test case insensitivity in header processing"""
        # Original headers with mixed case
        original = {
            "Content-Type": "application/json",
            "X-API-KEY": "original-key",
            "USER-agent": "Original Agent",
        }

        # Template headers with different case
        templates = {
            "content-type": "text/plain",
            "user-AGENT": "New Agent",
            "X-Custom": "custom-value",
        }

        result = HeaderUtils.process_headers(templates, {}, original)

        # All header names should be lowercase in result
        assert "content-type" in result
        assert "x-api-key" in result
        assert "user-agent" in result
        assert "x-custom" in result

        # Templates should override original values regardless of case
        assert result["content-type"] == "text/plain"
        assert result["user-agent"] == "New Agent"
        assert result["x-api-key"] == "original-key"
        assert result["x-custom"] == "custom-value"
