import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from nya.common.exceptions import (
    APIKeyNotConfiguredError,
    ConfigurationError,
    MissingAPIKeyError,
    NyaProxyStatus,
    QueueFullError,
    ReachedMaxQuotaError,
    ReachedMaxRetriesError,
    RequestExpiredError,
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
            lambda: ConfigurationError("just a string"),
            "just a string",
            {"errors": ["just a string"]},
        ),
        (
            lambda: VariablesConfigurationError("missing key"),
            "missing key",
            {"message": "missing key"},
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
