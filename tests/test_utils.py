"""
Common test utilities and fixtures for NyaProxy tests.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nya_proxy.load_balancer import LoadBalancer
from nya_proxy.metrics import MetricsCollector
from nya_proxy.rate_limiter import RateLimiter
from nya_proxy.request_queue import RequestQueue


class AsyncTestProcessor:
    """Helper class for async processor tests."""

    def __init__(self, delay=0.01, fail_on_ids=None):
        """
        Initialize processor with configurable delay and failure conditions.

        Args:
            delay: Time to sleep during processing (simulates work)
            fail_on_ids: List of request IDs that should raise exceptions
        """
        self.delay = delay
        self.fail_on_ids = fail_on_ids or []
        self.processed_items = []
        self.mock = AsyncMock(side_effect=self._process)

    async def _process(self, api_name, request_data):
        """Process a request with simulated delay and optional failures."""
        await asyncio.sleep(self.delay)

        self.processed_items.append((api_name, request_data))

        # Simulate failures for specific IDs
        if "id" in request_data and request_data["id"] in self.fail_on_ids:
            raise Exception(f"Simulated failure for {request_data['id']}")

        return f"processed_{api_name}_{request_data.get('id', 'unknown')}"

    def get_processor_mock(self):
        """Get the mock processor function."""
        return self.mock


# Helper function for running queue processor tests
async def run_queue_processor(queue, duration=0.2):
    """Run the queue processor for a specified duration."""
    # Start the queue processor task
    process_task = asyncio.create_task(queue.process_queue_task())

    # Let it run for the specified duration
    await asyncio.sleep(duration)

    # Cancel the task
    process_task.cancel()
    try:
        await process_task
    except asyncio.CancelledError:
        pass

    # Return metrics
    return queue.get_metrics()


# Helper function for testing distributions
def assert_distribution(items, expected_distribution, tolerance=0.05):
    """
    Assert that the distribution of items matches the expected distribution.

    Args:
        items: List of items to check distribution for
        expected_distribution: Dict mapping items to expected frequency (0-1)
        tolerance: Acceptable deviation from expected values
    """
    # Count occurrences
    counts = {}
    for item in items:
        if item not in counts:
            counts[item] = 0
        counts[item] += 1

    # Convert to frequencies
    total = len(items)
    actual_distribution = {k: v / total for k, v in counts.items()}

    # Check each item is within tolerance
    for item, expected in expected_distribution.items():
        actual = actual_distribution.get(item, 0)
        assert (
            abs(actual - expected) <= tolerance
        ), f"Distribution for {item}: expected {expected}, got {actual}"


# Basic fixtures
@pytest.fixture
def test_logger():
    """Create a test logger with mocked methods."""
    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.critical = MagicMock()
    return logger


@pytest.fixture
def mock_time():
    """Mock the time.time function for deterministic testing."""
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000  # Default time
        yield mock_time


# Rate limiter fixtures
@pytest.fixture
def rate_limiter(test_logger):
    """Create a standard rate limiter for testing."""
    return RateLimiter("10/s", logger=test_logger)


@pytest.fixture
def rate_limiters():
    """Create various rate limiters for different test scenarios."""
    return {
        "standard": RateLimiter("10/s"),
        "disabled": RateLimiter(None),
        "unlimited": RateLimiter("1000000/s"),
        "fractional": RateLimiter("0.5/s"),
    }


@pytest.fixture
def burst_rate_limiter():
    """Create a rate limiter with burst capacity."""
    limiter = RateLimiter("10/m")
    original_tokens = limiter.tokens
    # Set up burst capacity
    limiter.tokens = 15  # 10 standard + 5 burst
    return limiter, original_tokens


# Metrics collector fixtures
@pytest.fixture
def metrics_collector(test_logger):
    """Create a basic metrics collector for testing."""
    return MetricsCollector(test_logger)


@pytest.fixture
def metrics_collector_with_data(test_logger):
    """Create a metrics collector pre-populated with test data."""
    collector = MetricsCollector(test_logger)

    # API 1: Fast with good success rate (80%)
    for _ in range(80):
        collector.record_response("api1", 200, 0.1)
    for _ in range(15):
        collector.record_response("api1", 429, 0.05)
    for _ in range(5):
        collector.record_response("api1", 500, 0.5)

    # Record some key usage
    collector.record_key_usage("api1", "key1")
    collector.record_key_usage("api1", "key1")
    collector.record_key_usage("api1", "key2")
    collector.record_key_usage("api1", "key3")

    # API 2: Medium speed with poor success rate (50%)
    for _ in range(50):
        collector.record_response("api2", 200, 0.5)
    for _ in range(50):
        collector.record_response("api2", 500, 0.8)

    # Record some key usage
    collector.record_key_usage("api2", "key1")
    collector.record_key_usage("api2", "key2")
    collector.record_key_usage("api2", "key2")
    collector.record_key_usage("api2", "key2")

    # API 3: Slow with excellent success rate (90%)
    for _ in range(90):
        collector.record_response("api3", 200, 2.0)
    for _ in range(10):
        collector.record_response("api3", 400, 1.8)

    # Record some key usage
    collector.record_key_usage("api3", "key3")
    collector.record_key_usage("api3", "key3")
    collector.record_key_usage("api3", "key3")
    collector.record_key_usage("api3", "key3")

    return collector


@pytest.fixture
def time_series_metrics_collector(test_logger):
    """Create a metrics collector with time series data."""
    collector = MetricsCollector(test_logger)

    with patch("time.time") as mock_time:
        # Hour 1 - low traffic
        mock_time.return_value = 3600
        for _ in range(10):
            collector.record_response("api1", 200, 0.1)

        # Hour 2 - medium traffic with rate limiting
        mock_time.return_value = 7200
        for _ in range(15):
            collector.record_response("api1", 200, 0.2)
        for _ in range(5):
            collector.record_response("api1", 429, 0.05)

        # Hour 3 - more traffic with errors
        mock_time.return_value = 10800
        for _ in range(15):
            collector.record_response("api1", 200, 0.3)
        for _ in range(5):
            collector.record_response("api1", 500, 0.5)

        # Hour 4 - high traffic with more rate limiting and errors
        mock_time.return_value = 14400
        for _ in range(30):
            collector.record_response("api1", 200, 0.4)
        for _ in range(10):
            collector.record_response("api1", 429, 0.05)
        for _ in range(5):
            collector.record_response("api1", 500, 0.6)

    return collector


@pytest.fixture
def adaptive_rate_limit_metrics(test_logger):
    """Create metrics suitable for testing adaptive rate limiting."""
    collector = MetricsCollector(test_logger)

    with patch("time.time") as mock_time:
        # Period 1
        mock_time.return_value = 0
        for _ in range(100):
            collector.record_response("api1", 200, 0.1)

        # Period 2 - introduce rate limiting
        mock_time.return_value = 600  # 10 minutes later
        for _ in range(90):
            collector.record_response("api1", 200, 0.2)
        for _ in range(10):
            collector.record_response("api1", 429, 0.01)
            collector.record_rate_limit_hit("api1")

        # Period 3 - more rate limiting
        mock_time.return_value = 1200  # 20 minutes later
        for _ in range(80):
            collector.record_response("api1", 200, 0.3)
        for _ in range(20):
            collector.record_response("api1", 429, 0.01)
            collector.record_rate_limit_hit("api1")

        # Continue pattern of increasing rate limiting
        for period in range(4, 7):
            mock_time.return_value = period * 600
            success_rate = 100 - period * 10
            rate_limit_hits = period * 10

            for _ in range(success_rate):
                collector.record_response("api1", 200, 0.2)
            for _ in range(rate_limit_hits):
                collector.record_response("api1", 429, 0.01)
                collector.record_rate_limit_hit("api1")

    return collector


# LoadBalancer fixtures
@pytest.fixture
def load_balancer_fixtures(test_logger):
    """Create various load balancers for different test scenarios."""
    return {
        "round_robin": LoadBalancer(
            ["key1", "key2", "key3"], "round_robin", test_logger
        ),
        "random": LoadBalancer(["key1", "key2", "key3"], "random", test_logger),
        "weighted": LoadBalancer(
            ["key1", "key2", "key3"], "weighted", test_logger, weights=[5, 3, 2]
        ),
    }


@pytest.fixture
def load_balancer_round_robin(test_logger):
    """Create a round-robin load balancer for testing."""
    return LoadBalancer(["key1", "key2", "key3"], "round_robin", test_logger)


@pytest.fixture
def load_balancer_random(test_logger):
    """Create a random load balancer for testing."""
    return LoadBalancer(["key1", "key2", "key3"], "random", test_logger)


@pytest.fixture
def load_balancer_weighted(test_logger):
    """Create a weighted load balancer for testing."""
    return LoadBalancer(
        ["key1", "key2", "key3"], "weighted", test_logger, weights=[5, 3, 2]
    )


@pytest.fixture
def load_balancer_with_response_times(test_logger):
    """Create a load balancer with pre-recorded response times."""
    lb = LoadBalancer(["key1", "key2", "key3"], "fastest", test_logger)

    # Set up response times
    lb.response_times["key1"] = [0.5, 0.5, 0.5, 0.5, 0.5]  # avg 0.5
    lb.response_times["key2"] = [0.2, 0.2, 0.2, 0.2, 0.2]  # avg 0.2
    lb.response_times["key3"] = [0.8, 0.8, 0.8, 0.8, 0.8]  # avg 0.8

    # Force metrics update
    lb.update_metrics()

    return lb


@pytest.fixture
def load_balancer_with_success_rates(test_logger):
    """Create a load balancer with pre-recorded success rates."""
    lb = LoadBalancer(["key1", "key2", "key3"], "adaptive", test_logger)

    # Set success rates
    lb.success_rates["key1"] = 0.5  # 50% success
    lb.success_rates["key2"] = 0.9  # 90% success
    lb.success_rates["key3"] = 0.7  # 70% success

    # Force metrics update
    lb.update_metrics()

    return lb


@pytest.fixture
def load_balancer_with_connection_counts(test_logger):
    """Create a load balancer with pre-recorded connection counts."""
    lb = LoadBalancer(["key1", "key2", "key3"], "least_connections", test_logger)

    # Set active connections
    lb.active_connections["key1"] = 5
    lb.active_connections["key2"] = 2
    lb.active_connections["key3"] = 8

    return lb


@pytest.fixture
def load_balancer_with_usage_counts(test_logger):
    """Create a load balancer with pre-recorded usage counts."""
    lb = LoadBalancer(["key1", "key2", "key3"], "least_used", test_logger)

    # Set usage counts
    lb.usage_counts["key1"] = 50
    lb.usage_counts["key2"] = 20
    lb.usage_counts["key3"] = 30

    return lb


# Request Queue fixtures
@pytest.fixture
def empty_request_queue(test_logger):
    """Create an empty request queue for testing."""
    return RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)


@pytest.fixture
def populated_request_queue(test_logger):
    """Create a request queue populated with test data."""
    queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

    # Add some test requests
    queue.enqueue_request("api1", {"id": 1, "data": "test1"}, 60)
    queue.enqueue_request("api1", {"id": 2, "data": "test2"}, 30)
    queue.enqueue_request("api2", {"id": 3, "data": "test3"}, 90)

    return queue


@pytest.fixture
def request_queue_with_processor(test_logger, request_processing_delay=0.02):
    """Create a request queue with a test processor."""
    queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

    # Create and register a processor
    processor = AsyncTestProcessor(delay=request_processing_delay)
    queue.register_processor(processor.get_processor_mock())

    return queue, processor


@pytest.fixture
def request_queue_with_failing_items(test_logger):
    """Create a request queue with some items that will fail processing."""
    queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

    # Create processor that fails on specific IDs
    processor = AsyncTestProcessor(fail_on_ids=[2, 4])
    queue.register_processor(processor.get_processor_mock())

    # Add mix of succeeding and failing items
    queue.enqueue_request("api1", {"id": 1}, 60)  # Will succeed
    queue.enqueue_request("api1", {"id": 2}, 60)  # Will fail
    queue.enqueue_request("api1", {"id": 3}, 60)  # Will succeed
    queue.enqueue_request("api1", {"id": 4}, 60)  # Will fail
    queue.enqueue_request("api1", {"id": 5}, 60)  # Will succeed

    return queue, processor


@pytest.fixture
def request_queue_with_expiry_mix(test_logger):
    """Create a request queue with mixed expiry times."""
    queue = RequestQueue(max_size=10, expiry_seconds=60, logger=test_logger)

    with patch("time.time") as mock_time:
        mock_time.return_value = 1000

        # Add items with different expiry times
        queue.enqueue_request("api1", {"id": 1}, 60)  # Expires at 1060
        queue.enqueue_request("api1", {"id": 2}, 20)  # Expires at 1020
        queue.enqueue_request("api1", {"id": 3}, 90)  # Expires at 1090
        queue.enqueue_request("api2", {"id": 4}, 100)  # Expires at 1100
        queue.enqueue_request("api3", {"id": 5}, 10)  # Expires at 1010 (urgent)

    return queue
