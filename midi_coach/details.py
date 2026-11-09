"""Sheet details: chord symbols, Roman numerals, lyrics and section names over the sheet on screen.

The coach page's Details button. Two passes, both cached per file in
<home>/derived/details/<file sha1>.json (the folder is safe to delete):

local(score)       straight away, from the file: the chord in each bar (or half bar) named from
                   the notes (harmony.py), and the karaoke lyrics when the MIDI file has them.
research(...)      on the pianist's subscription (claude_run, a few minutes): the song's published
                   chords and section names (Ultimate Guitar's best-rated chart, checked against
                   Hooktheory TheoryTab) and its lyrics (LRCLIB, else the chart's words), laid onto
                   this file's bars and tune by Claude Code. Each published chord is checked
                   against the notes: one they contradict is kept out and reported, and the
                   file's own chord stays. A word is kept only if it is in the fetched lyrics.

apply(xml, ...)    writes them into the MusicXML the page draws, without touching a note: chord
                   letters (<harmony>) over the top piano staff, Roman numerals (<harmony> with a
                   <numeral>, worked out per key signature) under the bottom one, <lyric>s on the
                   tune (the vocal staff, else the right hand's top notes), section names over the
                   first staff. Each element's id starts 'details-' so the page can show and hide
                   them (docs/notation.html).
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import pathlib
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction

from . import harmony
from .atlas import claude_run
from .library import home
from .notes import MIDI_SUFFIXES, Note, Score, effective_roles, note_name, select_notes

log = logging.getLogger("midi-coach")

VERSION = 1
MODEL = "sonnet"
RUN_TIMEOUT_SEC = 12 * 60
MIN_FIT = 0.5  # a chord named from the notes that explains less of them than this isn't printed
SPLIT_FIT = 0.6  # a second chord in a bar must explain this much of its half
CONFLICT_MARGIN = 0.25  # a published chord explaining this much less of the notes than the file's own is kept out
LYRIC_REACH = 0.35  # beats between a syllable's note and the note it lands on in the sheet
NEAR_BEATS = Fraction(1, 2)  # a chord whose beat has no note on its staff goes on a note this close
LRCLIB = "https://lrclib.net/api/search"
CHART_CHARS = 12000
LYRICS_CHARS = 8000

# Files being researched now (the page shows 'Looking up…' for them).
running: set[str] = set()
_lock = threading.Lock()


# -- chords ----------------------------------------------------------------------------------

_STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# suffix -> (MusicXML kind, intervals above the root, added degrees)
_SUFFIXES: dict[str, tuple[str, tuple[int, ...], tuple[int, ...]]] = {
    "": ("major", (0, 4, 7), ()),
    "m": ("minor", (0, 3, 7), ()),
    "5": ("power", (0, 7), ()),
    "aug": ("augmented", (0, 4, 8), ()),
    "dim": ("diminished", (0, 3, 6), ()),
    "sus4": ("suspended-fourth", (0, 5, 7), ()),
    "sus2": ("suspended-second", (0, 2, 7), ()),
    "6": ("major-sixth", (0, 4, 7, 9), ()),
    "m6": ("minor-sixth", (0, 3, 7, 9), ()),
    "7": ("dominant", (0, 4, 7, 10), ()),
    "maj7": ("major-seventh", (0, 4, 7, 11), ()),
    "m7": ("minor-seventh", (0, 3, 7, 10), ()),
    "m7b5": ("half-diminished", (0, 3, 6, 10), ()),
    "dim7": ("diminished-seventh", (0, 3, 6, 9), ()),
    "mmaj7": ("major-minor", (0, 3, 7, 11), ()),
    "7sus4": ("suspended-fourth", (0, 5, 7, 10), (7,)),
    "9": ("dominant-ninth", (0, 4, 7, 10, 2), ()),
    "maj9": ("major-ninth", (0, 4, 7, 11, 2), ()),
    "m9": ("minor-ninth", (0, 3, 7, 10, 2), ()),
    "add9": ("major", (0, 4, 7, 2), (9,)),
    "madd9": ("minor", (0, 3, 7, 2), (9,)),
    "11": ("dominant-11th", (0, 4, 7, 10, 2, 5), ()),
    "m11": ("minor-11th", (0, 3, 7, 10, 2, 5), ()),
    "13": ("dominant-13th", (0, 4, 7, 10, 2, 9), ()),
}
_ALIASES = {"maj": "", "M": "", "min": "m", "-": "m", "+": "aug", "°": "dim", "o": "dim", "sus": "sus4",
            "M7": "maj7", "Δ": "maj7", "Δ7": "maj7", "ma7": "maj7", "min7": "m7", "-7": "m7", "ø": "m7b5", "ø7": "m7b5",
            "m7(b5)": "m7b5", "°7": "dim7", "o7": "dim7", "m(maj7)": "mmaj7", "mM7": "mmaj7", "add2": "add9",
            "2": "add9", "madd2": "madd9", "7sus": "7sus4", "min6": "m6", "min9": "m9", "M9": "maj9"}
_MINORISH = {"minor", "minor-seventh", "minor-sixth", "minor-ninth", "minor-11th", "major-minor"}
_SEVENTHS = {"dominant", "major-seventh", "minor-seventh", "half-diminished", "diminished-seventh", "major-minor"}


@dataclass
class Chord:
    root: int
    step: str
    alter: int
    kind: str
    intervals: tuple[int, ...]
    added: tuple[int, ...]
    bass: int | None = None
    bass_step: str | None = None
    bass_alter: int = 0

    @property
    def tones(self) -> set[int]:
        """Its pitch classes, the bass of a slash chord included (Cm/Bb sounds a B flat)."""
        return {(self.root + i) % 12 for i in self.intervals} | ({self.bass} if self.bass is not None else set())


def _note(text: str) -> tuple[str, int] | None:
    m = re.fullmatch(r"([A-G])([b#♭♯]?)", text)
    if not m:
        return None
    return m.group(1), {"b": -1, "♭": -1, "#": 1, "♯": 1}.get(m.group(2), 0)


def parse_chord(name: str) -> Chord | None:
    """'D/F#', 'Bbmaj7', 'Asus4', 'Em7b5'... -> Chord, None for anything else (N.C. included)."""
    m = re.fullmatch(r"\s*([A-G][b#♭♯]?)([^/\s]*)(?:/([A-G][b#♭♯]?))?\s*", name or "")
    if not m:
        return None
    root = _note(m.group(1))
    suffix = m.group(2)
    suffix = _ALIASES.get(suffix, suffix)
    if suffix not in _SUFFIXES:
        suffix = _ALIASES.get(suffix.replace("(", "").replace(")", ""), suffix.replace("(", "").replace(")", ""))
    if root is None or suffix not in _SUFFIXES:
        return None
    kind, intervals, added = _SUFFIXES[suffix]
    step, alter = root
    chord = Chord((_STEPS[step] + alter) % 12, step, alter, kind, intervals, added)
    if m.group(3):
        bass = _note(m.group(3))
        if bass is None:
            return None
        chord.bass_step, chord.bass_alter = bass
        chord.bass = (_STEPS[bass[0]] + bass[1]) % 12
    return chord


def chord_name(chord: Chord) -> str:
    """The chord's name as written by parse_chord's main spelling ('F#m7', 'D/F#')."""
    acc = {-1: "b", 0: "", 1: "#"}
    bass = f"/{chord.bass_step}{acc[chord.bass_alter]}" if chord.bass_step else ""
    return f"{chord.step}{acc[chord.alter]}{_suffix(chord)}{bass}"


# -- Roman numerals --------------------------------------------------------------------------

_UPPER_MAJOR = {0: "I", 1: "♭II", 2: "II", 3: "♭III", 4: "III", 5: "IV", 6: "♯IV", 7: "V", 8: "♭VI", 9: "VI", 10: "♭VII", 11: "VII"}
_UPPER_MINOR = {0: "I", 1: "♭II", 2: "II", 3: "III", 4: "♯III", 5: "IV", 6: "♯IV", 7: "V", 8: "VI", 9: "♯VI", 10: "VII", 11: "VII"}
# The key's own triads (minor: V and vii° from the harmonic minor), for secondary dominants.
_DIATONIC_MAJOR = {0: "maj", 2: "min", 4: "min", 5: "maj", 7: "maj", 9: "min", 11: "dim"}
_DIATONIC_MINOR = {0: "min", 2: "dim", 3: "maj", 5: "min", 7: "maj", 8: "maj", 10: "maj", 11: "dim"}
_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
# Scale degree (1-7) each pitch class above the tonic is counted from, for <numeral-root>.
_DEGREE = {0: 1, 1: 2, 2: 2, 3: 3, 4: 3, 5: 4, 6: 4, 7: 5, 8: 6, 9: 6, 10: 7, 11: 7}


def _figure(chord: Chord) -> str:
    """Inversion figures ('⁶', '⁶₄', '⁷', '⁶₅', '⁴₃', '⁴₂') and other marks after the numeral."""
    above = (chord.bass - chord.root) % 12 if chord.bass is not None else 0
    if chord.kind in _SEVENTHS:
        fig = {0: "7", 3: "65", 4: "65", 6: "43", 7: "43", 8: "43"}.get(above, "42" if above in (9, 10, 11) else "7")
        return fig[0].translate(_SUP) + (fig[1].translate(_SUB) if len(fig) > 1 else "")
    if chord.kind.endswith(("ninth", "11th", "13th")):
        return {"ninth": "9", "11th": "11", "13th": "13"}[chord.kind.rsplit("-", 1)[-1]].translate(_SUP)
    tail = {"suspended-fourth": "sus4", "suspended-second": "sus2"}.get(chord.kind, "")  # a 6th is colour: the triad's numeral
    if chord.added == (9,):
        tail = "add9"
    if chord.kind == "suspended-fourth" and chord.added == (7,):
        tail = "⁷sus4"
    if above in (3, 4):
        return "⁶" + tail
    if above in (6, 7, 8):
        return "⁶₄" + tail
    return tail


def _cased(upper: str, chord: Chord) -> str:
    if chord.kind in ("diminished", "diminished-seventh"):
        return upper.lower() + "°"
    if chord.kind == "half-diminished":
        return upper.lower() + "ø"
    if chord.kind in _MINORISH:
        return upper.lower()
    return upper + ("+" if chord.kind == "augmented" else "")


# A triad over a bass that isn't one of its notes is a seventh chord, as harmony is analysed:
# the 7th in the bass (Cm/Bb = Cm7 in third inversion), or the 6th (Cm/A = Am7b5, on A).
_SEVENTH_IN_BASS = {("major", 10): "7", ("major", 11): "maj7", ("minor", 10): "m7", ("minor", 11): "mmaj7",
                    ("diminished", 10): "m7b5", ("diminished", 9): "dim7"}
_SIXTH_IN_BASS = {"major": "m7", "minor": "m7b5"}


def _as_analysed(chord: Chord) -> Chord:
    """The chord a slash chord spells for Roman numerals (see _SEVENTH_IN_BASS)."""
    if chord.bass is None or chord.added or len(chord.intervals) != 3:
        return chord
    above = (chord.bass - chord.root) % 12
    if above in chord.intervals:
        return chord
    if (chord.kind, above) in _SEVENTH_IN_BASS:
        kind, intervals, added = _SUFFIXES[_SEVENTH_IN_BASS[chord.kind, above]]
        return Chord(chord.root, chord.step, chord.alter, kind, intervals, added, chord.bass, chord.bass_step, chord.bass_alter)
    if above == 9 and chord.kind in _SIXTH_IN_BASS:
        kind, intervals, added = _SUFFIXES[_SIXTH_IN_BASS[chord.kind]]
        return Chord(chord.bass, chord.bass_step, chord.bass_alter, kind, intervals, added)
    return chord


def roman(name: str, tonic: int, minor: bool) -> str | None:
    """The chord's Roman numeral in a key: 'V⁶₅', 'ii', '♭VII', 'V⁷/IV', 'vi⁴₂' for Cm/Bb in
    E flat; None if it isn't a chord."""
    chord = parse_chord(name)
    if chord is None:
        return None
    chord = _as_analysed(chord)
    deg = (chord.root - tonic) % 12
    uppers, diatonic = (_UPPER_MINOR, _DIATONIC_MINOR) if minor else (_UPPER_MAJOR, _DIATONIC_MAJOR)
    major_like = chord.kind in ("major", "dominant", "dominant-ninth") and not chord.added
    own = diatonic.get(deg) == "maj" and chord.kind == "major" or deg == 7 and chord.kind in ("dominant", "dominant-ninth")
    target = (deg + 5) % 12
    if major_like and not own and target != 0 and diatonic.get(target) in ("maj", "min"):
        aim = uppers[target] if diatonic[target] == "maj" else uppers[target].lower()
        return "V" + _figure(chord) + "/" + aim
    upper = uppers[deg]
    if minor and deg == 11 and chord.kind not in ("diminished", "diminished-seventh", "half-diminished"):
        upper = "♯VII"
    return _cased(upper, chord) + _figure(chord)


