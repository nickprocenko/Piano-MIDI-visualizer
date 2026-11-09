"""Woodwind fingering: the charts in docs/fingering.js cover every note the flute and sax courses
teach, Find the notes shows the new notes' charts and quizzes them, and the Maestro can turn the
score's diagrams and the monitor on and off."""

from __future__ import annotations

import json
import re

import pytest

from midi_coach.atlas import PACKAGE, fiddle, pan, sax
from midi_coach.display import REPO_ROOT, STATIC_FILES

FINGERING_JS = REPO_ROOT / "docs" / "fingering.js"


def chart_notes(name: str) -> set[int]:
    """The MIDI notes with a chart entry in fingering.js's FLUTE or SAX table, with its octave loops."""
    js = FINGERING_JS.read_text(encoding="utf-8")
    block = re.search(rf"const {name} = \{{(.*?)\n  \}};", js, re.S)[1]
    notes = {int(m) for m in re.findall(r"^\s*(\d+): ", block, re.M)}
    for lo, hi in re.findall(rf"for \(let m = (\d+); m <= (\d+); m\+\+\) {name}\[m\]", js):
        notes |= set(range(int(lo), int(hi) + 1))
    return notes


def taught(course) -> set[int]:
    return {p for ns in course.note_steps + [course.g2_notes] for p in ns["new"]}


@pytest.mark.parametrize("course, table", [(pan.FLUTE, "FLUTE"), (sax.SAX, "SAX")])
def test_every_note_the_course_teaches_has_a_chart(course, table):
    have = chart_notes(table)
    assert taught(course) <= have
    assert min(have) <= course.lowest  # the lowest note of the course's scales


def test_the_coach_page_serves_the_charts():
    assert STATIC_FILES["/fingering.js"][0] == FINGERING_JS
    page = (REPO_ROOT / "midi_coach" / "static" / "coach.html").read_text(encoding="utf-8")
    assert '<script src="fingering.js"></script>' in page
    assert '<script src="fingering.js"></script>' in (REPO_ROOT / "docs" / "notation.html").read_text(encoding="utf-8")


def test_quizzes_ask_for_each_new_note_among_other_letters():
    quizzes = pan.fingering_quizzes("flute", [72, 74], [71, 69, 67])
    assert [q["fingering"] for q in quizzes] == [{"instrument": "flute", "note": 72}, {"instrument": "flute", "note": 74}]
    for q, pitch in zip(quizzes, [72, 74]):
        assert q["type"] == "quiz" and q["graded"] is False and q["prompt"] == "Which note is this?"
        assert len(q["options"]) == 3 and len(set(q["options"])) == 3
        assert q["options"][q["answer"]] == pan.NOTE_NAMES[pitch % 12]


def test_an_octave_up_never_offers_its_own_letter_twice():
    q = pan.fingering_quizzes("sax", [76], [64, 65, 67])[0]  # the upper E, with the low E known
    assert q["options"].count("E") == 1 and q["options"][q["answer"]] == "E"


@pytest.mark.parametrize("course, sample", [(pan.FLUTE, "pan_syllabus.json"), (sax.SAX, "sax_syllabus.json")])
def test_find_the_notes_shows_the_charts_and_quizzes_them(tmp_path, course, sample):
    report = pan.write(pan.load_syllabus(PACKAGE / "sample" / sample, course), out=tmp_path / course.folder, tunes=[],
                       sight_count=1, course=course, lint=False)
    assert report["problems"] == []
    lessons = tmp_path / course.folder / "lessons"
    learn = json.loads((lessons / "initial.technique.notes.c-d.learn.json").read_text(encoding="utf-8"))
    kinds = [s["type"] for s in learn["steps"]]
    assert kinds == ["read", "quiz", "quiz", "listen", "play"]
    assert learn["steps"][0]["fingerings"] == {"instrument": course.instrument, "notes": [72, 74]}
    # Only the playing is graded: the quizzes don't change how the stage is passed.
    assert [s["id"] for s in learn["steps"] if s.get("graded")] == ["play"]
    steady = json.loads((lessons / "initial.technique.notes.c-d.steady.json").read_text(encoding="utf-8"))
    assert [s["type"] for s in steady["steps"]] == ["read", "listen", "play"] and "fingerings" not in steady["steps"][0]
    g2 = json.loads((lessons / "g2.technique.notes.upper-notes.learn.json").read_text(encoding="utf-8"))
    assert g2["steps"][0]["fingerings"]["notes"] == course.g2_notes["new"]


def test_a_fiddle_gets_no_fingering_charts(tmp_path):
    pan.write(fiddle.load_syllabus(), out=tmp_path / "fiddle", tunes=[], sight_count=1, course=fiddle.FIDDLE, lint=False)
    for f in (tmp_path / "fiddle" / "lessons").glob("*.json"):
        lesson = json.loads(f.read_text(encoding="utf-8"))
        assert not any("fingering" in s or "fingerings" in s for s in lesson.get("steps", [])), f.name


def test_the_maestro_can_turn_the_fingering_on_and_off(monkeypatch):
    from midi_coach import chat, display, server

    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    q = hub._subscribe()
    while not q.empty():
        q.get_nowait()
    props = next(t for t in chat.TOOLS if t["name"] == "page_control")["input_schema"]["properties"]
    assert props["fingering"]["enum"] == ["off", "repeats", "line"] and "fingering_monitor" in props
    assert server._voice_page(fingering="line", fingering_monitor=False) == {"done": {"fingering": "line", "fingering_monitor": False}}
    assert q.get_nowait() == {"type": "page", "fingering": "line", "fingering_monitor": False}
