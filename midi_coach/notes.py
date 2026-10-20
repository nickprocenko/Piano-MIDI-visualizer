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
# General MIDI program names (program_change 0-127). Channel 10 is always drums.
GM_PROGRAMS = [
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano", "Honky-tonk Piano",
    "Electric Piano 1", "Electric Piano 2", "Harpsichord", "Clavinet",
    "Celesta", "Glockenspiel", "Music Box", "Vibraphone", "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ", "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    "Nylon Guitar", "Steel Guitar", "Jazz Guitar", "Clean Electric Guitar",
    "Muted Guitar", "Overdriven Guitar", "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Fingered Bass", "Picked Bass", "Fretless Bass", "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass", "Tremolo Strings", "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2", "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn", "Brass Section", "Synth Brass 1", "Synth Brass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax", "Oboe", "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle", "Shakuhachi", "Whistle", "Ocarina",
    "Square Lead", "Sawtooth Lead", "Calliope Lead", "Chiff Lead", "Charang Lead", "Voice Lead", "Fifths Lead", "Bass + Lead",
    "New Age Pad", "Warm Pad", "Polysynth Pad", "Choir Pad", "Bowed Pad", "Metallic Pad", "Halo Pad", "Sweep Pad",
    "Rain FX", "Soundtrack FX", "Crystal FX", "Atmosphere FX", "Brightness FX", "Goblins FX", "Echoes FX", "Sci-fi FX",
    "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bagpipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock", "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet", "Telephone Ring", "Helicopter", "Applause", "Gunshot",
]
DRUM_CHANNEL = 9  # MIDI channel 10, 0-based

_SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def note_name(pitch: int, spelling: str | None = None) -> str:
    """spelling: None (mixed default), 'sharps' or 'flats' (e.g. to match a key signature)."""
    names = {"sharps": _SHARP_NAMES, "flats": _FLAT_NAMES}.get(spelling or "", _NOTE_NAMES)
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


@dataclass
class Note:
    pitch: int
    start: float
    end: float
    velocity: int
    part: int = 0
    beat: float = 0.0  # quarter notes from the start of the file (for score display)

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
    program: int | None = None  # General MIDI program; None = never set (sounds as piano)
    drums: bool = False

    @property
    def instrument(self) -> str:
        if self.drums:
            return "Drums"
        if self.program is None:
            return "Piano (no instrument set)"
        return GM_PROGRAMS[self.program]

    @property
    def is_piano(self) -> bool:
        return not self.drums and (self.program is None or self.program < 8)


@dataclass
class Bar:
    number: int  # 1-based
    start: float
    end: float
    numerator: int
    denominator: int
    start_beat: float = 0.0  # quarter notes
    end_beat: float = 0.0


@dataclass
class Score:
    path: str
    notes: list[Note]
    parts: list[Part]
    pedal: list[tuple[float, int]]  # (seconds, CC64 value)
    bars: list[Bar]
    tempos: list[tuple[float, float]]  # (seconds, bpm)
    duration: float
    hands: dict[int, str] = field(default_factory=dict)  # confirmed part -> 'right' | 'left' | 'both'
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
    programs: dict[int, list[tuple[int, int]]] = {}  # channel -> [(tick, program)]
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                tempo_changes.append((tick, msg.tempo))
            elif msg.type == "time_signature":
                sig_changes.append((tick, msg.numerator, msg.denominator))
            elif msg.type == "program_change":
                programs.setdefault(msg.channel, []).append((tick, msg.program))
    tmap = _TempoMap(ppq, tempo_changes)

    parts: dict[tuple[int, int], Part] = {}
    first_tick: dict[tuple[int, int], int] = {}
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
                    parts[key] = Part(index=-1, track=t_idx, channel=msg.channel, name=track_name, drums=msg.channel == DRUM_CHANNEL)
                first_tick[key] = min(first_tick.get(key, start_tick), start_tick)
                notes.append(Note(msg.note, tmap.to_seconds(start_tick), tmap.to_seconds(tick), vel, beat=start_tick / ppq))
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
    for key, part in parts.items():
        # The instrument sounding at the part's first note (else the channel's first program).
        changes = sorted(programs.get(part.channel, []))
        before = [prog for tick, prog in changes if tick <= first_tick[key]]
        if before or changes:
            part.program = before[-1] if before else changes[0][1]
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
        bars.append(Bar(len(bars) + 1, tmap.to_seconds(tick), tmap.to_seconds(bar_end), num, den, tick / ppq, bar_end / ppq))
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


def playable_parts(score: Score) -> list[Part]:
    """Parts that could be played on a keyboard: they have notes and aren't drums."""
    return [p for p in score.parts if p.note_count > 0 and not p.drums]


def _split(notes: list[Note], hand: str, split_note: int) -> list[Note]:
    if hand == "right":
        return [n for n in notes if n.pitch >= split_note]
    return [n for n in notes if n.pitch < split_note]


