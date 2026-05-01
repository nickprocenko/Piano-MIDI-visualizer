"""Persistence helpers for song-based performances and their themes."""

from __future__ import annotations

from src import config as cfg


_GLOBAL_NOTE_STYLE_KEYS = ("speed_px_per_sec",)


def _apply_global_note_style_fields(note_style: dict) -> dict:
    merged = dict(note_style)
    global_style = cfg.load().get("note_style", {})
    for key in _GLOBAL_NOTE_STYLE_KEYS:
        merged[key] = int(global_style.get(key, 420))
    return merged


def _strip_channel_note_overrides(note_style: dict) -> dict:
    cleaned = dict(note_style)
    for key in _GLOBAL_NOTE_STYLE_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _strip_legacy_note_automation(note_style: dict) -> dict:
    cleaned = dict(note_style)
    cleaned["active_theme_id"] = "custom"
    cleaned["experimental_claire_script_enabled"] = 0
    return cleaned


def _sanitize_id(name: str, fallback: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in name.strip())
    cleaned = "_".join(filter(None, cleaned.split("_")))
    return cleaned or fallback


def _unique_id(existing_ids: set[str], base_name: str, fallback_prefix: str) -> str:
    base = _sanitize_id(base_name, fallback_prefix)
    candidate = base
    counter = 2
    while candidate in existing_ids:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def _snapshot_current_theme(name: str) -> dict:
    data = cfg.load()
    display = data.get("display_style", {})
    note_style = _strip_legacy_note_automation(dict(data.get("note_style", {})))
    return {
        "id": _unique_id(set(), name, "theme"),
        "name": name,
        "note_style": note_style,
        "style_sync_enabled": False,
        "style_cues": [
            {
                "name": "Cue 1",
                "note_style": dict(note_style),
                "channels": {},
            }
        ],
        "media": {
            "background_image": str(display.get("background_image", "")),
            "background_slideshow_paths": list(display.get("background_slideshow_paths", [])),
            "background_alpha": int(display.get("background_alpha", 120)),
            "background_slide_duration_sec": int(display.get("background_slide_duration_sec", 5)),
            "background_transition_percent": int(display.get("background_transition_percent", 35)),
            "gif_speed_percent": int(display.get("gif_speed_percent", 100)),
        },
    }


def _theme_media_count(theme: dict) -> int:
    media = dict(theme.get("media", {}))
    slideshow = list(media.get("background_slideshow_paths", []))
    single = str(media.get("background_image", ""))
    if slideshow:
        return max(1, len(slideshow))
    return 1 if single else 1


def _ensure_style_cues(theme: dict) -> None:
    cues = theme.setdefault("style_cues", [])
    cue_count = _theme_media_count(theme)
    base_style = _strip_legacy_note_automation(dict(theme.get("note_style", {})))
    media = dict(theme.get("media", {}))
    default_transition = int(media.get("background_transition_percent", 35))
    while len(cues) < cue_count:
        cues.append(
            {
                "name": f"Cue {len(cues) + 1}",
                "note_style": dict(base_style),
                "channels": {},
                "background_transition_percent": default_transition,
            }
        )
    if len(cues) > cue_count:
        del cues[cue_count:]
    for i, cue in enumerate(cues):
        cue["name"] = str(cue.get("name", f"Cue {i + 1}"))
        cue["note_style"] = _strip_legacy_note_automation(dict(cue.get("note_style", base_style)))
        cue.setdefault("channels", {})
        cue["background_transition_percent"] = int(
            cue.get("background_transition_percent", default_transition)
        )


def load_performances() -> list[dict]:
    return list(cfg.load().get("performances", []))


def save_performances(performances: list[dict]) -> None:
    data = cfg.load()
    data["performances"] = performances
    cfg.save(data)


def get_active_performance_id() -> str:
    return str(cfg.load().get("active_performance_id", ""))


def set_active_performance_id(performance_id: str) -> None:
    data = cfg.load()
    data["active_performance_id"] = performance_id
    cfg.save(data)


def get_active_performance() -> dict | None:
    performances = load_performances()
    active_id = get_active_performance_id()
    for performance in performances:
        if str(performance.get("id", "")) == active_id:
            return performance
    return performances[0] if performances else None


def create_performance(name: str) -> dict:
    performances = load_performances()
    existing_ids = {str(perf.get("id", "")) for perf in performances}
    performance_id = _unique_id(existing_ids, name, "performance")
    performance = {
        "id": performance_id,
        "name": name,
        "themes": [],
        "active_theme_index": -1,
    }
    performances.append(performance)
    save_performances(performances)
    set_active_performance_id(performance_id)
    return performance


def rename_performance(performance_id: str, name: str) -> None:
    performances = load_performances()
    for performance in performances:
        if str(performance.get("id", "")) == performance_id:
            performance["name"] = name
            break
    save_performances(performances)


