"""Load MIDI / MusicXML files into a flat, seconds-based note model.

Parts are split by MIDI track + channel, matching the visualizer's Learn Mode
track list. Bars are derived from the file's time-signature and tempo maps so
results can be reported as "bar 12, beat 3".
"""

from __future__ import annotations

import bisect
import heapq
import math
import pathlib
import re
import tempfile
from dataclasses import dataclass, field, replace

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
    hand: str | None = None  # 'right' | 'left' when Clean (playable.py) gave it to a hand other than its part's

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
    roles: dict[int, str] = field(default_factory=dict)  # confirmed part -> any of ROLES (hands, pedals, vocals)
    _bar_starts: list[float] = field(default_factory=list, repr=False)
    _played_live: bool | None = field(default=None, repr=False)
    # Set when the beat grid was recovered (regrid.py): seconds <-> beats, and how well it fit.
    beat_map: object | None = field(default=None, repr=False)
    regrid: dict | None = field(default=None, repr=False)
    _sides: dict = field(default_factory=dict, repr=False)  # split_resolver's cache
    # Set when Clean made the hands' parts playable (playable.py): what it changed.
    clean: dict | None = field(default=None, repr=False)
    playing: str | None = None  # the named part drawn and played (library.default_part, or the run's)

    def beat_of(self, t: float) -> float:
        """Beat (quarter notes from the start) at a time in seconds."""
        if self.beat_map is not None:
            return self.beat_map.beat_at(t)
        bar = self.bar_at(t)
        if bar is None or bar.end <= bar.start:
            return t * 2.0
        inside = [(when, bpm) for when, bpm in self.tempos if bar.start < when < bar.end]
        if not inside:  # one tempo through the bar: its beats are evenly spaced
            return bar.start_beat + (t - bar.start) / (bar.end - bar.start) * (bar.end_beat - bar.start_beat)
        # A tempo change inside the bar (a ritardando moving beat by beat): add up each stretch.
        beat, at, bpm = bar.start_beat, bar.start, self.bpm_at(bar.start)
        for when, value in inside:
            if when >= t:
                break
            beat += (when - at) * bpm / 60
            at, bpm = when, value
        return beat + (t - at) * bpm / 60

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
        span = max(bar.end_beat - bar.start_beat, 1e-6)
        beat = 1.0 + (self.beat_of(t) - bar.start_beat) / span * bar.numerator
        return bar.number, round(beat, 2)

    def bar(self, number: int) -> Bar:
        """The bar with this number (bar 0 is an upbeat, when the music starts with one)."""
        first = self.bars[0].number
        return self.bars[max(0, min(number - first, len(self.bars) - 1))]

    def bar_range_times(self, first: int, last: int) -> tuple[float, float]:
        start = self.bar(first)
        return start.start, self.bar(max(first, last)).end

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
    # Grace notes are ornaments: drawn on the sheet (from the file itself), not graded. music21
    # writes them as zero-length MIDI notes with the note-off first, which load_midi would read
    # as a note left sounding until the next note-off of that pitch.
    for grace in [n for n in stream.recurse().notes if n.duration.isGrace]:
        grace.activeSite.remove(grace)
    for part in stream.parts:
        _join_ties(part)
    pickup = _pickup_beats(stream)
    with tempfile.TemporaryDirectory() as tmp:
        midi_path = pathlib.Path(tmp) / "converted.mid"
        stream.write("midi", fp=str(midi_path))
        score = load_midi(midi_path)
    score.path = str(path)
    if pickup:
        _with_pickup(score, pickup)
    return score


def _pickup_beats(stream) -> float:
    """How long the upbeat is, when the first bar is shorter than its time signature (a bar 0
    in the score), else 0."""
    try:
        measures = list(stream.parts[0].getElementsByClass("Measure"))
        first = measures[0]
        ts = first.timeSignature or first.getContextByClass("TimeSignature")
        full, actual = ts.barDuration.quarterLength, first.duration.quarterLength
    except (IndexError, AttributeError):
        return 0.0
    return float(actual) if len(measures) > 1 and 0 < actual < full - 1e-6 else 0.0


