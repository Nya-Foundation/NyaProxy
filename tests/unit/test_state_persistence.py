"""
Runtime state that has to survive the restart used to apply config changes.

The property under test throughout: a restart must not hand out a fresh burst
allowance or release a quarantined key, while still picking up a rate limit
that was edited while the process was down.
"""

import json
import os
import stat
import time
from types import SimpleNamespace

from nya.core.control import TrafficManager
from nya.server import app as server_app
from nya.services.limit import RateLimiter
from nya.services.state import (
    STATE_VERSION,
    load_state,
    resolve_state_path,
    save_state,
    state_key,
)


class StubConfig:
    """Minimal ConfigManager stand-in whose limits can change between runs."""

    def __init__(self, key_rate="2/m", endpoint_rate="0", config_path=None):
        self.key_rate = key_rate
        self.endpoint_rate = endpoint_rate
        self.config_path = config_path

    def get_api_key_rate_limit(self, api_name):
        return self.key_rate

    def get_api_endpoint_rate_limit(self, api_name):
        return self.endpoint_rate

    def get_api_ip_rate_limit(self, api_name):
        return "0"

    def get_api_user_rate_limit(self, api_name):
        return "0"


# --- RateLimiter snapshots ---------------------------------------------------


def test_export_returns_none_when_there_is_nothing_worth_keeping():
    assert RateLimiter("10/m").export_state() is None


def test_consumed_window_survives_a_restart():
    limiter = RateLimiter("2/m")
    limiter.record()
    limiter.record()
    assert limiter.is_limited()

    restored = RateLimiter("2/m")
    restored.restore_state(limiter.export_state())

    # Without this the operator would get a fresh quota on every config edit.
    assert restored.is_limited()
    assert len(restored.request_timestamps) == 2


def test_quarantined_key_stays_quarantined_across_a_restart():
    limiter = RateLimiter("0")
    limiter.block_for(300)

    restored = RateLimiter("0")
    restored.restore_state(limiter.export_state())

    assert restored.blocked_until > time.time()
    assert restored.is_limited()


def test_expired_cooldown_is_not_restored():
    limiter = RateLimiter("0")
    limiter.blocked_until = time.time() - 5
    assert limiter.export_state() is None

    restored = RateLimiter("0")
    restored.restore_state({"blocked_until": time.time() - 5})
    assert restored.blocked_until == 0.0


def test_timestamps_outside_the_window_are_dropped_on_restore():
    old = time.time() - 3600
    restored = RateLimiter("5/m")
    restored.restore_state({"timestamps": [old, old, time.time()]})

    assert len(restored.request_timestamps) == 1


def test_future_timestamps_are_rejected():
    """A backwards clock change or edited state file must not wedge a limiter."""
    restored = RateLimiter("1/m")
    restored.restore_state({"timestamps": [time.time() + 10_000]})

    assert len(restored.request_timestamps) == 0
    assert not restored.is_limited()


def test_malformed_entries_are_ignored():
    restored = RateLimiter("5/m")
    restored.restore_state(
        {"timestamps": ["nope", None, time.time()], "blocked_until": "x"}
    )

    assert len(restored.request_timestamps) == 1
    assert restored.blocked_until == 0.0


def test_concurrency_lock_is_not_restored():
    """`locked` tracks in-flight requests of a process that is going away."""
    limiter = RateLimiter("5/m")
    limiter.record()
    limiter.lock()

    restored = RateLimiter("5/m")
    restored.restore_state(limiter.export_state())

    assert restored.locked is False


# --- TrafficManager export/import --------------------------------------------


def test_persisted_state_contains_no_credentials():
    """Limiter names embed the upstream key, so the file must not hold them."""
    control = TrafficManager(StubConfig())
    control.get_key_limiter("openai", "sk-super-secret").record()

    exported = control.export_state()
    blob = json.dumps(exported)

    assert "sk-super-secret" not in blob
    assert state_key("openai_key_sk-super-secret") in exported["rate_limiters"]


def test_limiter_state_is_restored_on_next_use():
    before = TrafficManager(StubConfig(key_rate="2/m"))
    before.get_key_limiter("openai", "sk-a").record()
    before.get_key_limiter("openai", "sk-a").record()
    assert before.get_key_limiter("openai", "sk-a").is_limited()

    after = TrafficManager(StubConfig(key_rate="2/m"))
    after.import_state(before.export_state())

    assert after.get_key_limiter("openai", "sk-a").is_limited()


def test_restart_applies_an_edited_rate_limit_to_restored_state():
    """
    The whole reason for restarting is to pick up config, so restored state
    must not drag the old limit along with it.
    """
    before = TrafficManager(StubConfig(key_rate="2/m"))
    before.get_key_limiter("openai", "sk-a").record()
    before.get_key_limiter("openai", "sk-a").record()

    # Operator raises the limit while the process is down.
    after = TrafficManager(StubConfig(key_rate="10/m"))
    after.import_state(before.export_state())
    limiter = after.get_key_limiter("openai", "sk-a")

    assert limiter.rate_limit == "10/m"
    assert not limiter.is_limited()  # 2 of 10 consumed
    assert len(limiter.request_timestamps) == 2


