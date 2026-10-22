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
GRID_TOL = 0.025  # quarter notes: how far from a 16th / triplet-8th a note may start and still count as on the grid
LIVE_GRID_FIT = 0.7  # below this share of notes on the grid, a file was played live

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
    _played_live: bool | None = field(default=None, repr=False)
    # Set when the beat grid was recovered (regrid.py): seconds <-> beats, and how well it fit.
    beat_map: object | None = field(default=None, repr=False)
    regrid: dict | None = field(default=None, repr=False)
    _sides: dict = field(default_factory=dict, repr=False)  # split_resolver's cache

    def beat_of(self, t: float) -> float:
        """Beat (quarter notes from the start) at a time in seconds."""
        if self.beat_map is not None:
            return self.beat_map.beat_at(t)
        bar = self.bar_at(t)
        if bar is None or bar.end <= bar.start:
            return t * 2.0
        return bar.start_beat + (t - bar.start) / (bar.end - bar.start) * (bar.end_beat - bar.start_beat)

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

    def grid_fit(self) -> float:
        """Share of notes starting on a 16th or triplet-8th of the file's own beat. Files
        written in a sequencer or notation program are ~1.0; a performance recorded live,
        whose beats don't line up with the file's bar lines, scores far lower."""
        if not self.notes:
            return 1.0
        on_grid = sum(1 for n in self.notes if any(abs(n.beat * d - round(n.beat * d)) <= GRID_TOL * d for d in (4, 3)))
        return on_grid / len(self.notes)

    @property
    def played_live(self) -> bool:
        """No reliable beat grid: bar numbers, the metronome and sheet music would be wrong."""
        if self._played_live is None:
            self._played_live = len(self.notes) >= 50 and self.grid_fit() < LIVE_GRID_FIT
        return self._played_live

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


def _tolerate_bad_meta() -> None:
    """Keep a damaged meta event (a key signature with mode 255, an SMPTE offset with an
    unknown frame rate...) as an unknown one instead of rejecting the whole file. Nothing
    here reads those events; tempo and time signature still decode normally."""
    from mido.midifiles import meta, midifiles

    original = meta.build_meta_message
    if getattr(midifiles.build_meta_message, "tolerant", False):
        return

    def build(meta_type, data, delta=0):
        try:
            return original(meta_type, data, delta)
        except Exception:  # KeySignatureError, KeyError, IndexError...: any undecodable meta event
            return meta.UnknownMetaMessage(meta_type, data, time=delta)

    build.tolerant = True
    midifiles.build_meta_message = build


_tolerate_bad_meta()


def load_midi(path: str | pathlib.Path) -> Score:
    try:
        mid = mido.MidiFile(str(path))
    except (OSError, ValueError, EOFError, KeyError, IndexError):
        # Files from MIDI sites are sometimes slightly malformed (e.g. a data byte over
        # 127); the lenient reader clips such values instead of giving up.
        mid = mido.MidiFile(str(path), clip=True)
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


CHORD_GAP = 0.035  # seconds: notes starting this close together are one chord
HAND_REACH = 14  # semitones one hand spans (a ninth), counting the keys it is still holding
HOLD_WINDOW = 4.0  # seconds: a key held longer than this is taken to be ringing on the pedal, not blocking the hand
CROSS_COST = 2.0  # per note on the far side of split_note: a note crosses only when it's clearly the other hand's


