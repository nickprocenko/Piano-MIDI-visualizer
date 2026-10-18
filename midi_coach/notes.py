"""Load MIDI / MusicXML files into a flat, seconds-based note model.

Parts are split by MIDI track + channel, matching the visualizer's Learn Mode
track list. Bars are derived from the file's time-signature and tempo maps so
results can be reported as "bar 12, beat 3".
"""

from __future__ import annotations

import bisect
import pathlib
import tempfile
from dataclasses import dataclass, field

import mido

MUSICXML_SUFFIXES = {".xml", ".musicxml", ".mxl"}
MIDI_SUFFIXES = {".mid", ".midi"}

_NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def note_name(pitch: int) -> str:
    return f"{_NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


@dataclass
class Note:
    pitch: int
    start: float
    end: float
    velocity: int
    part: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Part:
    index: int
    track: int
    channel: int
    name: str
    note_count: int = 0
    low: int = 127
    high: int = 0
    mean_pitch: float = 0.0


@dataclass
class Bar:
    number: int  # 1-based
    start: float
    end: float
    numerator: int
    denominator: int


@dataclass
class Score:
    path: str
    notes: list[Note]
    parts: list[Part]
    pedal: list[tuple[float, int]]  # (seconds, CC64 value)
    bars: list[Bar]
    tempos: list[tuple[float, float]]  # (seconds, bpm)
    duration: float
    _bar_starts: list[float] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._bar_starts = [b.start for b in self.bars]

    def bar_at(self, t: float) -> Bar | None:
        if not self.bars:
            return None
        i = bisect.bisect_right(self._bar_starts, t) - 1
        return self.bars[max(0, min(i, len(self.bars) - 1))]

    def position(self, t: float) -> tuple[int, float]:
        """Return (bar number, 1-based beat) for a time in seconds."""
        bar = self.bar_at(t)
        if bar is None:
            return 1, 1.0
        span = max(bar.end - bar.start, 1e-6)
        beat = 1.0 + (t - bar.start) / span * bar.numerator
        return bar.number, round(beat, 2)

    def bar_range_times(self, first: int, last: int) -> tuple[float, float]:
        first = max(1, min(first, len(self.bars)))
        last = max(first, min(last, len(self.bars)))
        return self.bars[first - 1].start, self.bars[last - 1].end

    def bpm_at(self, t: float) -> float:
        bpm = self.tempos[0][1] if self.tempos else 120.0
        for when, value in self.tempos:
            if when > t:
                break
            bpm = value
        return bpm


class _TempoMap:
    def __init__(self, ppq: int, changes: list[tuple[int, int]]) -> None:
        self.ppq = ppq
        changes = sorted(changes)
        if not changes or changes[0][0] != 0:
            changes.insert(0, (0, 500000))
        self.ticks: list[int] = []
        self.secs: list[float] = []
        self.tempos: list[int] = []
        sec = 0.0
        prev_tick, prev_tempo = 0, changes[0][1]
        for tick, tempo in changes:
            sec += mido.tick2second(tick - prev_tick, ppq, prev_tempo)
            if self.ticks and self.ticks[-1] == tick:
                self.tempos[-1] = tempo
            else:
                self.ticks.append(tick)
                self.secs.append(sec)
                self.tempos.append(tempo)
            prev_tick, prev_tempo = tick, tempo

    def to_seconds(self, tick: int) -> float:
        i = bisect.bisect_right(self.ticks, tick) - 1
        return self.secs[i] + mido.tick2second(tick - self.ticks[i], self.ppq, self.tempos[i])


def load_score(path: str | pathlib.Path) -> Score:
    path = pathlib.Path(path)
    suffix = path.suffix.lower()
    if suffix in MUSICXML_SUFFIXES:
        return _load_musicxml(path)
    return load_midi(path)


def _load_musicxml(path: pathlib.Path) -> Score:
    from music21 import converter  # heavy import, only when needed

    stream = converter.parse(str(path))
    with tempfile.TemporaryDirectory() as tmp:
        midi_path = pathlib.Path(tmp) / "converted.mid"
        stream.write("midi", fp=str(midi_path))
        score = load_midi(midi_path)
    score.path = str(path)
    return score


