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


def test_bar_transport_starts_with_notes_in_the_requested_bar(ref):
    from midi_coach import server

    all_notes, _ = select_notes(ref, "right")
    start_bar = ref.bar(6)
    remaining = server._from_bar(ref, all_notes, start_bar.number)

    assert remaining
    assert min(note.start for note in remaining) >= start_bar.start - 1e-6
    assert min(note.beat for note in remaining) >= start_bar.start_beat


def test_transport_restart_waits_for_stop_and_preserves_loop_range(monkeypatch):
    from midi_coach import server

    events = []
    class FakeRecorder:
        def stop(self, reason):
            events.append(("stop", reason))

        def wait(self, timeout):
            events.append(("wait", timeout))
            return True

    settings = {"reference": "piece.mid", "bars": "2-8", "mode": "wait", "loop": True, "start_bar": 5}
    monkeypatch.setattr(server, "recorder", FakeRecorder())
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": settings, "pass": 2, "stopping": False})
    monkeypatch.setattr(server, "_live", {"session": None, "watcher": None})
    monkeypatch.setattr(server, "_begin_pass", lambda got, pass_no: events.append(("begin", got, pass_no)) or {"mode": "wait"})

    server._restart_at_bar(settings, 2)

    assert events[0] == ("stop", "transport seek")
    assert events[1] == ("wait", 5)
    assert events[2] == ("begin", settings, 2)
    assert settings["bars"] == "2-8" and settings["start_bar"] == 5 and settings["loop"]


def test_next_loop_pass_returns_to_the_selected_range(monkeypatch):
    from midi_coach import server

    settings = {"reference": "piece.mid", "bars": "2-8", "mode": "wait", "loop": True, "start_bar": 5}
    started = []
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": settings, "pass": 3, "stopping": False})
    monkeypatch.setattr(server, "_busy", lambda: False)
    monkeypatch.setattr(server, "_begin_pass", lambda got, pass_no: started.append((got, pass_no)) or {})

    server._next_pass()

    assert settings["start_bar"] is None
    assert settings["bars"] == "2-8" and settings["loop"]
    assert started == [(settings, 4)]


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


def test_recorder_reports_held_keys(fake_rtmidi):
    rec = midi_io.Recorder()
    seen = []
    rec.on_keys = lambda held: seen.append(sorted(held))
    rec.start(None, silence_sec=5, max_sec=30, lead_in_sec=5)
    FakeIn.instance.send([0x90, 60, 70])
    FakeIn.instance.send([0x90, 64, 70])
    FakeIn.instance.send([0xB0, 64, 127])  # the pedal lights no key
    FakeIn.instance.send([0x80, 60, 0])
    FakeIn.instance.send([0x90, 64, 0])  # note-on at velocity 0 lets go too
    rec.stop()
    assert seen == [[60], [60, 64], [64], [], []]  # and nothing is left lit when it ends


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

    def flash(self, text, hint=None):
        self.events.append(("flash", text) if hint is None else ("flash", text, hint))

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


def test_live_wait_mode_names_the_right_key_after_the_same_wrong_one(ref):
    from midi_coach import live

    notes, _ = select_notes(ref, "right", bars=(1, 1))
    hub = RecordingHub()
    sess = live.LiveSession("wait", ref, notes, hub)
    sess.start()
    sess.on_message(0.0, _on(61))
    sess.on_message(0.1, _on(63))  # a different wrong key: no hint yet
    sess.on_message(0.2, _on(63))  # the same one again: the flash names C5
    flashes = [e for e in hub.events if e[0] == "flash"]
    from midi_coach import fingering

    finger = {k[1]: f for k, (_, f) in fingering.score_fingers(ref).items() if k[0] == round(notes[0].start, 4)}[72]
    assert flashes == [("flash", "C#4"), ("flash", "Eb4"), ("flash", "Eb4", f"C5 ({finger})")]  # with its finger


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
    # After each chord the cursor flows on to the next instead of jumping, getting there ahead
    # of the tempo (this player is slower than it, so the tempo sets the pace).
    glides = [e for e in hub.events if e[0] == "cursor" and e[3] is not None]
    assert len(glides) == len(notes) - 1
    assert all(g[3] - g[1] == pytest.approx(0.5) and g[2] == pytest.approx(ref.bpm_at(0) / 60 / live.GLIDE_SHARE) for g in glides)
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


def test_live_reports_slips_for_labels(ref):
    from midi_coach import live

    notes, _ = select_notes(ref, "right", bars=(1, 2))
    slips = []
    sess = live.LiveSession("wait", ref, notes, None, on_slip=lambda bar, what: slips.append((bar, what)))
    sess.start()
    sess.on_message(0.0, _on(61))  # a wrong key
    sess.on_message(live.STUCK_SEC + 1, _on(notes[0].pitch))  # then a long hunt for the right one
    assert slips == [(1, "pitch"), (1, "stuck")]

    slips.clear()
    sess = live.LiveSession("rehearsal", ref, notes, None, on_slip=lambda bar, what: slips.append((bar, what)))
    sess._clock = 100.0  # the first note is due now; no ticker, so nothing is marked missed
    due = lambda n: 100.0 + (n.start - notes[0].start)
    second, ninth = notes[1], notes[8]  # an eighth into bar 1; the first of bar 2
    sess.on_message(due(second), _on(second.pitch))  # on time: a hit
    sess.on_message(due(second) + 0.05, _on(second.pitch))  # struck again in its window: no slip
    sess.on_message(due(ninth) + 0.4, _on(ninth.pitch))  # the right key, late: counting
    sess.on_message(due(ninth) + 0.5, _on(30))  # a key that isn't near: note names
    assert slips == [(2, "rhythm"), (2, "pitch")]


def test_aids_label_bars_where_you_slip_and_take_them_off(ref):
    from midi_coach import aids

    pushed = []
    a = aids.Aids(push=pushed.append)
    a.begin_pass(ref, {1, 2, 3})
    assert pushed == [[]]
    a.slip(1, "pitch")
    assert len(pushed) == 1  # one slip could be an accident
    a.slip(1, "stuck")
    assert pushed[-1] == [{"bar": 1, "start": 0.0, "end": 4.0, "kinds": ["names"]}]  # on mid-pass
    a.slip(2, "rhythm")
    changes = a.end_pass(True, {"mode": "rehearsal"}, {"per_bar": [{"bar": 3, "timing_ms": 120}, {"bar": 2, "timing_ms": 20}]})
    assert changes["added"] == {"names": [1], "counts": [3]} and changes["left"] == 2
    assert "note names on bar 1" in aids.remark(changes) and "counting on bar 3" in aids.remark(changes)

    def clean_pass(bars={1, 2, 3}, finished=True):
        a.begin_pass(ref, bars)
        return a.end_pass(finished)

    assert clean_pass()["removed"] == {}  # one clean pass: still on
    assert clean_pass(finished=False)["removed"] == {}  # stopped halfway: doesn't count
    assert clean_pass(bars={2})["removed"] == {}  # didn't play bars 1 or 3
    a.begin_pass(ref, {1, 3})
    a.slip(3, "rhythm")  # slipped again: bar 3 starts over
    assert a.end_pass(True)["removed"] == {"names": [1]}
    assert [b["bar"] for b in pushed[-1]] == [3]
    assert clean_pass()["removed"] == {}
    changes = clean_pass()
    assert changes == {"added": {}, "removed": {"counts": [3]}, "left": 0}
    assert aids.remark(changes) == "Labels off bar 3: you've got it. No labels left on this piece. Try Original under Sheet, Labels."
    assert pushed[-1] == []

    a.slip(1, "pitch")
    a.slip(1, "pitch")
    other = types.SimpleNamespace(path="other.mid", bars=ref.bars, bar=ref.bar)
    a.begin_pass(other, {1})  # another piece: its own labels
    assert a.left == 0 and pushed[-1] == []


def test_display_replays_labels(ref):
    from midi_coach import display

    hub = display.DisplayHub()
    hub.load_score(ref)
    hub.aids([{"bar": 2, "start": 4.0, "end": 8.0, "kinds": ["counts"]}])
    assert {"type": "aids", "bars": [{"bar": 2, "start": 4.0, "end": 8.0, "kinds": ["counts"]}], "off": False} in hub.snapshot()
    hub.aids([], off=True)
    assert {"type": "aids", "bars": [], "off": True} in hub.snapshot()


