"""Coordinators for the model catalog and the subscription quota."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.catalog import Catalog
from .api.client import AntigravityClient
from .api.errors import AntigravityError, AuthError
from .api.quota import QuotaWindow
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CATALOG_INTERVAL = timedelta(hours=6)
QUOTA_INTERVAL = timedelta(minutes=5)


class _AntigravityCoordinator[T](DataUpdateCoordinator[T]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        name: str,
        interval: timedelta,
        fetch: Callable[[], Awaitable[T]],
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=name, update_interval=interval)
        self._fetch = fetch

    async def _async_update_data(self) -> T:
        try:
            return await self._fetch()
        except AuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed", translation_placeholders={"error": str(err)}
            ) from err
        except (AntigravityError, aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="update_failed", translation_placeholders={"error": str(err)}
            ) from err


class CatalogCoordinator(_AntigravityCoordinator[Catalog]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AntigravityClient) -> None:
        super().__init__(hass, entry, "catalog", CATALOG_INTERVAL, client.fetch_catalog)


class QuotaCoordinator(_AntigravityCoordinator[list[QuotaWindow]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AntigravityClient) -> None:
        super().__init__(hass, entry, "quota", QUOTA_INTERVAL, client.fetch_quota)
