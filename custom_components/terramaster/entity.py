"""Shared entity bases for the TerraMaster integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import TerraMasterCoordinator
from .tos.models import Disk


class TerraMasterEntity(CoordinatorEntity[TerraMasterCoordinator]):
    """Base entity carrying the shared device registry entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TerraMasterCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.entry.entry_id)},
            manufacturer=MANUFACTURER,
            name=(data.device_name if data else None) or "TerraMaster NAS",
            model=data.model if data else None,
            configuration_url=self.coordinator.client.base_url,
        )


class TerraMasterDiskEntity(TerraMasterEntity):
    """Base for entities bound to one physical drive.

    The drive is looked up by slot on each read, while the unique ID is built
    from the serial so an entity follows its drive if the bays are rearranged.
    """

    def __init__(
        self, coordinator: TerraMasterCoordinator, disk: Disk, suffix: str
    ) -> None:
        super().__init__(coordinator, f"disk_{disk.unique_key}_{suffix}")
        self._slot = disk.slot
        self._attr_translation_placeholders = {"disk_name": disk.name}

    @property
    def _disk(self) -> Disk | None:
        return next(
            (d for d in self.coordinator.data.disks if d.slot == self._slot), None
        )
