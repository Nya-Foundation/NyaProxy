import pytest

from nya.common.exceptions import ConfigurationError
from nya.config.manager import ConfigManager


class FakeNachoConfig:
    def __init__(self, data):
        self.data = data

    def _get(self, path, default=None):
        current = self.data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def get(self, path, default=None):
        return self._get(path, default)

    def get_str(self, path, default=""):
        value = self._get(path, default)
        return default if value is None else str(value)

    def get_int(self, path, default=0):
        return int(self._get(path, default))

    def get_float(self, path, default=0.0):
        return float(self._get(path, default))

    def get_bool(self, path, default=False):
        return bool(self._get(path, default))

    def get_list(self, path, default=None):
        value = self._get(path, default if default is not None else [])
        if isinstance(value, str):
            return [part.strip() for part in value.split(",")]
        return value

    def get_dict(self, path, default=None):
        return self._get(path, default if default is not None else {})


def make_manager(data):
    manager = object.__new__(ConfigManager)
    manager.config = FakeNachoConfig(data)
    manager.server = None
    manager.config_path = "config.yaml"
    manager.schema_path = "schema.json"
    manager.remote_url = None
    manager.remote_api_key = None
    manager.remote_app_name = None
    manager.callback = None
    return manager


def sample_data():
    return {
        "server": {
            "debug_level": "DEBUG",
            "host": "127.0.0.1",
            "port": 9191,
            "dashboard": {"enabled": False},
            "retry": {"mode": "aggressive", "attempts": 3},
            "api_key": ["master", "secondary"],
            "logging": {
                "enabled": False,
                "level": "warning",
                "log_file": "nya.log",
            },
            "proxy": {"enabled": True, "address": "socks5://proxy"},
            "cors": {
                "allow_origins": "https://a.test, https://b.test",
                "allow_methods": ["GET"],
                "allow_headers": ["authorization"],
                "allow_credentials": True,
            },
            "timeouts": {"request_timeout_seconds": 45},
        },
        "default_settings": {
            "timeouts": {"request_timeout_seconds": 30},
            "key_variable": "keys",
            "key_concurrency": False,
            "randomness": 0.25,
            "headers": {"Authorization": "Bearer ${{keys}}"},
            "endpoint": "https://default.test",
            "load_balancing_strategy": "round_robin",
            "allowed_paths": {
                "enabled": True,
                "mode": "whitelist",
                "paths": ["/v1/*"],
            },
            "allowed_methods": ["GET", "POST"],
            "queue": {"max_size": 7, "max_workers": 2, "expiry_seconds": 4.5},
            "rate_limit": {
                "enabled": True,
                "endpoint_rate_limit": "10/m",
                "key_rate_limit": "1/s",
                "ip_rate_limit": "2/s",
                "user_rate_limit": "3/s",
                "rate_limit_paths": ["/v1/*"],
            },
            "retry": {
                "enabled": True,
                "mode": "default",
                "attempts": 4,
                "retry_after_seconds": 0.5,
                "retry_status_codes": [429, 500],
                "retry_request_methods": ["GET"],
            },
            "key_blocking": {
                "enabled": True,
                "status_codes": [401, 403],
                "duration_seconds": 60,
            },
            "request_body_substitution": {"enabled": False, "rules": []},
        },
        "apis": {
            "openai": {
                "name": "OpenAI",
                "endpoint": "https://api.openai.test",
                "aliases": ["oai"],
                "variables": {
                    "keys": ["key-a", None, "key-b"],
                    "regions": "us, eu",
                    "single": 123,
                },
                "request_body_substitution": {
                    "enabled": True,
                    "rules": [{"name": "drop", "operation": "remove", "path": "x"}],
                },
                "key_blocking": {"status_codes": [403, 429]},
            },
            "fallback": {"variables": {}},
        },
    }