def test_live_stop_freezes_cursor_before_publishing_inactive(ref):
    from midi_coach import live

    notes, _ = select_notes(ref, "right", bars=(1, 1))

    class StopCheckingHub(RecordingHub):
        session_ref = None

        def session(self, active, mode=None):
            if not active:
                assert self.session_ref.stopped
            super().session(active, mode)

    hub = StopCheckingHub()
    sess = live.LiveSession("rehearsal", ref, notes, hub)
    hub.session_ref = sess
    sess.start()
    sess.on_message(time.perf_counter(), _on(notes[0].pitch))
    time.sleep(0.3)

    sess.stop()
    cursor_count = sum(event[0] == "cursor" for event in hub.events)
    time.sleep(0.1)

    assert sum(event[0] == "cursor" for event in hub.events) == cursor_count
    assert ("session", False, "rehearsal") in hub.events


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
    assert remarks.VOICE["friend"].keys() == remarks.VOICE["strict"].keys()

    # Friend by default; the style and the recent wording survive a restart.
    memory = tmp_path / "maestro.json"
    coach = remarks.Coach(random.Random(3), memory=lambda: memory)
    assert coach.style == "friend"
    rough = {"mode": "wait", "hits": 4, "missed": 0, "wrong_presses": 12, "notes_total": 16, "per_bar": {}, "slips": []}
    for _ in range(3):
        said = coach.remark(rough)
        assert len(re.findall(r"[.!?](?=\s|$)", said)) <= 2
    coach.style = "strict"
    later = remarks.Coach(random.Random(3), memory=lambda: memory)
    assert later.style == "strict" and later._recent == coach._recent
    said_before = list(coach._recent["friend:verdict-rough"])
    later.style = "friend"
    assert later._pick("verdict-rough") not in said_before
    memory.write_text('{"style": "warm"}')  # the friend's old name
    assert remarks.Coach(memory=lambda: memory).style == "friend"
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


def test_autopilot_changes_the_practice_like_a_teacher():
    from midi_coach import autopilot

    def p(grade, hot=None):
        return {"grade": grade, "hot_bar": hot, "hot_count": 2 if hot else 0}

    pilot = autopilot.Autopilot()
    settings = {"mode": "wait", "hand": "both", "bars": "1-12", "tempo_percent": 80}
    pilot.start(settings)
    history = []

    def step(*passes):
        history.extend(passes)
        out = pilot.decide(history, settings, 20)
        if out:
            settings.update(out[0])
        return out

    assert step(p("close", 6)) is None
    changes, said = step(p("shaky", 6))  # bar 6 twice: loop it with a bar either side
    assert changes == {"bars": "5-7"} and "5 to 7" in said
    assert step(p("clean"), p("clean")) is None  # counted from the change: two isn't three
    changes, said = step(p("clean"))
    assert changes == {"bars": "1-12"} and "bars 1 to 12" in said
    assert step(p("clean"), p("clean")) is None
    changes, _ = step(p("clean"))  # Learn, three clean: Rehearse at 70%
    assert changes == {"mode": "rehearsal", "tempo_percent": 70}
    changes, said = step(p("rough"))
    assert changes == {"tempo_percent": 60} and "60 percent" in said
    changes, _ = step(p("rough"))
    assert changes == {"tempo_percent": 50}
    assert step(p("rough")) is None  # slowest already, and one rough pass since the change
    changes, _ = step(p("rough"))  # two rough in a row with both hands
    assert changes == {"hand": "right"}
    assert pilot.can_undo and pilot.undo(len(history)) == {"hand": "both"} and not pilot.can_undo
    settings["hand"] = "both"
    changes, _ = step(p("rough"), p("rough"))
    assert changes == {"hand": "right"}
    changes, _ = step(p("clean"), p("clean"))
    assert changes == {"hand": "left"}
    changes, said = step(p("clean"), p("clean"))
    assert changes == {"hand": "both"} and "both hands" in said.lower()
    step(p("clean"), p("clean"))
    changes, _ = step(p("clean"))
    assert changes == {"tempo_percent": 55}
    settings["tempo_percent"] = 100
    assert step(p("clean"), p("clean"), p("clean")) is None  # already at full tempo


def test_autopilot_runs_between_loop_passes_and_undo_puts_it_back(ref, monkeypatch, tmp_path):
    from midi_coach import display, remarks, server

    hub = display.DisplayHub()
    said = []
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(hub, "say", lambda text, interrupt=False, speaker="Claude": said.append(text) or 0)
    monkeypatch.setattr(server, "_coach", remarks.Coach(memory=lambda: tmp_path / "maestro.json"))
    monkeypatch.setattr(server, "_autopilot", server.autopilot.Autopilot())
    monkeypatch.setattr(server.threading, "Timer", lambda *a, **k: types.SimpleNamespace(start=lambda: None))
    settings = {"reference": ref.path, "mode": "rehearsal", "hand": "both", "bars": None, "tempo_percent": 90,
                "loop": True, "autopilot": True}
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": settings, "pass": 1, "stopping": False})
    server._autopilot.start(settings)
    rough = {"mode": "rehearsal", "hits": 4, "missed": 12, "wrong_presses": 3, "notes_total": 16, "per_bar": {},
             "slips": [], "tempo_percent": 90}
    server._end_pass("reached the end", rough, None)
    assert settings["tempo_percent"] == 80 and "80 percent" in said[-1]
    assert len(said[-1].split(". ")) <= 2  # how it went, then the change
    out = server._voice_reply("Undo!")
    assert out["actions"] == ["undo"] and settings["tempo_percent"] == 90 and "90 percent" in out["reply"]
    assert said[-1] == out["reply"]
    server._end_pass("reached the end", {**rough, "missed": 0, "wrong_presses": 0, "hits": 16}, None)  # clean: no change
    assert settings["tempo_percent"] == 90 and not server._autopilot.can_undo


def test_maestro_style_is_a_setting(monkeypatch, tmp_path):
    import json

    from midi_coach import display, remarks, server

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_coach", remarks.Coach(memory=lambda: tmp_path / "maestro.json"))
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})
    out = server._cmd_maestro({})
    assert out["style"] == "friend" and out["styles"] == ["friend", "strict"]
    assert server._voice.actions["set_style"](style="strict")["style"] == "strict"
    assert "Teaching style: strict." in server._voice_context()
    assert json.loads((tmp_path / "maestro.json").read_text())["style"] == "strict"


def test_maestro_talk_settings(monkeypatch, tmp_path):
    import json
    import random

    from midi_coach import display, remarks, server

    memory = tmp_path / "maestro.json"
    coach = remarks.Coach(random.Random(1), memory=lambda: memory)
    assert coach.talk == {"greet": True, "passes": "news", "sign_off": True}
    clean = _wait_summary()
    coach.start({"title": "Etude", "mode": "wait"})
    assert coach.remark(clean)
    assert coach.remark(clean) is None  # second clean pass in a row: nothing new

    coach.set_talk(passes="every")
    assert coach.remark(clean)  # every pass gets a remark
    coach.set_talk(greet=False, passes="off", sign_off=False)
    assert coach.start({"title": "Etude", "mode": "wait"}) is None and coach.context["title"] == "Etude"
    assert coach.remark(clean) is None and coach.remark(clean) is None and coach.last_lead is None
    assert len(coach.history) == 2  # still remembered, for the autopilot and the voice chat
    assert coach.wrap_up() is None
    assert remarks.Coach(memory=lambda: memory).talk == {"greet": False, "passes": "off", "sign_off": False}
    try:
        coach.set_talk(passes="sometimes")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown passes setting accepted")

    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_coach", remarks.Coach(memory=lambda: tmp_path / "other.json"))
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})
    assert server._cmd_maestro({})["talk"]["passes"] == "news"
    assert server._voice.actions["set_talk"](greet=False)["talk"] == {"greet": False, "passes": "news", "sign_off": True}
    assert "no greeting" in server._voice_context()
    assert json.loads((tmp_path / "other.json").read_text())["talk"]["greet"] is False


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


def test_voice_context_says_where_here_is(monkeypatch, ref):
    """'Loop from here' means the bar the cursor was on when Talk was pressed, not where a
    moving cursor has got to by the time the speech is transcribed."""
    from midi_coach import display, server, stt

    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})
    monkeypatch.setattr(server, "_talk", {})
    server._cmd_load({"lesson": "etude"})
    assert "Cursor at bar 1 " in server._voice_context()  # a loaded lesson starts at the top

    server.hub.cursor(ref.bars[1].start_beat + 0.5, 1.0, live=True)
    assert "Cursor at bar 2 " in server._voice_context()
    server._cmd_talk({})
    server.hub.cursor(ref.bars[3].start_beat, 1.0, live=True)  # the music moved on while they spoke
    seen = []
    monkeypatch.setattr(stt, "transcribe", lambda audio: "loop from here")
    monkeypatch.setattr(server, "_voice_reply", lambda heard: seen.append(server._voice_context()) or {"heard": heard})
    server._voice_audio(b"audio")
    assert "Cursor at bar 2 " in seen[0]
    assert "Cursor at bar 4 " in server._voice_context()  # a typed message later: the cursor as it is then