def delete_performance(performance_id: str) -> None:
    performances = [
        performance
        for performance in load_performances()
        if str(performance.get("id", "")) != performance_id
    ]
    save_performances(performances)
    active_id = get_active_performance_id()
    if active_id == performance_id:
        set_active_performance_id(str(performances[0].get("id", "")) if performances else "")


def set_active_performance(performance_id: str) -> None:
    set_active_performance_id(performance_id)


def load_themes(performance_id: str) -> list[dict]:
    for performance in load_performances():
        if str(performance.get("id", "")) == performance_id:
            return list(performance.get("themes", []))
    return []


def get_active_theme_index(performance_id: str) -> int:
    for performance in load_performances():
        if str(performance.get("id", "")) == performance_id:
            return int(performance.get("active_theme_index", -1))
    return -1


def save_themes(performance_id: str, themes: list[dict], active_index: int | None = None) -> None:
    performances = load_performances()
    for performance in performances:
        if str(performance.get("id", "")) == performance_id:
            performance["themes"] = themes
            if active_index is not None:
                performance["active_theme_index"] = active_index
            break
    save_performances(performances)


def create_theme(performance_id: str, name: str) -> None:
    themes = load_themes(performance_id)
    theme = _snapshot_current_theme(name)
    existing_ids = {str(entry.get("id", "")) for entry in themes}
    theme["id"] = _unique_id(existing_ids, name, "theme")
    _ensure_style_cues(theme)
    themes.append(theme)
    save_themes(performance_id, themes, len(themes) - 1)


def update_theme_from_current(performance_id: str, theme_index: int) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    current = _snapshot_current_theme(str(themes[theme_index].get("name", f"Theme {theme_index + 1}")))
    current["id"] = str(themes[theme_index].get("id", current["id"]))
    current["style_sync_enabled"] = bool(themes[theme_index].get("style_sync_enabled", False))
    current["style_cues"] = list(themes[theme_index].get("style_cues", []))
    _ensure_style_cues(current)
    themes[theme_index] = current
    save_themes(performance_id, themes, theme_index)


def save_active_theme_from_current(performance_id: str) -> None:
    """Save current app note/display state into the active theme for a performance."""
    theme_index = get_active_theme_index(performance_id)
    if theme_index >= 0:
        update_theme_from_current(performance_id, theme_index)


def rename_theme(performance_id: str, theme_index: int, name: str) -> None:
    themes = load_themes(performance_id)
    if 0 <= theme_index < len(themes):
        themes[theme_index]["name"] = name
        save_themes(performance_id, themes)


def delete_theme(performance_id: str, theme_index: int) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    themes.pop(theme_index)
    active_index = get_active_theme_index(performance_id)
    if active_index >= len(themes):
        active_index = len(themes) - 1
    save_themes(performance_id, themes, active_index)


def set_active_theme(performance_id: str, theme_index: int) -> None:
    themes = load_themes(performance_id)
    if 0 <= theme_index < len(themes):
        save_themes(performance_id, themes, theme_index)


def apply_theme_to_config(performance_id: str, theme_index: int) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    data = cfg.load()
    global_note_style = dict(data.get("note_style", {}))
    data["note_style"] = dict(theme.get("note_style", {}))
    for key in _GLOBAL_NOTE_STYLE_KEYS:
        if key in global_note_style:
            data["note_style"][key] = int(global_note_style[key])
    media = dict(theme.get("media", {}))
    display = data.setdefault("display_style", {})
    for key, value in media.items():
        display[key] = value
    cfg.save(data)
    set_active_theme(performance_id, theme_index)


def get_theme_note_style(performance_id: str, theme_index: int) -> dict:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return {}
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    style = _strip_legacy_note_automation(dict(theme.get("note_style", {})))
    return _apply_global_note_style_fields(style)


def get_theme_channel_note_style(performance_id: str, theme_index: int, channel: int) -> dict:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return {}
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    channels = dict(theme.get("channels", {}))
    channel_data = channels.get(str(channel), {})
    if isinstance(channel_data, dict) and isinstance(channel_data.get("note_style", {}), dict):
        style = _strip_legacy_note_automation(dict(theme.get("note_style", {})))
        style.update(_strip_legacy_note_automation(dict(channel_data.get("note_style", {}))))
        return _apply_global_note_style_fields(_strip_legacy_note_automation(style))
    return _apply_global_note_style_fields(_strip_legacy_note_automation(dict(theme.get("note_style", {}))))


