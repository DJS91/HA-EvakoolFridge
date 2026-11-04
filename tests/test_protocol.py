"""Protocol tests for the Evakool fridge protocol."""

import pytest
from evakool_unit.protocol import (
    STATUS_QUERY,
    FrameBuffer,
    ProtocolError,
    matches_name,
    mode_command,
    parse_status,
    power_command,
    target_range,
    temperature_command,
)

STATUS = "/SC0/1/0,1,1,+04,-18,+05,-20,2,12.6,1"


def test_encodes_exact_ascii_commands():
    assert temperature_command(1, 4) == "/SC3/1/+04\n"
    assert temperature_command(2, -18) == "/SC5/1/-18\n"
    assert temperature_command(1, 0) == "/SC3/1/+00\n"
    assert temperature_command(2, -99) == "/SC5/1/-99\n"
    assert temperature_command(1, 99) == "/SC3/1/+99\n"
    assert list(STATUS_QUERY.encode("ascii")) == [47, 83, 67, 48, 47, 49, 47, 45, 48, 49, 10]


@pytest.mark.parametrize(("compartment", "value"), [(0, 4), (3, 4), (1, 100), (1, -100)])
def test_rejects_invalid_commands(compartment, value):
    with pytest.raises(ValueError):
        temperature_command(compartment, value)


def test_decodes_and_encodes_compressor_mode_and_power():
    assert not parse_status(STATUS).max_mode
    assert parse_status(STATUS[:-1] + "2").max_mode
    assert parse_status(STATUS[:-1] + "002").max_mode
    assert mode_command(False) == "/SC6/1/001\n"
    assert mode_command(True) == "/SC6/1/002\n"
    assert power_command(True) == "/SC1/1/001\n"
    assert power_command(False) == "/SC1/1/000\n"
    assert not parse_status(STATUS.replace("/SC0/1/0,1,", "/SC0/1/0,0,")).on


def test_decodes_both_temperatures_and_targets():
    parsed = parse_status(STATUS)
    assert parsed.on and parsed.celsius
    assert (parsed.left, parsed.right) == (4, -18)
    assert (parsed.left_target, parsed.right_target) == (5, -20)
    assert (parsed.target(1), parsed.target(2)) == (5, -20)
    assert parsed.voltage == 12.6
    assert not parse_status(STATUS.replace(",1,1,", ",0,2,")).celsius
    assert parse_status(STATUS.replace(",1,1,", ",001,001,")).on


@pytest.mark.parametrize(
    ("raw", "volts"),
    [("138", 13.8), ("126", 12.6), ("240", 24.0), ("13.8", 13.8), ("12.60", 12.6), ("0", 0.0)],
)
def test_formats_voltage_in_volts(raw, volts):
    assert parse_status(STATUS.replace("12.6", raw)).voltage == volts


def test_rejects_unknown_voltage():
    with pytest.raises(ProtocolError):
        parse_status(STATUS.replace("12.6", "unknown"))


def test_assembles_every_possible_notification_split():
    for split in range(len(STATUS) + 1):
        frames = FrameBuffer()
        assert frames.append(STATUS[:split].encode()) == []
        assert frames.append((STATUS[split:] + "\n").encode()) == [STATUS]


def test_handles_coalesced_frames_and_crlf():
    frames = FrameBuffer()
    assert frames.append(f"{STATUS}\r\n{STATUS}\n".encode()) == [STATUS, STATUS]
    assert frames.finish_unterminated() is None
    assert frames.append(f"{STATUS}{STATUS}".encode()) == [STATUS]
    assert frames.finish_unterminated() == STATUS


def test_handles_unterminated_status_and_faults():
    frames = FrameBuffer()
    assert frames.append(STATUS.encode()) == []
    assert frames.finish_unterminated() == STATUS
    assert frames.append(b"/SEE/1/1") == []
    assert frames.finish_unterminated() == "/SEE/1/1"
    assert frames.append(b"/SCE/1/6") == []
    assert frames.finish_unterminated() == "/SCE/1/6"
    fault_with_status = STATUS.replace("/SC0/1/0", "/SEE/1/1")
    frames.append(fault_with_status.encode())
    assert frames.finish_unterminated() == fault_with_status
    assert parse_status(STATUS.replace("+04", "104")).left == 104


def test_preserves_incomplete_final_field_until_it_arrives():
    frames = FrameBuffer()
    frames.append(STATUS[:-1].encode())
    with pytest.raises(ProtocolError):
        frames.finish_unterminated()
    assert frames.append(b"1\n") == [STATUS]
    assert frames.finish_unterminated() is None


def test_parses_zero_targets_and_trailing_comma():
    frame = STATUS.replace("+05", "+00").replace("-20", "-00")
    parsed = parse_status(f"{frame},\r\n")
    assert (parsed.left_target, parsed.right_target) == (0, 0)


def test_rejects_incomplete_malformed_and_oversized_data():
    frames = FrameBuffer()
    with pytest.raises(ProtocolError):
        frames.append(bytes([65]) * 2049)
    frames.clear()
    assert frames.append(bytes([255, 0])) == []
    assert frames.finish_unterminated() is None
    for invalid in (
        STATUS.replace("+04", "bad"),
        STATUS.replace(",1,1,", ",x,1,"),
        "/SEE/1/1",
        STATUS.rsplit(",", 1)[0],
    ):
        with pytest.raises(ProtocolError):
            parse_status(invalid)


def test_accepts_extra_fields_and_unknown_units_like_official_app():
    assert parse_status(f"{STATUS},extra").left == 4
    assert not parse_status(STATUS.replace(",1,1,", ",1,7,")).celsius
    assert parse_status(STATUS.replace(",-18,", ", -18 ,")).right == -18


def test_matches_official_device_names():
    assert matches_name("DownUnder_1234")
    assert matches_name("Cool Ride")
    assert not matches_name("DiKey")
    assert not matches_name(None)


def test_target_ranges_match_app_guard():
    assert target_range(True) == (-25, 20)
    assert target_range(False) == (-13, 68)
