import json
import time
from typing import Any, Dict, List, Union
from unittest import mock

import pytest

from nya_proxy.common.utils import (
    _check_rule_conditions,
    _contains_value,
    _like_match,
    _mask_api_key,
    _process_value_references,
    _remove_field,
    _set_field,
    apply_body_substitutions,
    decode_content,
    format_elapsed_time,
    json_safe_dumps,
)


class TestMaskApiKey:
    def test_none_key(self):
        assert _mask_api_key(None) == "unknown"

    def test_empty_key(self):
        assert _mask_api_key("") == "unknown"

    def test_short_key(self):
        assert _mask_api_key("1234") == "****"
        assert _mask_api_key("12345678") == "********"

    def test_long_key(self):
        assert _mask_api_key("1234567890abcdef") == "1234...cdef"

    def test_non_string_key(self):
        assert _mask_api_key(12345) == "invalid_key_format"


class TestFormatElapsedTime:
    def test_microseconds(self):
        assert format_elapsed_time(0.0005) == "500μs"

    def test_milliseconds(self):
        assert format_elapsed_time(0.123) == "123ms"

    def test_seconds(self):
        assert format_elapsed_time(1.234) == "1.23s"

    def test_minutes(self):
        assert format_elapsed_time(123.4) == "2m 3.4s"

    def test_hours(self):
        assert format_elapsed_time(3661.0) == "1h 1m"


class TestDecodeContent:
    def test_none_encoding(self):
        content = b"test content"
        assert decode_content(content, None) == content

    def test_identity_encoding(self):
        content = b"test content"
        assert decode_content(content, "identity") == content

    @mock.patch("gzip.decompress")
    def test_gzip_encoding(self, mock_decompress):
        content = b"gzipped content"
        expected = b"decoded content"
        mock_decompress.return_value = expected
        assert decode_content(content, "gzip") == expected
        mock_decompress.assert_called_once_with(content)

    @mock.patch("zlib.decompress")
    def test_deflate_encoding(self, mock_decompress):
        content = b"deflated content"
        expected = b"decoded content"
        mock_decompress.return_value = expected
        assert decode_content(content, "deflate") == expected
        mock_decompress.assert_called_once_with(content)

    @mock.patch("brotli.decompress")
    def test_brotli_encoding(self, mock_decompress):
        content = b"brotli content"
        expected = b"decoded content"
        mock_decompress.return_value = expected
        assert decode_content(content, "br") == expected
        mock_decompress.assert_called_once_with(content)

    def test_unknown_encoding(self):
        content = b"unknown encoding"
        assert decode_content(content, "unknown") == content

    @mock.patch("gzip.decompress", side_effect=Exception("Decompression error"))
    def test_decoding_error(self, mock_decompress):
        content = b"invalid gzip content"
        assert decode_content(content, "gzip") == content


class TestJsonSafeDumps:
    def test_regular_dict(self):
        obj = {"name": "test", "count": 123}
        result = json_safe_dumps(obj)
        assert json.loads(result) == obj

    def test_nested_dict(self):
        obj = {"data": {"name": "test", "count": 123}, "valid": True}
        result = json_safe_dumps(obj)
        assert json.loads(result) == obj

    def test_non_json_string(self):
        obj = "This is not a JSON string"
        result = json_safe_dumps(obj)
        assert result == obj

    def test_json_with_custom_indent(self):
        obj = {"name": "test", "count": 123}
        result = json_safe_dumps(obj, indent=2)
        assert "  " in result  # Check for 2-space indentation


