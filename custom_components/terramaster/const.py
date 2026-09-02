"""Constants for the TerraMaster NAS integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "terramaster"
MANUFACTURER: Final = "TerraMaster"

CONF_SCAN_INTERVAL: Final = "scan_interval"

# /resource/temperature and /disk/GetDiskStatus both shell out to smartctl and
# can take several seconds, so poll gently by default.
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 15

# Fan presets exactly as the TOS web UI offers them.
FAN_MODE_AUTO: Final = "auto"
FAN_MODE_LOW: Final = "low"
FAN_MODE_MEDIUM: Final = "medium"
FAN_MODE_FULL: Final = "full"

FAN_MODES: Final = [FAN_MODE_AUTO, FAN_MODE_LOW, FAN_MODE_MEDIUM, FAN_MODE_FULL]

# mode -> (is_auto, level)
FAN_MODE_TO_SETTING: Final[dict[str, tuple[bool, int]]] = {
    FAN_MODE_AUTO: (True, -1),
    FAN_MODE_LOW: (False, 0),
    FAN_MODE_MEDIUM: (False, 4),
    FAN_MODE_FULL: (False, 8),
}

FAN_LEVEL_TO_MODE: Final[dict[int, str]] = {
    0: FAN_MODE_LOW,
    4: FAN_MODE_MEDIUM,
    8: FAN_MODE_FULL,
}

# Safety net: every non-auto mode disables the firmware's own ramp-up,
# so the integration hands control back if the drives get too hot.
CONF_OVERHEAT_PROTECTION: Final = "overheat_protection"
CONF_OVERHEAT_CELSIUS: Final = "overheat_celsius"
DEFAULT_OVERHEAT_PROTECTION: Final = True
# TOS's own overheat warning threshold (frontend string sot_temperatureHeight).
DEFAULT_OVERHEAT_CELSIUS: Final = 55.0
