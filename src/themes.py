"""Theme hierarchy management — banks, presets, themes, and channel styles.

A **bank** is a named song/project folder (e.g., "Song1").
A **preset** is a named section within a bank (e.g., "Chorus").
A **theme** is a named color scheme + background image snapshot at preset level.

Each bank has the shape::

    {
        "name": "Song1",
        "presets": [
            {
                "name": "Chorus",
                "themes": [
                    {
                        "name": "Blue Chill",
                        "background_image": "path/to/image.png",
                        "channels": {
                            "1": {"note_color_r": 86, "note_color_g": 128, ...},
                            ...  # channels 1-16
                        }
                    }
                ]
            }
        ]
    }
"""

from __future__ import annotations

from src import config as cfg

# -----------------------------------------------------------------
# Note-style fields captured per channel, stored with "note_" prefix
# -----------------------------------------------------------------
_NOTE_FIELDS: list[str] = [
    "color_h", "color_s", "color_v",
    "color_r", "color_g", "color_b",
    "interior_h", "interior_s", "interior_v",
    "interior_r", "interior_g", "interior_b",
    "glow_color_h", "glow_color_s", "glow_color_v",
    "glow_color_r", "glow_color_g", "glow_color_b",
    "highlight_color_h", "highlight_color_s", "highlight_color_v",
    "highlight_color_r", "highlight_color_g", "highlight_color_b",
    "spark_color_h", "spark_color_s", "spark_color_v",
    "spark_color_r", "spark_color_g", "spark_color_b",
    "ember_color_h", "ember_color_s", "ember_color_v",
    "ember_color_r", "ember_color_g", "ember_color_b",
    "smoke_color_h", "smoke_color_s", "smoke_color_v",
    "smoke_color_r", "smoke_color_g", "smoke_color_b",
    "mist_color_h", "mist_color_s", "mist_color_v",
    "mist_color_r", "mist_color_g", "mist_color_b",
    "dust_color_h", "dust_color_s", "dust_color_v",
    "dust_color_r", "dust_color_g", "dust_color_b",
    "steam_color_h", "steam_color_s", "steam_color_v",
    "steam_color_r", "steam_color_g", "steam_color_b",
    "inner_blend_percent",
    "glow_strength_percent",
    "highlight_strength_percent",
    "spark_amount_percent",
    "smoke_amount_percent",
    "press_smoke_amount_percent",
    "effect_glow_enabled",
    "effect_highlight_enabled",
    "effect_sparks_enabled",
    "effect_embers_enabled",
    "effect_smoke_enabled",
    "effect_press_smoke_enabled",
    "effect_moon_dust_enabled",
    "effect_steam_smoke_enabled",
    "effect_halo_pulse_enabled",
]

# -----------------------------------------------------------------
# (active colour tracks note colour at runtime — nothing extra needed)
# -----------------------------------------------------------------

_NOTE_DEFAULTS: dict[str, int] = {
    "color_h": 180, "color_s": 100, "color_v": 90,
    "color_r": 0, "color_g": 230, "color_b": 230,
    "interior_h": 180, "interior_s": 53, "interior_v": 100,
    "interior_r": 120, "interior_g": 255, "interior_b": 255,
    "glow_color_h": 180, "glow_color_s": 100, "glow_color_v": 90,
    "glow_color_r": 0, "glow_color_g": 230, "glow_color_b": 230,
    "highlight_color_h": 180, "highlight_color_s": 100, "highlight_color_v": 90,
    "highlight_color_r": 0, "highlight_color_g": 230, "highlight_color_b": 230,
    "spark_color_h": 180, "spark_color_s": 100, "spark_color_v": 90,
    "spark_color_r": 0, "spark_color_g": 230, "spark_color_b": 230,
    "ember_color_h": 180, "ember_color_s": 100, "ember_color_v": 90,
    "ember_color_r": 0, "ember_color_g": 230, "ember_color_b": 230,
    "smoke_color_h": 180, "smoke_color_s": 100, "smoke_color_v": 90,
    "smoke_color_r": 0, "smoke_color_g": 230, "smoke_color_b": 230,
    "mist_color_h": 180, "mist_color_s": 53, "mist_color_v": 100,
    "mist_color_r": 120, "mist_color_g": 255, "mist_color_b": 255,
    "dust_color_h": 180, "dust_color_s": 53, "dust_color_v": 100,
    "dust_color_r": 120, "dust_color_g": 255, "dust_color_b": 255,
    "steam_color_h": 180, "steam_color_s": 100, "steam_color_v": 90,
    "steam_color_r": 0, "steam_color_g": 230, "steam_color_b": 230,
    "inner_blend_percent": 35,
    "glow_strength_percent": 80,
    "highlight_strength_percent": 70,
    "spark_amount_percent": 100,
    "smoke_amount_percent": 100,
    "press_smoke_amount_percent": 100,
    "effect_glow_enabled": 1,
    "effect_highlight_enabled": 1,
    "effect_sparks_enabled": 1,
    "effect_embers_enabled": 0,
    "effect_smoke_enabled": 1,
    "effect_press_smoke_enabled": 0,
    "effect_moon_dust_enabled": 0,
    "effect_steam_smoke_enabled": 0,
    "effect_halo_pulse_enabled": 0,
}


# -----------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------

def _snapshot_channel(note_style: dict) -> dict:
    """Snapshot one channel's note_style into a note_-prefixed dict."""
    return {
        f"note_{f}": int(note_style.get(f, _NOTE_DEFAULTS.get(f, 0)))
        for f in _NOTE_FIELDS
    }


# -----------------------------------------------------------------
# Core snapshot/apply functions (for themes with background image)
# -----------------------------------------------------------------