def split_hands(notes: list[Note], split_note: int = 60) -> dict[tuple[float, int], str]:
    """Divide the notes of one part between the hands, chord by chord, the way a pianist
    would rather than at a fixed key. Each chord is cut where both hands stay within reach
    (counting keys they still hold) and nearest to where each hand has just been; split_note
    only decides close calls. So an inner line around middle C stays in one hand, and a
    bass note held under an arpeggio keeps the arpeggio out of the left hand.

    A hand's place is its outer note (the left hand's lowest, the right hand's highest: the
    bass and the tune), so an octave or a full chord in one hand costs nothing extra.

    Returns {(start rounded to 4 places, pitch): 'right' | 'left'}."""
    sides: dict[tuple[float, int], str] = {}
    pos = {"left": split_note - 12.0, "right": split_note + 7.0}  # each hand's outer note, smoothed

    def edge(side: str, group: list[int]) -> int:
        return group[0] if side == "left" else group[-1]

    held: list[tuple[float, float, int, str]] = []  # (start, end, pitch, side) of keys still down
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    i = 0
    while i < len(ordered):
        t = ordered[i].start
        j = i
        while j < len(ordered) and ordered[j].start - t <= CHORD_GAP:
            j += 1
        chord, i = ordered[i:j], j
        held = [h for h in held if h[1] > t + CHORD_GAP and t - h[0] < HOLD_WINDOW]
        holding = {s: [p for _, _, p, hs in held if hs == s] for s in pos}
        pitches = sorted({n.pitch for n in chord})

        def cost(k: int) -> float:
            total = 0.0
            for side, group in (("left", pitches[:k]), ("right", pitches[k:])):
                if not group:
                    continue
                reach = group + holding[side]
                total += 10 * max(0, max(reach) - min(reach) - HAND_REACH)
                total += abs(edge(side, group) - pos[side])
                total += CROSS_COST * sum((p >= split_note) != (side == "right") for p in group)
            if k and holding["right"] and pitches[k - 1] > min(holding["right"]):
                total += 10  # the left hand would cross over a key the right hand holds
            if k < len(pitches) and holding["left"] and pitches[k] < max(holding["left"]):
                total += 10
            return total

        k = min(range(len(pitches) + 1), key=cost)
        for side, group in (("left", pitches[:k]), ("right", pitches[k:])):
            if group:
                pos[side] = (pos[side] + edge(side, group)) / 2
        for n in chord:
            side = "left" if n.pitch in pitches[:k] else "right"
            sides[(round(n.start, 4), n.pitch)] = side
            held.append((n.start, n.end, n.pitch, side))
    return sides


def split_resolver(score: Score, parts: set[int], split_note: int = 60):
    """Note -> 'right' | 'left' for the notes of parts the hands share. The split is worked
    out over the whole piece, so one hand, a bar range and the sheet all agree."""
    key = (frozenset(parts), split_note)
    sides = score._sides.get(key)
    if sides is None:
        sides = score._sides[key] = split_hands([n for n in score.notes if n.part in parts], split_note)
    return lambda n: sides.get((round(n.start, 4), n.pitch)) or ("right" if n.pitch >= split_note else "left")


def _split(score: Score, notes: list[Note], hand: str, split_note: int, parts: set[int]) -> list[Note]:
    side = split_resolver(score, parts, split_note)
    return [n for n in notes if side(n) == hand]


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
    hands = effective_hands(score)
    if parts:
        wanted = set(parts)
        notes = [n for n in notes if n.part in wanted]
        info["method"] = f"parts {sorted(wanted)}"
    elif hands:
        if hand in ("right", "left"):
            whole = {i for i, h in hands.items() if h == hand}
            shared = {i for i, h in hands.items() if h == "both"}
            notes = [n for n in notes if n.part in whole] + _split(score, [n for n in notes if n.part in shared], hand, split_note, shared)
            notes.sort(key=lambda n: (n.start, n.pitch))
            used = sorted(whole | shared)
        else:
            used = sorted(hands)
            notes = [n for n in notes if n.part in hands]
        info["method"] = f"your chosen parts {used}" if score.hands else f"suggested parts {used} (not confirmed yet)"
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
            notes = _split(score, notes, hand, split_note, keep)
            info["method"] = f"split between the hands by register (around {note_name(split_note)})"
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