def _with_pickup(score: Score, pickup: float) -> None:
    """Re-cut a score's bars for an upbeat: bar 0 is the upbeat, bar 1 starts after it (a MIDI
    file has no partial bars, so the bars read from it all start a beat or so early)."""
    old = score.bars
    if not old:
        return
    marks = [(b.start_beat, b.start) for b in old] + [(old[-1].end_beat, old[-1].end)]

    def sec_at(beat: float) -> float:
        i = max(0, min(bisect.bisect_right([m[0] for m in marks], beat) - 1, len(marks) - 2))
        (b0, t0), (b1, t1) = marks[i], marks[i + 1]
        return t0 + (beat - b0) * (t1 - t0) / max(b1 - b0, 1e-9)

    def sig_at(beat: float) -> Bar:
        return old[max(0, min(bisect.bisect_right([b.start_beat for b in old], beat + 1e-6) - 1, len(old) - 1))]

    bars = [Bar(0, 0.0, sec_at(pickup), old[0].numerator, old[0].denominator, 0.0, pickup)]
    cursor, k = pickup, 1
    end = old[-1].end_beat
    while cursor < end - 1e-6:
        sig = sig_at(cursor)
        length = sig.numerator * 4 / sig.denominator
        bars.append(Bar(k, sec_at(cursor), sec_at(cursor + length), sig.numerator, sig.denominator, cursor, cursor + length))
        cursor += length
        k += 1
    score.bars = bars
    score._bar_starts = [b.start for b in bars]


def _join_ties(part) -> None:
    """Join tied notes pitch by pitch before the MIDI conversion. music21 only follows a chord's
    own tie, so a chord that holds some notes and strikes others (a held top note over a moving
    inner voice) would re-strike the held notes and merge the struck ones."""
    from music21 import note

    for el in list(part.recurse().getElementsByClass("Chord")):
        if not any(n.tie for n in el.notes):
            continue
        site, offset = el.activeSite, el.offset
        for n in el.notes:  # one note per pitch, each keeping its own tie
            single = note.Note(n.pitch, quarterLength=el.quarterLength)
            single.tie = n.tie
            if el.volume.velocity is not None:
                single.volume.velocity = el.volume.velocity
            site.insert(offset, single)
        site.remove(el)
    held: dict[int, tuple[object, float]] = {}  # pitch -> (first note of the tied run, its end)
    for el in sorted(part.recurse().notes, key=lambda n: n.getOffsetInHierarchy(part)):
        if el.isChord:
            continue  # chords left have no ties
        kind = el.tie.type if el.tie else None
        start = float(el.getOffsetInHierarchy(part))
        head = held.get(el.pitch.midi)
        if kind in ("stop", "continue") and head and abs(head[1] - start) < 1e-6:
            head[0].quarterLength += el.quarterLength
            el.activeSite.remove(el)
            first = head[0]
        else:
            first = el
        el.tie = None
        if kind in ("start", "continue"):
            held[el.pitch.midi] = (first, start + float(el.quarterLength) if first is el else head[1] + float(el.quarterLength))
        else:
            held.pop(el.pitch.midi, None)


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


# What a part of a file is: played by a hand (or shared between them by register), played
# with the feet on bass pedals, or the sung line (shown and heard, never graded).
HAND_ROLES = ("right", "left", "both")
OTHER_ROLES = ("pedals", "vocals")
ROLES = HAND_ROLES + OTHER_ROLES
_SUNG = re.compile(r"\b(vocal|voice|vox|sing)", re.I)  # a part named as the sung line


def is_named(role: str | None) -> bool:
    """A part the user named for what they play it on ('flute'): any role but a hand, the
    pedals or the vocals (nor a hand plus the pedals, 'right+pedals'). Playing it makes every
    other part of the file the backing."""
    return bool(role) and role.partition("+")[0] not in ROLES


