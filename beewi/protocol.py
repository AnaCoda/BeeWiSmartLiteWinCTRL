"""BeeWi SmartLite command frames. Each command is 0x55 <cmd> <args...> 0x0D 0x0A.

Protocol (UUIDs + command bytes) reverse-engineered by others; credit to:
- BeewiPy by delkk0 — https://github.com/delkk0/BeewiPy
- light.beewi by bbo76 — https://github.com/bbo76/light.beewi
- Raspberry Pi forum thread — https://forums.raspberrypi.com/viewtopic.php?t=117729
"""

from __future__ import annotations

from typing import NamedTuple

# GATT characteristics on the bulb.
WRITE_UUID = "a8b3fff1-4834-4051-89d0-3de95cddd318"
READ_UUID = "a8b3fff2-4834-4051-89d0-3de95cddd318"

_PREFIX = 0x55
_SUFFIX = (0x0D, 0x0A)

_CMD_POWER = 16
_CMD_TEMPERATURE = 17
_CMD_BRIGHTNESS = 18
_CMD_COLOR = 19
_CMD_WHITE = 20

# Brightness / temperature levels 0..9 map onto raw bytes 2..11.
_LEVEL_OFFSET = 2
LEVEL_MIN = 0
LEVEL_MAX = 9


def _frame(command: int, *args: int) -> bytes:
    return bytes((_PREFIX, command, *args, *_SUFFIX))


def _clamp(value: int, low: int, high: int, name: str) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer, got {value!r}") from None
    return max(low, min(high, value))


def cmd_on() -> bytes:
    """Turn the bulb on."""
    return _frame(_CMD_POWER, 1)


def cmd_off() -> bytes:
    """Turn the bulb off."""
    return _frame(_CMD_POWER, 0)


def cmd_brightness(level: int) -> bytes:
    """Set brightness. ``level`` is 0 (dimmest) to 9 (brightest)."""
    level = _clamp(level, LEVEL_MIN, LEVEL_MAX, "brightness level")
    return _frame(_CMD_BRIGHTNESS, level + _LEVEL_OFFSET)


def cmd_temperature(level: int) -> bytes:
    """Set white color temperature. ``level`` 0 (warm) to 9 (cool)."""
    level = _clamp(level, LEVEL_MIN, LEVEL_MAX, "temperature level")
    return _frame(_CMD_TEMPERATURE, level + _LEVEL_OFFSET)


def cmd_color(r: int, g: int, b: int) -> bytes:
    """Set an RGB color. Each channel is 0..255."""
    r = _clamp(r, 0, 255, "red")
    g = _clamp(g, 0, 255, "green")
    b = _clamp(b, 0, 255, "blue")
    return _frame(_CMD_COLOR, r, g, b)


def cmd_white() -> bytes:
    """Switch to plain white (full RGB white) mode."""
    return _frame(_CMD_WHITE, 255, 255, 255)


class Status(NamedTuple):
    """Decoded 5-byte status from the read characteristic."""

    on: bool
    brightness_or_white: int
    r: int
    g: int
    b: int


def parse_status(data: bytes) -> Status:
    """Decode the 5-byte status payload: [power, brightness/white, R, G, B]."""
    if data is None or len(data) < 5:
        raise ValueError(f"expected at least 5 status bytes, got {data!r}")
    return Status(
        on=bool(data[0]),
        brightness_or_white=data[1],
        r=data[2],
        g=data[3],
        b=data[4],
    )
