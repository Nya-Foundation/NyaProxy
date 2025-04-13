"""
Metrics collector for tracking proxy performance.
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List


class MetricsCollector:
    """
    Collects and stores metrics about the proxy's performance.
    """

    # Class variable to store singleton instances
    _instances = {}
    _instances_lock = threading.RLock()

    @classmethod
    def get_instance(
        cls,
        logger: logging.Logger,
        metrics_path: str = "./.metrics",
        history_size: int = 1000,
        persist_interval: int = 60,
    ) -> "MetricsCollector":
        """
        Get or create a MetricsCollector instance for the given metrics_path.

        Args:
            logger: Logger instance
            metrics_path: Path to store metrics data
            history_size: Number of recent requests to keep in memory
            persist_interval: How often to save metrics to disk (in seconds)

        Returns:
            MetricsCollector instance for the given metrics_path
        """
        abs_metrics_path = os.path.abspath(metrics_path)

        with cls._instances_lock:
            if abs_metrics_path not in cls._instances:
                cls._instances[abs_metrics_path] = cls(
                    logger, metrics_path, history_size, persist_interval
                )
            return cls._instances[abs_metrics_path]

    def __init__(
        self,
        logger: logging.Logger,
        metrics_path: str = "./.metrics",
        history_size: int = 1000,
        persist_interval: int = 60,
    ):
        """
        Initialize the metrics collector.

        Args:
            logger: Logger instance
            metrics_path: Path to store metrics data
            history_size: Number of recent requests to keep in memory
            persist_interval: How often to save metrics to disk (in seconds)
        """
        self.logger = logger
        self.metrics_path = metrics_path
        self.history_size = history_size
        self.persist_interval = persist_interval

        # Create metrics directory if it doesn't exist
        os.makedirs(metrics_path, exist_ok=True)

        # Thread safety
        self.lock = threading.RLock()

        # Initialize metrics containers
        self.initialize_metrics()

        # Try to load existing metrics from disk
        self.load_metrics()

        # Start persistence task
        self.last_persist_time = time.time()
        self.persistence_thread = None
        self.running = True

        if persist_interval > 0:
            self.persistence_thread = threading.Thread(
                target=self._persistence_task, daemon=True
            )
            self.persistence_thread.start()

    def initialize_metrics(self):
        """Initialize or reset metrics containers."""
        with self.lock:
            # API-specific counters
            self.request_counts: Dict[str, int] = defaultdict(int)
            self.response_counts: Dict[str, Dict[int, int]] = defaultdict(
                lambda: defaultdict(int)
            )
            self.error_counts: Dict[str, int] = defaultdict(int)
            self.rate_limit_hits: Dict[str, int] = defaultdict(int)
            self.queue_hits: Dict[str, int] = defaultdict(int)

            # Response time tracking (ms)
            self.response_times: Dict[str, List[float]] = defaultdict(list)
            self.avg_response_time: Dict[str, float] = defaultdict(float)
            self.min_response_time: Dict[str, float] = defaultdict(lambda: float("inf"))
            self.max_response_time: Dict[str, float] = defaultdict(float)

            # Key usage tracking
            self.key_usage: Dict[str, Dict[str, int]] = defaultdict(
                lambda: defaultdict(int)
            )

            # Request history (recent requests)
            self.request_history: Deque[Dict[str, Any]] = deque(
                maxlen=self.history_size
            )

            # Timestamp tracking
            self.start_time = time.time()
            self.last_request_time: Dict[str, float] = defaultdict(float)

    def record_request(self, api_name: str, key_id: str = "unknown"):
        """
        Record a request to an API.

        Args:
            api_name: Name of the API
            key_id: Identifier for the key/token used
        """
        with self.lock:
            current_time = time.time()
            self.request_counts[api_name] += 1
            self.key_usage[api_name][key_id] += 1
            self.last_request_time[api_name] = current_time

            # Add to request history
            self.request_history.append(
                {
                    "type": "request",
                    "api_name": api_name,
                    "key_id": key_id,
                    "timestamp": current_time,
                }
            )

    def record_response(self, api_name: str, status_code: int, elapsed_time: float):
        """
        Record a response from an API.

        Args:
            api_name: Name of the API
            status_code: HTTP status code
            elapsed_time: Time taken for the request in seconds
        """
        with self.lock:
            # Convert to milliseconds for easier readability
            elapsed_ms = elapsed_time * 1000

            # Update response counts by status code
            self.response_counts[api_name][status_code] += 1

            # Update error counts for non-2xx responses
            if status_code >= 400:
                self.error_counts[api_name] += 1

            # Update response time metrics
            self.response_times[api_name].append(elapsed_ms)
            if (
                len(self.response_times[api_name]) > 100
            ):  # Keep only recent measurements
                self.response_times[api_name] = self.response_times[api_name][-100:]

            # Update min/max/avg
            self.min_response_time[api_name] = min(
                self.min_response_time[api_name], elapsed_ms
            )
            self.max_response_time[api_name] = max(
                self.max_response_time[api_name], elapsed_ms
            )

            # Recalculate average
            if self.response_times[api_name]:
                self.avg_response_time[api_name] = sum(
                    self.response_times[api_name]
                ) / len(self.response_times[api_name])

            # Add to request history
            self.request_history.append(
                {
                    "type": "response",
                    "api_name": api_name,
                    "status_code": status_code,
                    "elapsed_ms": elapsed_ms,
                    "timestamp": time.time(),
                }
            )

    def record_rate_limit_hit(self, api_name: str):
        """
        Record a rate limit hit for an API.

        Args:
            api_name: Name of the API
        """
        with self.lock:
            self.rate_limit_hits[api_name] += 1

            # Add to request history
            self.request_history.append(
                {"type": "rate_limit", "api_name": api_name, "timestamp": time.time()}
            )

    def record_queue_hit(self, api_name: str):
        """
        Record a queue hit for an API.

        Args:
            api_name: Name of the API
        """
        with self.lock:
            self.queue_hits[api_name] += 1

            # Add to request history
            self.request_history.append(
                {"type": "queue", "api_name": api_name, "timestamp": time.time()}
            )

    def get_api_metrics(self, api_name: str) -> Dict[str, Any]:
        """
        Get metrics for a specific API.

        Args:
            api_name: Name of the API

        Returns:
            Dictionary with API metrics
        """
        with self.lock:
            return {
                "requests": self.request_counts[api_name],
                "responses": dict(self.response_counts[api_name]),
                "errors": self.error_counts[api_name],
                "rate_limit_hits": self.rate_limit_hits[api_name],
                "queue_hits": self.queue_hits[api_name],
                "avg_response_time_ms": self.avg_response_time[api_name],
                "min_response_time_ms": (
                    self.min_response_time[api_name]
                    if self.min_response_time[api_name] != float("inf")
                    else 0
                ),
                "max_response_time_ms": self.max_response_time[api_name],
                "key_usage": dict(self.key_usage[api_name]),
                "last_request_time": self.last_request_time[api_name],
            }

    def get_all_metrics(self) -> Dict[str, Any]:
        """
        Get metrics for all APIs.

        Returns:
            Dictionary with all metrics
        """
        with self.lock:
            api_names = set(self.request_counts.keys())

            # Add API names that might only have responses but no requests yet
            for api_name in self.response_counts:
                api_names.add(api_name)

            metrics = {
                "global": {
                    "total_requests": sum(self.request_counts.values()),
                    "total_errors": sum(self.error_counts.values()),
                    "total_rate_limit_hits": sum(self.rate_limit_hits.values()),
                    "total_queue_hits": sum(self.queue_hits.values()),
                    "uptime_seconds": time.time() - self.start_time,
                },
                "apis": {
                    api_name: self.get_api_metrics(api_name) for api_name in api_names
                },
            }

            return metrics

    def get_recent_history(self, count: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent request/response history.

        Args:
            count: Number of recent events to return

        Returns:
            List of recent events
        """
        with self.lock:
            return list(self.request_history)[-count:]

    def load_metrics(self):
        """Load metrics from disk if available."""
        metrics_file = os.path.join(self.metrics_path, "metrics.json")

        if not os.path.exists(metrics_file):
            self.logger.debug(f"No metrics file found at {metrics_file}")
            return

        try:
            with open(metrics_file, "r") as f:
                try:
                    saved_metrics = json.load(f)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON in metrics file: {str(e)}")
                    return

            with self.lock:
                # Load API-specific counters
                api_metrics = saved_metrics.get("apis", {})
                for api_name, metrics in api_metrics.items():
                    self.request_counts[api_name] = metrics.get("requests", 0)

                    # Load response counts by status code
                    for status_code_str, count in metrics.get("responses", {}).items():
                        try:
                            status_code = int(status_code_str)
                            self.response_counts[api_name][status_code] = count
                        except ValueError:
                            self.logger.warning(
                                f"Invalid status code: {status_code_str}"
                            )
                            continue

                    self.error_counts[api_name] = metrics.get("errors", 0)
                    self.rate_limit_hits[api_name] = metrics.get("rate_limit_hits", 0)
                    self.queue_hits[api_name] = metrics.get("queue_hits", 0)

                    # Load response time metrics
                    self.avg_response_time[api_name] = metrics.get(
                        "avg_response_time_ms", 0
                    )

                    min_time = metrics.get("min_response_time_ms")
                    if min_time is not None and min_time > 0:
                        self.min_response_time[api_name] = min_time

                    self.max_response_time[api_name] = metrics.get(
                        "max_response_time_ms", 0
                    )

                    # Load key usage data
                    for key_id, count in metrics.get("key_usage", {}).items():
                        self.key_usage[api_name][key_id] = count

                    # Load last request time
                    self.last_request_time[api_name] = metrics.get(
                        "last_request_time", 0
                    )

                # Restore start time to maintain accurate uptime
                saved_timestamp = saved_metrics.get("timestamp")
                if saved_timestamp and "global" in saved_metrics:
                    saved_uptime = saved_metrics["global"].get("uptime_seconds")
                    if saved_uptime is not None:
                        # Calculate original start time from previous data
                        calculated_start = float(saved_timestamp) - float(saved_uptime)
                        # Use the earlier of the two start times
                        self.start_time = min(self.start_time, calculated_start)

            self.logger.info(f"Successfully loaded metrics from {metrics_file}")

        except (OSError, IOError) as e:
            self.logger.error(f"Error reading metrics file: {str(e)}")
        except Exception as e:
            self.logger.error(
                f"Unexpected error loading metrics: {str(e)}", exc_info=True
            )

    def persist_metrics(self):
        """Save metrics to disk."""
        try:
            metrics_file = os.path.join(self.metrics_path, "metrics.json")
            tmp_file = metrics_file + ".tmp"

            # Get metrics data
            metrics = self.get_all_metrics()

            # Add timestamp
            metrics["timestamp"] = time.time()

            # Write to temp file first to prevent corruption
            with open(tmp_file, "w") as f:
                json.dump(metrics, f, indent=2)

            # Rename to final file
            os.replace(tmp_file, metrics_file)

            self.logger.debug(f"Metrics persisted to {metrics_file}")
            self.last_persist_time = time.time()

        except Exception as e:
            self.logger.error(f"Error persisting metrics: {str(e)}")

    def _persistence_task(self):
        """Background task for periodically persisting metrics."""
        while self.running:
            try:
                current_time = time.time()
                if current_time - self.last_persist_time >= self.persist_interval:
                    self.persist_metrics()
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Error in metrics persistence task: {str(e)}")
                time.sleep(5)  # Back off on error

    def stop(self):
        """Stop the metrics collector persistence thread."""
        self.running = False
        if self.persistence_thread:
            self.persistence_thread.join(timeout=2)

        # Save metrics one last time
        self.persist_metrics()

        # Remove from instances map
        with self._instances_lock:
            abs_path = os.path.abspath(self.metrics_path)
            if abs_path in self._instances:
                del self._instances[abs_path]

    def reset(self):
        """Reset all metrics."""
        with self.lock:
            self.initialize_metrics()
            # Save the reset metrics
            self.persist_metrics()
