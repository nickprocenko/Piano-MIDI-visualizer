"""Placement: finding your level with full mock exams.

It starts at the grade you name. A pass climbs to the next grade, until the first fail. If
the very first exam fails, it steps down a grade at a time until one passes (or Initial
fails). Then:
  - every grade up to the highest one passed is credited (a 'placement_credit' event per
    tier: its stages count as Proficient - passing Grade 3 vouches for Grade 2 too);
  - the first grade failed becomes a goal (goals.json), with the failed exam's weakest
    items first on its Path.
Passing Grade 8 places you beyond the Atlas: everything is credited and no goal is set.

The run is saved in <home>/atlas/placement.json; each exam is an ordinary ExamSession
(tagged 'placement'), so it can be paused and picked up like any exam.
"""

from __future__ import annotations

import json
import pathlib

from . import load_atlas, mastery, marking, store, user_dir
from .exam import ExamSession

PIECE_WEAK = 20      # a piece below the pass mark (of 30)
SCALE_WEAK = 65      # a scale's quality below what passes the section
SIGHT_WEAK = 60
AURAL_WEAK = 0.67


def path() -> pathlib.Path:
    return user_dir() / "placement.json"


def load() -> dict | None:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(data: dict) -> None:
    path().write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def passed(total: float) -> bool:
    return marking.band(total) != "Below pass"


def next_tier(order: list[str], start: str, results: list[tuple[str, bool]]) -> str | None:
    """Which grade to sit next, or None when placement is decided. results: (tier, passed)
    for the exams so far, in the order they were sat."""
    if not results:
        return start
    k = order.index(results[-1][0])
    first_passed = results[0][1]
    if first_passed:  # climbing: on until the first fail
        if not results[-1][1]:
            return None
        return order[k + 1] if k + 1 < len(order) else None
    # The first exam failed: step down until one passes.
    if results[-1][1]:
        return None
    return order[k - 1] if k > 0 else None


def outcome(order: list[str], results: list[tuple[str, bool]]) -> dict:
    """{credited: tiers up to the highest passed, goal: the first grade failed above them (or
    None past Grade 8)}."""
    best = max((order.index(t) for t, ok in results if ok), default=-1)
    goal = order[best + 1] if best + 1 < len(order) else None
    return {"credited": order[:best + 1], "goal": goal}


def weak_items(exam: dict) -> list[str]:
    """A finished exam's weakest requirements, weakest first: pieces below the pass mark,
    scales and aural tests that went badly, and the grade's sight-reading if that did."""
    atlas = load_atlas()
    scored: list[tuple[float, str]] = []
    for t in exam["tasks"]:
        res = t.get("result") or {}
        if t["kind"] == "piece" and res.get("mark", 0) < PIECE_WEAK:
            scored.append((res.get("mark", 0) / 30, t["req"]))
        elif t["kind"] == "scale" and res.get("q", 0) < SCALE_WEAK:
            scored.append((res.get("q", 0) / 100, t["req"]))
        elif t["kind"] == "aural" and res.get("q", 0) < AURAL_WEAK:
            scored.append((res.get("q", 0), t["req"]))
        elif t["kind"] == "sight" and res.get("q", 0) < SIGHT_WEAK:
            sight = [n["id"] for n in atlas["nodes"] if n["level"] == "requirement" and n["tier"] == exam["tier"]
                     and n["strand"] == "sight"]
            final = [r for r in sight if ".standard" in r] or sight[-1:]
            scored += [(res.get("q", 0) / 100, r) for r in final]
    scored.sort(key=lambda x: x[0])
    return list(dict.fromkeys(r for _, r in scored))


