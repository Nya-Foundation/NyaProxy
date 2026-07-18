import asyncio
import time
from types import SimpleNamespace

import pytest
from starlette.responses import Response

from nya.common.exceptions import (
    QueueFullError,
    ReachedMaxQuotaError,
    ReachedMaxRetriesError,
    RequestExpiredError,
)
from nya.core.control import TrafficManager
from nya.core.queue import RequestQueue
from tests.unit.core_helpers import CoreConfig, make_request


@pytest.mark.asyncio
async def test_queue_rejects_full_or_over_quota_requests():
    config = CoreConfig()
    config.queue_size = 0
    queue = RequestQueue(config, TrafficManager(config))
    request = make_request()
    request.api_name = "mock"

    with pytest.raises(QueueFullError):
        await queue.enqueue_request(request)

    for task in queue._worker_tasks.get("mock", []):
        task.cancel()
    await asyncio.gather(*queue._worker_tasks.get("mock", []), return_exceptions=True)

    config.queue_size = 10
    config.queue_expiry = 0.01
    queue = RequestQueue(config, TrafficManager(config))
    queue._check_for_proxy_limit = lambda api_name, request: asyncio.sleep(0, result=1)
    request = make_request()
    request.api_name = "mock"
    request._rate_limited = True
    request.future = asyncio.Future()

    assert await queue._wait_for_key("mock", request) is None
    with pytest.raises(ReachedMaxQuotaError):
        request.future.result()


@pytest.mark.asyncio
async def test_queue_enqueue_success_waits_records_metrics_and_reuses_workers(
    monkeypatch,
):
    config = CoreConfig()
    control = TrafficManager(config)
    metrics = SimpleNamespace(
        hits=[],
        queues=[],
        record_rate_limit_hit=lambda api: metrics.hits.append(api),
        record_queue_hit=lambda api: metrics.queues.append(api),
    )
    queue = RequestQueue(config, control, metrics)
    request = make_request()
    request.api_name = "mock"
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    async def fake_proxy_limit(api_name, request):
        return 0.01

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    queue._check_for_proxy_limit = fake_proxy_limit

    future = await queue.enqueue_request(request, priority=1)
    await queue._setup_endpoint_processor("mock")

    assert future is request.future
    assert request.priority == 1
    assert sleeps == []
    assert metrics.hits == []
    assert metrics.queues == ["mock"]
    assert queue.get_all_queue_sizes()["mock"] == 1

    for task in queue._worker_tasks["mock"]:
        task.cancel()
    await asyncio.gather(*queue._worker_tasks["mock"], return_exceptions=True)


