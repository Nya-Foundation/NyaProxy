#!/usr/bin/env python3
"""
Interactive load-test tool for NyaProxy.

Three subcommands, designed to be composed across terminals:

  upstream   Run a mock upstream API. The default port (8082) matches the
             `test` API in nya/config.yaml.

  burst      Blast N concurrent requests through NyaProxy, print a summary
             of status codes and latency distribution.

  watch      Poll NyaProxy's /metrics endpoint and pretty-print a live
             snapshot, with per-tick rates for the important counters.

Typical session (four terminals):

    1. python scripts/burst.py upstream
    2. nyaproxy --config nya/config.yaml
    3. python scripts/burst.py burst -n 200 -c 20
    4. python scripts/burst.py watch

Only the deps NyaProxy already has (fastapi, uvicorn, httpx) are required.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import sys
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

import httpx
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

DEFAULT_PROXY = "http://127.0.0.1:8080"
DEFAULT_UPSTREAM_PORT = 8082
# Matches the `test` API's rate_limit_paths (`/v1/*`) in nya/config.yaml, so
# requests are actually tracked in /metrics. Paths outside rate_limit_paths
# still proxy successfully, but never increment the per-request counters.
DEFAULT_PATH = "/api/test/v1/echo"


# ---------------------------------------------------------------------------
# upstream — a mock backend that NyaProxy can forward to
# ---------------------------------------------------------------------------


def build_upstream_app(latency_ms: int, fail_rate: float) -> FastAPI:
    """Build a FastAPI app that accepts any path and echoes back a JSON body."""
    app = FastAPI(title="burst.py mock upstream")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def echo(path: str, request: Request) -> JSONResponse:
        if latency_ms > 0:
            await asyncio.sleep(latency_ms / 1000)
        auth = request.headers.get("authorization", "")
        ua = request.headers.get("user-agent", "")
        # One line per request so header rotation is observable from the
        # upstream's stdout/log.
        print(
            f"[upstream] {request.method} /{path}  auth={auth!r}  ua={ua!r}",
            flush=True,
        )
        if fail_rate > 0 and random.random() < fail_rate:
            return JSONResponse({"injected": "failure"}, status_code=500)
        return JSONResponse(
            {
                "path": "/" + path,
                "method": request.method,
                "received_authorization": auth,
                "received_user_agent": ua,
            }
        )

    return app


def cmd_upstream(args: argparse.Namespace) -> None:
    print(
        f"[upstream] listening on http://127.0.0.1:{args.port}  "
        f"(latency={args.latency_ms}ms, fail_rate={args.fail_rate})"
    )
    uvicorn.run(
        build_upstream_app(args.latency_ms, args.fail_rate),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )


# ---------------------------------------------------------------------------
# burst — concurrent request blaster
# ---------------------------------------------------------------------------


async def _one_request(
    client: httpx.AsyncClient, url: str, headers: Dict[str, str]
) -> Tuple[Optional[int], float, Optional[str]]:
    start = time.monotonic()
    try:
        response = await client.get(url, headers=headers)
        return response.status_code, (time.monotonic() - start) * 1000, None
    except Exception as exc:
        return None, (time.monotonic() - start) * 1000, exc.__class__.__name__


async def _run_burst(args: argparse.Namespace) -> None:
    url = args.proxy.rstrip("/") + args.path
    headers = {"Authorization": f"Bearer {args.key}"} if args.key else {}
    semaphore = asyncio.Semaphore(args.concurrency)

    async def task(
        client: httpx.AsyncClient,
    ) -> Tuple[Optional[int], float, Optional[str]]:
        async with semaphore:
            return await _one_request(client, url, headers)

    print(
        f"[burst] {args.count} requests, concurrency={args.concurrency}, target={url}"
    )

    timeout = httpx.Timeout(args.timeout, connect=2.0)
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout) as client:
        results = await asyncio.gather(*(task(client) for _ in range(args.count)))
    elapsed = time.monotonic() - started

    _print_burst_summary(results, elapsed)


def _print_burst_summary(
    results: List[Tuple[Optional[int], float, Optional[str]]], elapsed: float
) -> None:
    by_status: Counter = Counter()
    errors: Counter = Counter()
    latencies: List[float] = []

    for status, latency_ms, err in results:
        if err is not None:
            errors[err] += 1
        else:
            by_status[status] += 1
            latencies.append(latency_ms)

    total = len(results)
    print()
    print(f"  Total:     {total}  ({total / elapsed:.1f} req/s, {elapsed:.2f}s wall)")
    print("  By status:")
    for code in sorted(by_status):
        bar = "█" * int(40 * by_status[code] / total)
        print(f"    {code:>5}  {by_status[code]:>5}  {bar}")
    for err in sorted(errors):
        print(f"    {err:>5}  {errors[err]:>5}  (client-side)")
    if latencies:
        latencies.sort()
        print("  Latency (ms):")
        for label, value in [
            ("p50", latencies[len(latencies) // 2]),
            ("p95", latencies[int(len(latencies) * 0.95)]),
            ("p99", latencies[int(len(latencies) * 0.99)]),
            ("max", latencies[-1]),
        ]:
            print(f"    {label:>5}  {value:>7.1f}")
    print()


def cmd_burst(args: argparse.Namespace) -> None:
    asyncio.run(_run_burst(args))


# ---------------------------------------------------------------------------
# watch — live /metrics snapshot with per-tick rates
# ---------------------------------------------------------------------------

#: Match `metric_name{labels} value` (and `metric_name value` without labels).
_SAMPLE_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([0-9eE+.\-]+)")
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def _parse_metrics(text: str) -> List[Tuple[str, Dict[str, str], float]]:
    samples: List[Tuple[str, Dict[str, str], float]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if not match:
            continue
        name, raw_labels, value = match.groups()
        labels = dict(_LABEL_RE.findall(raw_labels or ""))
        try:
            samples.append((name, labels, float(value)))
        except ValueError:
            continue
    return samples


def _collect_per_api(
    samples: List[Tuple[str, Dict[str, str], float]],
) -> Dict[str, Dict[str, float]]:
    """Group samples by `api` label into a compact snapshot per API."""
    apis: Dict[str, Dict[str, float]] = {}
    for name, labels, value in samples:
        api = labels.get("api")
        if api is None:
            continue
        bucket = apis.setdefault(
            api,
            {
                "requests": 0.0,
                "responses_2xx": 0.0,
                "responses_4xx": 0.0,
                "responses_5xx": 0.0,
                "responses_err": 0.0,  # status 0 (transport failure)
                "active": 0.0,
                "rate_limit_hits": 0.0,
                "queue_hits": 0.0,
                "duration_count": 0.0,
                "duration_sum": 0.0,
            },
        )
        if name == "nyaproxy_requests_total":
            bucket["requests"] = value
        elif name == "nyaproxy_responses_total":
            try:
                status = int(labels.get("status", "0"))
            except ValueError:
                continue
            if status == 0:
                bucket["responses_err"] += value
            elif 200 <= status < 300:
                bucket["responses_2xx"] += value
            elif 400 <= status < 500:
                bucket["responses_4xx"] += value
            elif status >= 500:
                bucket["responses_5xx"] += value
        elif name == "nyaproxy_active_requests":
            bucket["active"] = value
        elif name == "nyaproxy_rate_limit_hits_total":
            bucket["rate_limit_hits"] = value
        elif name == "nyaproxy_queue_hits_total":
            bucket["queue_hits"] = value
        elif name == "nyaproxy_request_duration_seconds_count":
            bucket["duration_count"] = value
        elif name == "nyaproxy_request_duration_seconds_sum":
            bucket["duration_sum"] = value
    return apis


def _render_watch(
    current: Dict[str, Dict[str, float]],
    previous: Optional[Dict[str, Dict[str, float]]],
    interval: float,
) -> str:
    if not current:
        return "(no per-api metrics yet — has any traffic flowed through NyaProxy?)\n"

    lines = []
    headers = [
        "api",
        "req",
        "Δ/s",
        "2xx",
        "4xx",
        "5xx",
        "err",
        "active",
        "rlim",
        "queue",
        "avg ms",
    ]
    widths = [14, 7, 7, 6, 6, 6, 5, 7, 6, 7, 8]
    lines.append(
        "  ".join(
            h.rjust(w) if i else h.ljust(w)
            for i, (h, w) in enumerate(zip(headers, widths))
        )
    )
    lines.append("  ".join("-" * w for w in widths))

    for api in sorted(current):
        cur = current[api]
        prev = (previous or {}).get(api, {})
        rps = (
            (cur["requests"] - prev.get("requests", 0.0)) / interval
            if previous
            else 0.0
        )
        avg_ms = (
            cur["duration_sum"] / cur["duration_count"] * 1000
            if cur["duration_count"]
            else 0.0
        )
        row = [
            api[:14],
            f"{int(cur['requests'])}",
            f"{rps:.1f}",
            f"{int(cur['responses_2xx'])}",
            f"{int(cur['responses_4xx'])}",
            f"{int(cur['responses_5xx'])}",
            f"{int(cur['responses_err'])}",
            f"{int(cur['active'])}",
            f"{int(cur['rate_limit_hits'])}",
            f"{int(cur['queue_hits'])}",
            f"{avg_ms:.1f}",
        ]
        lines.append(
            "  ".join(
                cell.rjust(w) if i else cell.ljust(w)
                for i, (cell, w) in enumerate(zip(row, widths))
            )
        )
    return "\n".join(lines) + "\n"


def cmd_watch(args: argparse.Namespace) -> None:
    metrics_url = args.proxy.rstrip("/") + "/metrics"
    previous: Optional[Dict[str, Dict[str, float]]] = None
    print(f"[watch] polling {metrics_url} every {args.interval}s — Ctrl-C to stop")

    try:
        with httpx.Client(timeout=3.0) as client:
            while True:
                try:
                    response = client.get(metrics_url)
                    response.raise_for_status()
                    current = _collect_per_api(_parse_metrics(response.text))
                except Exception as exc:
                    sys.stdout.write(f"\033[2J\033[H[watch] error: {exc}\n")
                    sys.stdout.flush()
                    time.sleep(args.interval)
                    continue

                sys.stdout.write("\033[2J\033[H")
                sys.stdout.write(
                    f"[watch] {time.strftime('%H:%M:%S')}  {metrics_url}\n\n"
                )
                sys.stdout.write(_render_watch(current, previous, args.interval))
                sys.stdout.flush()

                previous = current
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print()


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="burst",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    up = subparsers.add_parser("upstream", help="run a mock upstream API")
    up.add_argument("--port", type=int, default=DEFAULT_UPSTREAM_PORT)
    up.add_argument(
        "--latency-ms",
        type=int,
        default=0,
        help="injected per-request latency in milliseconds",
    )
    up.add_argument(
        "--fail-rate",
        type=float,
        default=0.0,
        help="probability of returning a 500 (0.0–1.0)",
    )
    up.set_defaults(func=cmd_upstream)

    b = subparsers.add_parser(
        "burst", help="blast concurrent requests through NyaProxy"
    )
    b.add_argument(
        "--proxy",
        default=DEFAULT_PROXY,
        help="NyaProxy base URL (default: %(default)s)",
    )
    b.add_argument(
        "--path",
        default=DEFAULT_PATH,
        help="path to hit, including leading / (default: %(default)s)",
    )
    b.add_argument(
        "--key",
        default=os.environ.get("NYAPROXY_KEY", ""),
        help="bearer token (default: $NYAPROXY_KEY, empty disables)",
    )
    b.add_argument("-n", "--count", type=int, default=100)
    b.add_argument("-c", "--concurrency", type=int, default=10)
    b.add_argument("--timeout", type=float, default=10.0)
    b.set_defaults(func=cmd_burst)

    w = subparsers.add_parser("watch", help="live snapshot of NyaProxy's /metrics")
    w.add_argument(
        "--proxy",
        default=DEFAULT_PROXY,
        help="NyaProxy base URL (default: %(default)s)",
    )
    w.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="poll interval in seconds (default: %(default)s)",
    )
    w.set_defaults(func=cmd_watch)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
