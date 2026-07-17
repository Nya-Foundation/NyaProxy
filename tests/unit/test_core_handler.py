import pytest

from nya.common.exceptions import (
    MissingAPIKeyError,
    VariablesConfigurationError,
)
from nya.core.handler import RequestHandler
from nya.utils.header import HeaderUtils
from tests.unit.core_helpers import CoreConfig, make_request


def test_handler_prepares_requests_aliases_priority_and_rate_limit_paths():
    config = CoreConfig()
    handler = RequestHandler(config)
    request = make_request(
        "/api/alias/v1/chat",
        headers={
            "authorization": "Bearer master",
            "x-forwarded-for": "203.0.113.10",
        },
    )

    handler.prepare_request(request)

    assert request.api_name == "mock"
    assert request.url == "https://upstream.test/v1/chat"
    assert request.ip == "203.0.113.10"
    assert request.user == "master"
    assert request.priority == 2
    assert request._rate_limited is True


def _policy_denial(handler, path, method="GET"):
    request = make_request(path, method)
    handler.prepare_request(request)
    return handler.validate_request_policy(request)


@pytest.mark.parametrize(
    ("path", "method", "denied_status"),
    [
        ("/api/mock/v1/chat", "GET", None),
        ("/api/mock/v2/chat", "GET", 403),
        ("/api/mock/v1/chat", "DELETE", 405),
    ],
)
def test_handler_request_allowlist(path, method, denied_status):
    denial = _policy_denial(RequestHandler(CoreConfig()), path, method)
    if denied_status is None:
        assert denial is None
    else:
        assert denial[0] == denied_status


@pytest.mark.parametrize("path", ["/not-api/mock", "/api/unknown/v1", "/api/"])
def test_handler_unknown_paths_resolve_to_no_api(path):
    handler = RequestHandler(CoreConfig())
    request = make_request(path)
    handler.prepare_request(request)
    assert request.api_name is None


def test_handler_blacklist_mode_and_rate_limit_path_matching():
    config = CoreConfig()
    config.allowed_mode = "blacklist"
    config.allowed_paths = ["/v1/private"]
    config.rate_limit_paths = ["/v1/limited/*"]
    handler = RequestHandler(config)

    assert _policy_denial(handler, "/api/mock/v1/public") is None
    assert _policy_denial(handler, "/api/mock/v1/private")[0] == 403
    assert handler.should_enforce_rate_limit("mock", "/v1/limited/chat") is True
    assert handler.should_enforce_rate_limit("mock", "/v1/free") is False
    config.rate_limit_enabled = False
    assert handler.should_enforce_rate_limit("mock", "/v1/limited/chat") is False


@pytest.mark.asyncio
async def test_handler_process_headers_and_json_body_substitution():
    config = CoreConfig()
    config.headers = {
        "Authorization": "Bearer ${{api_key}}",
        "X-Region": "${{region}}",
    }
    config.body_substitution_enabled = True
    config.body_rules = [
        {"name": "set", "operation": "set", "path": "extra", "value": 1}
    ]
    handler = RequestHandler(config)
    request = make_request(
        method="POST",
        headers={"content-type": "application/json"},
        content=b'{"ok": true}',
    )
    request.api_name = "mock"
    request.url = "https://upstream.test/v1/chat"
    request.api_key = "key-a"

    await handler.process_request_headers(request)
    handler.process_request_body(request)

    assert request.headers["authorization"] == "Bearer key-a"
    assert request.headers["x-region"] == "us"
    assert request.headers["host"] == "upstream.test"
    assert request.content == b'{"ok":true,"extra":1}'


@pytest.mark.asyncio
async def test_handler_process_headers_reports_missing_and_bad_variable_config():
    config = CoreConfig()
    handler = RequestHandler(config)
    request = make_request()
    request.api_name = "mock"
    request.url = "https://upstream.test/v1/chat"

    with pytest.raises(MissingAPIKeyError):
        await handler.process_request_headers(request)

    request.api_key = "key-a"
    original_process_headers = HeaderUtils.process_headers
    HeaderUtils.process_headers = staticmethod(
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad template"))
    )
    with pytest.raises(VariablesConfigurationError):
        try:
            await handler.process_request_headers(request)
        finally:
            HeaderUtils.process_headers = original_process_headers
