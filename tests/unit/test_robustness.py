import asyncio
import time

import pytest
from httpx import Headers
from starlette.datastructures import URL

from nya.common.models import ProxyRequest
from nya.core.control import TrafficManager
from nya.core.handler import RequestHandler
from nya.core.queue import RequestQueue
from nya.core.request import RequestExecutor
from nya.utils.redaction import redact_sensitive_data


class DummyConfig:
    def __init__(self):
        self.keys = ["key-1"]
        self.header_config = {"X-Static": "nyaproxy"}
        self.key_concurrency = True

    def get_api_load_balancing_strategy(self, api_name):
        return "round_robin"

    def get_api_key_variable(self, api_name):
        return "keys"

    def get_api_key_weights(self, api_name):
        return []

    def get_api_variable_values(self, api_name, variable_name):
        if variable_name == "keys":
            return self.keys
        return []

    def get_api_endpoint_rate_limit(self, api_name):
        return "0"

    def get_api_key_rate_limit(self, api_name):
        return "1/m"

    def get_api_ip_rate_limit(self, api_name):
        return "1/s"

    def get_api_user_rate_limit(self, api_name):
        return "1/s"

    def get_api_key_concurrency(self, api_name):
        return self.key_concurrency

    def get_api_queue_size(self, api_name):
        return 10

    def get_api_max_workers(self, api_name):
        return 2

    def get_api_queue_expiry(self, api_name):
        return 5

    def get_api_retry_enabled(self, api_name):
        return False

    def get_api_custom_headers(self, api_name):
        return self.header_config

    def get_api_default_timeout(self, api_name=None):
        return 30

    def get_proxy_enabled(self):
        return False

    def get_default_timeout(self):
        return 30


def make_request() -> ProxyRequest:
    request = ProxyRequest(
        method="POST",
        _url=URL("http://proxy.test/api/example/messages"),
        headers=Headers({"authorization": "Bearer proxy-key"}),
        content=b"{}",
        ip="127.0.0.1",
    )
    request.api_name = "example"
    request.url = "https://upstream.test/messages"
    request.user = "proxy-key"
    request.future = asyncio.Future()
    return request


async def cancel_worker_tasks(queue: RequestQueue, api_name: str) -> None:
    tasks = queue._worker_tasks.get(api_name, [])
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_queue_workers_do_not_acquire_keys_while_idle():
    config = DummyConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config=config, traffic_manager=control)

    await queue._setup_endpoint_processor("example")
    await asyncio.sleep(0.05)

    assert not any("_key_" in name for name in control.rate_limiters)
    assert not any(name.endswith("_endpoint") for name in control.rate_limiters)

    await cancel_worker_tasks(queue, "example")


@pytest.mark.asyncio
async def test_acquire_key_records_selection_atomically():
    config = DummyConfig()
    control = TrafficManager(config)

    results = await asyncio.gather(
        control.acquire_key("example"),
        control.acquire_key("example"),
    )

    acquired = [key for key, wait_time in results if key and wait_time == 0]
    limited = [wait_time for key, wait_time in results if key is None]

    assert acquired == ["key-1"]
    assert len(limited) == 1
    assert limited[0] > 0


@pytest.mark.asyncio
async def test_clear_queue_drains_pending_requests_without_stopping_workers():
    config = DummyConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config=config, traffic_manager=control)
    api_name = "example"
    queue._queues[api_name] = asyncio.PriorityQueue()
    worker = asyncio.create_task(asyncio.sleep(10))
    queue._worker_tasks[api_name] = [worker]

    request = make_request()
    await queue._queues[api_name].put(request)

    cleared = await queue.clear_queue(api_name)

    assert cleared == 1
    assert request.future.done()
    assert not worker.cancelled()

    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_header_processing_allows_headers_without_key_template():
    config = DummyConfig()
    handler = RequestHandler(config=config)
    request = make_request()
    request.api_key = "upstream-secret"

    await handler.process_request_headers(request)

    assert request.headers["X-Static"] == "nyaproxy"
    assert request.headers["host"] == "upstream.test"


def test_prunes_idle_ip_and_user_limiters_but_keeps_static_limiters():
    config = DummyConfig()
    control = TrafficManager(config)

    ip_limiter = control.get_ip_limiter("example", "203.0.113.10")
    user_limiter = control.get_user_limiter("example", "user-a")
    key_limiter = control.get_key_limiter("example", "key-1")
    old_timestamp = time.time() - 120
    ip_limiter.last_accessed = old_timestamp
    user_limiter.last_accessed = old_timestamp
    key_limiter.last_accessed = old_timestamp
    control._last_limiter_prune = 0

    control.get_endpoint_limiter("example")

    assert "example_ip_203.0.113.10" not in control.rate_limiters
    assert "example_user_user-a" not in control.rate_limiters
    assert "example_key_key-1" in control.rate_limiters
    assert "example_endpoint" in control.rate_limiters


def test_redact_sensitive_data_masks_common_secret_fields():
    redacted = redact_sensitive_data(
        {
            "Authorization": "Bearer upstream-secret",
            "nested": {"x-api-key": "abcdef123456"},
            "safe": "value",
        }
    )

    assert redacted["Authorization"] == "Bear...cret"
    assert redacted["nested"]["x-api-key"] == "abcd...3456"
    assert redacted["safe"] == "value"


class FakeResponse:
    status_code = 200
    headers = Headers({"content-type": "text/plain"})

    async def aiter_raw(self):
        yield b"hello "
        yield b"world"


@pytest.mark.asyncio
async def test_normal_response_buffers_chunks_without_repeated_concatenation():
    executor = RequestExecutor(config=DummyConfig())
    try:
        response = await executor.handle_normal_response(FakeResponse())
        assert response.body == b"hello world"
    finally:
        await executor.close()
