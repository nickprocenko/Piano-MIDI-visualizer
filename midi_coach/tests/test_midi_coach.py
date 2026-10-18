"""Tests for midi-coach using synthetic references, takes and a fake rtmidi."""

from __future__ import annotations

import asyncio
import random
import sys
import time
import types

import mido
import pytest

from midi_coach import analysis, library, midi_io
from midi_coach.notes import Note, load_score, notes_from_events, parse_bars, select_notes

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
