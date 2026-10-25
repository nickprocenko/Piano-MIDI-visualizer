"""Tests for midi-coach using synthetic references, takes and a fake rtmidi."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import random
import sys
import time
import types

import mido
import pytest

from midi_coach import analysis, library, midi_io
from midi_coach.notes import Note, load_score, notes_from_events, parse_bars, select_notes, suggest_hands

BPM = 100
BEAT = 60 / BPM
PPQ = 480


def _write_reference(path, rest_bars=(9, 10), pedal=True):
    """16 bars of 4/4: RH eighth-note melody (track 1), LH whole-bar triads (track 2)."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
    mid.tracks.append(meta)

    def track(name, events):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        last = 0
        for tick, msg in sorted(events, key=lambda e: (e[0], e[1].type == "note_on")):
            tr.append(msg.copy(time=tick - last))
            last = tick
        mid.tracks.append(tr)

    rh, lh = [], []
    scale = [72, 74, 76, 77, 79, 77, 76, 74]
    for bar in range(16):
        if bar + 1 in rest_bars:
            continue
        base = bar * 4 * PPQ
        shift = [0, 2, -1, 3, 1, -2, 4, 0, 2, -3, 1, 5, -1, 3, 0, 2][bar]  # every bar differs
        for k, pitch in enumerate(scale):
            pitch += shift if k % 2 else 0
            on = base + k * PPQ // 2
            vel = 60 + 3 * k  # crescendo within each bar
            rh.append((on, mido.Message("note_on", note=pitch, velocity=vel, channel=0)))
            rh.append((on + PPQ // 2, mido.Message("note_off", note=pitch, velocity=0, channel=0)))
        for pitch in (48, 52, 55):
            lh.append((base, mido.Message("note_on", note=pitch, velocity=50, channel=1)))
            lh.append((base + 4 * PPQ - 10, mido.Message("note_off", note=pitch, velocity=0, channel=1)))
        if pedal:
            lh.append((base + 10, mido.Message("control_change", control=64, value=127, channel=1)))
            lh.append((base + 4 * PPQ - 20, mido.Message("control_change", control=64, value=0, channel=1)))
    track("Right Hand", rh)
    track("Left Hand", lh)
    mid.save(str(path))
    return path


def _perform(score, tempo_ratio=0.8, jitter=0.01, seed=1, edit=None, bars=None):
    """Render the reference as a human-ish take (seconds), optionally edited."""
    rng = random.Random(seed)
    notes = [n for n in score.notes if bars is None or bars[0] <= score.position(n.start)[0] <= bars[1]]
    out = []
    offset = notes[0].start
    for n in notes:
        start = 1.0 + (n.start - offset) / tempo_ratio + rng.uniform(-jitter, jitter)
        out.append(Note(n.pitch, start, start + n.duration / tempo_ratio * 0.9, n.velocity))
    if edit:
        out = edit(out)
    return sorted(out, key=lambda n: n.start)


@pytest.fixture()
def ref(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    folder = tmp_path / "songs"
    folder.mkdir()
    monkeypatch.setenv("MIDI_COACH_REFERENCE_DIRS", str(folder))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "missing.json"))
    path = _write_reference(folder / "Practice Etude in C.mid")
    library._score_cache.clear()
    return load_score(path)


def test_load_reference_parts_bars(ref):
    assert len(ref.bars) == 16
    assert [p.name for p in ref.parts] == ["Right Hand", "Left Hand"]
    assert ref.position(ref.bars[4].start + BEAT * 2) == (5, 3.0)
    rh, info = select_notes(ref, "right")
    assert {n.part for n in rh} == {0} and "track name" in info["method"]
    lh, _ = select_notes(ref, "left", bars=(1, 2))
    assert len(lh) == 6
    assert parse_bars("9-16") == (9, 16) and parse_bars("12") == (12, 12)


def test_perfect_take_at_slower_tempo(ref):
    notes, _ = select_notes(ref, "both")
    take = _perform(ref, tempo_ratio=0.8)
    report = analysis.compare(ref, notes, take, [], bars_given=False)
    assert report["notes"]["wrong"] == report["notes"]["missed"] == report["notes"]["extra"] == 0
    assert report["tempo"]["your_bpm"] == pytest.approx(80, abs=1.5)
    assert report["timing"]["median_error_ms"] < 15
    assert report["scores"]["overall"] >= 90
    assert report["dynamics"]["reference_has_dynamics"]
    assert report["dynamics"]["shape_correlation"] > 0.9


def test_detects_mistakes_with_bar_numbers(ref):
    notes, _ = select_notes(ref, "both")
    bar = lambda b: 1.0 + (ref.bars[b - 1].start) / 0.8  # take time of a bar start  # noqa: E731

    def edit(take):
        take = list(take)
        # Wrong note: first RH note of bar 5 (C5 -> C#5).
        w = min((n for n in take if n.pitch == 72 and n.start >= bar(5) - 0.05), key=lambda n: n.start)
        w.pitch = 73
        # Missed: the E5 in bar 7.
        m = min((n for n in take if n.pitch == 76 and n.start >= bar(7) - 0.05), key=lambda n: n.start)
        take.remove(m)
        # Extra: a stray B3 in bar 3.
        take.append(Note(59, bar(3) + 0.9, bar(3) + 1.0, 40))
        # Hesitation: 0.9 s pause before bar 12.
        for n in take:
            if n.start >= bar(12) - 0.02:
                n.start += 0.9
                n.end += 0.9
        return take

    take = _perform(ref, edit=edit)
    report = analysis.compare(ref, notes, take, [], bars_given=False, detail="full")
    kinds = {(m["type"], m["bar"]) for m in report["mistakes"]}
    assert ("wrong", 5) in kinds
    assert ("missed", 7) in kinds
    assert ("extra", 3) in kinds
    wrong = next(m for m in report["mistakes"] if m["type"] == "wrong")
    assert wrong["expected"] == "C5" and wrong["played"] == "C#5" and wrong["hand"] == "right"
    assert report["tempo"]["hesitations"][0]["bar"] in (11, 12)
    assert report["notes"]["wrong"] == 1 and report["notes"]["missed"] == 1 and report["notes"]["extra"] == 1


def test_partial_take_scope_and_one_hand(ref):
    notes, _ = select_notes(ref, "right")
    rh_ref = [n for n in ref.notes if n.part == 0]
    take = [n for n in _perform(ref, bars=(3, 6)) if n.pitch >= 60]
    report = analysis.compare(ref, rh_ref, take, [], bars_given=False)
    assert report["scope"]["bars"] == "3-6"
    assert report["notes"]["missed"] == 0
    assert report["notes"]["accuracy_pct"] == 100.0


def test_rolled_chord_is_not_a_mistake(ref):
    notes, _ = select_notes(ref, "left")

    def roll(take):
        for n in take:
            if n.pitch == 55:
                n.start += 0.09  # top of the chord arrives 90 ms late
        return take

    take = [n for n in _perform(ref, edit=roll) if n.pitch < 60]
    report = analysis.compare(ref, notes, take, [], bars_given=False)
    assert report["notes"]["extra"] == 0 and report["notes"]["missed"] == 0


def test_pedal_blur_flag(ref):
    notes, _ = select_notes(ref, "both")
    take = _perform(ref, bars=(1, 4))
    # One pedal press held across all four bars.
    pedal = [(take[0].start, 127), (take[-1].end, 0)]
    report = analysis.compare(ref, notes, take, pedal, bars_given=False)
    issues = {f["bar"]: f["issue"] for f in report["pedal"]["bar_flags"]}
    assert any("blur" in v for v in issues.values())


def test_analyze_take_standalone(ref):
    take = _perform(ref, bars=(1, 4))
    out = analysis.analyze_take(take, [(1.0, 127), (3.0, 0)])
    assert out["notes"] == len(take)
    assert out["pulse"]["as_bpm"] == pytest.approx(80 * 2, rel=0.1)  # eighth notes at 80 bpm
    assert out["pedal"]["presses"] == 1


def test_rest_profile_extends_timeout(ref):
    notes, _ = select_notes(ref, "both")
    prof = midi_io.RestProfile.from_notes(notes)
    two_bars = 8 * BEAT
    assert max(prof.rests) == pytest.approx(two_bars, abs=0.1)
    before_rest = sum(1 for n in notes if n.start < ref.bars[8].start)
    assert prof.remaining_max_rest(before_rest) == pytest.approx(two_bars, abs=0.1)
    assert prof.remaining_max_rest(len(notes)) < 1.0


def test_reference_search(ref):
    hits = library.find_references("practice etude")
    assert hits and hits[0]["name"] == "Practice Etude in C.mid"
    assert library.resolve_reference("etude").name == "Practice Etude in C.mid"
    with pytest.raises(FileNotFoundError):
        library.resolve_reference("moonlight sonata")


# ---------------------------------------------------------------------------
# Fake rtmidi: exercises recorder / player / MCP tools end to end
# ---------------------------------------------------------------------------


class FakeIn:
    instance = None

    def __init__(self):
        FakeIn.instance = self
        self.cb = None

    def get_ports(self):
        return ["Microsoft GS Wavetable Synth", "JUNO-DS 0"]

    def open_port(self, idx):
        self.port = idx

    def ignore_types(self, **kw):
        pass

    def set_callback(self, cb):
        self.cb = cb

    def cancel_callback(self):
        self.cb = None

    def close_port(self):
        pass

    def send(self, msg):
        if self.cb:
            self.cb((msg, 0.0))


class FakeOut:
    sent: list = []

    def get_ports(self):
        return ["Microsoft GS Wavetable Synth", "JUNO-DS 0"]

    def open_port(self, idx):
        self.port = idx

    def send_message(self, msg):
        FakeOut.sent.append((time.perf_counter(), list(msg)))

    def close_port(self):
        pass


@pytest.fixture()
def fake_rtmidi(monkeypatch):
    mod = types.SimpleNamespace(MidiIn=FakeIn, MidiOut=FakeOut)
    monkeypatch.setitem(sys.modules, "rtmidi", mod)
    FakeOut.sent = []
    return mod


def test_port_resolution():
    names = ["Microsoft GS Wavetable Synth", "loopMIDI Coach 1", "JUNO-DS 0"]
    assert midi_io.resolve_port(names, None, "X_UNSET", "input") == 2
    assert midi_io.resolve_port(names, "coach", "X_UNSET", "input") == 1
    with pytest.raises(midi_io.PortError):
        midi_io.resolve_port(names, "nope", "X_UNSET", "input")


def test_recorder_waits_through_written_rest(fake_rtmidi):
    # Reference: 4 notes, a 2 s written rest, then 4 notes.
    ref_notes = [Note(60 + k, k * 0.25, k * 0.25 + 0.2, 64) for k in range(4)]
    ref_notes += [Note(60 + k, 3.0 + k * 0.25, 3.2 + k * 0.25, 64) for k in range(4)]
    rec = midi_io.Recorder()
    rec.start(None, silence_sec=0.3, max_sec=30, lead_in_sec=5, rests=midi_io.RestProfile.from_notes(ref_notes))
    fin = FakeIn.instance

    def phrase():
        for k in range(4):
            fin.send([0x90, 60 + k, 70])
            time.sleep(0.05)
            fin.send([0x80, 60 + k, 0])
            time.sleep(0.05)

    phrase()
    time.sleep(1.0)  # longer than silence_sec, shorter than the written rest
    assert rec.status()["state"] == "recording"
    phrase()
    assert rec.wait(5)
    st = rec.status()
    assert st["stop_reason"] == "silence" and st["notes_so_far"] == 8


def test_recorder_plain_silence_stop(fake_rtmidi):
    rec = midi_io.Recorder()
    rec.start(None, silence_sec=0.2, max_sec=30, lead_in_sec=5)
    FakeIn.instance.send([0x90, 60, 70])
    time.sleep(0.4)
    assert rec.status()["state"] == "recording"  # key still held
    FakeIn.instance.send([0x80, 60, 0])
    assert rec.wait(3)
    assert rec.status()["stop_reason"] == "silence"


def test_build_events_tempo_and_range(ref):
    notes, _ = select_notes(ref, "right", bars=(2, 2))
    t0, t1 = ref.bar_range_times(2, 2)
    events = midi_io.build_events(notes, ref.pedal, t0, t1, speed=0.5)
    ons = [t for t, m in events if m[0] & 0xF0 == 0x90]
    assert len(ons) == 8
    assert ons[-1] == pytest.approx(7 * BEAT / 2 / 0.5, abs=1e-6)
    assert events[-1][1] == [0xB0, 64, 0]


def test_mcp_end_to_end(ref, fake_rtmidi):
    from midi_coach import server

    async def run():
        res = await server.start_recording(reference="etude", hand="right", bars="1-2", silence_sec=0.3)
        assert res.get("recording"), res
        fin = FakeIn.instance
        for n in [n for n in ref.notes if n.part == 0 and n.start < ref.bars[2].start]:
            fin.send([0x90, n.pitch, n.velocity])
            time.sleep(0.1)
            fin.send([0x80, n.pitch, 0])
            time.sleep(0.02)  # 120 ms per eighth = a fast but human tempo
        out = await server.wait_for_recording(max_wait_sec=5)
        assert out["state"] == "stopped", out
        comp = out["comparison"]
        assert comp["notes"]["accuracy_pct"] == 100.0, comp["mistakes"]
        assert comp["scope"]["bars"] == "1-2"

        takes = await server.list_takes(reference="etude")
        assert len(takes["takes"]) == 1 and takes["takes"][0]["scores"]
        prog = await server.progress("etude")
        assert len(prog["sessions"]) == 1

        played = await server.play("etude", bars="1", hand="left", tempo_percent=400)
        assert played.get("playing"), played
        server.player._thread.join(5)
        assert any(m[0] == 0x90 and m[1] == 48 for _, m in FakeOut.sent)

        FakeOut.sent = []
        ab = await server.play_comparison(bars="1-2", reference_tempo="original")
        assert ab.get("order") == ["your take", "reference"], ab
        await server.stop_playback()

    asyncio.run(run())


def test_notes_from_events_closes_hanging_notes():
    notes, pedal = notes_from_events([(0.0, [0x90, 60, 80]), (0.5, [0xB0, 64, 127]), (1.0, [0x90, 62, 0])])
    assert len(notes) == 1 and notes[0].end >= 0.05 and pedal == [(0.5, 127)]


def test_unrelated_take_is_rejected(ref):
    notes, _ = select_notes(ref, "both")
    take = [Note(30 + (k * 7) % 11, k * 0.3, k * 0.3 + 0.2, 60) for k in range(40)]
    assert "error" in analysis.compare(ref, notes, take, [], bars_given=False)


def test_wait_without_recording_returns_immediately(monkeypatch):
    from midi_coach import server

    monkeypatch.setattr(server, "recorder", midi_io.Recorder())

    started = time.perf_counter()
    out = asyncio.run(server.wait_for_recording(max_wait_sec=10))
    assert "error" in out and time.perf_counter() - started < 1


# ---------------------------------------------------------------------------
# Live modes + display server
# ---------------------------------------------------------------------------


class RecordingHub:
    """DisplayHub stand-in that records what would be sent to the page."""

    def __init__(self):
        self.events = []

    def marks(self, updates, reset=False):
        self.events.append(("marks", list(updates), reset))

    def cursor(self, beat, bps=0.0, live=False, until=None):
        self.events.append(("cursor", beat, bps, until))

    def session(self, active, mode=None):
        self.events.append(("session", active, mode))

    def flash(self, text):
        self.events.append(("flash", text))

    def status(self, text):
        self.events.append(("status", text))

    def heat(self, bars):
        self.events.append(("heat", bars))

    def metronome(self, grid):
        self.events.append(("metronome", grid))

    def statuses(self, kind):
        return [m for e in self.events if e[0] == "marks" for m in e[1] if m[2] == kind]


def _on(pitch):
    return [0x90, pitch, 80]


def test_live_wait_mode(ref):
    from midi_coach import live

    notes, _ = select_notes(ref, "right", bars=(1, 1))
    hub = RecordingHub()
    sess = live.LiveSession("wait", ref, notes, hub)
    sess.start()
    first_chord = [m for m in hub.statuses("pending")]
    assert [m[1] for m in first_chord] == [72]
    t = 0.0
    sess.on_message(t, _on(61))  # wrong key: flashes, cursor stays
    assert ("flash", "C#4") in hub.events and sess.wrong == 1
    for n in notes:
        t += 0.5
        sess.on_message(t, _on(n.pitch))
    assert sess.should_stop() == "finished the piece"
    assert sess.hits == len(notes) == len(hub.statuses("hit"))
    cursors = [e[3] if e[3] is not None else e[1] for e in hub.events if e[0] == "cursor"]
    assert cursors == sorted(cursors) and cursors[-1] == pytest.approx(3.5)  # last eighth of bar 1
    # After each chord the cursor flows on at the score's tempo instead of jumping ahead.
    glides = [e for e in hub.events if e[0] == "cursor" and e[3] is not None]
    assert len(glides) == len(notes) - 1
    assert all(g[3] - g[1] == pytest.approx(0.5) and g[2] == pytest.approx(ref.bpm_at(0) / 60) for g in glides)
    summary = sess.summary()
    assert summary["per_bar"]["1"]["wrong"] == 1
    assert summary["slips"] == [{"bar": 1, "played": 61, "expected": [72]}]
    heat = live.heat_from_live(ref, summary)
    assert heat[0]["bar"] == 1 and heat[0]["value"] > 0 and "1 wrong" in heat[0]["label"]
    assert heat[0]["start"] == 0 and heat[0]["end"] == 4


def test_live_rehearsal_mode(ref):
    from midi_coach import live

    notes, _ = select_notes(ref, "right", bars=(1, 1))
    hub = RecordingHub()
    sess = live.LiveSession("rehearsal", ref, notes, hub, tempo_percent=400)  # 8 eighths in 0.6 s
    sess.start()
    try:
        sess.on_message(time.perf_counter(), _on(30))  # before the start: ignored
        assert sess.wrong == 0
        t0 = time.perf_counter()
        sess.on_message(t0, _on(notes[0].pitch))  # starts the clock
        for n in notes[1:6]:  # play five more on time, skip the last two
            due = t0 + (n.start - notes[0].start) / 4
            while time.perf_counter() < due:
                time.sleep(0.002)
            sess.on_message(time.perf_counter(), _on(n.pitch))
        deadline = time.time() + 5
        while not sess.should_stop() and time.time() < deadline:
            time.sleep(0.02)
    finally:
        sess.stop()
    assert sess.should_stop() == "reached the end"
    assert sess.hits == 6 and sess.misses == 2
    assert len(hub.statuses("missed")) == 2
    assert any(e[0] == "cursor" and e[2] > 0 for e in hub.events)  # moving cursor with tempo


def test_display_server_streams_state(ref):
    import json
    import urllib.request

    from midi_coach import display

    hub = display.DisplayHub()
    url = hub.start()
    try:
        page = urllib.request.urlopen(url).read().decode()
        assert "notation.html" in page
        assert b"applyMarks" in urllib.request.urlopen(url + "notation.html").read()
        hub.load_score(ref)  # MIDI -> MusicXML via music21
        payload = json.loads(urllib.request.urlopen(url + "score").read())
        assert payload["xml"].lstrip().startswith("<?xml") and payload["version"] == 1
        hub.marks([(0.0, 72, "hit")])
        hub.status("hello")
        stream = urllib.request.urlopen(url + "events")
        assert stream.headers["Access-Control-Allow-Origin"] == "*"
        msgs = []
        while len(msgs) < 4:
            line = stream.readline().decode().strip()
            if line.startswith("data: "):
                msgs.append(json.loads(line[6:]))
        assert [m["type"] for m in msgs] == ["score", "session", "marks", "status"]
        hub.flash("F#4")
        while True:
            line = stream.readline().decode().strip()
            if line.startswith("data: "):
                assert json.loads(line[6:]) == {"type": "flash", "text": "F#4"}
                break
        stream.close()
    finally:
        hub.shutdown()


def test_say_speaks_on_connected_page(monkeypatch):
    import asyncio
    import json
    import urllib.request

    from midi_coach import display, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    try:
        assert asyncio.run(server.say("   "))["error"]
        alone = asyncio.run(server.say("Nobody hears this."))
        assert alone["spoken"] is False and "click the page" in alone["note"]
        stream = urllib.request.urlopen(server.hub.url + "events")
        deadline = time.time() + 5
        while server.hub.clients == 0 and time.time() < deadline:
            time.sleep(0.02)
        res = asyncio.run(server.say("Keep the  thumb\nunder in bar 3.", interrupt=True))
        assert res == {"spoken": True, "pages": 1}
        while True:
            line = stream.readline().decode().strip()
            if line.startswith("data: ") and json.loads(line[6:])["type"] == "say":
                assert json.loads(line[6:]) == {"type": "say", "text": "Keep the thumb under in bar 3.", "interrupt": True, "speaker": "Claude"}
                break
        stream.close()
        assert all(m["type"] != "say" for m in server.hub.snapshot())  # never replayed later
    finally:
        server.hub.shutdown()


def _wait_summary(wrong_bars=(), slips=(), stall=None):
    per_bar = {str(b): {"wrong": 0, "missed": 0, "hits": 4, "wait_sec": 2.0} for b in range(1, 5)}
    for b in wrong_bars:
        per_bar[str(b)]["wrong"] += 1
    if stall:
        per_bar[str(stall[0])]["wait_sec"] = stall[1]
    return {"mode": "wait", "hits": 16, "missed": 0, "wrong_presses": len(wrong_bars), "notes_total": 16,
            "per_bar": per_bar, "slips": list(slips)}


def test_remarks_name_the_mistake_and_vary():
    import random

    from midi_coach import remarks

    assert remarks._slip(65, [66])[:3] == ("accidental", "F sharp", "F")  # F for F sharp
    assert remarks._slip(71, [70]) == ("accidental", "B flat", "B")
    assert remarks._slip(66, [65]) == ("accidental", "F natural", "F sharp")
    assert remarks._slip(64, [72])[0] == "wrong"
    assert remarks._pitch("F#4") == 66 and remarks._pitch("Bb3") == 58

    coach = remarks.Coach(random.Random(1))
    slip = {"bar": 2, "played": 65, "expected": [66]}
    first = coach.remark(_wait_summary([2], [slip]))
    assert "F sharp" in first and "bar 2" in first.lower()
    again = coach.remark(_wait_summary([2], [slip]))  # second time: how to fix it
    assert "F sharp" in again and again != first
    third = coach.remark(_wait_summary([2], [slip]))  # nothing new: a word or two
    assert len(third.split()) <= 2
    frozen = coach.remark(_wait_summary(stall=(3, 12.0)))
    assert "bar 3" in frozen.lower() and not frozen.startswith("Clean")
    assert coach.history[-1]["grade"] != "clean"

    # Clean loop passes: quiet except the first and the streak at three and five.
    coach.reset()
    said = [coach.remark(_wait_summary(), {"scores": {"overall": 98}}) for _ in range(6)]
    assert [s is not None for s in said] == [True, False, True, False, True, False]
    assert "three" in said[2].lower() and "five" in said[4].lower()
    assert coach.remark(None) is None


def test_remarks_stay_short_and_fresh(tmp_path):
    import random
    import re

    from midi_coach import remarks

    # Every phrase is one sentence (a remark is two of them), every pool has room to vary.
    for pools in [remarks.COMMON, *remarks.VOICE.values()]:
        for name, pool in pools.items():
            assert len(pool) >= 8, name
            for line in pool:
                assert len(re.findall(r"[.!?](?=\s|$)", line)) == 1, line
    assert remarks.VOICE["warm"].keys() == remarks.VOICE["strict"].keys()

    # Warm by default; the style and the recent wording survive a restart.
    memory = tmp_path / "maestro.json"
    coach = remarks.Coach(random.Random(3), memory=lambda: memory)
    assert coach.style == "warm"
    rough = {"mode": "wait", "hits": 4, "missed": 0, "wrong_presses": 12, "notes_total": 16, "per_bar": {}, "slips": []}
    for _ in range(3):
        said = coach.remark(rough)
        assert len(re.findall(r"[.!?](?=\s|$)", said)) <= 2
    coach.style = "strict"
    later = remarks.Coach(random.Random(3), memory=lambda: memory)
    assert later.style == "strict" and later._recent == coach._recent
    said_before = list(coach._recent["warm:verdict-rough"])
    later.style = "warm"
    assert later._pick("verdict-rough") not in said_before
    try:
        later.style = "mean"
    except ValueError:
        pass
    else:
        raise AssertionError("unknown style accepted")


def test_maestro_greets_celebrates_and_signs_off():
    import random

    from midi_coach import remarks

    assert remarks.key_reminder(2) == ("two sharps", "F sharp and C sharp")
    assert remarks.key_reminder(-1) == ("one flat", "B flat")
    assert remarks.key_reminder(0) is None

    coach = remarks.Coach(random.Random(2))
    hello = coach.start({"title": "D major scale", "mode": "wait", "fifths": 2})
    assert "D major scale" in hello and "F sharp and C sharp" in hello  # new piece: always the key
    back = remarks.Coach(random.Random(2)).start({"title": "Etude", "mode": "rehearsal", "tempo_percent": 80, "best_before": 91, "takes_before": 4})
    assert "91" in back and "80" in back
    away = remarks.Coach(random.Random(2)).start({"title": "Etude", "mode": "wait", "best_before": 70, "days_away": 9})
    assert "nine days" in away.lower()

    coach.start({"title": "Etude", "mode": "wait", "best_before": 90})
    first = coach.remark(_wait_summary(), {"scores": {"overall": 95}})
    second = coach.remark(_wait_summary(), {"scores": {"overall": 97}})
    third = coach.remark(_wait_summary(), {"scores": {"overall": 96}})
    records = [s for s in (first, second, third) if s and ("record" in s.lower() or "best" in s.lower())]
    assert records == [first] and "95" in first  # announced once, on the first pass that beats it
    assert coach.wrap_up() and "three passes" in coach.wrap_up().lower()
    coach.start({"title": "Etude", "mode": "wait"})
    coach.remark(_wait_summary())
    assert coach.wrap_up() is None  # a single pass gets no sign-off


def test_maestro_style_is_a_setting(monkeypatch, tmp_path):
    import json

    from midi_coach import display, remarks, server

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_coach", remarks.Coach(memory=lambda: tmp_path / "maestro.json"))
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})
    assert server._cmd_maestro({}) == {"style": "warm", "styles": ["warm", "strict"]}
    assert server._voice.actions["set_style"](style="strict")["style"] == "strict"
    assert "Teaching style: strict." in server._voice_context()
    assert json.loads((tmp_path / "maestro.json").read_text())["style"] == "strict"