# -- what the file shows ---------------------------------------------------------------------


def _harmony_notes(score: Score) -> list[Note]:
    """Every pitched note but the tune's: the band's bass and guitars name a chord too."""
    roles = effective_roles(score)
    drums = {p.index for p in score.parts if p.drums}
    return [n for n in score.notes if n.end > n.start and n.part not in drums and roles.get(n.part) != "vocals"]


def tune(score: Score) -> tuple[list[Note], str]:
    """The notes lyrics are sung on, and the staff they're drawn on: the vocal part when the
    file has one, else the right hand's top notes."""
    roles = set(effective_roles(score).values())
    if "vocals" in roles:
        return sorted(select_notes(score, "vocals")[0], key=lambda n: (n.beat, -n.pitch)), "vocals"
    top: dict[float, Note] = {}
    for n in select_notes(score, "right")[0]:
        at = round(n.beat, 2)
        if at not in top or n.pitch > top[at].pitch:
            top[at] = n
    return [top[k] for k in sorted(top)], "right"


def _sec(score: Score, beat: float) -> float:
    """Seconds at a beat (straight-line within its bar)."""
    starts = [b.start_beat for b in score.bars]
    bar = score.bars[max(0, bisect.bisect_right(starts, beat + 1e-9) - 1)]
    span = max(bar.end_beat - bar.start_beat, 1e-9)
    return bar.start + (beat - bar.start_beat) / span * (bar.end - bar.start)