def named_roles(score: Score) -> list[str]:
    """The named parts saved for a score, in part order."""
    return list(dict.fromkeys(r for _, r in sorted(score.roles.items()) if is_named(r)))


def find_part(score: Score, name: str) -> list[Part]:
    """The parts that could be the one called `name` ('flute'): those whose track name has
    the word, else those whose General MIDI instrument does. One match is the part; none or
    several, and the user is asked."""
    word = re.compile(rf"\b{re.escape(name.strip().rstrip('sS') or name)}", re.I)  # 'strings' finds 'String Ensemble'
    parts = [p for p in score.parts if p.note_count and not p.drums]
    return [p for p in parts if word.search(p.name)] or [p for p in parts if p.program is not None and word.search(GM_PROGRAMS[p.program])]


def playable_parts(score: Score) -> list[Part]:
    """Parts that could be played on a keyboard: they have notes and aren't drums."""
    return [p for p in score.parts if p.note_count > 0 and not p.drums]


CHORD_GAP = 0.035  # seconds: notes starting this close together are one chord
HAND_REACH = 14  # semitones one hand spans (a ninth), counting the keys it is still holding
HOLD_WINDOW = 4.0  # seconds: a key held longer than this is taken to be ringing on the pedal, not blocking the hand
CROSS_COST = 2.0  # per note on the far side of split_note: a note crosses only when it's clearly the other hand's
BEAM = 32  # ways of splitting the piece so far kept open, so a later chord can revise an earlier one
LINE_COST = 8.0  # passing a line of single notes (steps and small leaps) from one hand to the other
LINE_STEP = 4  # semitones: single notes this close, one after another, are one line...
LINE_GAP = 0.6  # seconds: ...when they follow this closely


def split_hands(notes: list[Note], split_note: int = 60) -> dict[tuple[float, int], str]:
    """Divide the notes of one part between the hands: split_by_reach, steered by the trained
    hand model (hand_model.py) when it's installed. The model reads the hands from the music
    but knows nothing of how far a hand reaches or how fast it can jump; the search keeps the
    hands playable and weighs the model's view of every note against that. Where the model has
    the hands the wrong way round (its right hand below its left over GUARD_NOTES notes, now
    and then a whole piece), it isn't listened to. Lines are kept in one hand either way
    (keep_lines_together). split_note only matters without the model.

    Returns {(start rounded to 4 places, pitch): 'right' | 'left'}."""
    from . import hand_model

    odds = hand_model.left_odds(notes)
    if odds is not None:
        ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
        for i in range(0, len(ordered), GUARD_NOTES):
            keys = [(round(n.start, 4), n.pitch) for n in ordered[i:i + GUARD_NOTES]]
            right = [k[1] for k in keys if odds[k] <= 0.5]
            left = [k[1] for k in keys if odds[k] > 0.5]
            if right and left and sum(right) / len(right) < sum(left) / len(left):
                odds.update((k, 0.5) for k in keys)
    return keep_lines_together(notes, split_by_reach(notes, split_note, odds))


GUARD_NOTES = 100  # stretch of notes in which the model's hands are checked for being the wrong way round
MODEL_WEIGHT = 4.0  # cost per unit of surprise (-log chance) of putting a note in a hand the model doesn't expect


