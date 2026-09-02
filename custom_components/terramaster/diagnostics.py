"""Diagnostics support for the TerraMaster NAS integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import TerraMasterConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TerraMasterConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": async_redact_data(
            {
                "fan_is_auto": data.fan_is_auto,
                "fan_level": data.fan_level,
                "fan_rpm": data.fan_rpm,
                "cpu_temperature": data.cpu_temperature,
                "system_temperature": data.system_temperature,
                "model": data.model,
                "processor": data.processor,
                "disks": [asdict(d) for d in data.disks],
                "volumes": [asdict(v) for v in data.volumes],
                "pools": [asdict(p) for p in data.pools],
            },
            TO_REDACT,
        ),
    }