_TRIAD_OF = {"7": "", "maj7": "", "6": "", "m7": "m", "m6": "m", "mmaj7": "m", "m7b5": "dim", "dim7": "dim"}
BASS_ROOT_MARGIN = 0.12  # the bass note's own triad wins when it explains nearly as much (Eb, not Cm7/Eb)
COLOUR_SHARE = 0.15  # a 7th or 6th with less of the sounding weight than this is colour: the triad is named


def _suffix(chord: Chord) -> str:
    return next(s for s, v in _SUFFIXES.items() if v == (chord.kind, chord.intervals, chord.added))


def lead_sheet_name(weights: list[float], bass: int | None, names: list[str]) -> tuple[str | None, float]:
    """harmony.name_chord, read the way a lead sheet names chords: on the bass note when its
    own triad explains nearly as much, and without a 7th or 6th that is only passing colour."""
    name, fit = harmony.name_chord(weights, bass, names)
    chord = parse_chord(name) if name else None
    if chord is None:
        return name, fit
    total = sum(weights)

    def share(root: int, suffix: str) -> float:
        return sum(weights[(root + i) % 12] for i in _SUFFIXES[suffix][1]) / total

    if chord.bass is not None:
        own, suffix = max((share(chord.bass, s), s) for s in ("", "m"))
        if own >= fit - BASS_ROOT_MARGIN:
            return names[chord.bass] + suffix, round(own, 2)
    suffix = _suffix(chord)
    if suffix in ("6", "m6") and chord.bass == (chord.root + 9) % 12:  # C6/A is Am7, Cm6/A is Am7b5
        renamed = "m7" if suffix == "6" else "m7b5"
        return names[chord.bass] + renamed, fit
    if suffix in _TRIAD_OF and (suffix in ("6", "m6") or weights[(chord.root + chord.intervals[3]) % 12] < COLOUR_SHARE * total):
        triad = _TRIAD_OF[suffix]
        tones = {(chord.root + i) % 12 for i in _SUFFIXES[triad][1]}
        slash = f"/{names[chord.bass]}" if chord.bass is not None and chord.bass in tones else ""
        return names[chord.root] + triad + slash, round(share(chord.root, triad), 2)
    return name, fit


def local_chords(score: Score) -> tuple[list[dict], str | None]:
    """[{beat, chord, from: 'notes', fit}] where the chord changes, and the key: one chord a
    bar, two when a bar of four or more beats clearly changes halfway (each half fits
    better than the whole bar). A chord the notes hardly explain (melody and passing notes)
    isn't printed."""
    notes = _harmony_notes(score)
    if not notes or not score.bars:
        return [], None
    key = harmony.estimate_key(notes)
    names = harmony.spelling_for(key)

    def named(t0: float, t1: float) -> tuple[str | None, float]:
        return lead_sheet_name(*harmony._profile(notes, t0, t1), names)

    out: list[dict] = []
    last = None
    for bar in score.bars:
        whole = named(bar.start, bar.end)
        segments = [(bar.start_beat, *whole)]
        if bar.numerator >= 4 and bar.numerator % 2 == 0:
            mid, mid_beat = (bar.start + bar.end) / 2, (bar.start_beat + bar.end_beat) / 2
            halves = [named(bar.start, mid), named(mid, bar.end)]
            if (halves[0][0] != halves[1][0] and all(h[0] and h[1] >= SPLIT_FIT and h[1] >= whole[1] + 0.1 for h in halves)):
                segments = [(bar.start_beat, *halves[0]), (mid_beat, *halves[1])]
        for beat, name, fit in segments:
            if not name or fit < MIN_FIT or name == last:
                continue
            out.append({"beat": round(beat, 4), "chord": name, "from": "notes", "fit": fit})
            last = name
    return out, key


def file_lyrics(score: Score) -> list[dict]:
    """The karaoke lyrics of a MIDI file, on the tune's notes: [{beat, pitch, text, syllabic}]."""
    if pathlib.Path(score.path).suffix.lower() not in MIDI_SUFFIXES:
        return []
    from .songs import midi_lyrics, place_lyrics

    words = midi_lyrics(score.path)
    if not words:
        return []
    notes, _ = tune(score)
    placed = place_lyrics(score, notes, words)
    return [{"beat": round(notes[k].beat, 4), "pitch": notes[k].pitch, "text": t, "syllabic": s}
            for k, (t, s) in sorted(placed.items())]


