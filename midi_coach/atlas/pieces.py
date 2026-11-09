"""Pieces of the Atlas: the public-domain catalog, the sheet music, and the stage lessons.

The catalog (data/pieces.json, in git) names each piece by its source (a Mutopia id, or a
PDMX file for the few MuseScore scores marked CC0/Public Domain that Mutopia lacks), with
the grade and exam list (A: fast and agile, B: lyrical, C: other styles) it fits, its
licence and the sha1 of the downloaded file. The music itself is fetched to
<home>/atlas/pieces/ (tools/fetch_pd_pieces.py), and written as MusicXML by the coach's
grand-staff writer: every pitch and rhythm of the source kept exactly (no legato joining,
no regridding), hands from the source's staves, and the source and licence recorded in
<identification><source>. Pieces keep the rhythms their composers wrote (grace notes as
short notes, quintuplets, double dots), so their sheets are checked with the 'published'
engraving profile.
"""

from __future__ import annotations

import json
import pathlib
from fractions import Fraction

from . import PACKAGE, content_dir, load_atlas, shared_dir

CATALOG = PACKAGE / "data" / "pieces.json"
LISTS = {"A": "List A: fast-moving, technical agility", "B": "List B: lyrical, expressive",
         "C": "List C: other styles and characters"}


def pieces_dir() -> pathlib.Path:
    path = shared_dir() / "pieces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_catalog() -> list[dict]:
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8"))["pieces"]
    except (OSError, ValueError):
        return []


