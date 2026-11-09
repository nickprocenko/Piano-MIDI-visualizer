"""Familiar tunes: public-domain songs in the graded tiers, beside the exam lists.
Built on the made-up sample syllabus (Initial and Grade 1)."""

from __future__ import annotations

import json

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import build, familiar, mastery
from midi_coach.tests.test_atlas import home  # noqa: F401  (fixture)
from midi_coach.tests.test_first_steps import tree  # noqa: F401  (fixture)


def _tunes(tree):  # noqa: F811
    return [n for n in tree["nodes"] if n["level"] == "requirement" and n.get("family", "").endswith(".familiar")]


def test_every_grade_1_tune_is_a_piece_on_the_path(tree):  # noqa: F811
    reqs = _tunes(tree)
    assert {r["piece"] for r in reqs} == {t["id"] for t in familiar.tunes() if t["tier"] == "g1"}
    assert all(r["tier"] == "g1" and r["strand"] == "pieces" and r["kind"] == "piece" for r in reqs)
    by_id = tree["by_id"]
    assert by_id["g1.pieces.familiar.twinkle-g"]["prereqs"] == ["g1.pieces.familiar.hot-cross-buns-octaves"]
    path = {r["id"] for f in mastery.path_families(tree, {}, ["g1.exam"]) for r in f["requirements"]}
    assert {r["id"] for r in reqs} <= path


def test_a_tune_in_a_grade_the_syllabus_lacks_is_left_out():
    sample = atlas_pkg.load_syllabus(atlas_pkg.SAMPLE / "syllabus.json")
    sample["grades"] = [g for g in sample["grades"] if g["id"] != "g1"]
    assert not _tunes(build.build(sample, []))


def test_lessons_are_lint_clean_and_note_for_note(home, tree):  # noqa: F811
    lessons = atlas_pkg.content_dir() / "lessons"
    report = familiar.write_lessons(tree, lessons)
    assert report["problems"] == [] and report["scores"] == len(_tunes(tree))
    for r in _tunes(tree):
        for sid in r["stages"]:
            lesson = json.loads((lessons / f"{sid}.json").read_text(encoding="utf-8"))
            play = lesson["steps"][-1]
            assert play["graded"] and (lessons / play["file"]).is_file()
