"""Today: one button that fills your practice time from your Path, the way a teacher plans a lesson.

A session is up to five parts, in this order:
  warm-up   a scale or pattern you already know (the technique strand), the one longest since
            you played it: a start you can't get wrong
  review    a skill you've passed before that has gone longest without practice
  new       the next stop on the active goal's Path (what Next opens); with time to spare, the
            stop after it too
  for fun   the piece you played most recently outside the Atlas (Freeplay)
New comes first in priority (a 5-minute day is just that), then the warm-up, the review and the
piece for fun (before the review if you're learning for songs you love), then a second new stop.
How long you have is what you told Getting to know you, else DEFAULT_MINUTES.

The plan is made once a day and kept in <home>/atlas/today.json, so it stays put while you work
through it. A part is done once you've practiced it since the plan was made: every graded step of
its lesson tried (passed or not; doing it is what counts today, the Atlas keeps the levels), or
for fun, a few seconds played with the piece on the stand. That is worked out from the takes and
the event log each time, like the Atlas's progress.

Practice time today comes from everything you did: takes (their span) and lesson events, merged,
with a gap of up to GAP_SEC between them counting too (reading the next step, a breath between
passes).
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import time

from .. import library
from . import content_dir, mastery, store, user_dir, welcome

TIME_MINUTES = (5, 10, 15, 20)  # welcome.TIME, in order
DEFAULT_MINUTES = 15
PART_MINUTES = {"warmup": 3, "review": 4, "new": 6, "fun": 5}
LABELS = {"warmup": "Warm-up", "review": "Review", "new": "New", "fun": "For fun"}
REVIEW_AFTER_DAYS = 2   # a skill passed more recently than this isn't due a review today
GAP_SEC = 300           # quiet up to this long between things you did still counts as practice
FUN_MIN_SEC = 20        # a take this long on the piece for fun counts
ACTIVE_EVENTS = ("touch",) + store.GRADED_EVENTS


def path() -> pathlib.Path:
    return user_dir() / "today.json"


def day(at: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(at))


def minutes_wanted() -> int:
    """How long you said you practice on most days (Getting to know you), else DEFAULT_MINUTES."""
    data = welcome.load() or {}
    k = (data.get("answers") or {}).get("time")
    return TIME_MINUTES[k] if isinstance(k, int) and 0 <= k < len(TIME_MINUTES) else DEFAULT_MINUTES


def loves_songs() -> bool:
    data = welcome.load() or {}
    return welcome.WHY.index("Playing songs I love") in ((data.get("answers") or {}).get("why") or [])


# -- choosing the parts ---------------------------------------------------------------------


def _known(tree: dict, states: dict, *, played: bool) -> list[dict]:
    """Requirements at Proficient or better whose last stage has a lesson (not a goal's temporary
    nodes). played: only ones you've actually passed, not just been credited with."""
    out = []
    for n in tree["nodes"]:
        if n["level"] != "requirement" or n.get("temporary") or not n.get("stages"):
            continue
        st = states.get(n["id"]) or {}
        if mastery.rank(st.get("level", "not_started")) < mastery.rank("proficient"):
            continue
        if played and not st.get("last_pass"):
            continue
        out.append(n)
    return out


def _first_with_lesson(reqs: list[dict], has_lesson) -> dict | None:
    return next((r for r in reqs if has_lesson(r["stages"][-1])), None)


def warmup(tree: dict, states: dict, has_lesson, skip: set[str] = frozenset()) -> dict | None:
    """A known technique requirement, the one longest since you practiced it (among those, the
    highest grade: the most use to you now)."""
    order = {t["id"]: t["order"] for t in tree["tiers"]}
    reqs = [r for r in _known(tree, states, played=False) if r["strand"] == "technique" and r["id"] not in skip]
    reqs.sort(key=lambda r: ((states[r["id"]].get("last_at") or "")[:10], -order.get(r["tier"], 0)))
    return _first_with_lesson(reqs, has_lesson)