def title_and_artist(path: str) -> tuple[str, str | None]:
    """'Adele - Skyfall [bitmidi 3932].mid' -> ('Skyfall', 'Adele'); a song lesson's
    '(with vocals)' is dropped too."""
    stem = re.sub(r"\s*\[[^\]]*\]\s*$", "", pathlib.Path(path).stem)
    stem = re.sub(r"\s*\((with vocals|\d+)\)\s*$", "", stem, flags=re.IGNORECASE).strip()
    if " - " in stem:
        artist, song = stem.split(" - ", 1)
        return song.strip(), artist.strip()
    return stem, None


def local(score: Score) -> dict:
    """What the file itself shows, ready to draw."""
    chords, key = local_chords(score)
    words = file_lyrics(score)
    song, artist = title_and_artist(score.path)
    _, staff = tune(score)
    return {"version": VERSION, "song": song, "artist": artist, "state": "local", "key": key,
            "chords": chords, "sections": [], "lyrics": words, "lyrics_on": staff,
            "lyrics_from": "the file's karaoke lyrics" if words else None, "sources": [], "conflicts": [],
            "note": "Chords worked out from the notes" + (", lyrics from the file" if words else "") + "."}


# -- cache -----------------------------------------------------------------------------------

_digests: dict[tuple[str, int, int], str] = {}


def cache_path(file: str | pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(file)
    st = p.stat()
    memo = (str(p), st.st_size, st.st_mtime_ns)
    if memo not in _digests:
        _digests[memo] = hashlib.sha1(p.read_bytes()).hexdigest()
    folder = home() / "derived" / "details"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{_digests[memo]}.json"


def load(file: str | pathlib.Path) -> dict | None:
    try:
        data = json.loads(cache_path(file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("version") == VERSION else None


def save(file: str | pathlib.Path, data: dict) -> None:
    cache_path(file).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def stamp(file: str | pathlib.Path) -> tuple:
    """Changes whenever what the page should draw for this file changes."""
    try:
        mtime = cache_path(file).stat().st_mtime_ns
    except OSError:
        mtime = None
    return mtime, str(file) in running


def offered(file: str | pathlib.Path) -> bool:
    """Details are for songs. The Atlas's own music (scales, arpeggios, exercises, exam pieces,
    sight-reading, bridges) has no chart or lyrics to look up, so it gets none."""
    from .atlas import content_dir, shared_dir, user_dir

    p = pathlib.Path(file).resolve()
    return not any(p.is_relative_to(d.resolve()) for d in (shared_dir(), content_dir(), user_dir()))


def status(file: str | pathlib.Path) -> dict:
    """For the page: {state: none | local | researching | done | failed, has: {...}, note, sources}."""
    data = load(file)
    state = "researching" if str(file) in running else (data or {}).get("state", "none")
    if not data:
        return {"state": state, "has": {}, "note": None, "sources": []}
    has = {"chords": bool(data.get("chords")), "roman": bool(data.get("chords")),
           "lyrics": bool(data.get("lyrics")), "sections": bool(data.get("sections"))}
    return {"state": state, "has": has, "note": data.get("note"), "sources": data.get("sources") or [],
            "conflicts": (data.get("conflicts") or [])[:20]}


# -- research (subscription) -----------------------------------------------------------------

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "chords": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"bar": {"type": "integer"}, "beat": {"type": "number"}, "chord": {"type": "string"}},
            "required": ["bar", "beat", "chord"]}},
        "sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"bar": {"type": "integer"}, "name": {"type": "string"}},
            "required": ["bar", "name"]}},
        "lyrics": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"note": {"type": "integer"}, "text": {"type": "string"},
                           "syllabic": {"type": "string", "enum": ["single", "begin", "middle", "end"]}},
            "required": ["note", "text", "syllabic"]}},
        "sources": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["chords", "sections", "lyrics", "sources"],
}

SYSTEM = """You lay a song's published chords, section names and lyrics onto one arrangement of it (a MIDI or MusicXML file), for the pianist's sheet music. You get the arrangement bar by bar - each bar's number, its time signature, the chords its notes suggest (with the beat in the bar and how much of the notes each explains, 0-1) and, when lyrics are wanted, the tune's notes numbered #n with their beat in the bar and pitch - plus a published chord chart (chords over lyrics, with [Verse]/[Chorus] headers) and the lyrics, when they were found. You may check Hooktheory TheoryTab with WebFetch (https://www.hooktheory.com/theorytab/view/<artist>/<song>, lower case, words joined by hyphens) for the sections and progression.

Return:
- chords: {bar, beat, chord} wherever the chord changes (beat 1 = the bar's first beat, counted in the time signature's beat unit). Write them at this arrangement's sounding pitch: the chart is already transposed to it when a shift is given. Follow the chart's harmony, matched to where this arrangement plays each line; where the arrangement plays something else (an added intro, a solo, a key change), follow the notes. Letter names only: G, Em7, D/F#, Bbmaj7, Asus4, C7, F#m7b5, Ebdim7, Gadd9. One chord a bar unless the harmony clearly changes within it. Nothing in bars without harmony.
- sections: {bar, name} where each section starts: Intro, Verse 1, Pre-chorus, Chorus, Bridge, Solo, Outro...
- lyrics (only when the tune's notes are listed): the words sung on the tune as {note, text, syllabic}, one syllable per note, in order: note is the tune note's number, syllabic is single (a one-syllable word), or begin / middle / end for a word split over notes (beau-ti-ful). A syllable sung over several notes goes on its first note only. Use only the words of the lyrics given; repeat a chorus wherever the arrangement repeats it. Work phrase by phrase: the tune's phrases are runs of notes between rests, and each lyric line goes on the phrase whose notes match its syllables in number, stress and order. A phrase with a few more notes than syllables (melismas, ornaments) or fewer (two syllables on a repeated note) is normal in a transcribed vocal line, not a reason to give up: place the line and leave the extra notes empty. Leave out only a line whose phrase you can't find, and leave lyrics empty only when the tune doesn't follow the words at all (an instrumental).
- sources: the URLs you used.
- note: one sentence on what you couldn't match, if anything.
Never invent a chord or a word: every chord comes from the chart, TheoryTab or the notes, every word from the lyrics given."""


