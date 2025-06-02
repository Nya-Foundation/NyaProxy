"""
Metrics collection for monitoring API usage.
"""

import time
from collections import deque
from typing import Any, Dict, List, Optional

from loguru import logger

from ..common.constants import MAX_QUEUE_SIZE
from ..utils.helper import mask_secret


class MetricsCollector:
    """
    Collects and aggregates metrics about API usage.

    This class provides a centralized way to track request volumes,
    response times, error rates, and other performance indicators
    across different APIs and keys.
    """

    def __init__(
        self,
    ):
        """
        Initialize the metrics collector.

        Args:
            logger: Logger instance
        """
        self.last_reset = time.time()

        # Initialize request history tracking
        self.request_history = deque(maxlen=2000)  # Store last 2000 requests/responses

        # Initialize metrics storage
        self._init_metrics()

    def record_request(self, api_name: str, api_key: str) -> None:
        """
        Record a request to an API.

        Args:
            api_name: Name of the API
            api_key: the API key used for the request
        """

        key_id = mask_secret(api_key)

        # Initialize API in dictionaries if not present
        self._ensure_api_exists(api_name)
        self._ensure_key_exists(api_name, key_id)

        # Increment request counters
        self._request_counts[api_name]["total"] += 1
        self._request_counts[api_name]["active"] += 1

        # Track key usage
        self._key_usage[api_name][key_id]["total"] += 1
        self._key_usage[api_name][key_id]["active"] += 1

        # Record in history
        self.request_history.append(
            {
                "type": "request",
                "api_name": api_name,
                "key_id": key_id,
                "timestamp": time.time(),
            }
        )

    def record_response(
        self, api_name: str, api_key: str, status_code: int, elapsed: float
    ) -> None:
        """
        Record a response from an API.

        Args:
            api_name: Name of the API
            api_key: the API key used for the request
            status_code: HTTP status code
            elapsed: Time taken for the request in seconds
        """

        key_id = mask_secret(api_key)

        # Initialize API in dictionaries if not present
        self._ensure_api_exists(api_name)
        self._ensure_key_exists(api_name, key_id)

        # Decrement active request counter
        self._request_counts[api_name]["active"] = max(
            0, self._request_counts[api_name]["active"] - 1
        )

        # Record status code
        if status_code not in self._status_codes[api_name]:
            self._status_codes[api_name][status_code] = 0

        self._status_codes[api_name][status_code] += 1

        # Record response time (convert to milliseconds)
        elapsed_ms = elapsed * 1000
        self._response_times[api_name].append(elapsed_ms)

        # Update key metrics
        key_metrics = self._key_usage[api_name][key_id]
        key_metrics["active"] = max(0, key_metrics["active"] - 1)

        # Record status code for key
        if status_code not in key_metrics["status_codes"]:
            key_metrics["status_codes"][status_code] = 0

        key_metrics["status_codes"][status_code] += 1

        # Record success/error for key
        if 200 <= status_code < 300:
            key_metrics["success"] += 1
        elif status_code >= 400:
            key_metrics["error"] += 1

        # Record in history
        self.request_history.append(
            {
                "type": "response",
                "api_name": api_name,
                "key_id": key_id,
                "status_code": status_code,
                "elapsed_ms": elapsed_ms,
                "timestamp": time.time(),
            }
        )

    def record_rate_limit_hit(self, api_name: str) -> None:
        """
        Record a rate limit hit.

        Args:
            api_name: Name of the API
        """
        # Initialize API in dictionaries if not present

        self._ensure_api_exists(api_name)
        self._rate_limit_hits[api_name] += 1

    def record_queue_hit(self, api_name: str) -> None:
        """
        Record a request being queued.

        Args:
            api_name: Name of the API
        """
        # Initialize API in dictionaries if not present
        self._ensure_api_exists(api_name)

        # Increment queue hit counter
        self._queue_hits[api_name] += 1

    def _ensure_api_exists(self, api_name: str) -> None:
        """
        Ensure that an API exists in all metric dictionaries.

        Args:
            api_name: Name of the API
        """
        if api_name not in self._request_counts:
            self._request_counts[api_name] = {"total": 0, "active": 0}

        if api_name not in self._status_codes:
            self._status_codes[api_name] = {}

        if api_name not in self._response_times:
            self._response_times[api_name] = deque(maxlen=MAX_QUEUE_SIZE)

        if api_name not in self._rate_limit_hits:
            self._rate_limit_hits[api_name] = 0

        if api_name not in self._queue_hits:
            self._queue_hits[api_name] = 0

        if api_name not in self._key_usage:
            self._key_usage[api_name] = {}

    def _ensure_key_exists(self, api_name: str, key_id: str) -> None:
        """
        Ensure that a key exists in the key usage dictionary.

        Args:
            api_name: Name of the API
            key_id: ID of the API key
        """
        if api_name not in self._key_usage:
            self._key_usage[api_name] = {}

        if key_id not in self._key_usage[api_name]:
            self._key_usage[api_name][key_id] = {
                "total": 0,
                "active": 0,
                "success": 0,
                "error": 0,
                "status_codes": {},
            }

    def get_api_metrics(self, api_name: str) -> Dict[str, Any]:
        """
        Get metrics for a specific API.

        Args:
            api_name: Name of the API

        Returns:
            Dictionary with API metrics
        """
        # Initialize metrics structure
        metrics = {
            "total_requests": 0,
            "active_requests": 0,
            "success_count": 0,
            "error_count": 0,
            "success_rate": 100.0,  # Default to 100% if no requests
            "avg_response_time": 0,
            "min_response_time": 0,
            "max_response_time": 0,
            "status_codes": {},
            "rate_limit_hits": 0,
            "queue_hits": 0,
            "keys": {},
        }

        # If API doesn't exist in metrics, return default structure
        if api_name not in self._request_counts:
            return metrics

        # Fill in request counts
        metrics["total_requests"] = self._request_counts[api_name].get("total", 0)
        metrics["active_requests"] = self._request_counts[api_name].get("active", 0)

        # Fill in status codes and calculate success/error rates
        if api_name in self._status_codes:
            metrics["status_codes"] = dict(self._status_codes[api_name])

            # Calculate success and error counts
            metrics["success_count"] = sum(
                count
                for status, count in self._status_codes[api_name].items()
                if 200 <= status < 300
            )
            metrics["error_count"] = sum(
                count
                for status, count in self._status_codes[api_name].items()
                if status >= 400
            )

            # Calculate success rate
            total = metrics["success_count"] + metrics["error_count"]
            if total > 0:
                metrics["success_rate"] = (metrics["success_count"] / total) * 100

        # Fill in response time metrics
        if api_name in self._response_times and self._response_times[api_name]:
            times = list(self._response_times[api_name])
            metrics["avg_response_time"] = sum(times) / len(times)
            metrics["min_response_time"] = min(times)
            metrics["max_response_time"] = max(times)

        # Fill in rate limit and queue hits
        metrics["rate_limit_hits"] = self._rate_limit_hits.get(api_name, 0)

        if api_name in self._queue_hits:
            metrics["queue_hits"] = self._queue_hits[api_name]

        # Fill in key metrics
        if api_name in self._key_usage:
            for key_id, key_metrics in self._key_usage[api_name].items():
                # Calculate key success rate
                key_success = key_metrics.get("success", 0)
                key_error = key_metrics.get("error", 0)
                key_success_rate = 100.0

                if key_success + key_error > 0:
                    key_success_rate = (key_success / (key_success + key_error)) * 100

                # Record key metrics
                metrics["keys"][key_id] = {
                    "total": key_metrics.get("total", 0),
                    "active": key_metrics.get("active", 0),
                    "success": key_success,
                    "error": key_error,
                    "success_rate": key_success_rate,
                }

        return metrics

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of all metrics.

        Returns:
            Dictionary with metrics summary
        """
        # Calculate global statistics
        total_requests = sum(
            metrics.get("total", 0) for metrics in self._request_counts.values()
        )
        active_requests = sum(
            metrics.get("active", 0) for metrics in self._request_counts.values()
        )

        # Calculate total success and error counts
        total_success = 0
        total_error = 0

        for api_name in self._status_codes:
            total_success += sum(
                count
                for status, count in self._status_codes[api_name].items()
                if 200 <= status < 300
            )
            total_error += sum(
                count
                for status, count in self._status_codes[api_name].items()
                if status >= 400
            )

        # Calculate overall success rate
        success_rate = 100.0
        if total_success + total_error > 0:
            success_rate = (total_success / (total_success + total_error)) * 100

        # Calculate overall average response time
        all_response_times = []
        for times in self._response_times.values():
            all_response_times.extend(times)

        avg_response_time = 0
        if all_response_times:
            avg_response_time = sum(all_response_times) / len(all_response_times)

        # Collect API-specific metrics
        apis = {}
        for api_name in sorted(self._request_counts.keys()):
            apis[api_name] = self.get_api_metrics(api_name)

        # Build summary
        return {
            "total_requests": total_requests,
            "active_requests": active_requests,
            "success_count": total_success,
            "error_count": total_error,
            "success_rate": success_rate,
            "avg_response_time": avg_response_time,
            "uptime": time.time() - self.last_reset,
            "apis": apis,
        }

    def get_all_metrics(self) -> Dict[str, Any]:
        """
        Get all metrics data formatted for dashboard visualization.

        Returns:
            Dictionary with formatted metrics for the dashboard
        """
        # Get summary metrics
        summary = self.get_summary()

        # Format for dashboard display
        apis_data = {}
        for api_name, api_metrics in summary["apis"].items():
            # Find the last request timestamp for this API
            last_request_time = self._get_last_request_time(api_name)

            # Format response codes
            responses = {
                str(code): count for code, count in api_metrics["status_codes"].items()
            }

            # Format key usage data
            key_usage = {
                key_id: data["total"] for key_id, data in api_metrics["keys"].items()
            }

            # Create formatted API metrics
            apis_data[api_name] = {
                "requests": api_metrics["total_requests"],
                "errors": api_metrics["error_count"],
                "avg_response_time_ms": api_metrics["avg_response_time"],
                "min_response_time_ms": api_metrics["min_response_time"],
                "max_response_time_ms": api_metrics["max_response_time"],
                "rate_limit_hits": api_metrics["rate_limit_hits"],
                "queue_hits": api_metrics["queue_hits"],
                "last_request_time": last_request_time,
                "responses": responses,
                "key_usage": key_usage,
            }

        return {
            "global": {
                "total_requests": summary["total_requests"],
                "total_errors": summary["error_count"],
                "total_rate_limit_hits": self._get_total_rate_limit_hits(),
                "total_queue_hits": self._get_total_queue_hits(),
                "uptime_seconds": summary["uptime"],
            },
            "apis": apis_data,
            "timestamp": time.time(),
        }

    def get_recent_history(self, count: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent request/response history.

        Args:
            count: Number of history entries to return

        Returns:
            List of history entries
        """
        return list(self.request_history)[-count:]

    def _get_last_request_time(self, api_name: str) -> Optional[float]:
        """
        Get the timestamp of the last request for a specific API.
        """
        for entry in reversed(self.request_history):
            if entry["api_name"] == api_name and entry["type"] == "request":
                return entry["timestamp"]
        return None

    def _get_total_rate_limit_hits(self) -> int:
        """
        Get total rate limit hits across all APIs.
        """
        total = 0
        for limit_hit in self._rate_limit_hits.values():
            total += limit_hit
        return total

    def _get_total_queue_hits(self) -> int:
        """
        Get total queue hits across all APIs.
        """
        return sum(self._queue_hits.values())

    def reset(self) -> None:
        """
        Reset all metrics.
        """
        self.last_reset = time.time()
        self._init_metrics()
        logger.info("Metrics have been reset")

    def _init_metrics(self) -> None:
        """
        Initialize or reset all metrics data structures.
        """
        # Response time history with fixed size per API
        self._response_times: Dict[str, deque] = {}

        # Request counts by API
        self._request_counts: Dict[str, Dict[str, int]] = {}

        # Status code distribution by API
        self._status_codes: Dict[str, Dict[int, int]] = {}

        # Rate limit hits by API
        self._rate_limit_hits: Dict[str, int] = {}

        # Queue hits by API
        self._queue_hits: Dict[str, int] = {}

        # Key usage statistics by API
        self._key_usage: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Reset request history
        self.request_history.clear()
