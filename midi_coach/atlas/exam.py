"""Mock exams: one per tier, shaped like a graded piano exam and marked out of 150.

An exam is a list of tasks, in exam order:
  piece  x3   one from each list (A, B, C) of the tier's pieces, played through in free play
  scale  xN   requirements drawn from the tier's technique, asked for by name, played from memory
  sight  x1   a fresh piece from the tier's sight-reading pool: 30 seconds to look, then play
  aural  xN   each aural test of the tier, as its 'test' stage lesson (quiz / tap / sing steps)
The session is saved after every task (<home>/atlas/exams/<id>.json), so an exam stopped
halfway - or a coach restarted - picks up at the task it was on. Finishing writes an
'exam_result' event, which the Atlas's exam node reads (Proficient at a pass, Mastered at
merit). It's labelled a mock: the coach's own marking (marking.py), not an exam board's.
"""

from __future__ import annotations

import json
import pathlib
import random
import re
import time

from . import content_dir, load_atlas, marking, store, user_dir

SCALE_COUNT = {"initial": 4, "g1": 5, "g2": 5, "g3": 6, "g4": 6, "g5": 6, "g6": 8, "g7": 8, "g8": 8}
PREP_SEC = 30
SECTIONS = ("pieces", "scales", "sight", "aural")
LIST_NAMES = {"a": "List A", "b": "List B", "c": "List C"}
ORDINAL = {1: "one", 2: "two", 3: "three", 4: "four"}


