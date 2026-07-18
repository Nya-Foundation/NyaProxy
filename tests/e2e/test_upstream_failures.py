"""
E2E coverage for upstream failure modes: dead upstream, slow upstream, and
mid-stream errors. These are the paths a gateway exists for — none of them
may surface as a hang or a generic 500.
"""

import time

import httpx
import pytest

from tests.e2e.conftest import PROXY_KEY, get_free_port

pytestmark = pytest.mark.e2e


def proxy_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_KEY}"}


def test_dead_upstream_returns_502(proxy_server):
    dead_endpoint = f"http://127.0.0.1:{get_free_port()}"
    proxy_url = proxy_server(retry_enabled=False, endpoint_override=dead_endpoint)

    response = httpx.get(
        f"{proxy_url}/api/mock/v1/anything", headers=proxy_headers(), timeout=10
    )

    assert response.status_code == 502
    assert "upstream" in response.json()["error"].lower()


def test_upstream_read_timeout_returns_504(proxy_server):
    proxy_url = proxy_server(
        retry_enabled=False,
        extra_api_config="""
    timeouts:
      request_timeout_seconds: 2
""",
    )

    started = time.time()
    response = httpx.get(
        f"{proxy_url}/api/mock/slow", headers=proxy_headers(), timeout=10
    )
    elapsed = time.time() - started

    assert response.status_code == 504
    # The upstream sleeps for 4s; the proxy must give up at its own 2s budget.
    assert elapsed < 3.5


def test_mid_stream_upstream_error_does_not_wedge_the_proxy(
    proxy_server, upstream_server
):
    proxy_url = proxy_server()
    _, upstream = upstream_server

    received = b""
    try:
        with httpx.stream(
            "GET",
            f"{proxy_url}/api/mock/stream-error",
            headers=proxy_headers(),
            timeout=10,
        ) as response:
            assert response.status_code == 200
            for chunk in response.iter_raw():
                received += chunk
    except httpx.HTTPError:
        # The truncated stream may surface as a protocol error client-side.
        pass

    assert b"data: first" in received

    # The proxy must stay fully functional after the broken stream:
    # buffered requests and clean streams both still work.
    response = httpx.get(
        f"{proxy_url}/api/mock/v1/after", headers=proxy_headers(), timeout=5
    )
    assert response.status_code == 200

    with httpx.stream(
        "GET", f"{proxy_url}/api/mock/stream", headers=proxy_headers(), timeout=10
    ) as response:
        body = b"".join(response.iter_raw())
    assert body == b"data: one\n\ndata: two\n\n"