class TestApplyBodySubstitutions:
    def test_no_rules(self):
        body = {"name": "test", "count": 123}
        assert apply_body_substitutions(body, []) == body

    def test_invalid_body(self):
        body = "not a valid JSON"
        assert apply_body_substitutions(body, []) == body

    def test_set_operation(self):
        body = {"name": "test", "count": 123}
        rules = [
            {"name": "Set Value", "operation": "set", "path": "count", "value": 456}
        ]
        expected = {"name": "test", "count": 456}
        assert apply_body_substitutions(body, rules) == expected

    def test_remove_operation(self):
        body = {"name": "test", "count": 123}
        rules = [{"name": "Remove Field", "operation": "remove", "path": "count"}]
        expected = {"name": "test"}
        assert apply_body_substitutions(body, rules) == expected

    def test_set_operation_with_condition_match(self):
        body = {"name": "test", "count": 123}
        rules = [
            {
                "name": "Conditional Set",
                "operation": "set",
                "path": "count",
                "value": 456,
                "conditions": [{"field": "name", "operator": "eq", "value": "test"}],
            }
        ]
        expected = {"name": "test", "count": 456}
        assert apply_body_substitutions(body, rules) == expected

    def test_set_operation_with_condition_no_match(self):
        body = {"name": "test", "count": 123}
        rules = [
            {
                "name": "Conditional Set",
                "operation": "set",
                "path": "count",
                "value": 456,
                "conditions": [{"field": "name", "operator": "eq", "value": "other"}],
            }
        ]
        expected = {"name": "test", "count": 123}
        assert apply_body_substitutions(body, rules) == expected

    def test_missing_required_fields(self):
        body = {"name": "test", "count": 123}
        rules = [{"name": "Missing Path", "operation": "set", "value": 456}]
        expected = {"name": "test", "count": 123}
        assert apply_body_substitutions(body, rules) == expected

    def test_legacy_operations(self):
        body = {"name": "test", "count": 123}
        rules = [
            {
                "name": "Add Field",
                "operation": "add",
                "path": "new_field",
                "value": "new value",
            },
            {
                "name": "Replace Field",
                "operation": "replace",
                "path": "count",
                "value": 456,
            },
        ]
        expected = {"name": "test", "count": 456, "new_field": "new value"}
        assert apply_body_substitutions(body, rules) == expected

    def test_string_input_body(self):
        body = json.dumps({"name": "test", "count": 123})
        rules = [
            {"name": "Set Value", "operation": "set", "path": "count", "value": 456}
        ]
        expected = {"name": "test", "count": 456}
        assert apply_body_substitutions(body, rules) == expected


