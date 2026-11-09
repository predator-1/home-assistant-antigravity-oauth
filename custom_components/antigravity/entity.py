"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import CONF_TIER, DEFAULT_TITLE, DOMAIN


def account_device(entry: ConfigEntry) -> DeviceInfo:
    """The service device for the signed-in account (quota sensors live here)."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=DEFAULT_TITLE,
        manufacturer="Google",
        model=entry.data.get(CONF_TIER) or "Antigravity subscription",
        entry_type=DeviceEntryType.SERVICE,
    )
