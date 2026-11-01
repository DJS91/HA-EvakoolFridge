"""Eco / Max compressor mode control."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvakoolConfigEntry
from .entity import EvakoolEntity
from .sensor import MODE_OPTIONS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvakoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([EvakoolModeSelect(entry.runtime_data, entry, "mode")])


class EvakoolModeSelect(EvakoolEntity, SelectEntity):
    _attr_options = MODE_OPTIONS

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        return None if data is None else ("max" if data.max_mode else "eco")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(option == "max")
