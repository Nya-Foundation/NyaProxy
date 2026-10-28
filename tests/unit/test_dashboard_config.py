"""
Tests for the dashboard config write-API (``nya.dashboard.routes.config``).

The routes mutate the live config through the wired-in config manager
(schema-validated ``set`` + ``save`` with rollback on save failure), so
they are registered only with ``enable_control=True`` and answer 503
when no config manager is attached.  The config client is faked
in-memory: no file-backed Nacho, no writes to ``nya/config.yaml``.
"""

from types import SimpleNamespace

from nacho import ValidationError
from starlette.testclient import TestClient

from nya.dashboard.api import DashboardAPI
from nya.dashboard.routes.config import _mask_key

# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeConfig:
    """In-memory stand-in for the Nacho client the config routes use."""

    def __init__(self, data=None):
        self.data = data if data is not None else {}
        self.set_error = None  # raised by set() when set
        self.save_error = None  # raised by save() when set
        self.save_calls = 0

    def get(self, path, default=None):
        current = self.data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def get_str(self, path, default=""):
        value = self.get(path, default)
        return default if value is None else str(value)

    def get_dict(self, path, default=None):
        value = self.get(path)
        if isinstance(value, dict):
            return value
        return {} if default is None else default

    def set(self, path, value):
        if self.set_error is not None:
            raise self.set_error
        parts = path.split(".")
        current = self.data
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value

    def delete(self, path):
        parts = path.split(".")
        current = self.data
        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current:
                return
            current = current[part]
        if isinstance(current, dict):
            current.pop(parts[-1], None)

    def save(self):
        self.save_calls += 1
        if self.save_error is not None:
            raise self.save_error


class FakeConfigManager:
    """Minimal ConfigManager stand-in exposing only what routes read."""

    def __init__(self, config):
        self.config = config


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def make_client(config=None, enable_control=True):
    """TestClient over DashboardAPI, optionally wired to a fake config."""
    dashboard = DashboardAPI(enable_control=enable_control)
    if config is not None:
        dashboard.set_config_manager(FakeConfigManager(config))
    return TestClient(dashboard.app)


def config_paths(enable_control):
    """/api/config/* paths present in the app's OpenAPI schema."""
    paths = DashboardAPI(enable_control=enable_control).app.openapi()["paths"]
    return {path for path in paths if path.startswith("/api/config/")}


def api_payload(**overrides):
    """A valid AddApiRequest body; override fields per test."""
    payload = {
        "name": "My API",
        "endpoint": "https://api.test/v1",
        "keys": ["k1", "k2"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Registration under enable_control
# --------------------------------------------------------------------------


def test_config_routes_absent_when_control_disabled():
    assert config_paths(enable_control=False) == set()


def test_config_routes_present_when_control_enabled():
    assert config_paths(enable_control=True) == {
        "/api/config/apis",
        "/api/config/apis/{key}",
        "/api/config/apis/{key}/keys",
        "/api/config/clients",
        "/api/config/clients/{index}",
    }


# --------------------------------------------------------------------------
# GET /api/config/apis
# --------------------------------------------------------------------------


def test_list_apis_returns_empty_list_when_none_configured():
    resp = make_client(FakeConfig()).get("/api/config/apis")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_apis_returns_503_without_config_manager():
    assert make_client().get("/api/config/apis").status_code == 503


def test_list_apis_reports_key_count_for_default_key_variable():
    config = FakeConfig(
        {
            "apis": {
                "openai": {
                    "name": "OpenAI",
                    "endpoint": "https://api.openai.test",
                    "variables": {"keys": ["k1", "k2", "k3"]},
                }
            }
        }
    )

    resp = make_client(config).get("/api/config/apis")

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "key": "openai",
            "name": "OpenAI",
            "endpoint": "https://api.openai.test",
            "key_count": 3,
            "key_masks": ["**", "**", "**"],
            "has_custom_headers": False,
            "is_default_auth": False,
            "aliases": [],
        }
    ]


