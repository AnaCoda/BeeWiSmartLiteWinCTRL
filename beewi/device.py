"""Bluetooth transport for the BeeWi SmartLite, built on bleak."""

from __future__ import annotations

from typing import List, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from . import protocol

_NAME_HINTS = ("smart lite", "smartlite", "beewi")


async def scan(timeout: float = 8.0, all_devices: bool = False) -> List[BLEDevice]:
    """Discover nearby BLE devices (likely BeeWi bulbs unless all_devices)."""
    devices = await BleakScanner.discover(timeout=timeout)
    if all_devices:
        return devices
    matches = [d for d in devices if _looks_like_bulb(d)]
    return matches


def _looks_like_bulb(device: BLEDevice) -> bool:
    name = (device.name or "").lower()
    return any(hint in name for hint in _NAME_HINTS)


class BeewiLight:
    """A single BeeWi SmartLite bulb addressed by its BLE MAC address."""

    def __init__(self, address: str):
        self.address = address
        self._client: Optional[BleakClient] = None

    async def __aenter__(self) -> "BeewiLight":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        self._client = BleakClient(self.address)
        await self._client.connect()

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def send(self, frame: bytes) -> None:
        # Prefer write-without-response; retry with response if the bulb needs it.
        if self._client is None:
            raise RuntimeError("not connected; call connect() first")
        try:
            await self._client.write_gatt_char(
                protocol.WRITE_UUID, frame, response=False
            )
        except Exception:
            await self._client.write_gatt_char(
                protocol.WRITE_UUID, frame, response=True
            )

    async def status(self) -> protocol.Status:
        if self._client is None:
            raise RuntimeError("not connected; call connect() first")
        data = await self._client.read_gatt_char(protocol.READ_UUID)
        return protocol.parse_status(bytes(data))

    async def on(self) -> None:
        await self.send(protocol.cmd_on())

    async def off(self) -> None:
        await self.send(protocol.cmd_off())

    async def brightness(self, level: int) -> None:
        await self.send(protocol.cmd_brightness(level))

    async def temperature(self, level: int) -> None:
        await self.send(protocol.cmd_temperature(level))

    async def color(self, r: int, g: int, b: int) -> None:
        await self.send(protocol.cmd_color(r, g, b))

    async def white(self) -> None:
        await self.send(protocol.cmd_white())