def _get_json(url: str):
    from . import web

    code, _, body = web._get(url, {"User-Agent": "midi-coach piano practice app", "Accept": "application/json"})
    if not 200 <= code < 300:
        raise web.WebError(code, f"{urllib.parse.urlparse(url).netloc} answered {code}")
    return json.loads(body)


def fetch_lyrics(song: str, artist: str | None, get=_get_json) -> dict | None:
    """{text, url} from LRCLIB (an open lyrics database), or None."""
    params = {"track_name": song, **({"artist_name": artist} if artist else {})}
    try:
        found = get(f"{LRCLIB}?{urllib.parse.urlencode(params)}")
    except Exception as exc:  # noqa: BLE001 - offline or no answer: no lyrics from here
        log.info("details: LRCLIB lookup failed: %s", exc)
        return None
    for hit in found if isinstance(found, list) else []:
        if hit.get("plainLyrics") and not hit.get("instrumental"):
            return {"text": hit["plainLyrics"][:LYRICS_CHARS], "url": f"https://lrclib.net/api/get/{hit.get('id')}"}
    return None


def _same_song(a: str, b: str) -> bool:
    simple = lambda s: re.sub(r"[^a-z0-9]+", "", re.sub(r"\(.*?\)", "", s.lower()))  # noqa: E731
    return simple(a) == simple(b)


def fetch_chart(song: str, artist: str | None, file_chords: list[str], search=None, tab=None) -> dict | None:
    """The best-rated Ultimate Guitar chords chart, transposed to the file's key when the
    harmony shows a shift: {text, url, key, capo, transpose}, or None."""
    from . import web

    search, tab = search or web.ug_search, tab or web.ug_tab
    try:
        tabs = search(f"{artist} {song}" if artist else song, ["chords"])
        tabs = sorted(tabs, key=lambda t: -(t.get("votes") or 0) * (t.get("rating") or 0))
        best = [t for t in tabs if _same_song(t.get("song", ""), song)] or tabs
        if not best:
            return None
        chart = tab(best[0]["tab_id"])
    except Exception as exc:  # noqa: BLE001 - offline or rate limited: no chart
        log.info("details: chart lookup failed: %s", exc)
        return None
    content = chart.get("content") or ""
    ranked = harmony.best_transpose(re.findall(r"\[ch\](.*?)\[/ch\]", content), file_chords)
    shift = ranked[0]["transpose"] if ranked and ranked[0]["match_pct"] >= 50 else 0
    return {"text": web.chart_text(content, shift)[:CHART_CHARS], "url": chart.get("url"), "key": chart.get("key"),
            "capo": chart.get("capo") or 0, "transpose": shift}


def _beat_in_bar(bar, beat: float) -> float:
    return round(1 + (beat - bar.start_beat) * bar.denominator / 4, 3)


def _bar_lines(score: Score, chords: list[dict], tune_notes: list[Note] | None) -> list[str]:
    starts = [b.start_beat for b in score.bars]
    where = lambda beat: max(0, bisect.bisect_right(starts, beat + 1e-6) - 1)  # noqa: E731
    by_bar: dict[int, list[str]] = {}
    for c in chords:
        bar = score.bars[where(c["beat"])]
        by_bar.setdefault(bar.number, []).append(f"{c['chord']}@{_beat_in_bar(bar, c['beat']):g} ({c['fit']:.2f})")
    sung: dict[int, list[str]] = {}
    for k, n in enumerate(tune_notes or []):
        bar = score.bars[where(n.beat)]
        sung.setdefault(bar.number, []).append(f"#{k} {_beat_in_bar(bar, n.beat):g} {note_name(n.pitch)}")
    lines = []
    for bar in score.bars:
        line = f"bar {bar.number} ({bar.numerator}/{bar.denominator}): {' '.join(by_bar.get(bar.number, [])) or '-'}"
        if tune_notes is not None:
            line += " | tune: " + (" ".join(sung.get(bar.number, [])) or "-")
        lines.append(line)
    return lines


def _norm(word: str) -> str:
    return re.sub(r"[^\w]+", "", word.lower()).replace("_", "")


def _words(*texts: str) -> set[str]:
    out = set()
    for text in texts:
        for token in re.split(r"[\s\-–—/]+", re.sub(r"\[[^\]]*\]", " ", text or "")):
            if _norm(token):
                out.add(_norm(token))
    return out


def check_lyrics(items: list[dict], tune_notes: list[Note], allowed: set[str]) -> list[dict]:
    """The returned syllables that are in order, on real notes, and spell words of the fetched
    lyrics, as [{beat, pitch, text, syllabic}]."""
    words: list[list[dict]] = []
    cur: list[dict] = []
    last = -1
    for item in items:
        k, text = item.get("note"), str(item.get("text") or "").strip()
        if not text or not isinstance(k, int) or not 0 <= k < len(tune_notes) or k <= last:
            continue
        last = k
        if item.get("syllabic") in ("single", "begin") or not cur:
            if cur:
                words.append(cur)
            cur = []
        cur.append({**item, "text": text})
        if item.get("syllabic") in ("single", "end"):
            words.append(cur)
            cur = []
    if cur:
        words.append(cur)
    out = []
    for word in words:
        if _norm("".join(s["text"] for s in word)) not in allowed:
            continue
        for i, s in enumerate(word):
            n = tune_notes[s["note"]]
            syllabic = "single" if len(word) == 1 else "begin" if i == 0 else "end" if i == len(word) - 1 else "middle"
            out.append({"beat": round(n.beat, 4), "pitch": n.pitch, "text": s["text"], "syllabic": syllabic})
    return out