class TestCheckRuleConditions:
    def test_eq_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "eq", "value": "test"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_eq_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "eq", "value": "other"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_ne_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "ne", "value": "other"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_ne_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "ne", "value": "test"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_gt_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "gt", "value": 100}]
        assert _check_rule_conditions(body, conditions) is True

    def test_gt_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "gt", "value": 200}]
        assert _check_rule_conditions(body, conditions) is False

    def test_lt_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "lt", "value": 200}]
        assert _check_rule_conditions(body, conditions) is True

    def test_lt_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "lt", "value": 100}]
        assert _check_rule_conditions(body, conditions) is False

    def test_ge_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "ge", "value": 123}]
        assert _check_rule_conditions(body, conditions) is True

    def test_le_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "le", "value": 123}]
        assert _check_rule_conditions(body, conditions) is True

    def test_in_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "in", "value": ["test", "other"]}]
        assert _check_rule_conditions(body, conditions) is True

    def test_in_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [
            {"field": "name", "operator": "in", "value": ["other", "another"]}
        ]
        assert _check_rule_conditions(body, conditions) is False

    def test_nin_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [
            {"field": "name", "operator": "nin", "value": ["other", "another"]}
        ]
        assert _check_rule_conditions(body, conditions) is True

    def test_nin_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "nin", "value": ["test", "other"]}]
        assert _check_rule_conditions(body, conditions) is False

    def test_like_operator_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "like", "value": "test_%"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_like_operator_no_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "like", "value": "other_%"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_nlike_operator_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "nlike", "value": "other_%"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_nlike_operator_no_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "nlike", "value": "test_%"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_contains_operator_match(self):
        body = {"name": "test_value", "count": 123, "tags": ["tag1", "tag2"]}
        conditions = [
            {"field": "name", "operator": "contains", "value": "value"},
            {"field": "tags", "operator": "contains", "value": "tag1"},
        ]
        assert _check_rule_conditions(body, conditions) is True

    def test_contains_operator_no_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "contains", "value": "other"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_ncontains_operator_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "ncontains", "value": "other"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_between_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "between", "value": [100, 200]}]
        assert _check_rule_conditions(body, conditions) is True

    def test_between_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "between", "value": [200, 300]}]
        assert _check_rule_conditions(body, conditions) is False

    def test_nbetween_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "nbetween", "value": [200, 300]}]
        assert _check_rule_conditions(body, conditions) is True

    def test_startswith_operator_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "startswith", "value": "test"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_startswith_operator_no_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "startswith", "value": "value"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_endswith_operator_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "endswith", "value": "value"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_endswith_operator_no_match(self):
        body = {"name": "test_value", "count": 123}
        conditions = [{"field": "name", "operator": "endswith", "value": "test"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_exists_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "exists"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_exists_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "missing", "operator": "exists"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_nexists_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "missing", "operator": "nexists"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_nexists_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "name", "operator": "nexists"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_isnull_operator_match(self):
        body = {"name": "test", "count": None}
        conditions = [{"field": "count", "operator": "isnull"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_isnull_operator_no_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "isnull"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_notnull_operator_match(self):
        body = {"name": "test", "count": 123}
        conditions = [{"field": "count", "operator": "notnull"}]
        assert _check_rule_conditions(body, conditions) is True

    def test_notnull_operator_no_match(self):
        body = {"name": "test", "count": None}
        conditions = [{"field": "count", "operator": "notnull"}]
        assert _check_rule_conditions(body, conditions) is False

    def test_multiple_conditions_all_match(self):
        body = {"name": "test", "count": 123, "active": True}
        conditions = [
            {"field": "name", "operator": "eq", "value": "test"},
            {"field": "count", "operator": "gt", "value": 100},
            {"field": "active", "operator": "eq", "value": True},
        ]
        assert _check_rule_conditions(body, conditions) is True

    def test_multiple_conditions_one_fails(self):
        body = {"name": "test", "count": 123, "active": True}
        conditions = [
            {"field": "name", "operator": "eq", "value": "test"},
            {"field": "count", "operator": "gt", "value": 200},  # This fails
            {"field": "active", "operator": "eq", "value": True},
        ]
        assert _check_rule_conditions(body, conditions) is False

    def test_invalid_condition_format(self):
        body = {"name": "test", "count": 123}
        conditions = [{"invalid": "condition"}]  # Missing required fields
        assert (
            _check_rule_conditions(body, conditions) is True
        )  # Invalid conditions are skipped


class TestSetField:
    def test_simple_set(self):
        body = {"name": "test", "count": 123}
        result = _set_field(body, "count", 456)
        expected = {"name": "test", "count": 456}
        assert result == expected

    def test_nested_set(self):
        body = {"user": {"name": "test", "details": {"age": 30}}}
        result = _set_field(body, "user.details.age", 35)
        expected = {"user": {"name": "test", "details": {"age": 35}}}
        assert result == expected

    def test_create_nested_path(self):
        body = {"user": {"name": "test"}}
        result = _set_field(body, "user.details.age", 35)
        expected = {"user": {"name": "test", "details": {"age": 35}}}
        assert result == expected

    def test_array_index_set(self):
        body = {"items": [{"id": 1}, {"id": 2}]}
        result = _set_field(body, "items[1].id", 3)
        expected = {"items": [{"id": 1}, {"id": 3}]}
        assert result == expected

    def test_array_append(self):
        body = {"items": [{"id": 1}]}
        result = _set_field(body, "items[1]", {"id": 2})
        expected = {"items": [{"id": 1}, {"id": 2}]}
        assert result == expected

    def test_root_replacement(self):
        body = {"name": "test", "count": 123}
        result = _set_field(body, "$", {"new": "value"})
        expected = {"new": "value"}
        assert result == expected

    def test_empty_path(self):
        body = {"name": "test", "count": 123}
        result = _set_field(body, "", {"new": "value"})
        expected = {"new": "value"}
        assert result == expected


class TestRemoveField:
    def test_simple_remove(self):
        body = {"name": "test", "count": 123}
        result = _remove_field(body, "count")
        expected = {"name": "test"}
        assert result == expected

    def test_nested_remove(self):
        body = {"user": {"name": "test", "details": {"age": 30}}}
        result = _remove_field(body, "user.details.age")
        expected = {"user": {"name": "test", "details": {}}}
        assert result == expected

    def test_non_existent_path(self):
        body = {"name": "test", "count": 123}
        result = _remove_field(body, "missing")
        assert result == body  # No change expected

    def test_array_index_remove(self):
        body = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
        result = _remove_field(body, "items[1]")
        expected = {"items": [{"id": 1}, {"id": 3}]}
        assert result == expected

    def test_root_removal(self):
        body = {"name": "test", "count": 123}
        result = _remove_field(body, "$")
        assert result == {}  # Empty object after root removal

    def test_empty_path(self):
        body = {"name": "test", "count": 123}
        result = _remove_field(body, "")
        assert result == {}  # Empty object after root removal


class TestLikeMatch:
    def test_exact_match(self):
        assert _like_match("test", "test") is True

    def test_wildcard_beginning(self):
        assert _like_match("test_value", "%value") is True
        assert _like_match("wrong_test", "%value") is False

    def test_wildcard_end(self):
        assert _like_match("test_value", "test%") is True
        assert _like_match("value_test", "test%") is False

    def test_wildcard_middle(self):
        assert _like_match("test_value_extra", "test%extra") is True
        assert _like_match("test_wrong_extra", "test%value%") is False

    def test_single_character_wildcard(self):
        assert _like_match("test", "t_st") is True
        assert _like_match("txt", "t_t") is True
        assert _like_match("tesst", "t__t") is False


class TestContainsValue:
    def test_string_contains(self):
        assert _contains_value("test_value", "value") is True
        assert _contains_value("test_value", "missing") is False

    def test_list_contains(self):
        assert _contains_value(["item1", "item2", "item3"], "item2") is True
        assert _contains_value(["item1", "item2", "item3"], "item4") is False

    def test_dict_contains_key(self):
        assert _contains_value({"key1": "value1", "key2": "value2"}, "key1") is True
        assert _contains_value({"key1": "value1", "key2": "value2"}, "key3") is False

    def test_other_types(self):
        assert _contains_value(123, 123) is True  # Same value
        assert _contains_value(123, 456) is False  # Different value


class TestProcessValueReferences:
    def test_direct_reference(self):
        body = {"name": "test", "count": 123}
        value = "${{name}}"
        assert _process_value_references(value, body) == "test"

    def test_nested_reference(self):
        body = {"user": {"name": "test", "details": {"age": 30}}}
        value = "${{user.details.age}}"
        assert _process_value_references(value, body) == 30

    def test_string_interpolation(self):
        body = {"name": "test", "count": 123}
        value = "User ${{name}} has count ${{count}}"
        assert _process_value_references(value, body) == "User test has count 123"

    def test_missing_reference(self):
        body = {"name": "test", "count": 123}
        value = "${{missing}}"
        assert _process_value_references(value, body) is None

    def test_object_reference(self):
        body = {"user": {"name": "test", "age": 30}}
        value = "${{user}}"
        assert _process_value_references(value, body) == {"name": "test", "age": 30}

    def test_array_reference(self):
        body = {"items": [1, 2, 3]}
        value = "${{items}}"
        assert _process_value_references(value, body) == [1, 2, 3]

    def test_reference_in_object(self):
        body = {"name": "test", "count": 123}
        value = {"user": "${{name}}", "value": "${{count}}"}
        assert _process_value_references(value, body) == {"user": "test", "value": 123}

    def test_reference_in_array(self):
        body = {"name": "test", "count": 123}
        value = ["${{name}}", "${{count}}"]
        assert _process_value_references(value, body) == ["test", 123]

    def test_complex_nested_references(self):
        body = {"user": {"name": "test", "age": 30}, "items": [{"id": 1}, {"id": 2}]}
        value = {
            "name": "${{user.name}}",
            "details": {"age": "${{user.age}}", "first_item": "${{items[0]}}"},
        }
        expected = {"name": "test", "details": {"age": 30, "first_item": {"id": 1}}}
        assert _process_value_references(value, body) == expected

    def test_object_in_string_interpolation(self):
        body = {"user": {"name": "test", "age": 30}}
        value = "User details: ${{user}}"
        assert (
            _process_value_references(value, body)
            == 'User details: {"name": "test", "age": 30}'
        )
