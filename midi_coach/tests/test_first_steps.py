"""First steps and Ready to read: the Atlas's own tiers before Initial, for complete beginners.
Built on the made-up sample syllabus (the real one lives only in the user's MidiCoach folder)."""

from __future__ import annotations

import json

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import build, first_steps, mastery
from midi_coach.tests.test_atlas import home  # noqa: F401  (fixture)


@pytest.fixture(scope="module")
def tree():
    t = build.build(atlas_pkg.load_syllabus(atlas_pkg.SAMPLE / "syllabus.json"), [])
    t["by_id"] = {n["id"]: n for n in t["nodes"]}
    return t


def _ours(tree, level="requirement"):
    return [n for n in tree["nodes"] if n["level"] == level and n["tier"] in first_steps.OURS]


def test_two_tiers_come_before_initial(tree):
    assert [t["id"] for t in tree["tiers"]][:3] == ["first", "ready", "initial"]
    orders = {t["id"]: t["order"] for t in tree["tiers"]}
    assert orders["first"] < orders["ready"] < orders["initial"]
    by_id = tree["by_id"]
    assert "first.review" in by_id and "first.exam" not in by_id and "ready.exam" not in by_id  # no mock exam for a four-year-old
    reqs = _ours(tree)
    assert len(reqs) > 120  # many small skills, not a handful of big ones
    assert {r["strand"] for r in reqs if r["tier"] == "first"} == {s["id"] for s in atlas_pkg.STRANDS}
    for r in reqs:
        stages = [by_id[s] for s in r["stages"]]
        assert stages[-1]["final"] and not any(s["final"] for s in stages[:-1])
        assert all(p in by_id for p in r["prereqs"])


def test_a_beginners_path_to_initial_starts_from_nothing(tree):
    ready = [r["id"] for f in mastery.path_families(tree, {}, ["ready.review"]) for r in f["requirements"]]
    assert set(ready) == {r["id"] for r in _ours(tree)}  # every First steps skill leads on to Ready to read
    path = [r["id"] for f in mastery.path_families(tree, {}, ["initial.exam"]) for r in f["requirements"]]
    first = tree["by_id"][path[0]]
    assert first["tier"] == "first" and first["prereqs"] == []  # where a complete beginner starts
    # Walked the way Next walks it (family by family, skipping what isn't ready yet), every
    # requirement's prerequisites are done before it, and something is always ready.
    families = mastery.path_families(tree, {}, ["initial.exam"])
    left = set(path)
    while left:
        rid = next((r["id"] for f in families for r in f["requirements"] if r["id"] in left
                    and not set(tree["by_id"][r["id"]]["prereqs"]) & left), None)
        assert rid, "nothing ready: a cycle"
        left.discard(rid)
    assert path.index("ready.technique.thumbs.thumb-under-down") < path.index(
        "initial.technique.scales-hs.scale-c-major-1oct-separate-legato")


def test_initials_starting_points_need_ready_to_read(tree):
    roots_before = [n for n in build.build(atlas_pkg.load_syllabus(atlas_pkg.SAMPLE / "syllabus.json"), [], first=False)["nodes"]
                    if n["level"] == "requirement" and n["tier"] == "initial" and not n["prereqs"]]
    assert roots_before
    for r in roots_before:
        assert any(p.startswith("ready.") for p in tree["by_id"][r["id"]]["prereqs"]), r["id"]
    scale = tree["by_id"]["initial.technique.scales-hs.scale-c-major-1oct-separate-legato"]
    assert "ready.technique.thumbs.thumb-under-down" in scale["prereqs"]


def test_what_you_know_brings_no_prerequisites(tree):
    initial = {n["id"]: {"level": "proficient"} for n in tree["nodes"] if n["level"] == "requirement" and n["tier"] == "initial"}
    path = [r["id"] for f in mastery.path_families(tree, initial, ["g1.exam"]) for r in f["requirements"]]
    assert path and not any(r.split(".")[0] in first_steps.OURS for r in path)