def check_chords(score: Score, items: list[dict], measured: list[dict]) -> tuple[list[dict], list[str]]:
    """Published chords at their beats, each checked against the notes it sounds over: kept
    when it explains them nearly as well as the chord the notes suggest, else the file's own
    chord stays and the disagreement is reported."""
    notes = _harmony_notes(score)
    names = harmony.spelling_for(harmony.estimate_key(notes) if notes else None)
    bars = {b.number: b for b in score.bars}
    placed = []
    for item in items:
        bar, chord = bars.get(item.get("bar")), parse_chord(str(item.get("chord", "")))
        if bar is None or chord is None:
            continue
        beat = bar.start_beat + (float(item.get("beat") or 1) - 1) * 4 / bar.denominator
        if bar.start_beat - 1e-6 <= beat < bar.end_beat - 1e-6:
            placed.append((round(beat, 4), chord, bar))
    placed.sort(key=lambda x: x[0])
    out, conflicts = [], []
    end_of = score.bars[-1].end_beat if score.bars else 0
    for k, (beat, chord, bar) in enumerate(placed):
        until = placed[k + 1][0] if k + 1 < len(placed) else end_of
        until = min(until, beat + 2 * (bar.end_beat - bar.start_beat))  # judge it by its first two bars
        weights, bass = harmony._profile(notes, _sec(score, beat), _sec(score, until))
        total = sum(weights)
        name = chord_name(chord)
        if total <= 0:
            out.append({"beat": beat, "chord": name, "from": "published"})
            continue
        fit = sum(weights[p] for p in chord.tones) / total
        own, own_fit = harmony.name_chord(weights, bass, names)
        if fit < 0.6 and own and fit < own_fit - CONFLICT_MARGIN:
            conflicts.append(f"Bar {bar.number}: the chart has {name}, the notes play {own}.")
            if own_fit >= MIN_FIT:
                out.append({"beat": beat, "chord": own, "from": "notes", "fit": own_fit})
            continue
        out.append({"beat": beat, "chord": name, "from": "published", "fit": round(fit, 2)})
    deduped = [c for k, c in enumerate(out) if k == 0 or c["chord"] != out[k - 1]["chord"]]
    return deduped, conflicts


def research(score: Score, data: dict, run=claude_run.run, lyrics=fetch_lyrics, chart=fetch_chart) -> dict:
    """The local details with the song's published chords, sections and lyrics laid on."""
    song, artist = data.get("song"), data.get("artist")
    measured = data.get("chords") or []
    has_own_lyrics = bool(data.get("lyrics")) and data.get("lyrics_from", "").startswith("the file")
    words = None if has_own_lyrics else lyrics(song, artist)
    sheet = chart(song, artist, [c["chord"] for c in measured])
    tune_notes, staff = tune(score)
    want_lyrics = bool(words or sheet) and not has_own_lyrics and bool(tune_notes)
    parts = [f"Song: {song}" + (f" by {artist}" if artist else ""),
             f"The arrangement: {len(score.bars)} bars, key {data.get('key')}; "
             + ("the tune is its vocal part." if staff == "vocals" else "the tune is taken as the right hand's top notes.")]
    if has_own_lyrics:
        parts.append("Lyrics: already in the file - return none.")
    if sheet:
        shift = f", transposed {sheet['transpose']:+d} semitones to this file's key" if sheet["transpose"] else ""
        parts += [f"\nChord chart ({sheet['url']}; key {sheet['key'] or '?'}, capo {sheet['capo']}{shift}):", sheet["text"]]
    else:
        parts.append("\nNo chord chart was found: use TheoryTab and the notes.")
    if words:
        parts += [f"\nLyrics ({words['url']}):", words["text"]]
    elif not has_own_lyrics:
        parts.append("\nNo lyrics were found apart from the chart's words." if sheet else "\nNo lyrics were found: return none.")
    parts += ["\nThe arrangement, bar by bar:", *_bar_lines(score, measured, tune_notes if want_lyrics else None)]
    out = run("\n".join(parts), MODEL, schema=SCHEMA, system=SYSTEM, tools="WebSearch,WebFetch", timeout=RUN_TIMEOUT_SEC)
    if out.get("error"):
        why = ("your Claude subscription's usage limit was reached - try again later" if out.get("usage_limit")
               else out["error"])
        return {**data, "state": "failed", "note": f"Couldn't look the song up ({why}). The chords on the sheet are worked out from the notes."}
    found = out.get("structured") or {}
    chords, conflicts = check_chords(score, found.get("chords") or [], measured)
    bars = {b.number: b for b in score.bars}
    sections = sorted({s["bar"]: {"beat": round(bars[s["bar"]].start_beat, 4), "name": str(s["name"]).strip()[:30]}
                       for s in found.get("sections") or [] if s.get("bar") in bars and str(s.get("name", "")).strip()}.items())
    new = {**data, "state": "done", "fetched": time.strftime("%Y-%m-%d"), "conflicts": conflicts,
           "sections": [s for _, s in sections], "lyrics_on": staff}
    if chords:
        new["chords"] = chords
    if want_lyrics:
        sung = check_lyrics(found.get("lyrics") or [], tune_notes, _words(words["text"] if words else "", sheet["text"] if sheet else ""))
        if sung:
            new["lyrics"], new["lyrics_from"] = sung, (words or sheet)["url"]
    sources = [s for s in [sheet and sheet["url"], words and words["url"], *(found.get("sources") or [])] if s and str(s).startswith("http")]
    new["sources"] = list(dict.fromkeys(sources))
    published = sum(1 for c in chords if c["from"] == "published")
    bits = [f"{published} chords from the published chart" + (f", {len(conflicts)} kept from the notes where it disagreed" if conflicts else "")
            if published else "chords worked out from the notes (no published chart matched)"]
    if new.get("lyrics"):
        bits.append(f"{len(new['lyrics'])} syllables of lyrics" + (" from the file" if has_own_lyrics else ""))
    if new["sections"]:
        bits.append(f"{len(new['sections'])} sections")
    new["note"] = "Added " + ", ".join(bits) + "." + (f" {found['note'].strip()}" if found.get("note") else "")
    return new


