"""
Common test fixtures and utilities for NyaProxy tests.
"""

import asyncio
import os
import tempfile
from typing import Any, Dict

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nya_proxy.config_manager import ConfigManager
from nya_proxy.load_balancer import LoadBalancer
from nya_proxy.logger import setup_logger
from nya_proxy.metrics import MetricsCollector
from nya_proxy.proxy_handler import ProxyHandler
from nya_proxy.rate_limiter import RateLimiter
from nya_proxy.request_queue import RequestQueue


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
        config_content = {
            "nya_proxy": {
                "host": "0.0.0.0",
                "port": 8080,
                "api_key": "test_api_key",
                "logging": {
                    "enabled": True,
                    "level": "DEBUG",
                    "log_file": "test_log.log",
                },
                "proxy": {"enabled": False, "address": ""},
                "dashboard": {"enabled": True},
                "queue": {"enabled": True, "max_size": 100, "expiry_seconds": 60},
            },
            "default_settings": {
                "key_variable": "keys",
                "load_balancing_strategy": "round_robin",
                "rate_limit": {"endpoint_rate_limit": "10/s", "key_rate_limit": "5/s"},
                "retry": {"enabled": True, "attempts": 3, "retry_after_seconds": 1},
                "timeouts": {"request_timeout_seconds": 10},
                "error_handling": {
                    "report_api_errors": True,
                    "retry_status_codes": [429, 500, 502, 503, 504],
                },
            },
            "apis": {
                "test_api": {
                    "name": "Test API",
                    "endpoint": "https://test-api.example.com",
                    "key_variable": "keys",
                    "headers": {
                        "Authorization": "Bearer ${{keys}}",
                        "User-Agent": "${{agents}}",
                    },
                    "variables": {
                        "keys": ["test_key_1", "test_key_2"],
                        "agents": ["TestAgent/1.0", "TestAgent/2.0"],
                    },
                },
                "test_api_2": {
                    "name": "Test API 2",
                    "endpoint": "https://test-api2.example.com",
                    "key_variable": "keys",
                    "aliases": ["api2", "testapi2"],
                    "headers": {"Authorization": "Bearer ${{keys}}"},
                    "variables": {"keys": ["test2_key_1", "test2_key_2"]},
                    "load_balancing_strategy": "random",
                },
            },
        }

        yaml.dump(config_content, tmp)
        tmp.flush()
        yield tmp.name

    # Clean up
    os.unlink(tmp.name)


@pytest.fixture
def test_logger():
    """Create a test logger."""
    log_config = {
        "enabled": True,
        "level": "DEBUG",
        "log_file": None,  # Use console logging only for tests
    }
    return setup_logger(log_config, name="test_nya_proxy")


@pytest.fixture
def config_manager(temp_config_file):
    """Create a ConfigManager instance for testing."""
    return ConfigManager(temp_config_file)


@pytest.fixture
def metrics_collector(test_logger):
    """Create a MetricsCollector instance for testing."""
    return MetricsCollector(test_logger)


@pytest.fixture
def request_queue(test_logger):
    """Create a RequestQueue instance for testing."""
    return RequestQueue(max_size=100, expiry_seconds=60, logger=test_logger)


@pytest.fixture
def proxy_handler(config_manager, test_logger, request_queue, metrics_collector):
    """Create a ProxyHandler instance for testing."""
    handler = ProxyHandler(
        config_manager=config_manager,
        logger=test_logger,
        request_queue=request_queue,
        metrics_collector=metrics_collector,
    )

    # Return the handler and clean up after test
    yield handler

    # Clean up
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.run_until_complete(handler.close())
    else:
        asyncio.run(handler.close())


@pytest.fixture
def load_balancer_round_robin(test_logger):
    """Create a round-robin LoadBalancer instance for testing."""
    return LoadBalancer(["key1", "key2", "key3"], "round_robin", test_logger)


@pytest.fixture
def load_balancer_random(test_logger):
    """Create a random LoadBalancer instance for testing."""
    return LoadBalancer(["key1", "key2", "key3"], "random", test_logger)


@pytest.fixture
def load_balancer_weighted(test_logger):
    """Create a weighted LoadBalancer instance for testing."""
    return LoadBalancer(
        ["key1", "key2", "key3"], "weighted", test_logger, weights=[3, 1, 1]
    )


@pytest.fixture
def rate_limiter():
    """Create a RateLimiter instance for testing."""
    return RateLimiter("10/s")


@pytest.fixture
def mock_fastapi_app():
    """Create a FastAPI app for testing."""
    app = FastAPI()

    @app.get("/test")
    def get_test():
        return {"status": "ok"}

    @app.get("/rate-limited")
    def get_rate_limited():
        return {"status": "rate_limited"}, 429

    @app.post("/test")
    def post_test(request: Dict[str, Any]):
        return {"status": "ok", "received": request}

    return app


@pytest.fixture
def test_client(mock_fastapi_app):
    """Create a TestClient for the mock FastAPI app."""
    return TestClient(mock_fastapi_app)


# Helper functions for tests
class MockResponse:
    """Mock HTTP response for testing."""

    def __init__(self, status_code=200, content=None, headers=None):
        self.status_code = status_code
        self.content = content or b'{"status": "ok"}'
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        import json

        return json.loads(self.content)


# Custom pytest marks
def pytest_configure(config):
    """Configure custom pytest marks."""
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "unit: mark test as unit test")
