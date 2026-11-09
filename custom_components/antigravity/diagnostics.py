"""Diagnostics with credentials and account identifiers redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import AntigravityConfigEntry
from .const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PROJECT_ID, CONF_REFRESH_TOKEN

TO_REDACT = {CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_EMAIL, CONF_PROJECT_ID, "title", "unique_id"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AntigravityConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    catalog = data.catalog.data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "catalog": {
            "models": {m.id: list(m.efforts) for m in catalog.models} if catalog else None,
            "default_model": catalog.default_model if catalog else None,
            "image_models": list(catalog.image_models) if catalog else None,
        },
        "quota": [
            {"key": w.key, "window": w.window, "remaining_percent": w.remaining_percent, "reset_at": str(w.reset_at)}
            for w in data.quota.data or []
        ],
    }