_ORGANS = range(16, 21)  # drawbar, percussive, rock, church and reed organ: keyboard parts too
DOUBLING = 0.8  # share of a part's notes also in a bigger part (same pitch or an octave away) for it to be a doubling
MINOR_PART = 0.15  # a keyboard part with fewer notes than this share of the main one is fills, not a hand
ONE_HANDED = 0.9  # share of a part's notes above middle C for it to be a right-hand-only part


def _is_keyboard(p: Part) -> bool:
    return p.is_piano or (p.program is not None and p.program in _ORGANS)


def _part_notes(score: Score, p: Part) -> list[Note]:
    return [n for n in score.notes if n.part == p.index]


def _share_below(score: Score, p: Part, split_note: int) -> float:
    notes = _part_notes(score, p)
    return sum(n.pitch < split_note for n in notes) / max(1, len(notes))


def _doublings(score: Score, parts: list[Part]) -> dict[int, int]:
    """Parts that only double another, note for note or an octave apart, as band files often
    do to thicken a sound: {doubling part: part it doubles}. Of two equal parts the one
    a piano, else nearer the middle of the keyboard, is kept."""
    starts: dict[int, dict[int, list[float]]] = {}  # part -> pitch -> sorted start times
    for p in parts:
        by_pitch = starts[p.index] = {}
        for n in _part_notes(score, p):
            by_pitch.setdefault(n.pitch, []).append(n.start)
        for times in by_pitch.values():
            times.sort()

    def found(times: list[float] | None, t: float) -> bool:  # a note within CHORD_GAP of t
        if not times:
            return False
        k = bisect.bisect_left(times, t - CHORD_GAP)
        return k < len(times) and times[k] <= t + CHORD_GAP

    order = sorted(parts, key=lambda p: (-p.note_count, not p.is_piano, abs(p.mean_pitch - 67), p.index))
    out: dict[int, int] = {}
    for i, small in enumerate(order):
        mine = _part_notes(score, small)
        for big in order[:i]:
            theirs = starts[big.index]
            if big.index not in out and any(sum(found(theirs.get(n.pitch + d), n.start) for n in mine) >= DOUBLING * len(mine) for d in (0, 12, -12)):
                out[small.index] = big.index
                break
    return out


def _two_handed(score: Score, p: Part) -> bool:
    """A part that needs both hands: more than 5% of its chords span over a tenth."""
    chords: dict[float, list[int]] = {}
    for n in _part_notes(score, p):
        chords.setdefault(round(n.start / CHORD_GAP), []).append(n.pitch)
    wide = sum(max(ps) - min(ps) > HAND_REACH + 2 for ps in chords.values())
    return wide > 0.05 * max(1, len(chords))


def _bass_partner(score: Score, main: Part, parts: list[Part], split_note: int = 60) -> Part | None:
    """A substantial keyboard part in the bass, playing alongside the main one (a boogie left
    hand on its own track, say): the left hand plays it as well."""
    for p in sorted(parts, key=lambda p: -p.note_count):
        if p is main or p.note_count < MINOR_PART * main.note_count or _share_below(score, p, split_note) < ONE_HANDED:
            continue
        bars_main = {score.position(n.start)[0] for n in _part_notes(score, main)}
        bars_p = {score.position(n.start)[0] for n in _part_notes(score, p)}
        if len(bars_main & bars_p) >= 0.5 * len(bars_p):
            return p
    return None


def _hand_pair(score: Score, a: Part, b: Part, split_note: int = 60) -> bool:
    """Two keyboard parts that are one player's two hands: both substantial, neither needing
    two hands itself, the higher one above middle C and the lower below it (90% of their
    notes), playing in the same bars. (Parts that overlap are two keyboards, a piano and its
    melody, or a full piano part and an extra bass track.)"""
    if min(a.note_count, b.note_count) < MINOR_PART * max(a.note_count, b.note_count):
        return False
    if _two_handed(score, a) or _two_handed(score, b):
        return False
    hi, lo = sorted((a, b), key=lambda p: -p.mean_pitch)
    if _share_below(score, hi, split_note) > 1 - ONE_HANDED or _share_below(score, lo, split_note + 8) < ONE_HANDED:
        return False  # each mostly on its own side of middle C (the left hand may reach up to G4)
    bars_hi = {score.position(n.start)[0] for n in _part_notes(score, hi)}
    bars_lo = {score.position(n.start)[0] for n in _part_notes(score, lo)}
    return len(bars_hi & bars_lo) >= 0.5 * min(len(bars_hi), len(bars_lo))


