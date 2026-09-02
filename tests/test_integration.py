"""Load the integration inside a real Home Assistant instance.

This is the check that matters most here: the integration is deployed by hand,
so an import error or a wrong HA API call would otherwise only surface as a
failed setup after copying files to the NAS box.

The NAS itself is replaced with captured payloads -- see tools/probe_tos.py.
"""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from homeassistant.exceptions import HomeAssistantError

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramaster.const import DOMAIN

ENTRY_DATA = {
    CONF_HOST: "10.0.0.9",
    CONF_PORT: 8181,
    CONF_USERNAME: "tester",
    CONF_PASSWORD: "secret",
}


def _ok(data):
    return {"is_login": True, "code": True, "msg": "", "data": data, "code_num": 0}


HARDWARE = _ok({"fan": {"is_auto": False, "level": 4}, "stand_by": "30m"})
TEMPERATURE = _ok(
    {"cpu_temperature": 39, "sys_temperature": 35, "fan_speed": 1225,
     "disk_temperature": {"HDD": "sdc", "Serial": "sdc", "Temp": 46}}
)
DISK_STATUS = _ok([
    {"slot": 1, "name": "HDD1", "serial": "SN00000001", "device": "/dev/sda",
     "status": 0, "temperature": "42°C/107°F", "power_on_hours": 20578},
    {"slot": 2, "name": "HDD2", "serial": "WD-SN00000002", "device": "/dev/sdb",
     "status": 0, "temperature": "36°C/96°F", "power_on_hours": 18477},
])
DISK_LIST = _ok([
    {"device": "/dev/sda", "model": "ST5000VN0001-1SF17X"},
    {"device": "/dev/sdb", "model": "WDC WD40EZAZ-00SF3B0"},
])
OVERVIEW = _ok({
    "device_name": "TNAS", "model": "F4-425", "hdd_disk_number": 2,
    "slot_data": [{"slot": 1, "factory_capacity": "5.00 TB"},
                  {"slot": 2, "factory_capacity": "4.00 TB"}],
})
VOLUMES = _ok({"uuid-1": {
    "show_name": "${global,lvm}1", "name": "lv0", "filesystem": "btrfs",
    "mntpath": "/Volume1", "usage": 1.52,
    "total": {"value": 3895820288, "unit": "KB"},
    "used": {"value": 59103304, "unit": "KB"},
    "available": {"value": 3834820344, "unit": "KB"},
}})
POOLS = _ok({"uuid-1-traid": {
    "show_name": "${global,storagepool}1", "name": "vg0", "level": "traid",
    "health": 3, "total": {"value": 4873207808, "unit": "KB"},
    "free": {"value": 977387520, "unit": "KB"},
}})
CPU = _ok({"IsArm": False, "Processor": "Intel(R) Celeron(R) N5095 @ 2.00GHz"})

GET_ROUTES = {
    "/hardware/": HARDWARE,
    "/resource/temperature": TEMPERATURE,
    "/disk/GetDiskStatus": DISK_STATUS,
    "/disk/GetDiskListData": DISK_LIST,
    "/disk/GetOverview": OVERVIEW,
    "/storage/list/volume": VOLUMES,
    "/storage/list/pool": POOLS,
    "/systemStatus/NasProcessorInfo": CPU,
}


def _make_client():
    # Deep-copied per test: the coordinator reads these dicts before writing, and
    # sharing module-level state would leak a fan change into the next test.
    routes = deepcopy(GET_ROUTES)
    client = AsyncMock()
    client.base_url = "http://10.0.0.9:8181"
    client.get.side_effect = lambda path, *a, **k: routes[path]
    client.hardware.side_effect = lambda: routes["/hardware/"]
    client.temperature.side_effect = lambda: routes["/resource/temperature"]
    client.disks.side_effect = lambda: routes["/disk/GetDiskListData"]
    client.volumes.side_effect = lambda: routes["/storage/list/volume"]
    client.pools.side_effect = lambda: routes["/storage/list/pool"]
    client.processor.side_effect = lambda: routes["/systemStatus/NasProcessorInfo"]
    client.routes = routes  # tests mutate this to simulate the NAS changing
    return client


@pytest.fixture
def mock_client():
    client = _make_client()
    with patch("custom_components.terramaster.TosClient", return_value=client):
        yield client


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="TNAS (F4-425)")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_expected_entities(hass: HomeAssistant, mock_client) -> None:
    await _setup(hass)

    assert hass.states.get("sensor.tnas_cpu_temperature").state == "39"
    assert hass.states.get("sensor.tnas_system_temperature").state == "35"
    assert hass.states.get("sensor.tnas_fan_speed").state == "1225"
    # Hottest of the two drives, parsed out of "42°C/107°F".
    assert hass.states.get("sensor.tnas_hottest_disk").state == "42.0"