def test_coach_context_reads_key_title_and_history(ref, tmp_path, monkeypatch):
    import json
    import pathlib

    from midi_coach import lessons, server

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    path, score = lessons.build_lesson("G major warmup", "g4 a b c'", None, "4/4", "G", 80)
    ctx = server._coach_context(score, "both", "wait", 100)
    assert ctx["title"] == "G major warmup" and ctx["fifths"] == 1
    assert ctx["best_before"] is None and ctx["takes_before"] == 0
    meta = library.save_take([], {"reference": score.path, "hand": "right"})
    meta["comparisons"].append({"reference": score.path, "hand": "right", "when": "2020-01-01 10:00:00", "scores": {"overall": 88}})
    (pathlib.Path(meta["file"]).with_suffix(".json")).write_text(json.dumps(meta), encoding="utf-8")
    ctx = server._coach_context(score, "right", "wait", 100)
    assert ctx["best_before"] == 88 and ctx["takes_before"] == 1 and ctx["days_away"] > 300


def _fake_claude(replies, calls):
    from types import SimpleNamespace as NS

    def create(**kw):
        calls.append({**kw, "messages": list(kw["messages"])})
        return replies.pop(0)

    return NS(messages=NS(create=create), beta=NS(messages=NS(create=create)))


def test_voice_chat_runs_tools_and_meters_cost(monkeypatch, tmp_path):
    from types import SimpleNamespace as NS

    from midi_coach import chat

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    usage = NS(input_tokens=3000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    replies = [
        NS(stop_reason="tool_use", usage=usage, content=[
            NS(type="thinking", thinking="", signature="sig"),
            NS(type="tool_use", id="t1", name="start_practice", input={"mode": "learn", "bars": "5-8", "loop": True}),
        ]),
        NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text="Bars five to eight, on a loop. Go.")]),
    ]
    calls, started = [], []
    voice = chat.VoiceChat({"start_practice": lambda **kw: started.append(kw) or {"mode": "wait"}},
                           lambda: "Lesson on screen: Scale.", client=_fake_claude(replies, calls))
    out = voice.ask("loop bars five to eight")
    assert out["reply"] == "Bars five to eight, on a loop. Go." and out["actions"] == ["start_practice"]
    assert started == [{"mode": "learn", "bars": "5-8", "loop": True}]
    assert calls[0]["model"] == chat.CHAT_MODEL and "Lesson on screen: Scale." in calls[0]["messages"][0]["content"]
    assert calls[1]["messages"][1]["content"][0].type == "thinking"  # replayed unchanged
    assert calls[1]["messages"][-1]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": '{"mode": "wait"}'}
    expected = 2 * (3000 * 0.10 + 200 * 0.50) / 1e6
    assert out["cost"] == pytest.approx(expected) and voice.ledger.today() == pytest.approx(expected)

    replies.append(NS(stop_reason="refusal", usage=usage, content=[]))
    assert "piano" in voice.ask("something odd")["reply"] and voice.messages == []  # fresh start, nothing edited

    monkeypatch.setenv("MIDI_COACH_DAILY_CAP", "0.000001")
    capped = voice.ask("hello")
    assert capped["capped"] and len(calls) == 3  # no request once the day's budget is spent


