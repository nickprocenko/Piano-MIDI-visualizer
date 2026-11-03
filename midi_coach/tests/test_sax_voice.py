"""The alto saxophone's and the voice's trees: Pan's engine with their own courses. Uses the
made-up sample sax syllabus in midi_coach/atlas/sample and the coach's own vocal syllabus."""

from __future__ import annotations

import json

import pytest

from midi_coach import instruments, library, profiles
from midi_coach.atlas import PACKAGE, content_dir, pan, sax, voice
from midi_coach.notes import load_score

SAX_SAMPLE = PACKAGE / "sample" / "sax_syllabus.json"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MIDI_COACH_ATLAS_CONTENT", raising=False)
    return library.home()


def _tree(syllabus, course):
    atlas, _ = pan.build(syllabus, pan.load_tunes(course=course), course)
    atlas["by_id"] = {n["id"]: n for n in atlas["nodes"]}
    return atlas


def _taught(course):
    return {p for ns in course.note_steps + [course.g2_notes] for p in ns["new"]}


# -- the saxophone ---------------------------------------------------------------------------------


def test_sax_tree_starts_with_a_first_sound_and_reads_in_written_pitch():
    tree = _tree(pan.load_syllabus(SAX_SAMPLE, sax.SAX), sax.SAX)
    by_id = tree["by_id"]
    assert tree["instrument"] == "sax" and [t["id"] for t in tree["tiers"]] == ["initial", "g1", "g2"]
    assert by_id[sax.FIRST_SOUND_ID]["prereqs"] == []
    assert by_id["initial.technique.notes.b-a-g"]["prereqs"] == [sax.FIRST_SOUND_ID]
    # D minor from the lowest D the alto has (written D4), which First notes teaches.
    assert pan.scale_pitches("D", "minor", "octave", lowest=sax.SAX.lowest)[0] == 62
    # Its latest new note is B flat, and that step comes after the low notes.
    assert "initial.technique.notes.f-sharp-b-flat" in by_id["g1.technique.scales.scale-d-minor-octave"]["prereqs"]
    assert by_id["initial.technique.notes.f-sharp-b-flat"]["prereqs"] == ["initial.technique.notes.low-d-e-f"]
    for t in pan.load_tunes(course=sax.SAX):  # every tune fits the alto and uses notes it has learnt
        assert set(pan.tune_pitches(t)) <= _taught(sax.SAX), t["id"]
        assert sax.SAX.lowest <= min(pan.tune_pitches(t)) and max(pan.tune_pitches(t)) <= sax.SAX.highest


