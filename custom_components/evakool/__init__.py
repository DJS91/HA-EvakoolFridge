"""Unofficial EVAKOOL Down Under / CoolRide Bluetooth fridge integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .client import EvakoolClient
from .const import (
    CONF_CONNECTION_ENABLED,
    CONF_KEEP_CONNECTED,
    CONF_SCAN_INTERVAL,
    DEFAULT_CONNECTION_ENABLED,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import EvakoolCoordinator

type EvakoolConfigEntry = ConfigEntry[EvakoolCoordinator]

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: EvakoolConfigEntry) -> bool:
    """Connect through any HA Bluetooth adapter or proxy that can reach the fridge.

    Setup succeeds even when the fridge is out of range (or the connection is turned off)
    so the connection switch is always available; data entities stay unavailable until
    the fridge reports status.
    """
    address: str = entry.data[CONF_ADDRESS].upper()
    enabled = entry.data.get(CONF_CONNECTION_ENABLED, DEFAULT_CONNECTION_ENABLED)
    client = EvakoolClient(
        address,
        lambda: bluetooth.async_ble_device_from_address(hass, address, connectable=True),
        keep_connected=entry.options.get(CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED),
        closed=not enabled,
    )
    coordinator = EvakoolCoordinator(
        hass, entry, client, entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    client.on_status = coordinator.async_pushed_status
    client.on_error = coordinator.async_pushed_error
    client.on_connection = coordinator.async_connection_changed

    async def _stop(_event: Event) -> None:
        await client.async_close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))

    entry.runtime_data = coordinator
    if enabled:
        await coordinator.async_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvakoolConfigEntry) -> bool:
    """Release the BLE connection so another client (e.g. the phone app) can connect."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded
