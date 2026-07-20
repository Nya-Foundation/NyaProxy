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


def test_trusted_proxy_applies_quota_per_forwarded_client(proxy_server):
    """
    Behind a trusted reverse proxy, quotas must apply to the real client.

    The socket peer is the proxy, so without this every user shares one
    bucket. Note the uvicorn access log always shows the peer address — the
    resolved client is only observable through behaviour like this.
    """
    proxy_url = proxy_server(
        ip_rate_limit="2/m",
        queue_expiry_seconds=1,
        trusted_proxies=("127.0.0.1/32", "::1/128"),
    )

    # Two requests from one client consume that client's quota.
    for _ in range(2):
        response = httpx.get(
            f"{proxy_url}/api/mock/v1/quota",
            headers=proxy_headers(**{"X-Forwarded-For": "203.0.113.10"}),
            timeout=5,
        )
        assert response.status_code == 200

    exhausted = httpx.get(
        f"{proxy_url}/api/mock/v1/quota",
        headers=proxy_headers(**{"X-Forwarded-For": "203.0.113.10"}),
        timeout=5,
    )
    assert exhausted.status_code == 429, "the forwarded client was not rate limited"

    # A different client must still have its own quota.
    other = httpx.get(
        f"{proxy_url}/api/mock/v1/quota",
        headers=proxy_headers(**{"X-Forwarded-For": "203.0.113.99"}),
        timeout=5,
    )
    assert other.status_code == 200, (
        "a second client shared the first client's quota, so the forwarded "
        "address was ignored and everyone is bucketed as the proxy"
    )


def test_x_real_ip_is_honoured_from_a_trusted_proxy(proxy_server):
    """nginx's X-Real-IP alone is enough; X-Forwarded-For is not required."""
    proxy_url = proxy_server(
        ip_rate_limit="1/m",
        queue_expiry_seconds=1,
        trusted_proxies=("127.0.0.1/32", "::1/128"),
    )

    first = httpx.get(
        f"{proxy_url}/api/mock/v1/quota",
        headers=proxy_headers(**{"X-Real-IP": "198.51.100.7"}),
        timeout=5,
    )
    second = httpx.get(
        f"{proxy_url}/api/mock/v1/quota",
        headers=proxy_headers(**{"X-Real-IP": "198.51.100.8"}),
        timeout=5,
    )

    assert first.status_code == 200
    assert second.status_code == 200, "X-Real-IP from a trusted proxy was ignored"