def test_list_apis_counts_keys_via_custom_key_variable():
    config = FakeConfig(
        {
            "default_settings": {"key_variable": "tokens"},
            "apis": {
                "custom": {
                    "name": "Custom",
                    "endpoint": "https://custom.test",
                    "variables": {"tokens": ["t1", "t2"], "keys": ["only-one"]},
                },
                "legacy": {
                    "name": "Legacy",
                    "endpoint": "https://legacy.test",
                    "variables": {"keys": ["x", "y"]},
                },
            },
        }
    )

    resp = make_client(config).get("/api/config/apis")

    counts = {item["key"]: item["key_count"] for item in resp.json()}
    # key_count must follow default_settings.key_variable ("tokens"):
    # "custom" counts its tokens (2), "legacy" sees no tokens (0).
    assert counts == {"custom": 2, "legacy": 0}


def test_list_apis_masks_keys_and_never_returns_full_keys():
    full_key = "sk-supersecret-token-1234567890"
    config = FakeConfig(
        {
            "apis": {
                "openai": {
                    "name": "OpenAI",
                    "endpoint": "https://api.openai.test",
                    "headers": {"Authorization": "Bearer ${{keys}}"},
                    "aliases": ["gpt4", "chat"],
                    "variables": {"keys": [full_key, "short1"]},
                }
            }
        }
    )

    resp = make_client(config).get("/api/config/apis")

    assert resp.status_code == 200
    item = resp.json()[0]
    # Long key: first/last 4 chars only; short key (<=8): full mask.
    assert item["key_masks"] == ["sk-s...7890", "******"]
    assert item["key_count"] == 2
    assert item["has_custom_headers"] is True
    assert item["is_default_auth"] is True
    assert item["aliases"] == ["gpt4", "chat"]
    # The full key must never appear anywhere in the response body.
    assert full_key not in resp.text


def test_list_apis_flags_custom_headers_and_invalid_aliases():
    config = FakeConfig(
        {
            "apis": {
                "custom": {
                    "name": "Custom",
                    "endpoint": "https://custom.test",
                    "headers": {"x-api-key": "${{keys}}"},
                    "aliases": ["one", 2],
                },
                "bare": {
                    "name": "Bare",
                    "endpoint": "https://bare.test",
                    "aliases": "not-a-list",
                },
            }
        }
    )

    resp = make_client(config).get("/api/config/apis")

    items = {item["key"]: item for item in resp.json()}
    assert items["custom"]["has_custom_headers"] is True
    assert items["custom"]["is_default_auth"] is False
    # aliases must be a list of strings, otherwise [].
    assert items["custom"]["aliases"] == []
    assert items["bare"]["has_custom_headers"] is False
    assert items["bare"]["is_default_auth"] is False
    assert items["bare"]["aliases"] == []


def test_mask_key_short_key_fully_starred_long_keeps_edges():
    assert _mask_key("") == ""
    assert _mask_key("12345678") == "********"
    assert _mask_key("abcdefghi") == "abcd...fghi"


# --------------------------------------------------------------------------
# POST /api/config/apis
# --------------------------------------------------------------------------


def test_add_api_returns_503_without_config_manager():
    resp = make_client().post("/api/config/apis", json=api_payload())

    assert resp.status_code == 503


def test_add_api_success_stores_slugified_entry():
    config = FakeConfig()

    resp = make_client(config).post("/api/config/apis", json=api_payload())

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "key": "my-api"}
    assert config.get("apis.my-api") == {
        "name": "My API",
        "endpoint": "https://api.test/v1",
        "headers": {"Authorization": "Bearer ${{keys}}"},
        "variables": {"keys": ["k1", "k2"]},
    }
    assert config.save_calls == 1


