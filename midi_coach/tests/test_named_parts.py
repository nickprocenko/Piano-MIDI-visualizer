"""Named parts: a part saved as what the user plays it on ('flute'), the rest of the file as
the backing band."""
import time

import mido
import pytest

from midi_coach import instruments, library, midi_io, server, tracks
from midi_coach.notes import CHORD_GAP, effective_hands, find_part, named_roles, one_line, select_notes
from midi_coach.tests.test_midi_coach import BPM, PPQ, FakeOut, _until, fake_rtmidi, ref  # noqa: F401  (fixtures)


def _write_band(path):
    """8 bars of 4/4 for a band: a flute line in bars 5-6 only (played legato, its notes running
    a little into the next, one with a grace note), a bass, a string pad named only by its
    instrument and drums."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))
    mid.tracks.append(meta)

    def track(name, channel, program, notes):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        if program is not None:
            tr.append(mido.Message("program_change", program=program, channel=channel))
        events = []
        for beat, length, pitch in notes:
            events.append((round(beat * PPQ), 1, pitch))
            events.append((round((beat + length) * PPQ), 0, pitch))
        now = 0
        for tick, on, pitch in sorted(events):
            tr.append(mido.Message("note_on" if on else "note_off", note=pitch, velocity=70 if on else 0,
                                   channel=channel, time=tick - now))
            now = tick
        mid.tracks.append(tr)

    flute = [(16 + b, 1.1, 72 + b % 5) for b in range(8)]  # each runs a tenth of a beat into the next
    flute.append((19 - 0.02, 0.03, 74))  # a grace note just before beat 19
    track("Flute", 5, 73, flute)
    track("Bass Gtr", 0, 33, [(b, 1, 40) for b in range(32)])
    track("Track 3", 2, 48, [(b * 4, 4, 60) for b in range(8)])  # strings, by program only
    track("Drums", 9, 0, [(b, 0.5, 36) for b in range(32)])
    mid.save(str(path))
    return path


@pytest.fixture()
def band(ref, tmp_path, monkeypatch):
    _write_band(tmp_path / "songs" / "Band Song.mid")
    monkeypatch.setattr(instruments, "uses_mic", lambda instrument=None: True)
    return library.get_score("band song")


def test_find_part_by_name_then_instrument(band):
    assert [p.name for p in find_part(band, "flute")] == ["Flute"]
    assert [p.name for p in find_part(band, "Strings")] == ["Track 3"]  # GM 48: String Ensemble 1
    assert find_part(band, "drums") == [] and find_part(band, "sax") == []


def test_named_part_is_one_clean_line(band):
    flute = next(p.index for p in band.parts if p.name == "Flute")
    role = library.name_part(band, "Flute", flute, keep_hands=False)
    assert role == "flute" and named_roles(band) == ["flute"]
    notes, info = select_notes(band, "flute")
    assert {n.part for n in notes} == {flute} and info["method"] == f"flute part [{flute}]"
    assert len(notes) == 8  # the grace note is dropped for the note it leads into
    assert all(b.start >= a.end - 1e-9 for a, b in zip(notes, notes[1:]))  # no overlaps left
    assert [band.position(n.start)[0] for n in (notes[0], notes[-1])] == [5, 6]
    assert len(select_notes(band, "flute", bars=(6, 6))[0]) == 4
    assert effective_hands(band) == {}  # no guessed hands next to a named part
    with pytest.raises(ValueError):
        select_notes(band, "oboe")


def test_one_line_keeps_chords_on_a_keyboard(band, monkeypatch):
    monkeypatch.setattr(instruments, "uses_mic", lambda instrument=None: False)
    flute = next(p.index for p in band.parts if p.name == "Flute")
    library.name_part(band, "flute", flute, keep_hands=False)
    assert len(select_notes(band, "flute")[0]) == 9  # as written


def test_one_line():
    from midi_coach.notes import Note

    notes = [Note(60, 0.0, 1.2, 70), Note(64, 1.0, 2.0, 70), Note(67, 1.0 + CHORD_GAP / 2, 1.5, 70)]
    assert [(n.pitch, n.start, n.end) for n in one_line(notes)] == [(60, 0.0, 1.0), (67, 1.0 + CHORD_GAP / 2, 1.5)]


def test_naming_a_part_clears_the_hands_and_keeps_settings(band):
    ix = {p.name: p.index for p in band.parts}
    library.save_hands(band, {ix["Flute"]: "right", ix["Bass Gtr"]: "left"})
    library.save_song_settings(band.path, lead_in=3)
    library.name_part(band, "flute", ix["Flute"], keep_hands=False)
    library._score_cache.clear()
    again = library.get_score("band song")
    assert again.roles == {ix["Flute"]: "flute"} and again.hands == {}
    assert library.song_settings(band.path)["lead_in"] == 3  # a new part choice keeps the settings
    library.name_part(again, "strings", ix["Track 3"], keep_hands=True)
    assert named_roles(again) == ["flute", "strings"]


def test_song_settings_defaults_and_limits(band):
    assert library.song_settings(band.path) == {"lead_in": 2, "lead_in_every_pass": True, "gains": {}, "played": {},
                                                "tracks": {}, "play": None, "practice": None}
    assert library.save_song_settings(band.path, lead_in=20)["lead_in"] == 8
    assert library.save_song_settings(band.path, lead_in=-1, lead_in_every_pass=False)["lead_in"] == 0


def test_practice_settings_are_kept_per_piece(band):
    """The Session's bars, tempo, loop and mode come back with the piece, cleaned to what the page shows."""
    assert library.practice_settings(band.path) is None
    out = server._cmd_practice_settings({"path": band.path, "from": "5", "to": "3", "tempo": 400, "loop": True,
                                         "mode": "rehearse", "hand": "left"})
    assert out["practice"] == {"from": 5, "to": 5, "tempo": 150, "loop": True, "mode": "rehearse"}
    library.save_song_settings(band.path, practice={"from": "", "to": None, "tempo": "x", "mode": "record"})
    assert library.practice_settings(band.path) == {"from": None, "to": None}
    assert library.song_settings(band.path)["lead_in"] == 2  # the rest of the file's settings untouched
    assert "error" in server._cmd_practice_settings({"path": band.path + ".gone"})


def test_score_event_carries_the_pieces_practice(band):
    from midi_coach.display import DisplayHub
    library.save_song_settings(band.path, practice={"from": 3, "to": 6, "tempo": 70, "loop": False, "mode": "learn"})
    msg = DisplayHub()._score_message(band.path)
    assert msg["type"] == "score" and msg["path"] == band.path
    assert msg["practice"] == {"from": 3, "to": 6, "tempo": 70, "loop": False, "mode": "learn"}


def test_band_is_every_other_part(band):
    ix = {p.name: p.index for p in band.parts}
    library.name_part(band, "flute", ix["Flute"], keep_hands=False)
    lanes, voices, gains = server._track_lanes(band, "5-6", skip_part="flute", voice_all=True)
    bass, strings, drums = str(ix["Bass Gtr"]), str(ix["Track 3"]), str(ix["Drums"])
    assert set(lanes) == {bass, strings, drums} and gains == {bass: 1.0, strings: 1.0, drums: 1.0}
    t0, t1 = band.bar_range_times(5, 6)
    assert all(t0 - 1e-6 <= n.start < t1 for notes in lanes.values() for n in notes)
    assert voices == {bass: (0, 33), strings: (2, 48), drums: (9, 0)}
    _, voices, _ = server._track_lanes(band, None, skip_part="flute", voice_all=True, keyboard=True)
    assert voices[bass][0] not in (0, 2, 5, 9)  # off the keyboard's channel, onto a free one


def test_accompanist_voices_each_lane(fake_rtmidi):
    acc = midi_io.Accompanist()
    acc.voices({"Bass": (1, 33), "Drums": (9, 0)})
    now = time.perf_counter()
    acc.schedule([(0.0, [0x90, 40, 80]), (0.05, [0x80, 40, 0])], now, "Bass")
    acc.schedule([(0.0, [0x90, 36, 80]), (0.05, [0x80, 36, 0])], now, "Drums")
    _until(lambda: [0x89, 36, 0] in [m for _, m in FakeOut.sent])
    acc.close()
    assert [m for _, m in FakeOut.sent] == [[0xC1, 33], [0x91, 40, 80], [0x99, 36, 80], [0x81, 40, 0], [0x89, 36, 0]]


def _name_flute(band):
    library.name_part(band, "flute", next(p.index for p in band.parts if p.name == "Flute"), keep_hands=False)


def test_sections_split_on_long_gaps(band):
    _name_flute(band)
    assert server.part_sections(band, "flute") == [(5, 6)]
    bass = next(p.index for p in band.parts if p.name == "Bass Gtr")
    band.notes = [n for n in band.notes if not (n.part == bass and 2 <= band.position(n.start)[0] <= 7)]
    library.name_part(band, "bass", bass, keep_hands=True)
    assert server.part_sections(band, "bass") == [(1, 8)]  # a 6-bar gap isn't a new section
    band.notes = [n for n in band.notes if not (n.part == bass and n.start < band.bars[0].end)]
    assert server.part_sections(band, "bass") == [(8, 8)]


