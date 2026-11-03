"""Pan (the flute's tree), the microphone as an input, and the Maestro for a flute profile.
Uses the made-up sample flute syllabus in midi_coach/atlas/sample (the real one lives only in
the user's MidiCoach folder)."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace as NS

import pytest

from midi_coach import library, profiles
from midi_coach.atlas import PACKAGE, pan
from midi_coach.midi_io import MIC_PORT, Recorder
from midi_coach.notes import note_name

SAMPLE = PACKAGE / "sample" / "pan_syllabus.json"
FEW_TUNES = ["hot-cross-buns", "yankee-doodle"]


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MIDI_COACH_ATLAS_CONTENT", raising=False)
    return library.home()


@pytest.fixture()
def tree():
    atlas, plan = pan.build(pan.load_syllabus(SAMPLE), pan.load_tunes())
    atlas["by_id"] = {n["id"]: n for n in atlas["nodes"]}
    return atlas


def _names(pitches):
    return " ".join(note_name(p) for p in pitches)


# -- the tree ------------------------------------------------------------------------------------


def test_tree_has_first_notes_then_the_grades(tree):
    assert [t["id"] for t in tree["tiers"]] == ["initial", "g1", "g2"] and tree["name"] == "Roadmap"
    by_id = tree["by_id"]
    assert len(by_id) == len(tree["nodes"])
    sound = by_id[pan.FIRST_SOUND_ID]
    assert sound["prereqs"] == [] and by_id[sound["stages"][0]]["prereqs"] == []  # where a beginner starts
    first = by_id["initial.technique.notes.b-a-g"]
    assert first["prereqs"] == [sound["id"]] and by_id[first["stages"][0]]["prereqs"] == [sound["stages"][-1]]
    assert by_id["initial.technique.notes.c-d"]["prereqs"] == ["initial.technique.notes.b-a-g"]
    for n in tree["nodes"]:
        if n["level"] == "requirement":
            stages = [by_id[s] for s in n["stages"]]
            assert stages and stages[-1]["final"] and all(s["stage"]["hand"] == "both" for s in stages)  # one line, no hands
            assert "box" in n
    scale = by_id["g1.technique.scales.scale-c-major-octave"]
    assert [by_id[s]["stage"]["key"] for s in scale["stages"]] == ["notes", "tongued", "slurred", "speed"]
    assert "g1.exam" in by_id and "initial.exam" not in by_id  # no mock exam before Grade 1


def test_tunes_need_the_notes_they_use(tree):
    by_id = tree["by_id"]
    assert by_id["initial.pieces.first-tunes.hot-cross-buns"]["prereqs"] == ["initial.technique.notes.b-a-g"]
    assert "initial.technique.notes.c-d" in by_id["initial.pieces.first-tunes.mary-had-a-little-lamb"]["prereqs"]
    assert "initial.technique.notes.upper-e-f-g" in by_id["g1.pieces.list-a.yankee-doodle"]["prereqs"]  # it climbs to F5
    taught = {p for ns in pan.NOTE_STEPS + [pan.G2_NOTES] for p in ns["new"]}
    for t in pan.load_tunes():
        assert set(pan.tune_pitches(t)) <= taught, t["id"]  # nothing a tune plays goes untaught
        assert pan.LOWEST <= min(pan.tune_pitches(t)) and max(pan.tune_pitches(t)) <= pan.HIGHEST


def test_scales_start_on_the_lowest_tonic_and_are_spelt_in_key():
    assert _names(pan.scale_pitches("F", "major", "octave")) == "F4 G4 A4 Bb4 C5 D5 E5 F5 E5 D5 C5 Bb4 A4 G4 F4"
    assert _names(pan.scale_pitches("E", "minor", "twelfth")).startswith("E4 F#4 G4 A4 B4 C5 D5 E5 F#5 G5 A5 B5 A5 G5 ")
    assert pan.scale_pitches("C", "major", "octave", start_octave=5)[0] == 72  # "an octave above the lowest tonic"
    assert _names(pan.arpeggio_pitches("G", "major", "twelfth")) == "G4 B4 D5 G5 B5 D6 B5 G5 D5 B4 G4"
    assert [pan.spell(p, k) for p, k in [(70, "F"), (78, "G"), (75, "Bb"), (60, "C"), (84, "C"), (55, "C")]] == \
        ["b-", "f'#", "e'-", "c", "c''", "G"]
    m = pan.technique_music({"type": "scale", "tonic": "G", "quality": "major", "range": "octave"})
    assert m["tiny"].endswith("g4") and m["tiny"].count("8") == 14  # quavers, the top-to-bottom tonic held


def test_sight_reading_steps_home_to_the_tonic():
    p = pan.sight_params(pan.load_syllabus(SAMPLE), "g2")
    assert p["keys"] == ["C", "G"] and p["times"] == ["4/4", "3/4"] and p["bars"] == 4
    for seed in range(40):
        piece = pan.sight_piece(p, seed)
        notes = piece["pitches"]
        lo, hi = p["range"]
        tonic = pan.key_tonic(piece["key"])[0]
        assert all(lo <= n <= hi for n in notes)
        assert notes[0] % 12 == tonic and notes[-1] % 12 == tonic
        assert abs(notes[-1] - notes[-2]) <= 2  # the last step is a step


def test_write_makes_every_lesson_lint_clean(tmp_path):
    tunes = [t for t in pan.load_tunes() if t["id"] in FEW_TUNES]
    report = pan.write(pan.load_syllabus(SAMPLE), out=tmp_path / "pan", tunes=tunes, sight_count=1)
    assert report["problems"] == []
    atlas = json.loads((tmp_path / "pan" / "atlas.json").read_text(encoding="utf-8"))
    stages = [n for n in atlas["nodes"] if n["level"] == "stage"]
    missing = [s["id"] for s in stages if not (tmp_path / "pan" / "lessons" / f"{s['id']}.json").exists()]
    assert missing == []  # aural lessons too, by the Atlas's writer
    speed = json.loads((tmp_path / "pan" / "lessons" / "g1.technique.scales.scale-c-major-octave.speed.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in speed["steps"]] == ["read", "listen", "play-tongued", "play-slurred"]
    assert (tmp_path / "pan" / "lessons" / "sight" / "g2-1.musicxml").exists()


# -- the microphone ------------------------------------------------------------------------------


def test_recorder_takes_notes_from_the_microphone():
    rec = Recorder()
    heard = []
    rec.listener = lambda now, msg: heard.append((now, msg))
    assert not rec.feed([0x90, 71, 80])  # nothing listening yet
    assert rec.start(MIC_PORT, silence_sec=30) == MIC_PORT and rec.on_mic
    before = time.perf_counter()
    assert rec.feed([0x90, 71, 80], at=before - 0.05) and rec.feed([0x80, 71, 0])
    assert [m for _, m in heard] == [[0x90, 71, 80], [0x80, 71, 0]]
    assert heard[0][0] == pytest.approx(before - 0.05)  # timed from when the note began, not when it arrived
    assert rec.status()["notes_so_far"] == 1 and rec.status()["port"] == MIC_PORT
    rec.stop()
    assert not rec.feed([0x90, 72, 80])


def test_a_flute_profile_listens_on_the_microphone(home):
    from midi_coach import server

    profiles.create("Flute", instrument="flute")
    assert MIC_PORT in server._cmd_ports({})["inputs"] and server._cmd_ports({})["default"] == MIC_PORT
    assert server._cmd_mic_note({"on": 71})["listening"] is False  # no run going
    port, fell_back = server._start_input(None, 30.0, 60.0, 30.0, None)
    try:
        assert port == MIC_PORT and not fell_back
        assert server._cmd_mic_note({"on": 71, "velocity": 70, "ago_ms": 40})["listening"] is True
        assert server._cmd_mic_note({"off": 71})["listening"] is True
        assert server.recorder.status()["notes_so_far"] == 1
    finally:
        server.recorder.stop()


# -- the Maestro for a flutist ---------------------------------------------------------------------


def _fake_claude(replies, calls):
    def create(**kw):
        calls.append({**kw, "messages": list(kw["messages"])})
        return replies.pop(0)

    return NS(messages=NS(create=create), beta=NS(messages=NS(create=create)))


def test_the_maestro_teaches_the_flute(monkeypatch, tmp_path):
    from midi_coach import chat, stt

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    usage = NS(input_tokens=100, output_tokens=20, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    lesson = {"title": "Long tones", "right": "b1 a1 g1", "left": "", "time_signature": "4/4", "key": "G", "tempo_bpm": 60}
    replies = [
        NS(stop_reason="tool_use", usage=usage, content=[NS(type="tool_use", id="w1", name="write_lesson", input={"request": "long tones"})]),
        NS(stop_reason="tool_use", usage=usage, content=[NS(type="tool_use", id="c1", name="create_lesson", input=lesson)]),
        NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text="Long tones are on your screen.")]),
    ]
    calls = []
    voice = chat.VoiceChat({"create_lesson": lambda **kw: {"path": "long.musicxml", "bars": 3}}, lambda: "",
                           client=_fake_claude(replies, calls), instrument=lambda: "flute")
    assert voice.ask("give me some long tones")["reply"] == "Long tones are on your screen."
    assert calls[0]["system"] == chat.FLUTE_SYSTEM and "[The flutist said]" in calls[0]["messages"][0]["content"]
    assert calls[1]["system"] == chat.FLUTE_LESSON_SYSTEM  # the composer writes one line for the flute

    profiles.create("Flute", instrument="flute")
    assert stt._hint() == stt.FLUTE_HINT and "Maestro" in stt.FLUTE_HINT


# -- examples: from the page, and quiet when the Maestro talks ------------------------------------


class _Hub:
    clients = 1

    def __init__(self):
        self.sounds, self.said = [], []

    def sound(self, notes):
        self.sounds.append(notes)

    def say(self, text, interrupt=False, speaker="Claude"):
        self.said.append(text)


class _Player:
    def __init__(self):
        self.played, self.stops = [], 0

    def play(self, segments, port, gap_sec=1.5):
        self.played.append(segments)
        return "JUNO-DS 0"

    def stop(self):
        self.stops += 1

    def status(self):
        return {"state": "idle", "total_sec": 1.0}


@pytest.fixture()
def quiet_server(home, monkeypatch):
    from midi_coach import server

    hub, player = _Hub(), _Player()
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(server, "player", player)
    return server, hub, player


def test_a_flute_hears_examples_from_the_page_not_the_keyboard(quiet_server):
    server, hub, player = quiet_server
    events = [(0.0, [0x90, 71, 80]), (0.5, [0x80, 71, 0]), (0.5, [0x90, 69, 70]), (1.0, [0x80, 69, 0])]
    profiles.create("Piano")
    assert server._sound([("a", events)], None, 0.8)[0] == "JUNO-DS 0" and len(player.played) == 1
    profiles.create("Flute", instrument="flute")
    port, seconds = server._sound([("a", events), ("b", events)], None, 0.8)
    assert port == server.PAGE_SOUND and seconds == pytest.approx(2.8) and len(player.played) == 1
    assert hub.sounds[-1] == [[0.0, 0.5, 71, 80], [0.5, 0.5, 69, 70], [1.8, 0.5, 71, 80], [2.3, 0.5, 69, 70]]
    assert server._sound([("a", events)], "JUNO-DS 0", 0.8)[0] == "JUNO-DS 0"  # a port named: the keyboard


def test_the_maestro_talking_stops_an_example(quiet_server, monkeypatch):
    server, hub, player = quiet_server
    server._npc_say(lambda: "Lovely tone.")
    assert hub.said == ["Lovely tone."] and hub.sounds == [None] and player.stops == 1
    server._npc_say(lambda: None)  # nothing said: nothing stopped
    assert player.stops == 1
    # The reply to "play it for me" goes with what it plays.
    monkeypatch.setattr(server._voice, "ask", lambda heard: {"reply": "Here it is.", "actions": ["play_passage"]})
    server._answer("play bar one")
    assert hub.said[-1] == "Here it is." and player.stops == 1
    monkeypatch.setattr(server._voice, "ask", lambda heard: {"reply": "Sure.", "actions": []})
    server._answer("how was that")
    assert player.stops == 2
