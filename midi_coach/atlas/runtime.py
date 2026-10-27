"""The Atlas at run time: the coach page's commands, and grading each pass of a step.

AtlasCoach gets the server's own functions passed in (showing a file on the page,
starting a run, playing on the MIDI output), the way chat.VoiceChat gets its actions, so
this module never imports server.py.

A lesson (<content>/lessons/<stage id>.json) is a list of steps:
  read    {text, snippet?}                         done when you've read it
  listen  {file, hand?, bars?, tempo_percent?}     played on the MIDI output
  play    {file, hand, bars?, mode, tempo_percent, graded, pass}   a Learn / Rehearse run
  quiz    {prompt, options, answer, accept?}       click or say the answer
  sing / tap                                       (aural.py)
Files are relative to the lessons folder (or absolute).

Mock exams (exam.py) run here too: each played task is a free-play take compared against
its music, and each aural test is its stage lesson, whose verdicts the exam collects.
"""

from __future__ import annotations

import json
import logging
import pathlib
import random
import re
import threading
import time

from .. import library
from ..notes import parse_bars
from . import content_dir, drills, load_atlas, steps, store, temporary, user_dir
from .exam import ExamSession
from .placement import Placement

log = logging.getLogger("midi-coach")

SLIM_FIELDS = ("id", "level", "parent", "tier", "strand", "family", "requirement", "title", "kind", "box", "final", "prereqs",
               "temporary", "writing", "goal")
FINISHED = ("finished the piece", "reached the end")
TAP_SILENCE_SEC = 2.5  # a tapped or played-back answer ends after this much quiet
EXAM_SILENCE_SEC = {"piece": 6.0, "scale": 3.0, "sight": 5.0}  # a played exam task ends after this much quiet


def _norm(text: str) -> str:
    """'E flat major' and 'E♭ major' both -> 'eb major'."""
    t = text.lower().replace("♭", "b").replace("♯", "#")
    t = re.sub(r"\b([a-g]) flat\b", r"\1b", t)
    t = re.sub(r"\b([a-g]) sharp\b", r"\1#", t)
    return re.sub(r"[^a-z0-9#/]+", " ", t).strip()