def save_catalog(pieces: list[dict]) -> None:
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps({"source": "Mutopia Project (Public Domain licence only) and PDMX, https://zenodo.org/records/"
                                             "15571083 (CC0 / Public Domain Mark scores, composers who died before 1955); "
                                             "grades from exam boards where "
                                             "they list the piece (grade_source), else the coach's estimate",
                                   "pieces": pieces}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def fetched(piece: dict) -> pathlib.Path | None:
    path = pieces_dir() / f"{piece['id']}.musicxml"
    return path if path.is_file() else None


def partial_beats(ly: str) -> Fraction | None:
    r"""The upbeat a LilyPond source declares (\partial 8, \partial 4., \partial 16*3...), in
    quarter-note beats: the MIDI it writes has no partial bars, so this is where to find it."""
    import re

    m = re.search(r"\\partial\s+(\d+)(\.*)\s*(?:\*\s*(\d+)(?:/(\d+))?)?", ly)
    if not m:
        return None
    beats = Fraction(4, int(m.group(1)))
    beats *= 2 - Fraction(1, 2 ** len(m.group(2)))  # dots
    if m.group(3):
        beats *= Fraction(int(m.group(3)), int(m.group(4) or 1))
    return beats


def to_musicxml(midi_path: str | pathlib.Path, title: str, composer: str | None, source: str,
                pickup: Fraction | None = None) -> dict:
    """A source MIDI file (one track per staff, as LilyPond writes them) as a two-hand score:
    {xml, events, bars}. The parts with the higher average pitch are the right hand."""
    from ..engraving import MISREAD_RULES, lint
    from ..notes import load_score
    from ..sheet import _tempo_marks
    from ..transcribe import grand_staff

    score = load_score(midi_path)
    parts = sorted((p for p in score.parts if p.note_count and not p.drums), key=lambda p: -p.mean_pitch)
    if not parts:
        raise ValueError(f"No notes in {midi_path}")
    if len(parts) == 1:
        right = {parts[0].index}
        split = True
    else:
        middle = (parts[0].mean_pitch + parts[-1].mean_pitch) / 2
        right = {p.index for p in parts if p.mean_pitch >= middle}
        split = False
    from ..sheet import _beat, _end, grids_for

    notes = [n for n in score.notes if n.end > n.start]
    hand_of = lambda n: ("right" if n.pitch >= 60 else "left") if split else ("right" if n.part in right else "left")  # noqa: E731
    grids = grids_for([n.beat for n in notes])

    def snap(n):
        on = _beat(n.beat, grids)
        return (hand_of(n), on, _end(score.beat_of(n.end), on, grids), n.pitch)

    try:
        # Exact, except the few notes on no grid (grace notes and ornaments, which the MIDI plays
        # by taking time from their neighbours): those alone are snapped.
        events, ornaments = [], 0
        for n in notes:
            try:
                on = _exact(n.beat)
                events.append((hand_of(n), on, max(_exact(score.beat_of(n.end)), on + Fraction(1, 32)), n.pitch))
            except ValueError:
                events.append(snap(n))
                ornaments += 1
        if ornaments > max(12, len(notes) // 20):
            raise ValueError(f"inexpressible duration: {ornaments} notes on no grid")
        note = (f" Notation only: {ornaments} grace or ornament note{'s' * (ornaments > 1)} written on the nearest "
                "sixteenth / triplet; every pitch kept.") if ornaments else ""
        out = grand_staff(events, title, _sigs(score, pickup), _tempo_marks(score), legato_gap=Fraction(0),
                          source=source + note, composer=composer, pickup=pickup)
        tangled = [f for f in lint(out["xml"], profile="published")["findings"] if f[0] in MISREAD_RULES]
        if tangled:
            raise ValueError(f"inexpressible duration: {tangled[0]}")
        snapped = False
    except Exception as exc:
        if "duration" not in str(exc):
            raise
        events, ornaments = [snap(n) for n in notes], 0
        out = grand_staff(events, title, _sigs(score, pickup), _tempo_marks(score), legato_gap=Fraction(0), pickup=pickup,
                          source=source + " Notation only: onsets and lengths snapped to a sixteenth / triplet grid "
                          "(grace notes and ornaments in the MIDI are too short to write); every pitch kept.",
                          composer=composer)
        snapped = True
    return {"xml": out["xml"], "events": events, "bars": out["bars"], "snapped": snapped, "ornaments": ornaments,
            "first_bar": 0 if pickup else 1}


# Beat subdivisions written music uses, coarsest first: 64th notes, triplets, sextuplets,
# quintuplets, septuplets (per quarter-note beat).
GRIDS = (16, 12, 24, 20, 28)
GRID_TOLERANCE = 0.004  # beats: about a tick and a half at LilyPond's 384 per quarter


def _exact(beat: float) -> Fraction:
    """A time in beats as the note value it was written as. Raises (an 'inexpressible duration',
    so the caller snaps) when it is on none of the grids: a grace note, a spread chord, or
    tempo-map drift, which would otherwise come out as 23-in-the-time-of-16 tuplets."""
    for d in GRIDS:
        f = Fraction(round(beat * d), d)
        if abs(f - beat) < GRID_TOLERANCE:
            return f
    raise ValueError(f"inexpressible duration at beat {beat:.4f}")


def _sigs(score, pickup: Fraction | None):
    """The file's time signatures - with an upbeat the MIDI's bars start early, so only one
    time signature is trusted: LilyPond's MIDI has no partial bar (its first signature is the
    real one), while MuseScore's writes the upbeat as a short bar of its own (then it's the second)."""
    from ..sheet import time_signatures

    sigs = time_signatures(score)
    if not pickup:
        return sigs
    if len(sigs) > 1 and upbeat_bar(score) == pickup:
        return _whole_bars(score)
    return sigs[0][1]


def _whole_bars(score) -> list[tuple[Fraction, str]]:
    """MuseScore's time signatures after its upbeat bar, with its split bars mended: a bar
    shorter than the metre around it, plus the bars after it that make it whole, is one bar
    (a repeat sign written out splits a 6/8 bar into 5/8 + 1/8). Real changes are kept."""
    out: list[tuple[Fraction, str]] = []
    full, short = Fraction(0), Fraction(0)
    bars = score.bars[1:]
    for i, b in enumerate(bars):
        length = Fraction(b.end_beat - b.start_beat).limit_denominator(48)
        sig = f"{b.numerator}/{b.denominator}"
        if short:  # completing a split bar
            short += length
            if short >= full:
                short = Fraction(0)
            continue
        after = f"{bars[i + 1].numerator}/{bars[i + 1].denominator}" if i + 1 < len(bars) else None
        if out and sig != out[-1][1] and length < full and after != sig:  # a new metre goes on; half a bar doesn't
            short = length
            continue
        if not out or sig != out[-1][1]:
            out.append((Fraction(0) if not out else Fraction(b.start_beat).limit_denominator(48), sig))
            full = length
    return out


def upbeat_bar(score) -> Fraction | None:
    """The length in beats of a first bar shorter than the next one (how MuseScore's MIDI
    writes an upbeat), or None."""
    if len(score.bars) < 2:
        return None
    first, second = (Fraction(b.end_beat - b.start_beat).limit_denominator(48) for b in score.bars[:2])
    return first if first < second and (score.bars[0].numerator, score.bars[0].denominator) != (score.bars[1].numerator, score.bars[1].denominator) else None


# -- lessons ----------------------------------------------------------------------------------


def lesson_for(stage: dict, req: dict, piece: dict, file: str) -> dict:
    st = stage["stage"]
    learn = st["mode"] == "learn"
    about = (f"{piece['title']} by {piece['composer']}. {LISTS.get(piece.get('list'), '')}."
             if st["key"] in ("s1-rh", "whole-60") else "")
    what = {"right": "right hand", "left": "left hand", "both": "hands together"}[st["hand"]]
    where = f"bars {st['bars']}" if st.get("bars") else "the whole piece"
    text = (about + f" {where.capitalize()}, {what}" + (f", at {st['tempo_percent']}%" if st["tempo_percent"] != 100 else ", at tempo")
            + (". Learn mode waits for each note." if learn else ". Keep going through slips, as in a performance.")).strip()
    steps = [{"id": "read", "type": "read", "text": text},
             {"id": "listen", "type": "listen", "file": file, "hand": st["hand"], "bars": st.get("bars"), "tempo_percent": st["tempo_percent"]},
             {"id": "play", "type": "play", "file": file, "hand": st["hand"], "bars": st.get("bars"), "mode": st["mode"],
              "tempo_percent": st["tempo_percent"], "graded": True,
              "pass": {"metric": "notes", "min": 90} if learn else
                      {"metric": "overall", "min": 80 if st["tempo_percent"] == 100 else 75, "tempo_min_pct": max(50, st["tempo_percent"] - 10)}}]
    # Notation that had to be snapped (whole piece, or its grace notes) waits for a look.
    checked = not (piece.get("snapped") or piece.get("ornaments"))
    return {"id": stage["id"], "version": 1, "made": "atlas.pieces", "checked": checked, "requirement": req["id"], "steps": steps,
            "piece": piece["id"]}


def write_lessons() -> int:
    atlas = load_atlas()
    catalog = {p["id"]: p for p in load_catalog()}
    count = 0
    for req in atlas["nodes"]:
        if req["level"] != "requirement" or req["kind"] != "piece":
            continue
        piece = catalog.get(req.get("piece"))
        path = fetched(piece) if piece else None
        if not path:
            continue
        for sid in req["stages"]:
            lesson = lesson_for(atlas["by_id"][sid], req, piece, str(path))
            (content_dir() / "lessons" / f"{sid}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
            count += 1
    return count
