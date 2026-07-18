"""
Regression tests for bugs found in review: key cool-down on unlimited
limiters, malformed forwarded headers, weighted LB wiring, real-queue
clear_all_queues, and non-blocking retries.
"""

import asyncio
import time
from collections import Counter

import pytest
from httpx import Headers
from starlette.datastructures import URL
from starlette.responses import Response

from nya.common.models import ProxyRequest
from nya.core.control import TrafficManager
from nya.core.queue import RequestQueue
from nya.services.limit import RateLimiter
from nya.utils.header import HeaderUtils

from .core_helpers import CoreConfig, make_request

# --------------------------------------------------------------------------
# RateLimiter.block_for on unlimited limiters (key cool-down after 429)
# --------------------------------------------------------------------------


def test_block_for_limits_even_without_rate_limit():
    """Cool-down must work when no key rate limit is configured."""
    limiter = RateLimiter("0")
    assert limiter.is_limited() is False

    limiter.block_for(30)

    assert limiter.is_limited() is True
    assert 0 < limiter.time_until_reset() <= 30


def test_block_for_expires_after_duration():
    limiter = RateLimiter(None)
    limiter.block_for(0.05)
    assert limiter.is_limited() is True
    time.sleep(0.06)
    assert limiter.is_limited() is False


def test_block_for_does_not_wipe_recorded_usage():
    limiter = RateLimiter("5/m")
    limiter.record()
    limiter.record()
    limiter.block_for(0.01)
    assert len(limiter.request_timestamps) == 2


def test_clear_resets_block():
    limiter = RateLimiter("0")
    limiter.block_for(30)
    limiter.clear()
    assert limiter.is_limited() is False


def test_traffic_manager_blocks_key_without_key_rate_limit():
    config = CoreConfig()
    config.key_rate_limit = "0"
    config.get_api_key_rate_limit = lambda api_name: "0"
    control = TrafficManager(config)

    control.block_key("mock", "key-a", 30)

    key_limiter = control.get_key_limiter("mock", "key-a")
    assert key_limiter.is_limited() is True


# --------------------------------------------------------------------------
# Malformed forwarded headers must be ignored, never raise
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"x-forwarded-for": "not-an-ip"},
        {"x-forwarded-for": "garbage, 10.0.0.1"},
        {"x-real-ip": ""},
        {"forwarded": "for=nonsense;proto=https"},
    ],
)
def test_parse_source_ip_ignores_malformed_values(headers):
    assert HeaderUtils.parse_source_ip_address(Headers(headers)) is None


def test_parse_source_ip_still_accepts_valid_values():
    headers = Headers({"x-forwarded-for": "203.0.113.7, 10.0.0.1"})
    assert HeaderUtils.parse_source_ip_address(headers) == "203.0.113.7"


# --------------------------------------------------------------------------
# Weighted load balancing is wired from config
# --------------------------------------------------------------------------


def test_weighted_strategy_uses_configured_key_weights():
    config = CoreConfig()
    config.get_api_load_balancing_strategy = lambda api_name: "weighted"
    config.get_api_key_weights = lambda api_name: [1, 0]
    control = TrafficManager(config)

    lb = control.get_load_balancer("mock")
    picks = Counter(lb.next() for _ in range(50))

    assert picks["key-a"] == 50
    assert "key-b" not in picks


def test_fastest_response_receives_recorded_times():
    """The queue records response times so fastest_response has data."""
    config = CoreConfig()
    config.get_api_load_balancing_strategy = lambda api_name: "fastest_response"
    control = TrafficManager(config)
    queue = RequestQueue(config, control)
    queue._queues["mock"] = asyncio.PriorityQueue()

    async def run():
        request = make_request()
        request.api_name = "mock"
        request.api_key = "key-a"
        request.future = asyncio.Future()
        queue.register_processor(
            lambda req: asyncio.sleep(0, result=Response(status_code=200))
        )
        await queue._process_with_worker("mock", request)

    asyncio.run(run())

    lb = control.get_load_balancer("mock")
    assert len(lb.response_times["key-a"]) == 1


# --------------------------------------------------------------------------
# RequestQueue behaviour
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_all_queues_clears_every_api():
    config = CoreConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config, control)

    for api_name in ("mock", "other"):
        queue._queues[api_name] = asyncio.PriorityQueue()
        request = make_request()
        request.api_name = api_name
        request.future = asyncio.Future()
        await queue._queues[api_name].put(request)

    cleared = await queue.clear_all_queues()

    assert cleared == 2
    assert queue.get_all_queue_sizes() == {"mock": 0, "other": 0}


@pytest.mark.asyncio
async def test_worker_skips_request_with_cancelled_future():
    """A client that timed out must not consume upstream quota."""
    config = CoreConfig()
    control = TrafficManager(config)
    queue = RequestQueue(config, control)
    queue._queues["mock"] = asyncio.PriorityQueue()

    calls = []

    async def processor(request):
        calls.append(request)
        return Response(status_code=200)

    queue.register_processor(processor)

    request = make_request()
    request.api_name = "mock"
    request.api_key = "key-a"
    request.future = asyncio.Future()
    request.future.cancel()

    await queue._process_with_worker("mock", request)

    assert calls == []


@pytest.mark.asyncio
async def test_retry_does_not_block_the_worker(monkeypatch):
    """_handle_retry must return immediately; the delay runs elsewhere."""
    config = CoreConfig()
    config.retry_enabled = True
    config.retry_after = 0.2
    config.retry_attempts = 3
    control = TrafficManager(config)
    queue = RequestQueue(config, control)
    queue._queues["mock"] = asyncio.PriorityQueue()

    request = make_request()
    request.api_name = "mock"
    request.api_key = "key-a"
    request.future = asyncio.Future()
    request.attempts = 1

    started = time.monotonic()
    await queue._handle_retry(request, 0.2)
    elapsed = time.monotonic() - started

    # Returns without sleeping for the retry delay
    assert elapsed < 0.1

    # The request is re-enqueued with retry priority after the delay
    requeued = await asyncio.wait_for(queue._queues["mock"].get(), timeout=2)
    assert requeued is request
    assert requeued.priority == 1
