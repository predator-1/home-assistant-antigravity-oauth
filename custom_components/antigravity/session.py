"""Access tokens for a config entry: refresh before expiry and persist to the entry."""

from __future__ import annotations

import asyncio
import time

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import auth
from .api.errors import InvalidGrantError
from .const import CONF_ACCESS_TOKEN, CONF_EXPIRES_AT, CONF_REFRESH_TOKEN

REFRESH_MARGIN = 120
"""Seconds before expiry at which the token is refreshed."""


class TokenManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession) -> None:
        self._hass = hass
        self._entry = entry
        self._session = session
        self._lock = asyncio.Lock()

    async def async_get_token(self, force: bool = False) -> str:
        """Return a valid access token. `force` refreshes even if not yet expiring (after a 401)."""
        async with self._lock:
            data = self._entry.data
            if not force and data[CONF_EXPIRES_AT] - time.time() > REFRESH_MARGIN:
                return data[CONF_ACCESS_TOKEN]
            try:
                tokens = await auth.refresh(self._session, data[CONF_REFRESH_TOKEN])
            except InvalidGrantError:
                self._entry.async_start_reauth(self._hass)
                raise
            self._hass.config_entries.async_update_entry(
                self._entry,
                data={
                    **data,
                    CONF_ACCESS_TOKEN: tokens.access_token,
                    CONF_REFRESH_TOKEN: tokens.refresh_token,
                    CONF_EXPIRES_AT: time.time() + tokens.expires_in,
                },
            )
            return tokens.access_token