async def test_per_disk_entities(hass: HomeAssistant, mock_client) -> None:
    await _setup(hass)

    hdd1 = hass.states.get("sensor.tnas_hdd1_temperature")
    assert hdd1.state == "42.0"
    assert hdd1.attributes["model"] == "ST5000VN0001-1SF17X"
    assert hdd1.attributes["capacity"] == "5.00 TB"
    assert hass.states.get("sensor.tnas_hdd2_temperature").state == "36.0"
    assert hass.states.get("binary_sensor.tnas_hdd1_problem").state == "off"


async def test_storage_entities(hass: HomeAssistant, mock_client) -> None:
    await _setup(hass)

    total = hass.states.get("sensor.tnas_volume_1_total")
    assert float(total.state) == pytest.approx(3895820288 * 1024 / 2**30, rel=1e-6)
    assert hass.states.get("sensor.tnas_volume_1_usage").state == "1.5"
    assert hass.states.get("sensor.tnas_storage_pool_1_total") is not None


async def test_fan_mode_select_reflects_level_four(hass: HomeAssistant, mock_client) -> None:
    await _setup(hass)
    assert hass.states.get("select.tnas_fan_mode").state == "medium"


async def test_selecting_a_fan_mode_writes_the_whole_hardware_object(
    hass: HomeAssistant, mock_client
) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.tnas_fan_mode", "option": "full"},
        blocking=True,
    )
    written = mock_client.set_hardware.call_args[0][0]
    assert written["fan"] == {"is_auto": False, "level": 8}
    # stand_by must survive: TOS replaces the whole object, not a delta.
    assert written["stand_by"] == "30m"


async def test_unload(hass: HomeAssistant, mock_client) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    mock_client.close.assert_awaited()


# ---- overheat watchdog ---------------------------------------------------


def _set_hottest_disk(client, celsius: int) -> None:
    client.routes["/disk/GetDiskStatus"]["data"][0]["temperature"] = f"{celsius}°C/xx°F"


def _set_fan(client, *, is_auto: bool, level: int) -> None:
    client.routes["/hardware/"]["data"]["fan"] = {"is_auto": is_auto, "level": level}


async def _refresh(hass: HomeAssistant, entry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_watchdog_restores_auto_when_manual_and_too_hot(
    hass: HomeAssistant, mock_client
) -> None:
    entry = await _setup(hass)
    mock_client.set_hardware.reset_mock()

    _set_fan(mock_client, is_auto=False, level=0)
    _set_hottest_disk(mock_client, 60)
    await _refresh(hass, entry)

    written = mock_client.set_hardware.call_args[0][0]
    assert written["fan"] == {"is_auto": True, "level": -1}
    assert hass.states.get("select.tnas_fan_mode").state == "auto"


async def test_watchdog_ignores_a_fan_already_in_auto(
    hass: HomeAssistant, mock_client
) -> None:
    entry = await _setup(hass)
    mock_client.set_hardware.reset_mock()

    _set_fan(mock_client, is_auto=True, level=-1)
    _set_hottest_disk(mock_client, 65)
    await _refresh(hass, entry)

    mock_client.set_hardware.assert_not_called()


async def test_watchdog_leaves_manual_mode_alone_below_threshold(
    hass: HomeAssistant, mock_client
) -> None:
    entry = await _setup(hass)
    mock_client.set_hardware.reset_mock()

    _set_fan(mock_client, is_auto=False, level=0)
    _set_hottest_disk(mock_client, 54)  # threshold is 55
    await _refresh(hass, entry)

    mock_client.set_hardware.assert_not_called()
    assert hass.states.get("select.tnas_fan_mode").state == "low"


async def test_watchdog_can_be_disabled_in_options(hass: HomeAssistant, mock_client) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        title="TNAS (F4-425)",
        options={"overheat_protection": False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_client.set_hardware.reset_mock()

    _set_fan(mock_client, is_auto=False, level=0)
    _set_hottest_disk(mock_client, 70)
    await _refresh(hass, entry)

    mock_client.set_hardware.assert_not_called()


async def test_fan_mode_failure_raises_a_translated_error(
    hass: HomeAssistant, mock_client
) -> None:
    """A NAS write failure must surface as HomeAssistantError, not a raw TosError."""
    from custom_components.terramaster.tos import TosError

    await _setup(hass)
    mock_client.set_hardware.side_effect = TosError("connection reset")

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.tnas_fan_mode", "option": "full"},
            blocking=True,
        )
    assert err.value.translation_key == "set_fan_mode_failed"
    assert err.value.translation_domain == DOMAIN
