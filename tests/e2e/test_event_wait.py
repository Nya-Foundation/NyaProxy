"""
E2E coverage for the event-driven key wait, against a real proxy process and
a real upstream.

The properties that must hold in the real system: an exclusive key is handed
from one finished request to the next without stalling, rate-limit pacing is
never leaked past by a wake-up, and clients that give up do not wedge the
worker pool. Shapes mirror production: one slow exclusive credential serving
a burst of image-generation-sized requests.
"""

import concurrent.futures
import time

import httpx
import pytest

from tests.e2e.conftest import PROXY_KEY

pytestmark = pytest.mark.e2e


def proxy_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_KEY}"}


def test_burst_on_one_exclusive_key_serializes_without_stalling(proxy_server):
    """
    Six concurrent requests, one key, no concurrency on it, 300ms each.

    Serialization proves the lock is honoured (wall time at least the sum of
    holds); completion well under the expiry proves each release actually
    reached the next waiter — the old tick-lottery is where handoffs leaked
    time, and a missed handoff would push the tail toward the 20s expiry.
    """
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("only-key",),
        queue_expiry_seconds=20,
        max_workers=8,
        retry_enabled=False,
    )

    def send(_):
        response = httpx.get(
            f"{proxy_url}/api/mock/sleep-300", headers=proxy_headers(), timeout=25
        )
        return response.status_code

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(send, range(6)))
    wall = time.time() - started

    assert codes == [200] * 6
    # 6 × 300ms on one exclusive key cannot finish faster than ~1.5s...
    assert wall >= 1.4, f"holds overlapped on an exclusive key ({wall:.2f}s)"
    # ...and event handoff should keep total far from the 20s expiry.
    assert wall < 15, f"handoffs stalled ({wall:.2f}s)"


def test_notifications_cannot_leak_past_the_rate_limit(proxy_server):
    """
    A wake-up is a signal to re-check, never a grant. With one key at one
    request per 2s, three requests must take at least two full windows no
    matter how promptly releases notify the waiters.
    """
    proxy_url = proxy_server(
        keys=("only-key",),
        key_rate_limit="1/2s",
        queue_expiry_seconds=15,
        max_workers=6,
        retry_enabled=False,
    )

    def send(_):
        response = httpx.get(
            f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=20
        )
        return response.status_code

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        codes = list(pool.map(send, range(3)))
    wall = time.time() - started

    assert codes == [200] * 3
    assert wall >= 3.8, (
        f"three requests through a 1/2s key finished in {wall:.2f}s — "
        "a notification let a waiter skip the rate-limit window"
    )


def test_abandoned_clients_do_not_wedge_the_worker_pool(proxy_server):
    """
    Clients that give up while waiting must not keep occupying workers.

    With two workers and one exclusive key: a slow request holds the key,
    impatient clients claim the remaining worker slots and hang up. A later
    patient request must still be served promptly.
    """
    proxy_url = proxy_server(
        key_concurrency=False,
        keys=("only-key",),
        queue_expiry_seconds=30,
        max_workers=2,
        retry_enabled=False,
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        # Occupy the key for ~2s.
        holder = pool.submit(
            lambda: (
                httpx.get(
                    f"{proxy_url}/api/mock/sleep-2000",
                    headers=proxy_headers(),
                    timeout=30,
                ).status_code
            )
        )
        time.sleep(0.3)

        # Impatient clients: claim worker slots, then abandon them.
        def impatient():
            try:
                httpx.get(
                    f"{proxy_url}/api/mock/plain",
                    headers=proxy_headers(),
                    timeout=0.4,
                )
            except httpx.HTTPError:
                pass

        list(pool.map(lambda f: f(), [impatient, impatient, impatient]))

        # The patient client arrives after the abandonments.
        patient = pool.submit(
            lambda: (
                httpx.get(
                    f"{proxy_url}/api/mock/plain", headers=proxy_headers(), timeout=15
                ).status_code
            )
        )

        assert holder.result(timeout=30) == 200
        started = time.time()
        assert patient.result(timeout=15) == 200
        assert time.time() - started < 10
