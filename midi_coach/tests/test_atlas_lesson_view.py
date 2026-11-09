"""The lesson view's run of a stage: Freeplay's sheet is kept, Listen is a Listen run, a run
never ends silently, and pass marks read in plain words."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import layout, steps
from midi_coach.atlas.runtime import AtlasCoach
from midi_coach.tests.test_atlas import _req, home, tree  # noqa: F401  (fixtures)


class Hub(SimpleNamespace):
    def atlas(self, msg):
        self.events.append(msg)


@pytest.fixture()
def coach(home, tree):  # noqa: F811
    folder = atlas_pkg.content_dir()
    (folder / "lessons").mkdir(parents=True)
    layout.layout(tree)
    (folder / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    stage = _req(tree, "scale-c-major", tier="initial")["stages"][0]
    lesson = {"id": stage, "version": 1, "steps": [
        {"id": "hear", "type": "listen", "file": "piece.mid", "hand": "right", "tempo_percent": 80},
        {"id": "play", "type": "play", "file": "piece.mid", "hand": "right", "mode": "learn", "graded": True,
         "pass": {"metric": "notes", "min": 80}}]}
    (folder / "lessons" / f"{stage}.json").write_text(json.dumps(lesson), encoding="utf-8")
    hub = Hub(score_path="freeplay/song.mid", events=[])
    shown, heard = [], []

    def show(path):
        shown.append(path)
        hub.score_path = path

    c = AtlasCoach(hub, show=show, listen=lambda path, **kw: heard.append((path, kw)) or {"mode": "listen"},
                   play=lambda *a, **k: pytest.fail("a Listen step is a Listen run, not a bare playback"))
    c.stage, c.shown, c.heard = stage, shown, heard
    return c


def test_leaving_a_lesson_gives_freeplay_its_sheet_back(coach):
    coach.cmd_stage_open({"node": coach.stage})
    assert coach.hub.score_path.endswith("piece.mid")
    coach.cmd_stage_open({"node": coach.stage})  # another exercise: still Freeplay's sheet to come back to
    assert coach.cmd_stage_close({})["restored"] == "freeplay/song.mid"
    assert coach.hub.score_path == "freeplay/song.mid"
    assert coach.cmd_stage_close({})["restored"] is None  # nothing kept twice


def test_nothing_in_freeplay_leaves_the_lesson_sheet(coach):
    coach.hub.score_path = None
    coach.cmd_stage_open({"node": coach.stage})
    assert coach.cmd_stage_close({})["restored"] is None and coach.hub.score_path.endswith("piece.mid")


def test_a_listen_step_starts_a_listen_run(coach):
    out = coach.cmd_step_start({"node": coach.stage, "step": "hear"})
    assert out["mode"] == "listen"
    path, kw = coach.heard[0]
    assert path.endswith("piece.mid") and kw == {"hand": "right", "bars": None, "tempo_percent": 80.0}


def test_a_pass_stopped_early_says_so(coach):
    meta = {"mode": "wait", "atlas": {"node": coach.stage, "step": "play"}}
    assert coach.on_pass(meta, {"scores": {"notes": 99}}, {}, "stopped") is None
    verdict = coach.hub.events[-1]["verdict"]
    assert verdict["passed"] is None and "not graded" in verdict["detail"]


def test_pass_marks_read_in_plain_words():
    step = {"pass": {"metric": "notes", "min": 80, "max_wrong": 2}}
    v = steps.evaluate(step, {"scores": {"notes": 72}}, {"wrong_presses": 3})
    assert not v["passed"] and v["detail"] == "72% of the notes right (need 80%), 3 wrong keys (at most 2)"
    v = steps.evaluate(step, {"scores": {"notes": 91}}, {"wrong_presses": 1})
    assert v["passed"] and v["detail"] == "91% of the notes right, 1 wrong key"
    v = steps.evaluate({"pass": {"metric": "overall", "min": 70, "tempo_min_pct": 90}},
                       {"scores": {"overall": 75}, "tempo": {"percent_of_reference": 85}})
    assert not v["passed"] and v["detail"] == "overall score 75, speed 85% of full (need 90%)"