def keep_lines_together(notes: list[Note], sides: dict[tuple[float, int], str]) -> dict[tuple[float, int], str]:
    """A line of single notes - each a step or small leap (LINE_STEP) after the last, within
    LINE_GAP - is played by one hand, not passed back and forth between the staves: a trill,
    a tremolo, a rolled third. A line that fits in one hand (HAND_REACH) goes to the hand that
    plays most of it; a longer one (a run across the keyboard) only loses its one-note
    detours into the other hand."""
    at: dict[float, list[Note]] = {}
    for n in notes:
        at.setdefault(round(n.start, 2), []).append(n)
    times = sorted(at)
    runs: list[list[Note]] = []
    for a, b in zip(times, times[1:]):
        x, y = at[a], at[b]
        if len(x) == len(y) == 1 and b - a < LINE_GAP and abs(x[0].pitch - y[0].pitch) <= LINE_STEP:
            if runs and runs[-1][-1] is x[0]:
                runs[-1].append(y[0])
            else:
                runs.append([x[0], y[0]])
    out = dict(sides)
    for run in runs:
        keys = [(round(n.start, 4), n.pitch) for n in run]
        hands = [out[k] for k in keys]
        if len(set(hands)) == 1:
            continue
        if max(n.pitch for n in run) - min(n.pitch for n in run) <= HAND_REACH:
            rights = hands.count("right")
            hand = "right" if rights * 2 > len(hands) else "left" if rights * 2 < len(hands) else hands[0]
            for k in keys:
                out[k] = hand
        else:
            for i in range(1, len(keys) - 1):
                if hands[i - 1] == hands[i + 1] != hands[i]:
                    out[keys[i]] = hands[i] = hands[i - 1]
    return out


def split_by_reach(notes: list[Note], split_note: int = 60, left_odds: dict[tuple[float, int], float] | None = None) -> dict[tuple[float, int], str]:
    """Divide the notes of one part between the hands, chord by chord, the way a pianist
    would rather than at a fixed key. Each chord is cut where both hands stay within reach
    (counting keys they still hold) and nearest to where each hand has just been; split_note
    only decides close calls. So an inner line around middle C stays in one hand, and a
    bass note held under an arpeggio keeps the arpeggio out of the left hand.

    A hand's place is its outer note (the left hand's lowest, the right hand's highest: the
    bass and the tune), so an octave or a full chord in one hand costs nothing extra.

    The piece is split as a whole, not one chord at a time: the BEAM cheapest histories are
    carried forward and the cheapest at the end wins. A chord that only makes sense in light
    of what follows (a held chord the right hand's stabs turn out to play over) is still
    given to the hand that can keep it. A line of single notes stays in one hand rather than
    passing back and forth between the staves.

    left_odds, the hand model's chance that each note is the left hand's, replaces split_note:
    each note costs MODEL_WEIGHT * -log(the model's chance of the hand it's given).

    Returns {(start rounded to 4 places, pitch): 'right' | 'left'}."""
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch))
    chords: list[list[Note]] = []
    for n in ordered:
        if chords and n.start - chords[-1][0].start <= CHORD_GAP:
            chords[-1].append(n)
        else:
            chords.append([n])

    def edge(side: str, group: list[int]) -> int:
        return group[0] if side == "left" else group[-1]

    # A history: (cost, each hand's outer note smoothed, keys still down as (start, end, pitch,
    # side), the last chord as (start, pitch, side) when it was a single note, and the cut of
    # every chord so far as a linked list (k, earlier...)).
    beam = [(0.0, {"left": split_note - 12.0, "right": split_note + 7.0}, (), None, None)]
    for chord in chords:
        t = chord[0].start
        pitches = sorted({n.pitch for n in chord})
        if left_odds is None:
            surprise = None
        else:  # per pitch: (cost in the left hand, cost in the right hand)
            odds = {n.pitch: min(0.99, max(0.01, left_odds.get((round(n.start, 4), n.pitch), 0.5))) for n in chord}
            surprise = {p: (-MODEL_WEIGHT * math.log(o), -MODEL_WEIGHT * math.log(1 - o)) for p, o in odds.items()}
        options: dict[tuple, tuple] = {}
        for so_far, pos, held, line, trail in beam:
            held = tuple(h for h in held if h[1] > t + CHORD_GAP and t - h[0] < HOLD_WINDOW)
            holding = {s: [p for _, _, p, hs in held if hs == s] for s in pos}
            for k in range(len(pitches) + 1):
                total = so_far
                moved = dict(pos)
                for side, group in (("left", pitches[:k]), ("right", pitches[k:])):
                    if not group:
                        continue
                    reach = group + holding[side]
                    total += 10 * max(0, max(reach) - min(reach) - HAND_REACH)
                    total += abs(edge(side, group) - pos[side])
                    if surprise is None:
                        total += CROSS_COST * sum((p >= split_note) != (side == "right") for p in group)
                    else:
                        total += sum(surprise[p][side == "right"] for p in group)
                    moved[side] = (pos[side] + edge(side, group)) / 2
                if k and holding["right"] and pitches[k - 1] > min(holding["right"]):
                    total += 10  # the left hand would cross over a key the right hand holds
                if k < len(pitches) and holding["left"] and pitches[k] < max(holding["left"]):
                    total += 10
                single = (t, pitches[0], "left" if k else "right") if len(pitches) == 1 else None
                if single and line and t - line[0] <= LINE_GAP and abs(pitches[0] - line[1]) <= LINE_STEP and single[2] != line[2]:
                    total += LINE_COST  # the line would hop to the other staff
                down = held + tuple((n.start, n.end, n.pitch, "left" if n.pitch in pitches[:k] else "right") for n in chord)
                # Histories that leave the hands in the same place holding the same keys play on
                # alike: keep only the cheaper, so the beam holds different ideas, not copies.
                state = (round(moved["left"]), round(moved["right"]), tuple(sorted((p, s) for _, _, p, s in down)), single and single[2])
                if state not in options or total < options[state][0]:
                    options[state] = (total, moved, down, single, (k, trail))
        beam = heapq.nsmallest(BEAM, options.values(), key=lambda h: h[0])

    cuts: list[int] = []
    trail = min(beam, key=lambda h: h[0])[4] if chords else None
    while trail is not None:
        k, trail = trail
        cuts.append(k)
    sides: dict[tuple[float, int], str] = {}
    for chord, k in zip(chords, reversed(cuts)):
        low = set(sorted({n.pitch for n in chord})[:k])
        for n in chord:
            sides[(round(n.start, 4), n.pitch)] = "left" if n.pitch in low else "right"
    return sides


