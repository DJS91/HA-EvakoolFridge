"""Fridge power."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvakoolConfigEntry
from .entity import EvakoolEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvakoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([EvakoolPowerSwitch(entry.runtime_data, entry, "power")])


class EvakoolPowerSwitch(EvakoolEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)