def test_default_part_is_the_profile_instrument_then_history(band, monkeypatch):
    _name_flute(band)
    library.name_part(band, "strings", next(p.index for p in band.parts if p.name == "Track 3"), keep_hands=True)
    monkeypatch.setattr(instruments, "current", lambda: "flute")
    assert library.default_part(band) == "flute"
    monkeypatch.setattr(instruments, "current", lambda: "piano")
    assert library.default_part(band) == "flute"  # nothing played yet: the first
    library.save_song_settings(band.path, played={"flute": 1, "strings": 3})
    assert library.default_part(band) == "strings"


def test_lead_in_bars(band):
    assert server._lead_in_start(band, 5, 1) == 3  # 2 bars before bar 5
    assert server._lead_in_start(band, 6, 2) == 4
    assert server._lead_in_start(band, 1, 1) is None  # nothing before bar 1
    library.save_song_settings(band.path, lead_in_every_pass=False)
    assert server._lead_in_start(band, 5, 2) is None and server._lead_in_start(band, 5, 1) == 3
    library.save_song_settings(band.path, lead_in=0)
    assert server._lead_in_start(band, 5, 1) is None
    library.save_song_settings(band.path, lead_in=8)
    assert server._lead_in_start(band, 5, 1) == 1


def test_learn_lead_in_plays_the_band_up_to_the_first_note(band):
    from midi_coach import live
    from midi_coach.tests.test_midi_coach import FakeAccompanist, RecordingHub, _on

    _name_flute(band)
    flute, _ = select_notes(band, "flute")
    lanes, _, _ = server._track_lanes(band, "3-6", skip_part="flute", voice_all=True)
    lanes = {next(p.name for p in band.parts if str(p.index) == k): v for k, v in lanes.items()}
    acc = FakeAccompanist()
    sess = live.LiveSession("wait", band, flute, RecordingHub(), backing=lanes, accompanist=acc, lead_in=band.bars[2].start)
    sess.start()
    try:
        first = flute[0].start
        ons = [(lane, m[1]) for _, events, lane in acc.scheduled for _, m in events if m[0] & 0xF0 == 0x90]
        assert {lane for lane, _ in ons} == {"Bass Gtr", "Track 3", "Drums"}
        assert len([1 for lane, _ in ons if lane == "Bass Gtr"]) == 8  # bars 3-4, nothing from bar 5 on
        offs = [t for start, events, _ in acc.scheduled for t, m in events if m[0] & 0xF0 == 0x80]
        assert max(offs) <= first - band.bars[2].start + 0.5 + 1e-6  # silent soon after the first note is due
        acc.scheduled.clear()
        sess.on_message(5.0, _on(flute[0].pitch))  # the right note: the band plays on to the next one
        assert acc.scheduled and all(start == 5.0 for start, _, _ in acc.scheduled)
    finally:
        sess.stop()


def test_page_start_plays_the_named_part_over_the_band(band, fake_rtmidi, monkeypatch):
    from midi_coach import display
    from midi_coach.tests.test_midi_coach import _post

    _name_flute(band)
    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    try:
        _post(url + "load", {"lesson": "band song"})
        started = _post(url + "start", {"mode": "learn", "loop": True, "port": "JUNO-DS 0"})
        assert started["mode"] == "wait", started
        assert started["selection"]["hand"] == "flute" and started["selection"]["bars"] == "5-6"
        session = server._live["session"]
        ix = {p.name: str(p.index) for p in band.parts}
        assert set(session.lanes) == {ix["Bass Gtr"], ix["Track 3"], ix["Drums"]} and session.lead_in == band.bars[2].start
        assert [0xC0, 33] in [m for _, m in FakeOut.sent] and [0xC2, 48] in [m for _, m in FakeOut.sent]
        assert library.song_settings(band.path)["played"] == {"flute": 1}
        _post(url + "track", {"index": int(ix["Drums"]), "vol": 25})
        assert session.accompanist.gains[ix["Drums"]] == 0.25  # heard from the next note
        assert library.song_settings(band.path)["tracks"][ix["Drums"]]["vol"] == 25  # kept for the song
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


def test_maestro_finds_or_asks_for_the_part(band):
    assert server._voice_part(band, "Flute") == {"part": "flute"}
    assert named_roles(band) == ["flute"]
    asked = server._voice_part(band, "oboe")
    assert asked["ask"] == "Which track is the oboe part?" and set(asked["tracks"]) == {"Flute", "Bass Gtr", "Track 3"}
    assert server._voice_part(band, "oboe", track="track 3") == {"part": "oboe"}
    assert set(named_roles(band)) == {"flute", "oboe"}