def test_sax_scores_say_they_are_for_an_e_flat_instrument(tmp_path):
    tunes = [t for t in pan.load_tunes(course=sax.SAX) if t["id"] == "hot-cross-buns"]
    report = pan.write(pan.load_syllabus(SAX_SAMPLE, sax.SAX), out=tmp_path / "sax", tunes=tunes, sight_count=1, course=sax.SAX)
    assert report["problems"] == []
    xml = (tmp_path / "sax" / "lessons" / "pieces" / "hot-cross-buns.musicxml").read_text(encoding="utf-8")
    assert "<chromatic>-9</chromatic>" in xml and "Alto Saxophone" in xml
    assert sorted({n.pitch for n in load_score(tmp_path / "sax" / "lessons" / "pieces" / "hot-cross-buns.musicxml").notes}) == \
        [67, 69, 71]  # graded in written pitch: the page adds 9 to what it hears
    speed = json.loads((tmp_path / "sax" / "lessons" / "g1.technique.scales.scale-g-major-octave.speed.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in speed["steps"]] == ["read", "listen", "play-tongued", "play-slurred"]
    assert "'tah'" in json.dumps(json.loads((tmp_path / "sax" / "lessons" / "g1.technique.scales.scale-g-major-octave.tongued.json")
                                            .read_text(encoding="utf-8")))


# -- the voice ---------------------------------------------------------------------------------------


def test_voice_tree_is_the_coachs_own_course():
    tree = _tree(voice.load_syllabus(), voice.VOICE_HIGH)
    by_id = tree["by_id"]
    assert tree["instrument"] == "voice" and [s["title"] for s in tree["strands"]][:3] == ["Songs", "Voice & scales", "Sight-singing"]
    assert by_id["initial.technique.notes.do-re-mi"]["prereqs"] == [voice.FIRST_SOUND_ID]
    scale = by_id["g1.technique.scales.scale-c-major-octave"]
    assert [by_id[s]["stage"]["key"] for s in scale["stages"]] == ["notes", "solfa", "legato", "speed"]
    assert "initial.technique.notes.la-ti-do" in scale["prereqs"]
    for t in pan.load_tunes(course=voice.VOICE_HIGH):
        assert set(pan.tune_pitches(t)) <= _taught(voice.VOICE_HIGH), t["id"]
        assert voice.VOICE_HIGH.lowest <= min(pan.tune_pitches(t)) and max(pan.tune_pitches(t)) <= voice.VOICE_HIGH.highest


def test_a_low_voice_sings_it_an_octave_down_under_a_treble_8_clef(tmp_path):
    tunes = [t for t in pan.load_tunes(course=voice.VOICE_LOW) if t["id"] == "hot-cross-buns"]
    syllabus = voice.load_syllabus()
    for course in (voice.VOICE_HIGH, voice.VOICE_LOW):
        report = pan.write(syllabus, out=tmp_path / course.folder, tunes=tunes, sight_count=1, course=course)
        assert report["problems"] == []
    high, low = (tmp_path / f / "lessons" / "pieces" / "hot-cross-buns.musicxml" for f in ("voice-high", "voice-low"))
    assert "<clef-octave-change>-1</clef-octave-change>" in low.read_text(encoding="utf-8")
    assert [n.pitch + 12 for n in load_score(low).notes] == [n.pitch for n in load_score(high).notes]
    final = json.loads((tmp_path / "voice-low" / "lessons" / "g1.technique.scales.scale-c-major-octave.speed.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in final["steps"]] == ["read", "listen", "play"]  # no tongued/slurred pair for a voice


# -- the profile picks the tree -----------------------------------------------------------------------


def test_the_profile_picks_the_instruments_tree_and_the_voices_octave(home):
    p = profiles.create("Sam", instrument="sax")
    assert content_dir().name == "sax" and instruments.uses_mic() and instruments.page_config()["transpose"] == 9
    profiles.set_instrument(p["id"], "voice")
    assert content_dir().name == "voice-high" and instruments.player_word() == "singer"
    profiles.set_voice(p["id"], "low")
    assert content_dir().name == "voice-low" and instruments.page_config()["mic"]["fmax"] < 1000
    profiles.set_instrument(p["id"], "piano")
    assert content_dir().name == "content" and not instruments.uses_mic()
    assert profiles.active()["instruments"] == ["sax", "voice", "piano"]
    with pytest.raises(ValueError):
        profiles.set_voice(p["id"], "middle")


# -- the welcome, the Maestro and the microphone ------------------------------------------------------


@pytest.mark.parametrize("instrument, word, check", [("sax", "saxophone", "g4"), ("voice", "sing", "c4")])
def test_the_welcome_asks_about_the_instrument(instrument, word, check):
    from midi_coach.atlas import welcome

    qs = {q["id"]: q for q in welcome.questions(instrument)}
    assert word in qs["played"]["prompt"] + qs["why"]["prompt"] and "f3" not in qs and check in qs
    right = {q["id"]: q["answer"] for q in qs.values() if q["kind"] == "check"}
    assert welcome.correct(right) == len(welcome.CHECKS)


def test_the_maestro_teaches_a_saxophonist_and_a_singer(home):
    from types import SimpleNamespace as NS

    from midi_coach import chat, stt

    usage = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    for instrument, system, player in [("sax", chat.SAX_SYSTEM, "saxophonist"), ("voice", chat.VOICE_SYSTEM, "singer")]:
        calls = []

        def create(**kw):
            calls.append(kw)
            return NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text="Lovely.")])

        client = NS(messages=NS(create=create), beta=NS(messages=NS(create=create)))
        voice_chat = chat.VoiceChat({}, lambda: "", client=client, instrument=lambda i=instrument: i)
        assert voice_chat.ask("how was that")["reply"] == "Lovely."
        assert calls[0]["system"] == system and f"[The {player} said]" in calls[0]["messages"][0]["content"]
        assert chat.LESSON_SYSTEMS[instrument] and "Maestro" in stt.HINTS[instrument]
    assert "written pitch" in chat.SAX_SYSTEM and "high or a low voice" in chat.VOICE_SYSTEM


def test_a_singer_listens_on_the_microphone_and_picks_a_voice(home):
    from midi_coach import server
    from midi_coach.midi_io import MIC_PORT

    sam = profiles.create("Sam", instrument="voice", voice="low")
    assert server._cmd_ports({})["default"] == MIC_PORT
    assert "low voice" in server._instrument_line()
    view = server._cmd_profile_voice({"id": sam["id"], "voice": "high"})
    assert view["instrument"] == {**view["instrument"], "id": "voice", "voice": "high", "transpose": 0}
    profiles.set_instrument(sam["id"], "sax")
    assert server._profile_view()["instrument"]["transpose"] == 9 and "written pitch" in server._instrument_line()
