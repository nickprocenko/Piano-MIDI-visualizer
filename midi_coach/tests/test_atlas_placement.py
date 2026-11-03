"""Placement: the climb / step-down rules, and placement runs driven through the runtime
(exams sat, grades credited, the first grade failed set as a goal with its weak items first)."""

from __future__ import annotations

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import mastery, placement, store
from midi_coach.tests.test_atlas import home, tree  # noqa: F401  (fixtures)
from midi_coach.tests.test_atlas_exam import GOOD, exam_content  # noqa: F401  (fixture)

ORDER = ["initial", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"]


@pytest.mark.parametrize("start, results, nxt, credited, goal", [
    ("g1", [], "g1", None, None),
    ("g1", [("g1", True), ("g2", True)], "g3", None, None),                      # climbing
    ("g1", [("g1", True), ("g2", True), ("g3", False)], None, ORDER[:3], "g3"),  # pass G1, pass G2, fail G3
    ("g3", [("g3", False)], "g2", None, None),                                   # the first exam failed: step down
    ("g3", [("g3", False), ("g2", False)], "g1", None, None),
    ("g3", [("g3", False), ("g2", False), ("g1", True)], None, ORDER[:2], "g2"),
    ("initial", [("initial", False)], None, [], "initial"),                      # nothing below Initial
    ("g8", [("g8", True)], None, ORDER, None),                                   # beyond the Atlas
])
def test_climb_and_step_down(start, results, nxt, credited, goal):
    assert placement.next_tier(ORDER, start, results) == nxt
    if nxt is None:
        assert placement.outcome(ORDER, results) == {"credited": credited, "goal": goal}


def test_path_brings_weak_items_forward(tree):  # noqa: F811
    plain = mastery.path_families(tree, {}, ["g1.exam"])
    order = [r["id"] for f in plain for r in f["requirements"]]
    free = [r for r in order if not tree["by_id"][r].get("prereqs")]
    weak = free[-1]  # one that came late
    led = mastery.path_families(tree, {}, ["g1.exam"], first=[weak])
    assert led[0]["requirements"][0]["id"] == weak
    assert sorted(r["id"] for f in led for r in f["requirements"]) == sorted(order)


def _sit(coach, good: bool) -> None:
    """Work through the exam going, every task well or badly, through the runtime's hooks."""
    exam = coach.exam()
    while exam is not None and not exam.done and exam.task():
        task, index = exam.task(), exam.data["current"]
        if task["kind"] == "aural":
            for step in task["steps"]:
                coach._exam_step(task["node"], step, 100 if good else 0)
        else:
            coach.compare = lambda meta: GOOD if good else {"error": "Take contains no notes."}
            coach._exam_pass({"id": "take", "atlas": {"exam": exam.id, "task": index}})


def _coach():
    from midi_coach.atlas.runtime import AtlasCoach

    said: list[str] = []
    return AtlasCoach(say=said.append), said


def test_placement_climbs_then_sets_the_first_failed_grade_as_the_goal(exam_content):  # noqa: F811
    coach, said = _coach()
    out = coach.cmd_placement_start({"tier": "initial", "seed": 1})
    assert out["exam"]["tier"] == "initial" and out["placement"]["status"] == "running"
    _sit(coach, good=True)
    assert "For your placement, Grade 1 is next" in said[-1]
    state = coach.cmd_placement_state({})["placement"]
    assert state["exams"][0]["passed"] and state["next"] == "g1"

    assert coach.cmd_placement_continue({"seed": 2})["exam"]["tier"] == "g1"
    _sit(coach, good=False)
    done = coach.cmd_placement_state({})["placement"]
    assert done["status"] == "done" and done["credited"] == ["first", "ready", "initial"] and done["goal_tier"] == "g1"
    assert done["summary"].startswith("Placed at Grade 1.") and done["summary"] in said[-1]
    assert done["weak"]  # the failed exam's weakest items

    goals = store.load_goals()
    goal = next(g for g in goals["goals"] if g["id"] == goals["active"])
    assert goal["targets"] == ["g1.exam"] and goal["first"] == [w["id"] for w in done["weak"]] and goal["families"]
    states = store.progress(atlas_pkg.load_atlas(), rebuild=True)
    initial_stages = [n["id"] for n in exam_content["nodes"] if n["level"] == "stage" and n["tier"] == "initial"]
    assert all(states[s]["level"] == "proficient" for s in initial_stages)  # credited by placement
    assert states["initial.exam"]["level"] in ("proficient", "mastered")
    assert states["g1.exam"]["level"] == "practised"


def test_placement_steps_down_when_the_first_exam_fails(exam_content):  # noqa: F811
    coach, said = _coach()
    coach.cmd_placement_start({"tier": "g1", "seed": 1})
    _sit(coach, good=False)
    assert coach.cmd_placement_state({})["placement"]["next"] == "initial"
    assert "Initial is next" in said[-1]
    coach.cmd_placement_continue({})
    _sit(coach, good=True)
    done = coach.cmd_placement_state({})["placement"]
    assert done["status"] == "done" and done["credited"] == ["first", "ready", "initial"] and done["goal_tier"] == "g1"
    assert [e["tier"] for e in done["exams"]] == ["g1", "initial"]


def test_placement_pauses_and_picks_up_the_same_exam(exam_content):  # noqa: F811
    coach, _ = _coach()
    first = coach.cmd_placement_start({"tier": "initial", "seed": 1})["exam"]["id"]
    exam = coach.exam()
    coach.compare = lambda meta: GOOD
    coach._exam_pass({"id": "take", "atlas": {"exam": first, "task": 0}})
    coach.cmd_placement_pause({})
    assert coach.exam() is None and coach.cmd_exam_state({})["exam"] is None  # hidden while paused
    fresh, _ = _coach()  # the coach restarted
    assert fresh.cmd_placement_state({})["placement"]["status"] == "paused"
    resumed = fresh.cmd_placement_continue({})["exam"]
    assert resumed["id"] == first and resumed["progress"]["pieces"]["done"] == 1
    assert exam.id == first

    fresh.cmd_exam_abort({})  # stopping the exam pauses placement; Continue sits the grade afresh
    assert fresh.cmd_placement_state({})["placement"]["status"] == "paused"
    again = fresh.cmd_placement_continue({})["exam"]
    assert again["tier"] == "initial" and again["id"] != first and again["progress"]["pieces"]["done"] == 0
