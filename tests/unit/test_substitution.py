import pytest

from nya.utils.substitution import (
    _check_rule_conditions,
    _contains_value,
    _process_value_references,
    _remove_field,
    _set_field,
    apply_body_substitutions,
)


def apply_one_condition(body, condition):
    return apply_body_substitutions(
        body,
        [
            {
                "name": "mark",
                "operation": "set",
                "path": "matched",
                "value": True,
                "conditions": [condition],
            }
        ],
    )


def test_invalid_or_non_json_bodies_are_returned_unchanged():
    assert apply_body_substitutions(b"{not-json", [{"name": "x"}]) == b"{not-json"
    assert apply_body_substitutions("plain text", [{"name": "x"}]) == "plain text"
    assert apply_body_substitutions(42, [{"name": "x"}]) == 42
    assert apply_body_substitutions({"a": 1}, []) == {"a": 1}


def test_malformed_rules_and_unknown_operations_are_ignored():
    body = {"a": 1}

    assert apply_body_substitutions(body, [{"operation": "set", "path": "b"}]) == body
    assert (
        apply_body_substitutions(
            body, [{"name": "missing value", "operation": "set", "path": "b"}]
        )
        == body
    )
    assert (
        apply_body_substitutions(
            body, [{"name": "unknown", "operation": "move", "path": "b"}]
        )
        == body
    )


def test_set_remove_and_legacy_operations_apply_in_order_without_mutating_input():
    original = {"model": "small", "drop": True, "items": [{"name": "old"}]}

    result = apply_body_substitutions(
        original,
        [
            {
                "name": "set nested",
                "operation": "set",
                "path": "items[1].name",
                "value": "new",
            },
            {
                "name": "add alias",
                "operation": "add",
                "path": "meta.model",
                "value": "${{model}}",
            },
            {
                "name": "replace alias",
                "operation": "replace",
                "path": "summary",
                "value": "Using ${{model}} with ${{items}}",
            },
            {"name": "remove", "operation": "remove", "path": "drop"},
        ],
    )

    assert original == {"model": "small", "drop": True, "items": [{"name": "old"}]}
    assert result["items"] == [{"name": "old"}, {"name": "new"}]
    assert result["meta"]["model"] == "small"
    assert result["summary"].startswith("Using small with ")
    assert "drop" not in result


def test_root_replacement_and_removal():
    assert apply_body_substitutions(
        {"payload": {"ok": True}},
        [{"name": "root", "operation": "set", "path": "$", "value": "${{payload}}"}],
    ) == {"ok": True}
    assert (
        apply_body_substitutions(
            [1, 2], [{"name": "remove root", "operation": "remove", "path": ""}]
        )
        == []
    )


@pytest.mark.parametrize(
    ("body", "condition"),
    [
        ({"value": "x"}, {"field": "value", "operator": "eq", "value": "x"}),
        ({"value": "x"}, {"field": "value", "operator": "ne", "value": "y"}),
        ({"value": 3}, {"field": "value", "operator": "gt", "value": 2}),
        ({"value": 3}, {"field": "value", "operator": "lt", "value": 4}),
        ({"value": 3}, {"field": "value", "operator": "ge", "value": 3}),
        ({"value": 3}, {"field": "value", "operator": "le", "value": 3}),
        ({"value": "a"}, {"field": "value", "operator": "in", "value": ["a", "b"]}),
        ({"value": "c"}, {"field": "value", "operator": "nin", "value": ["a", "b"]}),
        ({"value": "hello"}, {"field": "value", "operator": "like", "value": "he%o"}),
        ({"value": "hello"}, {"field": "value", "operator": "nlike", "value": "bye%"}),
        (
            {"value": ["a", "b"]},
            {"field": "value", "operator": "contains", "value": "a"},
        ),
        ({"value": "hello"}, {"field": "value", "operator": "ncontains", "value": "z"}),
        ({"value": 5}, {"field": "value", "operator": "between", "value": [1, 10]}),
        ({"value": 15}, {"field": "value", "operator": "nbetween", "value": [1, 10]}),
        (
            {"value": "hello"},
            {"field": "value", "operator": "startswith", "value": "he"},
        ),
        ({"value": "hello"}, {"field": "value", "operator": "endswith", "value": "lo"}),
        ({"value": ""}, {"field": "value", "operator": "exists"}),
        ({}, {"field": "missing", "operator": "nexists"}),
        ({"value": None}, {"field": "value", "operator": "isnull"}),
        ({"value": 0}, {"field": "value", "operator": "notnull"}),
    ],
)
def test_conditions_that_match_apply_rule(body, condition):
    assert apply_one_condition(body, condition)["matched"] is True


