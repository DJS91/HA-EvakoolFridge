"""EVAKOOL Down Under / CoolRide BLE protocol (no Home Assistant imports).

Ported from Open-DiKey's ``EvakoolProtocol.kt``, which mirrors the official
Down Under II 2.0.0 app: ASCII commands are written without response to E531,
and newline-delimited CSV status frames arrive as E532 notifications.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

SERVICE_UUID = "0000e530-1212-efde-1523-785feabcd123"
WRITE_UUID = "0000e531-1212-efde-1523-785feabcd123"
NOTIFY_UUID = "0000e532-1212-efde-1523-785feabcd123"

STATUS_QUERY = "/SC0/1/-01\n"
MAX_BUFFER = 2048

# Conservative app guard, not the model's rating.
TARGET_RANGE_C = (-25, 20)
TARGET_RANGE_F = (-13, 68)

_TEMPERATURE = re.compile(r"[+-]?\d{1,3}")
_VOLTAGE = re.compile(r"\d+(?:\.\d+)?")
_HEADER = re.compile(r"/(?:SC0|SEE|SCE)/")
_FAULT = re.compile(r"/S(?:EE|CE)/1/[1-6](?:,[^\r\n]*)?")


class ProtocolError(ValueError):
    """Raised for frames that cannot be decoded."""


@dataclass(frozen=True, slots=True)
class FridgeStatus:
    """One decoded ``/SC0/`` status frame."""

    on: bool
    celsius: bool
    left: int
    right: int
    left_target: int
    right_target: int
    voltage: float
    # Field 9: the official app shows "2" as Max and anything else as Eco.
    max_mode: bool = False

    def target(self, compartment: int) -> int:
        return self.left_target if compartment == 1 else self.right_target


def target_range(celsius: bool) -> tuple[int, int]:
    return TARGET_RANGE_C if celsius else TARGET_RANGE_F


def mode_command(max_mode: bool) -> str:
    return "/SC6/1/002\n" if max_mode else "/SC6/1/001\n"


def power_command(on: bool) -> str:
    return "/SC1/1/001\n" if on else "/SC1/1/000\n"


def temperature_command(compartment: int, temperature: int) -> str:
    if compartment not in (1, 2):
        raise ValueError("Invalid compartment")
    if not -99 <= temperature <= 99:
        raise ValueError("Temperature must be between -99 and 99")
    command = "SC3" if compartment == 1 else "SC5"
    return f"/{command}/1/{temperature:+03d}\n"


def matches_name(name: str | None) -> bool:
    lower = (name or "").lower()
    return "downunder_" in lower or "coolride" in re.sub(r"\s+", "", lower)


def is_fault(frame: str) -> bool:
    return frame.startswith(("/SEE/", "/SCE/"))


def parse_status(frame: str) -> FridgeStatus:
    """Decode the first ten fields of a status frame, ignoring extras like the app."""
    stripped = frame.strip()
    if stripped.endswith(","):
        stripped = stripped[:-1]
    fields = [f.strip() for f in stripped.split(",")]
    if len(fields) < 10 or not fields[0].startswith("/SC0/"):
        raise ProtocolError("Invalid status frame")
    try:
        power = int(fields[1])
    except ValueError as err:
        raise ProtocolError(f"Invalid power status: {fields[1]}") from err

    def temperature(index: int) -> int:
        if not _TEMPERATURE.fullmatch(fields[index]):
            raise ProtocolError(f"Invalid temperature field {index}: {fields[index]}")
        return int(fields[index])

    try:
        mode = int(fields[9])
    except ValueError:
        mode = None
    return FridgeStatus(
        on=power == 1,
        # The official app treats "1" as Celsius and anything else as Fahrenheit.
        celsius=fields[2] == "1",
        left=temperature(3),
        right=temperature(4),
        left_target=temperature(5),
        right_target=temperature(6),
        voltage=_voltage(fields[8]),
        max_mode=mode == 2,
    )


def _voltage(raw: str) -> float:
    if not _VOLTAGE.fullmatch(raw):
        raise ProtocolError(f"Invalid voltage: {raw}")
    # Integer values are tenths of a volt (138 -> 13.8); decimals are already volts.
    value = Decimal(raw) if "." in raw else Decimal(raw).scaleb(-1)
    return float(value)


class FrameBuffer:
    """Reassembles notifications that may split a message or contain several."""

    def __init__(self) -> None:
        self._buffer = ""

    def clear(self) -> None:
        self._buffer = ""

    def append(self, data: bytes) -> list[str]:
        # Drop padding/NUL and other non-printable bytes rather than the whole notification.
        self._buffer += "".join(chr(b) for b in data if b == 10 or 32 <= b <= 126)
        if len(self._buffer) > MAX_BUFFER:
            raise ProtocolError(f"Fridge response exceeded {MAX_BUFFER} bytes")
        frames: list[str] = []
        while self._buffer:
            newline = self._buffer.find("\n")
            header = _HEADER.search(self._buffer, 1)
            ends = [i for i in (newline, header.start() if header else -1) if i >= 0]
            if not ends:
                break
            end = min(ends)
            if chunk := self._buffer[:end].strip():
                frames.append(chunk)
            self._buffer = self._buffer[end + (1 if end == newline else 0) :]
        return frames

    def finish_unterminated(self) -> str | None:
        """Accept an un-terminated CSV frame once notifications have gone quiet.

        Raises ``ProtocolError`` (keeping the buffer) if it is still incomplete.
        """
        if not self._buffer.strip():
            return None
        result = self._buffer.strip()
        if is_fault(result):
            if not _FAULT.fullmatch(result):
                raise ProtocolError("Incomplete fault frame")
        else:
            parse_status(result)
        self._buffer = ""
        return result
