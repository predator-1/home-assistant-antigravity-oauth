import contextlib
import time
from unittest.mock import AsyncMock, patch

import aiohttp
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.antigravity.api.auth import Tokens
from custom_components.antigravity.api.errors import AuthError, InvalidGrantError
from custom_components.antigravity.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_TIER,
    DOMAIN,
)
from custom_components.antigravity.diagnostics import async_get_config_entry_diagnostics


async def test_setup_creates_quota_sensors(hass, config_entry, mock_client):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED

    remaining = hass.states.get("sensor.antigravity_gemini_models_weekly_remaining")
    assert remaining.state == "68"
    assert remaining.attributes["unit_of_measurement"] == "%"
    assert hass.states.get("sensor.antigravity_claude_and_gpt_models_5_hour_remaining").state == "100"
    reset = hass.states.get("sensor.antigravity_gemini_4_argon_weekly_reset")
    assert reset.state == "2026-11-14T18:16:10+00:00"
    entities = er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
    assert len(entities) == 10

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_refreshes_plan(hass, config_entry, mock_client):
    assert config_entry.data[CONF_TIER] == "free-tier"
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.data[CONF_TIER] == "Google AI Pro"
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert [d.model for d in devices if (DOMAIN, config_entry.entry_id) in d.identifiers] == ["Google AI Pro"]


async def test_setup_plan_error_keeps_stored_plan(hass, config_entry, mock_client):
    with patch(
        "custom_components.antigravity.api.client.AntigravityClient.fetch_plan",
        new=AsyncMock(side_effect=aiohttp.ClientError()),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_TIER] == "free-tier"


async def test_setup_auth_error_starts_reauth(hass, config_entry, mock_client):
    mock_client[0].side_effect = AuthError("401")
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_setup_network_error_retries(hass, config_entry, mock_client):
    mock_client[0].side_effect = aiohttp.ClientError()
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_expired_token_refreshed_and_persisted_without_reload(hass, config_entry, mock_client):
    hass.config_entries.async_update_entry(config_entry, data={**config_entry.data, CONF_EXPIRES_AT: time.time()})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    client = config_entry.runtime_data.client
    with (
        patch(
            "custom_components.antigravity.api.auth.refresh",
            new=AsyncMock(return_value=Tokens("access-2", "refresh-2", 3599)),
        ) as refresh,
        patch.object(hass.config_entries, "async_reload") as reload,
    ):
        assert await client._tokens(False) == "access-2"
        assert await client._tokens(False) == "access-2"
        await hass.async_block_till_done()
    refresh.assert_awaited_once()
    assert config_entry.data[CONF_ACCESS_TOKEN] == "access-2"
    assert config_entry.data[CONF_REFRESH_TOKEN] == "refresh-2"
    assert config_entry.data[CONF_EXPIRES_AT] > time.time() + 3000
    reload.assert_not_called()


async def test_revoked_refresh_token_starts_reauth(hass, config_entry, mock_client):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    client = config_entry.runtime_data.client
    with (
        patch("custom_components.antigravity.api.auth.refresh", new=AsyncMock(side_effect=InvalidGrantError("x"))),
        contextlib.suppress(InvalidGrantError),
    ):
        await client._tokens(True)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_diagnostics_redacts(hass, config_entry, mock_client):
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    text = str(diagnostics)
    for secret in ("access-1", "refresh-1", "proj-1", "user@example.com"):
        assert secret not in text
    assert diagnostics["catalog"]["default_model"] == "gemini-4-argon"
    assert len(diagnostics["quota"]) == 5
