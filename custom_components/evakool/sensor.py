"""Compartment temperatures, supply voltage and compressor mode."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvakoolConfigEntry
from .entity import EvakoolEntity
from .protocol import FridgeStatus

MODE_OPTIONS = ["eco", "max"]


@dataclass(frozen=True, kw_only=True)
class EvakoolSensorDescription(SensorEntityDescription):
    value: Callable[[FridgeStatus], float | int | str]
    temperature: bool = False


SENSORS = (
    EvakoolSensorDescription(
        key="left_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.left,
        temperature=True,
    ),
    EvakoolSensorDescription(
        key="right_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s.right,
        temperature=True,
    ),
    EvakoolSensorDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        value=lambda s: s.voltage,
    ),
    EvakoolSensorDescription(
        key="compressor_mode",
        device_class=SensorDeviceClass.ENUM,
        options=MODE_OPTIONS,
        value=lambda s: "max" if s.max_mode else "eco",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvakoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(EvakoolSensor(coordinator, entry, d) for d in SENSORS)


class EvakoolSensor(EvakoolEntity, SensorEntity):
    entity_description: EvakoolSensorDescription

    def __init__(self, coordinator, entry, description: EvakoolSensorDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | None:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value(data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.temperature:
            return self.temperature_unit
        return self.entity_description.native_unit_of_measurement
