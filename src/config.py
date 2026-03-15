"""Persistent application configuration stored as JSON in the project root."""

from __future__ import annotations

import json
import pathlib
from typing import Any

_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.json"

_DEFAULTS: dict[str, Any] = {
    "search_folders": [],
    "note_style": {
        "speed_px_per_sec": 420,
        "width_px": 12,
        "color_r": 0,
        "color_g": 230,
        "color_b": 230,
    },
    "led_output": {
        "enabled": False,
        "transport": "serial",
        "port": "COM5",
        "baudrate": 115200,
        "ble_address": "",
        "ble_service_uuid": "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
        "ble_char_uuid": "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
        "ble_write_with_response": False,
        "ble_chunk_size": 180,
        "led_count": 177,
        "mirror_per_key": 2,
        "fps_limit": 30,
        "active_r": 0,
        "active_g": 220,
        "active_b": 220,
        "black_r": 0,
        "black_g": 240,
        "black_b": 255,
    },
    "display_style": {
        "width_scale_percent": 66,
        "background_alpha": 120,
        "background_image": "",
        "fullscreen": True,
    },
    "keyboard_style": {
        "height_percent": 18,
        "brightness": 100,
        "visible": True,
        "sustain_latch": False,
    },
    "audience_control": {
        "enabled": False,
        "ws_url": "wss://example.com/ws/app",
        "channel_id": "",
        "app_api_key": "",
        "reconnect_sec": 2.0,
    },
    "slide_palette": {
        "enabled": False,
        "transition_ms": 2000,
        "palette": [],
        "palette_index": 0,
    },
}


def _merge_with_defaults(defaults: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            merged[key] = _merge_with_defaults(defaults[key], value)
        else:
            merged[key] = value
    return merged


def load() -> dict[str, Any]:
    """Load config from disk, merging with defaults for any missing keys."""
    if _CONFIG_PATH.exists():
        try:
            with _CONFIG_PATH.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    return _merge_with_defaults(_DEFAULTS, loaded)
        except Exception:
            pass
    return dict(_DEFAULTS)


def save(data: dict[str, Any]) -> None:
    """Write *data* to the config file, silently ignoring IO errors."""
    try:
        with _CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
