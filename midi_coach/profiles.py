"""Local profiles: each person who practices on this computer gets their own takes, part
choices, lessons, Maestro notes and Atlas progress.

The profile list is <home>/profiles.json. The Default profile keeps its data directly in
<home> (what existed before profiles, so nothing moves); any other profile lives in
<home>/profiles/<id>. Shared things stay in <home>: the song library, the Atlas content and
pieces, derived caches, the speech models and the API key. Deleting a profile only removes
it from the list; its folder is left on disk.
"""

from __future__ import annotations

import json
import re
import time

from . import library

DEFAULT_ID = "default"
MAX_NAME = 30


def _path():
    return library.home() / "profiles.json"


def load() -> dict:
    """{'active': id, 'profiles': [{id, name, created}]} - always with the Default profile first."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    profiles = [p for p in data.get("profiles", []) if isinstance(p, dict) and p.get("id") and p.get("name")]
    if not any(p["id"] == DEFAULT_ID for p in profiles):
        profiles.insert(0, {"id": DEFAULT_ID, "name": "Default", "created": None})
    active = data.get("active") if any(p["id"] == data.get("active") for p in profiles) else DEFAULT_ID
    return {"active": active, "profiles": profiles}


def _save(data: dict) -> None:
    _path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def active() -> dict:
    data = load()
    return next(p for p in data["profiles"] if p["id"] == data["active"])


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


def create(name: str, select: bool = True) -> dict:
    name = _clean(name)
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
    profile = {"id": pid, "name": name, "created": time.strftime("%Y-%m-%d")}
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
