"""Clean (playable.py): the hands' parts made playable, and the sheet that shows them."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction as F

import mido
import pytest

from midi_coach import display, engraving, library, playable, server, sheet
from midi_coach.notes import note_name, select_notes

PPQ = 480


@pytest.fixture
def band(tmp_path, monkeypatch):
    """A band file like Ghostbusters' chorus: an organ playing the bass line an octave up
    under its riff (one hand would need B2 and D5 at once), with a bass guitar, saved with
    the organ in the right hand and the bass in the left."""
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    folder = tmp_path / "songs"
    folder.mkdir()
    monkeypatch.setenv("MIDI_COACH_REFERENCE_DIRS", str(folder))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "missing.json"))
    library._score_cache.clear()
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    mid.tracks.append(meta)

    def track(name, channel, program, chords):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        tr.append(mido.Message("program_change", program=program, channel=channel))
        for pitches in chords:  # one chord a beat
            for p in pitches:
                tr.append(mido.Message("note_on", note=p, velocity=80, channel=channel, time=0))
            for k, p in enumerate(pitches):
                tr.append(mido.Message("note_off", note=p, velocity=0, channel=channel, time=PPQ if k == 0 else 0))
        mid.tracks.append(tr)

    # Per bar: B2+D5 over the bass's B1 (played as B2: the same key twice), A2 written twice
    # with A3 and D5 over the bass's A1 (A3 out of the right hand's reach, the left hand's to
    # take), B3 with G5 over a wide bass chord (neither hand can take B3), then D5 alone.
    organ = [(47, 74), (45, 45, 57, 74), (59, 79), (74,)] * 4
    bass = [(35,), (33,), (29, 41), (33,)] * 4
    track("Hammond Organ", 1, 16, organ)
    track("Slap Bass", 2, 36, bass)
    path = folder / "Organ Band.mid"
    mid.save(str(path))
    score = library.get_score(str(path))
    library.save_hands(score, {0: "right", 1: "left"})
    return str(path)


def _bar1(notes):
    return sorted((round(n.beat, 2), note_name(n.pitch)) for n in notes if n.beat < 4)


def test_clean_plays_doubled_keys_once_moves_and_leaves_out_what_no_hand_reaches(band):
    score = library.get_score(band)
    found = playable.plan(score)
    bar1 = [c for c in found["changes"] if c["bar"] == 1]
    assert Counter(c["kind"] for c in bar1) == {"twice": 3, "moved": 1, "reach": 1}
    assert {(c["beat"], c["note"], c["kind"]) for c in bar1} == {
        (1.0, "B2", "twice"), (2.0, "A2", "twice"), (2.0, "A2", "twice"), (2.0, "A3", "moved"), (3.0, "B3", "reach")}
    assert next(c for c in bar1 if c["kind"] == "moved")["change"] == "moved to the left hand"

    cleaned = playable.apply(score)
    assert _bar1(select_notes(cleaned, "right")[0]) == [(0.0, "D5"), (1.0, "D5"), (2.0, "G5"), (3.0, "D5")]
    assert _bar1(select_notes(cleaned, "left")[0]) == [(0.0, "B2"), (1.0, "A2"), (1.0, "A3"), (2.0, "F2"), (2.0, "F3"), (3.0, "A2")]
    # The file's own notes are untouched; only the cleaned copy lost and moved notes.
    assert len(score.notes) - len(cleaned.notes) == 4 * 4 and not any(n.hand for n in score.notes)
    assert cleaned.clean["summary"].endswith("(bars 1-4).")

    out = sheet.build(cleaned)
    assert "cleaned for two hands" in out["xml"]  # recorded in <identification><source>
    assert "<octave-shift" not in out["xml"]
    assert not engraving.lint(out["xml"])["findings"]


def test_clean_is_saved_per_file_and_redraws_the_sheet(band):
    hub = display.DisplayHub()
    hub.load_score(library.get_score(band))
    state = hub.score_payload()["playable"]
    assert not state["on"] and "bars 1-4" in state["warning"]

    library.set_playable(band, True)
    score = library.get_score(band)
    assert score.clean and library.get_score(band) is score  # cached until something changes
    hub.load_score(score)
    payload = hub.score_payload()
    assert payload["playable"]["on"] and payload["playable"]["warning"] is None
    assert "cleaned for two hands" in payload["xml"]
    assert all(role in ("right", "left") for *_, role in payload["notes"])

    library.save_hands(score, {0: "right", 1: "left"})  # a new part choice keeps Clean on
    assert library.playable_chosen(band)
    library.set_playable(band, False)
    assert library.get_score(band).clean is None


def test_clean_command_reports_what_changed_and_the_sheet_check(band, monkeypatch):
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server.hub, "start", lambda: "http://127.0.0.1:0/")
    server.hub.load_score(library.get_score(band))
    server.hub.score_path = band
    out = server._cmd_playable({"on": True})
    assert out["playable"] == "on" and "now played once" in out["summary"]
    assert out["check"] == "Sheet check: nothing hard to read."
    assert server._cmd_playable({"on": False})["playable"] == "off"
    assert not library.playable_chosen(band)


def test_clean_leaves_a_playable_part_alone(band):
    score = library.get_score(band)
    library.save_hands(score, {1: "left"})  # the bass alone: nothing to clean
    assert playable.plan(library.get_score(band))["changes"] == []


def test_no_octave_mark_over_a_chord_reaching_across_the_staff():
    from midi_coach.transcribe import grand_staff

    # The chorus as it was drawn before Clean: B2 under D5 in the right hand. An 8vb over the
    # chord drew the D5 as D6; the chord stays on ledger lines instead.
    events = [("right", F(b), F(b + 1), p) for b in range(16) for p in (47, 74)] + [("left", F(b * 4), F(b * 4 + 4), 35) for b in range(4)]
    xml = grand_staff(events, "t")["xml"]
    assert not [f for f in engraving.lint(xml)["findings"] if f[0] == "octave-mark-wrong-way"]
    # A low note held in one voice while the other plays on top: a mark over the held note
    # would cover the other voice's notes too (an octave mark is for the whole staff).
    events = [("right", F(0), F(8), 33), ("right", F(8), F(16), 33)]
    events += [("right", F(k), F(k + 1), 74 - (k % 3)) for k in range(16)] + [("left", F(0), F(16), 28)]
    xml = grand_staff(events, "t")["xml"]
    assert not [f for f in engraving.lint(xml)["findings"] if f[0] == "octave-mark-wrong-way"]


def test_lint_catches_an_octave_mark_that_moves_notes_off_the_staff():
    from music21 import chord, clef, meter, spanner, stream
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    part = stream.Part([clef.TrebleClef(), meter.TimeSignature("4/4")])
    chords = [chord.Chord(["B3", "D6"], quarterLength=1) for _ in range(4)]  # B2 + D5 drawn an octave up
    for c in chords:
        part.append(c)
    part.insert(0, spanner.Ottava(chords, type="8vb", transposing=True))
    part.makeMeasures(inPlace=True)
    xml = GeneralObjectExporter(stream.Score([part])).parse().decode("utf-8")
    found = [f for f in engraving.lint(xml)["findings"] if f[0] == "octave-mark-wrong-way"]
    assert found and "D5 under 8vb" in found[0][3]


def test_learn_cursor_gets_to_the_next_chord_before_you_do(tmp_path, monkeypatch):
    from midi_coach import live
    from midi_coach.notes import Bar, Note, Part, Score

    # Eighths at 120 BPM, practiced at 50% (an eighth is due every half second) by a player
    # who plays one every 0.2 s: the cursor used to crawl at the tempo set, behind them.
    notes = [Note(60 + k % 5, k * 0.25, k * 0.25 + 0.25, 80, beat=k * 0.5) for k in range(16)]
    score = Score("e.mid", notes, [Part(0, 1, 0, "Piano", 16, 60, 64, 62.0, 0)], [], [Bar(1, 0, 2, 4, 4, 0, 4), Bar(2, 2, 4, 4, 4, 4, 8)],
                  [(0.0, 120.0)], 4.0)

    class Hub:
        glides: list = []

        def cursor(self, beat, bps=0.0, live=False, until=None):
            if until is not None:
                self.glides.append((until - beat) / bps)

        def __getattr__(self, name):
            return lambda *a, **k: None

    hub = Hub()
    sess = live.LiveSession("wait", score, notes, hub, tempo_percent=50)
    sess.start()
    for k, n in enumerate(notes):
        sess.on_message(k * 0.2, [0x90, n.pitch, 80])
    assert sess.should_stop() == "finished the piece"
    assert hub.glides[0] == pytest.approx(live.GLIDE_SHARE * 0.5)  # before the pace is known: ahead of the tempo
    assert all(sec < 0.2 for sec in hub.glides[3:])  # then ahead of the player