def test_every_item_is_well_formed():
    keys = [i["key"] for table in (first_steps.TECHNIQUE, first_steps.THEORY, first_steps.SIGHT, first_steps.AURAL)
            for tid in first_steps.OURS for _, _, items in table[tid] for i in items] + [t["id"] for t in first_steps.tunes()]
    assert len(keys) == len(set(keys))
    for tid in first_steps.OURS:
        for _, _, items in first_steps.THEORY[tid]:
            for t in items:
                for prompt, options, answer, _ in t["quizzes"]:
                    assert 0 <= answer < len(options), prompt
        for _, _, items in first_steps.TECHNIQUE[tid]:
            for e in items:  # the fingering matches the notes (it raises if not)
                first_steps.fingers(e["right"], e["rf"], "right")
                first_steps.fingers(e["left"], e["lf"], "left")
    answers = [a for tid in first_steps.OURS for _, _, items in first_steps.THEORY[tid] for t in items for _, _, a, _ in t["quizzes"]]
    assert len(set(answers)) > 1  # the right answer isn't always the first button
    for t in first_steps.tunes():
        first_steps.fingers(t.get("right"), t.get("rh"), "right", t["time"])
        first_steps.fingers(t.get("left"), t.get("lh"), "left", t["time"])


def test_pool_pieces_end_at_home_and_keep_to_their_notes():
    items = {i["key"]: i for tid in first_steps.OURS for _, _, its in first_steps.SIGHT[tid] for i in its}
    for key in ("read-c-to-g", "read-lh-middle-c", "read-both-staves", "rhythm-ta"):
        item = items[key]
        for seed in range(20):
            piece = first_steps.pool_piece(item, seed)
            for hand, allowed in (("right", item["pitches"]), ("left", item["lpitches"])):
                if not piece[hand]:
                    continue
                notes = [p for chord in first_steps._tiny_pitches(piece[hand]) for p in chord]
                assert set(notes) <= set(allowed)
                assert notes[0] == notes[-1] in (60, 48)  # starts and ends on a C


def test_mark_up_adds_fingers_letters_and_no_bar_numbers(tmp_path):
    from midi_coach.lessons import build_lesson

    path, _ = build_lesson("t", "c4 d e2", "C1", out_dir=tmp_path, filename="t")
    xml = first_steps.mark_up(open(path, encoding="utf-8").read(), ["right", "left"], [1, 2, 3], [5], letters=True)
    assert xml.count("<fingering") == 4 and '<fingering placement="below">5</fingering>' in xml
    assert [t for t in __import__("re").findall(r"<text>([A-G])</text>", xml)] == ["C", "D", "E", "C"]
    assert xml.count("<measure-numbering>none</measure-numbering>") == 2


def test_write_lessons_makes_every_lesson_lint_clean(home, tree):  # noqa: F811
    from midi_coach.atlas import store
    from midi_coach.atlas.runtime import AtlasCoach

    lessons = atlas_pkg.content_dir() / "lessons"
    report = first_steps.write_lessons(tree, lessons, pool_count=1)
    assert report["problems"] == []
    for st in _ours(tree, "stage"):
        lesson = json.loads((lessons / f"{st['id']}.json").read_text(encoding="utf-8"))
        assert lesson["steps"][0]["type"] == "read" and any(s.get("graded") for s in lesson["steps"]), st["id"]
        for s in lesson["steps"]:
            if s.get("file"):
                assert (lessons / s["file"]).is_file(), s["file"]
            if s.get("pool"):
                folder, _, prefix = s["pool"].rpartition("/")
                assert list((lessons / folder).glob(f"{prefix}*.musicxml")), s["pool"]
            if s["type"] == "quiz":
                assert 0 <= s["answer"] < len(s["options"])
    mary = (lessons / "first" / "mary.musicxml").read_text(encoding="utf-8")
    assert "<fingering" in mary and "<lyric" in mary  # finger numbers and letter names for the youngest
    ode_g = (lessons / "first" / "ode-to-joy-g.musicxml").read_text(encoding="utf-8")
    assert "<fingering" in ode_g and "<lyric" not in ode_g  # Ready to read: reading the notes themselves

    # Next on a beginner's goal opens the very first lesson, then only what's ready.
    (atlas_pkg.content_dir() / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    store.save_goals({"active": "start", "goals": [{"id": "start", "title": "Initial", "kind": "grade", "targets": ["initial.exam"],
                                                     "families": [], "first": [], "bridges": [], "status": "active"}]})
    coach = AtlasCoach()
    nxt = coach.cmd_path_next({})
    assert nxt["requirement"] == "first.theory.at-the-piano.sitting"
    store.append_event("credit", node="first.theory.at-the-piano.sitting")
    nxt = coach.cmd_path_next({})
    assert not set(tree["by_id"][nxt["requirement"]]["prereqs"]) - {"first.theory.at-the-piano.sitting"}
