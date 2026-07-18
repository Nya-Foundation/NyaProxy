import httpx
import pytest

from tests.e2e.conftest import PROXY_KEY

pytestmark = pytest.mark.e2e


def proxy_headers(**extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_KEY}", **extra}


def test_query_and_custom_header_auth_are_forwarded_without_gateway_key(
    proxy_server, upstream_server
):
    proxy_url = proxy_server(
        upstream_headers='      X-API-Key: "${{keys}}"',
    )
    _, upstream = upstream_server

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/search?q=one&q=two&encoded=a%2Fb",
        headers=proxy_headers(),
        timeout=5,
    )

    assert response.status_code == 200
    record = upstream.records[-1]
    assert record["query"] == "q=one&q=two&encoded=a%2Fb"
    assert record["x_api_key"] == "key-a"
    assert record["authorization"] == ""
    assert PROXY_KEY not in str(record)


def test_disabled_rate_limits_keep_retry_load_balancing_and_metrics(
    proxy_server, upstream_server
):
    proxy_url = proxy_server(rate_limit_enabled=False)
    _, upstream = upstream_server
    upstream.statuses_by_key = {"key-a": [429], "key-b": [200]}

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/retry-without-limits",
        headers=proxy_headers(),
        timeout=5,
    )

    assert response.status_code == 200
    assert [record["key"] for record in upstream.records] == ["key-a", "key-b"]
    metrics = httpx.get(f"{proxy_url}/metrics", timeout=5)
    assert metrics.status_code == 200
    assert 'nyaproxy_requests_total{api="mock"} 2.0' in metrics.text


def test_duplicate_set_cookie_headers_remain_separate(proxy_server):
    proxy_url = proxy_server()

    response = httpx.get(
        f"{proxy_url}/api/mock/cookies", headers=proxy_headers(), timeout=5
    )

    assert response.status_code == 200
    assert response.headers.get_list("set-cookie") == [
        "first=1; Path=/",
        "second=2; Path=/",
    ]


def test_untrusted_forwarded_for_cannot_evade_ip_quota(proxy_server):
    proxy_url = proxy_server(ip_rate_limit="1/m", queue_expiry_seconds=1)

    first = httpx.get(
        f"{proxy_url}/api/mock/v1/quota",
        headers=proxy_headers(**{"X-Forwarded-For": "203.0.113.1"}),
        timeout=5,
    )
    second = httpx.get(
        f"{proxy_url}/api/mock/v1/quota",
        headers=proxy_headers(**{"X-Forwarded-For": "203.0.113.2"}),
        timeout=5,
    )

    assert first.status_code == 200
    assert second.status_code == 429