def test_add_api_uses_custom_key_variable_in_header_and_variables():
    config = FakeConfig({"default_settings": {"key_variable": "tokens"}})

    resp = make_client(config).post("/api/config/apis", json=api_payload())

    assert resp.status_code == 200
    entry = config.get("apis.my-api")
    assert entry["headers"] == {"Authorization": "Bearer ${{tokens}}"}
    assert entry["variables"] == {"tokens": ["k1", "k2"]}
    assert "keys" not in entry["variables"]


def test_add_api_slug_falls_back_to_timestamp_for_non_latin_name(monkeypatch):
    monkeypatch.setattr(
        "nya.dashboard.routes.config.time",
        SimpleNamespace(time=lambda: 1700000000.0),
    )
    config = FakeConfig()

    resp = make_client(config).post(
        "/api/config/apis",
        json=api_payload(name="Кофе"),
    )

    assert resp.status_code == 200
    # No latin slug can be derived, so the key is api-<ms timestamp>.
    assert resp.json() == {"status": "ok", "key": "api-1700000000000"}
    assert "api-1700000000000" in config.get("apis", {})


def test_add_api_duplicate_key_returns_409():
    config = FakeConfig(
        {"apis": {"my-api": {"name": "My API", "endpoint": "https://old.test"}}}
    )

    resp = make_client(config).post("/api/config/apis", json=api_payload())

    assert resp.status_code == 409
    assert config.get("apis.my-api.endpoint") == "https://old.test"
    assert config.save_calls == 0


def test_add_api_rejects_invalid_endpoint_before_touching_config():
    config = FakeConfig()

    resp = make_client(config).post(
        "/api/config/apis",
        json=api_payload(endpoint="ftp://bad.test"),
    )

    # Pydantic rejects the body before the route runs: config untouched.
    assert resp.status_code == 422
    assert "apis" not in config.data
    assert config.save_calls == 0


def test_add_api_config_set_validation_error_returns_422():
    config = FakeConfig()
    config.set_error = ValidationError(["apis.my-api: rejected by schema"])

    resp = make_client(config).post("/api/config/apis", json=api_payload())

    assert resp.status_code == 422
    assert "my-api" not in config.data.get("apis", {})
    assert config.save_calls == 0


def test_add_api_save_failure_returns_500_and_rolls_back():
    config = FakeConfig()
    config.save_error = RuntimeError("disk full")

    resp = make_client(config).post("/api/config/apis", json=api_payload())

    assert resp.status_code == 500
    # The failed save must roll the write back: no partial entry remains.
    assert "my-api" not in config.data.get("apis", {})
    assert config.save_calls == 1


# --------------------------------------------------------------------------
# POST /api/config/apis — custom headers
# --------------------------------------------------------------------------


def test_add_api_without_headers_keeps_default_bearer():
    config = FakeConfig()

    resp = make_client(config).post("/api/config/apis", json=api_payload())

    assert resp.status_code == 200
    assert config.get("apis.my-api.headers") == {"Authorization": "Bearer ${{keys}}"}


def test_add_api_with_empty_headers_dict_keeps_default_bearer():
    config = FakeConfig()

    resp = make_client(config).post("/api/config/apis", json=api_payload(headers={}))

    assert resp.status_code == 200
    assert config.get("apis.my-api.headers") == {"Authorization": "Bearer ${{keys}}"}


def test_add_api_custom_headers_replace_default_authorization():
    config = FakeConfig()
    headers = {"x-api-key": "${{keys}}", "anthropic-version": "2023-06-01"}

    resp = make_client(config).post(
        "/api/config/apis",
        json=api_payload(headers=headers),
    )

    assert resp.status_code == 200
    entry = config.get("apis.my-api")
    # Exactly the submitted headers, no default Authorization header.
    assert entry["headers"] == headers
    assert "Authorization" not in entry["headers"]
    # Structure of the rest of the entry is unchanged.
    assert entry["name"] == "My API"
    assert entry["endpoint"] == "https://api.test/v1"
    assert entry["variables"] == {"keys": ["k1", "k2"]}
    assert config.save_calls == 1


