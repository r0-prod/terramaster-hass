"""Config flow tests (quality scale: config-flow-test-coverage)."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.terramaster.const import (
    CONF_OVERHEAT_CELSIUS,
    CONF_OVERHEAT_PROTECTION,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.terramaster.tos import TosAuthError, TosError

USER_INPUT = {
    CONF_HOST: "10.0.0.9",
    CONF_PORT: 8181,
    CONF_USERNAME: "tester",
    CONF_PASSWORD: "secret",
}
OVERVIEW = {"data": {"device_name": "TNAS", "model": "F4-425"}}


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Stop a created/reloaded entry from really connecting to the fake host."""
    with patch(
        "custom_components.terramaster.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get.return_value = OVERVIEW
    with patch(
        "custom_components.terramaster.config_flow.TosClient", return_value=client
    ):
        yield client


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_client) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Title is built from the NAS's own reported name and model.
    assert result["title"] == "TNAS (F4-425)"
    assert result["data"] == USER_INPUT
    mock_client.login.assert_awaited()


@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        (TosAuthError("nope"), "invalid_auth"),
        (TosError("unreachable"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant, mock_client, side_effect, expected
) -> None:
    mock_client.login.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    # The form stays usable once the problem is fixed.
    mock_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_host_is_rejected(hass: HomeAssistant, mock_client) -> None:
    MockConfigEntry(domain=DOMAIN, data=USER_INPUT).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_credentials(hass: HomeAssistant, mock_client) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["host"] == "10.0.0.9"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "tester", CONF_PASSWORD: "new-secret"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-secret"
    # Host and port are preserved; only the credentials change.
    assert entry.data[CONF_HOST] == "10.0.0.9"
    assert entry.data[CONF_PORT] == 8181


async def test_reauth_rejects_bad_credentials(hass: HomeAssistant, mock_client) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)
    mock_client.login.side_effect = TosAuthError("still wrong")

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "tester", CONF_PASSWORD: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PASSWORD] == "secret"  # unchanged


async def test_options_flow_saves(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 120,
            CONF_OVERHEAT_PROTECTION: False,
            CONF_OVERHEAT_CELSIUS: 60.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 120
    assert entry.options[CONF_OVERHEAT_PROTECTION] is False
    assert entry.options[CONF_OVERHEAT_CELSIUS] == 60.0