def exams_dir() -> pathlib.Path:
    path = user_dir() / "exams"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _lesson(stage_id: str) -> dict | None:
    try:
        return json.loads((content_dir() / "lessons" / f"{stage_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _lesson_file(rel: str) -> str:
    p = pathlib.Path(rel)
    return str(p if p.is_absolute() else content_dir() / "lessons" / p)


def spoken_scale(title: str, hand: str) -> str:
    """'B♭ major · 2 oct · HT' -> 'B flat major, two octaves, hands together'."""
    parts = []
    for bit in title.split(" · "):
        m = re.fullmatch(r"(\d) oct", bit)
        if m:
            n = int(m.group(1))
            parts.append(f"{ORDINAL.get(n, n)} octave{'s' * (n > 1)}")
        elif bit == "HT":
            parts.append("hands together")
        elif bit == "HS":
            parts.append(f"{hand} hand")
        elif bit == "a 5th":
            parts.append("five notes")
        else:
            parts.append(bit)
    return ", ".join(parts).replace("♭", " flat").replace("♯", " sharp")


def plan(atlas: dict, tier: str, rng: random.Random, states: dict | None = None) -> list[dict]:
    """The exam's tasks for a tier (see the module doc). states: pieces you've worked on most
    are picked first, as you'd choose your best-prepared pieces."""
    from .pieces import fetched, load_catalog
    from ..notes import load_score

    states = states or {}
    reqs = [n for n in atlas["nodes"] if n["level"] == "requirement" and n["tier"] == tier]
    tier_title = next(t["title"] for t in atlas["tiers"] if t["id"] == tier)
    tasks: list[dict] = []

    catalog = {p["id"]: p for p in load_catalog()}
    by_list: dict[str, list[dict]] = {}
    for r in reqs:
        if r["kind"] == "piece" and catalog.get(r.get("piece")) and fetched(catalog[r["piece"]]):
            by_list.setdefault(r["family"].rsplit("list-", 1)[-1], []).append(r)
    rank = {"not_started": 0, "practised": 1, "proficient": 2, "mastered": 3}

    def best(rs):
        return max(rs, key=lambda r: (rank.get((states.get(r["id"]) or {}).get("level", "not_started"), 0), rng.random()))

    chosen = [best(by_list[k]) for k in sorted(by_list)][:3]
    spare = [r for k in sorted(by_list) for r in by_list[k] if r not in chosen]
    while len(chosen) < 3 and spare:
        chosen.append(spare.pop(rng.randrange(len(spare))))
    for r in chosen:
        piece = catalog[r["piece"]]
        path = fetched(piece)
        key = r["family"].rsplit("list-", 1)[-1]
        tasks.append({"kind": "piece", "section": "pieces", "req": r["id"], "title": r["title"],
                      "list": LIST_NAMES.get(key, key), "file": str(path), "notes": len(load_score(path).notes),
                      "rubato": piece.get("list") == "B",
                      "say": f"{r['title'].rsplit(' (', 1)[0]}, please, when you're ready."})

    tech = [r for r in reqs if r["kind"] == "technique" and r.get("stages")]
    rng.shuffle(tech)
    picked, families = [], set()
    for r in tech:  # one per family first, then any
        if r["family"] not in families:
            picked.append(r)
            families.add(r["family"])
    picked += [r for r in tech if r not in picked]
    for r in picked[:SCALE_COUNT.get(tier, 6)]:
        lesson = _lesson(r["stages"][-1])
        play = next((s for s in (lesson or {}).get("steps", []) if s["type"] == "play"), None)
        if not play:
            continue
        hand = "both" if (r.get("spec") or {}).get("hands") == "together" else rng.choice(["right", "left"])
        spoken = spoken_scale(r["title"], hand)
        tasks.append({"kind": "scale", "section": "scales", "req": r["id"], "title": r["title"], "hand": hand,
                      "file": _lesson_file(play["file"]), "say": spoken[0].upper() + spoken[1:] + ", please."})

    pool = sorted((content_dir() / "lessons" / "sight").glob(f"{tier}-*.musicxml"))
    if pool:
        tasks.append({"kind": "sight", "section": "sight", "title": f"{tier_title} sight-reading",
                      "file": str(rng.choice(pool)), "prep_sec": PREP_SEC,
                      "say": "Now the sight-reading. You have thirty seconds to look it over and try any part of it. "
                             "Press Play when you're ready, and keep going whatever happens."})

    for r in sorted((r for r in reqs if r["strand"] == "aural" and r.get("stages")), key=lambda r: r["title"]):  # A., B., C.
        stage = r["stages"][-1]
        lesson = _lesson(stage)
        graded = [s["id"] for s in (lesson or {}).get("steps", []) if s.get("graded")]
        if graded:
            tasks.append({"kind": "aural", "section": "aural", "req": r["id"], "node": stage, "title": r["title"],
                          "steps": graded, "say": f"{r['title']}."})
    return tasks


class ExamSession:
    """One mock exam, saved after every change."""

    def __init__(self, data: dict) -> None:
        self.data = data

    @classmethod
    def new(cls, tier: str, seed: int | None = None, atlas: dict | None = None, states: dict | None = None) -> "ExamSession":
        atlas = atlas or load_atlas()
        if tier not in {t["id"] for t in atlas["tiers"]}:
            raise ValueError(f"No tier {tier!r}.")
        seed = seed if seed is not None else int(time.time())
        tasks = plan(atlas, tier, random.Random(seed), states)
        if not any(t["kind"] == "piece" for t in tasks):
            raise ValueError(f"No pieces for {tier} yet: fetch them with tools/fetch_pd_pieces.py.")
        title = next(t["title"] for t in atlas["tiers"] if t["id"] == tier)
        exam_id = base = f"{tier}-{time.strftime('%Y%m%d-%H%M%S')}"
        k = 1
        while (exams_dir() / f"{exam_id}.json").exists():  # two exams in one second
            k += 1
            exam_id = f"{base}-{k}"
        exam = cls({"id": exam_id, "tier": tier, "title": f"{title} mock exam",
                    "seed": seed, "marking_version": marking.scheme()["version"], "started": store.now(),
                    "status": "running", "current": 0, "phase": None, "tasks": tasks})
        exam.save()
        return exam

    @classmethod
    def load(cls, exam_id: str) -> "ExamSession":
        return cls(json.loads((exams_dir() / f"{exam_id}.json").read_text(encoding="utf-8")))

    @classmethod
    def running(cls, tier: str | None = None) -> "ExamSession | None":
        """The latest unfinished exam (of a tier), to resume."""
        for path in sorted(exams_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("status") == "running" and (tier is None or data.get("tier") == tier):
                return cls(data)
        return None

    @classmethod
    def history(cls, tier: str | None = None) -> list[dict]:
        out = []
        for path in exams_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("status") == "done" and (tier is None or data["tier"] == tier):
                out.append({"id": data["id"], "tier": data["tier"], "finished": data.get("finished"),
                            "total": data["result"]["total"], "band": data["result"]["band"]})
        return sorted(out, key=lambda e: e["finished"] or "")

    def save(self) -> None:
        path = exams_dir() / f"{self.data['id']}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # -- running ------------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def done(self) -> bool:
        return self.data["status"] != "running"

    def task(self) -> dict | None:
        tasks = self.data["tasks"]
        return tasks[self.data["current"]] if not self.done and self.data["current"] < len(tasks) else None

    def examiner_line(self) -> str:
        """What the examiner says to start the current task (or to close the exam)."""
        if self.data["status"] == "done":
            r = self.data["result"]
            return (f"That's the end of the exam. Thank you. You scored {r['total']} out of {r['of']}: "
                    f"{r['band'].lower()}.")
        task = self.task()
        if task is None:
            return ""
        k, tasks = self.data["current"], self.data["tasks"]
        first_of_section = k == 0 or tasks[k - 1]["section"] != task["section"]
        lead = ""
        if k == 0:
            lead = (f"Hello. This is a mock {self.data['title'].replace(' mock exam', '')} exam, marked the way an "
                    "examiner would, though not by an exam board. We'll start with your pieces. ")
        elif first_of_section and task["section"] == "scales":
            lead = "Thank you. Now some scales and arpeggios, from memory. "
        elif first_of_section and task["section"] == "aural":
            lead = "Thank you. Finally, the aural tests. "
        elif not first_of_section or task["section"] == "pieces":
            lead = "Thank you. " if task["section"] == "pieces" else ""
        return lead + task["say"]

    def record(self, result: dict) -> None:
        """The current task's result; moves on (and finishes after the last task)."""
        task = self.task()
        if task is None:
            raise ValueError("The exam has no task waiting.")
        task["result"] = {**result, "at": store.now()}
        self.data["current"] += 1
        self.data["phase"] = None
        if self.data["current"] >= len(self.data["tasks"]):
            self.finish()
        self.save()

    def record_play(self, report: dict | None) -> dict:
        """A played task (piece, scale, sight-reading) from its comparison report."""
        task = self.task()
        if task["kind"] == "piece":
            result = marking.piece_mark(report, task.get("notes"), task.get("rubato", False))
        elif task["kind"] == "scale":
            result = marking.scale_q(report)
        else:
            result = marking.sight_mark(report)
        if report and report.get("take"):
            result["take"] = report["take"]
        self.record(result)
        return result

    def record_step(self, node: str, step: str, score: float) -> bool:
        """An aural step's score (0-100); returns True when that finished the test."""
        task = self.task()
        if not task or task["kind"] != "aural" or task["node"] != node or step not in task["steps"]:
            return False
        answers = task.setdefault("answers", {})
        if step in answers:  # the first answer counts, as in an exam
            return False
        answers[step] = score
        if all(s in answers for s in task["steps"]):
            self.finish_aural()
            return True
        self.save()
        return False

    def finish_aural(self) -> None:
        """Close the current aural test with the answers given (missing ones count 0)."""
        task = self.task()
        answers = task.get("answers", {})
        score = sum(answers.get(s, 0) for s in task["steps"]) / (100 * len(task["steps"]))
        self.record({"q": round(score, 3), "detail": f"{sum(1 for s in task['steps'] if answers.get(s, 0) >= 50)} of "
                                                     f"{len(task['steps'])} right"})

    def skip(self) -> None:
        task = self.task()
        if task is None:
            return
        if task["kind"] == "aural":
            self.finish_aural()
        elif task["kind"] == "scale":
            self.record({"q": 0.0, "skipped": True, "detail": "not played"})
        else:
            of = marking.scheme()["piece" if task["kind"] == "piece" else "sight"]["of"]
            self.record({"mark": 0, "of": of, "q": 0, "skipped": True, "comments": ["Not played."]})

    def abort(self) -> None:
        self.data["status"] = "aborted"
        self.save()

    def finish(self) -> dict:
        """Section marks, total and band; logs the result for the Atlas."""
        tasks = self.data["tasks"]
        pieces = [t["result"] for t in tasks if t["kind"] == "piece"]
        scales = [t["result"]["q"] for t in tasks if t["kind"] == "scale"]
        sight = next((t["result"] for t in tasks if t["kind"] == "sight"), None)
        aural = [t["result"]["q"] for t in tasks if t["kind"] == "aural"]
        sections = {"pieces": [{"title": t["title"], "list": t.get("list"), **{k: t["result"][k] for k in ("mark", "of")}}
                               for t in tasks if t["kind"] == "piece"],
                    "scales": marking.scales_mark(scales, sum(1 for t in tasks if t["kind"] == "scale" and t["result"].get("skipped"))),
                    "sight": sight if sight is not None else {"mark": 0, "of": marking.scheme()["sight"]["of"]},
                    "aural": marking.aural_mark(aural)}
        total = (sum(p["mark"] for p in pieces) + sections["scales"]["mark"] + sections["sight"]["mark"]
                 + sections["aural"]["mark"])
        self.data["result"] = {"total": total, "of": marking.scheme()["total"], "band": marking.band(total), "sections": sections}
        self.data["status"] = "done"
        self.data["finished"] = store.now()
        store.append_event("exam_result", tier=self.data["tier"], total=total, exam=self.id,
                           band=self.data["result"]["band"])
        return self.data["result"]

    # -- for the page -------------------------------------------------------------------

    def state(self) -> dict:
        """The exam card: sections with progress, the current task, and (when done) the marks."""
        tasks = self.data["tasks"]
        progress = {s: {"done": sum(1 for t in tasks if t["section"] == s and "result" in t),
                        "total": sum(1 for t in tasks if t["section"] == s)} for s in SECTIONS}
        task = self.task()
        current = None
        if task:
            current = {k: task[k] for k in ("kind", "section", "title", "hand", "list", "node", "steps", "prep_sec") if k in task}
            current["index"] = self.data["current"]
        return {"id": self.id, "tier": self.data["tier"], "title": self.data["title"], "status": self.data["status"],
                "phase": self.data.get("phase"), "progress": progress, "task": current, "examiner": self.examiner_line(),
                "result": self.data.get("result"), "report": self.report() if self.data["status"] == "done" else None}

    def report(self) -> str:
        """The written report: marks per section, with the comments."""
        r = self.data.get("result")
        if not r:
            return ""
        lines = [f"{self.data['title']} (a mock: the coach's own marking) - {r['total']}/{r['of']}, {r['band']}", ""]
        for t in self.data["tasks"]:
            if t["kind"] == "piece":
                res = t["result"]
                lines.append(f"{t.get('list') or 'Piece'}: {t['title']} - {res['mark']}/{res['of']}"
                             + (f" (capped: {res['capped']})" if res.get("capped") else ""))
                lines += [f"  {c}" for c in res.get("comments", [])]
        sc = r["sections"]["scales"]
        lines.append(f"Scales and arpeggios - {sc['mark']}/{sc['of']}")
        lines += [f"  {c}" for c in sc["comments"]]
        for t in self.data["tasks"]:
            if t["kind"] == "scale":
                lines.append(f"    {t['title']}{' (' + t['hand'] + ' hand)' if t['hand'] != 'both' else ''}: {t['result'].get('detail', '')}")
        si = r["sections"]["sight"]
        lines.append(f"Sight-reading - {si['mark']}/{si['of']}")
        lines += [f"  {c}" for c in si.get("comments", [])]
        au = r["sections"]["aural"]
        lines.append(f"Aural tests - {au['mark']}/{au['of']}")
        for t in self.data["tasks"]:
            if t["kind"] == "aural":
                lines.append(f"    {t['title']}: {t['result'].get('detail', '')}")
        return "\n".join(lines)
