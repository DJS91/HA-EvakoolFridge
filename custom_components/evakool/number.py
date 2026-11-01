"""Left/right compartment target temperatures."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvakoolConfigEntry
from .const import COMPARTMENTS
from .entity import EvakoolEntity
from .protocol import target_range


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvakoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        EvakoolTargetNumber(coordinator, entry, compartment) for compartment in COMPARTMENTS
    )


class EvakoolTargetNumber(EvakoolEntity, NumberEntity):
    """Setpoint in the fridge's own units, confirmed by the fridge before it is shown."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    def __init__(self, coordinator, entry, compartment: int) -> None:
        super().__init__(coordinator, entry, f"{COMPARTMENTS[compartment]}_target")
        self._compartment = compartment

    @property
    def _celsius(self) -> bool:
        return self.coordinator.data is None or self.coordinator.data.celsius

    @property
    def native_value(self) -> int | None:
        data = self.coordinator.data
        return None if data is None else data.target(self._compartment)

    @property
    def native_unit_of_measurement(self) -> str:
        return self.temperature_unit

    @property
    def native_min_value(self) -> float:
        return target_range(self._celsius)[0]

    @property
    def native_max_value(self) -> float:
        return target_range(self._celsius)[1]

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_temperature(self._compartment, round(value))
