"""Readability rules for sheet music, checked on what the reader sees, bar by bar.

Every rule is a mistake that was found once - in a score, or in a screenshot of one - and
must not come back. A score the coach writes should break none of them; every note of the
source must still be there (the builders check that separately).

    python -m midi_coach.engraving lesson.musicxml [--png out_dir]

prints the findings per rule and the worst bars, and with --png draws bars 1-8 and the worst
bars (midi_coach.render) so they can be looked at.
"""

from __future__ import annotations

import math
import pathlib
import sys
from collections import Counter
from fractions import Fraction

RULES = {
    "missing-accidental": "a note that would be read as the wrong pitch: its sharp/flat/natural differs from the key signature and the bar so far, and none is printed",
    "needless-accidental": "a printed accidental the key signature or an earlier note in the bar already gives",
    "nested-tuplet": "a tuplet inside a tuplet",
    "odd-tuplet": "a tuplet other than a plain triplet (3 in the time of 2)",
    "too-short": "a note or rest shorter than a sixteenth (sixteenth triplets included; grace notes aside)",
    "short-rest-in-tune": "a gap shorter than an eighth between two notes of the tune (hold the first note instead)",
    "busy-rests": "more than four rests drawn in one staff's bar",
    "too-many-voices": "more than two voices on one staff",
    "needless-tie": "two tied notes inside one beat that could be written as one note",
    "ledger-lines": "a note on five or more ledger lines, or three notes in a row on four (needs a clef change or 8va/8vb)",
    "key-change-soon": "a key signature change less than six bars after the previous one",
    "heading": "the title printed twice, or 'Music21' as the composer",
    "double-dot": "a double-dotted note or rest",
    "dangling-hyphen": "a lyric hyphen leading to a note with no syllable",
    "busy-octave-marks": "more than two 8va/8vb marks starting within eight bars of one staff (write the passage with ledger lines or one mark)",
    "needless-octave-mark": "an 8va/8vb over notes that would sit within three ledger lines without it",
}
TUNE_WORDS = ("vocal", "voice", "melody", "tune", "lead", "sing")
STAFF_LINES = {"treble": (31, 38), "bass": (19, 26)}  # diatonic note numbers of the bottom / top line: E4-F5, G2-A3


def _in_tune(part) -> bool:
    return any(w in (part.partName or "").lower() for w in TUNE_WORDS)


def _ledgers(p, clef, shift: int = 0) -> int:
    """Ledger lines for a pitch as drawn: shift is +1 under an 8vb (drawn an octave up), -1
    under an 8va."""
    kind = "bass" if type(clef).__name__.startswith("Bass") else "treble"
    octave = getattr(clef, "octaveChange", 0) or 0
    d = p.diatonicNoteNum - 7 * octave + 7 * shift  # where it is written
    low, high = STAFF_LINES[kind]
    return (low - d) // 2 if d < low else (d - high) // 2 if d > high else 0  # a note in a space needs no extra line


