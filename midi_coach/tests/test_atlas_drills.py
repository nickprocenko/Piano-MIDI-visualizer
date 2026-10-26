"""Remedial drills: made for a bar that keeps slipping, not for one-off slips, retired when learnt."""

from __future__ import annotations

import json

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import drills, layout, store, temporary
from midi_coach.atlas.runtime import AtlasCoach
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
    return [n for n in temporary.load() if n["level"] == "requirement" and n["kind"] == "drill"]


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
