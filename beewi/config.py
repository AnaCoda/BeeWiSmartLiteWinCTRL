"""Remember the chosen bulb address so you only scan once."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_APP_DIR_NAME = "BeeWiSmartLiteWinCTRL"


def _config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / _APP_DIR_NAME
    return Path.home() / ".config" / _APP_DIR_NAME


def _config_path() -> Path:
    return _config_dir() / "config.json"


def load_address() -> Optional[str]:
    """Return the saved bulb address, or None if none has been saved yet."""
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    address = data.get("address")
    return address or None


def save_address(address: str) -> Path:
    """Persist the bulb address and return the file path it was written to."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"address": address}, indent=2), encoding="utf-8")
    return path
