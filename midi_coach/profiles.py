"""Local profiles: each person who practices on this computer gets their own takes, part
choices, lessons, Maestro notes and Atlas progress.

The profile list is <home>/profiles.json. The Default profile keeps its data directly in
<home> (what existed before profiles, so nothing moves); any other profile lives in
<home>/profiles/<id>. Shared things stay in <home>: the song library, the Atlas content and
pieces, derived caches, the speech models and the API key. Deleting a profile only removes
it from the list; its folder is left on disk.

A profile learns one or more instruments, like courses: piano (the keyboard, over MIDI) or
flute (the microphone, pitch-tracked on the coach page), and plays one of them at a time (picked
on Home). The current instrument picks the Roadmap, the default input, the music the coach
writes and how the Maestro teaches. Each instrument keeps its own Roadmap progress: the first
one a profile learnt in <profile>/atlas (where it always was), any added later in
<profile>/atlas-<instrument>. Takes, lessons and the Maestro's notes are the person's, shared.

A profile can be a young learner (a child from about four): the Maestro talks to them in
short, simple words, the coach page reads each lesson step aloud in bigger print, and a new
piano profile starts on the Atlas's First steps.
"""

from __future__ import annotations

import json
import re
import time

from . import library

DEFAULT_ID = "default"
MAX_NAME = 30
INSTRUMENTS = ("piano", "flute")


def _path():
    return library.home() / "profiles.json"


def load() -> dict:
    """{'active': id, 'profiles': [{id, name, created, instrument, instruments, young}]} - always with
    the Default profile first. instrument is the current one, instruments every one learnt, first first."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    profiles = [p for p in data.get("profiles", []) if isinstance(p, dict) and p.get("id") and p.get("name")]
    if not any(p["id"] == DEFAULT_ID for p in profiles):
        profiles.insert(0, {"id": DEFAULT_ID, "name": "Default", "created": None})
    for p in profiles:
        if p.get("instrument") not in INSTRUMENTS:
            p["instrument"] = "piano"
        learnt = [i for i in p.get("instruments") or [] if i in INSTRUMENTS]
        p["instruments"] = list(dict.fromkeys(learnt + [p["instrument"]]))
        p["young"] = bool(p.get("young"))
    active = data.get("active") if any(p["id"] == data.get("active") for p in profiles) else DEFAULT_ID
    return {"active": active, "profiles": profiles}


def _save(data: dict) -> None:
    _path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def active() -> dict:
    data = load()
    return next(p for p in data["profiles"] if p["id"] == data["active"])


def instrument() -> str:
    """The active profile's instrument: 'piano' or 'flute'."""
    return active()["instrument"]


def atlas_folder() -> str:
    """The active profile's Roadmap folder name for its current instrument: 'atlas' for the first
    instrument it learnt, 'atlas-<instrument>' for one added later."""
    p = active()
    return "atlas" if p["instrument"] == p["instruments"][0] else f"atlas-{p['instrument']}"


def young() -> bool:
    """Whether the active profile is a young learner."""
    return active()["young"]


def data_dir():
    """Where the active profile's own data lives."""
    root = library.home()
    pid = load()["active"]
    if pid == DEFAULT_ID:
        return root
    path = root / "profiles" / pid
    (path / "takes").mkdir(parents=True, exist_ok=True)
    return path


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()[:MAX_NAME]


def create(name: str, select: bool = True, instrument: str = "piano", young: bool = False) -> dict:
    name = _clean(name)
    if instrument not in INSTRUMENTS:
        raise ValueError(f"The instrument must be one of {', '.join(INSTRUMENTS)}.")
    if not name:
        raise ValueError("Give the profile a name.")
    data = load()
    if any(p["name"].lower() == name.lower() for p in data["profiles"]):
        raise ValueError(f"There is already a profile called {name!r}.")
    stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "profile"
    taken = {p["id"] for p in data["profiles"]}
    pid, k = stem, 1
    while pid in taken:
        k += 1
        pid = f"{stem}-{k}"
    profile = {"id": pid, "name": name, "created": time.strftime("%Y-%m-%d"), "instrument": instrument,
               "instruments": [instrument], "young": bool(young)}
    data["profiles"].append(profile)
    if select:
        data["active"] = pid
    _save(data)
    return profile


def select(pid: str) -> dict:
    data = load()
    if not any(p["id"] == pid for p in data["profiles"]):
        raise ValueError("No such profile.")
    data["active"] = pid
    _save(data)
    return active()


def rename(pid: str, name: str) -> dict:
    name = _clean(name)
    data = load()
    if not name:
        raise ValueError("Give the profile a name.")
    if any(p["name"].lower() == name.lower() and p["id"] != pid for p in data["profiles"]):
        raise ValueError(f"There is already a profile called {name!r}.")
    for p in data["profiles"]:
        if p["id"] == pid:
            p["name"] = name
            _save(data)
            return p
    raise ValueError("No such profile.")


def set_instrument(pid: str, instrument: str) -> dict:
    """Play another instrument on this profile, adding it to the ones it learns if it's new."""
    if instrument not in INSTRUMENTS:
        raise ValueError(f"The instrument must be one of {', '.join(INSTRUMENTS)}.")
    data = load()
    for p in data["profiles"]:
        if p["id"] == pid:
            p["instrument"] = instrument
            if instrument not in p["instruments"]:
                p["instruments"].append(instrument)
            _save(data)
            return p
    raise ValueError("No such profile.")


def set_young(pid: str, young: bool) -> dict:
    data = load()
    for p in data["profiles"]:
        if p["id"] == pid:
            p["young"] = bool(young)
            _save(data)
            return p
    raise ValueError("No such profile.")


def delete(pid: str) -> dict:
    """Forget a profile (its folder stays on disk). The Default profile can't be deleted."""
    if pid == DEFAULT_ID:
        raise ValueError("The Default profile can't be deleted.")
    data = load()
    if not any(p["id"] == pid for p in data["profiles"]):
        raise ValueError("No such profile.")
    data["profiles"] = [p for p in data["profiles"] if p["id"] != pid]
    if data["active"] == pid:
        data["active"] = DEFAULT_ID
    _save(data)
    return load()
