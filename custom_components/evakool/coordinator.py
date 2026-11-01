"""Polling plus pushed status updates for one fridge."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import EvakoolClient, EvakoolError
from .const import DOMAIN
from .protocol import FridgeStatus

if TYPE_CHECKING:
    from . import EvakoolConfigEntry

_LOGGER = logging.getLogger(__name__)


class EvakoolCoordinator(DataUpdateCoordinator[FridgeStatus]):
    """Owns the client; entities read ``data`` and call the command helpers."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EvakoolConfigEntry,
        client: EvakoolClient,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {client.address}",
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> FridgeStatus:
        try:
            return await self.client.async_status()
        except EvakoolError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def async_pushed_status(self, status: FridgeStatus) -> None:
        """Publish unsolicited/extra frames received between polls."""
        if self.data != status or not self.last_update_success:
            self.async_set_updated_data(status)

    @callback
    def async_pushed_error(self, err: EvakoolError) -> None:
        """Make entities unavailable now on an unsolicited fault, not at the next poll."""
        self.async_set_update_error(UpdateFailed(str(err)))

    async def async_set_temperature(self, compartment: int, temperature: int) -> None:
        await self._command(lambda: self.client.async_set_temperature(compartment, temperature))

    async def async_set_mode(self, max_mode: bool) -> None:
        await self._command(lambda: self.client.async_set_mode(max_mode))

    async def async_set_power(self, on: bool) -> None:
        await self._command(lambda: self.client.async_set_power(on))

    async def _command(self, send: Callable[[], Awaitable[FridgeStatus]]) -> None:
        try:
            status = await send()
        except EvakoolError as err:
            # Show the latest reading (or unavailability) rather than an optimistic value.
            await self.async_request_refresh()
            raise HomeAssistantError(str(err)) from err
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(status)