def test_atlas_lesson_replaces_a_running_freeplay_song(monkeypatch, ref):
    """Opening a lesson from the Atlas while a Freeplay run is still going stops that run and
    puts the lesson's music on the sheet, instead of quietly leaving the last song up."""
    from midi_coach import display, server

    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})
    running = {"on": True}
    monkeypatch.setattr(server, "_busy", lambda: running["on"])
    monkeypatch.setattr(server, "_listening", lambda: False)
    monkeypatch.setattr(server, "_cmd_stop", lambda body: running.update(on=False) or {"stopped": True})
    out = server._atlas_show(str(ref.path))
    assert not running["on"] and server.hub.score_path == out["path"] == ref.path

    running["on"] = True  # a run that won't stop: the page hears why, not silence
    monkeypatch.setattr(server, "_cmd_stop", lambda body: {"stopped": True})
    with pytest.raises(RuntimeError, match="Stop the current run"):
        server._atlas_show(str(ref.path))


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
        assert comp["scores"]["notes"] == 100
        assert comp["notes"]["correct"] == 16 and comp["notes"]["missed"] == 0
        heat = server.hub._heat
        assert heat and {b["bar"] for b in heat} == {1, 2}
        shown = await server.show_heatmap()
        assert shown["bars_shown"] == 2

    try:
        asyncio.run(run())
    finally:
        server.hub.shutdown()


def test_wait_mode_grade_uses_live_accuracy():
    from midi_coach.server import _wait_mode_note_grade

    grade = _wait_mode_note_grade(
        {"hits": 6, "missed": 0, "wrong_presses": 2, "notes_total": 8},
        expected_notes=8,
    )
    assert grade["scores"]["notes"] == 75
    assert grade["notes"] == {
        "correct": 6,
        "wrong": 0,
        "missed": 2,
        "extra": 2,
        "accuracy_pct": 75.0,
        "precision_pct": 75.0,
    }


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


def test_page_file_menu_open_save_as_download(ref, fake_rtmidi, monkeypatch):
    import base64
    import urllib.request

    from midi_coach import display, lessons, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    server.hub.commands.update(server.PAGE_COMMANDS)
    root = server.hub.start()
    url = root + "cmd/"
    original = pathlib.Path(ref.path).read_bytes()
    try:
        assert "error" in _post(url + "save_as", {"title": "Copy"})  # nothing on the page yet
        _post(url + "load", {"lesson": "etude"})
        with urllib.request.urlopen(root + "file") as res:  # Download: the file the sheet came from
            assert res.read() == original
            assert "Practice%20Etude%20in%20C.mid" in res.headers["Content-Disposition"]

        saved = _post(url + "save_as", {"title": "Etude: my copy", "category": "Solo piano"})
        assert pathlib.Path(saved["path"]) == lessons.lessons_dir("Solo piano").resolve() / "Etude my copy.mid"
        assert pathlib.Path(saved["path"]).read_bytes() == original and pathlib.Path(ref.path).is_file()
        assert "already in" in _post(url + "save_as", {"title": "Etude my copy", "category": "Solo piano"})["error"]

        data = base64.b64encode(original).decode()
        opened = _post(url + "open_file", {"name": "My piece.mid", "data": data})
        path = pathlib.Path(opened["path"])
        assert path.parent == lessons.lessons_dir().resolve() and path.name == "My piece.mid"
        assert server.hub.score_path == opened["path"]
        assert _post(url + "open_file", {"name": "My piece.mid", "data": data})["path"] == opened["path"]  # the same file again
        bad = _post(url + "open_file", {"name": "My piece.mid", "data": base64.b64encode(b"not midi").decode()})
        assert "Couldn't read" in bad["error"] and not (path.parent / "My piece (2).mid").exists()
        assert "isn't a MIDI" in _post(url + "open_file", {"name": "notes.txt", "data": data})["error"]
    finally:
        server.hub.shutdown()


def test_deleted_sheet_file_is_not_searched_by_title(ref, monkeypatch, tmp_path):
    from midi_coach import display, server

    monkeypatch.setattr(server, "hub", display.DisplayHub())
    gone = tmp_path / "home" / "lessons" / "Needs review" / "Practice Etude in C (with vocals).musicxml"
    with pytest.raises(FileNotFoundError, match="moved or deleted"):  # not 'ambiguous', not another file
        library.get_score(str(gone))
    server.hub.score_path = str(gone)  # the page's sheet, deleted while it was open
    assert server._cmd_parts({}) == {"path": None, "tracks": [], "choices": [], "play": None}


def test_page_seek_restarts_learn_at_requested_bar_without_saving_partial_take(ref, fake_rtmidi, monkeypatch):
    from midi_coach import display, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_live", {"session": None, "watcher": None})
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None, "running": False})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"

    try:
        assert _post(url + "load", {"lesson": "etude"})["bars"] == len(ref.bars)
        assert [bar["number"] for bar in server.hub.score_payload()["bars"]] == [bar.number for bar in ref.bars]
        started = _post(url + "start", {"mode": "learn", "hand": "right", "bars": "1-3", "loop": True, "port": "JUNO-DS 0"})
        assert started["mode"] == "wait", started
        _until(lambda: server.recorder.active)
        first_session = server._live["session"]

        assert _post(url + "seek", {"bar": 2}) == {"bar": 2, "seeking": True}
        _until(lambda: server._live["session"] is not first_session and server.recorder.active)
        session = server._live["session"]
        assert min(note.start for note in session.notes) >= ref.bars[1].start - 1e-6
        assert server._practice["settings"]["bars"] == "1-3"

        _post(url + "stop")
        _until(lambda: not server._practice["running"])
        assert not asyncio.run(server.list_takes(reference="etude"))["takes"]
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


def test_page_listen_plays_it_for_you(ref, fake_rtmidi, monkeypatch):
    from midi_coach import display, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_live", {"session": None})
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    bar1 = [n.pitch for n in ref.notes if n.start < ref.bars[1].start]
    try:
        _post(url + "load", {"lesson": "etude"})
        started = _post(url + "start", {"mode": "listen", "bars": "1", "tempo": 150, "loop": True})
        assert started["mode"] == "listen" and started["output"] == "JUNO-DS 0", started
        assert not server.recorder.active  # nothing to play, so the keyboard input stays closed
        assert "error" in _post(url + "start", {"mode": "learn"})  # one run at a time
        assert "error" in _post(url + "load", {"lesson": "etude"})
        _until(lambda: server._practice["pass"] == 2, timeout=8)  # bar 1 played through, then looped
        ons = [m[1] for _, m in FakeOut.sent if m[0] & 0xF0 == 0x90 and m[2]]
        assert all(ons.count(p) >= bar1.count(p) for p in bar1)  # both hands
        assert [0xB0, 64, 127] in [m for _, m in FakeOut.sent]  # with the sustain pedal
        assert server.hub._cursor["live"]
        _post(url + "stop")
        _until(lambda: not server._practice["running"])
        time.sleep(1.7)  # no further pass after Stop
        assert not server._practice["running"] and server._practice["pass"] == 2
        sounding = set()
        for _, m in FakeOut.sent:
            if m[0] & 0xF0 == 0x90 and m[2]:
                sounding.add(m[1])
            elif m[0] & 0xF0 in (0x80, 0x90):
                sounding.discard(m[1])
        assert not sounding and FakeOut.sent[-1][1] == [0xB0, 64, 0]  # everything let go
        assert library.list_takes() == []  # nothing saved or graded
    finally:
        server._practice["stopping"] = True
        if server._live["session"]:
            server._live["session"].stop()
        server.hub.shutdown()


def test_page_listen_plays_each_part_at_its_fader(ref, fake_rtmidi, monkeypatch):
    from midi_coach import display, server

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_live", {"session": None})
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    left = {n.pitch for n in ref.notes if n.part == 1 and n.start < ref.bars[1].start}
    right = {n.pitch for n in ref.notes if n.part == 0 and n.start < ref.bars[1].start}
    try:
        _post(url + "load", {"lesson": "etude"})
        muted = _post(url + "start", {"mode": "listen", "gains": {"0": 0, "1": 0}})  # a lane per track
        assert "muted" in muted["error"]
        _post(url + "track", {"index": 1, "listen_mute": True})  # Listen's own mix, saved for the file
        _post(url + "track", {"index": 0, "listen_vol": 50})
        started = _post(url + "start", {"mode": "listen", "bars": "1"})
        assert started["mode"] == "listen", started
        session = server._live["session"]
        assert set(session.lanes) == {"0", "1"}  # the muted track is there to turn up mid-run
        assert session.accompanist.gains == {"0": 0.5, "1": 0.0}
        assert _post(url + "track", {"index": 0, "listen_vol": 25})["tracks"][0]["listen_vol"] == 25  # heard live
        assert session.accompanist.gains == {"0": 0.25, "1": 0.0}
        assert _post(url + "mix", {"gains": {"0": 0.2}}) == {"gains": {"0": 0.2}, "live": True}
        assert server._practice["settings"]["gains"] == {"0": 0.2}  # kept for the next pass
        _until(lambda: any(m[0] & 0xF0 == 0x90 and m[2] and m[1] in right for _, m in FakeOut.sent), timeout=8)
        _post(url + "stop")
        _until(lambda: not server._practice["running"])
        ons = [m for _, m in FakeOut.sent if m[0] & 0xF0 == 0x90 and m[2]]
        assert ons and all(m[1] not in left - right for m in ons)  # the left hand stays silent
    finally:
        server._practice["stopping"] = True
        if server._live["session"]:
            server._live["session"].stop()
        server.hub.shutdown()