def load_midi(path: str | pathlib.Path) -> Score:
    mid = mido.MidiFile(str(path))
    ppq = mid.ticks_per_beat

    tempo_changes: list[tuple[int, int]] = []
    sig_changes: list[tuple[int, int, int]] = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempo_changes.append((tick, msg.tempo))
            elif msg.type == "time_signature":
                sig_changes.append((tick, msg.numerator, msg.denominator))
    tmap = _TempoMap(ppq, tempo_changes)

    parts: dict[tuple[int, int], Part] = {}
    notes: list[Note] = []
    note_keys: list[tuple[int, int]] = []
    pedal: list[tuple[float, int]] = []
    end_tick = 0
    for t_idx, track in enumerate(mid.tracks):
        tick = 0
        track_name = ""
        open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for msg in track:
            tick += msg.time
            end_tick = max(end_tick, tick)
            if msg.type == "track_name":
                track_name = msg.name.strip()
            elif msg.type == "note_on" and msg.velocity > 0:
                open_notes.setdefault((msg.channel, msg.note), []).append((tick, msg.velocity))
            elif msg.type in ("note_off", "note_on"):
                stack = open_notes.get((msg.channel, msg.note))
                if not stack:
                    continue
                start_tick, vel = stack.pop(0)
                key = (t_idx, msg.channel)
                if key not in parts:
                    parts[key] = Part(index=-1, track=t_idx, channel=msg.channel, name=track_name)
                notes.append(Note(msg.note, tmap.to_seconds(start_tick), tmap.to_seconds(tick), vel))
                note_keys.append(key)
            elif msg.type == "control_change" and msg.control == 64:
                pedal.append((tmap.to_seconds(tick), msg.value))

    # Stable part numbering: by track, then channel.
    ordered = sorted(parts.values(), key=lambda p: (p.track, p.channel))
    per_track: dict[int, int] = {}
    for part in ordered:
        per_track[part.track] = per_track.get(part.track, 0) + 1
    for i, part in enumerate(ordered):
        part.index = i
        if not part.name:
            part.name = f"Track {part.track + 1}"
        if per_track[part.track] > 1:
            part.name = f"{part.name} (ch {part.channel + 1})"
    for n, key in zip(notes, note_keys):
        n.part = parts[key].index
    for part in ordered:
        pitches = [n.pitch for n in notes if n.part == part.index]
        part.note_count = len(pitches)
        if pitches:
            part.low, part.high = min(pitches), max(pitches)
            part.mean_pitch = round(sum(pitches) / len(pitches), 1)

    notes.sort(key=lambda n: (n.start, n.pitch))
    pedal.sort()
    duration = max([n.end for n in notes] + [tmap.to_seconds(end_tick)] + [0.0])
    bars = _build_bars(tmap, ppq, sig_changes, end_tick)
    last_note_end = max((n.end for n in notes), default=0.0)
    while len(bars) > 1 and bars[-1].start >= last_note_end - 1e-6:
        bars.pop()  # end-of-track padding after the music
    tempos = [(s, round(mido.tempo2bpm(t), 2)) for s, t in zip(tmap.secs, tmap.tempos)]
    return Score(str(path), notes, ordered, pedal, bars, tempos, duration)


def _build_bars(tmap: _TempoMap, ppq: int, sigs: list[tuple[int, int, int]], end_tick: int) -> list[Bar]:
    sigs = sorted(sigs)
    if not sigs or sigs[0][0] != 0:
        sigs.insert(0, (0, 4, 4))
    bars: list[Bar] = []
    tick = 0
    sig_i = 0
    while tick < max(end_tick, 1):
        while sig_i + 1 < len(sigs) and sigs[sig_i + 1][0] <= tick:
            sig_i += 1
        _, num, den = sigs[sig_i]
        length = int(num * ppq * 4 / den)
        bar_end = tick + length
        # A signature change in the middle of a bar starts a new bar there.
        if sig_i + 1 < len(sigs) and sigs[sig_i + 1][0] < bar_end:
            bar_end = sigs[sig_i + 1][0]
        bars.append(Bar(len(bars) + 1, tmap.to_seconds(tick), tmap.to_seconds(bar_end), num, den))
        tick = bar_end
    return bars


# ---------------------------------------------------------------------------
# Hand / part selection
# ---------------------------------------------------------------------------

_RIGHT_WORDS = ("right", "rh", "r.h", "treble", "upper", "melody")
_LEFT_WORDS = ("left", "lh", "l.h", "bass", "lower")