def test_add_api_header_keys_are_stripped_before_storing():
    config = FakeConfig()

    resp = make_client(config).post(
        "/api/config/apis",
        json=api_payload(headers={"  x-api-key  ": "  v  "}),
    )

    assert resp.status_code == 200
    # Key is stripped; value is stored as submitted.
    assert config.get("apis.my-api.headers") == {"x-api-key": "  v  "}


def test_add_api_headers_blank_key_after_strip_returns_422():
    config = FakeConfig()

    resp = make_client(config).post(
        "/api/config/apis",
        json=api_payload(headers={"  ": "v"}),
    )

    assert resp.status_code == 422
    # Rejected before anything is written.
    assert "apis" not in config.data
    assert config.save_calls == 0


def test_add_api_more_than_20_headers_returns_422():
    config = FakeConfig()
    headers = {f"h{i}": "v" for i in range(21)}

    resp = make_client(config).post(
        "/api/config/apis",
        json=api_payload(headers=headers),
    )

    assert resp.status_code == 422
    assert "apis" not in config.data
    assert config.save_calls == 0


# --------------------------------------------------------------------------
# POST /api/config/apis/{key}/keys
# --------------------------------------------------------------------------


def test_add_provider_key_returns_503_without_config_manager():
    resp = make_client().post("/api/config/apis/openai/keys", json={"key": "k"})

    assert resp.status_code == 503


