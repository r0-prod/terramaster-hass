"""Fan mode select for the TerraMaster NAS."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TerraMasterConfigEntry
from .const import DOMAIN, FAN_LEVEL_TO_MODE, FAN_MODE_AUTO, FAN_MODE_TO_SETTING, FAN_MODES
from .coordinator import TerraMasterCoordinator
from .entity import TerraMasterEntity
from .tos import TosError

# Writes are serialised by the client; one entity, nothing to throttle.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerraMasterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TerraMasterFanMode(entry.runtime_data)])


class TerraMasterFanMode(TerraMasterEntity, SelectEntity):
    """The four fan modes TOS exposes: automatic, low, medium and full."""

    _attr_translation_key = "fan_mode"
    _attr_options = FAN_MODES

    def __init__(self, coordinator: TerraMasterCoordinator) -> None:
        super().__init__(coordinator, "fan_mode")

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        # In automatic mode TOS reports the level it is currently driving rather
        # than -1, so is_auto has to be trusted ahead of the level.
        if data.fan_is_auto:
            return FAN_MODE_AUTO
        if data.fan_level is None:
            return None
        # An unrecognised level means something set the fan outside the presets;
        # report unknown rather than silently rounding to the nearest one.
        return FAN_LEVEL_TO_MODE.get(data.fan_level)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {
            "fan_level": self.coordinator.data.fan_level,
            "is_auto": self.coordinator.data.fan_is_auto,
        }

    async def async_select_option(self, option: str) -> None:
        is_auto, level = FAN_MODE_TO_SETTING[option]
        try:
            await self.coordinator.async_set_hardware(
                {"fan": {"is_auto": is_auto, "level": level}}
            )
        except TosError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_fan_mode_failed",
                translation_placeholders={"error": str(err)},
            ) from err