def snapshot_theme(name: str, background_image: str | None = None) -> dict:
    """Return a new theme dict capturing all 16 channels + background image."""
    data = cfg.load()
    all_styles = data.get("note_style", {})
    channels = {
        str(ch): _snapshot_channel(all_styles.get(str(ch), {}))
        for ch in range(1, 17)
    }
    theme = {
        "name": name,
        "channels": channels,
    }
    if background_image:
        theme["background_image"] = background_image
    return theme


def apply_theme_to_config(theme: dict) -> None:
    """Write all channel settings from a theme back into config.json."""
    data = cfg.load()
    all_styles = data.setdefault("note_style", {})
    for ch_key, ch_snap in theme.get("channels", {}).items():
        ch_style = all_styles.setdefault(ch_key, {})
        for f in _NOTE_FIELDS:
            key = f"note_{f}"
            if key in ch_snap:
                ch_style[f] = int(ch_snap[key])
    
    # Also apply background media to display_style (legacy top-level keys are ignored).
    display = data.setdefault("display_style", {})
    if "background_image" in theme:
        display["background_image"] = str(theme["background_image"])
    if "background_transition_percent" in theme:
        display["background_transition_percent"] = int(theme["background_transition_percent"])
    
    cfg.save(data)


# -----------------------------------------------------------------
# Hierarchical navigation and management
# -----------------------------------------------------------------

def load_banks() -> list[dict]:
    """Return the list of user-saved bank dicts from config."""
    banks = cfg.load().get("banks", [])
    # Ensure all banks have themes array (current format).
    for bank in banks:
        if "themes" not in bank:
            bank["themes"] = []

    # Legacy compatibility: preserve old preset structure if present.
    # (Can be removed after migration period.)
        if "presets" not in bank:
            bank["presets"] = []
        # Ensure all presets have themes array
        for preset in bank.get("presets", []):
            if "themes" not in preset:
                preset["themes"] = []
    return banks


def save_banks(banks: list[dict]) -> None:
    """Persist the bank list to config."""
    data = cfg.load()
    data["banks"] = banks
    cfg.save(data)


def create_bank(name: str) -> dict:
    """Create a new empty bank."""
    return {"name": name, "themes": [], "presets": []}


def create_preset(name: str) -> dict:
    """Create a new empty preset within a bank."""
    return {"name": name, "themes": []}


def get_active_bank_index() -> int:
    """Return the index of the currently active bank (0-based)."""
    return int(cfg.load().get("active_bank_index", 0))


def set_active_bank_index(index: int) -> None:
    """Save the active bank index to config."""
    data = cfg.load()
    data["active_bank_index"] = index
    cfg.save(data)


def get_active_preset_index() -> int:
    """Return the index of the currently active preset within the active bank."""
    return int(cfg.load().get("active_preset_index", 0))


def set_active_preset_index(index: int) -> None:
    """Save the active preset index to config."""
    data = cfg.load()
    data["active_preset_index"] = index
    cfg.save(data)


def get_active_theme_index() -> int:
    """Return the index of the currently active theme within the active preset."""
    return int(cfg.load().get("active_theme_index", 0))


def set_active_theme_index(index: int) -> None:
    """Save the active theme index to config."""
    data = cfg.load()
    data["active_theme_index"] = index
    cfg.save(data)


# -----------------------------------------------------------------
# Legacy shims — keep old callers working during transition
# -----------------------------------------------------------------

def snapshot_bank(name: str) -> dict:
    """Legacy: return a new bank dict (now just creates structure)."""
    return create_bank(name)


def apply_bank_to_config(bank: dict) -> None:
    """Apply the active theme from a bank to config (note + display media)."""
    # Current schema: bank['themes'][active_theme_index]
    themes = bank.get("themes", []) if isinstance(bank, dict) else []
    if themes:
        idx = max(0, min(len(themes) - 1, get_active_theme_index()))
        apply_theme_to_config(themes[idx])
        return

    # Legacy schema fallback: bank['presets'][0]['themes'][0]
    if bank.get("presets"):
        if bank["presets"][0].get("themes"):
            theme = bank["presets"][0]["themes"][0]
            apply_theme_to_config(theme)


def build_live_note_style_patch(theme_or_bank: dict, channel: str = "1") -> dict[str, int]:
    """Return flat note_style fields for a channel from a theme or bank.

    Keys match those used in ``App._note_style`` (e.g. ``"color_r"``).
    Falls back to channel 1 if the requested channel isn't in the theme.
    """
    theme = theme_or_bank if isinstance(theme_or_bank, dict) else {}
    if "channels" not in theme:
        themes = theme.get("themes", []) if isinstance(theme, dict) else []
        if themes:
            idx = max(0, min(len(themes) - 1, get_active_theme_index()))
            theme = themes[idx]

    channels = theme.get("channels", {}) if isinstance(theme, dict) else {}
    ch_snap = channels.get(channel) or channels.get("1") or {}
    return {
        f: int(ch_snap[f"note_{f}"])
        for f in _NOTE_FIELDS
        if f"note_{f}" in ch_snap
    }


def snapshot_current(name: str, channel: str = "1") -> dict:
    return snapshot_theme(name)


def apply_theme_to_config_legacy(bank: dict, channel: str = None) -> None:
    apply_bank_to_config(bank)


def load_user_themes() -> list[dict]:
    return load_banks()


def save_user_themes(banks: list[dict]) -> None:
    save_banks(banks)


def get_active_index() -> int:
    return get_active_bank_index()


def set_active_index(index: int) -> None:
    set_active_bank_index(index)