def test_voice_chat_hands_lesson_writing_to_sonnet(monkeypatch, tmp_path):
    from types import SimpleNamespace as NS

    from midi_coach import chat

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    usage = NS(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    lesson = {"title": "G scale", "right": "g4 a b c'", "left": "", "time_signature": "4/4", "key": "G", "tempo_bpm": 70}
    replies = [
        NS(stop_reason="tool_use", usage=usage, content=[NS(type="tool_use", id="w1", name="write_lesson", input={"request": "G major scale"})]),
        NS(stop_reason="tool_use", usage=usage, content=[NS(type="tool_use", id="c1", name="create_lesson", input={**lesson, "right": "g4 x"})]),
        NS(stop_reason="tool_use", usage=usage, content=[NS(type="tool_use", id="c2", name="create_lesson", input=lesson)]),
        NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text="It's on your screen.")]),
    ]
    calls, made = [], []

    def create_lesson(**kw):
        made.append(kw)
        return {"error": "Unrecognized notes ['x']"} if "x" in kw["right"] else {"path": "g.musicxml", "bars": 1}

    voice = chat.VoiceChat({"create_lesson": create_lesson}, lambda: "", client=_fake_claude(replies, calls))
    out = voice.ask("write me a G major scale")
    assert out["reply"] == "It's on your screen." and len(made) == 2  # the composer fixed its own typo
    sonnet = [c for c in calls if c["model"] == chat.LESSON_MODEL]
    assert len(sonnet) == 2 and sonnet[0]["fallbacks"] == "default" and sonnet[0]["betas"] == ["server-side-fallback-2026-07-01"]
    assert sonnet[1]["messages"][-1]["content"][0]["is_error"] is True
    assert '"created": "g.musicxml"' in calls[-1]["messages"][-1]["content"][0]["content"]


def test_deep_question_runs_claude_code_on_the_subscription(monkeypatch, tmp_path):
    import json
    import subprocess
    from types import SimpleNamespace as NS

    from midi_coach import deep

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(deep, "find_claude", lambda: "claude.exe")
    deep.remember("Learning Clair de Lune")
    runs, spoken = [], []
    replies = [{"result": "Bar five is a stretch.", "session_id": "s1"},
               {"result": "Done.", "session_id": "s1"},
               {"is_error": True, "result": "usage limit reached"}]

    def run(args, **kw):
        runs.append({"args": args, **kw})
        teacher.spoken += 1 if len(runs) == 2 else 0  # the second answer uses the say tool
        return subprocess.CompletedProcess(args, 0, json.dumps({"type": "result", **replies.pop(0)}), "")

    teacher = deep.DeepTeacher(NS(start=lambda: "http://127.0.0.1:8780/mcp"), spoken.append, run=run)
    assert teacher.ask("teach me bars 5 to 8", "Lesson on screen: Clair de Lune.", wait=True)["handed_off"]
    args, first = runs[0]["args"], runs[0]
    assert args[args.index("--permission-mode") + 1] == "dontAsk" and "--strict-mcp-config" in args
    assert json.loads(args[args.index("--mcp-config") + 1])["mcpServers"]["midi-coach"]["url"] == "http://127.0.0.1:8780/mcp"
    assert "ANTHROPIC_API_KEY" not in first["env"] and "--resume" not in args  # billed to the subscription
    assert "Learning Clair de Lune" in first["input"] and "teach me bars 5 to 8" in first["input"]
    assert spoken == ["Bar five is a stretch."]  # answered in text, so the text is spoken

    teacher.ask("next section", "", wait=True)
    assert runs[1]["args"][-2:] == ["--resume", "s1"] and spoken == ["Bar five is a stretch."]  # it spoke with say

    teacher.session_id = None
    teacher.ask("make me a practice plan", "No lesson on screen.", wait=True)
    assert "inbox" in spoken[-1] and not teacher.busy
    [saved] = deep.take_inbox()
    assert saved["question"] == "make me a practice plan" and saved["why_not_answered"] == "usage limit reached"
    assert deep.take_inbox() == []

    monkeypatch.setattr(deep, "find_claude", lambda: None)  # not installed: straight to the inbox
    out = teacher.ask("why is this hard?", "ctx")
    assert out["saved_to_inbox"] and len(runs) == 3 and deep.take_inbox()[0]["question"] == "why is this hard?"


def test_voice_chat_tools_all_have_actions():
    from midi_coach import chat, server

    names = {t["name"] for t in chat.TOOLS} - {"write_lesson"}  # write_lesson runs inside chat.py
    assert names <= set(server._voice.actions)


def test_voice_route_and_context(monkeypatch, ref):
    import json
    import urllib.request

    from midi_coach import display, server

    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})
    assert "No lesson on screen." in server._voice_context()
    server._cmd_load({"lesson": "etude"})
    ctx = server._voice_context()
    assert "Lesson on screen:" in ctx and "no graded takes yet" in ctx

    server.hub.voice_handler = lambda audio: {"heard": f"{len(audio)} bytes"}
    try:
        req = urllib.request.Request(server.hub.url + "voice", data=b"\x1a\x45\xdf\xa3" * 100, method="POST")
        assert json.loads(urllib.request.urlopen(req).read()) == {"heard": "400 bytes"}
    finally:
        server.hub.shutdown()


def test_tts_routes(monkeypatch, tmp_path):
    import io
    import json
    import urllib.error
    import urllib.request
    import wave
    from urllib.parse import urlencode

    import numpy as np

    from midi_coach import display, tts

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    monkeypatch.setattr(tts, "_engine", None)
    # A background warm-up could outlive the test and load the real model, slowing timing-sensitive tests.
    monkeypatch.setattr(tts, "warm_up", lambda: None)
    tts._cache.clear()
    hub = display.DisplayHub()
    url = hub.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as err:  # no model: the page uses browser voices
            urllib.request.urlopen(url + "tts/voices")
        assert err.value.code == 404

        class FakeKokoro:
            calls = []

            def get_voices(self):
                return ["bm_george", "af_heart", "jf_alpha"]

            def create(self, text, voice, speed, lang):
                self.calls.append((text, voice, lang))
                return np.zeros(2400, dtype=np.float32), 24000

        monkeypatch.setattr(tts, "_engine", FakeKokoro())
        voices = json.loads(urllib.request.urlopen(url + "tts/voices").read())["voices"]
        assert [v["id"] for v in voices] == ["af_heart", "bm_george"]  # default first, English only
        assert voices[1]["label"] == "George (UK male)"
        res = urllib.request.urlopen(url + "tts?" + urlencode({"text": "Bar  3\nagain", "voice": "bm_george"}))
        assert res.headers["Content-Type"] == "audio/wav"
        with wave.open(io.BytesIO(res.read())) as w:
            assert w.getframerate() == 24000 and w.getnframes() == 2400
        assert ("Bar 3 again", "bm_george", "en-gb") in FakeKokoro.calls
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(url + "tts?text=")
        assert err.value.code == 400
    finally:
        hub.shutdown()
        tts._cache.clear()