def review(tree: dict, states: dict, has_lesson, today: dt.date, skip: set[str] = frozenset()) -> dict | None:
    """A skill you've passed before: a mastered one due its recheck first, else the one longest
    since its last pass, if that was at least REVIEW_AFTER_DAYS ago."""
    reqs = []
    for r in _known(tree, states, played=True):
        if r["id"] in skip:
            continue
        st = states[r["id"]]
        age = (today - dt.date.fromisoformat(st["last_pass"][:10])).days
        if age >= REVIEW_AFTER_DAYS or mastery.recheck_due(st, today):
            reqs.append(r)
    reqs.sort(key=lambda r: (not mastery.recheck_due(states[r["id"]], today), states[r["id"]]["last_pass"]))
    return _first_with_lesson(reqs, has_lesson)


def for_fun(takes: list[dict], lessons_root: pathlib.Path) -> dict | None:
    """The piece you played most recently outside the Atlas, if it's still there."""
    root = str(lessons_root.resolve()).lower()
    for t in reversed(takes):
        ref = t.get("reference")
        if not ref or t.get("atlas") or t.get("mode") == "record" or str(pathlib.Path(ref).resolve()).lower().startswith(root):
            continue
        if pathlib.Path(ref).is_file():
            return {"file": ref, "title": pathlib.Path(ref).stem}
    return None


def stage_part(kind: str, tree: dict, req: dict, stage: str | None = None) -> dict:
    stage = stage or req["stages"][-1]
    by_id = tree["by_id"]
    tiers = {t["id"]: t["title"] for t in tree["tiers"]}
    detail = by_id[stage]["title"] if stage != req["stages"][-1] or len(req["stages"]) > 1 else ""
    return {"kind": kind, "label": LABELS[kind], "title": req["title"], "detail": detail,
            "where": tiers.get(req["tier"], ""), "requirement": req["id"], "stage": stage, "minutes": PART_MINUTES[kind]}


def make(tree: dict, states: dict, next_stop, has_lesson, takes: list[dict], *, minutes: int | None = None,
         songs_first: bool = False, today: dt.date | None = None) -> dict:
    """A fresh plan. next_stop(skip) -> the Path's next stop ({stage, requirement}) leaving out the
    requirements in skip, or None; has_lesson(stage id) -> bool."""
    today = today or dt.date.today()
    minutes = minutes or DEFAULT_MINUTES
    by_id = tree["by_id"]
    taken: set[str] = set()
    found: dict[str, dict] = {}

    def new() -> dict | None:
        nxt = next_stop(taken)
        if not nxt or nxt["requirement"] not in by_id:
            return None
        taken.add(nxt["requirement"])
        return stage_part("new", tree, by_id[nxt["requirement"]], nxt["stage"])

    def known(kind: str) -> dict | None:
        req = (warmup(tree, states, has_lesson, taken) if kind == "warmup"
               else review(tree, states, has_lesson, today, taken))
        if not req:
            return None
        taken.add(req["id"])
        return stage_part(kind, tree, req)

    def fun() -> dict | None:
        piece = for_fun(takes, content_dir() / "lessons")
        return {"kind": "fun", "label": LABELS["fun"], **piece, "detail": "Freeplay", "minutes": PART_MINUTES["fun"]} if piece else None

    priority = ["new", "warmup"] + (["fun", "review"] if songs_first else ["review", "fun"]) + ["new2"]
    used = 0
    for kind in priority:
        cost = PART_MINUTES[kind.rstrip("2")]
        if found and used + cost > minutes:
            continue
        part = new() if kind.startswith("new") else fun() if kind == "fun" else known(kind)
        if part:
            found[kind] = part
            used += cost
    order = ["warmup", "review", "new", "new2", "fun"]
    return {"day": today.isoformat(), "made": store.now(), "minutes": minutes, "parts": [found[k] for k in order if k in found]}


# -- what's done --------------------------------------------------------------------------