def lint(score) -> dict:
    """{'findings': [(rule, part, bar, detail)], 'counts': {rule: n}, 'worst': [(bar, n)]}.
    score: a MusicXML path, the XML text, or a parsed music21 Score."""
    from music21 import converter, duration

    xml = None
    if isinstance(score, (str, pathlib.Path)):
        text = str(score)
        xml = text if text.lstrip().startswith("<") else pathlib.Path(text).read_text(encoding="utf-8")
        score = converter.parseData(xml)
    found: list[tuple[str, str, int, str]] = []

    def add(rule, part, bar, detail):
        found.append((rule, part.partName or "?", bar, detail))

    if xml is not None and ("<creator type=\"composer\">Music21</creator>" in xml
                            or xml.count("<work-title>") and xml.count("<movement-title>")):
        found.append(("heading", "-", 0, "title twice or 'Music21' as composer"))

    for part in score.parts:
        tune = _in_tune(part)
        last_key_bar = None
        four_run = 0  # notes in a row on four ledger lines
        marks = sorted(min(x.getContextByClass("Measure").number for x in sp.getSpannedElements())
                       for sp in part.recurse().getElementsByClass("Ottava") if sp.getSpannedElements())
        for i, bar in enumerate(marks):
            if i >= 2 and bar - marks[i - 2] < 8:
                add("busy-octave-marks", part, bar, f"three octave marks within bars {marks[i - 2]}-{bar}")
        for sp in part.recurse().getElementsByClass("Ottava"):
            notes = [x for x in sp.getSpannedElements() if not x.isRest]
            clefs = [x.getContextByClass("Clef") for x in notes]
            if notes and all(c is not None for c in clefs) and \
                    max(_ledgers(p, c) for x, c in zip(notes, clefs) for p in x.pitches) <= 3:
                m_ = notes[0].getContextByClass("Measure")
                add("needless-octave-mark", part, m_.number if m_ else 0, f"{sp.type} over {notes[0].pitches[0].nameWithOctave}...")
        if tune:  # a hyphen must lead to the rest of its word (notes between are a melisma: fine)
            sung = [x for x in part.flatten().notes if x.lyrics and not x.duration.isGrace]
            for a, b in zip(sung, sung[1:] + [None]):
                if a.lyrics[0].syllabic in ("begin", "middle") and (b is None or b.lyrics[0].syllabic not in ("middle", "end")):
                    m_ = a.getContextByClass("Measure")
                    add("dangling-hyphen", part, m_.number if m_ else 0,
                        f"'{a.lyrics[0].text}-' is followed by '{b.lyrics[0].text if b else ''}', a new word")
        before: dict[str, float] = {}  # letter -> alteration last used in the previous bar (for courtesy accidentals)
        if tune:  # gaps between the tune's notes, across barlines
            seq = [x for x in part.flatten().notesAndRests if not x.duration.isGrace]
            k = 0
            while k < len(seq):
                if seq[k].isRest and k > 0 and not seq[k - 1].isRest:
                    j = k
                    while j < len(seq) and seq[j].isRest:
                        j += 1
                    gap = sum(Fraction(x.duration.quarterLength).limit_denominator(96) for x in seq[k:j])
                    if j < len(seq) and gap < Fraction(1, 2):
                        m_ = seq[k].getContextByClass("Measure")
                        add("short-rest-in-tune", part, m_.number if m_ else 0, f"{gap} beat gap between notes")
                    k = j
                else:
                    k += 1
        for m in part.getElementsByClass("Measure"):
            bar = m.number
            if m.keySignature is not None and bar > 1:
                if last_key_bar is not None and bar - last_key_bar < 6 and part is score.parts[0]:
                    add("key-change-soon", part, bar, f"{bar - last_key_bar} bars after the last one")
                last_key_bar = bar
            elif m.keySignature is not None:
                last_key_bar = bar
            if len(m.voices) > 2:
                add("too-many-voices", part, bar, f"{len(m.voices)} voices")
            ks = m.keySignature or m.getContextByClass("KeySignature")
            key_alter = {p.step: p.alter for p in (ks.alteredPitches if ks else [])}
            state: dict[tuple[str, int], float] = {}
            items = sorted(((Fraction(el.getOffsetInHierarchy(m)).limit_denominator(96), not el.duration.isGrace, i, el)
                            for i, el in enumerate(m.recurse().notesAndRests)), key=lambda x: x[:3])
            rests = 0
            for off, _, _, el in items:
                ql = Fraction(el.duration.quarterLength).limit_denominator(96)
                tuplets = el.duration.tuplets
                if len(tuplets) > 1:
                    add("nested-tuplet", part, bar, f"beat {float(off) + 1:g}: " + " in ".join(f"{t.numberNotesActual}:{t.numberNotesNormal}" for t in tuplets))
                elif tuplets and (tuplets[0].numberNotesActual, tuplets[0].numberNotesNormal) != (3, 2):
                    add("odd-tuplet", part, bar, f"beat {float(off) + 1:g}: {tuplets[0].numberNotesActual}:{tuplets[0].numberNotesNormal}")
                if not el.duration.isGrace and 0 < ql < Fraction(1, 4):
                    add("too-short", part, bar, f"beat {float(off) + 1:g}: {el.duration.type} ({ql})")
                if el.duration.dots > 1:
                    add("double-dot", part, bar, f"beat {float(off) + 1:g}: {el.duration.type} with {el.duration.dots} dots")
                if el.isRest:
                    if not el.style.hideObjectOnPrint:
                        rests += 1
                    continue
                clef = el.getContextByClass("Clef")
                continuing = el.tie is not None and el.tie.type in ("stop", "continue")
                ottava = next(iter(el.getSpannerSites("Ottava")), None)
                shift = 0 if ottava is None else (1 if ottava.type.endswith("vb") or ottava.type.endswith("mb") else -1)
                lines = max((_ledgers(p, clef, shift) for p in el.pitches), default=0) if clef is not None else 0
                if lines > 4:
                    add("ledger-lines", part, bar, f"{el.pitches[0].nameWithOctave}: {lines} ledger lines")
                four_run = four_run + 1 if lines == 4 else 0
                if four_run == 3:
                    add("ledger-lines", part, bar, f"three notes in a row on four ledger lines (to {el.pitches[0].nameWithOctave})")
                for p in el.pitches:
                    k = (p.step, p.octave)
                    current = state.get(k, key_alter.get(p.step, 0.0))
                    alter = p.alter
                    printed = p.accidental is not None and p.accidental.displayStatus is True
                    if not continuing:
                        # A courtesy accidental is fine: the same letter was altered differently
                        # earlier in this bar (another octave) or in the bar before.
                        courtesy = any(s == p.step and a != alter for (s, _), a in state.items()) or \
                            before.get(p.step, alter) != alter
                        if printed and alter == current and not courtesy:
                            add("needless-accidental", part, bar, f"{p.nameWithOctave} (key/bar already gives it)")
                        elif not printed and alter != current:
                            add("missing-accidental", part, bar, f"{p.nameWithOctave} would read as {'flat' if current < 0 else 'sharp' if current > 0 else 'natural'}")
                        state[k] = alter  # a note tied over from the last bar doesn't set the bar's accidental
            before = {s: a for (s, _), a in state.items() if a != key_alter.get(s, 0.0)}
            if rests > 4:
                add("busy-rests", part, bar, f"{rests} rests")
            # Ties inside one beat that could be one note.
            for v in (m.voices or [m]):
                seq = [x for x in v.notes if not x.duration.isGrace]
                for a, b in zip(seq, seq[1:]):
                    if a.tie is None or a.tie.type not in ("start", "continue") or a.pitches != b.pitches:
                        continue
                    oa = Fraction(a.getOffsetInHierarchy(m)).limit_denominator(96)
                    end = oa + Fraction(a.duration.quarterLength + b.duration.quarterLength).limit_denominator(96)
                    joined = duration.Duration(end - oa)
                    if math.floor(oa) == math.floor(end - Fraction(1, 96)) and joined.type != "inexpressible" and joined.dots <= 1 and not joined.tuplets:
                        add("needless-tie", part, bar, f"beat {float(oa) + 1:g}: {a.duration.type} + {b.duration.type} = {joined.type}{'.' * joined.dots}")
    counts = Counter(r for r, *_ in found)
    by_bar = Counter(b for _, _, b, _ in found if b)
    return {"findings": found, "counts": {r: counts.get(r, 0) for r in RULES}, "worst": by_bar.most_common(5)}


