"""
A production-shaped load scenario, end to end.

The real deployment this mirrors: five exclusive credentials
(key_concurrency: false) fronting an image-generation API, each request
holding its key for a long, variable time, a strict per-key pacing limit,
and — crucially — the credentials shared with consumers *outside* the
gateway, so any attempt can bounce off an upstream 429 through no fault of
NyaProxy's own accounting.

Production numbers are scaled ~10x in time so the test runs in tens of
seconds instead of eight minutes, keeping every ratio intact:

    production                      this test
    ----------                      ---------
    hold 5-7s per request           hold 500-700ms
    key_rate_limit 1/12s            key_rate_limit 1/1s
    retry_after_seconds 3           retry_after_seconds 0.3
    hold/window ~ 0.55              hold/window ~ 0.6

200 requests burst in at once. Ceiling: 5 keys x 1 grant/s = 5 successes
per second, so the burst needs ~40s to drain — the assertions below are
derived from that arithmetic, not tuned to observations.
"""

import concurrent.futures
import random
import time

import httpx
import pytest

from tests.e2e.conftest import PROXY_KEY

pytestmark = pytest.mark.e2e

KEYS = ("key-1", "key-2", "key-3", "key-4", "key-5")
BURST = 200
WINDOW_SECONDS = 1.0


def proxy_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {PROXY_KEY}"}


def test_burst_of_200_on_five_shared_exclusive_keys(proxy_server, upstream_server):
    _, upstream = upstream_server
    upstream.shared_key_429_rate = 0.15  # keys are used outside NyaProxy too

    proxy_url = proxy_server(
        key_concurrency=False,
        keys=KEYS,
        key_rate_limit="1/1s",
        queue_expiry_seconds=120,  # above the ~40s drain: nothing should expire
        queue_max_size=BURST + 50,
        max_workers=10,
        retry_after_seconds=0.3,
        # Production uses 300s against a ~480s worst-case wait — meaning a
        # real 200-burst would partially time out there too. Here the timeout
        # clears the ~40s drain so the assertions isolate queue mechanics.
        request_timeout_seconds=100,
    )

    rng = random.Random(7)
    holds_ms = [rng.randint(500, 700) for _ in range(BURST)]

    def send(hold_ms: int) -> int:
        try:
            return httpx.get(
                f"{proxy_url}/api/mock/sleep-{hold_ms}",
                headers=proxy_headers(),
                timeout=110,
            ).status_code
        except httpx.HTTPError:
            return -1

    started = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=BURST) as pool:
        codes = list(pool.map(send, holds_ms))
    wall = time.time() - started

    # ---- outcome ----------------------------------------------------------
    # Retries absorb the 15% external contention. A request that draws three
    # 429s in a row (~0.3%) legitimately surfaces the last 429 to the client;
    # anything else — 504 expiry, 503 overflow, 500, transport error — is a
    # gateway failure.
    assert set(codes) <= {200, 429}, f"unexpected statuses: {sorted(set(codes))}"
    successes = codes.count(200)
    assert successes >= int(BURST * 0.97), (
        f"only {successes}/{BURST} succeeded — retries are not absorbing external 429s"
    )

    # ---- the injected chaos really happened -------------------------------
    hits = [r for r in upstream.records if "status" in r]
    rejected = [r for r in hits if r["status"] == 429]
    served = [r for r in hits if r["status"] == 200]
    assert len(rejected) >= 10, "the 15% external-contention injection was inert"
    assert len(served) == successes

    # ---- rate limit honoured under chaos ----------------------------------
    # A successful use consumes the key's window, so after any 200 the next
    # attempt on that key must wait out the window. (After a 429 the slot is
    # refunded, so a quicker retry there is correct behaviour, not a leak.)
    # Grant happens inside NyaProxy; we observe arrival at the upstream. With
    # 200 client threads the scheduling jitter between those two moments can
    # reach a few hundred ms. A genuine leak shows sub-0.7s gaps (the next
    # grant following the ~0.6s lock release), so 0.3 still discriminates.
    tolerance = 0.3
    for key in KEYS:
        key_hits = sorted((r for r in hits if r["key"] == key), key=lambda r: r["at"])
        for prev, nxt in zip(key_hits, key_hits[1:]):
            if prev["status"] == 200:
                gap = nxt["at"] - prev["at"]
                assert gap >= WINDOW_SECONDS - tolerance, (
                    f"{key}: attempt {gap:.3f}s after a success — the per-key "
                    "rate limit leaked under retry/notify pressure"
                )

    # ---- exclusivity honoured under chaos ---------------------------------
    # key_concurrency: false means the upstream must never see two in-flight
    # holds on one key. 429 rejections return instantly and hold nothing.
    for key in KEYS:
        key_served = sorted(
            (r for r in served if r["key"] == key), key=lambda r: r["at"]
        )
        for prev, nxt in zip(key_served, key_served[1:]):
            assert nxt["at"] >= prev["done_at"] - 0.1, (
                f"{key}: a second request arrived while one was in flight — "
                "exclusive key served concurrently"
            )

    # ---- throughput is the configured ceiling, no more, no less -----------
    # The busiest key's successes are each >= 1 window apart, which bounds the
    # wall clock from below; the ceiling itself bounds how fast the burst can
    # drain. Far above that means grants stalled.
    busiest = max(sum(1 for r in served if r["key"] == key) for key in KEYS)
    floor = (busiest - 1) * WINDOW_SECONDS
    assert wall >= floor - 1.0, (
        f"drained {BURST} requests in {wall:.1f}s with busiest key serving "
        f"{busiest} — faster than the rate limit permits"
    )
    assert wall < floor + 30, (
        f"took {wall:.1f}s against a ~{floor:.0f}s floor — grants are stalling"
    )

    shares = {key: sum(1 for r in served if r["key"] == key) for key in KEYS}
    print(
        f"\nburst drained in {wall:.1f}s (floor ~{floor:.0f}s): "
        f"{successes}/{BURST} ok, {codes.count(429)} client 429s, "
        f"{len(rejected)} upstream rejections absorbed, per-key {shares}"
    )

    # ---- work spread across the pool --------------------------------------
    for key in KEYS:
        share = sum(1 for r in served if r["key"] == key)
        assert share >= successes // len(KEYS) // 2, (
            f"{key} served only {share} of {successes} — rotation is not spreading load"
        )
