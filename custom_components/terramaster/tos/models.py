"""Parsing helpers turning raw TOS payloads into typed values.

Shapes are taken from real captures in ``tools/captures/`` -- see
``tools/probe_tos.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# "44°C/111°F" -> 44
_TEMP_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*°?\s*C", re.IGNORECASE)

# "${global,storagepool}1" -> ("storagepool", "1")
_PLACEHOLDER_RE = re.compile(r"^\$\{[^,]+,([^}]+)\}(.*)$")

_UNIT_MULTIPLIER = {
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
    "PB": 1024**5,
}

_FRIENDLY_NAMES = {
    "storagepool": "Storage Pool",
    "lvm": "Volume",
    "volume": "Volume",
}

# TOS reports drive health as a string enum; 3 is its "good" value.
HEALTH_OK = "3"


def parse_temperature(value: Any) -> float | None:
    """Pull the Celsius figure out of TOS's ``"44°C/111°F"`` strings."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _TEMP_RE.search(str(value))
    return float(match.group(1)) if match else None


def parse_size(value: Any) -> int | None:
    """Convert a ``{"value": N, "unit": "KB"}`` pair to bytes."""
    if not isinstance(value, dict):
        return None
    raw = value.get("value")
    if raw is None:
        return None
    multiplier = _UNIT_MULTIPLIER.get(str(value.get("unit", "B")).upper())
    if multiplier is None:
        return None
    return int(float(raw) * multiplier)


def resolve_name(show_name: Any, fallback: str = "") -> str:
    """Render TOS's ``${global,storagepool}1`` i18n placeholders as English."""
    if not isinstance(show_name, str) or not show_name:
        return fallback
    match = _PLACEHOLDER_RE.match(show_name)
    if not match:
        return show_name
    token, suffix = match.groups()
    friendly = _FRIENDLY_NAMES.get(token, token.replace("_", " ").title())
    return f"{friendly} {suffix}".strip()


@dataclass(slots=True)
class Disk:
    """One physical drive, merged from GetDiskStatus + GetDiskListData."""

    slot: int
    name: str
    serial: str | None = None
    device: str | None = None
    model: str | None = None
    temperature: float | None = None
    power_on_hours: int | None = None
    status: int | None = None
    capacity: str | None = None

    @property
    def unique_key(self) -> str:
        """Stable across reboots and slot renames; serial is the real identity."""
        return self.serial or self.device or f"slot{self.slot}"

    @property
    def healthy(self) -> bool | None:
        return None if self.status is None else self.status == 0


@dataclass(slots=True)
class Volume:
    uuid: str
    name: str
    total: int | None = None
    used: int | None = None
    available: int | None = None
    usage: float | None = None
    filesystem: str | None = None
    mount_path: str | None = None


@dataclass(slots=True)
class Pool:
    uuid: str
    name: str
    total: int | None = None
    free: int | None = None
    level: str | None = None
    health: int | None = None
    status: str | None = None


@dataclass(slots=True)
class NasData:
    """Everything one coordinator refresh gathers."""

    fan_is_auto: bool | None = None
    fan_level: int | None = None
    fan_rpm: int | None = None
    cpu_temperature: float | None = None
    system_temperature: float | None = None
    model: str | None = None
    device_name: str | None = None
    processor: str | None = None
    disks: list[Disk] = field(default_factory=list)
    volumes: list[Volume] = field(default_factory=list)
    pools: list[Pool] = field(default_factory=list)

    @property
    def max_disk_temperature(self) -> float | None:
        temps = [d.temperature for d in self.disks if d.temperature is not None]
        return max(temps) if temps else None


def _unwrap(payload: Any) -> Any:
    """TOS wraps every result as ``{is_login, code, msg, data}``."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def build_disks(status: Any, listing: Any, overview: Any) -> list[Disk]:
    """Merge the three disk endpoints, keyed by slot.

    GetDiskStatus is authoritative for temperature and is the only endpoint that
    reports every bay -- IhmInfoList covers IronWolf drives only.
    """
    disks: dict[int, Disk] = {}

    for entry in _unwrap(status) or []:
        if not isinstance(entry, dict):
            continue
        slot = entry.get("slot")
        if slot is None:
            continue
        disks[slot] = Disk(
            slot=slot,
            name=entry.get("name") or f"HDD{slot}",
            serial=entry.get("serial"),
            device=entry.get("device"),
            temperature=parse_temperature(entry.get("temperature")),
            power_on_hours=entry.get("power_on_hours"),
            status=entry.get("status"),
        )

    # GetDiskListData has no slot field; match on device path.
    by_device = {d.device: d for d in disks.values() if d.device}
    for entry in _unwrap(listing) or []:
        if not isinstance(entry, dict):
            continue
        if disk := by_device.get(entry.get("device")):
            disk.model = entry.get("model")

    for entry in (_unwrap(overview) or {}).get("slot_data", []) or []:
        if not isinstance(entry, dict):
            continue
        if disk := disks.get(entry.get("slot")):
            disk.capacity = entry.get("factory_capacity") or None

    return [disks[slot] for slot in sorted(disks)]


def build_volumes(payload: Any) -> list[Volume]:
    volumes: list[Volume] = []
    for uuid, entry in (_unwrap(payload) or {}).items():
        if not isinstance(entry, dict):
            continue
        volumes.append(
            Volume(
                uuid=uuid,
                name=resolve_name(entry.get("show_name"), entry.get("name", uuid)),
                total=parse_size(entry.get("total")),
                used=parse_size(entry.get("used")),
                available=parse_size(entry.get("available")),
                usage=entry.get("usage"),
                filesystem=entry.get("filesystem"),
                mount_path=entry.get("mntpath"),
            )
        )
    return sorted(volumes, key=lambda v: v.name)


def build_pools(payload: Any) -> list[Pool]:
    pools: list[Pool] = []
    for uuid, entry in (_unwrap(payload) or {}).items():
        if not isinstance(entry, dict):
            continue
        pools.append(
            Pool(
                uuid=uuid,
                name=resolve_name(entry.get("show_name"), entry.get("name", uuid)),
                total=parse_size(entry.get("total")),
                free=parse_size(entry.get("free")),
                level=entry.get("level"),
                health=entry.get("health"),
                status=resolve_name(entry.get("status"), "") or None,
            )
        )
    return sorted(pools, key=lambda p: p.name)
