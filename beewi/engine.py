"""Background BLE engine: persistent connections + coalesced, rate-limited writes.

The GUI runs on the main thread; bleak needs an asyncio loop. So we run one loop
in a daemon thread and submit commands to it thread-safely. Each bulb keeps its
connection open, and rapid updates (slider drags) are coalesced: only the latest
value per control is kept, and writes are rate-limited, so the link never floods.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Dict, List

from bleak import BleakClient

from . import protocol

# Minimum gap between BLE writes to one bulb. ~20 writes/sec is plenty smooth and
# stays within what the connection can carry.
MIN_SEND_INTERVAL = 0.05

# How often an idle worker wakes to re-check / restore its connection.
KEEPALIVE_INTERVAL = 5.0


class _Bulb:
    def __init__(self, address: str):
        self.address = address
        self.client: BleakClient | None = None
        self.connected = False
        # Latest-wins pending frames, keyed by control ("power", "color", ...).
        self.pending: Dict[str, bytes] = {}
        self.event = asyncio.Event()


class Engine:
    """Thread-safe façade over a background asyncio BLE loop."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._bulbs: Dict[str, _Bulb] = {}
        self._ready = threading.Event()
        self._running = False

    # Lifecycle ----------------------------------------------------------

    def start(self, addresses: List[str]) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._run, args=(list(addresses),), daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run(self, addresses: List[str]) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        for addr in addresses:
            self._bulbs[addr] = _Bulb(addr)
        for bulb in self._bulbs.values():
            self._loop.create_task(self._worker(bulb))
        self._ready.set()
        self._loop.run_forever()

    # Worker per bulb ----------------------------------------------------

    async def _worker(self, bulb: _Bulb) -> None:
        while self._running:
            if not (bulb.client and bulb.client.is_connected):
                await self._connect(bulb)
                if not bulb.connected:
                    await asyncio.sleep(2.0)
                    continue
            try:
                await asyncio.wait_for(bulb.event.wait(), timeout=KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                continue  # periodic wake to keep the connection warm
            bulb.event.clear()

            items = list(bulb.pending.items())  # coalesced snapshot
            bulb.pending.clear()
            for key, frame in items:
                try:
                    await bulb.client.write_gatt_char(
                        protocol.WRITE_UUID, frame, response=False
                    )
                except Exception:
                    bulb.connected = False
                    bulb.pending[key] = frame  # retry after reconnect
                    bulb.event.set()
                    break
            await asyncio.sleep(MIN_SEND_INTERVAL)

    async def _connect(self, bulb: _Bulb) -> None:
        try:
            if bulb.client is not None:
                try:
                    await bulb.client.disconnect()
                except Exception:
                    pass
            bulb.client = BleakClient(bulb.address)
            await bulb.client.connect()
            bulb.connected = True
        except Exception:
            bulb.connected = False

    # Command submission (called from the GUI thread) --------------------

    def _submit(self, address: str, key: str, frame: bytes) -> None:
        bulb = self._bulbs.get(address)
        if bulb is None or self._loop is None:
            return

        def apply() -> None:
            bulb.pending[key] = frame
            bulb.event.set()

        self._loop.call_soon_threadsafe(apply)

    def power(self, address: str, on: bool) -> None:
        self._submit(address, "power", protocol.cmd_on() if on else protocol.cmd_off())

    def color(self, address: str, r: int, g: int, b: int) -> None:
        self._submit(address, "color", protocol.cmd_color(r, g, b))

    def brightness(self, address: str, level: int) -> None:
        self._submit(address, "brightness", protocol.cmd_brightness(level))

    def temperature(self, address: str, level: int) -> None:
        self._submit(address, "temperature", protocol.cmd_temperature(level))

    def white(self, address: str) -> None:
        self._submit(address, "white", protocol.cmd_white())

    def is_connected(self, address: str) -> bool:
        bulb = self._bulbs.get(address)
        return bool(bulb and bulb.connected)
