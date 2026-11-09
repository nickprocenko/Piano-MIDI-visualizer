"""Playlists: every keyboard part of a band's songs, in order, stepped through on the coach page."""

from __future__ import annotations

import json
import pathlib
import sys

import mido
import pytest

from midi_coach import library, lessons, playlist
from midi_coach.notes import keyboard_parts, load_score

TOOLS = pathlib.Path(__file__).resolve().parents[2] / "tools"


def _song(path, tracks, bars=8):
    """A band MIDI file: tracks are (name, program or 'drums', [pitches...]), one note per
    eighth for `bars` bars of 4/4 at 120, cycling through the pitches."""
    mid = mido.MidiFile(ticks_per_beat=480)
    meta = mido.MidiTrack([mido.MetaMessage("time_signature", numerator=4, denominator=4),
                           mido.MetaMessage("set_tempo", tempo=500000)])
    mid.tracks.append(meta)
    for i, (name, program, pitches) in enumerate(tracks):
        channel = 9 if program == "drums" else (i if i < 9 else i + 1)
        tr = mido.MidiTrack([mido.MetaMessage("track_name", name=name)])
        if program != "drums":
            tr.append(mido.Message("program_change", channel=channel, program=program))
        for k in range(bars * 8):
            chord = pitches[k % len(pitches)]
            chord = chord if isinstance(chord, tuple) else (chord,)
            for j, p in enumerate(chord):
                tr.append(mido.Message("note_on", channel=channel, note=p, velocity=80, time=0))
            for j, p in enumerate(chord):
                tr.append(mido.Message("note_off", channel=channel, note=p, velocity=0, time=240 if j == 0 else 0))
        mid.tracks.append(tr)
    mid.save(path)
    return path


@pytest.fixture
def library_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    folder = tmp_path / "songs"
    folder.mkdir()
    monkeypatch.setenv("MIDI_COACH_REFERENCE_DIRS", str(folder))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "missing.json"))
    library._score_cache.clear()
    return folder


def test_keyboard_parts_takes_every_keyboard_and_nothing_else(tmp_path):
    path = _song(tmp_path / "band.mid", [
        ("Elec Piano", 4, [60, 64, 67, 72]),
        ("Organ", 18, [(55, 59, 62), (57, 60, 64)]),
        ("organ O1R/W", 61, [76, 79, 81, 83, 84]),  # named an organ, on a brass sound
        ("Track 5", 81, [70, 72, 74]),  # a sawtooth lead, no useful name
        ("snare", 17, [38, 40]),  # a drum on an organ program
        ("synth voice", 54, [65, 67]),  # the vocal line
        ("Bass", 33, [36, 38]),
        ("Track 9", 30, [52, 55]),  # distortion guitar
        ("Organ double", 18, [(67, 71, 74), (69, 72, 76)]),  # the organ an octave up: a doubling
        ("Drums", "drums", [36, 38]),
        ("Split chord", 18, [50, 52]),  # the low notes of the organ's chords, on their own channel
    ])
    score = load_score(path)
    groups = keyboard_parts(score)
    names = [[score.parts[i].name for i in g] for g in groups]
    # One organ of the two an octave apart is kept (the one nearer the middle of the keyboard),
    # with the low notes of its chords from another channel as the same part.
    assert ["Organ double", "Split chord"] in names
    assert {n for g in names for n in g} == {"Elec Piano", "Organ double", "Split chord", "organ O1R/W", "Track 5"}
    # Chords split by register come as two hands; a one-hand line above middle C goes to the
    # right hand alone.
    assert sorted(sorted(g.values()) for g in groups) == [["left", "right"], ["right"], ["right"], ["right"]]


def test_keyboard_parts_pairs_two_hands():
    from midi_coach.tests.test_midi_coach import _band

    eighths = [k * 0.25 for k in range(64)]
    rh = [(t, (72, 76)[k % 2], 0.25) for k, t in enumerate(eighths)]
    lh = [(t, (48, 43)[k % 2], 0.5) for k, t in enumerate(eighths[::2])]
    score = _band([(0, "Piano RH", rh), (0, "Piano LH", lh), (81, "Lead", [(t, 84, 0.25) for t in eighths])])
    assert keyboard_parts(score) == [{0: "right", 1: "left"}, {2: "right"}]
    # A line low in the bass (a synth sequence) is the left hand's; one across both, both hands'.
    low = _band([(81, "Sequence", [(t, (40, 43, 45)[k % 3], 0.25) for k, t in enumerate(eighths)]),
                 (0, "Piano", [(t, (48, 72)[k % 2], 0.25) for k, t in enumerate(eighths)])])
    assert keyboard_parts(low) == [{0: "left"}, {1: "both"}]