def test_add_provider_key_appends_and_reports_new_count():
    config = FakeConfig(
        {"apis": {"openai": {"name": "OpenAI", "variables": {"keys": ["k1"]}}}}
    )

    resp = make_client(config).post("/api/config/apis/openai/keys", json={"key": "k2"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "key": "openai", "key_count": 2}
    assert config.get("apis.openai.variables.keys") == ["k1", "k2"]
    assert config.save_calls == 1


def test_add_provider_key_initializes_missing_variables():
    config = FakeConfig({"apis": {"openai": {"name": "OpenAI"}}})

    resp = make_client(config).post("/api/config/apis/openai/keys", json={"key": "k1"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "key": "openai", "key_count": 1}
    assert config.get("apis.openai.variables.keys") == ["k1"]
    assert config.save_calls == 1


def test_add_provider_key_unknown_provider_returns_404():
    config = FakeConfig({"apis": {"openai": {"name": "OpenAI"}}})

    resp = make_client(config).post("/api/config/apis/nope/keys", json={"key": "k"})

    assert resp.status_code == 404
    assert config.save_calls == 0


def test_add_provider_key_duplicate_returns_409():
    config = FakeConfig(
        {"apis": {"openai": {"name": "OpenAI", "variables": {"keys": ["dup"]}}}}
    )

    resp = make_client(config).post("/api/config/apis/openai/keys", json={"key": "dup"})

    assert resp.status_code == 409
    assert config.get("apis.openai.variables.keys") == ["dup"]
    assert config.save_calls == 0


def test_add_provider_key_empty_and_blank_return_422():
    config = FakeConfig({"apis": {"openai": {"name": "OpenAI"}}})
    client = make_client(config)

    empty = client.post("/api/config/apis/openai/keys", json={"key": ""})
    blank = client.post("/api/config/apis/openai/keys", json={"key": "   "})

    # "" is rejected by pydantic min_length, "   " by the route after strip.
    assert empty.status_code == 422
    assert blank.status_code == 422
    assert config.save_calls == 0


def test_add_provider_key_save_failure_rolls_back():
    config = FakeConfig(
        {"apis": {"openai": {"name": "OpenAI", "variables": {"keys": ["k1"]}}}}
    )
    config.save_error = RuntimeError("disk full")

    resp = make_client(config).post("/api/config/apis/openai/keys", json={"key": "k2"})

    assert resp.status_code == 500
    # Rollback restored the pre-write list.
    assert config.get("apis.openai.variables.keys") == ["k1"]
    assert config.save_calls == 1


# --------------------------------------------------------------------------
# DELETE /api/config/apis/{key}
# --------------------------------------------------------------------------


def test_delete_api_returns_503_without_config_manager():
    assert make_client().delete("/api/config/apis/openai").status_code == 503


def test_delete_api_removes_section():
    config = FakeConfig(
        {
            "apis": {
                "openai": {"name": "OpenAI", "endpoint": "https://api.openai.test"},
                "anthropic": {"name": "Anthropic", "endpoint": "https://a.test"},
            }
        }
    )

    resp = make_client(config).delete("/api/config/apis/openai")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert "openai" not in config.get("apis")
    assert "anthropic" in config.get("apis")
    assert config.save_calls == 1


def test_delete_api_unknown_provider_returns_404():
    config = FakeConfig({"apis": {"openai": {"name": "OpenAI"}}})

    resp = make_client(config).delete("/api/config/apis/nope")

    assert resp.status_code == 404
    assert "openai" in config.get("apis")


def test_delete_last_provider_returns_409_and_saves_nothing():
    config = FakeConfig({"apis": {"openai": {"name": "OpenAI"}}})

    resp = make_client(config).delete("/api/config/apis/openai")

    assert resp.status_code == 409
    assert "last provider" in resp.json()["error"]
    assert "openai" in config.get("apis")
    assert config.save_calls == 0
    assert config.save_calls == 0


def test_delete_api_save_failure_restores_section():
    entry = {"name": "OpenAI", "endpoint": "https://api.openai.test"}
    other = {"name": "Anthropic", "endpoint": "https://a.test"}
    # Two providers: deleting the last one is refused upfront (409), so a
    # save-failure rollback is only reachable when a provider remains.
    config = FakeConfig({"apis": {"openai": entry, "anthropic": other}})
    config.save_error = RuntimeError("disk full")

    resp = make_client(config).delete("/api/config/apis/openai")

    assert resp.status_code == 500
    # Rollback restored the removed section.
    assert config.get("apis.openai") == entry
    assert config.save_calls == 1


# --------------------------------------------------------------------------
# Template provider (example_service) — hidden from GET, protected from DELETE
# --------------------------------------------------------------------------


def _template_entry(**overrides):
    """The shipped demo section as it appears in the starter config."""
    entry = {
        "name": "Example Service",
        "endpoint": "https://api.example.com/v1",
        "aliases": ["example"],
        "headers": {"Authorization": "Bearer ${{keys}}"},
        "variables": {"keys": ["replace-with-upstream-key"]},
    }
    entry.update(overrides)
    return entry


def test_list_apis_hides_template_provider_from_response():
    config = FakeConfig(
        {
            "apis": {
                "example_service": _template_entry(),
                "openai": {
                    "name": "OpenAI",
                    "endpoint": "https://api.openai.test",
                    "variables": {"keys": ["k1"]},
                },
            }
        }
    )

    resp = make_client(config).get("/api/config/apis")

    assert resp.status_code == 200
    items = resp.json()
    # Only the non-template provider is listed.
    assert [item["key"] for item in items] == ["openai"]
    # Neither the display name nor the section key leaks into the body.
    assert "Example Service" not in resp.text
    assert "example_service" not in resp.text


def test_list_apis_returns_empty_list_when_only_template_configured():
    config = FakeConfig({"apis": {"example_service": _template_entry()}})

    resp = make_client(config).get("/api/config/apis")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_apis_hides_template_copy_under_different_key():
    # Same name+endpoint under another section key is still the template.
    config = FakeConfig(
        {
            "apis": {
                "copy": _template_entry(),
                "openai": {
                    "name": "OpenAI",
                    "endpoint": "https://api.openai.test",
                },
            }
        }
    )

    resp = make_client(config).get("/api/config/apis")

    assert resp.status_code == 200
    assert [item["key"] for item in resp.json()] == ["openai"]


def test_delete_template_provider_returns_403_without_saving():
    config = FakeConfig(
        {
            "apis": {
                "example_service": _template_entry(),
                "openai": {"name": "OpenAI", "endpoint": "https://api.openai.test"},
            }
        }
    )

    resp = make_client(config).delete("/api/config/apis/example_service")

    assert resp.status_code == 403
    assert "template" in resp.json()["error"]
    # The section stays intact, no other provider touched, nothing saved.
    assert config.get("apis.example_service") == _template_entry()
    assert "openai" in config.get("apis")
    assert config.save_calls == 0


def test_delete_template_copy_under_different_key_returns_403():
    config = FakeConfig(
        {
            "apis": {
                "copy": _template_entry(),
                "openai": {"name": "OpenAI", "endpoint": "https://api.openai.test"},
            }
        }
    )

    resp = make_client(config).delete("/api/config/apis/copy")

    assert resp.status_code == 403
    assert "template" in resp.json()["error"]
    assert config.get("apis.copy") == _template_entry()
    assert config.save_calls == 0


def test_add_api_with_template_section_key_returns_409():
    config = FakeConfig({"apis": {"example_service": _template_entry()}})

    resp = make_client(config).post(
        "/api/config/apis",
        json=api_payload(key="example_service"),
    )

    assert resp.status_code == 409
    assert config.get("apis.example_service") == _template_entry()
    assert config.save_calls == 0


# --------------------------------------------------------------------------
# POST /api/config/clients
# --------------------------------------------------------------------------


def test_add_client_key_returns_503_without_config_manager():
    resp = make_client().post("/api/config/clients", json={"key": "k"})

    assert resp.status_code == 503


def test_add_client_key_none_becomes_list():
    config = FakeConfig()

    resp = make_client(config).post("/api/config/clients", json={"key": "new-key"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert config.get("server.api_key") == ["new-key"]
    assert config.save_calls == 1


def test_add_client_key_appends_to_existing_string():
    config = FakeConfig({"server": {"api_key": "old"}})

    resp = make_client(config).post("/api/config/clients", json={"key": "new-key"})

    assert resp.status_code == 200
    assert config.get("server.api_key") == ["old", "new-key"]


def test_add_client_key_appends_to_existing_list():
    config = FakeConfig({"server": {"api_key": ["a", "b"]}})

    resp = make_client(config).post("/api/config/clients", json={"key": "c"})

    assert resp.status_code == 200
    assert config.get("server.api_key") == ["a", "b", "c"]


def test_add_client_key_duplicate_returns_409():
    config = FakeConfig({"server": {"api_key": ["dup"]}})

    resp = make_client(config).post("/api/config/clients", json={"key": "dup"})

    assert resp.status_code == 409
    assert config.get("server.api_key") == ["dup"]
    assert config.save_calls == 0


def test_add_client_key_empty_and_whitespace_only_return_422():
    config = FakeConfig()
    client = make_client(config)

    empty = client.post("/api/config/clients", json={"key": ""})
    blank = client.post("/api/config/clients", json={"key": "   "})

    # "" is rejected by pydantic min_length, "   " by the route after strip.
    assert empty.status_code == 422
    assert blank.status_code == 422
    assert config.get("server.api_key") is None
    assert config.save_calls == 0


def test_add_client_key_is_stripped_before_storing():
    config = FakeConfig()

    resp = make_client(config).post("/api/config/clients", json={"key": "  pad  "})

    assert resp.status_code == 200
    assert config.get("server.api_key") == ["pad"]


def test_add_client_key_save_failure_rolls_back_absent_value():
    config = FakeConfig()
    config.save_error = RuntimeError("disk full")

    resp = make_client(config).post("/api/config/clients", json={"key": "new-key"})

    assert resp.status_code == 500
    # raw_old was None, so rollback deletes the freshly written value.
    assert config.get("server.api_key") is None
    assert config.save_calls == 1


def test_add_client_key_save_failure_restores_previous_value():
    config = FakeConfig({"server": {"api_key": "old"}})
    config.save_error = RuntimeError("disk full")

    resp = make_client(config).post("/api/config/clients", json={"key": "new-key"})

    assert resp.status_code == 500
    assert config.get("server.api_key") == "old"


# --------------------------------------------------------------------------
# GET /api/config/clients
# --------------------------------------------------------------------------


def test_list_client_keys_returns_503_without_config_manager():
    assert make_client().get("/api/config/clients").status_code == 503


def test_list_client_keys_empty_returns_empty_list():
    resp = make_client(FakeConfig()).get("/api/config/clients")

    assert resp.status_code == 200
    assert resp.json() == {"clients": []}


def test_list_client_keys_normalizes_single_string():
    full_key = "verysecretclientkey-abcdef123456"
    config = FakeConfig({"server": {"api_key": full_key}})

    resp = make_client(config).get("/api/config/clients")

    assert resp.status_code == 200
    clients = resp.json()["clients"]
    assert clients == [{"index": 0, "mask": _mask_key(full_key)}]
    # Mask keeps only the edges — the full key never leaves the API.
    assert full_key not in resp.text


def test_list_client_keys_masks_short_values_and_indexes_lists():
    config = FakeConfig({"server": {"api_key": ["a", "bb", "ccc"]}})

    resp = make_client(config).get("/api/config/clients")

    assert resp.json() == {
        "clients": [
            {"index": 0, "mask": "*"},
            {"index": 1, "mask": "**"},
            {"index": 2, "mask": "***"},
        ]
    }


def test_list_client_keys_unexpected_type_returns_empty():
    resp = make_client(FakeConfig({"server": {"api_key": 42}})).get(
        "/api/config/clients"
    )

    assert resp.status_code == 200
    assert resp.json() == {"clients": []}


# --------------------------------------------------------------------------
# DELETE /api/config/clients/{index}
# --------------------------------------------------------------------------


def test_delete_client_key_returns_503_without_config_manager():
    assert make_client().delete("/api/config/clients/0").status_code == 503


def test_delete_client_key_removes_by_index():
    config = FakeConfig({"server": {"api_key": ["a", "b", "c"]}})

    resp = make_client(config).delete("/api/config/clients/1")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert config.get("server.api_key") == ["a", "c"]
    assert config.save_calls == 1


def test_delete_client_key_out_of_range_returns_404():
    config = FakeConfig({"server": {"api_key": ["a", "b"]}})
    client = make_client(config)

    past = client.delete("/api/config/clients/5")
    negative = client.delete("/api/config/clients/-1")

    assert past.status_code == 404
    # Negative indices must not wrap around the list.
    assert negative.status_code == 404
    assert config.get("server.api_key") == ["a", "b"]
    assert config.save_calls == 0


def test_delete_last_client_key_returns_409():
    config = FakeConfig({"server": {"api_key": ["only"]}})

    resp = make_client(config).delete("/api/config/clients/0")

    assert resp.status_code == 409
    assert resp.json() == {
        "error": ("Cannot revoke the last client key: dashboard auth would be disabled")
    }
    assert config.get("server.api_key") == ["only"]
    assert config.save_calls == 0


def test_delete_client_key_save_failure_restores_previous_value():
    config = FakeConfig({"server": {"api_key": ["a", "b"]}})
    config.save_error = RuntimeError("disk full")

    resp = make_client(config).delete("/api/config/clients/0")

    assert resp.status_code == 500
    assert config.get("server.api_key") == ["a", "b"]
    assert config.save_calls == 1