def test_quarantine_survives_through_the_traffic_manager():
    before = TrafficManager(StubConfig())
    before.block_key("openai", "sk-bad", 300)

    after = TrafficManager(StubConfig())
    after.import_state(before.export_state())

    assert after.get_key_limiter("openai", "sk-bad").blocked_until > time.time()


def test_import_tolerates_junk():
    control = TrafficManager(StubConfig())
    assert control.import_state({}) == 0
    assert control.import_state({"rate_limiters": None}) == 0
    assert control.import_state({"rate_limiters": "nope"}) == 0
    assert control.import_state({"rate_limiters": {"a": "not-a-dict"}}) == 0


def test_unused_restored_entries_do_not_leak_into_other_limiters():
    before = TrafficManager(StubConfig())
    before.get_key_limiter("openai", "sk-a").record()

    after = TrafficManager(StubConfig())
    after.import_state(before.export_state())

    # A different key must not inherit the first key's consumed window.
    other = after.get_key_limiter("openai", "sk-b")
    assert len(other.request_timestamps) == 0


# --- state file --------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert save_state(path, {"rate_limiters": {"a": {"timestamps": [1.0]}}}) is True

    assert load_state(path) == {"rate_limiters": {"a": {"timestamps": [1.0]}}}


def test_state_file_is_not_world_readable(tmp_path):
    """Even hashed, this is operational data about credential usage."""
    path = tmp_path / "state.json"
    save_state(path, {"rate_limiters": {}})

    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_missing_file_is_not_an_error(tmp_path):
    assert load_state(tmp_path / "absent.json") == {}


def test_corrupt_file_does_not_prevent_startup(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")

    assert load_state(path) == {}


def test_version_mismatch_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"version": STATE_VERSION + 1, "rate_limiters": {"a": {}}})
    )

    assert load_state(path) == {}


def test_non_object_document_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps([1, 2, 3]))

    assert load_state(path) == {}


def test_save_leaves_no_temporary_files_behind(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, {"rate_limiters": {}})

    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_save_failure_is_reported_not_raised(tmp_path):
    # A directory where the file should be makes the atomic rename fail.
    path = tmp_path / "state.json"
    path.mkdir()

    assert save_state(path, {"rate_limiters": {}}) is False


def test_state_file_lives_beside_the_config(tmp_path):
    """A bind-mounted config directory then carries the state with it."""
    config = tmp_path / "sub" / "config.yaml"
    config.parent.mkdir()
    config.write_text("{}")

    assert resolve_state_path(str(config)) == config.parent / ".nya_state.json"


def test_state_path_falls_back_to_cwd_without_a_config_path():
    assert resolve_state_path(None).name == ".nya_state.json"


# --- app wiring --------------------------------------------------------------


def _app_with_control(config_path, control):
    app = object.__new__(server_app.NyaProxyApp)
    app.config = SimpleNamespace(config_path=str(config_path))
    app.core = SimpleNamespace(control=control)
    return app


def test_app_persists_and_restores_limiter_state(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}")

    control = TrafficManager(StubConfig(key_rate="2/m"))
    control.get_key_limiter("openai", "sk-a").record()
    control.get_key_limiter("openai", "sk-a").record()

    assert _app_with_control(config_path, control).persist_runtime_state() is True
    assert (tmp_path / ".nya_state.json").exists()

    fresh = TrafficManager(StubConfig(key_rate="2/m"))
    assert _app_with_control(config_path, fresh).restore_runtime_state() == 1
    assert fresh.get_key_limiter("openai", "sk-a").is_limited()


def test_app_state_path_prefers_the_configured_path_over_the_environment(
    tmp_path, monkeypatch
):
    """
    The path can arrive as a constructor argument; falling back to the working
    directory would make two instances share one another's quotas.
    """
    monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "from-env" / "config.yaml"))
    config_path = tmp_path / "from-arg" / "config.yaml"
    config_path.parent.mkdir()

    app = _app_with_control(config_path, TrafficManager(StubConfig()))

    assert app._state_path() == config_path.parent / ".nya_state.json"


def test_restore_is_a_no_op_without_a_core(tmp_path):
    app = object.__new__(server_app.NyaProxyApp)
    app.config = SimpleNamespace(config_path=str(tmp_path / "config.yaml"))
    app.core = None

    assert app.restore_runtime_state() == 0
    assert app.persist_runtime_state() is False


def test_unreadable_state_does_not_break_startup(tmp_path):
    config_path = tmp_path / "config.yaml"
    (tmp_path / ".nya_state.json").write_text("{corrupt")

    app = _app_with_control(config_path, TrafficManager(StubConfig()))

    assert app.restore_runtime_state() == 0