def test_top_level_getters_return_configured_values():
    manager = make_manager(sample_data())

    assert manager.get_host() == "127.0.0.1"
    assert manager.get_port() == 9191
    assert manager.get_dashboard_enabled() is False
    assert manager.get_api_key() == ["master", "secondary"]
    assert manager.get_logging_config() == {
        "enabled": False,
        "level": "warning",
        "log_file": "nya.log",
    }
    assert manager.get_proxy_enabled() is True
    assert manager.get_proxy_address() == "socks5://proxy"
    assert manager.get_cors_allow_origins() == ["https://a.test", "https://b.test"]
    assert manager.get_cors_allow_methods() == ["GET"]
    assert manager.get_cors_allow_headers() == ["authorization"]
    assert manager.get_cors_allow_credentials() is True
    assert manager.get_default_timeout() == 45


def test_api_getters_fall_back_to_default_settings_and_api_overrides():
    manager = make_manager(sample_data())

    assert manager.get_api_default_timeout("openai") == 30
    assert manager.get_api_key_variable("openai") == "keys"
    assert manager.get_api_key_concurrency("openai") is False
    assert manager.get_api_random_delay("openai") == 0.25
    assert manager.get_api_custom_headers("openai") == {
        "Authorization": "Bearer ${{keys}}"
    }
    assert manager.get_api_endpoint("openai") == "https://api.openai.test"
    assert manager.get_api_load_balancing_strategy("openai") == "round_robin"
    assert manager.get_api_allowed_paths("openai") == ["/v1/*"]
    assert manager.get_api_allowed_paths_enabled("openai") is True
    assert manager.get_api_allowed_paths_mode("openai") == "whitelist"
    assert manager.get_api_allowed_methods("openai") == ["GET", "POST"]
    assert manager.get_api_queue_size("openai") == 7
    assert manager.get_api_max_workers("openai") == 2
    assert manager.get_api_queue_expiry("openai") == 4.5
    assert manager.get_api_rate_limit_enabled("openai") is True
    assert manager.get_api_endpoint_rate_limit("openai") == "10/m"
    assert manager.get_api_key_rate_limit("openai") == "1/s"
    assert manager.get_api_ip_rate_limit("openai") == "2/s"
    assert manager.get_api_user_rate_limit("openai") == "3/s"
    assert manager.get_api_retry_enabled("openai") is True
    assert manager.get_api_retry_attempts("openai") == 4
    assert manager.get_api_retry_after_seconds("openai") == 0.5
    assert manager.get_api_retry_status_codes("openai") == [429, 500]
    assert manager.get_api_retry_request_methods("openai") == ["GET"]
    assert manager.get_api_key_blocking_enabled("openai") is True
    assert manager.get_api_key_blocking_status_codes("openai") == [403, 429]
    assert manager.get_api_key_blocking_duration_seconds("openai") == 60
    assert manager.get_api_rate_limit_paths("openai") == ["/v1/*"]


def test_api_lookup_aliases_variables_and_disabled_substitutions():
    manager = make_manager(sample_data())

    assert manager.get_apis()["openai"]["name"] == "OpenAI"
    assert manager.get_api_config("missing") is None
    assert manager.get_api_aliases("openai") == ["oai"]
    assert manager.get_api_variable_values("openai", "keys") == ["key-a", "key-b"]
    assert manager.get_api_variable_values("openai", "regions") == ["us", "eu"]
    assert manager.get_api_variable_values("openai", "single") == ["123"]
    assert manager.get_api_variable_values("missing", "keys") == []
    assert manager.get_api_request_subst_rules("openai") == [
        {"name": "drop", "operation": "remove", "path": "x"}
    ]
    assert manager.get_api_request_subst_rules("fallback") == []


def test_get_apis_requires_at_least_one_api():
    manager = make_manager({"apis": {}})

    with pytest.raises(ConfigurationError):
        manager.get_apis()


def test_api_key_scalar_is_normalized_to_string():
    manager = make_manager({"server": {"api_key": 123}, "apis": {"x": {}}})

    assert manager.get_api_key() == "123"


