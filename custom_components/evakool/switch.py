"""Fridge power and the Home Assistant Bluetooth connection toggle."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvakoolConfigEntry
from .entity import EvakoolEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvakoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EvakoolPowerSwitch(coordinator, entry, "power"),
            EvakoolConnectionSwitch(coordinator, entry, "connection"),
        ]
    )


class EvakoolPowerSwitch(EvakoolEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)


class EvakoolConnectionSwitch(EvakoolEntity, SwitchEntity):
    """Off releases the fridge's single BLE connection so another app can connect."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.connection_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_connection_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_connection_enabled(False)
