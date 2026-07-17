import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from httpx import Headers
from starlette.datastructures import URL
from starlette.responses import Response

from nya.common.exceptions import (
    APIKeyNotConfiguredError,
    MissingAPIKeyError,
    QueueFullError,
    ReachedMaxQuotaError,
    ReachedMaxRetriesError,
    RequestExpiredError,
    VariablesConfigurationError,
)
from nya.common.models import ProxyRequest
from nya.core.control import TrafficManager
from nya.core.handler import RequestHandler
from nya.core.proxy import NyaProxyCore
from nya.core.queue import RequestQueue
from nya.core.request import RequestExecutor
from nya.core.streaming import detect_streaming_content, handle_streaming_response
from nya.utils.formatting import format_elapsed_time, json_safe_dumps
from nya.utils.header import HeaderUtils
from nya.utils.redaction import mask_secret, redact_sensitive_data


class CoreConfig:
    def __init__(self):
        self.apis = {
            "mock": {
                "endpoint": "https://upstream.test",
                "aliases": ["alias"],
            }
        }
        self.api_keys = ["master", "secondary"]
        self.keys = ["key-a", "key-b"]
        self.allowed_enabled = True
        self.allowed_mode = "whitelist"
        self.allowed_paths = ["/v1/*"]
        self.allowed_methods = ["GET", "POST"]
        self.rate_limit_enabled = True
        self.rate_limit_paths = ["*"]
        self.retry_enabled = False
        self.retry_methods = ["GET"]
        self.retry_status_codes = [429]
        self.retry_after = 0
        self.retry_attempts = 2
        self.key_concurrency = True
        self.random_delay = 0
        self.body_substitution_enabled = False
        self.body_rules = []
        self.headers = {"Authorization": "Bearer ${{api_key}}"}
        self.proxy_enabled = False
        self.queue_size = 10
        self.queue_expiry = 2
        self.max_workers = 1

    def get_apis(self):
        return self.apis

    def get_api_aliases(self, api_name):
        return self.apis[api_name].get("aliases", [])

    def get_api_endpoint(self, api_name):
        return self.apis[api_name]["endpoint"]

    def get_api_allowed_paths_enabled(self, api_name):
        return self.allowed_enabled

    def get_api_allowed_methods(self, api_name):
        return self.allowed_methods

    def get_api_allowed_paths(self, api_name):
        return self.allowed_paths

    def get_api_allowed_paths_mode(self, api_name):
        return self.allowed_mode

    def get_api_rate_limit_enabled(self, api_name):
        return self.rate_limit_enabled

    def get_api_rate_limit_paths(self, api_name):
        return self.rate_limit_paths

    def get_api_key(self):
        return self.api_keys

    def get_api_key_variable(self, api_name):
        return "api_key"

    def get_api_custom_headers(self, api_name):
        return self.headers

    def get_api_variable_values(self, api_name, variable_name):
        if variable_name == "api_key":
            return self.keys
        if variable_name == "region":
            return ["us"]
        return []

    def get_api_request_body_substitution_enabled(self, api_name):
        return self.body_substitution_enabled

    def get_api_request_subst_rules(self, api_name):
        return self.body_rules

    def get_api_load_balancing_strategy(self, api_name):
        return "round_robin"

    def get_api_key_weights(self, api_name):
        return []

    def get_api_key_rate_limit(self, api_name):
        return "1/s"

    def get_api_endpoint_rate_limit(self, api_name):
        return "0"

    def get_api_ip_rate_limit(self, api_name):
        return "0"

    def get_api_user_rate_limit(self, api_name):
        return "0"

    def get_api_key_concurrency(self, api_name):
        return self.key_concurrency

    def get_api_queue_size(self, api_name):
        return self.queue_size

    def get_api_max_workers(self, api_name):
        return self.max_workers

    def get_api_queue_expiry(self, api_name):
        return self.queue_expiry

    def get_api_retry_enabled(self, api_name):
        return self.retry_enabled

    def get_api_retry_request_methods(self, api_name):
        return self.retry_methods

    def get_api_retry_status_codes(self, api_name):
        return self.retry_status_codes

    def get_api_retry_after_seconds(self, api_name):
        return self.retry_after

    def get_api_retry_attempts(self, api_name):
        return self.retry_attempts

    def get_api_default_timeout(self, api_name=None):
        return 5

    def get_api_random_delay(self, api_name):
        return self.random_delay

    def get_default_timeout(self):
        return 10

    def get_proxy_enabled(self):
        return self.proxy_enabled

    def get_proxy_address(self):
        return "http://proxy.test"


