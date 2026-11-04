"""The fiddle's, the electric guitar's and the bass guitar's trees: Pan's engine with the coach's
own courses (data/fiddle_*, guitar_*, bass_*)."""

from __future__ import annotations

import json

import pytest

from midi_coach import instruments, library, profiles
from midi_coach.atlas import bass, content_dir, fiddle, guitar, pan
from midi_coach.notes import load_score

COURSES = [(fiddle, fiddle.FIDDLE), (guitar, guitar.GUITAR), (bass, bass.BASS)]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MIDI_COACH_ATLAS_CONTENT", raising=False)
    return library.home()


def _tree(module, course):
    atlas, _ = pan.build(module.load_syllabus(), pan.load_tunes(course=course), course)
    atlas["by_id"] = {n["id"]: n for n in atlas["nodes"]}
    return atlas


def _taught(course):
    return {p for ns in course.note_steps + [course.g2_notes] for p in ns["new"]}


@pytest.mark.parametrize("module, course", COURSES, ids=lambda c: getattr(c, "instrument", ""))
def test_every_tune_and_scale_uses_notes_the_course_has_taught(home, module, course):
    tree = _tree(module, course)
    by_id = tree["by_id"]
    assert tree["instrument"] == course.instrument and [t["id"] for t in tree["tiers"]] == ["initial", "g1", "g2"]
    assert by_id[module.FIRST_SOUND_ID]["prereqs"] == []
    first = course.note_steps[0]["key"]
    assert by_id[f"initial.technique.notes.{first}"]["prereqs"] == [module.FIRST_SOUND_ID]
    for t in pan.load_tunes(course=course):
        ps = pan.tune_pitches(t)
        assert set(ps) <= _taught(course), t["id"]
        assert course.lowest <= min(ps) and max(ps) <= course.highest, t["id"]
    for n in tree["nodes"]:
        if n.get("level") == "requirement" and n.get("kind") == "technique":
            assert set(pan.technique_music(n["spec"], course.lowest)["pitches"]) <= _taught(course), n["id"]