def test_listen_hears_the_shown_parts(ref):
    from midi_coach import server

    right = server._listen_notes(ref, ["right"], "2-3", 60)
    both = server._listen_notes(ref, ["right", "left", "right"], "2-3", 60)
    assert {n.part for n in right} == {0} and {n.part for n in both} == {0, 1}
    assert len(both) == len({id(n) for n in both})
    t0, t1 = ref.bar_range_times(2, 3)
    assert all(t0 - 1e-6 <= n.start < t1 for n in both)


def test_accompanist_sends_the_pedal_for_listen(fake_rtmidi):
    acc = midi_io.Accompanist(pedal=True)
    acc.schedule([(0.0, [0xB0, 64, 127]), (0.0, [0x90, 60, 80]), (0.0, [0xB0, 7, 100]), (5.0, [0x80, 60, 0])],
                 time.perf_counter())
    _until(lambda: [0x90, 60, 80] in [m for _, m in FakeOut.sent])
    acc.close()
    assert [m for _, m in FakeOut.sent] == [[0xB0, 64, 127], [0x90, 60, 80], [0x80, 60, 0], [0xB0, 64, 0]]


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
    assert [e["beat"] for e in d5] == [4.0, 7.0]  # the sheet's beats, for the visualizer's cursor
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


def _write_unsteady_take(path, wobble=0.04, bars=16, seed=3):
    """A piece played without a click at about 92 BPM, the tempo wandering a few percent
    each beat, saved at the default 120 BPM: right-hand eighths over a left-hand chord on
    each bar's downbeat. Too unsteady for regrid to trust on its own."""
    rng = random.Random(seed)
    ticks_per_sec = PPQ * 2  # 120 BPM in the file
    t, bpm, notes = 0.0, 92.0, []
    for bar in range(bars):
        for beat in range(4):
            bpm = min(max(bpm * (1 + rng.uniform(-wobble, wobble)), 70), 115)
            dur = 60 / bpm
            if beat == 0:
                notes += [(t, t + dur * 3.8, p) for p in (48, 52, 55)]
            for k in range(2):
                on = t + k * dur / 2 + rng.gauss(0, 0.008)
                notes.append((on, on + dur / 2 * 0.9, 67 + (bar * 3 + beat * 2 + k) % 8))
            t += dur
    events = []
    for on, off, pitch in notes:
        events += [(round(on * ticks_per_sec), mido.Message("note_on", note=pitch, velocity=70)),
                   (round(off * ticks_per_sec), mido.Message("note_off", note=pitch))]
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    last = 0
    for tick, msg in sorted(events, key=lambda e: (e[0], e[1].type == "note_on")):
        tr.append(msg.copy(time=max(0, tick - last)))
        last = max(last, tick)
    mid.save(str(path))
    return path


def test_live_recording_gets_a_rough_sheet_and_no_count_in(ref, tmp_path):
    from midi_coach import display, live

    live_path = _write_live_take(tmp_path / "songs" / "Nocturne live.mid")
    played = load_score(live_path)
    assert played.played_live and played.grid_fit() < 0.5
    assert not ref.played_live and ref.grid_fit() == 1.0
    hub = display.DisplayHub()
    hub.load_score(played)
    payload = hub.score_payload()
    # Drawn anyway, on the file's own grid, with a warning and the Auto clean offer.
    assert payload["xml"].lstrip().startswith("<?xml") and payload["notice"] is None
    assert payload["cleanup"] == "off" and "No steady beat" in payload["warning"] and payload["grid"] is False
    assert payload["tempo"] is None  # Match score / Follow score have nothing to go on
    hub.load_score(ref)
    payload = hub.score_payload()
    assert payload["xml"].lstrip().startswith("<?xml") and payload["notice"] is None
    assert payload["warning"] is None and payload["cleanup"] is None
    assert payload["tempo"] == {"bpm": BPM, "beats": 4, "type": 4}
    info = asyncio.run(__import__("midi_coach.server", fromlist=["x"]).inspect_reference(str(live_path)))
    assert info["played_live"] and "bar numbers" in info["timing_note"] and "Auto clean" in info["timing_note"]


def test_auto_clean_finds_the_beat_of_unsteady_playing(ref, tmp_path, monkeypatch):
    from midi_coach import display, regrid, server

    path = _write_unsteady_take(tmp_path / "songs" / "Unsteady.mid")
    raw = library.get_score("unsteady")
    assert raw.played_live and raw.regrid is None  # the automatic regrid doesn't trust it
    monkeypatch.setattr(server, "_show", lambda score, notes: server.hub.load_score(score))
    server.hub.score_path = raw.path
    assert server._cmd_cleanup({"on": True}) == {"cleanup": "on"}

    score = library.get_score("unsteady")
    assert not score.played_live and score.regrid["cleaned"]
    right = sorted((n for n in score.notes if n.pitch >= 60), key=lambda n: n.start)
    assert [b.beat - a.beat for a, b in zip(right, right[1:])] == [0.5] * (len(right) - 1)  # eighths, not dotted
    assert len(score.bars) == 16 and {n.beat for n in score.notes if n.pitch == 48} == {4.0 * k for k in range(16)}
    assert [(n.start, n.pitch) for n in score.notes] == [(n.start, n.pitch) for n in raw.notes]  # notation only
    payload = server.hub.score_payload()
    assert payload["cleanup"] == "on" and "Auto-cleaned" in payload["warning"] and payload["grid"]
    assert payload["xml"].count("<measure ") == 32  # 16 bars on each of two staves

    library.save_hands(score, {0: "both"})  # a part choice keeps the cleanup
    assert library.get_score("unsteady").regrid["cleaned"]
    assert server._cmd_cleanup({"on": False}) == {"cleanup": "off"}
    assert library.get_score("unsteady").played_live and server.hub.score_payload()["cleanup"] == "off"
    assert library.load_roles(score) == {0: "both"}

    monkeypatch.setattr(regrid, "track_free", lambda notes, bpm: [])
    path.write_bytes(path.read_bytes())  # a new date: the cached map is not used
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert "couldn't find" in server._cmd_cleanup({"on": True})["error"]
    assert not library.cleanup_chosen(raw.path)


def test_auto_clean_keeps_the_reading_that_writes_plainest(ref, tmp_path, monkeypatch):
    from midi_coach import regrid

    _write_unsteady_take(tmp_path / "songs" / "Unsteady.mid")
    raw = library.get_score("unsteady")
    [(good, quality), *_] = regrid.track_free(raw.notes, 120.0)
    # The same beat read 20% fast: dotted eighths and chords tied over the beat, though no
    # single note breaks an engraving rule. Offered first (as if it fitted a little better).
    stretched = regrid.BeatMap(good.secs, [b * 1.2 for b in good.beats])
    assert regrid.rhythm_cost([n.beat for n in regrid.apply(raw, stretched, quality).notes]) > \
        regrid.rhythm_cost([n.beat for n in regrid.apply(raw, good, quality).notes])
    monkeypatch.setattr(regrid, "track_free", lambda notes, bpm: [(stretched, quality), (good, quality)])
    library.set_cleanup(raw.path, True)

    score = library.get_score("unsteady")
    assert score.regrid["cleaned"] and score.regrid["choices"] == 2 and score.regrid["engraving_problems"] == 0
    assert score.beat_map.beats == good.beats
    right = sorted((n for n in score.notes if n.pitch >= 60), key=lambda n: n.start)
    assert [b.beat - a.beat for a, b in zip(right, right[1:])] == [0.5] * (len(right) - 1)