def test_maestro_reads_back_the_setup(band):
    _name_flute(band)
    assert server._readback(band, "flute", "learn", "5-6", True) == \
        "Flute part, bars 5-6, 2-bar lead-in, looping, the band waits for you."
    library.save_song_settings(band.path, lead_in=4, lead_in_every_pass=False)
    assert server._readback(band, "flute", "rehearse", "5-6", True) == \
        "Flute part, bars 5-6, 4-bar lead-in, looping, lead-in on the first pass only."
    library.save_song_settings(band.path, lead_in=0)
    assert server._readback(band, "flute", "learn", None, False) == \
        "Flute part, the whole song, no lead-in, the band waits for you."


def test_maestro_backing_volume_by_name_or_instrument(band, monkeypatch):
    _name_flute(band)
    monkeypatch.setattr(server.hub, "score_path", band.path)
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None})
    assert server._voice_backing_volume("drums", 30) == {"part": "Drums", "volume_percent": 30}
    assert server._voice_backing_volume("strings", 0) == {"part": "Track 3", "volume_percent": 0}  # by its instrument
    mix = tracks.mix(band)
    ix = {p.name: p.index for p in band.parts}
    assert (mix[ix["Drums"]]["vol"], mix[ix["Drums"]]["mute"]) == (30, False)
    assert (mix[ix["Track 3"]]["vol"], mix[ix["Track 3"]]["mute"]) == (100, True)  # 0 mutes it, keeping its level
    error = server._voice_backing_volume("tuba", 50)["error"]
    assert "Bass Gtr" in error and "Flute" not in error  # the part you play isn't backing


def test_maestro_knows_about_parts():
    from midi_coach import chat

    start = next(t for t in chat.TOOLS if t["name"] == "start_practice")
    assert {"part", "track", "lead_in_bars", "lead_in_every_pass"} <= set(start["input_schema"]["properties"])
    assert any(t["name"] == "set_backing_volume" for t in chat.TOOLS)
    assert "set_backing_volume" in server._voice.actions and "readback" in chat.PART_SYSTEM


def test_only_the_named_part_is_drawn(band):
    from midi_coach import display, engraving, sheet

    _name_flute(band)
    assert band.playing == "flute" and sheet.wanted(band) and sheet.staves(band) == ["flute"]
    out = sheet.build(band)
    assert out["staves"] == ["flute"] and out["xml"].count("<part id=") == 1 and "<part-name>Flute</part-name>" in out["xml"]
    assert out["notes"] == 8
    assert engraving.lint(out["xml"])["findings"] == []
    roll = display.roll_notes(band)
    ix = {p.name: p.index for p in band.parts}
    assert len([r for r in roll if r[3] == "flute"]) == 8
    # the backing falls too, by track, for the page to show or hide; never the drums
    assert {r[3] for r in roll} == {"flute", f"track:{ix['Bass Gtr']}", f"track:{ix['Track 3']}"}


def test_a_shown_backing_track_gets_its_own_staff(band):
    from midi_coach import engraving, sheet, tracks

    _name_flute(band)
    ix = {p.name: p.index for p in band.parts}
    tracks.set_mix(band, ix["Track 3"], show=True)
    tracks.set_mix(band, ix["Drums"], show=True)  # drums aren't drawn
    out = sheet.build(band)
    assert out["staves"] == sheet.staves(band) == [f"track:{ix['Track 3']}", "flute"]
    assert out["xml"].count("<part id=") == 2 and "<part-name>Track 3</part-name>" in out["xml"]
    assert out["notes"] == 8 + 8  # the flute's and the strings' notes
    assert engraving.lint(out["xml"])["findings"] == []
    first = sheet.piano_xml(band)
    tracks.set_mix(band, ix["Track 3"], show=False)
    assert sheet.piano_xml(band) != first  # a sheet per set of shown tracks
    # The hands' sheet the same way: the backing staff above the piano.
    library.save_hands(band, {ix["Flute"]: "right", ix["Bass Gtr"]: "left"})
    band.playing = None
    tracks.set_mix(band, ix["Track 3"], show=True)
    out = sheet.build(band)
    assert out["staves"] == [f"track:{ix['Track 3']}", "right", "left"] == sheet.staves(band)
    assert not engraving.lint(out["xml"])["findings"]


