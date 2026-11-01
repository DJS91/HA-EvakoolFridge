"""Unofficial EVAKOOL Down Under / CoolRide Bluetooth fridge integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .client import EvakoolClient
from .const import (
    CONF_KEEP_CONNECTED,
    CONF_SCAN_INTERVAL,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import EvakoolCoordinator

type EvakoolConfigEntry = ConfigEntry[EvakoolCoordinator]

PLATFORMS = [Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: EvakoolConfigEntry) -> bool:
    """Connect through any HA Bluetooth adapter or proxy that can reach the fridge."""
    address: str = entry.data[CONF_ADDRESS]
    ble_device = bluetooth.async_ble_device_from_address(hass, address.upper(), connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(f"No connectable Bluetooth adapter can see {address}")

    client = EvakoolClient(
        ble_device,
        keep_connected=entry.options.get(CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED),
    )
    coordinator = EvakoolCoordinator(
        hass, entry, client, entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    client.on_status = coordinator.async_pushed_status
    client.on_error = coordinator.async_pushed_error

    @callback
    def _advertisement(
        service_info: bluetooth.BluetoothServiceInfoBleak, _change: bluetooth.BluetoothChange
    ) -> None:
        client.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _advertisement,
            bluetooth.BluetoothCallbackMatcher(address=address.upper(), connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    async def _stop(_event: Event) -> None:
        await client.async_close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))

    entry.runtime_data = coordinator
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await client.async_close()
        raise
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvakoolConfigEntry) -> bool:
    """Release the BLE connection so another client (e.g. the phone app) can connect."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    return unloaded