def test_huge_file_gets_no_sheet(ref, monkeypatch):
    from midi_coach import display

    monkeypatch.setattr(display, "SHEET_MAX_NOTES", 100)
    hub = display.DisplayHub()
    monkeypatch.setattr(hub, "xml_for", lambda path: pytest.fail("a huge file must not be converted"))
    hub.load_score(ref)
    assert hub.score_payload()["xml"] is None and "too much to draw" in hub.score_payload()["notice"]
    assert hub.score_payload()["grid"] is True  # the metronome can still follow it


def test_falling_notes_come_with_the_score(ref, monkeypatch):
    from midi_coach import display

    monkeypatch.setattr(display, "SHEET_MAX_NOTES", 100)  # no sheet: the falling notes are still drawn
    hub = display.DisplayHub()
    hub.load_score(ref)
    notes = hub.score_payload()["notes"]
    assert len(notes) == len(ref.notes)
    by_start = {(round(n.beat, 3), n.pitch): n for n in ref.notes}
    for beat, length, pitch, role, finger in notes:  # each hand's note with its finger (fingering.py)
        n = by_start[(beat, pitch)]
        assert role == ("right" if pitch >= 60 else "left")
        assert length == pytest.approx(ref.beat_of(n.end) - n.beat, abs=1e-3)
        assert 1 <= finger <= 5
    assert {length for _, length, pitch, *_ in notes if pitch >= 60} == {0.5}  # eighth notes


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


def test_piano_sheet_marks_dynamics_from_velocities(ref, tmp_path):
    from fractions import Fraction

    from midi_coach import sheet

    assert not sheet.wanted(ref)  # a crescendo inside each bar, the same level every bar: no marks to add
    mid = mido.MidiFile(str(ref.path))
    for tr in mid.tracks:
        tick = 0
        for msg in tr:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity:
                bar = tick // (4 * PPQ)
                # p for 8 bars (bar 4 accented: one loud bar is not a new dynamic), then f
                msg.velocity = 100 if bar == 3 else 45 if bar < 8 else 95
    path = tmp_path / "songs" / "Dynamic Etude.mid"
    mid.save(str(path))
    score = library.get_score(str(path))
    onsets = [(Fraction(n.beat).limit_denominator(48), n.velocity) for n in score.notes]
    # f on the first note after the rest bars (9 and 10)
    assert [(float(at), mark) for at, mark in sheet.dynamic_marks(score, onsets)] == [(0.0, "p"), (40.0, "f")]
    assert sheet.wanted(score)  # a plain piano file, written by us so the dynamics are on it
    xml = sheet.build(score)["xml"]
    assert xml.count("<dynamics") == 2 and "<p />" in xml.replace("<p/>", "<p />") and "<f />" in xml.replace("<f/>", "<f />")
    drawn = load_score(tmp_path / "dyn.musicxml") if (tmp_path / "dyn.musicxml").write_text(xml, encoding="utf-8") else None
    assert sorted((n.beat, n.pitch) for n in drawn.notes) == sorted((n.beat, n.pitch) for n in score.notes)


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

    from midi_coach.engraving import lint
    from midi_coach.transcribe import grand_staff

    # D flat major: written with 5 flats, not C sharp major's 7 sharps.
    events = [("right", F(b * 4 + k), F(b * 4 + k + 1), p) for b in range(4) for k, p in enumerate((61, 65, 68, 73))]
    events += [("left", F(b * 4), F(b * 4 + 4), 49) for b in range(4)]
    out = grand_staff(events, "t")
    assert out["key"] == "Db" and "<fifths>-5</fifths>" in out["xml"]
    # A right hand that drops too low to read in treble for two bars (C3, a run on four ledger
    # lines) changes to bass clef and back.
    events = [("right", F(b * 4 + k), F(b * 4 + k + 1), 48 if b in (1, 2) else 72) for b in range(4) for k in range(4)]
    events += [("left", F(b * 4), F(b * 4 + 4), 36) for b in range(4)]
    right = converter.parseData(grand_staff(events, "t")["xml"]).parts[0]
    assert [(float(c.getOffsetInHierarchy(right)), c.sign) for c in right.recurse().getElementsByClass("Clef")] == [(0.0, "G"), (4.0, "F"), (12.0, "G")]
    # Dipping for four bars to notes that read on ledger lines (Great Gig in the Sky bars
    # 22-25: G3, B flat 3, E flat 3, one D3) stays in treble.
    dip = [(55, 58, 62), (51, 58, 62), (55, 50, 58), (55, 58, 63)]
    events = [("right", F(b * 4 + k), F(b * 4 + k + 1), 72) for b in range(12) for k in range(4) if not 4 <= b < 8]
    events += [("right", F(b * 4 + k), F(b * 4 + k + 1), p) for b in range(4, 8) for k in range(3) for p in [dip[b - 4][k]]]
    events += [("left", F(b * 4), F(b * 4 + 4), 39) for b in range(12)]
    out = grand_staff(events, "t")["xml"]
    right = converter.parseData(out).parts[0]
    assert [c.sign for c in right.recurse().getElementsByClass("Clef")] == ["G"]
    assert not lint(out)["counts"]["brief-clef-change"] and not lint(out)["counts"]["ledger-lines"]
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

    # Bass clef for four bars on the treble staff, over G3s that read on two ledger lines:
    # flagged. The same four bars down at C3, a run on four ledger lines, need it: not flagged.
    from music21 import clef

    def dip(pitch):
        bars = [bar(*[note.Note(pitch if 2 <= b < 6 else "C5", quarterLength=1) for _ in range(4)]) for b in range(12)]
        for b, m in enumerate(bars):
            m.number = b + 1
        bars[0].insert(0, clef.TrebleClef())
        bars[2].insert(0, clef.BassClef())
        bars[6].insert(0, clef.TrebleClef())
        return engraving.lint(stream.Score([stream.Part(bars)]))["findings"]

    assert [(f[0], f[2]) for f in dip("G3") if f[0] == "brief-clef-change"] == [("brief-clef-change", 3)]
    assert not [f for f in dip("C3") if f[0] == "brief-clef-change"]


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


def test_grand_staff_writes_a_note_two_octaves_out_under_15mb(tmp_path):
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    # A synth line in the bass that ends on a C0 held for two bars (a sound effect in a band
    # file): nine ledger lines as written, still five under 8vb, so it goes under 15mb.
    events = [("left", F(k, 2), F(k + 1, 2), (40, 43, 45, 50)[k % 4]) for k in range(16)]
    events += [("left", F(8), F(16), 12)] + [("right", F(b * 4), F(b * 4 + 4), 64) for b in range(4)]
    out = grand_staff(events, "t")
    report = engraving.lint(out["xml"])
    assert not report["findings"], report["findings"][:5]
    assert 'size="15"' in out["xml"]
    path = tmp_path / "t.musicxml"
    path.write_text(out["xml"], encoding="utf-8")
    score = load_score(path)  # still graded as C0
    assert 12 in {n.pitch for n in score.notes}
    assert sorted(n.pitch for n in score.notes) == sorted(p for *_, p in events)


def test_a_low_note_held_over_bars_is_one_note_on_four_ledger_lines():
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    # An F1 held for three bars after one short F1 (a synth line in a band file): written tied
    # over the barlines, it is two notes on four ledger lines, not four in a row needing 8vb.
    events = [("left", F(0), F(1), 29), ("left", F(4), F(16), 29)] + [("right", F(b * 4), F(b * 4 + 4), 64) for b in range(4)]
    out = grand_staff(events, "t")
    assert "<octave-shift" not in out["xml"] and "<tied" in out["xml"]
    report = engraving.lint(out["xml"])
    assert not report["findings"], report["findings"][:5]


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


# ---------------------------------------------------------------------------
# Part roles (pedals, vocals), accompaniment, and the page's Songs / Lessons panel
# ---------------------------------------------------------------------------


def _write_organ(path):
    """4 bars for organ and choir: a tune for the right hand, chords for the left, a bass line
    for the feet (named Pedal) and a sung line."""
    mid = mido.MidiFile(ticks_per_beat=PPQ)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM)))
    mid.tracks.append(meta)
    for name, channel, program, pitches in (
        ("Upper", 0, None, lambda b: [72 + b % 5]),
        ("Lower", 1, None, lambda b: [55, 60]),
        ("Pedal", 2, 19, lambda b: [36 + b % 3]),
        ("Choir Vocals", 3, 52, lambda b: [67 + b % 4]),
    ):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        if program is not None:
            tr.append(mido.Message("program_change", program=program, channel=channel))
        for beat in range(16):
            for pitch in pitches(beat):
                tr.append(mido.Message("note_on", note=pitch, velocity=70, channel=channel, time=0))
            for k, pitch in enumerate(pitches(beat)):
                tr.append(mido.Message("note_off", note=pitch, velocity=0, channel=channel, time=PPQ if k == 0 else 0))
        mid.tracks.append(tr)
    mid.save(str(path))
    return path