def split_resolver(score: Score, parts: set[int], split_note: int = 60):
    """Note -> 'right' | 'left' for the notes of parts the hands share. The split is worked
    out over the whole piece, so one hand, a bar range and the sheet all agree. It is kept
    on the Score and in <home>/derived (a long piece takes the hand model a while)."""
    from . import hand_model

    key = (frozenset(parts), split_note, hand_model.splitter())
    sides = score._sides.get(key)
    if sides is None:
        sides = score._sides[key] = _cached_split(score, parts, split_note)
    return lambda n: sides.get((round(n.start, 4), n.pitch)) or ("right" if n.pitch >= split_note else "left")


SPLIT_VERSION = 5  # bump when split_hands changes, so cached splits are worked out again


def _cached_split(score: Score, parts: set[int], split_note: int) -> dict[tuple[float, int], str]:
    import json

    from . import hand_model, library

    notes = as_played(score, [n for n in score.notes if n.part in parts])
    if not score.path or not pathlib.Path(score.path).is_file():
        return split_hands(notes, split_note)
    try:
        extra = f"hands-v{SPLIT_VERSION}|{hand_model.splitter()}|{sorted(parts)}|{split_note}|{sorted(octave_up_parts(score))}"
        cache = library.derived_path(score.path, "hands.json", extra)
    except OSError:
        return split_hands(notes, split_note)
    try:
        return {(start, pitch): side for start, pitch, side in json.loads(cache.read_text(encoding="utf-8"))}
    except (OSError, ValueError, TypeError):
        pass
    sides = split_hands(notes, split_note)
    try:
        cache.write_text(json.dumps([[start, pitch, side] for (start, pitch), side in sides.items()]), encoding="utf-8")
    except OSError:
        pass
    return sides


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
    base, plus, extra = hand.partition("+")
    if not parts and is_named(base) and not plus:
        return _select_named(score, base, bars)
    if not parts and (base in OTHER_ROLES or plus):
        return _select_role(score, hand, base, extra, bars, split_note)
    if score.clean and not parts and hand in ("right", "left"):
        # Clean handed some notes to the other hand, so a note's hand isn't always its part's.
        from .analysis import side_resolver

        notes, info = select_notes(score, "both", bars=bars, split_note=split_note)
        side = side_resolver(score, split_note)
        return [n for n in notes if side(n) == hand], {**info, "hand": hand}
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
    notes = as_played(score, notes)
    raised = sorted(octave_up_parts(score) & {n.part for n in notes})
    if raised:
        info["octave_up"] = raised
    return notes, info