def is_plain_piano(score: Score) -> bool:
    """One or two piano parts and nothing else: no part choice to make."""
    playable = playable_parts(score)
    return all(p.is_piano for p in playable) and len(playable) <= 2 and len(playable) == sum(1 for p in score.parts if p.note_count)


def effective_hands(score: Score) -> dict[int, str]:
    """Part -> 'right' | 'left' | 'both' for the parts the user plays: their confirmed
    choice, else the suggestion for a band arrangement (so the sheet music and the grading
    agree before anyone confirms). Empty for a plain piano file: every note counts."""
    if score.hands:
        return score.hands
    if is_plain_piano(score):
        return {}
    guess = suggest_hands(score)
    return {i: h for h in ("right", "left", "both") for i in guess[h]}


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
    keys = [p for p in playable if _is_keyboard(p)]
    if keys:
        doubled = _doublings(score, keys)
        for i, j in doubled.items():
            out["reasons"].append(f"Part {i} '{score.parts[i].name}' only doubles part {j}: left out.")
        keys = [p for p in keys if p.index not in doubled]
        sides = {p.index: _name_side(p.name) for p in keys}
        if "right" in sides.values() and "left" in sides.values():
            for p in keys:
                out[sides[p.index] or "both"].append(p.index)
            out["reasons"].append("Keyboard parts named for each hand.")
        else:
            main = max(keys, key=lambda p: p.note_count)
            partner = next((p for p in sorted(keys, key=lambda p: -p.note_count) if p is not main and _hand_pair(score, main, p)), None)
            basses = [p for p in playable if _is_bass(p) and not _is_keyboard(p)]
            if partner:
                hi, lo = sorted((main, partner), key=lambda p: -p.mean_pitch)
                out["right"].append(hi.index)
                out["left"].append(lo.index)
                out["reasons"].append(f"Two {hi.instrument.lower()} parts that are a player's two hands: part {hi.index} '{hi.name}' (higher) "
                                      f"for the right, part {lo.index} '{lo.name}' for the left.")
            elif _share_below(score, main, 60) < 1 - ONE_HANDED and basses:
                # A keyboard part in the treble only leaves the left hand idle: give it the bass line.
                bass = max(basses, key=lambda p: p.note_count)
                out["right"].append(main.index)
                out["left"].append(bass.index)
                out["reasons"].append(f"Right hand: the {main.instrument.lower()} part '{main.name}', which stays above middle C. "
                                      f"Left hand: part {bass.index} '{bass.name}' ({bass.instrument}), the bass line.")
            else:
                out["both"].append(main.index)
                out["reasons"].append(f"The {main.instrument.lower()} part '{main.name}', shared between the hands by register.")
                bass_part = _bass_partner(score, main, keys)
                if bass_part:
                    out["left"].append(bass_part.index)
                    out["reasons"].append(f"Left hand also plays part {bass_part.index} '{bass_part.name}', a {bass_part.instrument.lower()} part in the bass.")
            extra = [p for p in keys if p.index not in out["right"] + out["left"] + out["both"]]
            if extra:
                names = ", ".join(f"{p.index} '{p.name}' ({p.instrument}, {p.note_count} notes)" for p in extra)
                out["reasons"].append(f"Other keyboard parts left out (a second keyboard or fills): {names}.")
        chosen = set(out["right"] + out["left"] + out["both"])
        others = [p for p in playable if not _is_keyboard(p) and p.index not in chosen]
        if others:
            out["reasons"].append(f"Left out {len(others)} non-keyboard part(s).")
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
