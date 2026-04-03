"""Metadata for MIDI-mappable live performance actions."""

from __future__ import annotations


ACTION_DEFS: list[dict[str, str | int]] = [
    {
        "id": "performance.theme_next",
        "label": "Next Theme",
        "category": "Performance",
        "mode": "trigger",
        "threshold": 64,
    },
    {
        "id": "performance.theme_previous",
        "label": "Previous Theme",
        "category": "Performance",
        "mode": "trigger",
        "threshold": 64,
    },
    {
        "id": "performance.theme_select_1",
        "label": "Select Theme 1",
        "category": "Performance",
        "mode": "trigger",
        "threshold": 64,
    },
    {
        "id": "performance.theme_select_2",
        "label": "Select Theme 2",
        "category": "Performance",
        "mode": "trigger",
        "threshold": 64,
    },
    {
        "id": "performance.theme_select_3",
        "label": "Select Theme 3",
        "category": "Performance",
        "mode": "trigger",
        "threshold": 64,
    },
    {
        "id": "performance.theme_select_4",
        "label": "Select Theme 4",
        "category": "Performance",
        "mode": "trigger",
        "threshold": 64,
    },
    {
        "id": "effects.glow_toggle",
        "label": "Glow Toggle",
        "category": "Effects",
        "mode": "toggle",
        "threshold": 64,
    },
    {
        "id": "effects.sparks_toggle",
        "label": "Sparks Toggle",
        "category": "Effects",
        "mode": "toggle",
        "threshold": 64,
    },
    {
        "id": "effects.smoke_toggle",
        "label": "Smoke Toggle",
        "category": "Effects",
        "mode": "toggle",
        "threshold": 64,
    },
    {
        "id": "effects.glow_strength",
        "label": "Glow Strength",
        "category": "Effects",
        "mode": "continuous",
    },
    {
        "id": "effects.spark_amount",
        "label": "Spark Amount",
        "category": "Effects",
        "mode": "continuous",
    },
    {
        "id": "effects.smoke_amount",
        "label": "Smoke Amount",
        "category": "Effects",
        "mode": "continuous",
    },
    {
        "id": "visual.note_speed",
        "label": "Note Rise Speed",
        "category": "Visual",
        "mode": "continuous",
    },
    {
        "id": "visual.note_width",
        "label": "Note Width",
        "category": "Visual",
        "mode": "continuous",
    },
    {
        "id": "visual.background_alpha",
        "label": "Background Alpha",
        "category": "Visual",
        "mode": "continuous",
    },
    {
        "id": "keyboard.visible_toggle",
        "label": "Keyboard Visible",
        "category": "Keyboard",
        "mode": "toggle",
        "threshold": 64,
    },
]

_ACTION_DEF_BY_ID = {str(action["id"]): action for action in ACTION_DEFS}


def get_action_defs() -> list[dict[str, str | int]]:
    """Return all action definitions in display order."""
    return list(ACTION_DEFS)


def get_action_def(action_id: str) -> dict[str, str | int] | None:
    """Return the action definition for *action_id*, if known."""
    return _ACTION_DEF_BY_ID.get(action_id)


def get_actions_grouped() -> dict[str, list[dict[str, str | int]]]:
    """Return actions grouped by category for settings UIs."""
    grouped: dict[str, list[dict[str, str | int]]] = {}
    for action in ACTION_DEFS:
        category = str(action["category"])
        grouped.setdefault(category, []).append(action)
    return grouped
