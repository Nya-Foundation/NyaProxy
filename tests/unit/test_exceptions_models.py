import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from nya.common.exceptions import (
    APIConfigError,
    APIKeyNotConfiguredError,
    ConfigurationError,
    ConnectionError,
    EncounterUserDefinedRetry,
    EndpointRateLimitExceededError,
    MissingAPIKeyError,
    NoAvailableAPIKeyError,
    NyaProxyStatus,
    QueueFullError,
    ReachedMaxQuotaError,
    ReachedMaxRetriesError,
    RequestExpiredError,
    RequestRateLimited,
    TimeoutError,
    UnknownAPIError,
    VariablesConfigurationError,
)
from nya.common.models import ProxyRequest


@pytest.mark.parametrize(
    ("factory", "message_part", "attrs"),
    [
        (lambda: NyaProxyStatus(), "An event occurred", {}),
        (
            lambda: ConfigurationError(["bad"]),
            "configuration error",
            {"errors": ["bad"]},
        ),
        (
            lambda: VariablesConfigurationError("missing key"),
            "missing key",
            {"message": "missing key"},
        ),
        (
            lambda: EndpointRateLimitExceededError("mock", reset_in_seconds=3),
            "Rate limit exceeded",
            {"api_name": "mock", "reset_in_seconds": 3},
        ),
        (
            lambda: QueueFullError("mock"),
            "queue for mock is full",
            {"api_name": "mock"},
        ),
        (
            lambda: RequestExpiredError("mock", 1.25),
            "expired after waiting 1.2s",
            {"api_name": "mock", "wait_time": 1.25},
        ),
        (
            lambda: NoAvailableAPIKeyError("mock"),
            "No available API keys",
            {"api_name": "mock"},
        ),
        (
            lambda: APIKeyNotConfiguredError("mock"),
            "No API key found",
            {"api_name": "mock"},
        ),
        (
            lambda: MissingAPIKeyError("mock"),
            "Missing API key",
            {"api_name": "mock"},
        ),
        (
            lambda: UnknownAPIError("/api/nope"),
            "Unknown API endpoint",
            {"path": "/api/nope"},
        ),
        (
            lambda: ConnectionError("mock", "https://upstream"),
            "Connection error",
            {"api_name": "mock", "url": "https://upstream"},
        ),
        (
            lambda: TimeoutError("mock", 2.5),
            "timed out after 2.5s",
            {"api_name": "mock", "timeout": 2.5},
        ),
        (
            lambda: RequestRateLimited("mock", 4.5),
            "retry after 4.5s",
            {"api_name": "mock", "retry_after": 4.5},
        ),
        (
            lambda: EncounterUserDefinedRetry("mock", 429),
            "retry status code 429",
            {"api_name": "mock", "status_code": 429},
        ),
        (
            lambda: ReachedMaxRetriesError("mock", 3),
            "maximum retries (3)",
            {"api_name": "mock", "max_retries": 3},
        ),
        (
            lambda: ReachedMaxQuotaError("mock", 9),
            "try again in 9.0s",
            {"api_name": "mock", "wait_time": 9},
        ),
        (
            lambda: ReachedMaxQuotaError("mock"),
            "Max quota is reached",
            {"api_name": "mock", "wait_time": None},
        ),
    ],
)
def test_exception_messages_and_attributes(factory, message_part, attrs):
    exc = factory()

    assert message_part in exc.message
    for key, value in attrs.items():
        assert getattr(exc, key) == value


def test_api_config_error_inherits_base_status_message():
    exc = APIConfigError("bad api")

    assert exc.message == "bad api"


@pytest.mark.asyncio
async def test_proxy_request_from_fastapi_request_reads_body_and_client():
    app = FastAPI()

    @app.post("/capture")
    async def capture(request: Request):
        proxy_request = await ProxyRequest.from_request(request)
        return {
            "method": proxy_request.method,
            "path": proxy_request._url.path,
            "content": proxy_request.content.decode(),
            "ip_present": bool(proxy_request.ip),
        }

    response = TestClient(app).post("/capture", content="hello")

    assert response.json() == {
        "method": "POST",
        "path": "/capture",
        "content": "hello",
        "ip_present": True,
    }