def test_a_quick_ornament_is_not_drawn_as_a_chord(band):
    from midi_coach import engraving, sheet
    from midi_coach.notes import Note

    _name_flute(band)
    flute = next(p.index for p in band.parts if p.name == "Flute")
    t = band.bars[5].start  # a turn into bar 6's downbeat, faster than the grid: C6 B5 A5
    spb = 60 / BPM
    band.notes = [n for n in band.notes if n.part != flute] + [
        Note(84, t - 0.24 * spb, t - 0.12 * spb, 70, part=flute, beat=band.beat_of(t - 0.24 * spb)),
        Note(83, t - 0.12 * spb, t - 0.01 * spb, 70, part=flute, beat=band.beat_of(t - 0.12 * spb)),
        Note(81, t - 0.01 * spb, t + 2 * spb, 70, part=flute, beat=band.beat_of(t - 0.01 * spb)),
    ]
    out = sheet.build(band)
    assert out["notes"] == 3 and "<chord" not in out["xml"]
    assert engraving.lint(out["xml"])["counts"]["chord-in-line"] == 0


def test_engraving_flags_a_chord_in_a_flute_part():
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    xml = grand_staff([], "x", "4/4", melody=[(F(0), F(2), 72, None), (F(0), F(2), 74, None)], melody_name="Flute", piano=False)["xml"]
    assert engraving.lint(xml)["counts"].get("chord-in-line") == 1
    vocals = grand_staff([], "x", "4/4", melody=[(F(0), F(2), 72, None), (F(0), F(2), 74, None)], piano=False)["xml"]
    assert engraving.lint(vocals)["counts"]["chord-in-line"] == 0  # a sung part may split


def test_page_parts_menu_for_a_named_part(band, monkeypatch):
    ix = {p.name: p.index for p in band.parts}
    monkeypatch.setattr(server.hub, "score_path", band.path)
    monkeypatch.setattr(server, "_show", lambda score, notes: None)
    monkeypatch.setattr(server, "_busy", lambda: False)
    # Saving the roles from the page: a named part on its own is enough, no hands needed.
    out = server._cmd_set_parts({"roles": {str(ix["Flute"]): "Flute", str(ix["Bass Gtr"]): "off"}})
    assert out["named"] == ["flute"] and out["playing"] == "flute" and out["choices"] == ["flute"] and out["play"] == "flute"
    assert [(t["name"], t["part"], t["yours"]) for t in out["tracks"]] == [
        ("Flute", "flute", True), ("Bass Gtr", "backing", False), ("Track 3", "backing", False), ("Drums", "backing", False)]
    assert out["song"] == {"lead_in": 2, "lead_in_every_pass": True}
    out = server._cmd_song_settings({"lead_in": 4, "lead_in_every_pass": False})
    assert out["song"] == {"lead_in": 4, "lead_in_every_pass": False}
    server._cmd_set_parts({"roles": {str(ix["Flute"]): "flute", str(ix["Track 3"]): "strings"}})
    out = server._cmd_song_settings({"play": "strings"})
    assert out["playing"] == out["play"] == "strings" and library.song_settings(band.path)["play"] == "strings"
    assert [t["name"] for t in out["tracks"] if not t["yours"]] == ["Flute", "Bass Gtr", "Drums"]
    assert "error" in server._cmd_song_settings({"play": "tuba"})
    with pytest.raises(ValueError):
        server._save_parts(band, {"vocals": [ix["Flute"]]})  # nothing to play


def test_listen_plays_every_track_as_itself(band, fake_rtmidi, monkeypatch):
    from midi_coach import display

    _name_flute(band)
    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.start()
    ix = {p.name: p.index for p in band.parts}
    tracks.set_mix(band, ix["Drums"], listen_mute=True)
    try:
        out = server._begin_listen(band.path)
        assert out["bars"] is None, out  # the whole song
        session = server._live["session"]
        assert set(session.lanes) == {str(i) for i in ix.values()}
        assert ix["Drums"] not in {n.part for n in session.notes}  # muted: the cursor follows what sounds
        assert session.accompanist.gains[str(ix["Drums"])] == 0.0
        assert [0xC5, 73] in [m for _, m in FakeOut.sent]  # the flute sounds as a flute
    finally:
        server._practice["stopping"] = True
        session = server._live.get("session")
        if session:
            session.stop()
        server.hub.shutdown()
    server._live["session"] = None
    try:
        server.hub.start()
        server._begin_listen(band.path, roles=["flute"])  # a lesson's Listen step: just that part
        assert set(server._live["session"].lanes) == {str(ix["Flute"])}
    finally:
        server._practice["stopping"] = True
        server._live["session"].stop()
        server.hub.shutdown()
