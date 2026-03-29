"""Persistent application configuration stored as JSON in the project root."""

from __future__ import annotations

import json
import pathlib
from typing import Any

_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.json"

_DEFAULT_NOTE_STYLE_SINGLE = {
    "speed_px_per_sec": 420,
    "width_px": 12,
    "color_r": 0,
    "color_g": 230,
    "color_b": 230,
}

# Per-channel note style: dict of 16 channels (1-based, as strings)
_DEFAULTS: dict[str, Any] = {
    "search_folders": [],
    "note_channel_priority": [],
    "blend_same_pitch_channels": False,
    "note_style": {str(ch): _DEFAULT_NOTE_STYLE_SINGLE.copy() for ch in range(1, 17)},
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
    },
    "display_style": {
        "width_scale_percent": 66,
        "background_alpha": 120,
        "background_image": "",
        "fullscreen": True,
    },
    "audience_control": {
        "enabled": False,
        "ws_url": "wss://example.com/ws/app",
        "channel_id": "",
        "app_api_key": "",
        "reconnect_sec": 2.0,
    },
    "banks": [],
    "active_bank_index": 0,
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
                    # Migrate note_style if needed
                    ns = loaded.get("note_style")
                    if ns is not None:
                        # If it's a single dict (old format), migrate to per-channel
                        if isinstance(ns, dict) and ("speed_px_per_sec" in ns or "color_r" in ns):
                            loaded["note_style"] = {str(ch): ns.copy() for ch in range(1, 17)}
                        # If it's already per-channel, ensure all channels present
                        elif isinstance(ns, dict):
                            for ch in range(1, 17):
                                key = str(ch)
                                if key not in ns:
                                    ns[key] = _DEFAULT_NOTE_STYLE_SINGLE.copy()
                    # Migrate old user_themes → banks
                    if "user_themes" in loaded and "banks" not in loaded:
                        old = loaded.pop("user_themes")
                        # Promote each old flat theme to a bank with channel 1 data
                        banks = []
                        for t in old:
                            ch1 = {k: v for k, v in t.items() if k.startswith("note_") or k.startswith("led_")}
                            banks.append({"name": t.get("name", "Bank"), "channels": {"1": ch1}})
                        loaded["banks"] = banks
                    if "active_user_theme_index" in loaded and "active_bank_index" not in loaded:
                        loaded["active_bank_index"] = loaded.pop("active_user_theme_index")
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
