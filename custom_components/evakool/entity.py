"""Shared entity base."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS, UnitOfTemperature
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EvakoolConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import EvakoolCoordinator


class EvakoolEntity(CoordinatorEntity[EvakoolCoordinator]):
    """One fridge = one device; entities are unique per address and key."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EvakoolCoordinator, entry: EvakoolConfigEntry, key: str):
        super().__init__(coordinator)
        address: str = entry.data[CONF_ADDRESS]
        self._attr_translation_key = key
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=entry.title,
        )

    @property
    def available(self) -> bool:
        return (
            self.coordinator.connection_enabled
            and super().available
            and self.coordinator.data is not None
        )

    @property
    def temperature_unit(self) -> str:
        data = self.coordinator.data
        return (
            UnitOfTemperature.FAHRENHEIT
            if data is not None and not data.celsius
            else UnitOfTemperature.CELSIUS
        )
