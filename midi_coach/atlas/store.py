"""Your Atlas data in <home>/atlas: the event log, goals, temporary nodes, exam results.

Graded attempts are stored on the takes themselves (take meta 'atlas': {node, step,
passed, score}), with the verdict decided when the take was graded, so progress never
depends on re-grading. Everything else that counts (a read step done, a quiz answer, a
sung echo, credits, demotions, review sessions, exam results) is a line in events.jsonl.
progress.json is only a cache: progress() rebuilds it whenever the takes or the log change.
"""

from __future__ import annotations

import json
import pathlib
import time

from .. import library
from . import content_dir, mastery, user_dir

GRADED_EVENTS = ("quiz", "sing", "tap", "step")  # events carrying a graded verdict


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def events_path() -> pathlib.Path:
    return user_dir() / "events.jsonl"


def append_event(kind: str, **fields) -> dict:
    event = {"type": kind, "at": fields.pop("at", None) or now(), **fields}
    with events_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events() -> list[dict]:
    try:
        lines = events_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a line cut short by a crash; the rest still counts
    return out


def attempts(takes: list[dict] | None = None, events: list[dict] | None = None) -> list[dict]:
    """Every graded attempt: from takes (played steps) and from events (quiz, sing, tap)."""
    out = []
    for t in library.list_takes() if takes is None else takes:
        a = t.get("atlas")
        if a and a.get("node") and "passed" in a:
            out.append({"node": a["node"], "step": a.get("step"), "passed": bool(a["passed"]),
                        "score": a.get("score"), "at": t.get("created") or now(), "take": t.get("id")})
    for e in read_events() if events is None else events:
        if e.get("type") in GRADED_EVENTS and e.get("node") and "passed" in e:
            out.append({"node": e["node"], "step": e.get("step"), "passed": bool(e["passed"]),
                        "score": e.get("score"), "at": e["at"]})
    return out


def graded_steps(atlas: dict) -> dict[str, list[str]]:
    """Stage id -> its lesson's graded step ids (stages without a lesson yet use one step):
    the base lessons, and the temporary nodes' in <home>/atlas/lessons."""
    out = {}
    for folder in (content_dir() / "lessons", user_dir() / "lessons"):
        if not folder.is_dir():
            continue
        for f in folder.glob("*.json"):
            try:
                lesson = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            ids = [s["id"] for s in lesson.get("steps", []) if s.get("graded")]
            if ids:
                out[lesson["id"]] = ids
    return out


def _stamp(atlas: dict) -> list:
    """What progress depends on: the tree's version, the takes and the event log."""
    takes = library.profile_home() / "takes"
    def m(p: pathlib.Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    return [atlas.get("version"), len(atlas["nodes"]), m(events_path()), m(takes), len(list(takes.glob("*.json"))),
            m(user_dir() / "nodes.json"), m(user_dir() / "lessons")]


def progress(atlas: dict, rebuild: bool = False) -> dict:
    """{node id: state} (mastery.compute), from the cache when nothing changed."""
    cache = user_dir() / "progress.json"
    stamp = _stamp(atlas)
    if not rebuild:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("stamp") == stamp:
                return data["states"]
        except (OSError, ValueError):
            pass
    events = read_events()
    states = mastery.compute(atlas, attempts(events=events), events, graded_steps(atlas))
    try:
        cache.write_text(json.dumps({"stamp": stamp, "rebuilt": now(), "states": states}), encoding="utf-8")
    except OSError:
        pass
    return states


# -- goals ----------------------------------------------------------------------------


def goals_path() -> pathlib.Path:
    return user_dir() / "goals.json"


def load_goals() -> dict:
    try:
        return json.loads(goals_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"active": None, "goals": []}


def save_goals(data: dict) -> None:
    goals_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