class AtlasCoach:
    def __init__(self, hub=None, show=None, begin=None, play=None, compare=None, say=None) -> None:
        self.hub = hub
        self.show = show      # show(path): load a file on the coach page
        self.begin = begin    # begin(path, hand=, bars=, mode=, tempo_percent=, atlas=) -> dict (server._begin)
        self.play = play      # play(path, hand=, bars=, tempo_percent=) -> dict (MIDI output)
        self.compare = compare  # compare(take meta) -> analysis report (server._compare), for exam takes
        self.say = say        # say(text): the examiner speaks
        self._exam: ExamSession | None = None
        self._placement_done: dict | None = None  # a placement just settled, for the page
        self.current: dict | None = None  # {node, step} being practised
        self._last_pool: dict[str, str] = {}  # pool -> the piece it gave last
        self._played_at: dict[tuple, float] = {}  # (node, step) -> when its example started (perf_counter)
        self.planning: dict | None = None  # the goal being planned: {text, started, error?}
        self.plan_run = None  # claude_run.run, replaceable in tests
        self._bridges = threading.Lock()  # one bridge-writing worker at a time

    # -- data ------------------------------------------------------------------------

    def reset(self) -> None:
        """A different profile is now active: drop what belonged to the last one."""
        self._exam = None
        self._placement_done = None
        self.current = None
        self.planning = None
        self._played_at.clear()

    def tree(self) -> dict:
        """The built tree with the active goals' temporary nodes in its lanes."""
        return temporary.merged(load_atlas())

    def lesson(self, node_id: str) -> dict | None:
        """A stage's lesson: the base lessons, then the temporary nodes' (<home>/atlas/lessons).
        Its steps carry '_dir', the folder their files are relative to."""
        for folder in (content_dir() / "lessons", temporary.lessons_dir()):
            try:
                lesson = json.loads((folder / f"{node_id}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for s in lesson.get("steps", []):
                s["_dir"] = str(folder)
            return lesson
        return None

    def step(self, node_id: str, step_id: str) -> tuple[dict, dict]:
        lesson = self.lesson(node_id)
        if not lesson:
            raise ValueError(f"No lesson for {node_id} yet.")
        for s in lesson["steps"]:
            if s["id"] == step_id:
                return lesson, s
        raise ValueError(f"{node_id} has no step {step_id!r}.")

    def file(self, step: dict) -> pathlib.Path:
        """The step's music. A step with a 'pool' (e.g. 'sight/g3-') takes a piece from that
        set instead, a different one from last time (fresh sight-reading)."""
        if step.get("pool"):
            folder, _, prefix = step["pool"].rpartition("/")
            pieces = sorted((content_dir() / "lessons" / folder).glob(f"{prefix}*.musicxml"))
            if not pieces:
                raise ValueError(f"No pieces in {step['pool']} yet.")
            fresh = [p for p in pieces if str(p) != self._last_pool.get(step["pool"])] or pieces
            pick = random.choice(fresh)
            self._last_pool[step["pool"]] = str(pick)
            return pick
        p = pathlib.Path(step["file"])
        return p if p.is_absolute() else pathlib.Path(step.get("_dir") or content_dir() / "lessons") / p

    def states(self, rebuild: bool = False) -> dict:
        return store.progress(self.tree(), rebuild=rebuild)

    def publish(self, **extra) -> None:
        if self.hub:
            self.hub.atlas({"current": self.current, **extra})

    # -- page commands ------------------------------------------------------------------

    def page_commands(self) -> dict:
        return {"atlas": self.cmd_atlas, "node": self.cmd_node, "search": self.cmd_search,
                "step_start": self.cmd_step_start, "step_done": self.cmd_step_done,
                "quiz_answer": self.cmd_quiz_answer, "progress_rebuild": self.cmd_progress_rebuild,
                "stage_open": self.cmd_stage_open, "step_play": self.cmd_step_play, "step_show": self.cmd_step_show, "sing_result": self.cmd_sing_result,
                "exam_start": self.cmd_exam_start, "exam_state": self.cmd_exam_state, "exam_next": self.cmd_exam_next,
                "exam_skip": self.cmd_exam_skip, "exam_abort": self.cmd_exam_abort, "exam_report": self.cmd_exam_report,
                "placement_start": self.cmd_placement_start, "placement_continue": self.cmd_placement_continue,
                "placement_pause": self.cmd_placement_pause, "placement_state": self.cmd_placement_state,
                "lesson_feedback": self.cmd_lesson_feedback,
                "goals": self.cmd_goals, "goal_plan": self.cmd_goal_plan, "goal_activate": self.cmd_goal_activate,
                "goal_archive": self.cmd_goal_archive, "path_next": self.cmd_path_next}

    def cmd_atlas(self, _body: dict) -> dict:
        """The whole tree for the Atlas view: slim nodes, layout, bundled edges, and states."""
        tree = self.tree()
        states = self.states()
        slim = {k: v for k, v in states.items() if v.get("level") not in (None, "not_started") or "ring" in v}
        return {"version": tree["version"], "tiers": tree["tiers"], "strands": tree["strands"],
                "geometry": tree["geometry"], "bundles": tree["bundles"],
                "nodes": [{k: n[k] for k in SLIM_FIELDS if k in n} for n in tree["nodes"]],
                "temp_edges": tree.get("temp_edges", []), "states": slim, "current": self.current}

    def cmd_node(self, body: dict) -> dict:
        tree = self.tree()
        node = tree["by_id"].get(body.get("id", ""))
        if node is None:
            return {"error": f"No node {body.get('id')!r}."}
        states = self.states()
        out = {"node": {k: v for k, v in node.items() if k != "box"}, "state": states.get(node["id"]),
               "children": [{"id": c, "title": tree["by_id"][c]["title"], "state": states.get(c)} for c in node.get("stages", [])],
               "trail": self._trail(tree, node)}
        if node["level"] == "stage":
            lesson = self.lesson(node["id"])
            out["lesson"] = {**lesson, "steps": [{k: v for k, v in s.items() if k != "_dir"} for s in lesson["steps"]]} if lesson else None
        return out

    @staticmethod
    def _trail(tree: dict, node: dict) -> list[dict]:
        trail, n = [], node
        while n:
            trail.append({"id": n["id"], "title": n["title"], "level": n["level"]})
            n = tree["by_id"].get(n.get("parent", ""))
        return trail[::-1]

    def cmd_search(self, body: dict) -> dict:
        """Nodes whose title (with its tier) has every word of the query; requirements first."""
        words = _norm(body.get("q") or "").split()
        if not words:
            return {"results": []}
        tree = self.tree()
        tiers = {t["id"]: t["title"] for t in tree["tiers"]}
        rank = {"requirement": 0, "family": 1, "strand": 2, "tier": 3, "review": 4, "exam": 4, "stage": 5}
        hits = []
        for n in tree["nodes"]:
            hay = _norm(f"{n['title']} {tiers.get(n['tier'], '')}")
            if all(w in hay.split() or (len(w) > 2 and w in hay) for w in words):
                hits.append(n)
        hits.sort(key=lambda n: (rank[n["level"]], tree["tiers"].index(next(t for t in tree["tiers"] if t["id"] == n["tier"]))))
        return {"results": [{"id": n["id"], "title": n["title"], "level": n["level"], "tier": tiers[n["tier"]]} for n in hits[:25]],
                "count": len(hits)}

    def cmd_stage_open(self, body: dict) -> dict:
        """Practise a stage: its lesson's music goes on the sheet."""
        node_id = body.get("node", "")
        lesson = self.lesson(node_id)
        if not lesson:
            return {"error": f"No lesson for {node_id} yet."}
        self.current = {"node": node_id, "step": None}
        # The lesson's music on the sheet (aural examples are for hearing, never shown).
        first = next((s for s in lesson["steps"] if s["type"] in ("listen", "play") and (s.get("file") or s.get("pool"))), None)
        shown = None
        if first and self.show:
            shown = str(self.file(first))
            self.show(shown)
        self.publish()
        return {"node": node_id, "steps": len(lesson["steps"]), "shown": shown}

    def cmd_step_start(self, body: dict) -> dict:
        node_id, step_id = body.get("node", ""), body.get("step", "")
        lesson, step = self.step(node_id, step_id)
        self.current = {"node": node_id, "step": step_id}
        kind = step["type"]
        out: dict = {"type": kind}
        if kind == "play":
            path = self.file(step)
            if self.show:
                self.show(str(path))
            out.update(self.begin(str(path), hand=step.get("hand", "both"), bars=step.get("bars"),
                                  mode=step.get("mode", "learn"), tempo_percent=float(step.get("tempo_percent", 100)),
                                  input_port=body.get("port") or None,
                                  atlas={"node": node_id, "step": step_id, "lesson_version": lesson.get("version", 1)}))
        elif kind == "listen":
            if self.play:
                out.update(self.play(str(self.file(step)), hand=step.get("hand", "both"), bars=step.get("bars"),
                                     tempo_percent=float(step.get("tempo_percent", 100))))
            store.append_event("touch", node=node_id, step=step_id)
        elif kind == "read":
            store.append_event("touch", node=node_id, step=step_id)
        elif kind in ("tap", "sing"):
            # Tapping along: recording starts, then the example plays. An echo (tapped or played
            # back on the keyboard) is recorded after you've heard it (step_play).
            grade = "taps" if kind == "tap" else "echo"
            if kind == "sing" and body.get("via") != "keyboard":
                return {"error": "Sing it: the page listens and sends the notes (sing_result)."}
            out.update(self.begin(None, mode="free", show_score=False, silence_sec=TAP_SILENCE_SEC, max_minutes=2,
                                  input_port=body.get("port") or None,
                                  atlas={"node": node_id, "step": step_id, "lesson_version": lesson.get("version", 1), "grade": grade}))
            if kind == "tap" and step.get("along") and self.play and "error" not in out:
                self._played_at[(node_id, step_id)] = time.perf_counter()  # the example's zero, on the recorder's clock
                out.update(self.play(str(self.file(step)), hand="both", bars=None, tempo_percent=100.0))
        self.publish(started=step_id)
        return out

    def cmd_step_show(self, body: dict) -> dict:
        """A step's score on the sheet (singing from the score)."""
        _, step = self.step(body.get("node", ""), body.get("step", ""))
        if not step.get("score"):
            return {"error": "This step has no score to show."}
        if self.show:
            self.show(str(self.file({"file": step["score"]})))
        return {"shown": step["score"]}

    def cmd_step_play(self, body: dict) -> dict:
        """Play a step's example (a quiz's passage, a phrase to echo, the tonic before singing)."""
        _, step = self.step(body.get("node", ""), body.get("step", ""))
        if not step.get("file"):
            return {"error": "This step has nothing to play."}
        if not self.play:
            return {"error": "No MIDI output."}
        return self.play(str(self.file(step)), hand="both", bars=None, tempo_percent=float(step.get("tempo_percent", 100)))

    def cmd_sing_result(self, body: dict) -> dict:
        """The notes the page heard you sing (pitch-detected in the browser), graded against the step."""
        from . import aural

        node_id, step_id = body.get("node", ""), body.get("step", "")
        _, step = self.step(node_id, step_id)
        sung = [int(n["midi"]) for n in body.get("notes") or [] if "midi" in n]
        graded = aural.grade_sung(step["ref"], sung)
        verdict = steps.evaluate(step, score=graded["score"])
        verdict["detail"] = graded["detail"]
        store.append_event("sing", node=node_id, step=step_id, passed=verdict["passed"], score=verdict["score"], sung=sung)
        self.publish(verdict={"node": node_id, "step": step_id, **verdict})
        self._exam_step(node_id, step_id, verdict["score"])
        return verdict

    def cmd_step_done(self, body: dict) -> dict:
        store.append_event("touch", node=body.get("node"), step=body.get("step"))
        return {"ok": True}

    def cmd_quiz_answer(self, body: dict) -> dict:
        node_id, step_id = body.get("node", ""), body.get("step", "")
        _, step = self.step(node_id, step_id)
        correct = steps.check_answer(step, body.get("answer"))
        if step.get("graded", True):
            store.append_event("quiz", node=node_id, step=step_id, passed=correct, score=100 if correct else 0,
                               answer=body.get("answer"))
        verdict = {"passed": correct, "answer": step.get("answer"), "explain": step.get("explain")}
        self.publish(verdict={"node": node_id, "step": step_id, **verdict})
        self._exam_step(node_id, step_id, 100 if correct else 0)
        return verdict

    def cmd_lesson_feedback(self, body: dict) -> dict:
        """Your verdict on a lesson marked 'Needs review': {node, ok: true} marks it checked;
        {ok: false, note} keeps it marked and logs what's wrong (feedback.jsonl), for rewriting."""
        node_id = body.get("node", "")
        lesson = self.lesson(node_id)
        if not lesson:
            return {"error": f"No lesson for {node_id}."}
        folder = pathlib.Path(lesson["steps"][0]["_dir"]) if lesson.get("steps") else content_dir() / "lessons"
        for s in lesson.get("steps", []):
            s.pop("_dir", None)
        if body.get("ok"):
            lesson.update(checked=True, reviewed=store.now())
            (folder / f"{node_id}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
            store.append_event("lesson_reviewed", node=node_id, ok=True)
        else:
            note = " ".join(str(body.get("note") or "").split())[:500]
            with (user_dir() / "feedback.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": store.now(), "node": node_id, "step": body.get("step"), "note": note,
                                    "made": lesson.get("made")}, ensure_ascii=False) + "\n")
            store.append_event("lesson_reviewed", node=node_id, ok=False, note=note)
        return {"node": node_id, "checked": bool(lesson.get("checked"))}

    def cmd_progress_rebuild(self, _body: dict) -> dict:
        states = self.states(rebuild=True)
        return {"nodes": len(states)}

    # -- grading a pass -----------------------------------------------------------------

    def on_pass(self, meta: dict, report: dict | None, live: dict | None, reason: str | None) -> dict | None:
        """Called by the server after each graded pass. Grades the step the run belongs to
        and records the verdict on the take; returns it (None if not an Atlas run)."""
        ctx = meta.get("atlas")
        if ctx and ctx.get("exam"):
            return self._exam_pass(meta)
        if not ctx or not ctx.get("node") or not ctx.get("step"):
            return None
        if meta.get("mode") in ("wait", "rehearsal") and reason not in FINISHED:
            return None  # a pass you stopped halfway isn't graded
        try:
            _, step = self.step(ctx["node"], ctx["step"])
        except ValueError:
            return None
        if ctx.get("grade") in ("taps", "echo"):
            verdict = self._grade_keys(meta, step, ctx["grade"])
        else:
            verdict = steps.evaluate(step, report, live)
        ctx.update(passed=verdict["passed"], score=verdict["score"], detail=verdict["detail"])
        if meta.get("id"):
            library.update_take(meta)
        self._exam_step(ctx["node"], ctx["step"], verdict["score"])
        made, retired = self._drills(ctx, step, report, live)
        self.publish(verdict={"node": ctx["node"], "step": ctx["step"], **verdict},
                     **({"drills": made} if made else {}), **({"refresh": True} if made or retired else {}))
        return verdict

    def _drills(self, ctx: dict, step: dict, report: dict | None, live: dict | None) -> tuple[list[dict], list[str]]:
        """Remedial drills: log this pass's slips and make a drill for any bar that keeps
        slipping; a drill that is now Proficient retires. Returns ([{id, title}] made, ids retired)."""
        node = ctx["node"]
        try:
            if node.startswith("drill."):
                return [], drills.retire_proficient(self.states(rebuild=True))
            if (step.get("type") != "play" or not step.get("graded", True) or step.get("pool")
                    or ctx.get("grade") in ("taps", "echo")):
                return [], []
            drills.record_pass(node, ctx["step"], report, live, played=self._bars_played(step, report))
            made = []
            tree, file = self.tree(), str(self.file(step))
            for bar in drills.repeated(node, ctx["step"]):
                d = drills.add_drill(tree, node, ctx["step"], bar, file, step.get("hand", "both"))
                if d:
                    made.append({"id": d["id"], "title": d["title"], "bar": bar, "bars": d["source"]["bars"]})
                if len(made) >= drills.MAX_NEW:
                    break
            return made, []
        except Exception as exc:
            log.warning("drills failed: %s", exc)
            return [], []

    @staticmethod
    def _bars_played(step: dict, report: dict | None) -> int | None:
        """How many bars a pass covered: the comparison's bars, else the step's range."""
        if (report or {}).get("bars"):
            return len(report["bars"])
        try:
            first, last = parse_bars(step.get("bars")) or (None, None)
        except ValueError:
            return None
        return last - first + 1 if first is not None else None

    def _grade_keys(self, meta: dict, step: dict, grade: str) -> dict:
        """Taps (any key) or a played-back line, from the take's notes."""
        from . import aural

        notes = sorted(library.take_notes(meta)[0], key=lambda n: (n.start, n.pitch)) if meta.get("file") else []
        if grade == "taps":
            started = self._played_at.pop((meta["atlas"]["node"], meta["atlas"]["step"]), None)
            offset = started - meta["t0_perf"] if started is not None and meta.get("t0_perf") is not None else None
            graded = aural.grade_taps(step["ref"], [(n.start, n.velocity) for n in notes], along=bool(step.get("along")),
                                      accent_every=step.get("accent_every"), offset=offset)
        else:
            graded = aural.grade_sung(step["ref"], [n.pitch for n in notes])
        verdict = steps.evaluate(step, score=graded["score"])
        accent_min = (step.get("pass") or {}).get("accent_min")
        if accent_min and (graded.get("accent_ratio") or 0) < accent_min:
            verdict["passed"] = False
            graded["detail"] += f" (strong beats need to be louder: x{accent_min})"
        verdict["detail"] = graded["detail"]
        return verdict

    # -- mock exams -----------------------------------------------------------------------

    def exam(self) -> ExamSession | None:
        """The exam in progress (after a restart, the last unfinished one on disk) - not one
        whose placement you paused."""
        if self._exam is None or self._exam.done:
            running = ExamSession.running()
            placement = Placement.current()
            if running and running.data.get("placement") and placement and placement.data["status"] == "paused":
                running = None
            self._exam = running
        return self._exam

    def _exam_publish(self, exam: ExamSession | None = None, speak: bool = True) -> dict:
        exam = exam or self.exam()
        state = exam.state() if exam else None
        line = state["examiner"] if state else ""
        placement = Placement.current()
        if state and state["status"] == "done":
            self._exam = None
            if placement and exam.data.get("placement"):
                placement.exam_done(exam)  # passed or not, placement decides what's next
                p = placement.state()
                line += (f" For your placement, {p['next_title']} is next, when you're ready." if p.get("next_title")
                         else " " + p["summary"] if p.get("summary") else "")
                self._placement_done = p if p["status"] == "done" else None
                placement = Placement.current()
        pstate = placement.state() if placement else self._placement_done
        if self.hub:
            self.hub.atlas({"current": self.current, "exam": state, "placement": pstate})
        if speak and line and self.say:
            self.say(line)
        return {"exam": state, "placement": pstate}

    def cmd_exam_start(self, body: dict) -> dict:
        """Start a mock exam for a tier, or pick up the one left unfinished ({fresh: true}
        starts over)."""
        tier = body.get("tier", "")
        running = ExamSession.running(tier)
        if running and not body.get("fresh"):
            self._exam = running
        else:
            if running:
                running.abort()
            self._exam = ExamSession.new(tier, seed=body.get("seed"), states=self.states())
        return self._exam_publish(self._exam)

    def cmd_exam_state(self, _body: dict) -> dict:
        exam = self.exam()
        return {"exam": exam.state() if exam else None, "history": ExamSession.history()}

    def cmd_exam_next(self, body: dict) -> dict:
        """Begin the current task: a played one starts recording (sight-reading first shows
        the music for its 30 seconds); an aural one hands the page its lesson to run, and
        {finish: true} closes it with the answers given."""
        exam = self.exam()
        task = exam.task() if exam else None
        if task is None:
            return {"error": "No exam in progress."}
        kind = task["kind"]
        if kind == "aural":
            if body.get("finish"):
                exam.finish_aural()
                return self._exam_publish(exam)
            exam.data["phase"] = "answering"
            exam.save()
            self._exam_publish(exam, speak=False)
            return {"aural": task["node"]}
        if kind == "sight" and exam.data.get("phase") != "prepared":
            if self.show:
                self.show(task["file"])
            exam.data["phase"] = "prepared"
            exam.save()
            self._exam_publish(exam, speak=False)
            return {"prepare": task["prep_sec"]}
        if kind == "piece" and self.show:
            self.show(task["file"])
        out = self.begin(task["file"], hand=task.get("hand", "both"), mode="free", show_score=kind != "scale",
                         silence_sec=EXAM_SILENCE_SEC[kind], max_minutes=12 if kind == "piece" else 4,
                         input_port=body.get("port") or None,
                         atlas={"exam": exam.id, "task": exam.data["current"], "grade": "compare"})
        if "error" not in out:
            exam.data["phase"] = "playing"
            exam.save()
            self._exam_publish(exam, speak=False)
        return {k: v for k, v in out.items() if k != "rests"}  # the recorder's rest profile isn't for the page

    def cmd_exam_skip(self, _body: dict) -> dict:
        exam = self.exam()
        if not exam:
            return {"error": "No exam in progress."}
        exam.skip()
        return self._exam_publish(exam)

    def cmd_exam_abort(self, _body: dict) -> dict:
        exam = self.exam()
        if not exam:
            return {"error": "No exam in progress."}
        exam.abort()
        self._exam = None
        placement = Placement.current()
        if placement and placement.data.get("exam") == exam.id:  # placement waits; Continue sits that grade afresh
            placement.data["exam"] = None
            placement.pause()
        if self.hub:
            self.hub.atlas({"current": self.current, "exam": None, "placement": placement.state() if placement else None})
        return {"aborted": exam.id}

    def cmd_exam_report(self, body: dict) -> dict:
        """A finished exam's marks and written report (the latest, or {id})."""
        exam_id = body.get("id") or next((e["id"] for e in reversed(ExamSession.history(body.get("tier")))), None)
        if not exam_id:
            return {"error": "No finished mock exam yet."}
        return {"exam": ExamSession.load(exam_id).state()}

    def _exam_pass(self, meta: dict) -> dict | None:
        """A played exam task finished: compare it, mark it, and move on."""
        ctx = meta["atlas"]
        exam = self.exam()
        if not exam or exam.id != ctx["exam"] or exam.data["current"] != ctx.get("task"):
            return None
        report = None
        if meta.get("id") and self.compare:
            try:
                report = self.compare(meta)
            except Exception as exc:  # a take that can't be compared is marked as not played
                report = {"error": str(exc)}
        result = exam.record_play(report)
        self._exam_publish(exam)
        return result

    def _exam_step(self, node: str, step: str, score: float | None) -> None:
        exam = self.exam()
        if exam and exam.record_step(node, step, float(score or 0)):
            self._exam_publish(exam)

    # -- placement ------------------------------------------------------------------------

    def cmd_placement_start(self, body: dict) -> dict:
        """Find your level: mock exams from the grade you name, up until one fails (or down
        until one passes)."""
        self._placement_done = None
        placement = Placement.start(body.get("tier", ""))
        self._exam = placement.begin_exam(self.states(), seed=body.get("seed"))
        return self._exam_publish(self._exam)

    def cmd_placement_continue(self, body: dict) -> dict:
        """The next placement exam (or the one paused)."""
        placement = Placement.current()
        if not placement:
            return {"error": "No placement in progress."}
        self._exam = placement.begin_exam(self.states(), seed=body.get("seed"))
        return self._exam_publish(self._exam)

    def cmd_placement_pause(self, _body: dict) -> dict:
        """Stop for now: the exam going stays where it is, and Continue picks it up."""
        placement = Placement.current()
        if not placement:
            return {"error": "No placement in progress."}
        placement.pause()
        self._exam = None
        state = placement.state()
        if self.hub:
            self.hub.atlas({"current": self.current, "exam": None, "placement": state})
        return {"placement": state}

    def cmd_placement_state(self, _body: dict) -> dict:
        placement = Placement.current()
        return {"placement": placement.state() if placement else self._placement_done}

    # -- goals and Paths ---------------------------------------------------------------------

    def goal_state(self) -> dict:
        """The goals, the active one's Path (families in order, each requirement with its stages
        and whether their lessons exist), and what the planner is doing."""
        from . import planner

        data = store.load_goals()
        tree = self.tree()
        states = store.progress(tree)
        active = next((g for g in data["goals"] if g["id"] == data.get("active") and g["status"] == "active"), None)
        families = []
        if active:
            for fam in planner.path(active, states):
                fnode = tree["by_id"].get(fam["family"], {})
                fst = states.get(fam["family"]) or {}
                reqs = []
                for r in fam["requirements"]:
                    node = tree["by_id"].get(r["id"], {})
                    reqs.append({"id": r["id"], "title": node.get("title", r["id"]), "recheck": r["recheck"],
                                 "level": (states.get(r["id"]) or {}).get("level", "not_started"),
                                 "temporary": bool(node.get("temporary")), "kind": node.get("kind"),
                                 "stages": [{"id": sid, "title": tree["by_id"][sid]["title"],
                                             "level": (states.get(sid) or {}).get("level", "not_started"),
                                             "lesson": self.lesson(sid) is not None} for sid in node.get("stages", [])]})
                tier_title = next((t["title"] for t in tree["tiers"] if t["id"] == fnode.get("tier")), "")
                families.append({"family": fam["family"], "title": f"{tier_title} · {fnode.get('title', fam['family'])}".lstrip(" ·"),
                                 "tier": fnode.get("tier"),
                                 "ring": fst.get("ring"), "done": fst.get("done"), "total": fst.get("total"),
                                 "requirements": reqs})
        return {"active": active["id"] if active else None,
                "goals": [{k: g.get(k) for k in ("id", "title", "kind", "status", "created", "song")} for g in data["goals"]],
                "goal": active, "path": families, "planning": self.planning}

    def publish_goals(self) -> dict:
        state = self.goal_state()
        if self.hub:
            self.hub.atlas({"current": self.current, "goals": state})
        return state

    def cmd_goals(self, _body: dict) -> dict:
        return self.goal_state()

    def cmd_goal_plan(self, body: dict) -> dict:
        """Plan a goal in the background (Claude Code on the subscription, a minute or two;
        longer for a song, whose facts are researched first). {text, song?, artist?}"""
        text = " ".join(str(body.get("text") or "").split())
        if not text:
            return {"error": "Say what the goal is."}
        if self.planning and not self.planning.get("error") and not self.planning.get("done"):
            return {"error": "Still planning the last goal."}
        self.planning = {"text": text, "song": body.get("song"), "started": store.now()}
        worker = threading.Thread(target=self._plan, args=(text, body.get("song"), body.get("artist"), body.get("research", True)),
                                  daemon=True)
        worker.start()
        if body.get("wait"):
            worker.join()
        self.publish_goals()
        return {"planning": self.planning}

    def _plan(self, text: str, song: str | None, artist: str | None, research: bool) -> None:
        from . import claude_run, planner

        try:
            goal = planner.plan_goal(text, song=song, artist=artist, run=self.plan_run or claude_run.run, research=research)
        except Exception as exc:
            log.warning("planning failed: %s", exc)
            goal = {"error": str(exc)}
        if goal.get("error"):
            self.planning = {**(self.planning or {}), "error": goal["error"]}
        else:
            self.planning = {**(self.planning or {}), "done": goal["id"]}
            if self.say:
                self.say(f"Your path to {goal['title']} is ready: " + " ".join(goal["planner"]["reasons"][:2]))
            self.write_bridges()
        self.publish_goals()

    def write_bridges(self, wait: bool = False) -> None:
        """Write the active goals' bridge lessons, one stage at a time, in the background."""
        worker = threading.Thread(target=self._bridge_worker, daemon=True)
        worker.start()
        if wait:
            worker.join()

    def _bridge_worker(self) -> None:
        from . import claude_run, generate

        if not self._bridges.acquire(blocking=False):
            return
        try:
            while True:
                tree = self.tree()
                todo = [n for n in tree["nodes"] if n["level"] == "stage" and n.get("writing")]
                if not todo:
                    return
                result = generate.generate_stage(todo[0], tree, run=self.plan_run or claude_run.run,
                                                 lessons_dir=temporary.lessons_dir())
                if result["status"] != "ok":  # a usage limit, or it couldn't be fixed: try again later
                    log.warning("bridge lesson %s: %s", todo[0]["id"], result.get("error") or result.get("errors"))
                    return
                self.publish(refresh=True)
        finally:
            self._bridges.release()

    def cmd_goal_activate(self, body: dict) -> dict:
        data = store.load_goals()
        if not any(g["id"] == body.get("id") and g["status"] == "active" for g in data["goals"]):
            return {"error": f"No open goal {body.get('id')!r}."}
        data["active"] = body["id"]
        store.save_goals(data)
        return self.publish_goals()

    def cmd_goal_archive(self, body: dict) -> dict:
        """Put a goal away (done, or not wanted): its bridges leave the Atlas for the past-goals layer."""
        data = store.load_goals()
        goal = next((g for g in data["goals"] if g["id"] == body.get("id")), None)
        if not goal:
            return {"error": f"No goal {body.get('id')!r}."}
        goal["status"] = body.get("status") if body.get("status") in ("done", "archived") else "archived"
        goal["closed"] = store.now()
        temporary.retire_goal(goal["id"])
        if data.get("active") == goal["id"]:
            data["active"] = next((g["id"] for g in data["goals"] if g["status"] == "active"), None)
        store.save_goals(data)
        return self.publish_goals()

    def next_stop(self) -> dict | None:
        """Where the active goal's Path goes next: the first family with work left, its first
        unfinished requirement, and that requirement's first unfinished stage that has a lesson."""
        state = self.goal_state()
        for fam in state["path"]:
            for req in fam["requirements"]:
                for st in req["stages"]:
                    if st["level"] in ("not_started", "practised") and st["lesson"]:
                        return {"stage": st["id"], "title": st["title"], "requirement": req["id"],
                                "requirement_title": req["title"], "family": fam["title"], "goal": state["goal"]["title"]}
        return None

    def cmd_path_next(self, _body: dict) -> dict:
        nxt = self.next_stop()
        if not nxt:
            state = self.goal_state()
            if not state["goal"]:
                return {"error": "No goal yet: set one first."}
            return {"error": "Nothing left on this Path with a lesson ready." if state["path"] else "This goal's Path is done."}
        return nxt

    def context_lines(self) -> list[str]:
        """What the Maestro knows about the Atlas: the goal and its next stop, drills, exams, placement."""
        lines = []
        try:
            state = self.goal_state()
        except Exception:
            return lines
        if state["goal"]:
            nxt = self.next_stop()
            left = sum(len(f["requirements"]) for f in state["path"])
            lines.append(f"Active goal: {state['goal']['title']} ({left} requirements to go)"
                         + (f"; next stop: {nxt['requirement_title']}, {nxt['title']}" if nxt else "") + ".")
        made = drills.active()
        if made:
            lines.append("Drills for bars that keep slipping: "
                         + "; ".join(d["title"] for d in made[:4])
                         + (f"; and {len(made) - 4} more" if len(made) > 4 else "") + ".")
        if self.planning and not self.planning.get("done"):
            lines.append(f"Planning a goal now: {self.planning['text']}" + (f" (failed: {self.planning['error']})" if self.planning.get("error") else "") + ".")
        done = ExamSession.history()
        if done:
            last = done[-1]
            lines.append(f"Latest mock exam: {last['tier']} {last['total']}/150 ({last['band']}).")
        placement = Placement.current()
        if placement:
            lines.append(f"Placement is under way ({placement.data['status']}).")
        return lines