def test_build_playlist_orders_every_part_and_steps_through(library_dir, monkeypatch):
    from midi_coach import server

    for name in ("score_path", "_score_key", "_score_payload"):  # the sheet this test shows goes again after it
        monkeypatch.setattr(server.hub, name, getattr(server.hub, name))

    a = _song(library_dir / "Band - Alpha [1].mid", [("Piano", 0, [(60, 64, 67), (62, 65, 69)]), ("Organ", 18, [(50, 53), (51, 55)]),
                                                     ("Bass", 33, [36])])
    _song(library_dir / "Band - Alpha [2].mid", [("Piano", 0, [60, 64, 67])])  # fewer keyboard notes
    b = _song(library_dir / "Band - Beta [3].mid", [("Lead", 81, [72, 74, 76])])
    _song(library_dir / "Other - Beta [4].mid", [("Piano", 0, [60] * 3, )])  # another artist's Beta
    _song(library_dir / "Band - Gamma [5].mid", [("Guitar", 27, [52, 55])])  # no keyboard

    out = playlist.build_playlist("Album", ["Alpha", "Beta", "Gamma", "Delta"], artist="Band")
    assert out["missing"] == ["Gamma", "Delta"] and out["entries"] == 3
    folder = lessons.lessons_dir("Album")
    data = lessons.read_playlist(folder)
    assert [(e["song"], e["part"]) for e in data["entries"]] == [("Alpha", "Piano"), ("Alpha", "Organ"), ("Beta", "Sawtooth Lead")]
    assert [e["file"] for e in data["entries"]] == ["01 Alpha – Piano.mid", "02 Alpha – Organ.mid", "03 Beta – Sawtooth Lead.mid"]
    for e, src in zip(data["entries"], (a, a, b)):  # untouched copies of the chosen version
        assert (folder / e["file"]).read_bytes() == pathlib.Path(src).read_bytes()
        assert set(library.load_hands(library.get_score(str(folder / e["file"])))) == set(e["parts"])

    # The Songs panel lists the playlist in order, whatever the files' dates.
    (folder / "zz extra.mid").write_bytes((folder / data["entries"][0]["file"]).read_bytes())
    menu = server._cmd_lessons({})
    mine = [x for x in menu["lessons"] if x["category"] == "Album"]
    assert [x["title"] for x in mine] == ["01 Alpha – Piano", "02 Alpha – Organ", "03 Beta – Sawtooth Lead", "zz extra"]
    assert [x["track"] for x in mine] == [1, 2, 3, 4]

    # ◀ ▶ on the page come from where the piece sits.
    second = str(folder / data["entries"][1]["file"])
    at = lessons.playlist_position(second)
    assert at["playlist"] == "Album" and (at["track"], at["total"]) == (2, 4)
    assert at["previous"] == str(folder / data["entries"][0]["file"]) and at["next"] == str(folder / data["entries"][2]["file"])
    assert lessons.playlist_position(str(folder / data["entries"][0]["file"]))["previous"] is None
    assert lessons.playlist_position(a) is None
    server._cmd_load({"lesson": second})
    payload = server.hub._score_payload
    assert payload["playlist"]["track"] == 2

    # Moving a piece out with organize_lesson takes it off the playlist; renaming keeps it.
    lessons.move_lesson(str(folder / "zz extra.mid"), "Solo piano")
    renamed = lessons.move_lesson(second, "Album", "02 Alpha – Hammond")
    assert [e["file"] for e in lessons.read_playlist(folder)["entries"]][1] == "02 Alpha – Hammond.mid"
    assert lessons.playlist_position(renamed)["track"] == 2

    # A rebuild needs replace, and only replaces a playlist.
    with pytest.raises(FileExistsError):
        playlist.build_playlist("Album", ["Beta"], artist="Band")
    out = playlist.build_playlist("Album", ["Beta"], artist="Band", replace=True)
    assert out["entries"] == 1 and sorted(f.name for f in folder.iterdir()) == ["01 Beta – Sawtooth Lead.mid", "playlist.json"]
    with pytest.raises(FileExistsError):
        playlist.build_playlist("Solo piano", ["Beta"], artist="Band", replace=True)


def test_split_medley_keeps_every_note(tmp_path):
    sys.path.insert(0, str(TOOLS))
    try:
        import split_midi
    finally:
        sys.path.remove(str(TOOLS))
    src = mido.MidiFile(_song(tmp_path / "Band - Side [7].mid", [("Organ", 18, [(60, 64), 62]), ("Bass", 33, [36, 43])]))
    held = mido.MidiTrack([mido.Message("program_change", channel=5, program=0),
                           mido.Message("note_on", channel=5, note=72, velocity=90, time=480 * 7),
                           mido.Message("note_off", channel=5, note=72, velocity=0, time=480 * 3)])  # across the cut at bar 2
    src.tracks.append(held)
    bar = split_midi.bar_ticks(src)
    first, second = split_midi.section(src, 0, 2 * bar), split_midi.section(src, 2 * bar, None)

    def notes(mid, shift=0):
        out = []
        for ti, tr in enumerate(mid.tracks):
            t, sounding = 0, {}
            for m in tr:
                t += m.time
                if m.type == "note_on" and m.velocity:
                    sounding.setdefault((m.channel, m.note), []).append((t, m.velocity))
                elif m.type in ("note_on", "note_off") and sounding.get((m.channel, m.note)):
                    s, v = sounding[(m.channel, m.note)].pop(0)
                    out.append((ti, m.channel, m.note, v, s + shift, t - s))
        return out

    assert sorted(notes(first) + notes(second, 2 * bar)) == sorted(notes(src))
    assert (3, 5, 72, 90, 480 * 7, 480 * 3) in notes(first)  # the held note keeps its length
    tempo = [m for m in second.tracks[0] if m.type == "set_tempo"]
    programs = [m.program for tr in second.tracks for m in tr if m.type == "program_change"]
    assert tempo and programs == [18, 33, 0]  # what was in force at the cut is set at the start