def select_notes(
    score: Score,
    hand: str = "both",
    parts: list[int] | None = None,
    bars: tuple[int, int] | None = None,
    split_note: int = 60,
) -> tuple[list[Note], dict]:
    """Pick the notes of one hand (or explicit parts) within an optional bar range.

    Precedence: explicit parts, then the user's confirmed part choice (score.hands),
    then a guess from track names / register / pitch split. Drums are left out unless
    asked for by part number. Returns (notes, info) where info explains the selection.
    """
    hand = (hand or "both").lower()
    info: dict = {"hand": hand}
    notes = score.notes
    playable = playable_parts(score)
    if parts:
        wanted = set(parts)
        notes = [n for n in notes if n.part in wanted]
        info["method"] = f"parts {sorted(wanted)}"
    elif score.hands:
        if hand in ("right", "left"):
            whole = {i for i, h in score.hands.items() if h == hand}
            shared = {i for i, h in score.hands.items() if h == "both"}
            notes = [n for n in notes if n.part in whole] + _split([n for n in notes if n.part in shared], hand, split_note)
            notes.sort(key=lambda n: (n.start, n.pitch))
            used = sorted(whole | shared)
        else:
            used = sorted(score.hands)
            notes = [n for n in notes if n.part in score.hands]
        info["method"] = f"your chosen parts {used}"
    elif hand in ("right", "left"):
        keep = {p.index for p in playable}
        notes = [n for n in notes if n.part in keep]
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
            notes = _split(notes, hand, split_note)
            info["method"] = f"pitch split at {note_name(split_note)}"
    else:
        keep = {p.index for p in playable}
        if len(keep) < sum(1 for p in score.parts if p.note_count > 0):
            notes = [n for n in notes if n.part in keep]
            info["method"] = "all parts except drums"
        else:
            info["method"] = "all parts"
    if bars:
        t0, t1 = score.bar_range_times(*bars)
        notes = [n for n in notes if t0 - 1e-6 <= n.start < t1 - 1e-6]
        info["bars"] = f"{bars[0]}-{bars[1]}"
    return list(notes), info


_MELODY_WORDS = ("melody", "vocal", "voice", "vox", "lead", "sing", "solo", "tune")
# Instrument families that usually carry a tune: voices, reeds, pipes, synth leads.
_MELODY_PROGRAMS = set(range(52, 55)) | set(range(64, 88))


def _is_bass(p: Part) -> bool:
    return (p.program is not None and 32 <= p.program <= 39) or "bass" in p.name.lower()


def _melody_part(parts: list[Part]) -> tuple[Part, str] | None:
    """The part most likely to carry the tune, and why."""
    tunes = [p for p in parts if not _is_bass(p)]
    named = [p for p in tunes if any(w in p.name.lower() for w in _MELODY_WORDS)]
    if named:
        return max(named, key=lambda p: p.note_count), "named as the melody"
    leads = [p for p in tunes if p.program in _MELODY_PROGRAMS]
    if leads:
        return max(leads, key=lambda p: p.note_count), "a melody instrument"
    if tunes:
        return max(tunes, key=lambda p: p.mean_pitch), "the highest part"
    return None


def suggest_hands(score: Score) -> dict:
    """Guess which parts to play with which hand, with the reasons, for the user to confirm.

    Returns {"right": [...], "left": [...], "both": [...], "reasons": [...]}; a part in
    "both" is shared between the hands by pitch. Parts in none of the lists are left out.
    """
    out: dict = {"right": [], "left": [], "both": [], "reasons": []}
    playable = playable_parts(score)
    if not playable:
        out["reasons"].append("No playable parts (only drums or no notes).")
        return out
    pianos = [p for p in playable if p.is_piano]
    if pianos:
        sides = {p.index: _name_side(p.name) for p in pianos}
        if len(pianos) == 2 or ("right" in sides.values() and "left" in sides.values()):
            if "right" in sides.values() and "left" in sides.values():
                for p in pianos:
                    out[sides[p.index] or "both"].append(p.index)
                out["reasons"].append("Piano parts named for each hand.")
            else:
                hi, lo = sorted(pianos, key=lambda p: -p.mean_pitch)
                out["right"].append(hi.index)
                out["left"].append(lo.index)
                out["reasons"].append(f"Two piano parts: the higher ('{hi.name}') for the right hand, the lower ('{lo.name}') for the left.")
        else:
            out["both"] = [p.index for p in pianos]
            names = ", ".join(f"'{p.name}'" for p in pianos)
            out["reasons"].append(f"Piano part(s) {names}, shared between the hands by pitch.")
        others = [p for p in playable if not p.is_piano]
        if others:
            out["reasons"].append(f"Left out {len(others)} non-piano part(s).")
            tune = _melody_part(others)
            if tune:
                out["reasons"].append(f"Alternative: part {tune[0].index} '{tune[0].name}' ({tune[0].instrument}) is {tune[1]}, to play the tune instead.")
        return out

    if len(playable) == 1:
        p = playable[0]
        out["both"].append(p.index)
        out["reasons"].append(f"Only one playable part ({p.instrument}), shared between the hands by pitch.")
        return out
    busiest = max(p.note_count for p in playable)
    substantial = [p for p in playable if p.note_count >= busiest * 0.1]
    melody, why = _melody_part(substantial) or (None, "")
    basses = [p for p in substantial if _is_bass(p) and p is not melody]
    bass = max(basses, key=lambda p: p.note_count) if basses else None
    bass_why = "the bass line"
    if bass is None:
        rest = [p for p in substantial if p is not melody]
        bass = min(rest, key=lambda p: p.mean_pitch) if rest else None
        bass_why = "the lowest part"
    if melody:
        out["right"].append(melody.index)
        out["reasons"].append(f"No piano part. Right hand: part {melody.index} '{melody.name}' ({melody.instrument}), {why}.")
    if bass:
        out["left"].append(bass.index)
        out["reasons"].append(f"Left hand: part {bass.index} '{bass.name}' ({bass.instrument}), {bass_why}.")
    return out


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