class Placement:
    """A placement run: which exam is going, what has been decided."""

    def __init__(self, data: dict) -> None:
        self.data = data

    @classmethod
    def start(cls, tier: str) -> "Placement":
        atlas = load_atlas()
        order = [t["id"] for t in sorted(atlas["tiers"], key=lambda t: t["order"])]
        if tier not in order:
            raise ValueError(f"No grade {tier!r}.")
        old = cls.current()
        if old and old.data.get("exam"):
            running = _exam(old.data["exam"])
            if running and not running.done:
                running.abort()
        data = {"status": "running", "start": tier, "order": order, "started": store.now(), "exams": [], "exam": None}
        return cls(data)

    @classmethod
    def current(cls) -> "Placement | None":
        data = load()
        return cls(data) if data and data.get("status") in ("running", "paused") else None

    def save(self) -> None:
        save(self.data)

    @property
    def results(self) -> list[tuple[str, bool]]:
        return [(e["tier"], e["passed"]) for e in self.data["exams"]]

    def next_tier(self) -> str | None:
        return next_tier(self.data["order"], self.data["start"], self.results)

    def begin_exam(self, states: dict | None = None, seed: int | None = None) -> ExamSession:
        """The next exam (or the one already going for this placement)."""
        if self.data.get("exam"):
            exam = _exam(self.data["exam"])
            if exam and not exam.done:
                self.data["status"] = "running"
                self.save()
                return exam
        tier = self.next_tier()
        if tier is None:
            raise ValueError("Placement is already decided.")
        exam = ExamSession.new(tier, seed=seed, states=states)
        exam.data["placement"] = True
        exam.save()
        self.data.update(exam=exam.id, status="running")
        self.save()
        return exam

    def exam_done(self, exam: ExamSession) -> None:
        """A placement exam was finished: record it, and settle the placement if it's decided."""
        if exam.id != self.data.get("exam") or exam.data["status"] != "done":
            return
        total = exam.data["result"]["total"]
        self.data["exams"].append({"tier": exam.data["tier"], "exam": exam.id, "total": total, "passed": passed(total)})
        self.data["exam"] = None
        if self.next_tier() is None:
            self.finish()
        self.save()

    def pause(self) -> None:
        self.data["status"] = "paused"
        self.save()

    def finish(self) -> None:
        """Credit the grades passed and set the first grade failed as the goal."""
        out = outcome(self.data["order"], self.results)
        for tier in out["credited"]:
            store.append_event("placement_credit", tier=tier, placement=self.data["started"])
        weak: list[str] = []
        goal_id = None
        if out["goal"]:
            failed = next((e for e in self.data["exams"] if e["tier"] == out["goal"]), None)
            if failed:
                weak = weak_items(ExamSession.load(failed["exam"]).data)
            goal_id = _set_goal(out["goal"], weak)
        self.data.update(status="done", finished=store.now(), credited=out["credited"], goal_tier=out["goal"],
                         goal=goal_id, weak=weak)

    def state(self) -> dict:
        """For the page: the exams so far, what comes next, and (when done) where you landed."""
        atlas = load_atlas()
        titles = {t["id"]: t["title"] for t in atlas["tiers"]}
        nxt = self.next_tier() if self.data["status"] != "done" else None
        out = {"status": self.data["status"], "start": self.data["start"], "exam": self.data.get("exam"),
               "exams": [{**e, "title": titles[e["tier"]]} for e in self.data["exams"]],
               "next": nxt, "next_title": titles.get(nxt)}
        if self.data["status"] == "done":
            credited = self.data.get("credited") or []
            goal = self.data.get("goal_tier")
            if goal:
                summary = f"Placed at {titles[goal]}. "
                summary += (f"{titles[credited[0]]} to {titles[credited[-1]]} credited; " if len(credited) > 1
                            else f"{titles[credited[0]]} credited; " if credited else "")
                summary += f"{titles[goal]} is your goal, its weakest items first."
            else:
                summary = "Placed beyond Grade 8: every grade is credited."
            out.update(credited=credited, goal_tier=goal, goal_title=titles.get(goal), summary=summary,
                       weak=[{"id": r, "title": atlas["by_id"][r]["title"]} for r in self.data.get("weak", []) if r in atlas["by_id"]])
        return out


def _exam(exam_id: str) -> ExamSession | None:
    try:
        return ExamSession.load(exam_id)
    except (OSError, ValueError):
        return None


def _set_goal(tier: str, weak: list[str]) -> str:
    """The grade to work towards, as the active goal; its Path puts the weak items first."""
    atlas = load_atlas()
    title = next(t["title"] for t in atlas["tiers"] if t["id"] == tier)
    states = store.progress(atlas, rebuild=True)
    families = mastery.path_families(atlas, states, [f"{tier}.exam"], first=weak)
    goals = store.load_goals()
    goal_id = f"placement-{tier}-{store.now()[:10]}"
    goals["goals"] = [g for g in goals["goals"] if g["id"] != goal_id]
    goals["goals"].append({"id": goal_id, "title": title, "kind": "grade", "targets": [f"{tier}.exam"],
                           "families": [f["family"] for f in families], "first": weak, "bridges": [],
                           "status": "active", "created": store.now(), "source": "placement"})
    goals["active"] = goal_id
    store.save_goals(goals)
    return goal_id
