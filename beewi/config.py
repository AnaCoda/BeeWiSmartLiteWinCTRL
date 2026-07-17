"""Persist bulb addresses and presets in one config.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List

_APP_DIR_NAME = "BeeWiSmartLiteWinCTRL"


def _config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / _APP_DIR_NAME
    return Path.home() / ".config" / _APP_DIR_NAME


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _load_all() -> dict:
    try:
        return json.loads(_config_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_all(data: dict) -> Path:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_addresses() -> List[str]:
    """Return the saved bulb addresses (empty if none saved yet)."""
    data = _load_all()
    if data.get("addresses"):
        return list(data["addresses"])
    if data.get("address"):  # migrate old single-address configs
        return [data["address"]]
    return []


def save_addresses(addresses: List[str]) -> Path:
    """Persist the bulb addresses, keeping any saved presets."""
    data = _load_all()
    data["addresses"] = addresses
    return _save_all(data)


def load_presets() -> Dict[str, dict]:
    """Return saved presets as {name: {address: state}} (empty if none)."""
    data = _load_all()
    presets = data.get("presets")
    return dict(presets) if isinstance(presets, dict) else {}


def save_presets(presets: Dict[str, dict]) -> Path:
    """Persist all presets, keeping any saved addresses."""
    data = _load_all()
    data["presets"] = presets
    return _save_all(data)
