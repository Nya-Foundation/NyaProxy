"""
Metrics collection for NyaProxy, backed by ``prometheus_client``.

The Prometheus metric objects are the single source of truth. They are
exposed verbatim at ``/metrics`` for scraping, and also projected into a
JSON shape for the in-app dashboard. The only non-Prometheus state is a
bounded ring buffer of recent requests, used purely for the dashboard's
"recent activity" view (it is an event log, not a metric).
"""

import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from ..utils.redaction import mask_secret

#: Content-type for the Prometheus exposition format; re-exported for the
#: ``/metrics`` route so ``prometheus_client`` stays an implementation detail.
PROMETHEUS_CONTENT_TYPE = CONTENT_TYPE_LATEST

#: Latency histogram buckets, in seconds.
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

#: Number of recent request/response events kept for the dashboard log.
_HISTORY_SIZE = 2000

# Metric base names. Defined once so metric creation and snapshot parsing
# can never drift apart.
_M_REQUESTS = "nyaproxy_requests"
_M_RESPONSES = "nyaproxy_responses"
_M_DURATION = "nyaproxy_request_duration_seconds"
_M_ACTIVE = "nyaproxy_active_requests"
_M_RATE_LIMIT = "nyaproxy_rate_limit_hits"
_M_QUEUE = "nyaproxy_queue_hits"
_M_KEY = "nyaproxy_key_requests"


def _blank_api() -> Dict[str, Any]:
    """Zero-valued metric bucket for one API."""
    return {
        "requests": 0.0,
        "responses": {},
        "duration_count": 0.0,
        "duration_sum": 0.0,
        "active": 0.0,
        "rate_limit_hits": 0.0,
        "queue_hits": 0.0,
        "keys": {},
    }


