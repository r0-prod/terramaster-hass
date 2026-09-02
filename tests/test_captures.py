"""Parse the real captured payloads, so firmware drift shows up as a test failure.

Captures are produced by ``tools/probe_tos.py`` and are gitignored; these tests
skip when they are absent (e.g. on a machine with no NAS access).
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "terramaster"))

from tos import models  # noqa: E402

CAPTURES = ROOT / "tools" / "captures"

pytestmark = pytest.mark.skipif(
    not (CAPTURES / "disk_GetDiskStatus.json").exists(),
    reason="no captures; run tools/probe_tos.py against a NAS first",
)


def _load(name: str):
    return json.loads((CAPTURES / f"{name}.json").read_text())


def test_every_bay_yields_a_temperature():
    disks = models.build_disks(
        _load("disk_GetDiskStatus"),
        _load("disk_GetDiskListData"),
        _load("disk_GetOverview"),
    )
    assert disks, "no disks parsed"
    assert len(disks) == _load("disk_GetOverview")["data"]["hdd_disk_number"]
    for disk in disks:
        assert disk.temperature is not None, f"{disk.name} has no temperature"
        assert 0 < disk.temperature < 100
        assert disk.serial
        assert disk.unique_key


def test_disk_unique_keys_are_distinct():
    disks = models.build_disks(
        _load("disk_GetDiskStatus"),
        _load("disk_GetDiskListData"),
        _load("disk_GetOverview"),
    )
    keys = [d.unique_key for d in disks]
    assert len(set(keys)) == len(keys)


def test_volumes_parse_with_sane_capacities():
    volumes = models.build_volumes(_load("storage_list_volume"))
    assert volumes
    for volume in volumes:
        assert volume.total and volume.total > 0
        assert volume.used is not None
        assert not volume.name.startswith("${"), "i18n placeholder left unresolved"


def test_pools_parse_with_sane_capacities():
    pools = models.build_pools(_load("storage_list_pool"))
    assert pools
    for pool in pools:
        assert pool.total and pool.total > 0
        assert not pool.name.startswith("${")


def test_hardware_capture_exposes_the_fan_contract():
    fan = _load("hardware")["data"]["fan"]
    assert set(fan) >= {"is_auto", "level"}
    assert isinstance(fan["level"], int)


def test_temperature_capture_exposes_expected_fields():
    data = _load("resource_temperature")["data"]
    assert {"cpu_temperature", "sys_temperature", "fan_speed"} <= set(data)