def parse_bars(bars: str | None) -> tuple[int, int] | None:
    if bars is None or str(bars).strip() == "":
        return None
    text = str(bars).replace("–", "-").replace(" ", "")
    if "-" in text:
        a, b = text.split("-", 1)
        first, last = int(a), int(b)
    else:
        first = last = int(text)
    if first < 1 or last < first:
        raise ValueError(f"Invalid bar range: {bars!r}")
    return first, last


def _name_side(name: str) -> str | None:
    lower = name.lower()
    tokens = set(lower.replace("(", " ").replace(")", " ").replace("-", " ").replace("_", " ").split())
    if any(w in tokens or (len(w) > 3 and w in lower) for w in _RIGHT_WORDS):
        return "right"
    if any(w in tokens or (len(w) > 3 and w in lower) for w in _LEFT_WORDS):
        return "left"
    return None


def select_notes(
    score: Score,
    hand: str = "both",
    parts: list[int] | None = None,
    bars: tuple[int, int] | None = None,
    split_note: int = 60,
) -> tuple[list[Note], dict]:
    """Pick the notes of one hand (or explicit parts) within an optional bar range.

    Returns (notes, info) where info explains how the selection was made.
    """
    hand = (hand or "both").lower()
    info: dict = {"hand": hand}
    notes = score.notes
    if parts:
        wanted = set(parts)
        notes = [n for n in notes if n.part in wanted]
        info["method"] = f"parts {sorted(wanted)}"
    elif hand in ("right", "left"):
        playable = [p for p in score.parts if p.note_count > 0]
        sides = {p.index: _name_side(p.name) for p in playable}
        named = [i for i, s in sides.items() if s == hand]
        if named and any(s for s in sides.values() if s != hand):
            notes = [n for n in notes if n.part in set(named)]
            info["method"] = f"parts {named} by track name"
        elif len(playable) == 2:
            hi, lo = sorted(playable, key=lambda p: -p.mean_pitch)
            chosen = hi if hand == "right" else lo
            notes = [n for n in notes if n.part == chosen.index]
            info["method"] = f"part {chosen.index} ('{chosen.name}') by register"
        else:
            if hand == "right":
                notes = [n for n in notes if n.pitch >= split_note]
            else:
                notes = [n for n in notes if n.pitch < split_note]
            info["method"] = f"pitch split at {note_name(split_note)}"
    else:
        info["method"] = "all parts"
    if bars:
        t0, t1 = score.bar_range_times(*bars)
        notes = [n for n in notes if t0 - 1e-6 <= n.start < t1 - 1e-6]
        info["bars"] = f"{bars[0]}-{bars[1]}"
    return list(notes), info


def notes_from_events(events: list[tuple[float, list[int]]]) -> tuple[list[Note], list[tuple[float, int]]]:
    """Turn raw (seconds, midi bytes) events into notes + pedal list."""
    notes: list[Note] = []
    pedal: list[tuple[float, int]] = []
    open_notes: dict[int, list[tuple[float, int]]] = {}
    last_t = 0.0
    for t, data in events:
        last_t = max(last_t, t)
        if not data:
            continue
        status = data[0] & 0xF0
        if status == 0x90 and len(data) >= 3 and data[2] > 0:
            open_notes.setdefault(data[1], []).append((t, data[2]))
        elif status in (0x80, 0x90) and len(data) >= 3:
            stack = open_notes.get(data[1])
            if stack:
                start, vel = stack.pop(0)
                notes.append(Note(data[1], start, t, vel))
        elif status == 0xB0 and len(data) >= 3 and data[1] == 64:
            pedal.append((t, data[2]))
    for pitch, stack in open_notes.items():
        for start, vel in stack:
            notes.append(Note(pitch, start, max(last_t, start + 0.05), vel))
    notes.sort(key=lambda n: (n.start, n.pitch))
    return notes, pedal


def pedal_intervals(pedal: list[tuple[float, int]], end: float) -> list[tuple[float, float]]:
    """Convert CC64 values into (down, up) intervals."""
    out: list[tuple[float, float]] = []
    down_at: float | None = None
    for t, value in pedal:
        if value >= 64 and down_at is None:
            down_at = t
        elif value < 64 and down_at is not None:
            out.append((down_at, t))
            down_at = None
    if down_at is not None:
        out.append((down_at, max(end, down_at)))
    return out