class MetricsCollector:
    """
    Collects API-usage metrics into Prometheus instruments.

    The write API (``record_*``) is called from the request path. The read
    API (``get_*``) and ``render_prometheus`` are called from the dashboard
    and the ``/metrics`` endpoint.
    """

    def __init__(self) -> None:
        self.start_time = time.time()
        self.registry = CollectorRegistry()
        self.request_history: Deque[Dict[str, Any]] = deque(maxlen=_HISTORY_SIZE)

        # Last request timestamp per API — tracked on write so the dashboard
        # never has to scan the history ring buffer.
        self._last_request: Dict[str, float] = {}

        self._requests = Counter(
            _M_REQUESTS,
            "Total requests received, by API.",
            ["api"],
            registry=self.registry,
        )
        self._responses = Counter(
            _M_RESPONSES,
            "Total responses, by API and HTTP status code.",
            ["api", "status"],
            registry=self.registry,
        )
        self._duration = Histogram(
            _M_DURATION,
            "Upstream request duration in seconds, by API.",
            ["api"],
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self._active = Gauge(
            _M_ACTIVE,
            "Requests currently in flight, by API.",
            ["api"],
            registry=self.registry,
        )
        self._rate_limit_hits = Counter(
            _M_RATE_LIMIT,
            "Total rate-limit hits, by API.",
            ["api"],
            registry=self.registry,
        )
        self._queue_hits = Counter(
            _M_QUEUE,
            "Total requests routed through the queue, by API.",
            ["api"],
            registry=self.registry,
        )
        self._key_requests = Counter(
            _M_KEY,
            "Total requests, by API and masked key id.",
            ["api", "key"],
            registry=self.registry,
        )

    # ----------------------------------------------------------------- write

    def record_request(
        self, api_name: str, api_key: str, path: Optional[str] = None
    ) -> None:
        """
        Record a request being sent to an upstream API.

        ``path`` is kept in the history buffer only, never as a Prometheus
        label: paths are unbounded, and one label per distinct path would grow
        the metric series without limit.
        """
        key_id = mask_secret(api_key)
        now = time.time()

        self._requests.labels(api=api_name).inc()
        self._active.labels(api=api_name).inc()
        self._key_requests.labels(api=api_name, key=key_id).inc()
        self._last_request[api_name] = now

        self.request_history.append(
            {
                "type": "request",
                "api_name": api_name,
                "key_id": key_id,
                "path": path or "/",
                "timestamp": now,
            }
        )

    def record_response(
        self,
        api_name: str,
        api_key: str,
        status_code: int,
        elapsed: float,
        path: Optional[str] = None,
    ) -> None:
        """Record a response received from an upstream API."""
        self._responses.labels(api=api_name, status=str(status_code)).inc()
        self._duration.labels(api=api_name).observe(elapsed)
        self._active.labels(api=api_name).dec()

        self.request_history.append(
            {
                "type": "response",
                "api_name": api_name,
                "key_id": mask_secret(api_key),
                "status_code": status_code,
                "elapsed_ms": elapsed * 1000,
                "path": path or "/",
                "timestamp": time.time(),
            }
        )

    def record_rate_limit_hit(self, api_name: str) -> None:
        """Record a request being rejected or delayed by a rate limit."""
        self._rate_limit_hits.labels(api=api_name).inc()

    def record_queue_hit(self, api_name: str) -> None:
        """Record a request being routed through the queue."""
        self._queue_hits.labels(api=api_name).inc()

    # ------------------------------------------------------------------ read

    def render_prometheus(self) -> bytes:
        """Render all metrics in the Prometheus exposition format."""
        return generate_latest(self.registry)

    def get_recent_history(self, count: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent request/response events."""
        return list(self.request_history)[-count:]

    def get_api_metrics(self, api_name: str) -> Dict[str, Any]:
        """Return a metrics summary for a single API."""
        return self._format_api(self._snapshot().get(api_name, _blank_api()))

    def get_all_metrics(self) -> Dict[str, Any]:
        """Return global and per-API metrics formatted for the dashboard."""
        snapshot = self._snapshot()

        apis: Dict[str, Any] = {}
        total_requests = total_errors = 0
        total_rate_limit_hits = total_queue_hits = 0

        for api_name in sorted(snapshot):
            summary = self._format_api(snapshot[api_name])
            total_requests += summary["total_requests"]
            total_errors += summary["error_count"]
            total_rate_limit_hits += summary["rate_limit_hits"]
            total_queue_hits += summary["queue_hits"]

            apis[api_name] = {
                "requests": summary["total_requests"],
                "errors": summary["error_count"],
                "active_requests": summary["active_requests"],
                "avg_response_time_ms": summary["avg_response_time"],
                "rate_limit_hits": summary["rate_limit_hits"],
                "queue_hits": summary["queue_hits"],
                "last_request_time": self._last_request.get(api_name),
                "responses": summary["status_codes"],
                "key_usage": {
                    key_id: data["total"] for key_id, data in summary["keys"].items()
                },
            }

        return {
            "global": {
                "total_requests": total_requests,
                "total_errors": total_errors,
                "total_rate_limit_hits": total_rate_limit_hits,
                "total_queue_hits": total_queue_hits,
                "uptime_seconds": time.time() - self.start_time,
            },
            "apis": apis,
            "timestamp": time.time(),
        }

    def reset(self) -> None:
        """Clear every metric and the recent-activity history."""
        for metric in (
            self._requests,
            self._responses,
            self._duration,
            self._active,
            self._rate_limit_hits,
            self._queue_hits,
            self._key_requests,
        ):
            metric.clear()
        self.request_history.clear()
        self._last_request.clear()
        self.start_time = time.time()

    # --------------------------------------------------------------- private

    def _snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Collect every metric into a per-API dict in a single pass."""
        apis: Dict[str, Dict[str, Any]] = defaultdict(_blank_api)

        for metric in self.registry.collect():
            for sample in metric.samples:
                api = sample.labels.get("api")
                if api is None:
                    continue
                bucket = apis[api]
                name, value = sample.name, sample.value

                if name == f"{_M_REQUESTS}_total":
                    bucket["requests"] = value
                elif name == f"{_M_RESPONSES}_total":
                    bucket["responses"][sample.labels["status"]] = value
                elif name == f"{_M_DURATION}_count":
                    bucket["duration_count"] = value
                elif name == f"{_M_DURATION}_sum":
                    bucket["duration_sum"] = value
                elif name == _M_ACTIVE:
                    bucket["active"] = value
                elif name == f"{_M_RATE_LIMIT}_total":
                    bucket["rate_limit_hits"] = value
                elif name == f"{_M_QUEUE}_total":
                    bucket["queue_hits"] = value
                elif name == f"{_M_KEY}_total":
                    bucket["keys"][sample.labels["key"]] = value

        return apis

    @staticmethod
    def _format_api(bucket: Dict[str, Any]) -> Dict[str, Any]:
        """Turn one raw metric bucket into a formatted API summary."""
        status_codes = {int(code): int(n) for code, n in bucket["responses"].items()}
        success = sum(n for code, n in status_codes.items() if 200 <= code < 300)
        # Status 0 is the sentinel for a transport failure (no HTTP response).
        errors = sum(n for code, n in status_codes.items() if code >= 400 or code == 0)

        handled = success + errors
        success_rate = (success / handled * 100) if handled else 100.0

        count = bucket["duration_count"]
        avg_ms = (bucket["duration_sum"] / count * 1000) if count else 0.0

        return {
            "total_requests": int(bucket["requests"]),
            "active_requests": int(bucket["active"]),
            "success_count": success,
            "error_count": errors,
            "success_rate": success_rate,
            "avg_response_time": avg_ms,
            "status_codes": status_codes,
            "rate_limit_hits": int(bucket["rate_limit_hits"]),
            "queue_hits": int(bucket["queue_hits"]),
            "keys": {
                key_id: {"total": int(total)}
                for key_id, total in bucket["keys"].items()
            },
        }