def _select_role(score: Score, hand: str, base: str, extra: str, bars: tuple[int, int] | None, split_note: int) -> tuple[list[Note], dict]:
    """select_notes for 'pedals' / 'vocals', or a hand plus the pedals ('right+pedals')."""
    role = base if base in OTHER_ROLES else extra
    if role not in OTHER_ROLES or (extra and base not in ("both", "right", "left")):
        raise ValueError(f"hand must be 'both', 'right', 'left', 'pedals', 'vocals' or a hand plus '+pedals', not {hand!r}.")
    own = sorted(i for i, r in effective_roles(score).items() if r == role)
    notes = as_played(score, [n for n in score.notes if n.part in set(own)])
    info: dict = {"hand": hand, "method": f"{role} parts {own}"}
    if extra:
        hands_notes, hands_info = select_notes(score, base, split_note=split_note)
        notes = sorted(hands_notes + notes, key=lambda n: (n.start, n.pitch))
        info["method"] = f"{hands_info['method']} + {role} parts {own}"
    if bars:
        t0, t1 = score.bar_range_times(*bars)
        notes = [n for n in notes if t0 - 1e-6 <= n.start < t1 - 1e-6]
        info["bars"] = f"{bars[0]}-{bars[1]}"
    raised = sorted(octave_up_parts(score) & {n.part for n in notes})
    if raised:
        info["octave_up"] = raised
    return notes, info


def _select_named(score: Score, role: str, bars: tuple[int, int] | None) -> tuple[list[Note], dict]:
    """select_notes for a named part ('flute'): its notes as written, made one line (one_line)
    when the instrument sounds one note at a time (heard through the microphone)."""
    from . import instruments

    own = sorted(i for i, r in score.roles.items() if r == role)
    if not own:
        raise ValueError(f"No part called {role!r} in this piece.")
    notes = [n for n in score.notes if n.part in set(own)]
    if instruments.uses_mic():
        notes = one_line(notes)
    info: dict = {"hand": role, "method": f"{role} part {own}"}
    if bars:
        t0, t1 = score.bar_range_times(*bars)
        notes = [n for n in notes if t0 - 1e-6 <= n.start < t1 - 1e-6]
        info["bars"] = f"{bars[0]}-{bars[1]}"
    return notes, info


def one_line(notes: list[Note]) -> list[Note]:
    """A part for an instrument that sounds one note at a time: of notes starting together
    (CHORD_GAP) only the top one is kept, and a note still sounding when the next one starts
    ends there (legato played into the file), so it reads and is graded as single notes."""
    kept: list[Note] = []
    starts: list[float] = []  # when each kept note's group of notes starting together began
    for n in sorted(notes, key=lambda n: n.start):
        if kept and n.start - starts[-1] < CHORD_GAP:
            if n.pitch > kept[-1].pitch:
                kept[-1] = n
        else:
            kept.append(n)
            starts.append(n.start)
    return [replace(n, end=nxt) if nxt < n.end else n for n, nxt in zip(kept, starts[1:])] + kept[-1:]


OCTAVE_UP_BELOW = 48  # a bass part averaging below C3 is played an octave up


