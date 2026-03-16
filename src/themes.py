"""User-defined theme snapshots — capture, store and apply visual settings.

A theme stores the visual fields that define how notes look and how the LED
strip is coloured.  Themes are persisted in config.json under ``user_themes``.
"""

from __future__ import annotations

from src import config as cfg

# -----------------------------------------------------------------
# Fields captured from note_style → stored with "note_" prefix
# -----------------------------------------------------------------
_NOTE_FIELDS: list[str] = [
    "color_r", "color_g", "color_b",
    "interior_r", "interior_g", "interior_b",
    "inner_blend_percent",
    "glow_strength_percent",
    "highlight_strength_percent",
    "spark_amount_percent",
    "smoke_amount_percent",
    "press_smoke_amount_percent",
    "effect_glow_enabled",
    "effect_highlight_enabled",
    "effect_sparks_enabled",
    "effect_smoke_enabled",
    "effect_press_smoke_enabled",
    "effect_moon_dust_enabled",
    "effect_steam_smoke_enabled",
    "effect_halo_pulse_enabled",
]

# -----------------------------------------------------------------
# Fields captured from led_output → stored with "led_" prefix
# (active colour tracks note colour at runtime — nothing extra to store)
# -----------------------------------------------------------------
_LED_FIELDS: list[str] = []

_NOTE_DEFAULTS: dict[str, int] = {
    "color_r": 0, "color_g": 230, "color_b": 230,
    "interior_r": 120, "interior_g": 255, "interior_b": 255,
    "inner_blend_percent": 35,
    "glow_strength_percent": 80,
    "highlight_strength_percent": 70,
    "spark_amount_percent": 100,
    "smoke_amount_percent": 100,
    "press_smoke_amount_percent": 100,
    "effect_glow_enabled": 1,
    "effect_highlight_enabled": 1,
    "effect_sparks_enabled": 1,
    "effect_smoke_enabled": 1,
    "effect_press_smoke_enabled": 0,
    "effect_moon_dust_enabled": 0,
    "effect_steam_smoke_enabled": 0,
    "effect_halo_pulse_enabled": 0,
}

_LED_DEFAULTS: dict[str, int] = {}


# -----------------------------------------------------------------
# Public API
# -----------------------------------------------------------------

def snapshot_current(name: str) -> dict:
    """Return a new theme dict built from the current config."""
    data = cfg.load()
    note_style = data.get("note_style", {})
    led_cfg = data.get("led_output", {})

    theme: dict = {"name": name}
    for f in _NOTE_FIELDS:
        theme[f"note_{f}"] = int(note_style.get(f, _NOTE_DEFAULTS.get(f, 0)))
    for f in _LED_FIELDS:
        theme[f"led_{f}"] = int(led_cfg.get(f, _LED_DEFAULTS.get(f, 0)))
    return theme


def apply_theme_to_config(theme: dict) -> None:
    """Write a theme's values back into config.json."""
    data = cfg.load()
    note_style = data.setdefault("note_style", {})
    led_cfg = data.setdefault("led_output", {})

    for f in _NOTE_FIELDS:
        key = f"note_{f}"
        if key in theme:
            note_style[f] = int(theme[key])
    for f in _LED_FIELDS:
        key = f"led_{f}"
        if key in theme:
            led_cfg[f] = int(theme[key])
    cfg.save(data)


def build_live_note_style_patch(theme: dict) -> dict[str, int]:
    """Return flat note_style fields extracted from the theme dict.

    Keys in the returned dict match the keys used in ``App._note_style``
    (e.g. ``"color_r"``, ``"effect_glow_enabled"``, …).
    """
    patch: dict[str, int] = {}
    for f in _NOTE_FIELDS:
        key = f"note_{f}"
        if key in theme:
            patch[f] = int(theme[key])
    return patch


def load_user_themes() -> list[dict]:
    """Return the list of user-saved theme dicts from config."""
    return list(cfg.load().get("user_themes", []))


def save_user_themes(themes: list[dict]) -> None:
    """Persist the user-saved theme list to config."""
    data = cfg.load()
    data["user_themes"] = themes
    cfg.save(data)


def get_active_index() -> int:
    """Return the index of the currently active user theme (0-based)."""
    return int(cfg.load().get("active_user_theme_index", 0))


def set_active_index(index: int) -> None:
    """Save the active user theme index to config."""
    data = cfg.load()
    data["active_user_theme_index"] = index
    cfg.save(data)