def test_pedals_and_vocals_roles(ref, tmp_path):
    from midi_coach import engraving, sheet
    from midi_coach.notes import effective_roles

    _write_organ(tmp_path / "songs" / "Organ Hymn.mid")
    score = library.get_score("organ hymn")
    ix = {p.name: p.index for p in score.parts}
    upper, lower, pedal, choir = ix["Upper"], ix["Lower"], ix["Pedal"], ix["Choir Vocals"]
    # Suggested before anyone confirms: the pedal part is for the feet, not a hand.
    assert effective_roles(score) == {upper: "right", lower: "left", pedal: "pedals", choir: "vocals"}

    def parts_of(s, hand):
        return {n.part for n in select_notes(s, hand)[0]}

    assert parts_of(score, "both") == {upper, lower}  # the hands only: no feet, never the vocals
    assert parts_of(score, "right+pedals") == {upper, pedal}
    assert parts_of(score, "pedals") == {pedal} and parts_of(score, "vocals") == {choir}
    assert len(select_notes(score, "both+pedals", bars=(1, 1))[0]) == 4 * 2 + 4 + 4
    with pytest.raises(ValueError):
        select_notes(score, "pedals+right")

    # A confirmed choice keeps the roles; score.hands stays the hands' parts only.
    library.save_hands(score, {upper: "both", pedal: "pedals", choir: "vocals"})
    library._score_cache.clear()
    again = library.get_score("organ hymn")
    assert again.roles == {upper: "both", pedal: "pedals", choir: "vocals"} and again.hands == {upper: "both"}
    assert parts_of(again, "both") == {upper}

    # The sheet: the vocal line over the piano, the pedals under it, each staff's role known.
    library.save_hands(again, {upper: "right", lower: "left", pedal: "pedals", choir: "vocals"})
    out = sheet.build(again)
    assert out["staves"] == sheet.staves(again) == ["vocals", "right", "left", "pedals"]
    names = [n.split(">", 1)[1].split("<", 1)[0] for n in out["xml"].split("<part-name")[1:]]
    assert names == ["Vocals", "Right Hand", "Left Hand", "Pedals"], names
    assert not engraving.lint(out["xml"])["findings"]
    path = tmp_path / "organ.musicxml"
    path.write_text(out["xml"], encoding="utf-8")
    written = load_score(path)  # every pedal note is on the sheet, at its pitch
    feet = next(p.index for p in written.parts if p.name == "Pedals")
    assert sorted(n.pitch for n in written.notes if n.part == feet) == sorted(n.pitch for n in again.notes if n.part == pedal)


def test_backing_is_what_you_dont_play(ref, tmp_path):
    from midi_coach import server

    _write_organ(tmp_path / "songs" / "Organ Hymn.mid")
    score = library.get_score("organ hymn")
    ix = {p.name: p.index for p in score.parts}
    mine = server._selection(score, "right+pedals", "2-3", 60)[0]
    lanes, _, gains = server._track_lanes(score, "2-3", mine=mine)
    lower, choir = str(ix["Lower"]), str(ix["Choir Vocals"])
    assert set(lanes) == {lower, choir}  # one lane per track you don't play
    assert {n.part for n in lanes[lower]} == {ix["Lower"]} and {n.part for n in lanes[choir]} == {ix["Choir Vocals"]}
    assert gains == {lower: 1.0, choir: 1.0}  # every track sounds unless muted
    t0, t1 = score.bar_range_times(2, 3)
    assert all(t0 - 1e-6 <= n.start < t1 for part in lanes.values() for n in part)
    both, _, _ = server._track_lanes(score, None, mine=server._selection(score, "both", None, 60)[0])
    assert set(both) == {str(ix["Pedal"]), choir}  # the feet's part and the singing sound when you play the hands


def test_accompanist_plays_each_lane_at_its_volume(fake_rtmidi):
    acc = midi_io.Accompanist()
    acc.gains.update({"left": 0.5, "vocals": 0.0})
    now = time.perf_counter()
    acc.schedule([(0.0, [0x90, 60, 80]), (0.05, [0x80, 60, 0])], now, "right")  # no fader: as written
    acc.schedule([(0.0, [0x90, 48, 100]), (0.05, [0x80, 48, 0])], now, "left")
    acc.schedule([(0.0, [0x90, 72, 90]), (0.05, [0x80, 72, 0])], now, "vocals")  # muted, its note-off too
    acc.schedule([(0.3, [0x90, 50, 100]), (0.35, [0x80, 50, 0])], now, "left")
    _until(lambda: [0x80, 48, 0] in [m for _, m in FakeOut.sent])
    acc.gains["left"] = 1.0  # a fader moved mid-run: heard from the next note
    _until(lambda: [0x80, 50, 0] in [m for _, m in FakeOut.sent])
    acc.close()
    assert [m for _, m in FakeOut.sent] == [[0x90, 60, 80], [0x90, 48, 50], [0x80, 60, 0], [0x80, 48, 0],
                                            [0x90, 50, 100], [0x80, 50, 0]]


def test_accompanist_sends_notes_only_and_lets_go(fake_rtmidi):
    acc = midi_io.Accompanist()
    assert acc.port == "JUNO-DS 0"
    now = time.perf_counter()
    acc.schedule([(0.0, [0xB0, 64, 127]), (0.0, [0x90, 60, 80]), (0.05, [0x80, 60, 0]),
                  (0.0, [0x90, 64, 80]), (5.0, [0x80, 64, 0]), (9.0, [0x90, 67, 80])], now)
    acc.schedule([(0.0, [0x90, 62, 80]), (0.1, [0x80, 62, 0])], now - 1.0)  # already past: dropped
    _until(lambda: [0x80, 60, 0] in [m for _, m in FakeOut.sent])
    acc.close()
    sent = [m for _, m in FakeOut.sent]
    assert sent == [[0x90, 60, 80], [0x90, 64, 80], [0x80, 60, 0], [0x80, 64, 0]]  # 64 let go on close; no pedal, no 67


def test_accompanist_never_leaves_a_restruck_key_hanging(fake_rtmidi):
    # Learn schedules a chord window at a time: a held note's off (window end + 0.5 s) can come
    # after the next window strikes the same key. On, on, off used to leave a voice stuck.
    acc = midi_io.Accompanist()
    acc.voices({"band": (3, None)})
    now = time.perf_counter()
    acc.schedule([(0.0, [0x90, 67, 80]), (0.3, [0x80, 67, 0])], now, "band")
    acc.schedule([(0.1, [0x90, 67, 90]), (0.2, [0x80, 67, 0])], now, "band")
    _until(lambda: len(FakeOut.sent) >= 4)
    acc.close()
    assert [m for _, m in FakeOut.sent] == [[0x93, 67, 80], [0x83, 67, 0], [0x93, 67, 90], [0x83, 67, 0]]
    FakeOut.sent = []
    acc = midi_io.Accompanist()
    acc.schedule([(0.0, [0x90, 60, 80]), (0.05, [0x90, 60, 80]), (0.1, [0x80, 60, 0]), (9.0, [0x80, 60, 0])],
                 time.perf_counter())
    _until(lambda: len(FakeOut.sent) >= 3)
    acc.close()  # the second strike still holds the key: close lets it go
    assert [m for _, m in FakeOut.sent] == [[0x90, 60, 80], [0x80, 60, 0], [0x90, 60, 80], [0x80, 60, 0]]


class FakeAccompanist:
    def __init__(self):
        self.scheduled = []
        self.closed = False

    def schedule(self, events, start, lane=None):
        self.scheduled.append((start, events) if lane is None else (start, events, lane))

    def close(self):
        self.closed = True


def test_live_runs_play_the_backing(ref):
    from midi_coach import live

    right, _ = select_notes(ref, "right", bars=(1, 1))
    left, _ = select_notes(ref, "left", bars=(1, 1))
    # Learn: each chord you finish plays the left hand up to the next chord.
    acc = FakeAccompanist()
    sess = live.LiveSession("wait", ref, right, RecordingHub(), backing=left, accompanist=acc)
    sess.start()
    sess.on_message(1.0, _on(right[0].pitch))
    start, events = acc.scheduled[0]
    expected = {n.pitch for n in left if right[0].start <= n.start < right[1].start}
    assert start == 1.0 and {m[1] for _, m in events if m[0] & 0xF0 == 0x90} == expected
    for n in right[1:]:
        sess.on_message(2.0, _on(n.pitch))
    assert len(acc.scheduled) == len(right)
    sess.stop()
    assert acc.closed

    # Rehearse: the whole backing once the clock starts on your first note.
    acc = FakeAccompanist()
    sess = live.LiveSession("rehearsal", ref, right, RecordingHub(), tempo_percent=50, backing=left, accompanist=acc)
    sess.start()
    try:
        assert acc.scheduled == []
        t0 = time.perf_counter()
        sess.on_message(t0, _on(right[0].pitch))
        (start, events), = acc.scheduled
        assert start == t0
        ons = sorted(t for t, m in events if m[0] & 0xF0 == 0x90)
        assert ons[-1] == pytest.approx((max(n.start for n in left) - right[0].start) / 0.5)
    finally:
        sess.stop()
    assert acc.closed


