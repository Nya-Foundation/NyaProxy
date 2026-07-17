"""
End-to-end coverage for the two must-work flows:

1. Rate limiting under load — bursts are throttled and queued, never
   dropped with 5xx errors, and hard limits fail fast with 429 + Retry-After.
2. Retry strategy — retryable upstream statuses (429/5xx) rotate keys,
   cool the failing key down, and never stall unrelated traffic.
"""

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tests.e2e.conftest import PROXY_KEY, UPSTREAM_KEYS

pytestmark = pytest.mark.e2e


def proxy_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_KEY}"}


# --------------------------------------------------------------------------
# Rate limiting under load
# --------------------------------------------------------------------------


def test_endpoint_rate_limit_throttles_burst_without_errors(
    proxy_server, upstream_server
):
    """A burst above the endpoint rate limit is queued, not rejected."""
    proxy_url = proxy_server(endpoint_rate_limit="3/1s", max_workers=9)
    _, upstream = upstream_server

    def call_proxy(index: int) -> int:
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/burst/{index}",
            headers=proxy_headers(),
            timeout=15,
        )
        return response.status_code

    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=9) as executor:
        statuses = list(executor.map(call_proxy, range(9)))
    elapsed = time.monotonic() - started_at

    assert statuses == [200] * 9
    assert len(upstream.records) == 9
    # 9 requests at 3/s must span at least two additional windows.
    assert elapsed >= 1.5


def test_key_rate_limit_spreads_burst_across_keys(proxy_server, upstream_server):
    """Per-key limits force the burst to use the whole key pool."""
    proxy_url = proxy_server(key_rate_limit="2/1s", max_workers=9)
    _, upstream = upstream_server

    def call_proxy(index: int) -> int:
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/spread/{index}",
            headers=proxy_headers(),
            timeout=15,
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(call_proxy, range(6)))

    assert statuses == [200] * 6
    usage = Counter(record["key"] for record in upstream.records)
    assert set(usage) == set(UPSTREAM_KEYS)
    assert all(count == 2 for count in usage.values())


def test_queue_overflow_fails_fast_with_503(proxy_server, upstream_server):
    """When the queue is full new requests get 503, queued ones expire to 504."""
    proxy_url = proxy_server(
        endpoint_rate_limit="1/10s",
        queue_max_size=2,
        max_workers=1,
        queue_expiry_seconds=2,
    )

    # Consume the whole endpoint budget.
    first = httpx.get(
        f"{proxy_url}/api/mock/v1/first", headers=proxy_headers(), timeout=15
    )
    assert first.status_code == 200

    def call_proxy(index: int) -> int:
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/overflow/{index}",
            headers=proxy_headers(),
            timeout=15,
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(call_proxy, range(5)))

    # Nothing else can get through the 1/10s budget: every request either
    # bounces off the full queue (503) or expires inside it (504).
    assert set(statuses) <= {503, 504}
    assert 503 in statuses
    assert 504 in statuses


def test_ip_rate_limit_over_quota_returns_429_with_retry_after(
    proxy_server, upstream_server
):
    """Requests beyond the IP quota fail fast with 429 and a Retry-After."""
    proxy_url = proxy_server(ip_rate_limit="2/m", queue_expiry_seconds=2)

    for _ in range(2):
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/quota", headers=proxy_headers(), timeout=15
        )
        assert response.status_code == 200

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/quota", headers=proxy_headers(), timeout=15
    )

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1


def test_malformed_forwarded_header_is_ignored(proxy_server, upstream_server):
    """A garbage x-forwarded-for value must not break the request."""
    proxy_url = proxy_server()

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/xff",
        headers={**proxy_headers(), "x-forwarded-for": "not-an-ip"},
        timeout=15,
    )

    assert response.status_code == 200


# --------------------------------------------------------------------------
# Retry strategy on retryable upstream statuses
# --------------------------------------------------------------------------


def test_429_rotates_to_next_key_with_unlimited_key_limit(
    proxy_server, upstream_server
):
    """Key rotation on 429 works even when no key rate limit is set."""
    proxy_url = proxy_server(key_rate_limit="0")
    _, upstream = upstream_server
    upstream.statuses_by_key = {"key-a": [429]}

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/rotate", headers=proxy_headers(), timeout=15
    )

    assert response.status_code == 200
    assert [record["key"] for record in upstream.records] == ["key-a", "key-b"]


def test_429_on_single_key_cools_down_and_recovers(proxy_server, upstream_server):
    """With one key and no key limit, a 429 cools the key down, then retries."""
    proxy_url = proxy_server(
        key_rate_limit="0", keys=("key-a",), retry_after_seconds=0.5
    )
    _, upstream = upstream_server
    upstream.statuses_by_key = {"key-a": [429, 200]}

    started_at = time.monotonic()
    response = httpx.get(
        f"{proxy_url}/api/mock/v1/cooldown", headers=proxy_headers(), timeout=15
    )
    elapsed = time.monotonic() - started_at

    assert response.status_code == 200
    assert [record["key"] for record in upstream.records] == ["key-a", "key-a"]
    # The retry respected the cool-down delay.
    assert elapsed >= 0.3


