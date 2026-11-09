"""Config flow: Google sign-in by pasting the redirect URL (docs/auth.md)."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

import aiohttp
import probatio
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_LLM_HASS_API, CONF_NAME, CONF_PROMPT
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
    TextSelector,
)

from .api import auth
from .api.errors import AuthError, NotEligibleError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CHAT_MODEL,
    CONF_EMAIL,
    CONF_EXPIRES_AT,
    CONF_PROJECT_ID,
    CONF_REASONING_EFFORT,
    CONF_REDIRECT_URL,
    CONF_REFRESH_TOKEN,
    CONF_TIER,
    CONF_WEB_SEARCH,
    DEFAULT_CONVERSATION_NAME,
    DEFAULT_TITLE,
    DOMAIN,
    REASONING_EFFORTS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_REASONING_EFFORT,
    REDIRECT_URI,
    SUBENTRY_CONVERSATION,
)

_LOGGER = logging.getLogger(__name__)

AUTHORIZE_SCHEMA = probatio.Schema({probatio.Required(CONF_REDIRECT_URL): TextSelector()})

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_CHAT_MODEL: RECOMMENDED_CHAT_MODEL,
    CONF_REASONING_EFFORT: RECOMMENDED_REASONING_EFFORT,
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
    CONF_WEB_SEARCH: True,
}


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
                return self.async_create_entry(
                    title=eligibility.email or DEFAULT_TITLE,
                    data=data,
                    subentries=[
                        {
                            "subentry_type": SUBENTRY_CONVERSATION,
                            "data": RECOMMENDED_CONVERSATION_OPTIONS,
                            "title": DEFAULT_CONVERSATION_NAME,
                            "unique_id": None,
                        }
                    ],
                )

        return self.async_show_form(
            step_id="authorize",
            data_schema=AUTHORIZE_SCHEMA,
            description_placeholders={"auth_url": self._pkce.authorize_url, "redirect_uri": REDIRECT_URI},
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_CONVERSATION: AgentSubentryFlow}


class AgentSubentryFlow(ConfigSubentryFlow):
    """Create or reconfigure an agent. Models come from the loaded entry's catalog."""

    @property
    def _is_new(self) -> bool:
        return self.source == "user"

    async def async_step_set_options(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        if user_input is not None:
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)
            if self._is_new:
                return self.async_create_entry(title=user_input.pop(CONF_NAME), data=user_input)
            # The entry's update listener reloads when subentry data changes.
            return self.async_update_and_abort(entry, self._get_reconfigure_subentry(), data=user_input)

        options = (
            dict(RECOMMENDED_CONVERSATION_OPTIONS) if self._is_new else dict(self._get_reconfigure_subentry().data)
        )
        return self.async_show_form(step_id="set_options", data_schema=probatio.Schema(self._schema(entry, options)))

    async_step_user = async_step_set_options
    async_step_reconfigure = async_step_set_options

    def _schema(self, entry: ConfigEntry, options: dict[str, Any]) -> dict[Any, Any]:
        catalog = entry.runtime_data.catalog.data
        models = [SelectOptionDict(value=m.id, label=m.name) for m in catalog.models]
        known_apis = {api.id: api.name for api in llm.async_get_apis(self.hass)}
        selected_apis = options.get(CONF_LLM_HASS_API) or []
        if isinstance(selected_apis, str):
            selected_apis = [selected_apis]
        schema: dict[Any, Any] = {}
        if self._is_new:
            # pylint: disable-next=home-assistant-config-flow-name-field
            schema[probatio.Required(CONF_NAME, default=DEFAULT_CONVERSATION_NAME)] = str
        schema.update(
            {
                probatio.Required(
                    CONF_CHAT_MODEL, default=options.get(CONF_CHAT_MODEL, RECOMMENDED_CHAT_MODEL)
                ): SelectSelector(SelectSelectorConfig(options=models, mode=SelectSelectorMode.DROPDOWN)),
                probatio.Required(
                    CONF_REASONING_EFFORT, default=options.get(CONF_REASONING_EFFORT, RECOMMENDED_REASONING_EFFORT)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(REASONING_EFFORTS),
                        translation_key=CONF_REASONING_EFFORT,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                probatio.Optional(
                    CONF_PROMPT,
                    description={"suggested_value": options.get(CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT)},
                ): TemplateSelector(),
                probatio.Optional(
                    CONF_LLM_HASS_API,
                    description={"suggested_value": [a for a in selected_apis if a in known_apis]},
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=k, label=v) for k, v in known_apis.items()], multiple=True
                    )
                ),
                probatio.Required(CONF_WEB_SEARCH, default=options.get(CONF_WEB_SEARCH, True)): bool,
            }
        )
        return schema
