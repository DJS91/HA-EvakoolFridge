"""HA-specific unit tests, requiring the optional homeassistant-test dependency group."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip(
    "homeassistant", reason="Install the homeassistant-test group on Python 3.14.2+"
)

from homeassistant.const import CONF_ADDRESS, UnitOfTemperature  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402

from custom_components.evakool import async_setup_entry, async_unload_entry  # noqa: E402
from custom_components.evakool.binary_sensor import EvakoolConnectedSensor  # noqa: E402
from custom_components.evakool.client import (  # noqa: E402
    EvakoolConnectionError,
    EvakoolNotConfirmed,
)
from custom_components.evakool.config_flow import (  # noqa: E402
    EvakoolConfigFlow,
    EvakoolOptionsFlow,
)
from custom_components.evakool.coordinator import EvakoolCoordinator  # noqa: E402
from custom_components.evakool.number import EvakoolTargetNumber  # noqa: E402
from custom_components.evakool.protocol import SERVICE_UUID, parse_status  # noqa: E402
from custom_components.evakool.select import EvakoolModeSelect  # noqa: E402
from custom_components.evakool.sensor import SENSORS, EvakoolSensor  # noqa: E402
from custom_components.evakool.switch import (  # noqa: E402
    EvakoolConnectionSwitch,
    EvakoolPowerSwitch,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
STATUS = parse_status("/SC0/1/0,1,1,+04,-18,+05,-20,2,138,2")
COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "evakool"


def entry(options=None):
    return SimpleNamespace(
        data={CONF_ADDRESS: ADDRESS},
        options=options or {},
        title="DownUnder_1234",
        entry_id="test-entry",
        unique_id=ADDRESS,
        async_on_unload=MagicMock(),
    )


def coordinator(data=STATUS):
    return SimpleNamespace(
        data=data,
        last_update_success=True,
        connection_enabled=True,
        async_set_temperature=AsyncMock(),
        async_set_mode=AsyncMock(),
        async_set_power=AsyncMock(),
    )


def service_info(name="DownUnder_1234", uuids=(SERVICE_UUID,), address=ADDRESS):
    return SimpleNamespace(name=name, address=address, service_uuids=list(uuids))


def setup_patches(device):
    return (
        patch(
            "custom_components.evakool.bluetooth.async_ble_device_from_address",
            return_value=device,
        ),
        patch("custom_components.evakool.EvakoolCoordinator.async_refresh", AsyncMock()),
    )


def ha():
    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


async def test_setup_succeeds_out_of_range_and_searches_on_each_connect():
    hass, config_entry = ha(), entry({"scan_interval": 15, "keep_connected": False})
    lookup, refresh = setup_patches(None)
    with lookup as find, refresh:
        assert await async_setup_entry(hass, config_entry)
        coord = config_entry.runtime_data
        coord.async_refresh.assert_awaited_once()
        client = coord.client
        assert client._lookup() is None
        find.assert_called_with(hass, ADDRESS, connectable=True)
    assert client.keep_connected is False and not client.closed
    assert coord.update_interval.total_seconds() == 15
    assert client.on_status == coord.async_pushed_status
    assert client.on_error == coord.async_pushed_error
    assert client.on_connection == coord.async_connection_changed
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    client.async_close = AsyncMock()
    assert await async_unload_entry(hass, config_entry)
    client.async_close.assert_awaited_once()


async def test_setup_with_connection_off_never_connects():
    hass, config_entry = ha(), entry()
    config_entry.data["connection_enabled"] = False
    lookup, refresh = setup_patches(SimpleNamespace(address=ADDRESS, name="DownUnder_1234"))
    with lookup, refresh:
        assert await async_setup_entry(hass, config_entry)
        coord = config_entry.runtime_data
        coord.async_refresh.assert_not_awaited()
    assert coord.client.closed and not coord.connection_enabled
    assert coord.update_interval is None
    with pytest.raises(UpdateFailed, match="turned off"):
        await coord._async_update_data()


async def test_connection_toggle_releases_and_reconnects():
    hass, config_entry = ha(), entry({"scan_interval": 20})
    lookup, refresh = setup_patches(None)
    with lookup, refresh:
        await async_setup_entry(hass, config_entry)
        coord = config_entry.runtime_data
        coord.data = STATUS
        coord.client.async_close = AsyncMock()
        temperature = EvakoolSensor(coord, config_entry, SENSORS[0])
        switch = EvakoolConnectionSwitch(coord, config_entry, "connection")
        connected = EvakoolConnectedSensor(coord, config_entry, "connected")
        assert switch.is_on and switch.entity_category == "config"

        coord.last_update_success = True
        assert temperature.available
        await switch.async_turn_off()
        coord.client.async_close.assert_awaited_once()
        hass.config_entries.async_update_entry.assert_called_once_with(
            config_entry, data={CONF_ADDRESS: ADDRESS, "connection_enabled": False}
        )
        assert coord.update_interval is None
        assert not switch.is_on and switch.available
        assert not temperature.available, "data entities go unavailable while released"
        assert connected.available and not connected.is_on
        assert await coord._async_update_data() is STATUS, "stray scheduled poll is ignored"

        config_entry.data["connection_enabled"] = False
        coord.client._closed = True
        coord.async_refresh.reset_mock()
        await switch.async_turn_on()
        assert not coord.client.closed and switch.is_on
        assert coord.update_interval.total_seconds() == 20
        coord.async_refresh.assert_awaited_once()
        assert hass.config_entries.async_update_entry.call_args.kwargs["data"]["connection_enabled"]


async def test_coordinator_maps_errors_and_confirms_commands():
    coord = object.__new__(EvakoolCoordinator)
    coord.connection_enabled = True
    coord.client = SimpleNamespace(
        async_status=AsyncMock(side_effect=EvakoolConnectionError("Out of range")),
        async_set_mode=AsyncMock(return_value=STATUS),
        async_set_temperature=AsyncMock(side_effect=EvakoolNotConfirmed("Not confirmed")),
        async_set_power=AsyncMock(return_value=STATUS),
    )
    coord.async_set_updated_data = MagicMock()
    coord.async_request_refresh = AsyncMock()
    with pytest.raises(UpdateFailed, match="Out of range"):
        await coord._async_update_data()
    await coord.async_set_mode(True)
    coord.async_set_updated_data.assert_called_once_with(STATUS)
    with pytest.raises(HomeAssistantError, match="Not confirmed"):
        await coord.async_set_temperature(1, 3)
    coord.async_request_refresh.assert_awaited_once()


def test_pushed_status_only_publishes_changes():
    coord = object.__new__(EvakoolCoordinator)
    coord.data, coord.last_update_success = STATUS, True
    coord.async_set_updated_data = MagicMock()
    coord.async_pushed_status(STATUS)
    coord.async_set_updated_data.assert_not_called()
    changed = parse_status("/SC0/1/0,1,1,+03,-18,+05,-20,2,138,2")
    coord.async_pushed_status(changed)
    coord.async_set_updated_data.assert_called_once_with(changed)


def test_sensors_identity_values_and_units():
    coord, config_entry = coordinator(), entry()
    sensors = {d.key: EvakoolSensor(coord, config_entry, d) for d in SENSORS}
    assert sensors["left_temperature"].unique_id == f"{ADDRESS}_left_temperature"
    assert sensors["left_temperature"].native_value == 4
    assert sensors["right_temperature"].native_value == -18
    assert sensors["left_temperature"].native_unit_of_measurement == UnitOfTemperature.CELSIUS
    assert sensors["voltage"].native_value == 13.8
    assert sensors["voltage"].native_unit_of_measurement == "V"
    assert sensors["compressor_mode"].native_value == "max"
    assert sensors["voltage"].device_info["connections"] == {("bluetooth", ADDRESS)}
    assert sensors["voltage"].available
    coord.data = parse_status("/SC0/1/0,1,2,+40,+00,+41,-04,2,126,1")
    assert sensors["left_temperature"].native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT
    assert sensors["compressor_mode"].native_value == "eco"
    coord.data = None
    assert sensors["left_temperature"].native_value is None
    assert not sensors["left_temperature"].available


async def test_controls_read_status_and_send_commands():
    coord, config_entry = coordinator(), entry()
    left, right = (
        EvakoolTargetNumber(coord, config_entry, 1),
        EvakoolTargetNumber(coord, config_entry, 2),
    )
    assert (left.native_value, right.native_value) == (5, -20)
    assert (left.native_min_value, left.native_max_value) == (-25, 20)
    assert right.unique_id == f"{ADDRESS}_right_target"
    await right.async_set_native_value(-16.0)
    coord.async_set_temperature.assert_awaited_once_with(2, -16)
    coord.data = parse_status("/SC0/1/0,1,2,+40,+00,+41,-04,2,126,1")
    assert (left.native_min_value, left.native_max_value) == (-13, 68)
    assert left.native_unit_of_measurement == UnitOfTemperature.FAHRENHEIT

    mode = EvakoolModeSelect(coord, config_entry, "mode")
    assert mode.current_option == "eco"
    await mode.async_select_option("max")
    coord.async_set_mode.assert_awaited_once_with(True)

    power = EvakoolPowerSwitch(coord, config_entry, "power")
    assert power.is_on
    await power.async_turn_off()
    coord.async_set_power.assert_awaited_once_with(False)


def flow():
    config_flow = EvakoolConfigFlow()
    config_flow.hass = MagicMock()
    config_flow.context = {"source": "bluetooth"}
    config_flow.async_set_unique_id = AsyncMock()
    config_flow._abort_if_unique_id_configured = MagicMock()
    return config_flow


async def test_bluetooth_discovery_confirms_then_creates_entry():
    config_flow = flow()
    result = await config_flow.async_step_bluetooth(service_info())
    assert result["step_id"] == "bluetooth_confirm"
    config_flow.async_set_unique_id.assert_awaited_once_with(ADDRESS)
    result = await config_flow.async_step_bluetooth_confirm({})
    assert result["title"] == "DownUnder_1234"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}

    other = flow()
    result = await other.async_step_bluetooth(service_info("Phone", ()))
    assert result["reason"] == "not_supported"


async def test_user_step_lists_only_unconfigured_fridges():
    config_flow = flow()
    config_flow.context = {"source": "user"}
    config_flow._async_current_ids = MagicMock(return_value={"11:22:33:44:55:66"})
    found = [
        service_info(),
        service_info("Cool Ride", (), "AA:AA:AA:AA:AA:AA"),
        service_info("DownUnder_9", (), "11:22:33:44:55:66"),
        service_info("Headphones", (), "BB:BB:BB:BB:BB:BB"),
    ]
    with patch(
        "custom_components.evakool.config_flow.async_discovered_service_info",
        return_value=found,
    ):
        result = await config_flow.async_step_user()
    assert result["step_id"] == "user"
    assert set(config_flow._discovered) == {ADDRESS, "AA:AA:AA:AA:AA:AA"}
    result = await config_flow.async_step_user({CONF_ADDRESS: "AA:AA:AA:AA:AA:AA"})
    assert result["title"] == "Cool Ride"

    empty = flow()
    empty._async_current_ids = MagicMock(return_value=set())
    with patch(
        "custom_components.evakool.config_flow.async_discovered_service_info", return_value=[]
    ):
        assert (await empty.async_step_user())["reason"] == "no_devices_found"


async def test_options_flow_defaults_and_saves():
    options = EvakoolOptionsFlow()
    with patch.object(
        EvakoolOptionsFlow, "config_entry", new=SimpleNamespace(options={}), create=True
    ):
        result = await options.async_step_init()
        assert result["step_id"] == "init"
        assert result["data_schema"]({}) == {"scan_interval": 30, "keep_connected": True}
        result = await options.async_step_init({"scan_interval": 60.0, "keep_connected": False})
    assert result["data"] == {"scan_interval": 60, "keep_connected": False}


def test_translations_cover_every_entity_and_match_strings():
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert strings == english
    entity = strings["entity"]
    assert {d.key for d in SENSORS} == set(entity["sensor"])
    assert set(entity["number"]) == {"left_target", "right_target"}
    assert set(entity["select"]) == {"mode"}
    assert set(entity["switch"]) == {"power", "connection"}
    assert set(entity["binary_sensor"]) == {"connected"}
    icons = json.loads((COMPONENT / "icons.json").read_text(encoding="utf-8"))["entity"]
    assert all(key in entity[platform] for platform in icons for key in icons[platform])
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "evakool"
    assert {"service_uuid": SERVICE_UUID, "connectable": True} in manifest["bluetooth"]


def test_pushed_error_marks_coordinator_failed():
    coord = object.__new__(EvakoolCoordinator)
    coord.async_set_update_error = MagicMock()
    coord.async_pushed_error(EvakoolConnectionError("Fridge reported fault /SEE/1/1"))
    (err,) = coord.async_set_update_error.call_args.args
    assert isinstance(err, UpdateFailed) and "fault" in str(err)