def make_request(
    path="/api/mock/v1/chat",
    method="GET",
    headers=None,
    content=b"{}",
):
    return ProxyRequest(
        method=method,
        _url=URL(f"http://proxy.test{path}"),
        headers=Headers(headers or {"authorization": "Bearer user-key"}),
        content=content,
        ip="198.51.100.1",
    )


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
        original_headers={"Connection": "close", "X-Original": "yes"},
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
    assert merged["X-Original"] == "yes"
    assert "connection" not in processed


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


@pytest.mark.asyncio
async def test_traffic_manager_key_selection_release_and_blocking():
    config = CoreConfig()
    config.key_concurrency = False
    control = TrafficManager(config)

    key, wait_time = await control.acquire_key("mock")
    assert (key, wait_time) == ("key-a", 0)
    assert control.time_to_key_ready("mock") == 0
    control.block_key("mock", "key-b", 1)
    assert control.time_to_key_ready("mock") > 0
    control.release_key("mock", "key-a")
    control.unlock_key("mock", "key-b")
    assert control.select_any_key("mock") in {"key-a", "key-b"}
    control.record_ip_request("mock", "ip")
    control.record_user_request("mock", "user")
    control.release_ip("mock", "ip")
    control.release_user("mock", "user")
    control.release_endpoint("mock")


def test_traffic_manager_select_any_key_requires_configured_keys():
    config = CoreConfig()
    config.keys = []

    with pytest.raises(APIKeyNotConfiguredError):
        TrafficManager(config).select_any_key("mock")


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

    with pytest.raises(ReachedMaxQuotaError):
        await queue.enqueue_request(request)


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
    assert sleeps == [0.1]
    assert metrics.hits == ["mock"]
    assert metrics.queues == ["mock"]
    assert queue.get_queue_size("mock") == 1

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
    queue._check_for_resource_limit = lambda api_name: asyncio.sleep(
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
async def test_queue_wait_for_key_expires_and_basic_status_methods():
    config = CoreConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config, control)
    queue._queues["mock"] = asyncio.PriorityQueue()
    request = make_request()
    request.api_name = "mock"
    request.future = asyncio.Future()
    request.added_at = time.time() - 10
    queue._check_for_resource_limit = lambda api_name: asyncio.sleep(
        0, result=(None, 1)
    )

    key = await queue._wait_for_key("mock", request)

    assert key is None
    with pytest.raises(RequestExpiredError):
        request.future.result()
    assert queue.get_queue_size("mock") == 0
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

    async def limited_resource(api_name):
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
    control.acquire_key = lambda api_name: asyncio.sleep(0, result=(None, 0.5))
    assert await queue._check_for_resource_limit("mock") == (None, 0.5)

    control.acquire_key = lambda api_name: asyncio.sleep(0, result=("key-a", 0))
    assert await queue._check_for_resource_limit("mock") == ("key-a", 0.0)


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


class FakeStreamContext:
    def __init__(self, response):
        self.response = response
        self.closed = False

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True