def octave_up_parts(score: Score) -> set[int]:
    """Bass-guitar parts, played an octave up on the keyboard: bass parts are written an
    octave above where they sound, and so a 61-key keyboard (lowest note C2) reaches them.
    Parts the file already has in that range stay where they are."""
    return {p.index for p in score.parts
            if not p.drums and not _is_keyboard(p) and _is_bass(p) and p.note_count and p.mean_pitch < OCTAVE_UP_BELOW}


def as_played(score: Score, notes: list[Note]) -> list[Note]:
    """The notes as the user plays them: bass-guitar parts an octave up (octave_up_parts)."""
    up = octave_up_parts(score)
    return [replace(n, pitch=n.pitch + 12) if n.part in up else n for n in notes] if up else list(notes)


_MELODY_WORDS = ("melody", "vocal", "voice", "vox", "lead", "sing", "solo", "tune")
# Instrument families that usually carry a tune: voices, reeds, pipes, synth leads.
_MELODY_PROGRAMS = set(range(52, 55)) | set(range(64, 88))


def _is_bass(p: Part) -> bool:
    return not p.drums and ((p.program is not None and 32 <= p.program <= 39) or "bass" in p.name.lower())


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


# Every keyboard a band's keyboard player might cover, for keyboard_parts: pianos and organs,
# synth strings and brass, synth leads and pads. Not the leads that stand in for a voice (85)
# or a guitar (84, 87).
_SYNTH_PROGRAMS = {50, 51, 62, 63} | set(range(80, 96)) - {84, 85, 87}
_DRUM_NAME = re.compile(r"\b(drums?|snare|toms?|cym\w*|hi.?hats?|kick|rototoms?)\b")
_VOICE_NAME = re.compile(r"voice|vocal|vox|choir|sing")
_KEYBOARD_NAME = re.compile(r"piano|organ|synth|keys|keyboard|rhodes|wurli|moog|clav|mellotron|hammond|harpsi|\be\.?p\b")
_OTHER_NAME = re.compile(r"guit|gtr|bass|sax|oboe|flute|trumpet|horn|violin|viola|cello|strings")
MIN_KEYBOARD_NOTES = 16  # fewer than this isn't a part worth practicing


def keyboard_parts(score: Score) -> list[dict[int, str]]:
    """Every keyboard part of a band file a keyboard player would learn, busiest first, each as
    {part index: 'right' | 'left' | 'both'}: pianos, organs and synths, by track name first and
    then by instrument. Tracks that are one keyboard split up (a right and a left hand, or the
    notes of one chord on two channels) come as one part; a line one hand plays, above or below
    middle C, goes to that hand, not split between two. Drums, voices, bass and parts that
    only double a bigger keyboard part are left out. Wider than the hand suggestion, which only
    looks for the part a pianist's two hands would take."""
    found = []
    for p in score.parts:
        name = p.name.lower()
        if p.drums or _is_bass(p) or p.note_count < MIN_KEYBOARD_NOTES or _DRUM_NAME.search(name) or _VOICE_NAME.search(name):
            continue
        if _KEYBOARD_NAME.search(name):
            found.append(p)
        elif not _OTHER_NAME.search(name) and (_is_keyboard(p) or p.program in _SYNTH_PROGRAMS):
            found.append(p)
    doubles = _doublings(score, found)
    found = [p for p in found if p.index not in doubles]

    def family(p: Part) -> int:
        return 0 if p.is_piano else p.program // 8

    groups: list[dict[int, str]] = []
    taken: set[int] = set()
    for p in sorted(found, key=lambda p: (-p.note_count, p.index)):
        if p.index in taken:
            continue
        group = {p.index: "both"}
        taken.add(p.index)
        for q in found:
            if q.index in taken or family(q) != family(p):
                continue
            if len(group) == 1 and _hand_pair(score, p, q):
                hi, lo = sorted((p, q), key=lambda x: -x.mean_pitch)
                group = {hi.index: "right", lo.index: "left"}
                taken.add(q.index)
            elif _same_rhythm(score, q, p):  # the other notes of its chords
                group[q.index] = "both"
                taken.add(q.index)
        if len(group) == 1 and not _two_handed(score, p):  # a line for one hand, on its side of middle C
            if _share_below(score, p, 60) <= 1 - ONE_HANDED:
                group = {p.index: "right"}
            elif _share_below(score, p, 60 + 8) >= ONE_HANDED:
                group = {p.index: "left"}
        groups.append(group)
    return groups


