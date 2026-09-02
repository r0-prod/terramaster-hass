"""Tests for the TOS payload parsers, using shapes captured from a real NAS."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "terramaster"))

from tos import models  # noqa: E402


def test_parse_temperature_from_tos_dual_unit_string():
    assert models.parse_temperature("44°C/111°F") == 44.0


def test_parse_temperature_passes_through_numbers():
    assert models.parse_temperature(39) == 39.0


def test_parse_temperature_handles_missing():
    assert models.parse_temperature(None) is None
    assert models.parse_temperature("n/a") is None


def test_parse_size_converts_kb_to_bytes():
    assert models.parse_size({"value": 4873207808, "unit": "KB"}) == 4873207808 * 1024


def test_parse_size_rejects_unknown_unit():
    assert models.parse_size({"value": 1, "unit": "furlongs"}) is None


def test_resolve_name_expands_tos_placeholders():
    assert models.resolve_name("${global,storagepool}1") == "Storage Pool 1"
    assert models.resolve_name("${global,lvm}1") == "Volume 1"


def test_resolve_name_leaves_plain_strings_alone():
    assert models.resolve_name("vg0") == "vg0"


def test_build_disks_merges_status_listing_and_overview():
    status = {"data": [
        {"slot": 2, "name": "HDD2", "serial": "WD-X", "device": "/dev/sdb",
         "status": 0, "temperature": "38°C/100°F", "power_on_hours": 18477},
        {"slot": 1, "name": "HDD1", "serial": "SN00000001", "device": "/dev/sda",
         "status": 0, "temperature": "44°C/111°F", "power_on_hours": 20578},
    ]}
    listing = {"data": [{"device": "/dev/sda", "model": "ST5000VN0001-1SF17X"}]}
    overview = {"data": {"slot_data": [{"slot": 1, "factory_capacity": "5.00 TB"}]}}

    disks = models.build_disks(status, listing, overview)

    assert [d.slot for d in disks] == [1, 2]          # sorted by slot
    assert disks[0].model == "ST5000VN0001-1SF17X"     # merged on device path
    assert disks[0].capacity == "5.00 TB"
    assert disks[0].temperature == 44.0
    assert disks[1].model is None                      # not in the listing
    assert all(d.healthy for d in disks)


def test_disk_unique_key_prefers_serial():
    disk = models.Disk(slot=1, name="HDD1", serial="SN00000001", device="/dev/sda")
    assert disk.unique_key == "SN00000001"
    assert models.Disk(slot=1, name="HDD1", device="/dev/sda").unique_key == "/dev/sda"
    assert models.Disk(slot=3, name="HDD3").unique_key == "slot3"


def test_max_disk_temperature_ignores_missing_readings():
    data = models.NasData(disks=[
        models.Disk(slot=1, name="HDD1", temperature=44.0),
        models.Disk(slot=2, name="HDD2", temperature=None),
        models.Disk(slot=3, name="HDD3", temperature=48.0),
    ])
    assert data.max_disk_temperature == 48.0


def test_max_disk_temperature_is_none_without_disks():
    assert models.NasData().max_disk_temperature is None


def test_build_volumes_and_pools_from_uuid_keyed_maps():
    volumes = models.build_volumes({"data": {"uuid-1": {
        "show_name": "${global,lvm}1", "name": "lv0", "filesystem": "btrfs",
        "mntpath": "/Volume1", "usage": 1.51,
        "total": {"value": 100, "unit": "KB"},
        "used": {"value": 40, "unit": "KB"},
        "available": {"value": 60, "unit": "KB"},
    }}})
    assert volumes[0].name == "Volume 1"
    assert volumes[0].total == 100 * 1024
    assert volumes[0].mount_path == "/Volume1"

    pools = models.build_pools({"data": {"uuid-1-traid": {
        "show_name": "${global,storagepool}1", "level": "traid", "health": 3,
        "total": {"value": 200, "unit": "KB"}, "free": {"value": 50, "unit": "KB"},
    }}})
    assert pools[0].name == "Storage Pool 1"
    assert pools[0].level == "traid"
    assert pools[0].free == 50 * 1024