def test_backing_by_role_is_scheduled_per_role(ref):
    from midi_coach import live

    right, _ = select_notes(ref, "right", bars=(1, 2))
    left, _ = select_notes(ref, "left", bars=(1, 2))
    acc = FakeAccompanist()
    sess = live.LiveSession(live.LISTEN, ref, right + left, None, backing={"right": right, "left": left, "vocals": []},
                            accompanist=acc, pedal=[(0.0, 127)])
    sess.start()
    try:
        assert [s[2] for s in acc.scheduled] == ["right", "left"]  # a role with no notes is left out
        pedals = [[m for _, m in s[1] if m[0] & 0xF0 == 0xB0] for s in acc.scheduled]
        assert pedals[0] and not pedals[1]  # the pedal goes once
        assert {m[1] for _, m in acc.scheduled[1][1] if m[0] & 0xF0 == 0x90} == {n.pitch for n in left}
    finally:
        sess.stop()


def test_page_songs_lessons_and_parts(ref, tmp_path, fake_rtmidi, monkeypatch):
    from midi_coach import display, lessons, server

    _write_organ(tmp_path / "songs" / "Organ Hymn.mid")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_song_files", {"at": -1e9, "files": []})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    exercise = lessons.lessons_dir(lessons.EXERCISES) / "Scale.mid"
    _write_reference(exercise)
    song = lessons.lessons_dir("Solo piano") / "Nocturne.mid"
    _write_reference(song)
    library.save_take([(0.0, [0x90, 60, 80]), (0.5, [0x80, 60, 0])], {"reference": str(exercise)})
    try:
        found = _post(url + "songs", {"query": "hymn organ"})
        assert [s["title"] for s in found["songs"]] == ["Organ Hymn"]
        assert found["total"] == 2  # the etude and the hymn: saved lessons aren't library songs
        assert _post(url + "songs", {"query": "nothing like it"})["matches"] == 0
        practised = _post(url + "songs", {})  # no query: library files practised lately (none yet)
        assert practised["songs"] == [] and practised["total"] == 2
        listed = {item["title"]: item for item in _post(url + "lessons")["lessons"]}
        assert listed["Scale"]["kind"] == "lesson" and listed["Scale"]["history"]["runs"] == 1
        assert listed["Nocturne"]["kind"] == "song" and listed["Nocturne"]["history"] is None

        assert _post(url + "parts")["tracks"] == []
        _post(url + "load", {"lesson": "organ hymn"})
        parts = _post(url + "parts")
        assert not parts["confirmed"] and parts["play"] == "both"
        assert parts["choices"] == ["both", "right", "left", "both+pedals", "right+pedals", "left+pedals", "pedals"]
        assert {t["name"]: t["part"] for t in parts["tracks"]} == {
            "Upper": "right", "Lower": "left", "Pedal": "pedals", "Choir Vocals": "vocals"}
        payload = server.hub._score_payload
        assert payload["staves"] == ["vocals", "right", "left", "pedals"] and payload["path"].endswith("Organ Hymn.mid")

        by_name = {t["name"]: t["index"] for t in parts["tracks"]}
        assert _post(url + "confirm_parts")["confirmed"]
        _post(url + "track", {"index": by_name["Upper"], "part": "both"})
        saved = _post(url + "track", {"index": by_name["Lower"], "part": "backing"})
        assert {t["name"]: t["part"] for t in saved["tracks"]}["Lower"] == "backing"
        _post(url + "track", {"index": by_name["Choir Vocals"], "part": "backing"})
        assert server.hub._score_payload["staves"] == ["right", "left", "pedals"]  # redrawn for the new parts
        assert _post(url + "parts")["choices"] == ["both", "right", "left", "both+pedals", "right+pedals", "left+pedals", "pedals"]
        _post(url + "track", {"index": by_name["Upper"], "part": "right"})  # no track for the left hand now
        assert _post(url + "parts")["choices"] == ["right", "right+pedals", "pedals"]
        assert "yours to play" in _post(url + "track", {"index": by_name["Upper"], "part": "backing"})["error"]
        out = _post(url + "song_settings", {"play": "right+pedals"})
        assert out["play"] == "right+pedals" and out["playing"] is None  # a hand and the feet, not a named part
    finally:
        server.hub.shutdown()


def test_song_lesson_vocals_are_not_a_hand(ref, tmp_path):
    from fractions import Fraction as F

    from midi_coach.notes import effective_roles, is_plain_piano
    from midi_coach.transcribe import grand_staff

    events = [("right", F(k), F(k + 1), 72) for k in range(8)] + [("left", F(k * 2), F(k * 2 + 2), 48) for k in range(4)]
    tune = [(F(k), F(k + 1), 67, None) for k in range(8)]
    path = tmp_path / "songs" / "Song (with vocals).musicxml"
    path.write_text(grand_staff(events, "Song", melody=tune)["xml"], encoding="utf-8")
    score = library.get_score(str(path))
    # Every staff of a MusicXML file loads as piano; the one named Vocals is still the sung line.
    ix = {p.name: p.index for p in score.parts if p.note_count}
    assert effective_roles(score) == {ix["Vocals"]: "vocals", ix["Right Hand"]: "right", ix["Left Hand"]: "left"}
    assert {n.part for n in select_notes(score, "both")[0]} == {ix["Right Hand"], ix["Left Hand"]}
    two = tmp_path / "songs" / "Duet.musicxml"  # a vocal line over one piano staff isn't plain piano either
    two.write_text(grand_staff([("right", F(k), F(k + 1), 72) for k in range(4)], "Duet", melody=tune[:4])["xml"], encoding="utf-8")
    assert not is_plain_piano(library.get_score(str(two)))


def test_accidentals_follow_the_sounding_octave_under_an_octave_mark():
    """A note under 8va is drawn an octave below where it sounds: its accidental is decided
    by the sounding pitch, so an A4 natural drawn where an earlier A3 natural sits keeps its
    sign (B flat minor, left hand climbing to B flat 4 in the bass clef)."""
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    lh = [46, 48, 49, 51, 53, 54, 57, 58, 60, 61, 63, 65, 66, 69, 70, 69, 66]  # B flat 2 .. B flat 4 (harmonic) and back
    events = [("left", F(k, 4), F(k + 1, 4), p) for k, p in enumerate(lh)] + [("right", F(k, 4), F(k + 1, 4), p + 12) for k, p in enumerate(lh)]
    out = grand_staff(events, "t", "4/4", legato_gap=F(0))
    assert "<octave-shift" in out["xml"]  # the top of the left hand goes under 8va...
    assert not engraving.lint(out["xml"])["findings"]  # ...and keeps its naturals


def test_clefs_can_change_inside_a_bar():
    """clef_every: a four-octave arpeggio inside a bar changes clef as it climbs, instead of
    leaving notes eight ledger lines off the staff."""
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    up = [35 + o for o in (0, 4, 7, 12, 16, 19, 24, 28, 31, 36, 40, 43, 48)]  # B major from B1 over four octaves
    seq = up + up[-2::-1]
    events = [("left", F(k, 4), F(k + 1, 4), p) for k, p in enumerate(seq)] + [("right", F(k, 4), F(k + 1, 4), p + 12) for k, p in enumerate(seq)]
    per_bar = engraving.lint(grand_staff(events, "t", "4/4", legato_gap=F(0))["xml"])["counts"]
    per_beat = grand_staff(events, "t", "4/4", legato_gap=F(0), clef_every=F(1))["xml"]
    assert per_bar["ledger-lines"] > 0
    assert not engraving.lint(per_beat)["findings"]
    assert per_beat.count("<clef") > 4  # changes inside the bars


def test_notes_of_the_key_signature_are_spelled_as_the_key_spells_them():
    """In F minor (four flats) the note between G and A is A flat, not G sharp; the raised
    leading note E natural stays as it is."""
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    tune = [65, 67, 68, 70, 72, 68, 64, 65, 68, 67, 68, 65]  # F G Ab Bb C Ab E F ...
    events = [("right", F(k), F(k + 1), p) for k, p in enumerate(tune)] + [("left", F(4 * b), F(4 * b + 4), 53) for b in range(3)]
    xml = grand_staff(events, "t", "4/4")["xml"]
    assert "<fifths>-4</fifths>" in xml
    assert "<step>G</step>\n          <alter>1</alter>" not in xml and not engraving.lint(xml)["findings"]
    # The rule itself: a G sharp written in that key is reported.
    bad = xml.replace("<step>A</step>\n          <alter>-1</alter>", "<step>G</step>\n          <alter>1</alter>", 1)
    assert bad != xml and engraving.lint(bad)["counts"]["wrong-enharmonic"] >= 1