def _same_rhythm(score: Score, small: Part, big: Part) -> bool:
    """Nearly every note of `small` starts with a note of `big`, at any pitch."""
    starts = sorted(n.start for n in _part_notes(score, big))
    mine = _part_notes(score, small)
    hit = 0
    for n in mine:
        k = bisect.bisect_left(starts, n.start - CHORD_GAP)
        hit += k < len(starts) and starts[k] <= n.start + CHORD_GAP
    return hit >= DOUBLING * len(mine)


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
    return (all(p.is_piano and not _is_pedals(p) and not _is_sung(p) for p in playable) and len(playable) <= 2
            and len(playable) == sum(1 for p in score.parts if p.note_count))


def effective_hands(score: Score) -> dict[int, str]:
    """Part -> 'right' | 'left' | 'both' for the parts the user plays: their confirmed
    choice, else the suggestion for a band arrangement (so the sheet music and the grading
    agree before anyone confirms). Empty for a plain piano file: every note counts."""
    if score.hands or any(is_named(r) for r in score.roles.values()):
        return score.hands
    if is_plain_piano(score):
        return {}
    guess = suggest_hands(score)
    return {i: h for h in ("right", "left", "both") for i in guess[h]}


def effective_roles(score: Score) -> dict[int, str]:
    """Part -> role (ROLES) for every part that has one: the user's confirmed choice, else the
    suggested hands plus any part named as a vocal line or as pedals. Parts left out play no
    role (drums, doublings, other instruments)."""
    if score.roles:
        return score.roles
    guess = suggest_hands(score)
    roles = {i: h for h in HAND_ROLES for i in guess[h]}
    for p in playable_parts(score):
        if p.index in roles:
            continue
        if _is_pedals(p):
            roles[p.index] = "pedals"
        elif _is_sung(p) or "melody" in p.name.lower():
            roles[p.index] = "vocals"
    return roles


def _is_pedals(p: Part) -> bool:
    """A part named for the organ's pedalboard (played with the feet)."""
    return "pedal" in p.name.lower()


def _is_sung(p: Part) -> bool:
    """A part named as the vocal line (a song lesson's Vocals staff loads as a piano part)."""
    return bool(_SUNG.search(p.name))


def suggest_hands(score: Score) -> dict:
    """Guess which parts to play with which hand, with the reasons, for the user to confirm.

    Returns {"right": [...], "left": [...], "both": [...], "reasons": [...]}; a part in
    "both" is shared between the hands by pitch. Parts in none of the lists are left out.
    """
    out = _suggest_hands(score)
    for i in sorted(octave_up_parts(score) & set(out["right"] + out["left"] + out["both"])):
        out["reasons"].append(f"Part {i} '{score.parts[i].name}' is played an octave up, as bass parts are written "
                              "(it also keeps it on a 61-key keyboard).")
    return out


def _suggest_hands(score: Score) -> dict:
    out: dict = {"right": [], "left": [], "both": [], "reasons": []}
    playable = playable_parts(score)
    feet = [p for p in playable if _is_pedals(p)]
    if feet:
        playable = [p for p in playable if p not in feet]
        out["reasons"].append("Played with the feet, not the hands: " + ", ".join(f"part {p.index} '{p.name}'" for p in feet) + ".")
    if not playable:
        out["reasons"].append("No playable parts (only drums or no notes).")
        return out
    keys = [p for p in playable if _is_keyboard(p) and not _is_sung(p)]
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