def test_mcp_wait_mode_end_to_end(ref, fake_rtmidi, monkeypatch):
    from midi_coach import display, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())

    async def run():
        res = await server.start_recording(reference="etude", hand="right", bars="1-2", mode="wait")
        assert res.get("recording") and res["display"], res
        fin = FakeIn.instance
        for n in [n for n in ref.notes if n.part == 0 and n.start < ref.bars[2].start]:
            fin.send([0x90, n.pitch, 70])
            time.sleep(0.03)
            fin.send([0x80, n.pitch, 0])
        out = await server.wait_for_recording(max_wait_sec=5)
        assert out["stop_reason"] == "finished the piece", out
        comp = out["comparison"]
        assert comp["scores"]["method"].startswith("wait mode") and comp["live"]["hits"] == 16
        heat = server.hub._heat
        assert heat and {b["bar"] for b in heat} == {1, 2}
        shown = await server.show_heatmap()
        assert shown["bars_shown"] == 2

    try:
        asyncio.run(run())
    finally:
        server.hub.shutdown()


def _post(url, body=None):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())


def _until(cond, timeout=5.0):
    deadline = time.time() + timeout
    while not cond():
        assert time.time() < deadline, "timed out"
        time.sleep(0.02)


def test_page_menu_learn_loop(ref, fake_rtmidi, monkeypatch):
    from midi_coach import display, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    bar1 = [n for n in ref.notes if n.part == 0 and n.start < ref.bars[1].start]

    def play_pass():
        _until(lambda: server.recorder.active)
        for n in bar1:
            FakeIn.instance.send([0x90, n.pitch, 70])
            time.sleep(0.02)
            FakeIn.instance.send([0x80, n.pitch, 0])

    try:
        assert _post(url + "ports")["default"] == "JUNO-DS 0"
        assert "error" in _post(url + "start", {"mode": "learn"})  # no lesson picked yet
        assert _post(url + "load", {"lesson": "etude"})["bars"] == len(ref.bars)
        started = _post(url + "start", {"mode": "learn", "hand": "right", "bars": "1", "loop": True, "port": "JUNO-DS 0"})
        assert started["mode"] == "wait" and started["port"] == "JUNO-DS 0", started
        assert "error" in _post(url + "start", {"mode": "learn"})  # one session at a time
        play_pass()
        _until(lambda: server._practice["pass"] == 2 and server.recorder.active)
        assert server._practice["last"].startswith("Pass 1 · Learn: 8/8 notes, 0 wrong")
        play_pass()
        _until(lambda: server._practice["pass"] == 3)
        _post(url + "stop")
        _until(lambda: not server._practice["running"])
        time.sleep(1.7)  # no further pass after Stop
        assert not server.recorder.active
        takes = asyncio.run(server.list_takes(reference="etude"))["takes"]
        assert len(takes) == 2 and all(t["scores"] for t in takes)
        assert len(asyncio.run(server.progress("etude"))["sessions"]) == 2  # each pass graded once
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


def test_busy_keyboard_falls_back_to_coach_port(fake_rtmidi, monkeypatch):
    from midi_coach import server

    def open_port(self, idx):
        if "JUNO" in self.get_ports()[idx]:
            raise OSError("in use")
        self.port = idx

    monkeypatch.setattr(FakeIn, "get_ports", lambda self: ["JUNO-DS 0", "Coach 1"])
    monkeypatch.setattr(FakeIn, "open_port", open_port)
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    port, fell_back = server._start_input(None, 4.0, 60.0, 5.0, None)
    try:
        assert port == "Coach 1" and fell_back
    finally:
        server.recorder.stop()
    monkeypatch.setattr(FakeIn, "get_ports", lambda self: ["JUNO-DS 0"])
    with pytest.raises(midi_io.PortError, match="in use"):
        server._start_input(None, 4.0, 60.0, 5.0, None)  # no Coach port: the original error stands


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------


def test_build_lesson_two_hands(ref):
    from midi_coach import lessons

    path, score = lessons.build_lesson(
        "G warm-up", right="g4 a b c' d'2 r4 d'8 c' b1", left="chord{GG2 BB D} r2 GG1", key="G", tempo_bpm=120
    )
    assert path.endswith("g-warm-up.musicxml") and "<fifths>1</fifths>" in open(path).read()
    side = analysis.side_resolver(score)
    lines = lessons.describe(score, side)
    assert lines[0] == "1: RH G4@1 A4@2 B4@3 C5@4 | LH G2+B2+D3@1"
    assert lines[1] == "2: RH D5@1 D5@4 C5@4.5 | LH G2@1"  # rest on beat 3 respected
    events = lessons.learn_events(score, side)
    d5 = [e for e in events if e["note"] == 74]
    assert [e["ms"] for e in d5] == [2000.0, 3500.0]  # 120 bpm: bar 2 starts at 2 s
    assert {e["channel"] for e in events} == {0, 1}
    # Lessons live in the reference library.
    assert library.resolve_reference("g warm-up").name == "g-warm-up.musicxml"


def test_lesson_rejects_silently_dropped_tokens(ref):
    from midi_coach import lessons

    with pytest.raises(ValueError, match="G,"):
        lessons.build_lesson("bad", left="chord{G,2 B, D} r2")
    with pytest.raises(ValueError):
        lessons.build_lesson("bad key", right="c4 d e f", key="H")


def test_excerpt_lesson_one_hand(ref):
    from midi_coach import lessons

    path, score = lessons.excerpt_lesson(ref.path, (3, 4), "left", "etude LH 3-4")
    assert len(score.bars) == 2
    assert sorted({n.pitch for n in score.notes}) == [48, 52, 55]


def test_beats_follow_a_tempo_change_inside_a_bar(tmp_path):
    # 4/4 at 60 bpm, slowing to 30 bpm on beat 3 of bar 1 (a ritardando written beat by beat).
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    path = tmp_path / "rit.mid"
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=0))
    track.append(mido.Message("note_on", note=60, velocity=80, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    track.append(mido.Message("note_on", note=62, velocity=80, time=0))
    track.append(mido.Message("note_off", note=62, velocity=0, time=480))
    track.append(mido.MetaMessage("set_tempo", tempo=2_000_000, time=0))
    for i, n in enumerate((64, 65, 67, 69)):
        track.append(mido.Message("note_on", note=n, velocity=80, time=0))
        track.append(mido.Message("note_off", note=n, velocity=0, time=480))
    mid.save(path)
    score = load_score(path)
    # Beats 0,1 take a second each; beats 2,3 (still bar 1) and 4,5 take two seconds each.
    assert [round(n.start, 3) for n in score.notes] == [0.0, 1.0, 2.0, 4.0, 6.0, 8.0]
    assert [round(n.beat, 3) for n in score.notes] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert score.position(score.notes[3].start) == (1, 4.0)
    assert round(score.beat_of(1.5), 3) == 1.5 and round(score.beat_of(2.0), 3) == 2.0  # before / at the change


def test_musicxml_grace_notes_are_not_graded(tmp_path):
    from music21 import meter, note, stream
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    part = stream.Part([meter.TimeSignature("4/4")])
    part.append(note.Note("D5", quarterLength=0.5).getGrace())  # a flick into the B
    part.append([note.Note("B4", quarterLength=2), note.Note("D5", quarterLength=1), note.Rest(quarterLength=1)])
    path = tmp_path / "grace.musicxml"
    path.write_text(GeneralObjectExporter(stream.Score([part])).parse().decode("utf-8"), encoding="utf-8")
    score = load_score(path)
    # Only the real notes, with their written lengths (the grace D5 used to hang on until beat 3).
    assert [(n.pitch, round(n.beat, 3), round(score.beat_of(n.end) - n.beat, 3)) for n in score.notes] == [(71, 0.0, 2.0), (74, 2.0, 1.0)]


def test_musicxml_ties_follow_each_pitch_in_a_chord(tmp_path):
    from music21 import chord, meter, note, stream, tie
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    def piece(pitches, ties, ql):
        c = chord.Chord([note.Note(p) for p in pitches], quarterLength=ql)
        for n, t in zip(c.notes, ties):
            n.tie = tie.Tie(t) if t else None
        return c

    # A held top G4 (1.5 beats) over an E4 struck twice: the chord ties differ per pitch.
    part = stream.Part([meter.TimeSignature("2/4"), piece(["E4", "G4"], [None, "start"], 1),
                        piece(["E4", "G4"], [None, "stop"], 0.5), note.Rest(quarterLength=0.5)])
    path = tmp_path / "held.musicxml"
    path.write_text(GeneralObjectExporter(stream.Score([part])).parse().decode("utf-8"), encoding="utf-8")
    score = load_score(path)
    got = sorted((n.pitch, round(n.beat, 3), round(score.beat_of(n.end) - n.beat, 3)) for n in score.notes)
    assert got == [(64, 0.0, 1.0), (64, 1.0, 0.5), (67, 0.0, 1.5)]


def test_lesson_categories_and_moving_keeps_history(ref):
    import pathlib

    from midi_coach import lessons, server

    path, _ = lessons.build_lesson("Scale", right="c4 d e f g a b c'")
    assert pathlib.Path(path).parent.name == "AI exercises"  # a composed lesson is the AI's own
    cut, _ = lessons.excerpt_lesson(ref.path, (1, 2), "both", "etude bars 1-2")
    assert pathlib.Path(cut).parent.name == "Exercises"  # an excerpt of a real piece
    song, _ = lessons.build_lesson("Song", right="c4 d e f", category="vocals & ACCOMPANIMENT")
    assert pathlib.Path(song).parent.name == "Vocals & accompaniment"
    loose = lessons.lessons_dir() / "old.musicxml"
    loose.write_text(pathlib.Path(path).read_text(encoding="utf-8"), encoding="utf-8")

    # A take and a part choice on the lesson must follow it when it moves.
    score = library.get_score(path)
    library.save_hands(score, {0: "right"})
    take = library.save_take([(0.0, [0x90, 60, 80]), (0.5, [0x80, 60, 0])], {"reference": path})
    moved = lessons.move_lesson(path, "Solo piano", "C major scale")
    assert pathlib.Path(moved).name == "C major scale.musicxml" and not pathlib.Path(path).exists()
    assert library.get_take(take["id"])["reference"] == moved
    assert library.load_hands(library.get_score(moved)) == {0: "right"}
    with pytest.raises(FileExistsError):
        lessons.move_lesson(song, "Solo piano", "C major scale")

    menu = server._cmd_lessons({})
    assert menu["categories"] == ["Solo piano", "Vocals & accompaniment", "Exercises", "Unsorted"]
    assert {(x["title"], x["category"]) for x in menu["lessons"]} == {
        ("C major scale", "Solo piano"), ("song", "Vocals & accompaniment"), ("etude-bars-1-2", "Exercises"), ("old", "Unsorted")}
    assert json.loads(json.dumps(menu))  # the page gets it as JSON


def test_song_lesson_vocals_over_piano(ref, tmp_path):
    import pathlib

    from music21 import converter

    from midi_coach import lessons, songs

    # A band file: piano chords and a sung line with lyrics; C major, a 2/4 bar, then E major.
    mid = mido.MidiFile(ticks_per_beat=480)
    meta, piano, voice = mido.MidiTrack(), mido.MidiTrack(), mido.MidiTrack()
    mid.tracks += [meta, piano, voice]
    meta.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=2, denominator=4, time=480 * 8))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=480 * 2))
    piano.append(mido.MetaMessage("track_name", name="Piano", time=0))
    voice.append(mido.MetaMessage("track_name", name="Vocals", time=0))
    voice.append(mido.Message("program_change", program=53, channel=1, time=0))

    def beats():  # (beat, tonic): C for bars 1-2, the 2/4 bar 3, bars 4-10; E from bar 11 for 10 bars
        b = 0
        for _ in range(8 + 2 + 28):
            yield b, 0
            b += 1
        for _ in range(40):
            yield b, 4
            b += 1

    words = ["Hel", "lo", "there"]
    last_p = last_v = 0
    for k, (b, tonic) in enumerate(beats()):
        t = b * 480
        chord = [48 + tonic, 52 + tonic, 55 + tonic, 60 + tonic + (0, 4, 7, 11)[k % 4]]
        for i, p in enumerate(chord):
            piano.append(mido.Message("note_on", note=p, velocity=80, time=(t - last_p) if i == 0 else 0))
        for i, p in enumerate(chord):
            piano.append(mido.Message("note_off", note=p, velocity=0, time=440 if i == 0 else 0))
        last_p = t + 440
        sung = 60 + tonic + (0, 2, 4, 5, 7, 9, 11)[k % 7]
        voice.append(mido.MetaMessage("lyrics", text=(" " if k % 3 == 0 else "") + words[k % 3], time=t - last_v))
        voice.append(mido.Message("note_on", note=sung, velocity=80, channel=1, time=0))
        voice.append(mido.Message("note_off", note=sung, velocity=0, channel=1, time=400))
        last_v = t + 400
    path = pathlib.Path(os.environ["MIDI_COACH_REFERENCE_DIRS"]) / "Band - Hello [42].mid"
    mid.save(path)

    out = songs.song_lesson(str(path))
    assert out["title"] == "Band - Hello (with vocals)" and out["category"] == "Needs review"
    assert all(v["same as source"] for v in out["check"].values()), out["check"]
    assert out["key_changes"] == [(1, 0), (11, 4)]  # a modulation, not the 2/4 bar
    assert out["lyrics"].startswith("78 of 78")
    parsed = converter.parseData(pathlib.Path(out["path"]).read_text(encoding="utf-8"))
    vocal = parsed.parts[0]
    assert [n.lyric for n in vocal.recurse().notes][:4] == ["Hel", "lo", "there", "Hel"]
    assert [ts.ratioString for ts in vocal.recurse().getElementsByClass("TimeSignature")] == ["4/4", "2/4", "4/4"]
    listed = next(x for x in lessons.list_lessons() if x["path"] == out["path"])
    assert listed["category"] == "Needs review" and lessons.made_from(listed["source"]) == "from MIDI"
    assert "Band - Hello [42].mid" in listed["source"] and "Vocals" in listed["source"]


