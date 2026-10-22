"""Piano sheet music for a MIDI reference: the parts you play, on a grand staff.

A band arrangement drawn as-is is one staff per instrument, drums included. Instead this
writes only the parts you play (your confirmed choice, else the suggestion), each hand on
its own staff, from the same notes the coach grades - so the sheet, the hit/miss marks
and the grading agree. Files whose beat grid was recovered (regrid.py) are written on that
grid, with tempo marks where the tempo moves.

Results are cached in <home>/derived, keyed by the file and the part choice.
"""

from __future__ import annotations

import pathlib
from fractions import Fraction

from . import analysis, library
from .notes import MIDI_SUFFIXES, Score, is_plain_piano, playable_parts, select_notes
from .regrid import snap
from .transcribe import grand_staff

VERSION = 4  # bump when the output changes, so cached sheets are rewritten
MIN_TEMPO_CHANGE = 2.0  # BPM: smaller drifts don't get a new tempo mark


def wanted(score: Score) -> bool:
    """Write our own piano sheet (rather than converting the whole file) for MIDI files that
    aren't plain piano, whose beat grid had to be recovered, or that keep both hands in one
    track (a straight conversion would put every note on one staff)."""
    if pathlib.Path(score.path).suffix.lower() not in MIDI_SUFFIXES:
        return False
    return not is_plain_piano(score) or score.beat_map is not None or len(playable_parts(score)) == 1


TEMPO_SMOOTH_BARS = 5  # tempo marks follow the median over this many bars, not one bar's wobble


def _beat(x: float) -> Fraction:
    return Fraction(snap(x)).limit_denominator(12)


def _end(x: float, onset: Fraction) -> Fraction:
    """Where a note stops. Key releases are imprecise, so the length is rounded more coarsely
    the longer the note: to a 16th under a beat, an 8th under two beats, else to the beat. A
    quarter let go a little early is a quarter, not a quarter tied to a 16th and a rest. Only
    a note that started on a triplet may end on one."""
    if (onset * 4).denominator != 1:
        return _beat(x)
    length = x - float(onset)
    step = Fraction(1, 4) if length < 1 else Fraction(1, 2) if length < 2 else Fraction(1)
    return onset + max(step, round(length / step) * step)


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
    """{xml, bars, notes, key, parts} for the parts the user plays."""
    notes, info = select_notes(score, "both", split_note=split_note)
    if not notes:
        raise ValueError("No notes in the chosen parts.")
    side = analysis.side_resolver(score, split_note)
    events = []
    for n in notes:
        on = _beat(n.beat)
        end = max(_end(score.beat_of(n.end), on), on + Fraction(1, 4))
        events.append((side(n), on, end, n.pitch))
    first = score.bars[0] if score.bars else None
    time_signature = f"{first.numerator}/{first.denominator}" if first else "4/4"
    title = pathlib.Path(score.path).stem
    out = grand_staff(events, title, time_signature, _tempo_marks(score))
    return {**out, "parts": info.get("method")}


def piano_xml(score: Score, split_note: int = 60) -> str:
    """The piano sheet's MusicXML, from the cache when the file and part choice are unchanged."""
    choice = ",".join(f"{i}{h[0]}" for i, h in sorted(score.hands.items())) or "suggested"
    cache = library.derived_path(score.path, "musicxml", f"sheet-v{VERSION}|{choice}|{split_note}|{score.regrid is not None}")
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