def part_done(part: dict, since: str, attempts: list[dict], events: list[dict], takes: list[dict],
              graded: dict[str, list[str]]) -> bool:
    if part["kind"] == "fun":
        return any((t.get("created") or "") >= since and t.get("reference") == part["file"]
                   and float(t.get("duration_sec") or 0) >= FUN_MIN_SEC for t in takes)
    stage = part["stage"]
    tried = {a.get("step") or mastery.DEFAULT_STEPS[0] for a in attempts if a["node"] == stage and a["at"] >= since}
    steps = graded.get(stage)
    if steps:
        return set(steps) <= tried
    # No graded step: reading and listening through it is doing it.
    return bool(tried) or any(e.get("type") == "touch" and e.get("node") == stage and e.get("at", "") >= since for e in events)


def _ts(at: str) -> float:
    return time.mktime(time.strptime(at[:19], "%Y-%m-%d %H:%M:%S"))


def practice_seconds(takes: list[dict], events: list[dict], on: str) -> int:
    """Seconds practiced on a day ('YYYY-MM-DD'): takes and lesson events merged into spans,
    gaps up to GAP_SEC included."""
    spans = []
    for t in takes:
        if (t.get("created") or "")[:10] == on:
            end = _ts(t["created"])
            spans.append((end - float(t.get("duration_sec") or 0), end))
    for e in events:
        if e.get("type") in ACTIVE_EVENTS and (e.get("at") or "")[:10] == on:
            at = _ts(e["at"])
            spans.append((at, at))
    spans.sort()
    total, start, end = 0.0, None, None
    for a, b in spans:
        if start is None or a - end > GAP_SEC:
            if start is not None:
                total += end - start
            start, end = a, b
        else:
            end = max(end, b)
    if start is not None:
        total += end - start
    return int(total)


# -- the plan on disk ------------------------------------------------------------------------


def load() -> dict | None:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(plan: dict) -> None:
    path().write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")


def remove(plan: dict, which: list[int]) -> list[dict]:
    """Take the parts at these positions out of the plan (kept for the day: it isn't remade until
    tomorrow or Plan again). Returns the parts removed; plan["removed"] counts them all."""
    gone = [p for k, p in enumerate(plan["parts"]) if k in set(which)]
    plan["parts"] = [p for k, p in enumerate(plan["parts"]) if k not in set(which)]
    plan["removed"] = int(plan.get("removed") or 0) + len(gone)
    return gone


def match(plan: dict, said: str) -> list[int]:
    """Positions of the parts `said` names: "all", a part's label ("for fun", "warm-up") or words
    of its title ("thriller"). Empty when nothing matches."""
    words = " ".join(re.sub(r"[^a-z0-9]+", " ", (said or "").lower()).split())
    if not words:
        return []
    parts = plan["parts"]
    if words in ("all", "everything", "the whole plan", "whole plan", "plan"):
        return list(range(len(parts)))

    def norm(text: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())

    by_label = [k for k, p in enumerate(parts) if norm(p.get("label")) == words or p.get("kind") == words.replace(" ", "")]
    if by_label:
        return by_label
    said_words = set(words.split())
    return [k for k, p in enumerate(parts) if said_words <= set(norm(p.get("title")).split())]


def state(plan: dict, graded: dict[str, list[str]], takes: list[dict] | None = None, events: list[dict] | None = None) -> dict:
    """The plan with each part's done flag, the next part to do, and the minutes practiced today."""
    takes = library.list_takes() if takes is None else takes
    events = store.read_events() if events is None else events
    attempts = store.attempts(takes, events)
    parts = [{**p, "done": part_done(p, plan["made"], attempts, events, takes, graded)} for p in plan["parts"]]
    nxt = next((k for k, p in enumerate(parts) if not p["done"]), None)
    return {"day": plan["day"], "minutes": plan["minutes"], "parts": parts, "next": nxt,
            "all_done": bool(parts) and nxt is None, "removed": int(plan.get("removed") or 0),
            "practiced_min": round(practice_seconds(takes, events, plan["day"]) / 60, 1)}