def start(score: Score, refresh: bool = False, done=None, run=claude_run.run) -> dict:
    """Show the file's own details now and look the song up in the background. done(path) is
    called when the lookup has finished. Returns status()."""
    path = score.path
    data = load(path)
    if data is None:
        data = local(score)
        save(path, data)
    with _lock:
        if path in running or (data.get("state") == "done" and not refresh):
            return status(path)
        running.add(path)

    def work() -> None:
        try:
            new = research(score, data, run)
        except Exception as exc:  # noqa: BLE001 - report it on the page, keep the local details
            log.exception("details: research failed")
            new = {**data, "state": "failed", "note": f"Couldn't look the song up ({exc}). The chords on the sheet are worked out from the notes."}
        try:
            save(path, new)
        finally:
            with _lock:
                running.discard(path)
            if done:
                done(path)

    threading.Thread(target=work, daemon=True, name="details").start()
    return status(path)


# -- writing them into the sheet -------------------------------------------------------------


@dataclass
class _Measure:
    el: ET.Element
    start: Fraction  # quarter notes from the start of the piece
    divisions: int
    anchors: list[tuple[ET.Element, Fraction]]  # where a <harmony> or <direction> can go: (element before it, position)
    notes: list[tuple[ET.Element, Fraction, int, int | None]]  # (note, position, staff, MIDI pitch or None for a rest)


_PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _midi(note: ET.Element) -> int | None:
    p = note.find("pitch")
    if p is None:
        return None
    alter = p.findtext("alter")
    return 12 * (int(p.findtext("octave")) + 1) + _PITCH[p.findtext("step")] + (round(float(alter)) if alter else 0)


def _measures(part: ET.Element) -> list[_Measure]:
    out = []
    divisions, start = 1, Fraction(0)
    for m in part.findall("measure"):
        pos = longest = onset = Fraction(0)
        anchors, notes = [], []
        for child in list(m):
            if child.tag == "attributes" and child.findtext("divisions"):
                divisions = int(float(child.findtext("divisions")))
            dur = Fraction(int(float(child.findtext("duration") or 0)), divisions)
            if child.tag == "note":
                chord, grace = child.find("chord") is not None, child.find("grace") is not None
                if not chord:
                    anchors.append((child, pos))
                    onset = pos
                tied_on = any(t.get("type") == "stop" for t in child.findall("tie"))
                if not chord and not grace and not tied_on and child.find("rest") is None:  # a lyric goes on a chord's first note
                    notes.append((child, onset, int(child.findtext("staff") or 1), _midi(child)))
                if not chord and not grace:
                    pos += dur
            elif child.tag == "backup":
                anchors.append((child, pos))
                pos -= dur
            elif child.tag == "forward":
                anchors.append((child, pos))
                pos += dur
            longest = max(longest, pos)
        out.append(_Measure(m, start, divisions, anchors, notes))
        start += longest
    return out


def _el(tag: str, content: str | None = None, **attrs) -> ET.Element:
    el = ET.Element(tag, {k.replace("_", "-"): v for k, v in attrs.items()})
    if content is not None:
        el.text = content
    return el


def _harmony_el(chord: Chord, ident: str, staff: int | None) -> ET.Element:
    h = _el("harmony", id=ident, placement="above")
    root = ET.SubElement(h, "root")
    ET.SubElement(root, "root-step").text = chord.step
    if chord.alter:
        ET.SubElement(root, "root-alter").text = str(chord.alter)
    ET.SubElement(h, "kind").text = chord.kind
    if chord.bass_step:
        bass = ET.SubElement(h, "bass")
        ET.SubElement(bass, "bass-step").text = chord.bass_step
        if chord.bass_alter:
            ET.SubElement(bass, "bass-alter").text = str(chord.bass_alter)
    for value in chord.added:
        degree = ET.SubElement(h, "degree")
        ET.SubElement(degree, "degree-value").text = str(value)
        ET.SubElement(degree, "degree-alter").text = "0"
        ET.SubElement(degree, "degree-type").text = "add"
    if staff:
        ET.SubElement(h, "staff").text = str(staff)
    return h


def _numeral_el(text: str, degree: int, ident: str, staff: int | None) -> ET.Element:
    h = _el("harmony", id=ident, placement="below")
    numeral = ET.SubElement(h, "numeral")
    numeral.append(_el("numeral-root", str(degree), text=text))
    ET.SubElement(h, "kind").text = "none"
    if staff:
        ET.SubElement(h, "staff").text = str(staff)
    return h


def _words_el(text: str, ident: str, staff: int | None) -> ET.Element:
    d = _el("direction", id=ident, placement="above")
    kind = ET.SubElement(d, "direction-type")
    kind.append(_el("words", text, font_weight="bold", font_size="11"))
    if staff:
        ET.SubElement(d, "staff").text = str(staff)
    return d


class _Sheet:
    """The parts of a MusicXML score, their staves, and where things can go in each bar."""

    def __init__(self, root: ET.Element, roles: list[str]):
        self.parts = root.findall("part")
        self._measures: dict[int, list[_Measure]] = {}
        self.slots: list[tuple[int, int, int]] = []  # (part index, staff number, staves in the part)
        for i, part in enumerate(self.parts):
            n = int(part.findtext("measure/attributes/staves") or 1)
            self.slots += [(i, s, n) for s in range(1, n + 1)]
        if len(roles) == len(self.slots):
            self.roles = roles
        else:  # a two-staff part is the right hand over the left
            self.roles = [("right" if s == 1 else "left") if n == 2 else "other" for _, s, n in self.slots]

    def measures(self, part: int) -> list[_Measure]:
        if part not in self._measures:
            self._measures[part] = _measures(self.parts[part])
        return self._measures[part]

    def measure_at(self, part: int, beat: Fraction) -> _Measure | None:
        ms = self.measures(part)
        k = bisect.bisect_right([m.start for m in ms], beat) - 1
        return ms[k] if k >= 0 else None

    def slot(self, *wanted: str, last: bool = False) -> int:
        piano = [k for k, r in enumerate(self.roles) if r in ("right", "left", "both")] or list(range(len(self.slots)))
        order = list(reversed(piano)) if last else piano
        return next((k for k in order if self.roles[k] in wanted), order[0])

    def insert(self, slots: list[int], beat: Fraction, make) -> bool:
        """Put make(staff number or None) at a beat: in the first of these staves if something
        starts there or within NEAR_BEATS of it in the same bar (OSMD hangs a chord symbol
        on a note or rest, so it goes on the nearest one), else in the next staff that has
        something starting exactly there."""
        for n, k in enumerate(slots):
            part, staff, count = self.slots[k]
            m = self.measure_at(part, beat)
            if m is None:
                continue
            at = beat - m.start
            reach = NEAR_BEATS if n == 0 else Fraction(1, 48)
            near = [(abs(pos - at), i, el) for i, (el, pos) in enumerate(m.anchors)
                    if abs(pos - at) <= Fraction(1, 48) or (abs(pos - at) <= reach and el.tag == "note")]
            if near:
                anchor = min(near, key=lambda x: x[:2])[2]
                m.el.insert(list(m.el).index(anchor), make(staff if count > 1 else None))
                return True
        return False


