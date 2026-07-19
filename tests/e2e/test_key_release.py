"""
E2E coverage for credential release under `key_concurrency: false`.

With per-key concurrency disabled, a key is locked for the duration of a
request and released when it finishes. Every path out of a request has to
release it: a lock that leaks takes the key out of rotation permanently,
because nothing expires it. With a small pool that is an outage, and the
queue then fills with requests that can never be served.

These tests drive a real proxy process against a real upstream, and assert on
the only thing that matters operationally: can the gateway still serve traffic
afterwards.
"""

import httpx
import pytest

from tests.e2e.conftest import PROXY_KEY

pytestmark = pytest.mark.e2e


def proxy_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_KEY}"}


def test_client_disconnect_midstream_releases_the_key(proxy_server):
    """
    A client that hangs up mid-stream must not cost us the credential.

    This is the production failure: an image-generation client aborts a
    streamed response, the release is skipped, and with a small key pool the
    API stops serving entirely.
    """
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("only-key",),  # one key: a single leak is a full outage
        queue_expiry_seconds=5,
    )

    # Abort the stream after the first chunk, without draining it.
    with httpx.Client(timeout=10) as client:
        with client.stream(
            "GET", f"{proxy_url}/api/mock/stream", headers=proxy_headers()
        ) as response:
            assert response.status_code == 200
            for _ in response.iter_raw():
                break  # hang up mid-stream

    # The key must be back in rotation.
    after = httpx.get(
        f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=15
    )
    assert after.status_code == 200, (
        "the key was never released after the client disconnected, so the "
        "gateway can no longer serve any request"
    )


def test_midstream_upstream_failure_releases_the_key(proxy_server):
    """An upstream that dies mid-stream must not strand the credential either."""
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("only-key",),
        queue_expiry_seconds=5,
        retry_enabled=False,
    )

    with httpx.Client(timeout=10) as client:
        try:
            with client.stream(
                "GET", f"{proxy_url}/api/mock/stream-error", headers=proxy_headers()
            ) as response:
                for _ in response.iter_raw():
                    pass
        except httpx.HTTPError:
            pass  # the upstream failure surfacing as a broken stream is fine

    after = httpx.get(
        f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=15
    )
    assert after.status_code == 200, "an upstream failure mid-stream stranded the key"


def test_repeated_aborted_streams_keep_the_pool_alive(proxy_server):
    """
    The leak is cumulative: each abort costs one key.

    Aborting more times than there are keys is what turns a transient client
    behaviour into a dead API.
    """
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("key-a", "key-b"),
        queue_expiry_seconds=5,
    )

    for _ in range(4):  # twice the pool size
        with httpx.Client(timeout=10) as client:
            with client.stream(
                "GET", f"{proxy_url}/api/mock/stream", headers=proxy_headers()
            ) as response:
                for _ in response.iter_raw():
                    break

    after = httpx.get(
        f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=15
    )
    assert after.status_code == 200, "the whole key pool leaked away"


def test_request_timeout_midstream_releases_the_key(proxy_server):
    """
    A stream that stalls until the request timeout fires must release the key.

    The timeout cancels the task, and cancellation interrupts awaits — so the
    release has to survive being cancelled, not merely survive a clean finish.
    This is the shape of a slow image generation stalling in production.
    """
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("only-key",),
        request_timeout_seconds=2,
        queue_expiry_seconds=5,
        retry_enabled=False,
    )

    with httpx.Client(timeout=20) as client:
        try:
            with client.stream(
                "GET", f"{proxy_url}/api/mock/stream-hang", headers=proxy_headers()
            ) as response:
                for _ in response.iter_raw():
                    pass
        except httpx.HTTPError:
            pass  # the stall surfacing as a timeout/broken stream is fine

    after = httpx.get(
        f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=20
    )
    assert after.status_code == 200, (
        "a stalled stream cancelled by the request timeout stranded the key"
    )


def test_fully_consumed_stream_releases_the_key(proxy_server):
    """The happy path, so a fix cannot work by simply never locking."""
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("only-key",),
        queue_expiry_seconds=5,
    )

    with httpx.Client(timeout=10) as client:
        with client.stream(
            "GET", f"{proxy_url}/api/mock/stream", headers=proxy_headers()
        ) as response:
            body = b"".join(response.iter_raw())
    assert b"two" in body

    after = httpx.get(
        f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=15
    )
    assert after.status_code == 200


def test_demand_above_the_key_rate_ceiling_expires_instead_of_draining(
    proxy_server,
):
    """
    Document what a queue that "never drains" actually looks like.

    Key rate limits are not a fast-fail path like the IP/user quotas: a
    request waits for a key until the queue expiry, then fails. So sustained
    demand above `keys x key_rate_limit` leaves a permanently full queue where
    most requests wait the whole expiry and 504 — which reads as a hang but is
    the configured ceiling doing its job.

    Only what can drain within the expiry can ever succeed, so a max_size far
    above `rate x expiry` just buys a longer wait before the same failure.
    """
    # 1 key at 1 request / 2s, expiring after 6s: at most ~3 can be served.
    proxy_url = proxy_server(
        keys=("only-key",),
        key_rate_limit="1/2s",
        queue_expiry_seconds=6,
        queue_max_size=50,
        max_workers=10,
        retry_enabled=False,
    )

    import concurrent.futures

    def send(_):
        try:
            return httpx.get(
                f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=30
            ).status_code
        except httpx.HTTPError:
            return "error"

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(send, range(12)))

    served = codes.count(200)
    expired = codes.count(504)

    # Roughly expiry / rate can get through; the rest wait it out and fail.
    assert 1 <= served <= 5, f"expected a handful served, got {codes}"
    assert expired >= 5, f"expected the excess to expire, got {codes}"
    assert served + expired == len(codes), f"unexpected statuses: {codes}"


def test_serial_requests_still_work_with_concurrency_disabled(proxy_server):
    """
    Non-streaming requests must release the key too, and back-to-back requests
    on a single key must keep working.
    """
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("only-key",),
        queue_expiry_seconds=5,
    )

    for _ in range(3):
        response = httpx.get(
            f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=15
        )
        assert response.status_code == 200
