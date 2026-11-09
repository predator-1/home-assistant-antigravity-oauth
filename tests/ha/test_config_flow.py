from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.antigravity.api.auth import Eligibility
from custom_components.antigravity.api.errors import AuthError, NotEligibleError
from custom_components.antigravity.const import (
    CONF_ACCESS_TOKEN,
    CONF_PROJECT_ID,
    CONF_REDIRECT_URL,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

from .conftest import EMAIL


def redirect_for(result) -> str:
    """Build the URL Google would redirect to for this flow's state."""
    auth_url = result["description_placeholders"]["auth_url"]
    state = auth_url.split("state=")[1].split("&")[0]
    return f"http://localhost:51121/oauth-callback?state={state}&code=4/abc&scope=x"


async def start(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "authorize"
    assert result["description_placeholders"]["auth_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    return result


async def test_sign_in_creates_entry(hass, mock_sign_in):
    exchange, _ = mock_sign_in
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_for(result)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["result"].unique_id == EMAIL
    data = result["data"]
    assert data[CONF_ACCESS_TOKEN] == "access-2"
    assert data[CONF_REFRESH_TOKEN] == "refresh-2"
    assert data[CONF_PROJECT_ID] == "proj-1"
    assert exchange.await_args.args[2] == "4/abc"
    subentries = {s.subentry_type: s for s in result["result"].subentries.values()}
    assert set(subentries) == {"conversation", "ai_task_data", "stt"}
    agent = subentries["conversation"]
    assert agent.data["chat_model"] == "gemini-3.5-flash-lite"
    assert agent.data["web_search"] is True
    assert agent.data["llm_hass_api"] == ["assist"]
    assert subentries["ai_task_data"].data["web_search"] is False
    assert subentries["stt"].data["chat_model"] == "gemini-3.5-flash-lite"


async def test_state_mismatch_shows_error_and_new_url(hass, mock_sign_in):
    result = await start(hass)
    first_url = result["description_placeholders"]["auth_url"]
    stale = "http://localhost:51121/oauth-callback?state=other&code=4/abc"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_REDIRECT_URL: stale})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert result["description_placeholders"]["auth_url"] != first_url
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_for(result)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [(AuthError("bad"), "invalid_auth"), (aiohttp.ClientError(), "cannot_connect"), (ValueError(), "unknown")],
)
async def test_exchange_errors(hass, mock_sign_in, side_effect, error):
    exchange, _ = mock_sign_in
    exchange.side_effect = side_effect
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_for(result)}
    )
    assert result["errors"] == {"base": error}


async def test_not_eligible(hass, mock_sign_in):
    mock_sign_in[1].side_effect = NotEligibleError()
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_for(result)}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_eligible"


async def test_already_configured(hass, config_entry, mock_sign_in):
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_for(result)}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass, config_entry, mock_sign_in, mock_client):
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "authorize"
    with patch("homeassistant.config_entries.ConfigEntries.async_schedule_reload") as reload:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_REDIRECT_URL: redirect_for(result)}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_REFRESH_TOKEN] == "refresh-2"
    reload.assert_called_once_with(config_entry.entry_id)


async def test_reauth_wrong_account(hass, config_entry, mock_sign_in):
    mock_sign_in[1].return_value = Eligibility(project_id="p2", email="other@example.com", tier=None)
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_for(result)}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_REFRESH_TOKEN] == "refresh-1"


async def test_paste_bare_code(hass, mock_sign_in):
    with patch("custom_components.antigravity.api.auth.exchange_code", new=AsyncMock(side_effect=AuthError("x"))):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_REDIRECT_URL: "4/bare"})
    assert result["errors"] == {"base": "invalid_auth"}