class FakeHttpxResponse:
    def __init__(self, chunks, status_code=200, headers=None, fail=False):
        self.status_code = status_code
        self.headers = Headers(headers or {"content-type": "text/plain"})
        self._chunks = chunks
        self._stream_ctx = FakeStreamContext(self)
        self.fail = fail

    async def aiter_raw(self):
        if self.fail:
            raise RuntimeError("stream failed")
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_request_executor_normal_streaming_proxy_and_metrics_paths(monkeypatch):
    config = CoreConfig()
    metrics = SimpleNamespace(
        requests=[],
        responses=[],
        record_request=lambda api, key: metrics.requests.append((api, key)),
        record_response=lambda api, key, status, elapsed: metrics.responses.append(
            (api, key, status)
        ),
    )
    executor = RequestExecutor(config, metrics)
    request = make_request()
    request.api_name = "mock"
    request.api_key = "key-a"
    request.url = "https://upstream.test/v1"
    request._rate_limited = True

    async def fake_execute_request(request, timeout):
        return FakeHttpxResponse(
            [b"hello"], headers={"content-type": "text/plain", "content-length": "5"}
        )

    executor.execute_request = fake_execute_request
    response = await executor.execute(request)
    assert response.body == b"hello"
    assert metrics.requests == [("mock", "key-a")]
    assert metrics.responses[0][:3] == ("mock", "key-a", 200)

    async def boom(request, timeout):
        raise RuntimeError("network")

    executor.execute_request = boom
    with pytest.raises(RuntimeError):
        await executor.execute(request)
    assert metrics.responses[-1][:3] == ("mock", "key-a", 0)

    await executor.close()


@pytest.mark.asyncio
async def test_request_executor_execute_request_and_cleanup_on_processing_error():
    config = CoreConfig()
    executor = RequestExecutor(config)
    request = make_request()
    request.url = "https://upstream.test/v1"

    class Client:
        def stream(self, **kwargs):
            response = FakeHttpxResponse(
                [b"broken"],
                headers={"content-type": "text/plain", "content-length": "6"},
                fail=True,
            )
            return FakeStreamContext(response)

    executor.client = Client()
    response = await executor.execute_request(request, executor._get_timeout("mock"))
    stream_ctx = response._stream_ctx

    with pytest.raises(RuntimeError):
        await executor.process_response(response)
    assert stream_ctx.closed is True


@pytest.mark.asyncio
async def test_request_executor_close_is_noop_without_client():
    executor = object.__new__(RequestExecutor)
    executor.client = None

    await executor.close()


def test_request_executor_timeout_and_proxy_client_options(monkeypatch):
    config = CoreConfig()
    config.proxy_enabled = True
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def aclose(self):
            captured["closed"] = True

    monkeypatch.setattr("nya.core.request.httpx.AsyncClient", FakeClient)

    executor = RequestExecutor(config)

    assert captured["proxy"] == "http://proxy.test"
    assert executor._get_timeout("mock").read == pytest.approx(4.75)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"content-type": "application/json"}, False),
        ({"content-type": "text/event-stream"}, True),
        ({"transfer-encoding": "chunked", "content-type": "text/plain"}, True),
        (
            {
                "accept-ranges": "bytes",
                "content-type": "video/mp4",
                "content-length": "10",
            },
            True,
        ),
        ({"content-type": "text/plain", "content-length": "10"}, False),
    ],
)
def test_detect_streaming_content(headers, expected):
    assert detect_streaming_content(Headers(headers)) is expected


@pytest.mark.asyncio
async def test_handle_streaming_response_yields_chunks_and_closes_context():
    response = FakeHttpxResponse(
        [b"data: one\n\n", b"", b"data: two\n\n"],
        headers={
            "content-type": "text/event-stream; charset=utf-8",
            "content-length": "100",
            "date": "today",
        },
    )

    streaming = await handle_streaming_response(response)
    body = [chunk async for chunk in streaming.body_iterator]

    assert body == [b"data: one\n\n", b"data: two\n\n"]
    assert response._stream_ctx is None
    assert "content-length" not in streaming.headers
    assert streaming.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_handle_streaming_response_logs_generator_errors_and_closes():
    response = FakeHttpxResponse(
        [],
        headers={"content-type": "text/event-stream"},
        fail=True,
    )

    streaming = await handle_streaming_response(response)
    assert [chunk async for chunk in streaming.body_iterator] == []
    assert response._stream_ctx is None


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
