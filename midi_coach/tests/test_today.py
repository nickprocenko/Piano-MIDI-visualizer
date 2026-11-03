"""Today: the one-button session planned from the Path (atlas/today.py). Built on the made-up
sample syllabus (the real one lives only in the user's MidiCoach folder)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import store, today, welcome
from midi_coach.tests.test_atlas import home, tree  # noqa: F401  (fixtures)

TODAY = dt.date(2026, 10, 27)


def _reqs(tree, strand, tier="initial"):  # noqa: F811
    return [n for n in tree["nodes"] if n["level"] == "requirement" and n["strand"] == strand and n["tier"] == tier]


def _all_lessons(_sid):
    return True


def _stop(tree, reqs):  # noqa: F811
    """A stand-in for AtlasCoach.next_stop: the first of reqs not skipped."""
    def nxt(skip):
        r = next((r for r in reqs if r["id"] not in skip), None)
        return {"requirement": r["id"], "stage": r["stages"][0]} if r else None
    return nxt


def test_five_minutes_is_just_the_next_stop(tree):  # noqa: F811
    new = _reqs(tree, "pieces")
    known = _reqs(tree, "technique")[0]
    states = {known["id"]: {"level": "proficient", "last_at": "2026-10-01 10:00:00", "last_pass": "2026-10-01 10:00:00"}}
    plan = today.make(tree, states, _stop(tree, new), _all_lessons, [], minutes=5, today=TODAY)
    assert [p["kind"] for p in plan["parts"]] == ["new"]
    assert plan["parts"][0]["requirement"] == new[0]["id"] and plan["parts"][0]["stage"] == new[0]["stages"][0]


def test_twenty_minutes_warms_up_reviews_learns_and_plays_for_fun(tree, tmp_path):  # noqa: F811
    scales, theory = _reqs(tree, "technique"), _reqs(tree, "theory")
    old, older = "2026-10-20 10:00:00", "2026-10-10 10:00:00"
    states = {scales[0]["id"]: {"level": "proficient", "last_at": old, "last_pass": old},
              scales[1]["id"]: {"level": "mastered", "last_at": older, "last_pass": older},
              theory[0]["id"]: {"level": "proficient", "last_at": older, "last_pass": older},
              theory[1]["id"]: {"level": "proficient", "last_at": "2026-10-26 10:00:00", "last_pass": "2026-10-26 10:00:00"}}
    song = tmp_path / "Song.mid"
    song.write_bytes(b"")
    takes = [{"reference": str(song), "mode": "wait", "created": "2026-10-25 20:00:00"},
             {"reference": str(tmp_path / "gone.mid"), "mode": "wait", "created": "2026-10-26 20:00:00"}]
    plan = today.make(tree, states, _stop(tree, _reqs(tree, "pieces")), _all_lessons, takes, minutes=20, today=TODAY)
    kinds = [p["kind"] for p in plan["parts"]]
    assert kinds == ["warmup", "review", "new", "fun"]
    warm, rev, _, fun = plan["parts"]
    assert warm["requirement"] == scales[1]["id"]  # the scale longest since you played it
    assert rev["requirement"] == theory[0]["id"]   # not the one passed yesterday, nor the warm-up again
    assert fun["file"] == str(song) and fun["title"] == "Song"  # the newest piece that is still there
    # Learning for songs you love: the piece comes before the review when time is short.
    plan = today.make(tree, states, _stop(tree, _reqs(tree, "pieces")), _all_lessons, takes, minutes=15,
                      songs_first=True, today=TODAY)
    assert [p["kind"] for p in plan["parts"]] == ["warmup", "new", "fun"]


def test_no_goal_and_nothing_known_is_an_empty_plan(tree):  # noqa: F811
    plan = today.make(tree, {}, lambda skip: None, _all_lessons, [], minutes=20, today=TODAY)
    assert plan["parts"] == []


def test_a_second_new_stop_fills_spare_time(tree):  # noqa: F811
    theory = _reqs(tree, "theory")
    plan = today.make(tree, {}, _stop(tree, theory), _all_lessons, [], minutes=20, today=TODAY)
    assert [p["requirement"] for p in plan["parts"]] == [theory[0]["id"], theory[1]["id"]]


def test_practice_time_merges_takes_and_events_with_short_gaps():
    takes = [{"created": "2026-10-27 18:02:00", "duration_sec": 120},   # 18:00-18:02
             {"created": "2026-10-27 18:06:00", "duration_sec": 60},    # 18:05-18:06, a 3-minute gap: counts
             {"created": "2026-10-26 18:06:00", "duration_sec": 600}]   # another day
    events = [{"type": "quiz", "at": "2026-10-27 18:08:00"},             # 2 minutes later: counts
              {"type": "credit", "at": "2026-10-27 18:09:00"},           # not something you did
              {"type": "touch", "at": "2026-10-27 19:00:00"}]            # an hour later: a moment on its own
    assert today.practice_seconds(takes, events, "2026-10-27") == 8 * 60


def test_a_part_is_done_when_every_graded_step_was_tried(tree):  # noqa: F811
    req = _reqs(tree, "pieces")[0]
    part = today.stage_part("new", tree, req, req["stages"][0])
    stage, since = part["stage"], "2026-10-27 09:00:00"
    graded = {stage: ["learn", "rehearse"]}
    tried = [{"node": stage, "step": "learn", "passed": False, "at": "2026-10-27 09:05:00"}]
    assert not today.part_done(part, since, tried, [], [], graded)
    tried.append({"node": stage, "step": "rehearse", "passed": True, "at": "2026-10-27 09:10:00"})
    assert today.part_done(part, since, tried, [], [], graded)
    assert not today.part_done(part, "2026-10-27 09:30:00", tried, [], [], graded)  # before this plan was made
    fun = {"kind": "fun", "file": "x.mid"}
    assert today.part_done(fun, since, [], [], [{"reference": "x.mid", "created": "2026-10-27 09:20:00", "duration_sec": 45}], {})
    assert not today.part_done(fun, since, [], [], [{"reference": "x.mid", "created": "2026-10-27 09:20:00", "duration_sec": 5}], {})


@pytest.fixture()
def coach(home, tree):  # noqa: F811
    from midi_coach.atlas.runtime import AtlasCoach

    content = atlas_pkg.content_dir()
    (content / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    lessons = content / "lessons"
    lessons.mkdir(parents=True, exist_ok=True)
    for n in tree["nodes"]:
        if n["level"] == "stage" and n["tier"] == "initial":
            lesson = {"id": n["id"], "steps": [{"id": "q", "type": "quiz", "prompt": "?", "options": ["a", "b"], "answer": 0, "graded": True}]}
            (lessons / f"{n['id']}.json").write_text(json.dumps(lesson), encoding="utf-8")
    store.save_goals({"active": "g", "goals": [{"id": "g", "title": "Initial", "kind": "grade", "targets": ["initial.exam"],
                                                 "families": [], "first": [], "bridges": [], "status": "active"}]})
    welcome.path().write_text(json.dumps({"answers": {"time": 0}}), encoding="utf-8")  # 5 minutes a day
    return AtlasCoach()


def test_the_plan_is_kept_for_the_day_and_ticks_off(coach):
    first = coach.cmd_today({})
    assert [p["kind"] for p in first["parts"]] == ["new"] and first["minutes"] == 5 and first["next"] == 0
    assert first["goal"] == "Initial" and not first["all_done"]
    part = first["parts"][0]
    assert coach.next_stop()["stage"] == part["stage"]
    store.append_event("quiz", node=part["stage"], step="q", passed=False, score=0)
    again = coach.cmd_today({})
    assert again["parts"][0]["stage"] == part["stage"]  # the same plan, not a new one
    assert again["all_done"] and again["next"] is None and again["parts"][0]["done"]
    more = coach.cmd_today_more({})
    assert len(more["parts"]) == 2 and more["parts"][1]["requirement"] != part["requirement"] and not more["all_done"]
    assert any(line.startswith("Today's session (5 min planned") for line in coach.context_lines())
    # Tomorrow: a new plan.
    plan = today.load()
    plan["day"] = "2000-01-01"
    today.save(plan)
    assert len(coach.cmd_today({})["parts"]) == 1
