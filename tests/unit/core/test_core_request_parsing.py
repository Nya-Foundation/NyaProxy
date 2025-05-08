import pytest

from nya.common.constants import API_PATH_PREFIX
from nya.common.models import NyaRequest
from nya.core.factory import ServiceFactory
from nya.core.proxy import NyaProxyCore


class MockConfig:
    def __init__(self):
        self._apis = {
            "default": {
                "endpoint": "http://localhost:8080",
                "aliases": [],
                "timeout": 30,
            },
            "openai": {"endpoint": "https://api.openai.com", "aliases": ["/oai", "/o"]},
            "gemini": {
                "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
                "aliases": ["/gemini", "/g"],
            },
            "test": {"endpoint": "http://localhost:8000", "aliases": []},
        }

    def get_apis(self):
        return self._apis

    def get_api_endpoint(self, api):
        return self._apis.get(api, {}).get("endpoint")

    def get_api_aliases(self, api):
        return self._apis.get(api, {}).get("aliases", [])

    def get_api_default_timeout(self):
        return self._apis.get("default", {}).get("timeout", 30)

    def get_default_timeout(self):
        return self.get_api_default_timeout()

    # Mock other required methods
    def get_proxy_enabled(self):
        return False

    def get_proxy_address(self):
        return ""

    def get_queue_enabled(self):
        return False

    def get_debug_level(self):
        return "INFO"


@pytest.fixture
def mock_config():
    return MockConfig()


@pytest.fixture
def mock_factory(mock_config, mocker):
    factory = mocker.Mock(spec=ServiceFactory)
    factory.config = mock_config
    factory.create_metrics_collector.return_value = mocker.Mock()
    factory.create_load_balancers.return_value = {}
    factory.create_rate_limiters.return_value = {}
    factory.create_key_manager.return_value = mocker.Mock()
    factory.create_request_queue.return_value = None
    factory.create_request_executor.return_value = mocker.Mock()
    factory.create_response_processor.return_value = mocker.Mock()
    factory.get_component.return_value = {}
    return factory


@pytest.fixture
def core(mock_config, mock_factory, mocker):
    core = NyaProxyCore(config=mock_config, factory=mock_factory)
    core.logger = mocker.Mock()
    return core


@pytest.fixture
def make_request(mocker):
    def _make(path):
        req = mocker.Mock(spec=NyaRequest)
        req._url = mocker.Mock()
        req._url.path = path
        req.headers = {"Host": "localhost:8080"}
        return req

    return _make


class TestRequestParsing:
    def test_direct_api_match(self, core, make_request):
        req = make_request("/api/openai/v1/chat/completions")
        api, trail = core.request_handler.parse_request(req)
        assert api == "openai"
        assert trail == "/v1/chat/completions"

    def test_invalid_path(self, core, make_request):
        req = make_request("/notapi/openai")
        api, trail = core.request_handler.parse_request(req)
        assert api is None
        assert trail is None

    def test_empty_path(self, core, make_request):
        req = make_request("")
        api, trail = core.request_handler.parse_request(req)
        assert api is None
        assert trail is None

    def test_prefix_only(self, core, make_request):
        req = make_request("/api/")
        api, trail = core.request_handler.parse_request(req)
        assert api is None
        assert trail is None

    def test_trailing_slash(self, core, make_request):
        req = make_request("/api/test/")
        api, trail = core.request_handler.parse_request(req)
        assert api == "test"
        assert trail == "/"

    def test_path_with_query_parameters(self, core, make_request):
        req = make_request("/api/test/v1/endpoint?param1=value1&param2=value2")
        api, trail = core.request_handler.parse_request(req)
        assert api == "test"
        assert trail == "/v1/endpoint?param1=value1&param2=value2"