def tidy_heading(xml: str) -> str:
    """The title once (music21 writes it as both work title and movement title) and no
    'Music21' placeholder as composer."""
    import re

    xml = xml.replace('<creator type="composer">Music21</creator>', "")
    if "<movement-title>" in xml:
        xml = re.sub(r"\s*<work>\s*<work-title>[^<]*</work-title>\s*</work>", "", xml, count=1)
    return xml


def repair_accidentals(path: str | pathlib.Path) -> dict:
    """Redo which accidentals a score prints (by the rule lint checks) and tidy its heading,
    leaving every note as it is. Returns the findings before and after."""
    from music21 import converter
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    from .transcribe import _print_accidentals

    path = pathlib.Path(path)
    before = lint(path)["counts"]
    score = converter.parse(str(path))
    for part in score.parts:
        _print_accidentals(part)
    xml = tidy_heading(GeneralObjectExporter(score).parse().decode("utf-8"))
    source = path.read_text(encoding="utf-8")
    import re

    m = re.search(r"<source>.*?</source>", source, re.S)
    if m and "<source>" not in xml:
        xml = xml.replace("</encoding>", f"</encoding>\n    {m.group(0)}", 1)
    path.write_text(xml, encoding="utf-8")
    return {"before": before, "after": lint(path)["counts"]}


def report(path: str, png_dir: str | None = None) -> dict:
    out = lint(path)
    print(pathlib.Path(path).name)
    for rule, n in out["counts"].items():
        if n:
            examples = [f"{p} bar {b}: {d}" for r, p, b, d in out["findings"] if r == rule][:3]
            print(f"  {rule:20} {n:5}   e.g. {'; '.join(examples)}")
    print("  worst bars:", out["worst"] or "none")
    if png_dir:
        from .render import render_png

        stem = pathlib.Path(path).stem
        shots = [(1, 8)] + [(max(1, b - 1), b + 2) for b, _ in out["worst"][:2]]
        for first, last in shots:
            print("  drew", render_png(path, pathlib.Path(png_dir) / f"{stem} bars {first}-{last}.png", first, last))
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    png = args[args.index("--png") + 1] if "--png" in args else None
    for f in [a for a in args if a != "--png" and a != png]:
        report(f, png)
