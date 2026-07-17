"""Command-line control for the BeeWi SmartLite."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

from . import config
from .device import BeewiLight, scan


def _resolve_address(explicit: Optional[str]) -> str:
    address = explicit or config.load_address()
    if not address:
        print(
            "No bulb address. Run 'beewi scan' first, or pass --address <MAC>.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return address


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

    # Auto-save when there is exactly one obvious match.
    if not args.all and len(devices) == 1:
        path = config.save_address(devices[0].address)
        print(f"\nSaved {devices[0].address} to {path}")
    else:
        print(
            "\nSave one with:  beewi use <MAC>\n"
            "  e.g.  beewi use " + devices[0].address
        )
    return 0


async def _run_use(args: argparse.Namespace) -> int:
    path = config.save_address(args.address)
    print(f"Saved {args.address} to {path}")
    return 0


async def _run_action(args: argparse.Namespace) -> int:
    address = _resolve_address(args.address)
    async with BeewiLight(address) as light:
        if args.command == "on":
            await light.on()
            print("on")
        elif args.command == "off":
            await light.off()
            print("off")
        elif args.command == "color":
            await light.color(args.r, args.g, args.b)
            print(f"color {args.r} {args.g} {args.b}")
        elif args.command == "dim":
            await light.brightness(args.level)
            print(f"brightness {args.level}")
        elif args.command == "temp":
            await light.temperature(args.level)
            print(f"temperature {args.level}")
        elif args.command == "white":
            await light.white()
            print("white")
        elif args.command == "status":
            s = await light.status()
            state = "on" if s.on else "off"
            print(
                f"power={state}  level/white={s.brightness_or_white}  "
                f"rgb=({s.r},{s.g},{s.b})"
            )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beewi", description="Control a BeeWi SmartLite bulb over Bluetooth."
    )
    parser.add_argument(
        "--address",
        help="Bulb BLE MAC address (overrides the saved one).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Discover bulbs and save the address.")
    p_scan.add_argument(
        "--timeout", type=float, default=8.0, help="Scan duration in seconds."
    )
    p_scan.add_argument(
        "--all", action="store_true", help="List every BLE device, not just BeeWi."
    )

    p_use = sub.add_parser("use", help="Save a specific bulb MAC as the target.")
    p_use.add_argument("address", help="BLE MAC address to save.")

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