def test_upstream_500_is_retried_on_other_keys(proxy_server, upstream_server):
    """5xx retry statuses rotate exactly like 429s."""
    proxy_url = proxy_server()
    _, upstream = upstream_server
    upstream.statuses_by_key = {"key-a": [502], "key-b": [500]}

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/5xx", headers=proxy_headers(), timeout=15
    )

    assert response.status_code == 200
    assert [record["key"] for record in upstream.records] == [
        "key-a",
        "key-b",
        "key-c",
    ]


def test_exhausted_retries_return_429_to_client(proxy_server, upstream_server):
    """When every attempt fails with a retryable status, the client gets 429."""
    proxy_url = proxy_server(retry_after_seconds=0.05)
    _, upstream = upstream_server
    upstream.statuses_by_key = {
        "key-a": [429, 429],
        "key-b": [429, 429],
        "key-c": [429, 429],
    }

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/exhausted", headers=proxy_headers(), timeout=15
    )

    assert response.status_code == 429
    assert "error" in response.json()


def test_retrying_request_does_not_stall_other_traffic(proxy_server, upstream_server):
    """A request waiting on its retry delay must not block the worker."""
    proxy_url = proxy_server(max_workers=1, retry_after_seconds=1.0)
    _, upstream = upstream_server
    upstream.statuses_by_key = {"key-a": [429]}

    results: dict[str, int] = {}

    def slow_request():
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/slow", headers=proxy_headers(), timeout=15
        )
        results["slow"] = response.status_code

    slow_thread = threading.Thread(target=slow_request)
    slow_thread.start()
    time.sleep(0.3)  # let the slow request hit key-a's 429 and enter retry

    started_at = time.monotonic()
    fast = httpx.get(
        f"{proxy_url}/api/mock/v1/fast", headers=proxy_headers(), timeout=15
    )
    fast_elapsed = time.monotonic() - started_at

    slow_thread.join(timeout=15)

    assert fast.status_code == 200
    # The single worker was free while the slow request waited out its
    # ~1s retry delay; the fast request must not have queued behind it.
    assert fast_elapsed < 0.8
    assert results["slow"] == 200


# --------------------------------------------------------------------------
# Routing, dashboard, and load-balancing extras
# --------------------------------------------------------------------------


def test_alias_and_head_requests_are_routed(proxy_server, upstream_server):
    proxy_url = proxy_server()
    _, upstream = upstream_server

    via_alias = httpx.get(
        f"{proxy_url}/api/mock-alias/v1/aliased", headers=proxy_headers(), timeout=15
    )
    assert via_alias.status_code == 200
    assert upstream.records[-1]["path"] == "/v1/aliased"

    head = httpx.head(
        f"{proxy_url}/api/mock/v1/headcheck", headers=proxy_headers(), timeout=15
    )
    assert head.status_code == 200


def test_invalid_proxy_key_is_rejected(proxy_server):
    proxy_url = proxy_server()

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/denied",
        headers={"Authorization": "Bearer wrong-key"},
        timeout=15,
    )

    assert response.status_code == 403


def test_weighted_strategy_honors_key_weights(proxy_server, upstream_server):
    proxy_url = proxy_server(
        load_balancing_strategy="weighted",
        extra_api_config="""    key_weights:
      - 1
      - 0
      - 0""",
    )
    _, upstream = upstream_server

    for index in range(6):
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/weighted/{index}",
            headers=proxy_headers(),
            timeout=15,
        )
        assert response.status_code == 200

    assert {record["key"] for record in upstream.records} == {"key-a"}


def test_dashboard_metrics_and_queue_controls(proxy_server, upstream_server):
    """Dashboard exposes metrics and the clear-all-queues control works."""
    proxy_url = proxy_server(dashboard_enabled=True)

    warm_up = httpx.get(
        f"{proxy_url}/api/mock/v1/traffic", headers=proxy_headers(), timeout=15
    )
    assert warm_up.status_code == 200

    metrics = httpx.get(
        f"{proxy_url}/dashboard/api/metrics", headers=proxy_headers(), timeout=15
    )
    assert metrics.status_code == 200
    assert "mock" in metrics.json()["apis"]

    clear_all = httpx.post(
        f"{proxy_url}/dashboard/api/queue/clear", headers=proxy_headers(), timeout=15
    )
    assert clear_all.status_code == 200
    assert clear_all.json()["cleared_count"] == 0

    reset = httpx.post(
        f"{proxy_url}/dashboard/api/metrics/reset", headers=proxy_headers(), timeout=15
    )
    assert reset.status_code == 200
