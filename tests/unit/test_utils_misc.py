import pytest
from httpx import Headers

from nya.utils.formatting import format_elapsed_time, json_safe_dumps
from nya.utils.header import HeaderUtils
from nya.utils.redaction import mask_secret, redact_sensitive_data
from tests.unit.core_helpers import make_request


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"x-forwarded-for": "203.0.113.1, 10.0.0.1"}, "203.0.113.1"),
        ({"x-real-ip": "2001:db8::1"}, "2001:db8::1"),
        ({"forwarded": 'for="[2001:db8::2]";proto=https'}, "2001:db8::2"),
        ({}, None),
    ],
)
def test_header_utils_parse_source_ip(headers, expected):
    assert HeaderUtils.parse_source_ip_address(Headers(headers)) == expected


def test_header_utils_templates_filter_and_merge_headers():
    processed = HeaderUtils.process_headers(
        {"X-Key": "${{ key }}", "X-List": "${{ values }}", "X-None": None},
        {"key": "secret", "values": ["first", "second"]},
        original_headers={
            "Authorization": "Bearer gateway-secret",
            "Connection": "close",
            "Transfer-Encoding": "chunked",
            "X-Original": "yes",
        },
    )
    merged = HeaderUtils.merge_headers(
        Headers({"X-Original": "old", "Keep-Alive": "timeout=5"}), processed
    )

    assert HeaderUtils.extract_required_variables(
        {"x": "${{ key }} ${{ values }}"}
    ) == {
        "key",
        "values",
    }
    assert processed["X-Key"] == "secret"
    assert processed["X-List"] == "first"
    assert "connection" not in processed
    assert "authorization" not in processed
    assert "transfer-encoding" not in processed
    assert merged["X-Original"] == "yes"
    assert "connection" not in processed


def test_header_utils_trusted_proxy_cidrs():
    assert HeaderUtils.is_trusted_proxy("10.1.2.3", ["10.0.0.0/8"]) is True
    assert HeaderUtils.is_trusted_proxy("2001:db8::1", ["2001:db8::/32"]) is True
    assert HeaderUtils.is_trusted_proxy("192.0.2.1", ["10.0.0.0/8"]) is False
    assert HeaderUtils.is_trusted_proxy("invalid", ["0.0.0.0/0"]) is False


def test_proxy_request_ordering_and_helpers():
    first = make_request()
    second = make_request()
    first.priority = 1
    second.priority = 3
    second.added_at = first.added_at - 10

    assert first < second
    assert (
        json_safe_dumps({"payload": b'{"ok":true}'}, indent=None)
        == '{"payload": {"ok": true}}'
    )
    assert json_safe_dumps({"payload": b"\xff"}, indent=None).startswith("{")
    assert json_safe_dumps(object()).startswith("<object object")
    assert format_elapsed_time(0.000001).endswith("μs")
    assert format_elapsed_time(0.2) == "200ms"
    assert format_elapsed_time(2) == "2.00s"
    assert format_elapsed_time(61) == "1m 1.0s"
    assert format_elapsed_time(3660) == "1h 1m"
    assert mask_secret(None) == "unknown_secret"
    assert mask_secret("short") == "*****"
    assert redact_sensitive_data([{"token": "123456789"}]) == [{"token": "1234...6789"}]
