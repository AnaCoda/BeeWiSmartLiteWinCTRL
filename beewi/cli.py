"""Command-line control for the BeeWi SmartLite."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import List, Optional

from . import config
from .device import BeewiLight, scan


def _resolve_addresses(explicit: Optional[str]) -> List[str]:
    addresses = [explicit] if explicit else config.load_addresses()
    if not addresses:
        print(
            "No bulbs saved. Run 'beewi scan' first, or pass --address <MAC>.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return addresses


async def _run_scan(args: argparse.Namespace) -> int:
    print(f"Scanning for {args.timeout:.0f}s ...")
    devices = await scan(timeout=args.timeout, all_devices=args.all)
    if not devices:
        if args.all:
            print("No BLE devices found. Is Bluetooth on and a bulb powered?")
        else:
            print(
                "No BeeWi bulbs found. Try 'beewi scan --all' to list every "
                "BLE device (the bulb may advertise under another name)."
            )
        return 1

    print(f"Found {len(devices)} device(s):")
    for i, d in enumerate(devices):
        print(f"  [{i}] {d.address}  {d.name or '(no name)'}")

    if args.all:
        print("\nSave the ones you want with:  beewi use <MAC> [<MAC> ...]")
    else:
        path = config.save_addresses([d.address for d in devices])
        print(f"\nSaved {len(devices)} bulb(s) to {path}")
    return 0


async def _run_use(args: argparse.Namespace) -> int:
    path = config.save_addresses(args.addresses)
    print(f"Saved {len(args.addresses)} bulb(s) to {path}")
    return 0


async def _act(address: str, args: argparse.Namespace) -> str:
    """Apply one command to a single bulb and return a result line."""
    async with BeewiLight(address) as light:
        if args.command == "on":
            await light.on()
            return "on"
        if args.command == "off":
            await light.off()
            return "off"
        if args.command == "color":
            await light.color(args.r, args.g, args.b)
            return f"color {args.r} {args.g} {args.b}"
        if args.command == "dim":
            await light.brightness(args.level)
            return f"brightness {args.level}"
        if args.command == "temp":
            await light.temperature(args.level)
            return f"temperature {args.level}"
        if args.command == "white":
            await light.white()
            return "white"
        if args.command == "status":
            s = await light.status()
            state = "on" if s.on else "off"
            return (
                f"power={state}  level/white={s.brightness_or_white}  "
                f"rgb=({s.r},{s.g},{s.b})"
            )
        raise ValueError(f"unknown command {args.command!r}")


async def _run_action(args: argparse.Namespace) -> int:
    addresses = _resolve_addresses(args.address)
    results = await asyncio.gather(
        *(_act(addr, args) for addr in addresses), return_exceptions=True
    )
    ok = True
    for addr, result in zip(addresses, results):
        if isinstance(result, Exception):
            ok = False
            print(f"{addr}  ERROR: {result}", file=sys.stderr)
        else:
            print(f"{addr}  {result}")
    return 0 if ok else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beewi", description="Control a BeeWi SmartLite bulb over Bluetooth."
    )
    parser.add_argument(
        "--address",
        help="Target only this bulb MAC (default: all saved bulbs).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Discover bulbs and save their addresses.")
    p_scan.add_argument(
        "--timeout", type=float, default=8.0, help="Scan duration in seconds."
    )
    p_scan.add_argument(
        "--all", action="store_true", help="List every BLE device, not just BeeWi."
    )

    p_use = sub.add_parser("use", help="Save specific bulb MACs as the targets.")
    p_use.add_argument("addresses", nargs="+", help="BLE MAC address(es) to save.")

    sub.add_parser("on", help="Turn the bulb on.")
    sub.add_parser("off", help="Turn the bulb off.")
    sub.add_parser("white", help="Switch to white mode.")
    sub.add_parser("status", help="Read and print current state.")

    p_color = sub.add_parser("color", help="Set an RGB color (0..255 each).")
    p_color.add_argument("r", type=int)
    p_color.add_argument("g", type=int)
    p_color.add_argument("b", type=int)

    p_dim = sub.add_parser("dim", help="Set brightness level 0..9.")
    p_dim.add_argument("level", type=int)

    p_temp = sub.add_parser("temp", help="Set white color temperature 0..9.")
    p_temp.add_argument("level", type=int)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        runner = _run_scan
    elif args.command == "use":
        runner = _run_use
    else:
        runner = _run_action

    try:
        return asyncio.run(runner(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a friendly message
        print(f"Error: {exc}", file=sys.stderr)
        print(
            "Tips: make sure Bluetooth is on, the bulb is powered, and no phone "
            "(OtioHome) is currently connected to it.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
