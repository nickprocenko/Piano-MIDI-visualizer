"""Piano sheet music for a MIDI reference: the parts you play, on a grand staff.

A band arrangement drawn as-is is one staff per instrument, drums included. Instead this
writes only the parts you play (your confirmed choice, else the suggestion), each hand on
its own staff, from the same notes the coach grades - so the sheet, the hit/miss marks
and the grading agree. A vocal line goes on a staff above the piano and a bass-pedal part
on one below it (notes.ROLES). Files whose beat grid was recovered (regrid.py) are written on that
grid, with tempo marks where the tempo moves.

Results are cached in <home>/derived, keyed by the file and the part choice.
"""

from __future__ import annotations

import pathlib
from fractions import Fraction

from . import analysis, library
from .notes import MIDI_SUFFIXES, OTHER_ROLES, SPLIT_VERSION, Score, effective_roles, is_plain_piano, playable_parts, select_notes
from .regrid import snap
from .transcribe import grand_staff

VERSION = 6  # bump when the output changes, so cached sheets are rewritten
MIN_TEMPO_CHANGE = 2.0  # BPM: smaller drifts don't get a new tempo mark


def wanted(score: Score) -> bool:
    """Write our own piano sheet (rather than converting the whole file) for MIDI files that
    aren't plain piano, whose beat grid had to be recovered, or that keep both hands in one
    track (a straight conversion would put every note on one staff)."""
    if pathlib.Path(score.path).suffix.lower() not in MIDI_SUFFIXES:
        return False
    return (not is_plain_piano(score) or score.beat_map is not None or len(playable_parts(score)) == 1
            or any(r in OTHER_ROLES for r in score.roles.values()))


TEMPO_SMOOTH_BARS = 5  # tempo marks follow the median over this many bars, not one bar's wobble


def grids_for(beats: list[float]) -> dict[int, Fraction]:
    """One grid per beat for a group of staves: straight sixteenths, or triplet eighths where
    the notes in that beat clearly sit on triplets. Deciding per beat rather than per note
    keeps a beat from mixing sixteenths, triplets and sextuplets (nested tuplets)."""
    from .transcribe import _beat_grids

    return _beat_grids([max(Fraction(0), Fraction(b).limit_denominator(96)) for b in beats], "auto")


def _beat(x: float, grids: dict[int, Fraction] | None = None) -> Fraction:
    if grids is None:
        return Fraction(snap(x)).limit_denominator(12)
    from .transcribe import _quantize

    return _quantize(max(Fraction(0), Fraction(x).limit_denominator(96)), grids)


def _end(x: float, onset: Fraction, grids: dict[int, Fraction] | None = None) -> Fraction:
    """Where a note stops. Key releases are imprecise, so the length is rounded more coarsely
    the longer the note: to the grid (a 16th, or a triplet 8th in a triplet beat) under a
    beat, an 8th under two beats, else to the beat - always onto a line of the grid of the
    beat it ends in. A quarter let go a little early is a quarter, not a quarter tied to a
    16th and a rest. Without grids, only a note that started on a triplet may end on one."""
    if grids is None:
        if (onset * 4).denominator != 1:
            return _beat(x)
        length = x - float(onset)
        step = Fraction(1, 4) if length < 1 else Fraction(1, 2) if length < 2 else Fraction(1)
        return onset + max(step, round(length / step) * step)
    import math

    length = x - float(onset)
    beat = math.floor(x + 1 / 8)
    grid = grids.get(beat, Fraction(1, 4))
    step = grid if length < 1 else (Fraction(1, 2) if grid == Fraction(1, 4) else grid) if length < 2 else Fraction(1)
    end = Fraction(round(Fraction(x).limit_denominator(96) / step)) * step
    shortest = grids.get(math.floor(onset + Fraction(1, 8)), Fraction(1, 4))
    return max(end, onset + shortest)


