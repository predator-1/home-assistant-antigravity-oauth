"""Quota sensors: remaining percent and reset time per usage window."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AntigravityConfigEntry
from .api.quota import QuotaWindow
from .coordinator import QuotaCoordinator
from .entity import account_device

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class QuotaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[QuotaWindow], int | datetime | None]


SENSORS = (
    QuotaSensorDescription(
        key="remaining",
        translation_key="remaining",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w: w.remaining_percent,
    ),
    QuotaSensorDescription(
        key="reset",
        translation_key="reset",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda w: w.reset_at,
    ),
)

WINDOW_NAMES = {"weekly": "weekly", "5h": "5-hour"}


async def async_setup_entry(
    hass: HomeAssistant, entry: AntigravityConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.quota
    async_add_entities(
        QuotaSensor(coordinator, entry, window, description) for window in coordinator.data for description in SENSORS
    )


class QuotaSensor(CoordinatorEntity[QuotaCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: QuotaSensorDescription

    def __init__(
        self,
        coordinator: QuotaCoordinator,
        entry: AntigravityConfigEntry,
        window: QuotaWindow,
        description: QuotaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._key = window.key
        self._attr_unique_id = f"{entry.entry_id}_{window.key}_{description.key}"
        self._attr_device_info = account_device(entry)
        self._attr_translation_placeholders = {"group": window.group, "window": WINDOW_NAMES[window.window]}

    @property
    def _window(self) -> QuotaWindow | None:
        return next((w for w in self.coordinator.data or [] if w.key == self._key), None)

    @property
    def available(self) -> bool:
        return super().available and self._window is not None

    @property
    def native_value(self) -> int | datetime | None:
        window = self._window
        return self.entity_description.value_fn(window) if window else None
