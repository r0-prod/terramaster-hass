"""The TerraMaster NAS integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import TerraMasterCoordinator
from .tos import TosAuthError, TosClient, TosError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
]

type TerraMasterConfigEntry = ConfigEntry[TerraMasterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TerraMasterConfigEntry) -> bool:
    """Set up TerraMaster NAS from a config entry."""
    # A dedicated session: the client needs an unsafe cookie jar to accept
    # cookies from a bare IP address, which HA's shared session does not use.
    client = TosClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, 8181),
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    try:
        await client.login()
    except TosAuthError as err:
        await client.close()
        raise ConfigEntryAuthFailed(str(err)) from err
    except TosError as err:
        await client.close()
        raise ConfigEntryNotReady(f"cannot reach the NAS: {err}") from err

    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    coordinator = TerraMasterCoordinator(hass, entry, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TerraMasterConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.close()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: TerraMasterConfigEntry) -> None:
    """Reload when the options (poll interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