def _tempo_marks(score: Score) -> list[tuple[Fraction, float]]:
    """A tempo mark at bar 1 and wherever the (smoothed) tempo moves by MIN_TEMPO_CHANGE."""
    import statistics

    bars = score.bars
    if not bars:
        return [(Fraction(0), score.tempos[0][1] if score.tempos else 120.0)]
    per_bar = [60 * (b.end_beat - b.start_beat) / max(b.end - b.start, 1e-6) for b in bars]
    half = TEMPO_SMOOTH_BARS // 2
    marks: list[tuple[Fraction, float]] = []
    for i, b in enumerate(bars):
        bpm = round(statistics.median(per_bar[max(0, i - half): i + half + 1]))
        if not marks or abs(bpm - marks[-1][1]) >= MIN_TEMPO_CHANGE:
            marks.append((Fraction(b.start_beat).limit_denominator(12), bpm))
    return marks


def build(score: Score, split_note: int = 60) -> dict:
    """{xml, bars, notes, key, parts, staves} for the parts the user plays, plus the vocal
    line and the bass pedals; staves is the role of each staff, top to bottom."""
    notes, info = select_notes(score, "both", split_note=split_note)
    roles = set(effective_roles(score).values())
    pedals = select_notes(score, "pedals")[0] if "pedals" in roles else []
    sung = select_notes(score, "vocals")[0] if "vocals" in roles else []
    if not notes and not pedals:
        raise ValueError("No notes in the chosen parts.")
    side = analysis.side_resolver(score, split_note)
    grids = grids_for([n.beat for n in notes + pedals])
    events = []
    for group, staff in ((notes, None), (pedals, "pedals")):
        for n in group:
            on = _beat(n.beat, grids)
            events.append((staff or side(n), on, _end(score.beat_of(n.end), on, grids), n.pitch))
    tune_grids = grids_for([n.beat for n in sung])  # its own grid: a sung triplet over straight piano
    tune = []
    for n in sung:
        on = _beat(n.beat, tune_grids)
        tune.append((on, _end(score.beat_of(n.end), on, tune_grids), n.pitch, None))
    title = pathlib.Path(score.path).stem
    out = grand_staff(events, title, time_signatures(score), _tempo_marks(score), melody=tune or None)
    staves = ["vocals"] * bool(tune) + ["right", "left"] + ["pedals"] * bool(pedals)
    return {**out, "parts": info.get("method"), "staves": staves}


def staves(score: Score) -> list[str]:
    """The role of each staff drawn for a score, top to bottom (a role from notes.ROLES, or
    'other' for a part without one), so the page can show and hide them by role. Matches
    build() for the sheets written here, and the file's parts in order otherwise."""
    roles = effective_roles(score)
    has = lambda role: any(r == role and score.parts[i].note_count for i, r in roles.items())  # noqa: E731
    if wanted(score):
        return ["vocals"] * has("vocals") + ["right", "left"] + ["pedals"] * has("pedals")
    return [roles.get(p.index, "other") for p in score.parts if p.note_count]


def time_signatures(score: Score) -> list[tuple[Fraction, str]]:
    """The file's time signature changes as (beat, "n/d"), e.g. a 2/4 bar between 4/4 ones."""
    out: list[tuple[Fraction, str]] = []
    for bar in score.bars:
        sig = f"{bar.numerator}/{bar.denominator}"
        if not out or sig != out[-1][1]:
            out.append((Fraction(bar.start_beat).limit_denominator(48), sig))
    return out or [(Fraction(0), "4/4")]


def piano_xml(score: Score, split_note: int = 60) -> str:
    """The piano sheet's MusicXML, from the cache when the file and part choice are unchanged."""
    from . import hand_model

    choice = ",".join(f"{i}{h[0]}" for i, h in sorted(score.roles.items())) or "suggested"
    hands = f"{hand_model.splitter()}-v{SPLIT_VERSION}"  # a sheet split by the old search is rebuilt once the model is installed
    cache = library.derived_path(score.path, "musicxml", f"sheet-v{VERSION}|{choice}|{split_note}|{score.regrid is not None}|{hands}")
    try:
        return cache.read_text(encoding="utf-8")
    except OSError:
        pass
    xml = build(score, split_note)["xml"]
    try:
        cache.write_text(xml, encoding="utf-8")
    except OSError:
        pass
    return xml
