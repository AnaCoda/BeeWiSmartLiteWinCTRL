"""Remember the chosen bulb addresses so you only scan once."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

_APP_DIR_NAME = "BeeWiSmartLiteWinCTRL"


def _config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / _APP_DIR_NAME
    return Path.home() / ".config" / _APP_DIR_NAME


def _config_path() -> Path:
    return _config_dir() / "config.json"


def load_addresses() -> List[str]:
    """Return the saved bulb addresses (empty if none saved yet)."""
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    if data.get("addresses"):
        return list(data["addresses"])
    if data.get("address"):  # migrate old single-address configs
        return [data["address"]]
    return []


def save_addresses(addresses: List[str]) -> Path:
    """Persist the bulb addresses and return the file path written to."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"addresses": addresses}, indent=2), encoding="utf-8")
    return path
