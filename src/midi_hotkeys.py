"""Persistence and lookup helpers for MIDI hotkey mappings."""

from __future__ import annotations

from src import config as cfg
from src.midi_actions import get_action_def

_DEFAULT_THEME_NEXT_MAPPING = {
    "action_id": "performance.theme_next",
    "message_type": "cc",
    "cc_number": 64,
    "midi_channel": None,
    "mode": "trigger",
    "threshold": 64,
    "invert": False,
}


def _normalize_mapping(mapping: dict) -> dict[str, object] | None:
    action_id = str(mapping.get("action_id", "")).strip()
    action_def = get_action_def(action_id)
    if not action_id or action_def is None:
        return None

    message_type = str(mapping.get("message_type", "cc")).lower()
    if message_type != "cc":
        return None

    try:
        cc_number = int(mapping.get("cc_number", -1))
    except Exception:
        return None
    if cc_number < 0 or cc_number > 127:
        return None

    raw_channel = mapping.get("midi_channel", None)
    midi_channel: int | None
    if raw_channel in (None, "", -1):
        midi_channel = None
    else:
        try:
            midi_channel = int(raw_channel)
        except Exception:
            midi_channel = None
        if midi_channel is not None and (midi_channel < 0 or midi_channel > 15):
            midi_channel = None

    mode = str(mapping.get("mode", action_def.get("mode", "trigger")))
    try:
        threshold = int(mapping.get("threshold", int(action_def.get("threshold", 64))))
    except Exception:
        threshold = int(action_def.get("threshold", 64))
    threshold = max(0, min(127, threshold))

    return {
        "action_id": action_id,
        "message_type": "cc",
        "cc_number": cc_number,
        "midi_channel": midi_channel,
        "mode": mode,
        "threshold": threshold,
        "invert": bool(mapping.get("invert", False)),
    }


def load_hotkeys() -> list[dict[str, object]]:
    """Return normalized hotkey mappings, seeding a default theme-next mapping."""
    data = cfg.load().get("midi_settings", {})
    raw_hotkeys = data.get("hotkeys", [])
    hotkeys: list[dict[str, object]] = []
    for entry in raw_hotkeys if isinstance(raw_hotkeys, list) else []:
        if isinstance(entry, dict):
            normalized = _normalize_mapping(entry)
            if normalized is not None:
                hotkeys.append(normalized)

    if hotkeys:
        return hotkeys
    return [dict(_DEFAULT_THEME_NEXT_MAPPING)]


def save_hotkeys(mappings: list[dict[str, object]]) -> None:
    """Persist normalized hotkey mappings."""
    normalized = []
    for mapping in mappings:
        normalized_mapping = _normalize_mapping(mapping)
        if normalized_mapping is not None:
            normalized.append(normalized_mapping)

    data = cfg.load()
    midi_settings = data.setdefault("midi_settings", {})
    midi_settings["hotkeys"] = normalized
    cfg.save(data)


def set_hotkey(mapping: dict[str, object]) -> None:
    """Upsert a hotkey by action id."""
    normalized = _normalize_mapping(mapping)
    if normalized is None:
        return

    mappings = load_hotkeys()
    action_id = str(normalized["action_id"])
    updated = False
    for index, existing in enumerate(mappings):
        if str(existing.get("action_id", "")) == action_id:
            mappings[index] = normalized
            updated = True
            break
    if not updated:
        mappings.append(normalized)
    save_hotkeys(mappings)


def clear_hotkey(action_id: str) -> None:
    """Remove the mapping for *action_id* if present."""
    mappings = [
        mapping
        for mapping in load_hotkeys()
        if str(mapping.get("action_id", "")) != action_id
    ]
    save_hotkeys(mappings)


def find_matching_actions(
    midi_channel: int,
    cc_number: int,
    value: int,
) -> list[dict[str, object]]:
    """Return hotkeys matching an incoming MIDI CC event."""
    matches: list[dict[str, object]] = []
    for mapping in load_hotkeys():
        if int(mapping.get("cc_number", -1)) != cc_number:
            continue
        mapped_channel = mapping.get("midi_channel", None)
        if mapped_channel is not None and int(mapped_channel) != midi_channel:
            continue
        event_mapping = dict(mapping)
        event_mapping["value"] = max(0, min(127, int(value)))
        matches.append(event_mapping)
    return matches


def format_mapping_label(mapping: dict[str, object] | None) -> str:
    """Return a short human-readable label for a mapping."""
    if not mapping:
        return "Unmapped"
    cc_number = int(mapping.get("cc_number", -1))
    midi_channel = mapping.get("midi_channel", None)
    if midi_channel is None:
        return f"CC {cc_number}"
    return f"CC {cc_number} Ch {int(midi_channel) + 1}"
