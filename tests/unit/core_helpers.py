"""Shared fakes and helpers for the nya/core unit test modules."""

from httpx import Headers
from starlette.datastructures import URL

from nya.common.models import ProxyRequest


class CoreConfig:
    def __init__(self):
        self.apis = {
            "mock": {
                "endpoint": "https://upstream.test",
                "aliases": ["alias"],
            }
        }
        self.api_keys = ["master", "secondary"]
        self.keys = ["key-a", "key-b"]
        self.allowed_enabled = True
        self.allowed_mode = "whitelist"
        self.allowed_paths = ["/v1/*"]
        self.allowed_methods = ["GET", "POST"]
        self.rate_limit_enabled = True
        self.rate_limit_paths = ["*"]
        self.retry_enabled = False
        self.retry_methods = ["GET"]
        self.retry_status_codes = [429]
        self.retry_after = 0
        self.retry_attempts = 2
        self.key_blocking_enabled = False
        self.key_blocking_status_codes = [403]
        self.key_blocking_duration = 300
        self.key_concurrency = True
        self.random_delay = 0
        self.body_substitution_enabled = False
        self.body_rules = []
        self.headers = {"Authorization": "Bearer ${{api_key}}"}
        self.proxy_enabled = False
        self.queue_size = 10
        self.queue_expiry = 2
        self.max_workers = 1

    def get_apis(self):
        return self.apis

    def get_api_aliases(self, api_name):
        return self.apis[api_name].get("aliases", [])

    def get_api_endpoint(self, api_name):
        return self.apis[api_name]["endpoint"]

    def get_api_allowed_paths_enabled(self, api_name):
        return self.allowed_enabled

    def get_api_allowed_methods(self, api_name):
        return self.allowed_methods

    def get_api_allowed_paths(self, api_name):
        return self.allowed_paths

    def get_api_allowed_paths_mode(self, api_name):
        return self.allowed_mode

    def get_api_rate_limit_enabled(self, api_name):
        return self.rate_limit_enabled

    def get_api_rate_limit_paths(self, api_name):
        return self.rate_limit_paths

    def get_api_key(self):
        return self.api_keys

    def get_api_key_variable(self, api_name):
        return "api_key"

    def get_api_custom_headers(self, api_name):
        return self.headers

    def get_api_variable_values(self, api_name, variable_name):
        if variable_name == "api_key":
            return self.keys
        if variable_name == "region":
            return ["us"]
        return []

    def get_api_request_subst_rules(self, api_name):
        return self.body_rules if self.body_substitution_enabled else []

    def get_api_load_balancing_strategy(self, api_name):
        return "round_robin"

    def get_api_key_weights(self, api_name):
        return []

    def get_api_key_rate_limit(self, api_name):
        return "1/s"

    def get_api_endpoint_rate_limit(self, api_name):
        return "0"

    def get_api_ip_rate_limit(self, api_name):
        return "0"

    def get_api_user_rate_limit(self, api_name):
        return "0"

    def get_api_key_concurrency(self, api_name):
        return self.key_concurrency

    def get_api_queue_size(self, api_name):
        return self.queue_size

    def get_api_max_workers(self, api_name):
        return self.max_workers

    def get_api_queue_expiry(self, api_name):
        return self.queue_expiry

    def get_api_retry_enabled(self, api_name):
        return self.retry_enabled

    def get_api_retry_request_methods(self, api_name):
        return self.retry_methods

    def get_api_retry_status_codes(self, api_name):
        return self.retry_status_codes

    def get_api_retry_after_seconds(self, api_name):
        return self.retry_after

    def get_api_retry_attempts(self, api_name):
        return self.retry_attempts

    def get_api_key_blocking_enabled(self, api_name):
        return self.key_blocking_enabled

    def get_api_key_blocking_status_codes(self, api_name):
        return self.key_blocking_status_codes

    def get_api_key_blocking_duration_seconds(self, api_name):
        return self.key_blocking_duration

    def get_api_default_timeout(self, api_name=None):
        return 5

    def get_api_random_delay(self, api_name):
        return self.random_delay

    def get_default_timeout(self):
        return 10

    def get_proxy_enabled(self):
        return self.proxy_enabled

    def get_proxy_address(self):
        return "http://proxy.test"


def make_request(
    path="/api/mock/v1/chat",
    method="GET",
    headers=None,
    content=b"{}",
):
    return ProxyRequest(
        method=method,
        _url=URL(f"http://proxy.test{path}"),
        headers=Headers(headers or {"authorization": "Bearer user-key"}),
        content=content,
        ip="198.51.100.1",
    )


class FakeStreamContext:
    def __init__(self, response):
        self.response = response
        self.closed = False

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True


class FakeHttpxResponse:
    def __init__(self, chunks, status_code=200, headers=None, fail=False):
        self.status_code = status_code
        self.headers = Headers(headers or {"content-type": "text/plain"})
        self._chunks = chunks
        self._stream_ctx = FakeStreamContext(self)
        self.fail = fail

    async def aiter_raw(self):
        if self.fail:
            raise RuntimeError("stream failed")
        for chunk in self._chunks:
            yield chunk
