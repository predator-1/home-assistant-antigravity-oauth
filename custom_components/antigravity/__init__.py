"""The Antigravity integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.client import AntigravityClient
from .const import CONF_PROJECT_ID, DOMAIN
from .coordinator import CatalogCoordinator, QuotaCoordinator
from .session import TokenManager

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = (Platform.CONVERSATION, Platform.SENSOR)


@dataclass
class AntigravityData:
    client: AntigravityClient
    catalog: CatalogCoordinator
    quota: QuotaCoordinator
    subentries: dict[str, Any] = field(default_factory=dict)
    """Snapshot used to reload only when subentries change (token refreshes also update the entry)."""


type AntigravityConfigEntry = ConfigEntry[AntigravityData]


def _subentry_snapshot(entry: ConfigEntry) -> dict[str, Any]:
    return {sid: (sub.title, dict(sub.data)) for sid, sub in entry.subentries.items()}


async def async_setup_entry(hass: HomeAssistant, entry: AntigravityConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    tokens = TokenManager(hass, entry, session)
    client = AntigravityClient(session, tokens.async_get_token, entry.data[CONF_PROJECT_ID])
    catalog = CatalogCoordinator(hass, entry, client)
    quota = QuotaCoordinator(hass, entry, client)
    await catalog.async_config_entry_first_refresh()
    await quota.async_config_entry_first_refresh()
    entry.runtime_data = AntigravityData(client, catalog, quota, _subentry_snapshot(entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: AntigravityConfigEntry) -> None:
    if _subentry_snapshot(entry) != entry.runtime_data.subentries:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AntigravityConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