def set_theme_channel_note_style(
    performance_id: str,
    theme_index: int,
    channel: int,
    note_style: dict,
) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    theme = themes[theme_index]
    channels = theme.setdefault("channels", {})
    channel_entry = channels.setdefault(str(channel), {})
    cleaned_style = _strip_channel_note_overrides(_strip_legacy_note_automation(dict(note_style)))
    channel_entry["note_style"] = cleaned_style
    save_themes(performance_id, themes)

    if get_active_theme_index(performance_id) == theme_index:
        data = cfg.load()
        data["note_style"] = _apply_global_note_style_fields(
            _strip_legacy_note_automation(dict(note_style))
        )
        cfg.save(data)


def has_theme_channel_override(performance_id: str, theme_index: int, channel: int) -> bool:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return False
    theme = themes[theme_index]
    channels = dict(theme.get("channels", {}))
    channel_data = channels.get(str(channel), {})
    return bool(isinstance(channel_data, dict) and channel_data.get("note_style"))


def is_theme_style_sync_enabled(performance_id: str, theme_index: int) -> bool:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return False
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    return bool(theme.get("style_sync_enabled", False))


def set_theme_style_sync_enabled(performance_id: str, theme_index: int, enabled: bool) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    theme = themes[theme_index]
    theme["style_sync_enabled"] = bool(enabled)
    _ensure_style_cues(theme)
    save_themes(performance_id, themes)


def get_theme_style_cue_count(performance_id: str, theme_index: int) -> int:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return 1
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    return len(theme.get("style_cues", [])) or 1


def get_theme_style_cue_label(performance_id: str, theme_index: int, cue_index: int) -> str:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return f"Cue {cue_index + 1}"
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    cues = list(theme.get("style_cues", []))
    if not (0 <= cue_index < len(cues)):
        return f"Cue {cue_index + 1}"
    return str(cues[cue_index].get("name", f"Cue {cue_index + 1}"))


def get_theme_cue_transition_percent(
    performance_id: str,
    theme_index: int,
    cue_index: int,
) -> int:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return 35
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    media = dict(theme.get("media", {}))
    default_transition = int(media.get("background_transition_percent", 35))
    cues = list(theme.get("style_cues", []))
    if not (0 <= cue_index < len(cues)):
        return default_transition
    return int(cues[cue_index].get("background_transition_percent", default_transition))


def set_theme_cue_transition_percent(
    performance_id: str,
    theme_index: int,
    cue_index: int,
    transition_percent: int,
) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    cues = theme.setdefault("style_cues", [])
    if not (0 <= cue_index < len(cues)):
        return
    cues[cue_index]["background_transition_percent"] = int(max(10, min(90, transition_percent)))
    save_themes(performance_id, themes)


def get_theme_cue_note_style(
    performance_id: str,
    theme_index: int,
    cue_index: int,
    channel: int,
) -> dict:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return {}
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    cues = list(theme.get("style_cues", []))
    if not (0 <= cue_index < len(cues)):
        return get_theme_channel_note_style(performance_id, theme_index, channel)
    cue = cues[cue_index]
    style = _strip_legacy_note_automation(dict(cue.get("note_style", theme.get("note_style", {}))))
    channels = dict(cue.get("channels", {}))
    channel_data = channels.get(str(channel), {})
    if isinstance(channel_data, dict) and isinstance(channel_data.get("note_style", {}), dict):
        style.update(_strip_legacy_note_automation(dict(channel_data.get("note_style", {}))))
    return _apply_global_note_style_fields(_strip_legacy_note_automation(style))


def set_theme_cue_channel_note_style(
    performance_id: str,
    theme_index: int,
    cue_index: int,
    channel: int,
    note_style: dict,
) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    cues = theme.setdefault("style_cues", [])
    if not (0 <= cue_index < len(cues)):
        return
    cue = cues[cue_index]
    channels = cue.setdefault("channels", {})
    channel_entry = channels.setdefault(str(channel), {})
    cleaned_style = _strip_channel_note_overrides(_strip_legacy_note_automation(dict(note_style)))
    channel_entry["note_style"] = cleaned_style
    save_themes(performance_id, themes)


def has_theme_cue_channel_override(
    performance_id: str,
    theme_index: int,
    cue_index: int,
    channel: int,
) -> bool:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return False
    theme = themes[theme_index]
    _ensure_style_cues(theme)
    cues = list(theme.get("style_cues", []))
    if not (0 <= cue_index < len(cues)):
        return False
    cue = cues[cue_index]
    channels = dict(cue.get("channels", {}))
    channel_data = channels.get(str(channel), {})
    return bool(isinstance(channel_data, dict) and channel_data.get("note_style"))


def set_theme_media(performance_id: str, theme_index: int, media_patch: dict) -> None:
    themes = load_themes(performance_id)
    if not (0 <= theme_index < len(themes)):
        return
    theme = themes[theme_index]
    media = theme.setdefault("media", {})
    media.update(media_patch)
    _ensure_style_cues(theme)
    save_themes(performance_id, themes)
    if get_active_theme_index(performance_id) == theme_index:
        apply_theme_to_config(performance_id, theme_index)