def test_a_tie_no_single_note_can_replace_is_not_needless():
    """A quaver tied to a 32nd inside one beat can't be written as one note (music21 calls its
    sum 'complex'): the tie is needed, so needless-tie must not report it."""
    from music21 import note, stream, tie

    from midi_coach import engraving

    part = stream.Part()
    part.partName = "Right Hand"
    m = stream.Measure(number=1)
    a, b = note.Note("C5", quarterLength=0.5), note.Note("C5", quarterLength=0.125)
    a.tie, b.tie = tie.Tie("start"), tie.Tie("stop")
    for el in (a, b, note.Note("D5", quarterLength=0.375), note.Note("E5", quarterLength=3)):
        m.append(el)
    part.append(m)
    assert engraving.lint(stream.Score([part]))["counts"]["needless-tie"] == 0


def test_an_upbeat_is_bar_zero_on_the_sheet_and_in_the_coach(tmp_path):
    """Für Elise starts with two semiquavers before bar 1: the sheet writes them as a short
    bar 0 (implicit), and loading it back the coach's bar 1 starts where the sheet's does."""
    import re
    from fractions import Fraction as F

    from midi_coach import engraving
    from midi_coach.transcribe import grand_staff

    tune = [76, 75, 76, 75, 76, 71, 74, 72]
    events = [("right", F(k, 4), F(k + 1, 4), p) for k, p in enumerate(tune)] + [("right", F(2), F(7, 2), 69),
              ("left", F(3, 4), F(1), 45), ("left", F(1), F(5, 4), 52), ("left", F(5, 4), F(3, 2), 57)]
    xml = grand_staff(events, "t", "3/8", legato_gap=F(0), pickup=F(1, 2))["xml"]
    assert re.findall(r'<measure implicit="(\w+)" number="(\d+)"', xml)[:2] == [("yes", "0"), ("no", "1")]
    assert not engraving.lint(xml)["findings"]
    path = tmp_path / "upbeat.musicxml"
    path.write_text(xml, encoding="utf-8")
    score = load_score(path)
    assert [(b.number, b.start_beat, b.end_beat) for b in score.bars[:3]] == [(0, 0.0, 0.5), (1, 0.5, 2.0), (2, 2.0, 3.5)]
    third = sorted(score.notes, key=lambda n: (n.start, n.pitch))[2]  # E, the first note of bar 1
    assert score.position(third.start) == (1, 1.0)
    assert score.bar_range_times(1, 1) == (score.bars[1].start, score.bars[1].end)


def test_an_upbeat_with_a_two_voice_left_hand_keeps_its_timing(tmp_path):
    """The left hand rests through the upbeat and then has two voices (a held bass under
    moving notes): its notes stay where they were, the empty upbeat holds one rest per voice."""
    from fractions import Fraction as F

    from midi_coach.transcribe import grand_staff

    events = [("right", F(0), F(1, 2), 74)] + [("right", F(1, 2) + F(k, 2), F(1) + F(k, 2), 79 - k) for k in range(8)]
    events += [("left", F(1, 2), F(9, 2), 43)] + [("left", F(1, 2) + F(k, 2), F(1) + F(k, 2), 55 + (k % 3)) for k in range(8)]
    xml = grand_staff(events, "t", "2/4", legato_gap=F(0), pickup=F(1, 2))["xml"]
    path = tmp_path / "voices.musicxml"
    path.write_text(xml, encoding="utf-8")
    got = sorted((round(n.beat, 3), n.pitch) for n in load_score(path).notes)
    assert got == sorted((float(on), p) for _, on, _, p in events)


def test_a_beat_mixing_triplet_values_is_one_bracket_and_the_next_note_stays_plain(tmp_path):
    """A quarter and two 16ths, all triplets, then a plain eighth: the beat is one triplet
    bracket, and the eighth isn't cut into a tied eighth-and-16th triplet to fill a group."""
    from fractions import Fraction as F

    from midi_coach.engraving import lint
    from midi_coach.transcribe import grand_staff

    events = [("right", F(0), F(2, 3), 76), ("right", F(2, 3), F(5, 6), 85), ("right", F(5, 6), F(1), 82),
              ("right", F(1), F(3, 2), 71), ("right", F(3, 2), F(2), 67), ("left", F(0), F(2), 48)]
    xml = grand_staff(events, "t", "2/4", legato_gap=F(0))["xml"]
    assert "<tie " not in xml
    assert not lint(xml)["counts"].get("needless-tie")
    path = tmp_path / "triplets.musicxml"
    path.write_text(xml, encoding="utf-8")
    got = sorted((round(n.beat, 3), n.pitch) for n in load_score(path).notes)
    assert got == sorted((round(float(on), 3), p) for _, on, _, p in events)


def test_lint_flags_tuplets_no_one_writes_even_in_published_music():
    from music21 import duration, note, stream

    from midi_coach.engraving import lint

    m = stream.Measure(number=1)
    n = note.Note("C5")
    d = duration.Duration("16th")
    d.appendTuplet(duration.Tuplet(23, 16, "32nd"))
    n.duration = d
    m.append(n)
    part = stream.Part([m])
    part.partName = "Right Hand"
    score = stream.Score([part])
    assert lint(score, profile="published")["counts"].get("unwritable-tuplet")


def test_lint_flags_triple_dots_even_in_published_music():
    from music21 import duration, note, stream

    from midi_coach.engraving import lint

    m = stream.Measure(number=1)
    n = note.Note("C5")
    n.duration = duration.Duration(type="eighth", dots=3)
    m.append(n)
    part = stream.Part([m])
    part.partName = "Right Hand"
    found = lint(stream.Score([part]), profile="published")["counts"]
    assert found.get("triple-dot") and not found.get("double-dot")


def test_build_lesson_prints_a_repeated_accidental_once_per_bar(tmp_path):
    """F sharp, G, F sharp in one bar: the second F sharp needs no sign (the bar's first one
    covers it), F natural after it needs a natural, and the next bar starts afresh."""
    from midi_coach.engraving import lint
    from midi_coach import lessons

    path, score = lessons.build_lesson("Sharps", "f#4 g f# a f#4 fn f# r", None, "4/4", "C", 72, out_dir=tmp_path,
                                       filename="sharps")
    assert path.endswith("sharps.musicxml") and str(tmp_path) in path
    assert not lint(path)["findings"]
    xml = pathlib.Path(path).read_text(encoding="utf-8")
    assert xml.count("<accidental>sharp</accidental>") == 3 and xml.count("<accidental>natural</accidental>") == 1
    assert [n.pitch for n in score.notes] == [66, 67, 66, 69, 66, 65, 66]


def test_launcher_reuses_only_a_coach_started_after_the_code_changed(tmp_path):
    """The shortcut opens the running coach only if it's current; a copy from before an update
    is restarted (practice) or reported (Claude Desktop), never shown half-working."""
    import json
    import os
    import socket
    import urllib.request

    from midi_coach import display, launch

    hub = display.DisplayHub()
    url = hub.start()
    try:
        info = json.loads(urllib.request.urlopen(url + "version").read())
        assert info["pid"] == os.getpid() and info["started"] == hub.started
        assert launch.running(int(url.rsplit(":", 1)[1].strip("/"))) == info
        assert urllib.request.urlopen(url + "favicon.ico").headers["Content-Type"] == "image/x-icon"
    finally:
        hub.shutdown()
    with socket.socket() as s:  # a port nothing listens on
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert launch.running(free) is None

    code = tmp_path / "pkg"
    (code / "tests").mkdir(parents=True)
    (code / "a.py").write_text("")
    (code / "tests" / "test_a.py").write_text("")
    (code / "logo.png").write_text("")
    os.utime(code / "a.py", (1000, 1000))
    os.utime(code / "tests" / "test_a.py", (5000, 5000))
    os.utime(code / "logo.png", (5000, 5000))
    assert launch.newest_source([code]) == 1000  # tests and images don't count
    assert launch.is_current({"started": 1001}, 1000)
    assert not launch.is_current({"started": 999}, 1000) and not launch.is_current({}, 1000)

    assert launch.is_practice(r'"C:\repo\.venv\Scripts\python.exe" -m midi_coach.launch')
    assert launch.is_practice("python -m midi_coach.practice great gig")
    assert not launch.is_practice("python -m midi_coach")  # Claude Desktop's server