@pytest.mark.parametrize(
    ("body", "condition"),
    [
        ({"value": "x"}, {"field": "value", "operator": "eq", "value": "y"}),
        ({"value": "x"}, {"field": "value", "operator": "ne", "value": "x"}),
        ({"value": "3"}, {"field": "value", "operator": "gt", "value": 2}),
        ({"value": 3}, {"field": "value", "operator": "lt", "value": 2}),
        ({"value": 2}, {"field": "value", "operator": "ge", "value": 3}),
        ({"value": 4}, {"field": "value", "operator": "le", "value": 3}),
        ({"value": "a"}, {"field": "value", "operator": "in", "value": "a"}),
        ({"value": "a"}, {"field": "value", "operator": "nin", "value": ["a"]}),
        ({"value": 1}, {"field": "value", "operator": "like", "value": "%"}),
        ({"value": "hello"}, {"field": "value", "operator": "nlike", "value": "%"}),
        ({"value": ["a"]}, {"field": "value", "operator": "contains", "value": "b"}),
        (
            {"value": {"a": 1}},
            {"field": "value", "operator": "ncontains", "value": "a"},
        ),
        ({"value": 5}, {"field": "value", "operator": "between", "value": [6, 10]}),
        ({"value": 5}, {"field": "value", "operator": "nbetween", "value": [1, 10]}),
        (
            {"value": "hello"},
            {"field": "value", "operator": "startswith", "value": "x"},
        ),
        ({"value": "hello"}, {"field": "value", "operator": "endswith", "value": "x"}),
        ({}, {"field": "missing", "operator": "exists"}),
        ({"value": ""}, {"field": "value", "operator": "nexists"}),
        ({"value": 0}, {"field": "value", "operator": "isnull"}),
        ({"value": None}, {"field": "value", "operator": "notnull"}),
        ({"value": 1}, {"field": "[", "operator": "exists"}),
    ],
)
def test_conditions_that_do_not_match_skip_rule(body, condition):
    assert "matched" not in apply_one_condition(body, condition)


def test_invalid_paths_and_impossible_list_navigation_are_noops():
    body = {"items": [{"name": "a"}], "scalar": 1}

    assert (
        apply_body_substitutions(
            body,
            [
                {
                    "name": "bad list path",
                    "operation": "set",
                    "path": "items.name",
                    "value": "x",
                }
            ],
        )
        == body
    )
    assert (
        apply_body_substitutions(
            body,
            [{"name": "bad remove path", "operation": "remove", "path": "items.name"}],
        )
        == body
    )
    assert (
        apply_body_substitutions(
            body,
            [
                {
                    "name": "bad scalar path",
                    "operation": "set",
                    "path": "scalar.name",
                    "value": "x",
                }
            ],
        )
        == body
    )


def test_value_references_handle_missing_invalid_nested_and_binary_json_values():
    result = apply_body_substitutions(
        b'{"source":{"name":"nya"},"items":[1,2]}',
        [
            {
                "name": "refs",
                "operation": "set",
                "path": "derived",
                "value": {
                    "direct": "${{source.name}}",
                    "missing": "${{missing.value}}",
                    "embedded": "items=${{items}} bad=${{[}}",
                },
            }
        ],
    )

    assert result["derived"]["direct"] == "nya"
    assert result["derived"]["missing"] is None
    assert result["derived"]["embedded"] == "items=[1, 2] bad="


def test_private_helpers_cover_navigation_and_error_edges(monkeypatch):
    assert _check_rule_conditions({"a": 1}, [{"field": "a"}]) is True
    assert (
        _check_rule_conditions(
            {"a": 1}, [{"field": "a", "operator": "gt", "value": "bad"}]
        )
        is False
    )

    assert _contains_value("abc", "b") is True
    assert _contains_value(("a", "b"), "b") is True
    assert _contains_value({"a": 1}, "a") is True
    assert _contains_value(3, 3) is True

    assert _set_field({"items": []}, "items[2]", "x") == {"items": [None, None, "x"]}
    assert _set_field([], "1.name", "nya") == [{}, {"name": "nya"}]
    assert _set_field({"a": 1}, ".", "ignored") == {"a": 1}
    assert _set_field({"items": []}, "items.name.value", "x") == {"items": []}

    assert _remove_field({"items": ["a", "b"]}, "items[1]") == {"items": ["a"]}
    assert _remove_field({"items": ["a"]}, "items.name") == {"items": ["a"]}
    assert _remove_field({"items": [{"x": 1}]}, "items[0].x") == {"items": [{}]}
    assert _remove_field({"items": [1]}, "items[0].x") == {"items": [1]}
    assert _remove_field({"items": [1]}, "items[0].x[") == {"items": [1]}

    assert _process_value_references(["${{a}}", 2], {"a": 1}) == [1, 2]
    assert _process_value_references("${{[}}", {"a": 1}) is None
    assert _process_value_references("plain", {"a": 1}) == "plain"

    def broken_sub(*args, **kwargs):
        raise RuntimeError("regex broke")

    monkeypatch.setattr("nya.utils.substitution.re.sub", broken_sub)
    assert _process_value_references("x ${{a}}", {"a": 1}) == "x ${{a}}"


def test_apply_continues_when_operation_raises(monkeypatch):
    def broken_set(*args, **kwargs):
        raise RuntimeError("set failed")

    monkeypatch.setattr("nya.utils.substitution._set_field", broken_set)

    assert apply_body_substitutions(
        {"a": 1},
        [
            {"name": "broken", "operation": "set", "path": "b", "value": 2},
            {"name": "ignored", "operation": "unknown", "path": "c"},
        ],
    ) == {"a": 1}