def test_create_lesson_tool_publishes(ref, monkeypatch):
    import json
    import urllib.request

    from midi_coach import display, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "hub", display.DisplayHub())

    async def run():
        page_only = await server.create_lesson("Scale", right="c4 d e f g a b c'")
        assert page_only["sent"]["lesson_version"] is None and server.hub.lesson_payload() is None
        assert server.hub.score_path == page_only["path"]  # on the coach page, ready for its menu
        out = await server.create_lesson("Scale", right="c4 d e f g a b c'", practice_mode="rehearsal", tempo_percent=70, to_visualizer=True)
        assert out["notes"] == {"right": 8, "left": 0} and out["bars"] == 2, out
        lesson = json.loads(urllib.request.urlopen(server.hub.url + "lesson").read())
        assert lesson["learn_mode"] == "freeplay" and lesson["speed"] == 0.7 and lesson["autostart"]
        assert len(lesson["events"]) == 8 and lesson["xml"].lstrip().startswith("<?xml")
        bad = await server.create_lesson("Bad", right="c4 x9")
        assert "error" in bad
        again = await server.send_lesson("etude", to_visualizer=True)  # a MIDI reference becomes a lesson too
        assert again["sent"]["lesson_version"] == 2
        lesson = json.loads(urllib.request.urlopen(server.hub.url + "lesson").read())
        assert lesson["xml"].lstrip().startswith("<?xml")

    try:
        asyncio.run(run())
    finally:
        server.hub.shutdown()


def test_readout_spells_black_keys_in_key(ref):
    from midi_coach import lessons

    _, score = lessons.build_lesson("E run", right="e16 f# g# a b c'# d'# e' f'# g'# a' b' c''# d''# e''8 "
                                    "d''#16 c''# b' a' g'# f'# e' d'# c'# b a g# f# e8.", key="E")
    lines = lessons.describe(score, analysis.side_resolver(score), lessons.key_spelling("E"))
    assert len(lines) == 2 and "D#6@4.25" in lines[0] and "G#4" in lines[1] and "Ab" not in "".join(lines)
    assert lessons.key_spelling("Bb") == "flats" and lessons.key_spelling("C") is None


# ---------------------------------------------------------------------------
# Cross-reference: chord charts, YouTube, harmony
# ---------------------------------------------------------------------------

UG_TAB = {
    "id": 42, "song_name": "Etude", "artist_name": "Test", "type": 300, "type_name": "Chords",
    "version": 2, "rating": 4.71234, "votes": 120, "tonality_name": "G", "capo": 2,
    "tuning": {"name": "Standard", "value": "E A D G B E"},
    "content": "[Intro]\r\n[ch]G[/ch]  [ch]D/F#[/ch]\r\n\r\n\r\n[Verse]\r\n[tab][ch]G[/ch]      [ch]Em[/ch]\r\nHello   world[/tab]\r\n[ch]Bb7[/ch]",
    "applicature": [
        {"chord": "G", "variations": [{"frets": [3, 2, 0, 0, 0, 3], "fingers": [2, 1, 0, 0, 0, 3], "fret": 1}]},
        {"chord": "G", "variations": []},
        {"chord": "Em", "frets": ["0", "2", "2", "0", "0", "x"], "fingers": [0, 2, 3, 0, 0, 0]},
    ],
}


def _fake_get(responses):
    calls = []

    def get(url, headers):
        calls.append((url, headers))
        for key, res in responses.items():
            if key in url:
                return res
        return 404, "application/json", "{}"

    return get, calls


def test_chord_sheet_markup():
    from midi_coach import web

    content = UG_TAB["content"]
    assert web.chart_chords(content) == ["G", "D/F#", "Em", "Bb7"]
    assert web.chart_chords(content, 2) == ["A", "E/G#", "F#m", "C7"]
    assert web.transpose_chord("Bb7", 1) == "B7" and web.transpose_chord("Eb", 1) == "E"
    assert web.chart_progression(content) == [
        {"section": "Intro", "chords": ["G", "D/F#"]},
        {"section": "Verse", "chords": ["G", "Em", "Bb7"]},
    ]
    text = web.chart_text(content)
    assert "G      Em\nHello   world" in text and "\n\n\n" not in text and "[ch]" not in text


def test_ug_client_parses_search_and_tab(monkeypatch):
    from midi_coach import web

    get, calls = _fake_get({
        "/tab/search": (200, "application/json; charset=utf-8", json.dumps({"tabs": [UG_TAB, {"song_name": "no id"}]})),
        "/tab/info": (200, "application/json", json.dumps(UG_TAB)),
    })
    monkeypatch.setattr(web, "_get", get)
    results = web.ug_search("etude", ["chords", "tabs"])
    assert [r["tab_id"] for r in results] == [42] and results[0]["rating"] == 4.71
    assert "type%5B%5D=300" in calls[0][0] and "type%5B%5D=200" in calls[0][0]
    assert len(calls[0][1]["X-UG-API-KEY"]) == 32
    tab = web.ug_tab(42)
    assert tab["capo"] == 2 and tab["tuning"] == "Standard" and tab["key"] == "G"
    assert [s["chord"] for s in tab["chord_shapes"]] == ["G", "Em"]
    assert tab["chord_shapes"][1]["frets"] == [0, 2, 2, 0, 0]

    monkeypatch.setattr(web, "_get", _fake_get({})[0])
    assert web.ug_search("nothing") == []  # UG answers 404 for no results
    monkeypatch.setattr(web, "_get", lambda url, headers: (429, "text/html", "slow down"))
    with pytest.raises(web.WebError, match="rate limited"):
        web.ug_search("etude")


def test_ug_api_key_matches_band_hq():
    import datetime
    import hashlib

    from midi_coach import web

    now = datetime.datetime(2024, 3, 5, 7, 30, tzinfo=datetime.timezone.utc)
    assert web.ug_api_key("abc", now) == hashlib.md5(b"abc2024-03-05:7createLog()").hexdigest()


