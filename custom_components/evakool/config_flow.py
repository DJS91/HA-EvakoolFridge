"""Bluetooth discovery, manual device selection and polling options."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    CONF_KEEP_CONNECTED,
    CONF_SCAN_INTERVAL,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .protocol import SERVICE_UUID, matches_name


def is_fridge(info: BluetoothServiceInfoBleak) -> bool:
    return SERVICE_UUID in info.service_uuids or matches_name(info.name)


def _title(info: BluetoothServiceInfoBleak) -> str:
    return info.name if info.name and info.name != info.address else f"EVAKOOL {info.address}"


class EvakoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per fridge, keyed by Bluetooth address."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EvakoolOptionsFlow:
        return EvakoolOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not is_fridge(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery is not None
        title = _title(self._discovery)
        if user_input is not None:
            return self.async_create_entry(
                title=title, data={CONF_ADDRESS: self._discovery.address}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm", description_placeholders={"name": title}
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(self._discovered[address]), data={CONF_ADDRESS: address}
            )

        configured = self._async_current_ids(include_ignore=False)
        self._discovered = {
            info.address: info
            for info in async_discovered_service_info(self.hass, connectable=True)
            if info.address not in configured and is_fridge(info)
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_ADDRESS): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=address, label=f"{_title(info)} ({address})")
                                for address, info in self._discovered.items()
                            ]
                        )
                    )
                }
            ),
        )


class EvakoolOptionsFlow(OptionsFlowWithReload):
    """Polling cadence and whether to hold the single BLE connection between polls."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_KEEP_CONNECTED: user_input[CONF_KEEP_CONNECTED],
                }
            )
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    probatio.Required(
                        CONF_KEEP_CONNECTED,
                        default=options.get(CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED),
                    ): BooleanSelector(),
                }
            ),
        )
