"""Config flow: Google sign-in by pasting the redirect URL (docs/auth.md)."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

import aiohttp
import probatio
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector

from .api import auth
from .api.errors import AuthError, NotEligibleError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EMAIL,
    CONF_EXPIRES_AT,
    CONF_PROJECT_ID,
    CONF_REDIRECT_URL,
    CONF_REFRESH_TOKEN,
    CONF_TIER,
    DEFAULT_TITLE,
    DOMAIN,
    REDIRECT_URI,
)

_LOGGER = logging.getLogger(__name__)

AUTHORIZE_SCHEMA = probatio.Schema({probatio.Required(CONF_REDIRECT_URL): TextSelector()})


class AntigravityConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    _pkce: auth.PkceSession | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_authorize()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", description_placeholders={"name": self._get_reauth_entry().title}
            )
        return await self.async_step_authorize()

    async def async_step_authorize(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if self._pkce is None:
            self._pkce = auth.new_pkce_session()
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                code = auth.parse_callback_input(user_input[CONF_REDIRECT_URL], self._pkce.state)
                tokens = await auth.exchange_code(session, self._pkce, code)
                eligibility = await auth.check_eligibility(session, tokens.access_token)
            except NotEligibleError:
                return self.async_abort(reason="not_eligible")
            except AuthError as err:
                _LOGGER.debug("Sign-in failed: %s", err)
                errors["base"] = "invalid_auth"
                self._pkce = auth.new_pkce_session()
            except aiohttp.ClientError, TimeoutError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during sign-in")
                errors["base"] = "unknown"
            else:
                data = {
                    CONF_ACCESS_TOKEN: tokens.access_token,
                    CONF_REFRESH_TOKEN: tokens.refresh_token,
                    CONF_EXPIRES_AT: time.time() + tokens.expires_in,
                    CONF_PROJECT_ID: eligibility.project_id,
                    CONF_EMAIL: eligibility.email,
                    CONF_TIER: eligibility.tier,
                }
                await self.async_set_unique_id((eligibility.email or eligibility.project_id).lower())
                if self.source == SOURCE_REAUTH:
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    entry = self._get_reauth_entry()
                    # The entry has an update listener, so reload explicitly instead of
                    # async_update_reload_and_abort.
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=eligibility.email or DEFAULT_TITLE, data=data)

        return self.async_show_form(
            step_id="authorize",
            data_schema=AUTHORIZE_SCHEMA,
            description_placeholders={"auth_url": self._pkce.authorize_url, "redirect_uri": REDIRECT_URI},
            errors=errors,
        )
