"""Remedial drills: made for a bar that keeps slipping, not for one-off slips, retired when learnt."""

from __future__ import annotations

import json

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import drills, layout, store, temporary
from midi_coach.atlas.runtime import AtlasCoach
from midi_coach.atlas.templates import stage
from midi_coach.tests.test_atlas import _req, home, tree  # noqa: F401  (fixtures)

FINISHED = "finished the piece"


@pytest.fixture()
def coach(home, tree):  # noqa: F811
    folder = atlas_pkg.content_dir()
    (folder / "lessons").mkdir(parents=True)
    layout.layout(tree)
    (folder / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    stage = _req(tree, "scale-c-major", tier="initial")["stages"][0]
    play = {"id": "play", "type": "play", "file": str(home / "piece.musicxml"), "hand": "right", "bars": "1-8",
            "mode": "learn", "tempo_percent": 80, "graded": True, "pass": {"metric": "notes", "min": 90}}
    (folder / "lessons" / f"{stage}.json").write_text(json.dumps({"id": stage, "version": 1, "steps": [play]}), encoding="utf-8")
    c = AtlasCoach()
    c.stage = stage
    return c


def _pass(coach, node=None, step="play", slips=(), mistakes=()):
    meta = {"mode": "wait", "atlas": {"node": node or coach.stage, "step": step}}
    live = {"slips": [{"bar": b, "played": 60, "expected": e} for b, e in slips]}
    report = {"scores": {"notes": 95}, "mistakes": [{"type": t, "bar": b, "expected": n} for t, b, n in mistakes]}
    return coach.on_pass(meta, report, live, FINISHED)


def _drills():
    return drills.active()


def test_slips_are_read_from_live_and_the_comparison():
    bars = drills.slip_bars({"mistakes": [{"type": "wrong", "bar": 3, "expected": "E4"}, {"type": "extra", "bar": 4, "played": "C4"},
                                          {"type": "missed", "bar": 3, "expected": "G4"}]},
                            {"slips": [{"bar": 3, "played": 61, "expected": [64]}, {"bar": 6, "played": 1, "expected": [60, 67]}]})
    assert bars == {3: ["E4", "G4"], 6: ["C4", "G4"]}  # extra notes aren't slips


def test_a_bar_that_slips_in_two_of_three_passes_gets_a_drill(coach):
    _pass(coach, slips=[(5, [64])])
    assert _drills() == []  # once is not a habit
    _pass(coach)
    _pass(coach, slips=[(5, [64]), (7, [60])])
    made = _drills()
    assert [d["id"] for d in made] == [drills.drill_id(coach.stage, 5)]  # bar 7 slipped once only
    tree = coach.tree()
    drill = tree["by_id"][made[0]["id"]]
    assert drill["temporary"] and len(drill["stages"]) == 3
    lessons = [coach.lesson(s) for s in drill["stages"]]
    first, second, last = (l["steps"] for l in lessons)
    assert [s["type"] for s in first] == ["read", "listen", "play"] and first[1]["tempo_percent"] == 70
    assert second[-1]["mode"] == "learn" and last[-1]["mode"] == "rehearse" and last[-1]["tempo_percent"] == 80
    assert all(s["bars"] == "4-6" and s["file"].endswith("piece.musicxml") and s["hand"] == "right"
               for steps_ in (first, second, last) for s in steps_ if s["type"] != "read")
    _pass(coach, slips=[(5, [64])])
    assert len(_drills()) == 1  # not made twice


def test_different_notes_or_spread_out_slips_make_no_drill(coach):
    _pass(coach, slips=[(5, [64])])
    _pass(coach, slips=[(5, [67])])  # same bar, different notes
    _pass(coach)
    _pass(coach)
    _pass(coach, slips=[(5, [64])])  # the first has dropped out of the last three
    assert _drills() == []


def test_drills_do_not_spawn_drills_and_retire_when_proficient(coach):
    _pass(coach, slips=[(5, [64])])
    _pass(coach, mistakes=[("missed", 5, "E4")])
    [made] = _drills()
    stages = [s for s in temporary.load() if s.get("parent") == made["id"]]
    for _ in range(3):
        _pass(coach, node=stages[0]["id"], step="play", slips=[(5, [64])])
    assert len(_drills()) == 1
    for st in stages:
        store.append_event("step", node=st["id"], step="play", passed=True, score=95)
    _pass(coach, node=stages[-1]["id"])
    assert all(n["status"] == "past" for n in temporary.load() if n["id"] == made["id"])
    assert made["id"] not in coach.tree()["by_id"]
    kinds = [e["type"] for e in store.read_events() if e["type"].startswith("drill_")]
    assert kinds == ["drill_created", "drill_retired"]
    # The bar slips again: the slips that made the first drill don't count twice...
    _pass(coach, slips=[(5, [64])])
    assert _drills() == []
    # ...but two fresh ones make a new drill, starting unpractised.
    _pass(coach, slips=[(5, [64])])
    [again] = _drills()
    assert again["id"] == made["id"] + ".r2"
    states = coach.states(rebuild=True)
    assert all((states.get(s) or {}).get("level", "not_started") == "not_started" for s in again["stages"])


def _goal(targets, gid="g"):
    store.save_goals({"active": gid, "goals": [{"id": gid, "title": "A goal", "kind": "skill", "targets": targets,
                                                "status": "active", "created": store.now()}]})


def test_a_drill_comes_first_on_the_path_and_the_maestro_knows(coach):
    req = coach.tree()["by_id"][coach.stage]["requirement"]
    _goal([req])
    _pass(coach, slips=[(5, [64])])
    _pass(coach, slips=[(5, [64])])
    [made] = _drills()
    tree = coach.tree()
    assert [made["id"], req] in tree["temp_edges"]  # drawn dashed into what it drills
    assert tree["by_id"][made["family"]]["title"] == "Drills"
    path = coach.goal_state()["path"]
    order = [r["id"] for f in path for r in f["requirements"]]
    assert order.index(made["id"]) < order.index(req)
    assert next(r for f in path for r in f["requirements"] if r["id"] == made["id"])["kind"] == "drill"
    assert coach.next_stop()["stage"] == made["stages"][0]
    assert any(made["title"] in line for line in coach.context_lines())


def test_a_drill_on_a_song_leads_into_the_song(coach):
    song = {"id": "tmp.pm.piano-man", "level": "requirement", "parent": "initial.goals", "tier": "initial",
            "strand": "pieces", "family": "initial.goals", "kind": "song", "title": "Piano Man", "prereqs": [],
            "before": [], "covers": [], "temporary": True, "goal": "pm", "status": "active"}
    kids = temporary._stage_nodes(song, [stage("a", "Bars 1-4", "right", "learn", 80, final=True)])
    temporary.save([song] + kids)
    _goal([song["id"]], gid="pm")
    d = drills.add_drill(coach.tree(), kids[0]["id"], "play", 3, "song.mid", "right")
    assert d["before"] == [song["id"]]
    order = [r["id"] for f in coach.goal_state()["path"] for r in f["requirements"]]
    assert order == [d["id"], song["id"]]
    assert coach.tree()["by_id"]["initial.goals"]["title"] == "Goal bridges and drills"


def test_broad_ungraded_and_pickup_slips_make_no_drill(coach):
    many = [(b, [60]) for b in range(1, 6)]  # 5 of the step's 8 bars: the passage isn't ready, not one bar
    _pass(coach, slips=many)
    _pass(coach, slips=many)
    assert _drills() == [] and all(e.get("broad") for e in store.read_events() if e["type"] == "slips")
    _pass(coach, slips=[(0, [60])])  # a pickup can't be picked out on its own
    _pass(coach, slips=[(0, [60])])
    assert _drills() == []
    lesson = atlas_pkg.content_dir() / "lessons" / f"{coach.stage}.json"
    data = json.loads(lesson.read_text(encoding="utf-8"))
    data["steps"][0]["graded"] = False
    lesson.write_text(json.dumps(data), encoding="utf-8")
    before = len(store.read_events())
    _pass(coach, slips=[(5, [64])])
    _pass(coach, slips=[(5, [64])])
    assert _drills() == [] and not [e for e in store.read_events()[before:] if e["type"] == "slips"]


def test_one_drill_per_stretch_of_bars(coach):
    _pass(coach, slips=[(2, [60]), (5, [64]), (6, [65])])
    _pass(coach, slips=[(2, [60]), (5, [64]), (6, [65])])
    assert [d["id"] for d in _drills()] == [drills.drill_id(coach.stage, b) for b in (2, 5)]  # bar 6 is in bar 5's drill (4-6)


def test_a_pass_makes_at_most_two_drills(coach):
    slips = [(1, [60]), (4, [64]), (7, [67])]
    _pass(coach, slips=slips)
    _pass(coach, slips=slips)
    assert [d["id"] for d in _drills()] == [drills.drill_id(coach.stage, b) for b in (1, 4)]
    _pass(coach, slips=slips)  # bar 7 still repeats: its drill comes with the next pass
    assert [d["id"] for d in _drills()] == [drills.drill_id(coach.stage, b) for b in (1, 4, 7)]
