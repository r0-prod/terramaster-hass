"""Binary sensors for the TerraMaster NAS."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TerraMasterConfigEntry
from .coordinator import TerraMasterCoordinator
from .entity import TerraMasterDiskEntity
from .tos.models import Disk

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerraMasterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        TerraMasterDiskProblem(coordinator, disk) for disk in coordinator.data.disks
    )


class TerraMasterDiskProblem(TerraMasterDiskEntity, BinarySensorEntity):
    """On when TOS reports a non-zero status for the drive."""

    _attr_translation_key = "disk_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: TerraMasterCoordinator, disk: Disk) -> None:
        super().__init__(coordinator, disk, "problem")

    @property
    def is_on(self) -> bool | None:
        if (disk := self._disk) is None or disk.healthy is None:
            return None
        return not disk.healthy
