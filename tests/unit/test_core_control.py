import pytest

from nya.common.exceptions import APIKeyNotConfiguredError
from nya.core.control import TrafficManager
from tests.unit.core_helpers import CoreConfig


@pytest.mark.asyncio
async def test_traffic_manager_key_selection_release_and_blocking():
    config = CoreConfig()
    config.key_concurrency = False
    control = TrafficManager(config)

    key, wait_time = await control.acquire_key("mock")
    assert (key, wait_time) == ("key-a", 0)
    assert control.time_to_key_ready("mock") == 0
    control.block_key("mock", "key-b", 1)
    assert control.time_to_key_ready("mock") > 0
    control.release_key("mock", "key-a")
    control.unlock_key("mock", "key-b")
    assert control.select_any_key("mock") in {"key-a", "key-b"}
    control.record_ip_request("mock", "ip")
    control.record_user_request("mock", "user")
    control.release_ip("mock", "ip")
    control.release_user("mock", "user")
    control.release_endpoint("mock")


def test_traffic_manager_select_any_key_requires_configured_keys():
    config = CoreConfig()
    config.keys = []

    with pytest.raises(APIKeyNotConfiguredError):
        TrafficManager(config).select_any_key("mock")
