"""Config flow for the TerraMaster NAS integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_OVERHEAT_CELSIUS,
    CONF_OVERHEAT_PROTECTION,
    CONF_SCAN_INTERVAL,
    DEFAULT_OVERHEAT_CELSIUS,
    DEFAULT_OVERHEAT_PROTECTION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .tos import DEFAULT_PORT, TosAuthError, TosClient, TosError

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): cv.string, vol.Required(CONF_PASSWORD): cv.string}
)


async def _validate(data: Mapping[str, Any]) -> str:
    """Log in once and return a title. Raises on failure."""
    client = TosClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
    )
    try:
        await client.login()
        overview = (await client.get("/disk/GetOverview")).get("data") or {}
    finally:
        await client.close()

    name = overview.get("device_name") or "TerraMaster"
    model = overview.get("model")
    return f"{name} ({model})" if model else name


class TerraMasterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup and reauthentication."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            try:
                title = await _validate(user_input)
            except TosAuthError:
                errors["base"] = "invalid_auth"
            except TosError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - surface anything else as unknown
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the NAS starts rejecting the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            try:
                await _validate({**entry.data, **user_input})
            except TosAuthError:
                errors["base"] = "invalid_auth"
            except TosError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return TerraMasterOptionsFlow()


class TerraMasterOptionsFlow(OptionsFlow):
    """Poll interval and overheat protection."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)),
                vol.Required(
                    CONF_OVERHEAT_PROTECTION,
                    default=options.get(
                        CONF_OVERHEAT_PROTECTION, DEFAULT_OVERHEAT_PROTECTION
                    ),
                ): cv.boolean,
                vol.Required(
                    CONF_OVERHEAT_CELSIUS,
                    default=options.get(CONF_OVERHEAT_CELSIUS, DEFAULT_OVERHEAT_CELSIUS),
                ): vol.All(vol.Coerce(float), vol.Range(min=40, max=70)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
