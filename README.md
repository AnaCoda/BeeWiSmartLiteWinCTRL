# BeeWi SmartLite — Windows Control

Control a BeeWi SmartLite RGB bulb from Windows over Bluetooth — no app, no cloud.

## Setup

Needs Bluetooth (BLE) on your laptop and [`uv`](https://docs.astral.sh/uv/).

```powershell
uv sync
```

## Usage

Make sure the bulb is on and no phone is connected to it (Bluetooth allows one
connection at a time).

```powershell
uv run beewi scan            # find the bulb; saves its address
uv run beewi on
uv run beewi off
uv run beewi color 255 0 0   # R G B, each 0..255
uv run beewi dim 5           # brightness 0..9
uv run beewi white
uv run beewi temp 3          # white warmth 0..9
uv run beewi status
```

`scan` saves the address, so later commands need nothing extra. If it finds
several devices, save yours with `uv run beewi use AA:BB:CC:DD:EE:FF`.

Nothing found? Try `uv run beewi scan --all` to list every BLE device.

## Credits

The BeeWi SmartLite Bluetooth protocol (characteristic UUIDs and command bytes)
was reverse-engineered by others. This project just ports it to Windows. Credit to:

- [BeewiPy](https://github.com/delkk0/BeewiPy) by delkk0
- [light.beewi](https://github.com/bbo76/light.beewi) by bbo76
- [Raspberry Pi forum thread](https://forums.raspberrypi.com/viewtopic.php?t=117729)
