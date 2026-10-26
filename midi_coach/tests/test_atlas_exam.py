"""Mock exams: marking anchored on real comparisons of synthetic performances, the band
edges, and an exam run through its tasks (saved, resumed, finished, credited in the Atlas)."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import replace

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import build, marking, store
from midi_coach.tests.test_atlas import home  # noqa: F401  (fixture)

PIECES = [{"id": f"{g}-{k}", "title": f"Piece {g} {k.upper()}", "grade": g, "list": k.upper(), "bars": 16}
          for g in ("initial", "g1") for k in "abc"]


# -- marking --------------------------------------------------------------------------------


def test_band_edges_and_pass_marks_add_up():
    assert [marking.band(t) for t in (0, 99, 100, 119, 120, 129, 130, 150)] == [
        "Below pass", "Below pass", "Pass", "Pass", "Merit", "Merit", "Distinction", "Distinction"]
    s = marking.scheme()
    at_pass = (3 * marking.to_marks(60, s["piece"]["map"]) + marking.to_marks(65, s["scales"]["map"])
               + marking.to_marks(60, s["sight"]["map"]) + marking.to_marks(0.67, s["aural"]["map"]))
    assert at_pass == 100
    assert marking.to_marks(100, s["piece"]["map"]) == 30 and marking.to_marks(-5, s["piece"]["map"]) == 10


@pytest.fixture()
def piece(tmp_path):
    from midi_coach.notes import load_score
    from midi_coach.tests.test_midi_coach import _write_reference

    score = load_score(_write_reference(tmp_path / "piece.mid", rest_bars=()))
    return score


def _perform(score, *, wrong_every=0, tempo=1.0, pauses=(), jitter=0.008):
    """A take of the whole piece: humanised a little (timing jitter, a varied touch), with
    every wrong_every-th note a semitone off, played at `tempo` times the speed, and a pause
    of 2 seconds before each bar in `pauses`."""
    from midi_coach.analysis import compare

    out = []
    for k, n in enumerate(sorted(score.notes, key=lambda n: (n.start, n.pitch))):
        bar = score.position(n.start)[0]
        shift = 2.0 * sum(1 for b in pauses if bar >= b)
        wobble = jitter * ((k * 7) % 5 - 2) / 2
        start = n.start / tempo + shift + wobble
        out.append(replace(n, start=start, end=start + n.duration / tempo,
                           pitch=n.pitch + (1 if wrong_every and k % wrong_every == 0 else 0),
                           velocity=55 + (k * 13) % 35))
    return compare(score, score.notes, out, [], bars_given=False)


def test_piece_marks_anchor_on_real_comparisons(piece):
    good = marking.piece_mark(_perform(piece), len(piece.notes))
    assert good["mark"] >= 27 and good["capped"] is None, good
    assert "Secure notes throughout." in good["comments"]

    sloppy = marking.piece_mark(_perform(piece, wrong_every=3), len(piece.notes))
    assert sloppy["mark"] <= 19 and sloppy["capped"] == "many wrong or missing notes", sloppy

    slow = marking.piece_mark(_perform(piece, tempo=0.6), len(piece.notes))
    assert slow["mark"] <= 23 and any("tempo" in c for c in slow["comments"]), slow

    stops = marking.piece_mark(_perform(piece, pauses=(4, 8, 12)), len(piece.notes))
    assert stops["mark"] <= 22 and any("Hesitations" in c for c in stops["comments"]), stops
    assert good["mark"] > max(sloppy["mark"], slow["mark"], stops["mark"])

    assert marking.piece_mark({"error": "Take contains no notes."})["mark"] == 0


def test_scales_and_sight_reading_marks(piece):
    clean = marking.scale_q(_perform(piece))
    assert clean["q"] >= 90
    from midi_coach.analysis import compare

    shifted = [replace(n, pitch=n.pitch + 2) for n in piece.notes]  # the wrong key
    wrong = marking.scale_q(compare(piece, piece.notes, shifted, [], bars_given=False))
    assert wrong["q"] == 0
    assert marking.scales_mark([clean["q"]] * 5)["mark"] >= 20 and marking.scales_mark([0, 0])["mark"] == 7
    assert marking.sight_mark(_perform(piece))["mark"] >= 19
    assert marking.sight_mark(_perform(piece, pauses=(5,)))["mark"] < marking.sight_mark(_perform(piece))["mark"]
    assert marking.aural_mark([1, 1])["mark"] == 18 and marking.aural_mark([0.5, 0.5])["mark"] == 10


# -- the exam -------------------------------------------------------------------------------


@pytest.fixture()
def exam_content(home, monkeypatch):  # noqa: F811
    """The sample syllabus's Initial tier with everything an exam needs: three fetched
    pieces, a technique lesson per requirement, a sight-reading pool and the aural lessons."""
    from midi_coach.atlas import aural_lessons, pieces
    from midi_coach.tests.test_midi_coach import _write_reference

    syllabus = atlas_pkg.load_syllabus(atlas_pkg.SAMPLE / "syllabus.json")
    tree = build.build(syllabus, PIECES)
    content = atlas_pkg.content_dir()
    (content / "lessons" / "sight").mkdir(parents=True)
    shutil.copy(atlas_pkg.SAMPLE / "syllabus.json", content / "syllabus.json")
    (content / "atlas.json").write_text(json.dumps(tree), encoding="utf-8")
    etude = _write_reference(content / "lessons" / "etude.mid", rest_bars=())
    xml = pieces.to_musicxml(etude, "Etude", "Anon", "test")["xml"]
    for p in PIECES:
        (pieces.pieces_dir() / f"{p['id']}.musicxml").write_text(xml, encoding="utf-8")
    for tier in ("initial", "g1"):
        (content / "lessons" / "sight" / f"{tier}-1.musicxml").write_text(xml, encoding="utf-8")
    monkeypatch.setattr(pieces, "load_catalog", lambda: PIECES)
    for n in tree["nodes"]:
        if n["level"] == "requirement" and n["kind"] == "technique":
            lesson = {"id": n["stages"][-1], "version": 1, "steps": [
                {"id": "play", "type": "play", "file": "etude.mid", "hand": "both", "mode": "rehearse", "tempo_percent": 100,
                 "graded": True, "pass": {"metric": "overall", "min": 80}}]}
            (content / "lessons" / f"{n['stages'][-1]}.json").write_text(json.dumps(lesson), encoding="utf-8")
    aural_lessons.write_lessons()
    return tree


GOOD = {"scores": {"overall": 97, "notes": 100, "timing": 95, "tempo_stability": 95},
        "tempo": {"percent_of_reference": 100, "hesitations": []}, "scope": {"reference_notes": 10_000},
        "dynamics": {"take_velocity": {"std": 10}}, "articulation": {}, "pedal": {}, "mistakes": []}


def test_an_exam_runs_saves_resumes_and_credits_the_atlas(exam_content):
    from midi_coach.atlas.exam import ExamSession

    exam = ExamSession.new("initial", seed=3, atlas=exam_content)
    kinds = [t["kind"] for t in exam.data["tasks"]]
    assert kinds[:3] == ["piece"] * 3 and kinds.count("scale") == 2 and kinds.count("sight") == 1 and kinds[-1] == "aural"
    assert [t["list"] for t in exam.data["tasks"][:3]] == ["List A", "List B", "List C"]
    assert exam.examiner_line().startswith("Hello. This is a mock Initial exam")

    exam.record_play(GOOD)
    exam.record_play(GOOD)
    resumed = ExamSession.running("initial")  # the coach restarted mid-exam
    assert resumed.id == exam.id and resumed.data["current"] == 2
    resumed.record_play({"error": "Take contains no notes."})  # a piece that went nowhere
    assert resumed.data["tasks"][2]["result"]["mark"] == 0
    assert "scales and arpeggios" in resumed.examiner_line()
    assert resumed.examiner_line().endswith(", please.")
    resumed.record_play(GOOD)
    resumed.skip()  # the second scale
    assert resumed.task()["kind"] == "sight"
    resumed.record_play(GOOD)
    aural = resumed.task()
    assert aural["kind"] == "aural" and resumed.examiner_line().startswith("Thank you. Finally, the aural tests.")
    assert resumed.record_step("someone.else", aural["steps"][0], 100) is False
    for k, step_id in enumerate(aural["steps"]):
        resumed.record_step(aural["node"], step_id, 100)
        resumed.record_step(aural["node"], step_id, 0)  # a second try doesn't count
    assert resumed.done and resumed.data["status"] == "done"
    r = resumed.data["result"]
    assert r["sections"]["aural"]["mark"] == 18 and r["sections"]["pieces"][2]["mark"] == 0
    assert r["total"] == sum(p["mark"] for p in r["sections"]["pieces"]) + sum(r["sections"][k]["mark"] for k in ("scales", "sight", "aural"))
    assert r["band"] == marking.band(r["total"])
    assert "Initial mock exam" in resumed.report() and "Not marked" in resumed.report()
    assert ExamSession.running("initial") is None
    assert ExamSession.history("initial")[-1]["total"] == r["total"]

    states = store.progress(atlas_pkg.load_atlas(), rebuild=True)
    expected = "mastered" if r["total"] >= 120 else "proficient" if r["total"] >= 100 else "practised"
    assert states["initial.exam"]["level"] == expected and states["initial.exam"]["best"] == r["total"]


def test_page_runs_an_exam_piece_and_the_examiner_moves_on(exam_content, monkeypatch):
    from midi_coach import display, library, midi_io, server
    from midi_coach.atlas import runtime
    from midi_coach.notes import load_score
    from midi_coach.tests.test_midi_coach import FakeIn, FakeOut, _post, _until

    monkeypatch.setitem(__import__("sys").modules, "rtmidi", __import__("types").SimpleNamespace(MidiIn=FakeIn, MidiOut=FakeOut))
    monkeypatch.setattr(runtime, "EXAM_SILENCE_SEC", {"piece": 1.0, "scale": 1.0, "sight": 1.0})
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(atlas_pkg.content_dir() / "missing.json"))
    library._score_cache.clear()
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server._atlas, "hub", server.hub)
    monkeypatch.setattr(server._atlas, "_exam", None)
    said = []
    monkeypatch.setattr(server._atlas, "say", said.append)
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    try:
        state = _post(url + "exam_start", {"tier": "initial", "seed": 3})["exam"]
        assert state["task"]["kind"] == "piece" and said[-1].startswith("Hello.")
        out = _post(url + "exam_next", {"port": "JUNO-DS 0"})
        assert out.get("mode") == "free", out
        _until(lambda: server.recorder.active)
        score = load_score(server._atlas.exam().data["tasks"][0]["file"])
        first = [n for n in score.notes if n.start < score.bars[2].start]
        t0 = time.perf_counter()
        for n in sorted(first, key=lambda n: n.start):  # two bars, at twice the speed
            while time.perf_counter() < t0 + n.start / 2:
                time.sleep(0.002)
            FakeIn.instance.send([0x90, n.pitch, 70])
            FakeIn.instance.send([0x80, n.pitch, 0])
        _until(lambda: server._atlas.exam() and server._atlas.exam().data["current"] == 1, timeout=15)
        result = server._atlas.exam().data["tasks"][0]["result"]
        assert result["of"] == 30 and result.get("take") and 10 <= result["mark"] <= 30, result
        assert said[-1].startswith("Thank you.")
        state = _post(url + "exam_state")["exam"]
        assert state["progress"]["pieces"] == {"done": 1, "total": 3}
        assert _post(url + "exam_start", {"tier": "initial"})["exam"]["id"] == state["id"]  # picked up, not restarted
        _post(url + "exam_abort")
        assert _post(url + "exam_state")["exam"] is None
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


def test_an_exam_skipped_throughout_still_finishes_and_is_marked(exam_content):
    from midi_coach.atlas.exam import ExamSession

    exam = ExamSession.new("initial", seed=5, atlas=exam_content)
    while not exam.done:
        exam.skip()
    r = exam.data["result"]
    assert exam.data["status"] == "done" and r["band"] == "Below pass"
    assert [p["mark"] for p in r["sections"]["pieces"]] == [0, 0, 0] and r["sections"]["sight"]["mark"] == 0
    assert r["total"] == r["sections"]["scales"]["mark"] + r["sections"]["aural"]["mark"]
    assert "Not played." in exam.report()
