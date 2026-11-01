"""Client tests against a simulated fridge; no radio or Home Assistant required."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("bleak_retry_connector")

from bleak.exc import BleakError  # noqa: E402
from evakool_unit import client as client_module  # noqa: E402
from evakool_unit.client import (  # noqa: E402
    EvakoolClient,
    EvakoolConnectionError,
    EvakoolFault,
    EvakoolNotConfirmed,
)
from evakool_unit.protocol import NOTIFY_UUID, STATUS_QUERY, WRITE_UUID  # noqa: E402


class FakeFridge:
    """Stateful fridge that answers queries over notifications, optionally split in two."""

    def __init__(self, *, split=False, ignore_commands=False, fault=None, silent=False):
        self.on, self.celsius, self.max = 1, 1, 1
        self.left, self.right, self.lt, self.rt = 4, -18, 5, -20
        self.split, self.ignore_commands, self.fault, self.silent = (
            split,
            ignore_commands,
            fault,
            silent,
        )
        self.writes: list[str] = []

    def frame(self) -> str:
        return (
            f"/SC0/1/0,{self.on},{self.celsius},{self.left:+03d},{self.right:+03d},"
            f"{self.lt:+03d},{self.rt:+03d},2,138,{self.max}\n"
        )

    def handle(self, command: str) -> list[bytes]:
        self.writes.append(command)
        if command == STATUS_QUERY:
            if self.silent:
                return []
            if self.fault:
                return [self.fault.encode()]
            data = self.frame().encode()
            return [data[:7], data[7:]] if self.split else [data]
        if not self.ignore_commands:
            head, value = command[:4], int(command[7:])
            if head == "/SC3":
                self.lt = value
            elif head == "/SC5":
                self.rt = value
            elif head == "/SC6":
                self.max = value
            elif head == "/SC1":
                self.on = value
        return []


class FakeBleakClient:
    def __init__(self, fridge: FakeFridge, *, compatible=True):
        self.fridge = fridge
        self.is_connected = True
        self.callback = None
        self.disconnects = 0
        chars = {
            WRITE_UUID: SimpleNamespace(properties=["write-without-response"]),
            NOTIFY_UUID: SimpleNamespace(properties=["notify"]),
        }
        if not compatible:
            chars.pop(WRITE_UUID)
        self.services = SimpleNamespace(get_characteristic=chars.get)
        self.cache_cleared = False

    async def start_notify(self, _char, callback):
        self.callback = callback

    async def write_gatt_char(self, uuid, data, response):
        assert uuid == WRITE_UUID and response is False
        loop = asyncio.get_running_loop()
        for chunk in self.fridge.handle(data.decode("ascii")):
            loop.call_soon(self.callback, None, bytearray(chunk))

    async def disconnect(self):
        self.disconnects += 1
        self.is_connected = False

    async def clear_cache(self):
        self.cache_cleared = True


@pytest.fixture(autouse=True)
def fast_timeouts(monkeypatch):
    monkeypatch.setattr(client_module, "STATUS_TIMEOUT", 0.3)
    monkeypatch.setattr(client_module, "CONFIRM_TIMEOUT", 0.3)
    monkeypatch.setattr(client_module, "REQUERY_INTERVAL", 0.1)
    monkeypatch.setattr(client_module, "QUIET_INTERVAL", 0.01)


def make(fridge: FakeFridge, **kwargs):
    fake = FakeBleakClient(fridge, compatible=kwargs.pop("compatible", True))
    connections = []

    async def establish(cls, device, name, **kw):
        connections.append(kw)
        fake.is_connected = True
        return fake

    patcher = patch.object(client_module, "establish_connection", establish)
    patcher.start()
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="DownUnder_1234")
    return EvakoolClient(device, **kwargs), fake, connections, patcher


async def test_status_query_reassembles_split_notifications_and_pushes():
    pushed = []
    client, fake, connections, patcher = make(FakeFridge(split=True), on_status=pushed.append)
    try:
        status = await client.async_status()
        assert (status.left, status.right, status.voltage, status.max_mode) == (4, -18, 13.8, False)
        assert pushed == [status]
        assert client.connected and len(connections) == 1
        await client.async_status()
        assert len(connections) == 1, "persistent connection is reused"
    finally:
        patcher.stop()


async def test_commands_are_confirmed_by_reported_status():
    fridge = FakeFridge()
    client, _fake, _c, patcher = make(fridge)
    try:
        await client.async_status()
        assert (await client.async_set_temperature(2, -15)).right_target == -15
        assert (await client.async_set_mode(True)).max_mode
        assert not (await client.async_set_power(False)).on
        assert [w for w in fridge.writes if w != STATUS_QUERY] == [
            "/SC5/1/-15\n",
            "/SC6/1/002\n",
            "/SC1/1/000\n",
        ]
    finally:
        patcher.stop()


async def test_unconfirmed_command_is_never_resent():
    fridge = FakeFridge(ignore_commands=True)
    client, fake, _c, patcher = make(fridge)
    try:
        await client.async_status()
        with pytest.raises(EvakoolNotConfirmed):
            await client.async_set_temperature(1, 2)
        assert fridge.writes.count("/SC3/1/+02\n") == 1
        assert fridge.writes.count(STATUS_QUERY) > 2, "status is re-queried"
        assert client.connected, "a responsive fridge stays connected"
    finally:
        patcher.stop()


async def test_fault_frame_raises_and_disconnects():
    client, fake, _c, patcher = make(FakeFridge(fault="/SEE/1/3\n"))
    try:
        with pytest.raises(EvakoolFault):
            await client.async_status()
        assert fake.disconnects == 1 and not client.connected
    finally:
        patcher.stop()


async def test_silent_fridge_times_out_and_disconnects():
    client, fake, _c, patcher = make(FakeFridge(silent=True))
    try:
        with pytest.raises(EvakoolConnectionError):
            await client.async_status()
        assert fake.disconnects == 1
    finally:
        patcher.stop()


async def test_incompatible_device_is_rejected_and_cache_cleared():
    client, fake, _c, patcher = make(FakeFridge(), compatible=False)
    try:
        with pytest.raises(EvakoolConnectionError, match="compatible"):
            await client.async_status()
        assert fake.cache_cleared
    finally:
        patcher.stop()


async def test_disconnect_between_polls_option():
    client, fake, connections, patcher = make(FakeFridge(), keep_connected=False)
    try:
        await client.async_status()
        await client.async_status()
        assert len(connections) == 2 and fake.disconnects == 2
    finally:
        patcher.stop()


async def test_connection_failure_and_unexpected_disconnect():
    client, fake, connections, patcher = make(FakeFridge())
    try:
        await client.async_status()
        connections[0]["disconnected_callback"](fake)
        assert not client.connected
        await client.async_status()
        assert len(connections) == 2, "reconnects on next request"
    finally:
        patcher.stop()

    connections[1]["disconnected_callback"](fake)

    async def broken(*_args, **_kwargs):
        raise BleakError("out of range")

    with patch.object(client_module, "establish_connection", broken):
        with pytest.raises(EvakoolConnectionError, match="out of range"):
            await client.async_status()


async def test_unsolicited_fault_clears_status_and_reports_error():
    errors = []
    client, fake, _c, patcher = make(FakeFridge(), on_error=errors.append)
    try:
        await client.async_status()
        fake.callback(None, bytearray(b"/SCE/1/2\n"))
        assert client.status is None
        assert len(errors) == 1 and isinstance(errors[0], EvakoolFault)
    finally:
        patcher.stop()


async def test_notifications_from_a_replaced_connection_are_ignored():
    pushed = []
    client, fake, _c, patcher = make(FakeFridge(), on_status=pushed.append)
    try:
        await client.async_status()
        stale = fake.callback
        client._client = FakeBleakClient(FakeFridge())
        stale(None, bytearray(b"/SC0/1/0,1,1,+09,-18,+05,-20,2,138,1\n"))
        assert len(pushed) == 1 and client.status.left == 4
    finally:
        patcher.stop()


async def test_close_cancels_inflight_connect_and_blocks_new_requests():
    started = asyncio.Event()

    async def hanging(*_args, **_kwargs):
        started.set()
        await asyncio.sleep(3600)

    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="DownUnder_1234")
    client = EvakoolClient(device)
    with patch.object(client_module, "establish_connection", hanging):
        request = asyncio.create_task(client.async_status())
        await started.wait()
        async with asyncio.timeout(1):
            await client.async_close()
        with pytest.raises(asyncio.CancelledError):
            await request
        with pytest.raises(EvakoolConnectionError, match="closed"):
            await client.async_status()