@pytest.mark.asyncio
async def test_queue_processor_loop_handles_no_processor_expiry_success_and_errors(
    monkeypatch,
):
    config = CoreConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config, control)

    await queue._process_api_queue("mock")

    queue._queues["mock"] = asyncio.PriorityQueue()

    expired = make_request()
    expired.api_name = "mock"
    expired.future = asyncio.Future()
    expired.added_at = time.time() - 10
    await queue._queues["mock"].put(expired)
    queue.register_processor(
        lambda request: asyncio.sleep(0, result=Response(status_code=200))
    )
    task = asyncio.create_task(queue._process_api_queue("mock"))
    with pytest.raises(RequestExpiredError):
        await asyncio.wait_for(expired.future, timeout=1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    successful = make_request()
    successful.api_name = "mock"
    successful.future = asyncio.Future()
    queue._check_for_resource_limit = lambda api_name, **kwargs: asyncio.sleep(
        0, result=("key-a", 0)
    )
    await queue._queues["mock"].put(successful)
    task = asyncio.create_task(queue._process_api_queue("mock"))
    assert (await asyncio.wait_for(successful.future, timeout=1)).status_code == 200
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    errored = make_request()
    errored.api_name = "mock"
    errored.future = asyncio.Future()

    async def bad_worker(api_name, request):
        raise RuntimeError("worker failed")

    async def short_sleep(delay):
        raise asyncio.CancelledError()

    queue._process_with_worker = bad_worker
    monkeypatch.setattr(asyncio, "sleep", short_sleep)
    await queue._queues["mock"].put(errored)
    with pytest.raises(asyncio.CancelledError):
        await queue._process_api_queue("mock")


@pytest.mark.asyncio
async def test_queue_processes_success_failure_retry_and_expiry(monkeypatch):
    config = CoreConfig()
    config.retry_enabled = True
    config.retry_after = 0
    control = TrafficManager(config)
    queue = RequestQueue(config, control)
    queue._queues["mock"] = asyncio.PriorityQueue()

    success = make_request()
    success.api_name = "mock"
    success.api_key = "key-a"
    success.future = asyncio.Future()
    queue.register_processor(
        lambda request: asyncio.sleep(0, result=Response(status_code=200))
    )
    await queue._process_with_worker("mock", success)
    assert success.future.result().status_code == 200

    failing = make_request()
    failing.api_name = "mock"
    failing.api_key = "key-a"
    failing.future = asyncio.Future()
    queue.register_processor(
        lambda request: asyncio.sleep(0, result=Response(status_code=500))
    )
    await queue._process_with_worker("mock", failing)
    assert failing.future.result().status_code == 500

    retrying = make_request()
    retrying.api_name = "mock"
    retrying.api_key = "key-a"
    retrying.future = asyncio.Future()
    retrying.attempts = 1
    monkeypatch.setattr("nya.core.queue.random.uniform", lambda a, b: 0)
    handled = await queue._handle_user_defined_retry(retrying, 429)
    assert handled is True
    assert await queue._queues["mock"].get() is retrying

    exhausted = make_request()
    exhausted.api_name = "mock"
    exhausted.api_key = "key-a"
    exhausted.future = asyncio.Future()
    exhausted.attempts = 2
    await queue._handle_retry(exhausted, 0)
    with pytest.raises(ReachedMaxRetriesError):
        exhausted.future.result()

    expired = make_request()
    expired.api_name = "mock"
    expired.added_at = time.time() - 10
    assert queue._is_request_expired(expired) is True

    done = make_request()
    done.api_name = "mock"
    done.future = asyncio.Future()
    done.future.set_result(Response())
    await queue._handle_retry(done, 0)

    config.retry_enabled = False
    assert await queue._handle_user_defined_retry(done, 429) is False
    config.retry_enabled = True
    config.retry_methods = ["POST"]
    assert await queue._handle_user_defined_retry(done, 429) is False
    config.retry_methods = ["GET"]
    assert await queue._handle_user_defined_retry(done, 200) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_configured_upstream_status_temporarily_blocks_selected_key(status_code):
    config = CoreConfig()
    config.key_blocking_enabled = True
    config.key_blocking_status_codes = [401, 403]
    config.key_blocking_duration = 30
    control = TrafficManager(config)
    queue = RequestQueue(config, control)

    request = make_request()
    request.api_name = "mock"
    request.api_key = "key-a"
    request.future = asyncio.Future()
    queue.register_processor(
        lambda request: asyncio.sleep(0, result=Response(status_code=status_code))
    )

    before = time.time()
    await queue._process_with_worker("mock", request)

    assert request.future.result().status_code == status_code
    blocked_key = control.get_key_limiter("mock", "key-a")
    assert blocked_key.blocked_until >= before + 30
    assert blocked_key.locked is False
    assert await control.acquire_key("mock", enforce_rate_limits=False) == ("key-b", 0)


@pytest.mark.asyncio
async def test_key_blocking_ignores_unconfigured_status_and_disabled_policy():
    config = CoreConfig()
    config.key_blocking_status_codes = [403]
    control = TrafficManager(config)
    queue = RequestQueue(config, control)

    request = make_request()
    request.api_name = "mock"
    request.api_key = "key-a"
    request.future = asyncio.Future()
    queue.register_processor(
        lambda request: asyncio.sleep(0, result=Response(status_code=403))
    )
    await queue._process_with_worker("mock", request)
    assert control.get_key_limiter("mock", "key-a").blocked_until == 0

    config.key_blocking_enabled = True
    request = make_request()
    request.api_name = "mock"
    request.api_key = "key-a"
    request.future = asyncio.Future()
    queue.register_processor(
        lambda request: asyncio.sleep(0, result=Response(status_code=401))
    )
    await queue._process_with_worker("mock", request)
    assert control.get_key_limiter("mock", "key-a").blocked_until == 0


@pytest.mark.asyncio
async def test_queue_wait_for_key_expires_and_basic_status_methods():
    config = CoreConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config, control)
    queue._queues["mock"] = asyncio.PriorityQueue()
    request = make_request()
    request.api_name = "mock"
    request.future = asyncio.Future()
    request.added_at = time.time() - 10
    queue._check_for_resource_limit = lambda api_name, **kwargs: asyncio.sleep(
        0, result=(None, 1)
    )

    key = await queue._wait_for_key("mock", request)

    assert key is None
    with pytest.raises(RequestExpiredError):
        request.future.result()
    assert queue.get_all_queue_sizes()["mock"] == 0
    await queue._queues["mock"].put(make_request())
    assert queue.get_all_queue_sizes() == {"mock": 1}


@pytest.mark.asyncio
async def test_queue_wait_for_key_sleeps_once_before_expiring(monkeypatch):
    config = CoreConfig()
    control = TrafficManager(config)
    metrics = SimpleNamespace(
        hits=[],
        record_rate_limit_hit=lambda api: metrics.hits.append(api),
    )
    queue = RequestQueue(config, control, metrics)
    request = make_request()
    request.api_name = "mock"
    request.future = asyncio.Future()
    sleeps = []

    async def limited_resource(api_name, **kwargs):
        return None, 0.4

    queue._check_for_resource_limit = limited_resource

    async def fake_sleep(delay):
        sleeps.append(delay)
        request.added_at = time.time() - 10

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    assert await queue._wait_for_key("mock", request) is None
    assert sleeps == [0.2]
    assert metrics.hits == ["mock"]


@pytest.mark.asyncio
async def test_queue_resource_limit_checks_endpoint_and_key_waits():
    config = CoreConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config, control)

    control.time_to_endpoint_ready = lambda api_name: 0.25
    assert await queue._check_for_resource_limit("mock") == (None, 0.25)

    control.time_to_endpoint_ready = lambda api_name: 0
    control.acquire_key = lambda api_name, **kwargs: asyncio.sleep(
        0, result=(None, 0.5)
    )
    assert await queue._check_for_resource_limit("mock") == (None, 0.5)

    control.acquire_key = lambda api_name, **kwargs: asyncio.sleep(
        0, result=("key-a", 0)
    )
    assert await queue._check_for_resource_limit("mock") == ("key-a", 0.0)