def test_youtube_parse():
    from midi_coach import web

    html = (
        '"videoRenderer":{"videoId":"abcdefghijk","thumbnail":{},"title":{"runs":[{"text":"Clair de Lune \\u0026 more \\"live\\""}]}'
        '"videoRenderer":{"videoId":"abcdefghijk","title":{"runs":[{"text":"dup"}]}'
        '"videoRenderer":{"videoId":"ZYXWVUTSRQP","title":{"runs":[{"text":"Second"}]}'
    )
    videos = web.parse_youtube(html, 5)
    assert [v["title"] for v in videos] == ['Clair de Lune & more "live"', "Second"]
    assert videos[0]["url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert [v["video_id"] for v in web.parse_youtube('"videoId":"AAAAAAAAAAA" "videoId":"BBBBBBBBBBB"', 1)] == ["AAAAAAAAAAA"]


def test_name_chord_templates():
    from midi_coach import harmony

    def w(*pcs):
        out = [0.0] * 12
        for pc in pcs:
            out[pc] += 1
        return out

    assert harmony.name_chord(w(0, 4, 7), 0)[0] == "C"
    assert harmony.name_chord(w(9, 0, 4), 9)[0] == "Am"
    assert harmony.name_chord(w(7, 11, 2, 5), 7)[0] == "G7"
    assert harmony.name_chord(w(0, 4, 7), 4)[0] == "C/E"
    assert harmony.name_chord(w(2, 5, 9, 0), 2)[0] == "Dm7"
    assert harmony.name_chord([0.0] * 12, None) == (None, 0.0)


def test_chords_in_score_and_chart_comparison(ref, monkeypatch):
    from midi_coach import server, web

    async def run():
        harm = await server.chords_in_score("etude", hand="left")
        assert harm["key"] in ("C", "Am")
        by_bar = {c["bar"]: c["chord"] for c in harm["chords"]}
        assert by_bar[1] == "C" and by_bar[9] == "N.C." and harm["distinct"] == ["C"]
        assert len((await server.chords_in_score("etude", bars="1-2", per_bar=2))["chords"]) == 4

        monkeypatch.setattr(web, "_get", _fake_get({"/tab/info": (200, "application/json", json.dumps(UG_TAB))})[0])
        chart = await server.get_chord_chart(42, transpose=2, reference="etude", bars="1-8")
        assert chart["chords"][0] == "A" and chart["sounding_chords"][0] == "B"
        assert chart["progression"][0]["chords"] == ["A", "E/G#"]
        # Written G -> score's C is +5.
        assert chart["score_comparison"]["best_transpose"][0]["transpose"] == 5

        monkeypatch.setattr(web, "_get", lambda url, headers: (200, "text/html", '"videoRenderer":{"videoId":"abcdefghijk","title":{"runs":[{"text":"Etude"}]}'))
        yt = await server.search_youtube("etude piano")
        assert yt["videos"][0]["title"] == "Etude"
        res = await server.search_chord_charts("etude", types=["kazoo"])
        assert "Unknown tab type" in res["error"]

    asyncio.run(run())


def _write_band(path):
    """4 bars of a band arrangement: drums, bass, chord guitar and a sung melody."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))
    mid.tracks.append(meta)

    def track(name, channel, program, pitches_per_beat):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        if program is not None:
            tr.append(mido.Message("program_change", program=program, channel=channel))
        for beat in range(16):
            for pitch in pitches_per_beat(beat):
                tr.append(mido.Message("note_on", note=pitch, velocity=70, channel=channel, time=0))
            for k, pitch in enumerate(pitches_per_beat(beat)):
                tr.append(mido.Message("note_off", note=pitch, velocity=0, channel=channel, time=PPQ if k == 0 else 0))
        mid.tracks.append(tr)

    track("Drums", 9, None, lambda b: [36, 42])
    track("Track 2", 1, 33, lambda b: [40 + (b % 4)])  # fingered bass, unnamed
    track("Gtr", 2, 29, lambda b: [55, 59, 62])  # overdriven guitar chords
    track("Lead Vocal", 3, 53, lambda b: [67 + (b % 5)])  # voice oohs
    mid.save(str(path))
    return path


def test_instruments_and_drums_detected(ref, tmp_path):
    band = load_score(_write_band(tmp_path / "songs" / "Band Song.mid"))
    by_name = {p.name: p for p in band.parts}
    assert by_name["Drums"].drums and by_name["Drums"].instrument == "Drums"
    assert by_name["Track 2"].instrument == "Fingered Bass"
    assert by_name["Gtr"].instrument == "Overdriven Guitar"
    assert by_name["Lead Vocal"].instrument == "Voice Oohs"
    assert ref.parts[0].instrument == "Piano (no instrument set)" and ref.parts[0].is_piano
    everything, info = select_notes(band)
    assert not any(n.part == by_name["Drums"].index for n in everything)
    # Before anyone confirms, the suggestion (sung melody + bass) is what's played and graded.
    assert {n.part for n in everything} == {by_name["Lead Vocal"].index, by_name["Track 2"].index}
    assert info["method"].startswith("suggested parts")
    rh, _ = select_notes(band, "right")
    assert 36 not in {n.pitch for n in rh} and 42 not in {n.pitch for n in rh}


def test_suggest_hands_for_band_and_piano(ref, tmp_path):
    band = load_score(_write_band(tmp_path / "songs" / "Band Song.mid"))
    by_name = {p.name: p.index for p in band.parts}
    guess = suggest_hands(band)
    assert guess["right"] == [by_name["Lead Vocal"]] and guess["left"] == [by_name["Track 2"]], guess
    assert suggest_hands(ref)["right"] == [0] and suggest_hands(ref)["left"] == [1]


def test_part_choice_is_asked_saved_and_used(ref, tmp_path):
    from midi_coach import server

    _write_band(tmp_path / "songs" / "Band Song.mid")

    async def run():
        plain = await server.inspect_reference("etude")
        assert plain["ask_user"] is False

        info = await server.inspect_reference("band song")
        assert info["ask_user"] is True and not info["part_choice"]["confirmed"]
        parts = {p["name"]: p for p in info["parts"]}
        assert parts["Drums"]["hand"] == "not played (drums)"
        assert parts["Track 2"]["instrument"] == "Fingered Bass"
        vocal, bass, gtr = parts["Lead Vocal"]["index"], parts["Track 2"]["index"], parts["Gtr"]["index"]

        bad = await server.set_parts("band song", right=[vocal], left=[vocal])
        assert "error" in bad
        saved = await server.set_parts("band song", right=[vocal], left=[bass])
        assert "error" not in saved, saved
        assert any("Gtr" in name for name in saved["left_out"])

        library._score_cache.clear()  # the choice survives a reload
        again = await server.inspect_reference("band song")
        assert again["ask_user"] is False and again["part_choice"]["right"] == [vocal]
        assert {p["name"]: p["hand"] for p in again["parts"]}["Gtr"] == "not played"

        score = library.get_score("band song")
        right, info = select_notes(score, "right")
        assert {n.part for n in right} == {vocal} and "chosen" in info["method"]
        both, _ = select_notes(score)
        assert {n.part for n in both} == {vocal, bass}
        side = analysis.side_resolver(score)
        assert side(next(n for n in score.notes if n.part == bass)) == "left"
        only_gtr, _ = select_notes(score, "both", parts=[gtr])
        assert {n.part for n in only_gtr} == {gtr}

        await server.set_parts("band song", clear=True)
        assert library.get_score("band song").hands == {}

    asyncio.run(run())


def test_saved_choice_ignored_when_file_changes(ref, tmp_path):
    path = _write_band(tmp_path / "songs" / "Band Song.mid")
    score = library.get_score("band song")
    library.save_hands(score, {3: "right"})
    assert library.get_score("band song").hands == {3: "right"}
    _write_reference(path)  # same file name, different parts
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert library.get_score("band song").hands == {}


# ---------------------------------------------------------------------------
# Metronome that follows the score, and Record mode (transcription)
# ---------------------------------------------------------------------------


def test_metronome_grid_follows_score_at_tempo(ref):
    from midi_coach import live

    notes, _ = select_notes(ref, "both", bars=(3, 4))
    grid = live.metronome_grid(ref, notes, 0.5)  # half speed: every bar twice as long
    bar_sec = 4 * 60 / BPM / 0.5
    assert grid["count_in"] == pytest.approx(bar_sec)
    count_in, bar3, bar4 = grid["bars"]
    assert count_in == {"t": 0, "len": pytest.approx(bar_sec), "beats": 4, "accent": True}
    assert bar3["t"] == pytest.approx(bar_sec) and bar3["len"] == pytest.approx(bar_sec) and bar3["beats"] == 4
    assert bar4["t"] == pytest.approx(2 * bar_sec)
    fast = live.metronome_grid(ref, notes, 3.0)  # 0.8 s bars: two count-in bars
    assert fast["count_in"] == pytest.approx(2 * 4 * 60 / BPM / 3.0) and len(fast["bars"]) == 4


def test_rehearsal_count_in_starts_the_clock(ref):
    from midi_coach import live

    notes, _ = select_notes(ref, "right", bars=(1, 1))
    hub = RecordingHub()
    sess = live.LiveSession("rehearsal", ref, notes, hub, tempo_percent=400, count_in=True)  # 0.6 s bars
    sess.start()
    try:
        grid = [e[1] for e in hub.events if e[0] == "metronome"][0]
        assert len(grid["bars"]) == 3 and grid["start_in"] > 0  # two count-in bars + bar 1
        sess.on_message(time.perf_counter(), _on(notes[0].pitch))  # during the count-in: ignored
        assert sess.wrong == 0 and sess.hits == 0
        for n in notes:  # nothing else to start it: the count-in does
            due = sess._real(n)
            while time.perf_counter() < due:
                time.sleep(0.002)
            sess.on_message(time.perf_counter(), _on(n.pitch))
        _until(lambda: sess.should_stop())
    finally:
        sess.stop()
    assert sess.hits == len(notes) and sess.misses == 0 and sess.wrong == 0
    assert ("metronome", None) in hub.events  # the page stops clicking


def _played(bpm, downbeat, phrase, jitter=0.02, seed=3):
    """Notes for (beat, length in beats, pitch) played against a click at bpm."""
    rng = random.Random(seed)
    spb = 60 / bpm
    return [Note(p, downbeat + b * spb + rng.uniform(-jitter, jitter), downbeat + (b + d) * spb - 0.04, 80) for b, d, p in phrase]


def test_transcribe_quantizes_hands_triplets_and_key(tmp_path):
    from midi_coach import transcribe

    phrase = [(0, 1, 67), (1, 1, 69), (2, 1, 71), (3, 1, 66),  # G A B F#: G major
              (4, 1 / 3, 74), (4 + 1 / 3, 1 / 3, 72), (4 + 2 / 3, 1 / 3, 71), (5, 3, 67),  # triplet, then held G
              (0, 4, 43), (0, 4, 50), (4, 4, 47)]  # LH
    notes = _played(90, 5.0, phrase) + [Note(60, 3.9, 4.0, 40)]  # a stray note in the count-in
    out = transcribe.transcribe(notes, 90, 4, downbeat=5.0, title="Sketch")
    assert out["bars"] == 2 and out["key"] == "G" and out["dropped"] == 1
    path = tmp_path / "sketch.musicxml"
    path.write_text(out["xml"], encoding="utf-8")
    score = load_score(path)
    got = sorted((round(n.beat, 3), n.pitch) for n in score.notes)
    want = sorted((round(b, 3), p) for b, _, p in phrase)
    assert got == want
    assert "<time-modification>" in out["xml"] and "<fifths>1</fifths>" in out["xml"]
    assert {n.pitch for n in score.notes if n.part == 0} == {66, 67, 69, 71, 72, 74}  # right hand staff


def test_estimate_bpm_from_free_play():
    from midi_coach import transcribe

    phrase = [(k / 2, 0.5, 60 + k % 5) for k in range(24)]  # eighth notes
    est = transcribe.estimate_bpm(_played(84, 1.0, phrase, jitter=0.01))
    assert min(abs(est - 84), abs(est - 168), abs(est - 42)) <= 3


def test_page_record_mode_writes_sheet_music(ref, fake_rtmidi, monkeypatch):
    from midi_coach import display, server

    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    try:
        started = _post(url + "record", {"bpm": 240, "beats": 4, "port": "JUNO-DS 0"})
        assert started["mode"] == "record" and started["count_in_beats"] == 8, started  # 1 s bars: two count-in bars
        _until(lambda: server.recorder.active)
        downbeat = server._record_box["downbeat"]
        spb = 60 / 240
        phrase = [(0, 1, 72), (1, 1, 76), (2, 2, 79), (4, 4, 77)]
        for beat, length, pitch in phrase:
            while time.perf_counter() < downbeat + beat * spb:
                time.sleep(0.002)
            FakeIn.instance.send([0x90, pitch, 70])
            time.sleep(length * spb - 0.03)
            FakeIn.instance.send([0x80, pitch, 0])
        _post(url + "stop")
        _until(lambda: not server._practice["running"])
        assert server._practice["last"].startswith("Recorded 2 bars"), server._practice["last"]
        score = library.get_score(server.hub.score_path)
        assert [(round(n.beat, 2), n.pitch) for n in score.notes] == [(b, p) for b, _, p in phrase]
        take = library.get_take("latest")
        assert take["mode"] == "record" and take["bpm"] == 240
        assert abs(take["downbeat_sec"]) < 0.05  # the take file starts at the first note, played on the downbeat
        again = asyncio.run(server.transcribe_take(title="Again"))  # the saved grid gives the same result
        assert again["bars"] == 2 and not again["bpm_estimated"]
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


# ---------------------------------------------------------------------------
# Messy downloads: damaged files, live recordings, huge band files
# ---------------------------------------------------------------------------


def _write_live_take(path, notes=120, seed=5):
    """A performance recorded without a click: onsets land anywhere in the file's beats."""
    rng = random.Random(seed)
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tick, last = 0, 0
    events = []
    for _ in range(notes):
        tick += rng.randint(170, 330)  # uneven gaps, almost never on a 16th or triplet
        pitch = rng.choice([60, 62, 64, 65, 67, 69, 71, 72])
        events += [(tick, mido.Message("note_on", note=pitch, velocity=70)), (tick + 150, mido.Message("note_off", note=pitch))]
    for t, msg in sorted(events, key=lambda e: e[0]):
        tr.append(msg.copy(time=t - last))
        last = t
    mid.save(str(path))
    return path


def test_damaged_meta_events_dont_reject_the_file(ref, tmp_path):
    path = tmp_path / "songs" / "damaged.mid"
    mid = mido.MidiFile(str(_write_reference(tmp_path / "songs" / "plain.mid")))
    mid.tracks[0].insert(0, mido.MetaMessage("key_signature", key="F"))
    mid.save(str(path))
    data = bytearray(path.read_bytes())
    at = data.index(bytes([0xFF, 0x59, 0x02]))
    data[at + 4] = 0xFF  # mode 255: mido's strict decoder rejects the whole file
    path.write_bytes(bytes(data))
    score = load_score(path)
    assert len(score.notes) == len(ref.notes) and score.tempos[0][1] == pytest.approx(BPM)


def test_broken_folder_is_skipped(ref, tmp_path):
    folder = tmp_path / "songs" / library.BROKEN_DIR
    folder.mkdir()
    (folder / "Practice Etude in C copy.mid").write_bytes(b"MThd garbage")
    assert [h["name"] for h in library.find_references("practice etude")] == ["Practice Etude in C.mid"]


def test_live_recording_gets_no_sheet_and_no_count_in(ref, tmp_path):
    from midi_coach import display, live

    live_path = _write_live_take(tmp_path / "songs" / "Nocturne live.mid")
    played = load_score(live_path)
    assert played.played_live and played.grid_fit() < 0.5
    assert not ref.played_live and ref.grid_fit() == 1.0
    hub = display.DisplayHub()
    hub.load_score(played)
    payload = hub.score_payload()
    assert payload["xml"] is None and "recorded live" in payload["notice"] and payload["grid"] is False
    assert payload["tempo"] is None  # Match score / Follow score have nothing to go on
    hub.load_score(ref)
    payload = hub.score_payload()
    assert payload["xml"].lstrip().startswith("<?xml") and payload["notice"] is None
    assert payload["tempo"] == {"bpm": BPM, "beats": 4, "type": 4}
    info = asyncio.run(__import__("midi_coach.server", fromlist=["x"]).inspect_reference(str(live_path)))
    assert info["played_live"] and "bar numbers" in info["timing_note"]


def test_huge_file_gets_no_sheet(ref, monkeypatch):
    from midi_coach import display

    monkeypatch.setattr(display, "SHEET_MAX_NOTES", 100)
    hub = display.DisplayHub()
    monkeypatch.setattr(hub, "xml_for", lambda path: pytest.fail("a huge file must not be converted"))
    hub.load_score(ref)
    assert hub.score_payload()["xml"] is None and "too much to draw" in hub.score_payload()["notice"]
    assert hub.score_payload()["grid"] is True  # the metronome can still follow it


def _write_drifting_band(path, bars=24):
    """A band file sequenced on a grid at 117 BPM, speeding to 123 halfway, but saved with
    a flat 120 BPM tempo map - so its notes slide off the file's own bar lines.
    Piano (both hands), bass, and drums; bar 9 has a 32nd-note fill."""
    ticks_per_sec = PPQ * 2  # 120 BPM in the file

    def sec(beat):
        half = bars * 2
        return beat * 60 / 117 if beat <= half else half * 60 / 117 + (beat - half) * 60 / 123

    events = []

    def note(beat, length, pitch, channel, program=None):
        on, off = round(sec(beat) * ticks_per_sec), round(sec(beat + length) * ticks_per_sec) - 5
        events.append((on, mido.Message("note_on", note=pitch, velocity=70, channel=channel)))
        events.append((off, mido.Message("note_off", note=pitch, channel=channel)))

    chords = [(55, 58, 62), (53, 57, 60), (51, 55, 58), (50, 54, 57)]  # Gm, F, Eb, D
    for bar in range(bars):
        b0 = bar * 4
        for k in range(8):  # piano: right-hand eighths over a left-hand chord
            note(b0 + k / 2, 0.5, 67 + (k * 3 + bar) % 8, 0)
        for p in chords[bar % 4]:
            note(b0, 4, p - 12, 0)
        note(b0, 1.5, 43 - (bar % 4), 1)  # bass
        note(b0 + 2, 2, 43 - (bar % 4), 1)
        for k in range(4):
            note(b0 + k, 0.25, 36 if k % 2 == 0 else 38, 9)
        if bar == 8:
            for k in range(8):  # a fill faster than the grid the tracker uses
                note(b0 + 3 + k / 8, 0.1, 45, 9)
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    mid.tracks.append(meta)
    for channel, name, program in ((0, "Piano", 0), (1, "Bass", 33), (9, "Drums", None)):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        if program is not None:
            tr.append(mido.Message("program_change", program=program, channel=channel))
        last = 0
        for t, msg in sorted((e for e in events if e[1].channel == channel), key=lambda e: (e[0], e[1].type == "note_on")):
            tr.append(msg.copy(time=t - last))
            last = t
        mid.tracks.append(tr)
    mid.save(str(path))
    return path


def test_regrid_recovers_a_drifting_tempo_map(ref, tmp_path):
    path = _write_drifting_band(tmp_path / "songs" / "Drifting Song.mid")
    raw = load_score(path)
    assert raw.played_live  # off the file's own grid
    score = library.get_score("drifting song")
    assert not score.played_live and score.regrid["median_ms"] < 5
    piano = sorted((n for n in score.notes if n.part == 0 and n.pitch >= 60), key=lambda n: n.start)
    assert [n.beat for n in piano[:8]] == [k / 2 for k in range(8)]  # bar 1, exactly on the eighths
    assert piano[-1].beat == pytest.approx(24 * 4 - 0.5)  # still on the grid after the tempo change
    assert len(score.bars) == 24 and score.bars[12].start == pytest.approx(48 * 60 / 117, abs=0.02)
    assert score.tempos[0][1] == pytest.approx(117, abs=0.5) and score.tempos[-1][1] == pytest.approx(123, abs=0.5)
    cached = list((library.home() / "derived").glob("Drifting-Song-*.beatmap.json"))
    assert len(cached) == 1
    library._score_cache.clear()
    assert library.get_score("drifting song").regrid == score.regrid  # from the cache
    assert library.get_score(str(_write_live_take(tmp_path / "songs" / "Free.mid"))).played_live  # rubato doesn't lock


def test_piano_sheet_of_a_band_file(ref, tmp_path):
    from midi_coach import display, server, sheet

    path = _write_drifting_band(tmp_path / "songs" / "Drifting Song.mid")
    score = library.get_score("drifting song")
    assert sheet.wanted(score) and not sheet.wanted(ref)
    out = sheet.build(score)
    xml = out["xml"]
    assert xml.count("<score-part ") == 2 and out["key"] in ("Gm", "Bb")
    assert "<per-minute>117</per-minute>" in xml and "<per-minute>123</per-minute>" in xml
    drawn = load_score(tmp_path / "sheet.musicxml") if (tmp_path / "sheet.musicxml").write_text(xml, encoding="utf-8") else None
    graded, _ = select_notes(score)
    assert {n.part for n in graded} == {0}  # the suggestion: the piano part, no bass or drums
    assert {(n.beat, n.pitch) for n in graded} <= {(n.beat, n.pitch) for n in drawn.notes}  # marks find their notes
    assert len(drawn.notes) == len(graded)

    hub = display.DisplayHub()
    hub.load_score(score)
    first = hub.score_payload()
    assert first["xml"] == sheet.piano_xml(score)  # the cached piano sheet, not the whole file
    assert first["grid"] and first["tempo"]["bpm"] == pytest.approx(117, abs=0.5)
    library.save_hands(score, {0: "right", 1: "left"})  # play the bass line with the left hand
    hub.load_score(library.get_score("drifting song"))
    second = hub.score_payload()
    assert second["version"] == first["version"] + 1 and second["xml"] != first["xml"]  # redrawn for the new parts


def test_split_hands_follows_the_hands_not_middle_c():
    from midi_coach.notes import split_hands

    notes = []
    for bar in range(2):  # a held B2 under an arpeggio that dips below middle C
        t = bar * 4.0
        notes.append(Note(47, t, t + 4, 60))
        notes += [Note(62, t, t + 1, 60), Note(66, t, t + 1, 60), Note(59, t + 1, t + 2, 60),
                  Note(62, t + 2, t + 3, 60), Note(66, t + 2, t + 3, 60), Note(60, t + 3, t + 4, 60)]
    notes += [Note(p, 8.0, 10.0, 60) for p in (46, 58, 65, 70)]  # B flat octave under F + B flat
    sides = split_hands(notes)
    assert sides[(0.0, 47)] == "left" and sides[(4.0, 47)] == "left"
    assert sides[(1.0, 59)] == "right" and sides[(3.0, 60)] == "right"  # the arpeggio stays in one hand
    assert sides[(8.0, 58)] == "left" and sides[(8.0, 65)] == "right"  # the octave stays together


def test_split_by_reach_revises_a_chord_later_notes_explain():
    """A held chord around middle C, then stabs high above it while it rings: the chord was
    the left hand's all along. Deciding chord by chord gave the first chord to the right hand,
    then the stabs to the left, and kept the hands crossed for the rest of the piece."""
    from midi_coach.notes import split_by_reach

    notes = []
    for bar in range(4):
        t = bar * 2.5
        notes += [Note(p, t, t + 2.45, 70) for p in (55, 60, 63)]
        if bar:
            notes += [Note(p, t + s, t + s + 0.08, 90) for s in (0.3, 0.9, 1.5) for p in (79, 84, 87)]
    sides = split_by_reach(notes)
    assert all(sides[(round(n.start, 4), n.pitch)] == ("right" if n.pitch > 70 else "left") for n in notes)


def _installed_hand_model():
    from midi_coach import hand_model

    path = pathlib.Path(os.environ.get("MIDI_COACH_HOME") or pathlib.Path.home() / "MidiCoach") / "models" / hand_model.MODEL_FILE
    return path if path.exists() else None


INSTALLED_HAND_MODEL = _installed_hand_model()  # looked up before the tests move MIDI_COACH_HOME


@pytest.mark.skipif(INSTALLED_HAND_MODEL is None, reason="hand model not installed (tools/export_pm2s_hand.py)")
def test_hand_model_puts_a_high_tune_right_and_a_low_bass_left(monkeypatch):
    """The model's output is the chance of the LEFT hand, though PM2S documents it as the
    right: read the wrong way round, every note lands in the other hand. A tune up high over
    a bass line down low must come out the obvious way."""
    from midi_coach import hand_model
    from midi_coach.notes import split_hands

    monkeypatch.setenv("MIDI_COACH_HAND_MODEL", str(INSTALLED_HAND_MODEL))
    tune = [Note(72 + (0, 2, 4, 5, 7, 5, 4, 2)[i % 8], i * 0.3, i * 0.3 + 0.28, 85) for i in range(64)]
    bass = [Note(p, i * 1.2, i * 1.2 + 1.1, 65) for i, p in enumerate([36, 43, 41, 43] * 4)]
    sides = split_hands(tune + bass)
    assert hand_model.splitter() == "pm2s"
    assert all(sides[(round(n.start, 4), n.pitch)] == "right" for n in tune)
    assert all(sides[(round(n.start, 4), n.pitch)] == "left" for n in bass)


def test_split_hands_overrules_a_model_with_the_hands_the_wrong_way_round(monkeypatch):
    """Where the model puts its right hand below its left, it isn't listened to."""
    from midi_coach import hand_model
    from midi_coach.notes import split_hands

    tune = [Note(76 + i % 3, i * 0.5, i * 0.5 + 0.4, 80) for i in range(40)]
    bass = [Note(40 + i % 3, i * 2.0, i * 2.0 + 1.9, 70) for i in range(10)]
    monkeypatch.setattr(hand_model, "left_odds", lambda notes: {(round(n.start, 4), n.pitch): 0.99 if n.pitch > 60 else 0.01 for n in notes})
    sides = split_hands(tune + bass)
    assert all(sides[(round(n.start, 4), n.pitch)] == "right" for n in tune)
    assert all(sides[(round(n.start, 4), n.pitch)] == "left" for n in bass)


def test_split_hands_without_the_model_uses_split_by_reach(monkeypatch, tmp_path):
    from midi_coach import hand_model
    from midi_coach.notes import split_by_reach, split_hands

    notes = [Note(48 + i % 3, i * 0.5, i * 0.5 + 0.4, 70) for i in range(8)] + [Note(76, i * 0.5, i * 0.5 + 0.4, 70) for i in range(8)]
    monkeypatch.setenv("MIDI_COACH_HAND_MODEL", str(tmp_path / "missing.onnx"))
    assert hand_model.predict(notes) is None and hand_model.splitter() == "reach"
    assert split_hands(notes) == split_by_reach(notes)


def test_one_track_piano_file_gets_a_grand_staff(ref, tmp_path):
    from midi_coach import display, sheet

    mid = mido.MidiFile(ticks_per_beat=PPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    events = []
    for bar in range(4):  # both hands in one track: a C3 bass and a C major arpeggio above
        b = bar * 4 * PPQ
        events += [(b, 48, 4 * PPQ)] + [(b + k * PPQ, p, PPQ) for k, p in enumerate((64, 67, 72, 67))]
    msgs = sorted([(t, mido.Message("note_on", note=p, velocity=60)) for t, p, _ in events]
                  + [(t + d, mido.Message("note_off", note=p, velocity=0)) for t, p, d in events], key=lambda e: (e[0], e[1].type == "note_on"))
    last = 0
    for t, msg in msgs:
        tr.append(msg.copy(time=t - last))
        last = t
    mid.save(str(tmp_path / "songs" / "One Track.mid"))
    score = library.get_score("one track")
    assert sheet.wanted(score) and not sheet.wanted(ref)  # two tracks named for the hands: converted as is
    hub = display.DisplayHub()
    hub.load_score(score)
    xml = hub.score_payload()["xml"]
    assert xml.count("<score-part ") == 2 and "<sign>F</sign>" in xml


def _band(parts):
    """A Score from [(program, name, [(start sec, pitch, length sec)...])], 4/4 at 120."""
    from midi_coach.notes import Bar, Part, Score

    notes, out_parts = [], []
    for i, (program, name, spec) in enumerate(parts):
        ns = [Note(p, t, t + d, 70, part=i, beat=t * 2) for t, p, d in spec]
        notes += ns
        pitches = [n.pitch for n in ns]
        out_parts.append(Part(i, i + 1, 9 if program == "drums" else i, name, len(ns), min(pitches), max(pitches),
                              sum(pitches) / len(pitches), None if program == "drums" else program, program == "drums"))
    end = max(n.end for n in notes)
    bars = [Bar(k + 1, 2.0 * k, 2.0 * (k + 1), 4, 4, 4.0 * k, 4.0 * (k + 1)) for k in range(int(end // 2) + 1)]
    return Score("band.mid", sorted(notes, key=lambda n: (n.start, n.pitch)), out_parts, [], bars, [(0.0, 120.0)], end)


def test_keyboard_part_suggestions():
    eighths = [k * 0.25 for k in range(64)]  # 8 bars of eighths
    # A piano part, an electric piano that only doubles it, and an organ an octave above the piano.
    piano = [(t, (60, 64, 67, 48)[k % 4], 0.25) for k, t in enumerate(eighths)]
    score = _band([(0, "Piano", piano), (4, "E.Piano", piano[:20]), (18, "Organ", [(t, p + 12, d) for t, p, d in piano])])
    out = suggest_hands(score)
    assert out["both"] == [0] and not out["right"] and not out["left"]
    assert any("only doubles part 0" in r for r in out["reasons"]) and sum("only doubles" in r for r in out["reasons"]) == 2

    # An organ riff in the treble only, plus a bass guitar: the bass line fills the left hand.
    organ = [(t, (72, 76, 79)[k % 3], 0.25) for k, t in enumerate(eighths)]
    bass = [(t, 36, 0.5) for t in eighths[::2]]
    band = _band([(18, "Organ", organ), (33, "Bass", bass), (6, "Harpsichord", organ[:10])])
    out = suggest_hands(band)
    assert out["right"] == [0] and out["left"] == [1]
    left, info = select_notes(band, "left")  # the bass guitar is played an octave up, as bass parts are written
    assert {n.pitch for n in left} == {48} and info["octave_up"] == [1] and any("octave up" in r for r in out["reasons"])

    # Two piano tracks that are one player's hands; and a full piano part with a boogie bass track.
    rh = [(t, (72, 76)[k % 2], 0.25) for k, t in enumerate(eighths)]
    lh = [(t, (48, 55)[k % 2], 0.5) for k, t in enumerate(eighths[::2])]
    out = suggest_hands(_band([(0, "Track 2", rh), (0, "Track 3", lh), (25, "Guitar", rh)]))
    assert out["right"] == [0] and out["left"] == [1]
    full = [(t, p, 0.25) for t in eighths for p in ((43, 72, 76) if t % 1 == 0 else (72,))]
    out = suggest_hands(_band([(0, "Piano", full), (0, "Piano", lh), (25, "Guitar", rh)]))
    assert out["both"] == [0] and out["left"] == [1]  # the full part needs both hands: not a hand of a pair


def test_grand_staff_clefs_keys_and_short_notes():
    from fractions import Fraction as F

    from music21 import converter

    from midi_coach.transcribe import grand_staff

    # D flat major: written with 5 flats, not C sharp major's 7 sharps.
    events = [("right", F(b * 4 + k), F(b * 4 + k + 1), p) for b in range(4) for k, p in enumerate((61, 65, 68, 73))]
    events += [("left", F(b * 4), F(b * 4 + 4), 49) for b in range(4)]
    out = grand_staff(events, "t")
    assert out["key"] == "Db" and "<fifths>-5</fifths>" in out["xml"]
    # A right hand that drops low for two bars changes to bass clef and back.
    events = [("right", F(b * 4 + k), F(b * 4 + k + 1), 48 if b in (1, 2) else 72) for b in range(4) for k in range(4)]
    events += [("left", F(b * 4), F(b * 4 + 4), 36) for b in range(4)]
    right = converter.parseData(grand_staff(events, "t")["xml"]).parts[0]
    assert [(float(c.getOffsetInHierarchy(right)), c.sign) for c in right.recurse().getElementsByClass("Clef")] == [(0.0, "G"), (4.0, "F"), (12.0, "G")]
    # A short note on an eighth before a gap is written as an eighth, not a 16th and a rest.
    events = [("right", F(k, 2), F(k, 2) + F(1, 4), 72) for k in range(0, 8, 2)] + [("left", F(0), F(4), 48)]
    notes = converter.parseData(grand_staff(events, "t")["xml"]).parts[0].recurse().notes
    assert [n.quarterLength for n in notes] == [0.5] * 4


def test_grand_staff_key_signature_follows_modulations():
    from fractions import Fraction as F

    from music21 import converter

    from midi_coach.transcribe import grand_staff

    def scale_bars(first_bar, count, tonic, borrow=None):
        out = []
        for bar in range(first_bar, first_bar + count):
            for k, d in enumerate((0, 2, 4, 5, 7, 9, 11, 12)):
                at = F(bar * 4) + F(k, 2)
                out.append(("right", at, at + F(1, 2), 60 + tonic + d))
            out.append(("left", F(bar * 4), F(bar * 4 + 4), 48 + tonic))
        if borrow is not None:  # one bar's chord borrowed from elsewhere: accidentals, not a new key
            out.append(("left", F(borrow * 4), F(borrow * 4 + 4), 51))
        return out

    # C major (with a two-bar trip to E flat and one borrowed E flat), then E major to the end.
    events = scale_bars(0, 6, 0, borrow=2) + scale_bars(6, 2, 3) + scale_bars(8, 4, 0) + scale_bars(12, 10, 4)
    out = grand_staff(events, "t")
    assert out["keys"] == [(1, 0), (13, 4)]
    right = converter.parseData(out["xml"]).parts[0]
    sigs = [(ks.getContextByClass("Measure").number, ks.sharps) for ks in right.recurse().getElementsByClass("KeySignature")]
    assert sigs == [(1, 0), (13, 4)]
    assert all(p.name != "A-" for n in right.measure(15).recurse().notes for p in n.pitches)  # G sharp in E major

    # Time signature changes: a 2/4 bar between 4/4 bars.
    ts = [(F(0), "4/4"), (F(4), "2/4"), (F(6), "4/4")]
    out = grand_staff([("right", F(k), F(k + 1), 60) for k in range(10)], "t", ts)
    bars = converter.parseData(out["xml"]).parts[0].getElementsByClass("Measure")
    assert [m.barDuration.quarterLength for m in bars] == [4, 2, 4]


def test_engraving_rules_catch_known_mistakes():
    from music21 import key, meter, note, stream

    from midi_coach import engraving

    def bar(*items):
        m = stream.Measure()
        for x in items:
            m.append(x)
        return m

    eb = note.Note("E-4", quarterLength=1)
    eb.pitch.accidental.displayStatus = True  # a flat the key signature already gives
    a3 = note.Note("A3", quarterLength=1)  # A natural in E flat with no sign: reads as A flat
    first = bar(eb, note.Note("G4", quarterLength=1), a3, note.Rest(quarterLength=1))
    first.insert(0, key.KeySignature(-3))
    first.insert(0, meter.TimeSignature("4/4"))
    part = stream.Part([first, bar(note.Note("C5", quarterLength=3.5), note.Note("D5", quarterLength=0.125), note.Rest(quarterLength=0.375))])
    part.partName = "Piano"
    found = engraving.lint(stream.Score([part]))["counts"]
    assert found["needless-accidental"] == 1 and found["missing-accidental"] == 1
    assert found["double-dot"] == 1 and found["too-short"] == 1


def test_grand_staff_is_readable_without_losing_notes(tmp_path):
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    # E flat major: E flats and B flats (no signs), A naturals in two octaves (both need one),
    # a long rest starting off the beat across a barline, a run of very low bass notes, and a
    # low sung line on a treble-8vb staff.
    events = []
    for b in range(8):
        for k, p in enumerate((63, 67, 70, 75)):
            events.append(("right", F(b * 4 + k), F(b * 4 + k + 1), p))
        if b == 2:
            events += [("left", F(8), F(9), 45), ("left", F(9), F(10), 57)]  # A2 then A3
        elif b in (4, 5):
            events += [("left", F(b * 4 + k), F(b * 4 + k + 1), 29) for k in range(4)]  # F1, four to a bar
        else:
            events.append(("left", F(b * 4), F(b * 4 + 4), 39))
    tune = [(F(0), F(1), 58, ("Hey", "single")), (F(1), F(1, 2) + 1, 55, None), (F(13, 2), F(7), 51, None), (F(12), F(14), 58, None)]
    out = grand_staff(events, "t", melody=tune)
    report = engraving.lint(out["xml"])
    assert not report["findings"], report["findings"][:5]
    assert "<octave-shift" in out["xml"]  # the low F1 passage is under 8vb...
    path = tmp_path / "t.musicxml"
    path.write_text(out["xml"], encoding="utf-8")
    score = load_score(path)  # ...but still graded as F1
    assert {(round(n.beat, 3), n.pitch) for n in score.notes if n.part == 2} == {(float(on), p) for h, on, _, p in events if h == "left"}
    assert {(round(n.beat, 3), n.pitch) for n in score.notes if n.part == 0} == {(float(on), p) for on, _, p, _ in tune}


def test_grand_staff_voices_spelling_and_lengths():
    from fractions import Fraction as F

    from music21 import converter

    from midi_coach import sheet
    from midi_coach.transcribe import grand_staff

    events = []
    for bar in range(8):
        b = F(bar * 4)
        if bar < 2:  # B minor, in a piece that is otherwise in G minor
            right = [(0, (62, 66)), (1, (59,)), (2, (62, 66)), (3, (59,))]
        else:
            right = [(0, (62, 67, 70)), (2, (63, 67, 70))]
        for at, pitches in right:
            events += [("right", b + at, b + at + 1, p) for p in pitches]
    events.append(("left", F(0), F(4), 43))  # G2 held under G3 on beats 2 and 4
    events += [("left", F(k), F(k + 1), 55) for k in (1, 3)]
    events += [("left", F(bar * 4), F(bar * 4 + 2), 43) for bar in range(2, 8)]
    out = grand_staff(events, "t")
    assert out["key"] in ("Gm", "Bb")
    parsed = converter.parseData(out["xml"])
    right, left = parsed.parts
    assert {p.name for n in right.measure(1).recurse().notes for p in n.pitches} == {"D", "F#", "B"}  # not G flat
    bar1 = left.measure(1)
    assert len(bar1.voices) == 2
    assert [(n.nameWithOctave, n.quarterLength) for n in bar1.recurse().notes if n.nameWithOctave == "G2"] == [("G2", 4.0)]
    assert not left.measure(3).voices  # nothing held there: one voice
    # Releases a little early or late are written as plain values, not tied 16ths.
    assert sheet._end(2.19, F(1)) == 2 and sheet._end(1.81, F(0)) == 2 and sheet._end(0.73, F(0)) == F(3, 4)