def test_key_blocking_has_safe_builtin_defaults():
    manager = make_manager({"default_settings": {}, "apis": {"mock": {}}})

    assert manager.get_api_key_blocking_enabled("mock") is False
    assert manager.get_api_key_blocking_status_codes("mock") == [403]
    assert manager.get_api_key_blocking_duration_seconds("mock") == 300


def test_key_blocking_semantic_validation_rejects_invalid_error_policy():
    data = sample_data()
    data["default_settings"]["key_blocking"]["status_codes"] = [399, 600]
    data["apis"]["openai"]["key_blocking"]["duration_seconds"] = 0

    errors = ConfigManager._semantic_validation_errors(FakeNachoConfig(data))

    assert any(
        "default_settings.key_blocking.status_codes" in error for error in errors
    )
    assert any("apis.openai.key_blocking.duration_seconds" in error for error in errors)


def test_missing_config_path_fails_before_nacho_initialization(tmp_path):
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ConfigurationError):
        ConfigManager(config_path=str(missing))


def test_init_config_client_builds_local_storage_and_registers_callback(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, storage, schema, env_prefix, events):
            calls["client"] = (storage, schema, env_prefix, events)

        def on_change(self, topic, priority):
            calls["on_change"] = (topic, priority)
            return lambda callback: calls.setdefault("callback", callback)

        def validate(self):
            return []

    monkeypatch.setattr(
        "nya.config.manager.FileStorageBackend", lambda path: ("file", path)
    )
    monkeypatch.setattr("nya.config.manager.Nacho", FakeClient)

    callback = object()
    manager = object.__new__(ConfigManager)
    manager.config_path = "config.yaml"
    manager.schema_path = "schema.json"
    manager.remote_url = None
    manager.remote_api_key = None
    manager.remote_app_name = None
    manager.callback = callback

    client = manager.init_config_client()

    assert client is not None
    assert calls["client"] == (("file", "config.yaml"), "schema.json", "NYA", True)
    assert calls["on_change"] == ("@global", 10)
    assert calls["callback"] is callback


def test_init_config_client_raises_validation_errors(monkeypatch):
    class InvalidClient:
        def __init__(self, **kwargs):
            pass

        def validate(self):
            return ["bad endpoint"]

    monkeypatch.setattr("nya.config.manager.FileStorageBackend", lambda path: object())
    monkeypatch.setattr("nya.config.manager.Nacho", InvalidClient)

    manager = object.__new__(ConfigManager)
    manager.config_path = "config.yaml"
    manager.schema_path = None
    manager.remote_url = None
    manager.remote_api_key = None
    manager.remote_app_name = None
    manager.callback = None

    with pytest.raises(ConfigurationError) as exc:
        manager.init_config_client()

    assert exc.value.errors == ["bad endpoint"]


def test_remote_config_skips_local_orchestrator(monkeypatch):
    calls = {}

    class ValidClient:
        def __init__(self, storage, schema, env_prefix, events):
            calls["storage"] = storage

        def validate(self):
            return []

    def fake_remote(**kwargs):
        calls["remote"] = kwargs
        return ("remote", kwargs)

    monkeypatch.setattr("nya.config.manager.RemoteStorageBackend", fake_remote)
    monkeypatch.setattr("nya.config.manager.Nacho", ValidClient)

    manager = object.__new__(ConfigManager)
    manager.config_path = None
    manager.schema_path = None
    manager.remote_url = "https://config.test"
    manager.remote_api_key = "secret"
    manager.remote_app_name = None
    manager.callback = None

    assert manager.init_config_client() is not None
    assert calls["remote"]["app_name"] is None
    manager.config = object()
    assert manager.init_config_server() is None


def test_init_config_server_wraps_orchestrator_errors(monkeypatch):
    manager = object.__new__(ConfigManager)
    manager.remote_url = None
    manager.config = object()

    def explode(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("nya.config.manager.NachoOrchestrator", explode)

    with pytest.raises(ConfigurationError):
        manager.init_config_server()
