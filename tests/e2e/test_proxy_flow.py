import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tests.e2e.conftest import PROXY_KEY, UPSTREAM_KEYS

pytestmark = pytest.mark.e2e


def proxy_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_KEY}"}


def test_round_robin_injects_credentials_and_transforms_body(
    proxy_server, upstream_server
):
    proxy_url = proxy_server(
        request_body_substitution="""
      enabled: true
      rules:
        - name: "Remove unsupported field"
          operation: remove
          path: "drop_me"
          conditions:
            - field: "drop_me"
              operator: "exists"
"""
    )
    _, upstream = upstream_server

    for index in range(6):
        response = httpx.post(
            f"{proxy_url}/api/mock/v1/messages",
            headers=proxy_headers(),
            json={"message": index, "drop_me": "remove"},
            timeout=5,
        )
        assert response.status_code == 200

    assert [record["key"] for record in upstream.records] == [
        "key-a",
        "key-b",
        "key-c",
        "key-a",
        "key-b",
        "key-c",
    ]
    assert [record["authorization"] for record in upstream.records] == [
        f"Bearer {key}" for key in (*UPSTREAM_KEYS, *UPSTREAM_KEYS)
    ]
    assert all(record["key"] != PROXY_KEY for record in upstream.records)
    assert {record["path"] for record in upstream.records} == {"/v1/messages"}
    assert all("drop_me" not in record["body"] for record in upstream.records)


def test_retryable_status_rotates_to_next_key(proxy_server, upstream_server):
    proxy_url = proxy_server()
    _, upstream = upstream_server
    upstream.statuses_by_key = {"key-a": [429], "key-b": [200]}

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/retry",
        headers=proxy_headers(),
        timeout=5,
    )

    assert response.status_code == 200
    assert [record["key"] for record in upstream.records] == ["key-a", "key-b"]


def test_retryable_chain_rotates_across_all_keys(proxy_server, upstream_server):
    proxy_url = proxy_server()
    _, upstream = upstream_server
    upstream.statuses_by_key = {"key-a": [429], "key-b": [500], "key-c": [200]}

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/retry-chain",
        headers=proxy_headers(),
        timeout=5,
    )

    assert response.status_code == 200
    assert [record["key"] for record in upstream.records] == [
        "key-a",
        "key-b",
        "key-c",
    ]
    assert [record["path"] for record in upstream.records] == [
        "/v1/retry-chain",
        "/v1/retry-chain",
        "/v1/retry-chain",
    ]


def test_concurrent_requests_rotate_credentials_evenly(proxy_server, upstream_server):
    proxy_url = proxy_server(max_workers=9, key_rate_limit="1000/m")
    _, upstream = upstream_server

    def call_proxy(index: int) -> int:
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/concurrent/{index}",
            headers=proxy_headers(),
            timeout=5,
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=9) as executor:
        statuses = list(executor.map(call_proxy, range(9)))

    assert statuses == [200] * 9
    assert Counter(record["key"] for record in upstream.records) == {
        "key-a": 3,
        "key-b": 3,
        "key-c": 3,
    }
    assert all(
        record["authorization"].startswith("Bearer key-")
        for record in upstream.records
    )
    assert all(PROXY_KEY not in record["authorization"] for record in upstream.records)


def test_disallowed_path_is_rejected_before_upstream(proxy_server, upstream_server):
    proxy_url = proxy_server(
        allowed_paths="""
    enabled: true
    mode: whitelist
    paths:
      - "/v1/allowed/*"
"""
    )
    _, upstream = upstream_server

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/blocked",
        headers=proxy_headers(),
        timeout=5,
    )

    assert response.status_code == 405
    assert upstream.records == []


def test_key_rate_limit_queues_until_next_key_window(proxy_server, upstream_server):
    proxy_url = proxy_server(key_rate_limit="1/1s", retry_enabled=False)
    _, upstream = upstream_server

    for _ in range(3):
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/rate-limited",
            headers=proxy_headers(),
            timeout=5,
        )
        assert response.status_code == 200

    started_at = time.monotonic()
    response = httpx.get(
        f"{proxy_url}/api/mock/v1/rate-limited",
        headers=proxy_headers(),
        timeout=5,
    )

    assert response.status_code == 200
    assert time.monotonic() - started_at >= 0.75
    assert [record["key"] for record in upstream.records] == [
        "key-a",
        "key-b",
        "key-c",
        "key-a",
    ]


def test_streaming_response_is_forwarded(proxy_server):
    proxy_url = proxy_server()

    with httpx.stream(
        "GET",
        f"{proxy_url}/api/mock/stream",
        headers=proxy_headers(),
        timeout=5,
    ) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert b"data: one" in body
    assert b"data: two" in body
