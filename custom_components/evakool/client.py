"""Bleak connection to one fridge (no Home Assistant imports)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .protocol import (
    NOTIFY_UUID,
    STATUS_QUERY,
    WRITE_UUID,
    FrameBuffer,
    FridgeStatus,
    ProtocolError,
    is_fault,
    mode_command,
    parse_status,
    power_command,
    temperature_command,
)

_LOGGER = logging.getLogger(__name__)

WRITE_TIMEOUT = 4.0
STATUS_TIMEOUT = 10.0
CONFIRM_TIMEOUT = 10.0
REQUERY_INTERVAL = 2.0
QUIET_INTERVAL = 0.5


class EvakoolError(Exception):
    """Base error for fridge communication."""


class EvakoolConnectionError(EvakoolError):
    """The fridge could not be connected, or the link dropped."""


class EvakoolFault(EvakoolError):
    """The fridge replied with a ``/SEE/`` or ``/SCE/`` fault frame."""


class EvakoolNotConfirmed(EvakoolError):
    """A command was written but the fridge did not report the new value."""


class EvakoolClient:
    """Serializes queries/commands over one BLE connection."""

    def __init__(
        self,
        ble_device: BLEDevice,
        *,
        keep_connected: bool = True,
        on_status: Callable[[FridgeStatus], None] | None = None,
        on_error: Callable[[EvakoolError], None] | None = None,
    ) -> None:
        self._ble_device = ble_device
        self.keep_connected = keep_connected
        self.on_status = on_status
        # Faults/invalid frames that arrive while no request is waiting for status.
        self.on_error = on_error
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._operation: asyncio.Task | None = None
        self._closed = False
        self._frames = FrameBuffer()
        self._waiters: list[asyncio.Future[FridgeStatus]] = []
        self._quiet: asyncio.TimerHandle | None = None
        self.status: FridgeStatus | None = None
        self.last_frame: str | None = None

    @property
    def address(self) -> str:
        return self._ble_device.address

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Use the freshest path/adapter (or proxy) for the next connection."""
        self._ble_device = ble_device

    async def async_status(self) -> FridgeStatus:
        return await self._serialized(None, lambda _: True, STATUS_TIMEOUT)

    async def async_set_temperature(self, compartment: int, temperature: int) -> FridgeStatus:
        command = temperature_command(compartment, temperature)
        # Only accept a confirmation in the units the target was chosen in.
        celsius = self.status.celsius if self.status else None
        return await self._serialized(
            command,
            lambda s: (
                s.target(compartment) == temperature and (celsius is None or s.celsius == celsius)
            ),
            CONFIRM_TIMEOUT,
        )

    async def async_set_mode(self, max_mode: bool) -> FridgeStatus:
        return await self._serialized(
            mode_command(max_mode), lambda s: s.max_mode == max_mode, CONFIRM_TIMEOUT
        )

    async def async_set_power(self, on: bool) -> FridgeStatus:
        return await self._serialized(power_command(on), lambda s: s.on == on, CONFIRM_TIMEOUT)

    async def async_close(self) -> None:
        """Release the fridge for good, cancelling any in-flight connect/request."""
        self._closed = True
        operation = self._operation
        if operation is not None and operation is not asyncio.current_task():
            operation.cancel()
        async with self._lock:
            await self._disconnect()

    async def _serialized(
        self,
        command: str | None,
        confirmed: Callable[[FridgeStatus], bool],
        timeout: float,
    ) -> FridgeStatus:
        async with self._lock:
            if self._closed:
                raise EvakoolConnectionError("Connection closed")
            self._operation = asyncio.current_task()
            try:
                return await self._run(command, confirmed, timeout)
            finally:
                self._operation = None

    async def _run(
        self,
        command: str | None,
        confirmed: Callable[[FridgeStatus], bool],
        timeout: float,
    ) -> FridgeStatus:
        try:
            await self._ensure_connected()
            if command is not None:
                # Written exactly once: retries only repeat the status query.
                await self._write(command)
            return await self._await_status(confirmed, timeout, command is not None)
        except EvakoolNotConfirmed:
            raise
        except EvakoolError:
            await self._disconnect()
            raise
        finally:
            if not self.keep_connected:
                await self._disconnect()

    async def _await_status(
        self, confirmed: Callable[[FridgeStatus], bool], timeout: float, is_command: bool
    ) -> FridgeStatus:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last: FridgeStatus | None = None
        while (remaining := deadline - loop.time()) > 0:
            future: asyncio.Future[FridgeStatus] = loop.create_future()
            self._waiters.append(future)
            try:
                await self._write(STATUS_QUERY)
                last = await asyncio.wait_for(future, min(remaining, REQUERY_INTERVAL))
            except TimeoutError:
                continue
            finally:
                if future in self._waiters:
                    self._waiters.remove(future)
            if confirmed(last):
                return last
            await asyncio.sleep(min(REQUERY_INTERVAL, max(0.0, deadline - loop.time())))
        if is_command and last is not None:
            raise EvakoolNotConfirmed("The fridge did not confirm the change")
        raise EvakoolConnectionError("Timed out waiting for fridge status")

    async def _ensure_connected(self) -> None:
        if self.connected:
            return
        await self._disconnect()
        _LOGGER.debug("Connecting to %s", self.address)
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self._ble_device.name or self.address,
                disconnected_callback=self._on_disconnected,
                ble_device_callback=lambda: self._ble_device,
            )
        except (BleakError, TimeoutError) as err:
            raise EvakoolConnectionError(f"Could not connect: {err}") from err
        self._client = client
        self._frames.clear()
        try:
            write = client.services.get_characteristic(WRITE_UUID)
            notify = client.services.get_characteristic(NOTIFY_UUID)
            if (
                write is None
                or notify is None
                or "write-without-response" not in write.properties
                or "notify" not in notify.properties
            ):
                await client.clear_cache()
                raise EvakoolConnectionError("Device is not a compatible EVAKOOL fridge")
            await client.start_notify(notify, lambda _s, data: self._on_notify(client, data))
        except (BleakError, TimeoutError) as err:
            raise EvakoolConnectionError(f"Could not enable notifications: {err}") from err
        _LOGGER.debug("Connected to %s", self.address)

    async def _write(self, command: str) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise EvakoolConnectionError("Fridge disconnected")
        _LOGGER.debug("TX %s: %r", self.address, command)
        try:
            async with asyncio.timeout(WRITE_TIMEOUT):
                await client.write_gatt_char(WRITE_UUID, command.encode("ascii"), response=False)
        except (BleakError, TimeoutError) as err:
            raise EvakoolConnectionError(f"Write failed: {err}") from err

    async def _disconnect(self) -> None:
        self._cancel_quiet()
        client, self._client = self._client, None
        self._frames.clear()
        self._fail_waiters(EvakoolConnectionError("Disconnected"))
        if client is not None:
            try:
                await client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Error disconnecting from %s: %s", self.address, err)

    def _on_disconnected(self, client: BleakClientWithServiceCache) -> None:
        if client is not self._client:
            return
        _LOGGER.debug("Disconnected from %s", self.address)
        self._client = None
        self._cancel_quiet()
        self._frames.clear()
        self._fail_waiters(EvakoolConnectionError("Fridge disconnected"))

    def _on_notify(self, client: BleakClientWithServiceCache, data: bytearray) -> None:
        if client is not self._client:
            return
        self._cancel_quiet()
        try:
            frames = self._frames.append(bytes(data))
        except ProtocolError as err:
            self._frames.clear()
            self._report(EvakoolError(f"Invalid fridge response: {err}"))
            return
        for frame in frames:
            self._handle_frame(frame)
        self._quiet = asyncio.get_running_loop().call_later(QUIET_INTERVAL, self._on_quiet)

    def _on_quiet(self) -> None:
        self._quiet = None
        try:
            frame = self._frames.finish_unterminated()
        except ProtocolError as err:
            # Keep the partial message until more bytes arrive or the request times out.
            _LOGGER.debug("Incomplete status from %s: %s", self.address, err)
            return
        if frame is not None:
            self._handle_frame(frame)

    def _cancel_quiet(self) -> None:
        if self._quiet is not None:
            self._quiet.cancel()
            self._quiet = None

    def _handle_frame(self, frame: str) -> None:
        self.last_frame = frame[:256]
        _LOGGER.debug("RX %s: %s", self.address, self.last_frame)
        if is_fault(frame):
            self._report(EvakoolFault(f"Fridge reported fault {frame[:100]}"))
            return
        try:
            status = parse_status(frame)
        except ProtocolError as err:
            self._report(EvakoolError(f"Invalid fridge response: {err}"))
            return
        self.status = status
        waiters, self._waiters = self._waiters, []
        for future in waiters:
            if not future.done():
                future.set_result(status)
        if self.on_status is not None:
            self.on_status(status)

    def _report(self, err: EvakoolError) -> None:
        """Like the app, drop the last status; a waiting request raises, else push the error."""
        self.status = None
        if self._waiters:
            self._fail_waiters(err)
        elif self.on_error is not None:
            self.on_error(err)

    def _fail_waiters(self, err: Exception) -> None:
        waiters, self._waiters = self._waiters, []
        for future in waiters:
            if not future.done():
                future.set_exception(err)