def test_fiddle_scales_are_bowed_separate_then_slurred(tmp_path):
    tunes = [t for t in pan.load_tunes(course=fiddle.FIDDLE) if t["id"] == "twinkle-twinkle"]
    report = pan.write(fiddle.load_syllabus(), out=tmp_path / "fiddle", tunes=tunes, sight_count=1, course=fiddle.FIDDLE)
    assert report["problems"] == []
    speed = json.loads((tmp_path / "fiddle" / "lessons" / "g1.technique.scales.scale-d-major-octave.speed.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in speed["steps"]] == ["read", "listen", "play-separate", "play-slurred"]
    xml = (tmp_path / "fiddle" / "lessons" / "pieces" / "twinkle-twinkle.musicxml").read_text(encoding="utf-8")
    assert "Fiddle" in xml and "clef-octave-change" not in xml


@pytest.mark.parametrize("course, sign", [(guitar.GUITAR, "G"), (bass.BASS, "F")])
def test_guitar_and_bass_are_written_an_octave_up_and_stored_sounding(tmp_path, course, sign):
    tunes = [t for t in pan.load_tunes(course=course) if t["id"] == "hot-cross-buns"]
    syllabus = pan.load_own_syllabus(f"{course.instrument}_syllabus.json")
    report = pan.write(syllabus, out=tmp_path / course.folder, tunes=tunes, sight_count=1, course=course)
    assert report["problems"] == []
    path = tmp_path / course.folder / "lessons" / "pieces" / "hot-cross-buns.musicxml"
    xml = path.read_text(encoding="utf-8")
    assert f"<sign>{sign}</sign>" in xml and "<clef-octave-change>-1</clef-octave-change>" in xml
    written = sorted(set(pan.tune_pitches(tunes[0])))
    assert sorted({n.pitch for n in load_score(path).notes}) == [p - 12 for p in written]  # what the microphone hears


def test_guitar_chords_are_taught_but_not_graded():
    tree = _tree(guitar, guitar.GUITAR)
    chords = [n for n in tree["nodes"] if n.get("level") == "requirement" and "chord" in n["id"]]
    assert chords and all(n["kind"] == "theory" for n in chords)


def test_the_profile_picks_the_string_instruments(home):
    p = profiles.create("Sam", instrument="fiddle")
    assert content_dir().name == "fiddle" and instruments.uses_mic() and instruments.player_word() == "fiddler"
    assert instruments.page_config()["strings"] is None
    profiles.set_instrument(p["id"], "guitar")
    cfg = instruments.page_config()
    assert content_dir().name == "guitar" and cfg["strings"] == [40, 45, 50, 55, 59, 64] and cfg["transpose"] == 0
    profiles.set_instrument(p["id"], "bass")
    assert content_dir().name == "bass" and instruments.page_config()["mic"]["fmin"] < 41.2  # a low E
    assert profiles.active()["instruments"] == ["fiddle", "guitar", "bass"]


# -- the welcome, the Maestro, the microphone and the Maestro's lessons --------------------------------


@pytest.mark.parametrize("instrument, word, check", [("fiddle", "fiddle", "a4"), ("guitar", "guitar", "e5"), ("bass", "bass", "a2")])
def test_the_welcome_asks_about_the_string_instrument(instrument, word, check):
    from midi_coach.atlas import welcome

    qs = {q["id"]: q for q in welcome.questions(instrument)}
    assert word in qs["played"]["prompt"] and "f3" not in qs and check in qs
    right = {q["id"]: q["answer"] for q in qs.values() if q["kind"] == "check"}
    assert welcome.correct(right) == len(welcome.CHECKS)


def test_the_maestro_teaches_a_fiddler_a_guitarist_and_a_bassist(home):
    from types import SimpleNamespace as NS

    from midi_coach import chat, stt

    usage = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    for instrument, player in [("fiddle", "fiddler"), ("guitar", "guitarist"), ("bass", "bassist")]:
        calls = []

        def create(**kw):
            calls.append(kw)
            return NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text="Lovely.")])

        client = NS(messages=NS(create=create), beta=NS(messages=NS(create=create)))
        voice_chat = chat.VoiceChat({}, lambda: "", client=client, instrument=lambda i=instrument: i)
        assert voice_chat.ask("how was that")["reply"] == "Lovely."
        assert calls[0]["system"] == chat.SYSTEMS[instrument] + chat.PART_SYSTEM + chat.PAGE_SYSTEM
        assert f"[The {player} said]" in calls[0]["messages"][0]["content"] and "{" not in chat.SYSTEMS[instrument]
        assert chat.LESSON_SYSTEMS[instrument] and "Maestro" in stt.HINTS[instrument]
    assert "not graded" in chat.GUITAR_SYSTEM and "bow" in chat.FIDDLE_SYSTEM and "drums" in chat.BASS_SYSTEM


def test_a_guitarist_listens_on_the_microphone_and_gets_lessons_in_guitar_notation(home):
    import asyncio

    from midi_coach import server
    from midi_coach.midi_io import MIC_PORT

    profiles.create("Sam", instrument="guitar")
    assert server._cmd_ports({})["default"] == MIC_PORT
    assert "written pitch" in server._instrument_line() and server._profile_view()["instrument"]["strings"]
    out = asyncio.run(server.create_lesson("Open E", "e'4 f' g' f' e'1", None, "4/4", "C", 72))
    xml = open(out["path"], encoding="utf-8").read()
    assert "<clef-octave-change>-1</clef-octave-change>" in xml and "Guitar" in xml
    assert sorted({n.pitch for n in load_score(out["path"]).notes}) == [64, 65, 67]  # as it sounds


def test_the_maestro_can_turn_the_tab_on_and_off(monkeypatch):
    from midi_coach import chat, display, server

    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    q = hub._subscribe()
    while not q.empty():
        q.get_nowait()
    tool = next(t for t in chat.TOOLS if t["name"] == "page_control")
    assert "tab" in tool["input_schema"]["properties"]
    assert server._voice_page(tab=False) == {"done": {"tab": False}}
    assert q.get_nowait() == {"type": "page", "tab": False}
