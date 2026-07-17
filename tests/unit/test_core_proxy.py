import asyncio

import pytest
from starlette.responses import Response

from nya.common.exceptions import (
    APIKeyNotConfiguredError,
    QueueFullError,
    ReachedMaxQuotaError,
    ReachedMaxRetriesError,
)
from nya.core.proxy import NyaProxyCore
from tests.unit.core_helpers import CoreConfig, make_request


@pytest.mark.asyncio
async def test_proxy_core_handles_direct_queue_and_error_paths(monkeypatch):
    config = CoreConfig()
    core = NyaProxyCore(config)

    async def fake_execute(request):
        return Response(b"ok", status_code=201)

    core.request_executor.execute = fake_execute
    request = make_request()
    config.rate_limit_enabled = False
    response = await core.handle_request(request)
    assert response.status_code == 201

    unknown = await core.handle_request(make_request("/api/missing/v1"))
    assert unknown.status_code == 404

    config.rate_limit_enabled = True
    config.allowed_methods = ["POST"]
    denied = await core.handle_request(make_request(method="GET"))
    assert denied.status_code == 405

    config.allowed_methods = ["GET"]

    async def raise_queue_full(request):
        raise QueueFullError("mock")

    core.request_queue.enqueue_request = raise_queue_full
    assert (await core.handle_request(make_request())).status_code == 503

    async def raise_timeout(request):
        future = asyncio.Future()
        return future

    core.request_queue.enqueue_request = raise_timeout
    monkeypatch.setattr(config, "get_api_default_timeout", lambda api_name=None: 0.001)
    assert (await core.handle_request(make_request())).status_code == 504


@pytest.mark.asyncio
async def test_proxy_core_maps_known_exceptions_to_responses():
    config = CoreConfig()
    core = NyaProxyCore(config)

    for exc, expected in [
        (ReachedMaxRetriesError("mock", 2), 429),
        (ReachedMaxQuotaError("mock", 3), 429),
        (APIKeyNotConfiguredError("mock"), 500),
        (RuntimeError("boom"), 500),
    ]:

        async def raise_exc(request, exc=exc):
            raise exc

        core.request_queue.enqueue_request = raise_exc
        response = await core.handle_request(make_request())
        assert response.status_code == expected