def _key_regions(sheet: _Sheet, score: Score) -> list[tuple[Fraction, int, bool]]:
    """(beat, tonic, minor?) at each key signature, the mode read from the notes under it
    when the file doesn't say."""
    regions: list[tuple[Fraction, int, str | None]] = []
    for m in sheet.measures(0):
        key = m.el.find("attributes/key")
        if key is not None and key.findtext("fifths") is not None:
            sharps = int(key.findtext("fifths"))
            if not regions or regions[-1][1] != sharps:
                regions.append((m.start, sharps, key.findtext("mode")))
    if not regions:
        regions = [(Fraction(0), 0, None)]
    notes = _harmony_notes(score)
    out = []
    for k, (at, sharps, mode) in enumerate(regions):
        until = regions[k + 1][0] if k + 1 < len(regions) else Fraction(10 ** 9)
        if mode in ("major", "minor"):
            major = (7 * sharps) % 12
            out.append((at, (major + 9) % 12 if mode == "minor" else major, mode == "minor"))
        else:
            out.append((at, *harmony.key_for_signature([n for n in notes if at <= n.beat < until], sharps)))
    return out


def apply(xml: str, data: dict | None, roles: list[str], score: Score) -> str:
    """The sheet with the details written in (the notes are left exactly as they are)."""
    if not data or not (data.get("chords") or data.get("lyrics") or data.get("sections")):
        return xml
    head = xml.find("<score-partwise")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return xml
    if root.tag != "score-partwise":
        return xml
    sheet = _Sheet(root, roles)
    beat_of = lambda x: Fraction(x).limit_denominator(48)  # noqa: E731
    top = sheet.slot("right", "both")
    bottom = sheet.slot("left", "both", last=True)
    piano = [k for k, r in enumerate(sheet.roles) if r in ("right", "left", "both")]
    own_harmony = root.find(".//harmony") is not None

    keys = _key_regions(sheet, score) if data.get("chords") else []
    for k, c in enumerate(data.get("chords") or []):
        chord = parse_chord(c["chord"])
        if chord is None:
            continue
        at = beat_of(c["beat"])
        if not own_harmony:
            sheet.insert([top] + [s for s in piano if s != top], at,
                         lambda staff, k=k, chord=chord: _harmony_el(chord, f"details-chord-{k}", staff))
        tonic, minor = next(((t, mi) for b, t, mi in reversed(keys) if b <= at), (0, False))
        numeral = roman(c["chord"], tonic, minor)
        if numeral:
            degree = _DEGREE[(chord.root - tonic) % 12]
            sheet.insert([bottom] + [s for s in reversed(piano) if s != bottom], at,
                         lambda staff, k=k, numeral=numeral, degree=degree: _numeral_el(numeral, degree, f"details-roman-{k}", staff))

    for k, s in enumerate(data.get("sections") or []):
        sheet.insert([0], beat_of(s["beat"]), lambda staff, k=k, s=s: _words_el(s["name"], f"details-section-{k}", staff))

    lyrics = data.get("lyrics") or []
    on = sheet.roles.index("vocals") if data.get("lyrics_on") == "vocals" and "vocals" in sheet.roles else top
    part, staff, _ = sheet.slots[on]
    candidates = [(m.start + pos, el, pitch) for m in sheet.measures(part) for el, pos, st, pitch in m.notes
                  if st == staff and pitch is not None]
    if lyrics and candidates and not any(el.find("lyric") is not None for _, el, _ in candidates):
        candidates.sort(key=lambda c: c[0])
        starts = [float(c[0]) for c in candidates]
        placed: list[tuple[ET.Element, dict]] = []
        used: set[int] = set()
        # A syllable with no note to go on joins its word's neighbour, so the word is printed
        # whole ('ex' + 'cuse' on one note as 'excuse'), as songs.py does for karaoke files.
        word_last: int | None = None  # the placed syllable the current word ends on so far
        prefix = ""  # syllables of the current word still waiting for a note
        for syl in sorted(lyrics, key=lambda s: s["beat"]):
            if syl["syllabic"] in ("single", "begin"):
                word_last, prefix = None, ""
            lo = bisect.bisect_left(starts, syl["beat"] - LYRIC_REACH)
            hi = bisect.bisect_right(starts, syl["beat"] + LYRIC_REACH)
            near = [i for i in range(lo, hi) if i not in used and (not placed or i > max(used))]
            if not near:
                if word_last is not None:
                    el, held = placed[word_last]
                    placed[word_last] = (el, {**held, "text": held["text"] + syl["text"]})
                else:
                    prefix += syl["text"]
                continue
            i = min(near, key=lambda i: abs(starts[i] - syl["beat"]) - (0.1 if candidates[i][2] == syl.get("pitch") else 0))
            used.add(i)
            placed.append((candidates[i][1], {**syl, "text": prefix + syl["text"]}))
            word_last, prefix = len(placed) - 1, ""
        for k, (el, syl) in enumerate(placed):
            prev = placed[k - 1][1]["syllabic"] if k else "single"
            nxt = placed[k + 1][1]["syllabic"] if k + 1 < len(placed) else "single"
            starts_word = syl["syllabic"] in ("single", "begin") or prev not in ("begin", "middle")
            ends_word = syl["syllabic"] in ("single", "end") or nxt not in ("middle", "end")
            syllabic = "single" if starts_word and ends_word else "begin" if starts_word else "end" if ends_word else "middle"
            lyric = _el("lyric", number="1", id=f"details-lyric-{k}")
            ET.SubElement(lyric, "syllabic").text = syllabic
            ET.SubElement(lyric, "text").text = syl["text"]
            el.append(lyric)

    return (xml[:head] if head > 0 else "") + ET.tostring(root, encoding="unicode")
