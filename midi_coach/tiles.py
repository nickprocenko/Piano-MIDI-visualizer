"""The Maestro panel's quick-action tiles: which show on each part of the coach page.

A layout is a list of tile ids per view, kept per profile in <profile>/tiles.json; a view never
changed shows its defaults. The page (coach.html's TILES) knows what each tile does; this module
only knows the ids, so the Maestro's set_tiles and the page's edit mode agree on them.
"""

import json
import logging

from . import profiles

log = logging.getLogger(__name__)

# id -> what it does (also what the Maestro is told)
TILES = {
    "play": "Start or stop a run in the current mode (Learn, Rehearse, Listen; Record on Record)",
    "start": "Jump back to the first bar",
    "loop": "Loop on or off",
    "metronome": "Metronome on or off",
    "slower": "Tempo down 10%",
    "faster": "Tempo up 10%",
    "record": "Go to Record a new idea",
    "today": "Today's practice: the next thing on the plan",
    "next": "Open the next stop on the Path",
    "planner": "The Roadmap's Planner",
    "exam": "Mock exams",
    "continue": "Back to the Session with the last piece",
}

# The page's parts: Session ("practice", with Explore), Roadmap ("progress", with its lessons).
VIEWS = ("home", "practice", "record", "progress", "youtube")
VIEW_NAMES = {"home": "Home", "practice": "Session", "record": "Record", "progress": "Roadmap", "youtube": "YouTube"}

DEFAULTS = {
    "practice": ["play", "start", "loop", "metronome", "slower", "faster", "record"],
    "progress": ["today", "next", "planner", "exam"],
    "home": ["today", "continue"],
    "record": ["play", "metronome"],
    "youtube": ["play", "metronome"],
}


def _path():
    return profiles.data_dir() / "tiles.json"


def _saved() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def layouts() -> dict:
    """Every view's tiles: what was saved, else the defaults."""
    saved = _saved()
    return {v: [t for t in saved.get(v, DEFAULTS[v]) if t in TILES] for v in VIEWS}


def save(view: str, tiles: list) -> dict:
    """Set one view's tiles (in order, each once). Returns {view, tiles} or {error}."""
    if view not in VIEWS:
        return {"error": f"No view {view!r}; the views are {', '.join(VIEWS)}."}
    unknown = [t for t in tiles if t not in TILES]
    if unknown:
        return {"error": f"No tile {unknown[0]!r}; the tiles are {', '.join(TILES)}."}
    tiles = list(dict.fromkeys(tiles))
    data = _saved()
    data[view] = tiles
    try:
        _path().write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError as exc:
        return {"error": f"Couldn't save the tiles: {exc}"}
    return {"view": view, "tiles": tiles}


def change(view: str, add=(), remove=(), reset: bool = False) -> dict:
    """The Maestro's set_tiles: add tiles (at the end, or moved there), take some off, or put
    the view back to its defaults."""
    if view not in VIEWS:
        return {"error": f"No view {view!r}; the views are {', '.join(VIEWS)}."}
    now = list(DEFAULTS[view]) if reset else layouts()[view]
    now = [t for t in now if t not in set(remove) | set(add)] + list(add)
    return save(view, now)
