"""Piano sheets of real band files, held to piano-notation conventions.

Runs on the downloaded reference library (reference/, not in git); songs that aren't there
are skipped. Each song's counts are its baseline from when the sheet writer was last
improved: a change may make them better, not noticeably worse. When a change improves a
song, lower its baseline.
"""

from __future__ import annotations

import bisect
import glob
import pathlib

import pytest

from midi_coach import analysis, engraving, library, sheet
from midi_coach.notes import select_notes, suggest_hands

REFERENCE = library.REPO_ROOT / "reference"

# Readability findings a song may still have (engraving.lint); every other song must have none.
# Great Balls of Fire: its one-track piano gives the left hand chords over two octaves wide
# (see 'wide' below), which no clef or 8va can make readable.
LINT_ALLOWED = {"Jerry Lee Lewis - Great Balls of Fire.mid": {"ledger-lines": 1, "busy-octave-marks": 1}}

# file name: (key, suggested {hand: parts}, baseline counts)
SONGS = {
    "Pink Floyd - Great Gig in the Sky.mid": ("Gm", {"both": [2]}, dict(wide=0, hops=2, ledger=2, accidentals=85)),
    "The Beatles - Let It Be.mid": ("C", {"both": [3]}, dict(wide=0, hops=0, ledger=99, accidentals=8)),
    "Billy Joel - Piano Man [157].mid": ("C", {"right": [0], "left": [1]}, dict(wide=0, hops=0, ledger=18, accidentals=48)),
    "Journey - Don't Stop Believin.mid": ("Db", {"both": [0]}, dict(wide=0, hops=0, ledger=35, accidentals=0)),
    "The Doors - Light My Fire.mid": ("D", {"right": [0], "left": [6]}, dict(wide=0, hops=0, ledger=7, accidentals=264)),
    "Jerry Lee Lewis - Great Balls of Fire.mid": ("C", {"both": [0], "left": [1]}, dict(wide=59, hops=0, ledger=212, accidentals=198)),
    "Queen - Bohemian Rhapsody.mid": ("Bb", {"both": [2]}, dict(wide=3, hops=7, ledger=30, accidentals=246)),
}
MARK_REACH = 0.26  # beats: how far docs/notation.html looks for a note to mark


def _find(name: str) -> pathlib.Path | None:
    return next(REFERENCE.rglob(glob.escape(name)), None) if REFERENCE.is_dir() else None  # names have [brackets]


def _counts(score, xml: str) -> dict:
    """Convention breaks in a sheet: chords one hand can't reach (over a tenth), a line
    passed between the staves, notes on three or more ledger lines, accidentals the key
    signature doesn't supply, and graded notes with nothing drawn for their mark."""
    from music21 import converter

    notes, _ = select_notes(score)
    side = analysis.side_resolver(score)
    chords: dict = {}
    for n in notes:
        chords.setdefault((round(n.start, 2), side(n)), []).append(n.pitch)
    wide = sum(max(ps) - min(ps) > 16 for ps in chords.values())
    at: dict = {}
    for n in notes:
        at.setdefault(round(n.start, 2), []).append(n)
    times = sorted(at)
    hops = sum(1 for a, b in zip(times, times[1:]) if len(at[a]) == len(at[b]) == 1 and b - a < 0.6
               and abs(at[a][0].pitch - at[b][0].pitch) <= 4 and side(at[a][0]) != side(at[b][0]))

    ledger = accidentals = 0
    drawn: dict[int, list[float]] = {}
    for part in converter.parseData(xml).parts:
        for x in part.recurse().notes:
            ks = x.getContextByClass("KeySignature")  # the key signature in force at this note
            altered = {p.name for p in ks.alteredPitches} if ks else set()
            treble = type(x.getContextByClass("Clef")).__name__ == "TrebleClef"
            for p in x.pitches:
                ledger += (p.midi >= 88 or p.midi <= 53) if treble else (p.midi <= 33 or p.midi >= 67)
                if p.accidental is not None and p.accidental.name != "natural":
                    accidentals += p.name not in altered
                else:
                    accidentals += p.step in {a[0] for a in altered}
                if x.tie is None or x.tie.type == "start":
                    drawn.setdefault(p.midi, []).append(float(x.getOffsetInHierarchy(part)))
    for beats in drawn.values():
        beats.sort()

    def marked(n) -> bool:
        beats = drawn.get(n.pitch, [])
        k = bisect.bisect_left(beats, n.beat - MARK_REACH)
        return k < len(beats) and beats[k] < n.beat + MARK_REACH

    return dict(wide=wide, hops=hops, ledger=ledger, accidentals=accidentals, unmarked=sum(not marked(n) for n in notes))


@pytest.mark.parametrize("name", list(SONGS))
def test_band_file_sheet_follows_conventions(name, tmp_path, monkeypatch):
    path = _find(name)
    if path is None:
        pytest.skip(f"{name} isn't in the reference library")
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))  # no saved part choices or cached sheets
    library._score_cache.clear()
    key, parts, baseline = SONGS[name]
    score = library.get_score(str(path))
    suggested = suggest_hands(score)
    assert {h: suggested[h] for h in ("right", "left", "both") if suggested[h]} == parts, suggested["reasons"]
    out = sheet.build(score)
    assert out["key"] == key
    counts = _counts(score, out["xml"])
    assert counts.pop("unmarked") == 0  # every graded note has a drawn note for its mark
    worse = {k: (v, baseline[k]) for k, v in counts.items() if v > baseline[k] + max(2, baseline[k] // 10)}
    assert not worse, f"worse than the baseline (now, baseline): {worse}"
    # The readability rules (midi_coach.engraving): none broken, but for known hard cases.
    allowed = LINT_ALLOWED.get(name, {})
    broken = {r: n for r, n in engraving.lint(out["xml"])["counts"].items() if n > allowed.get(r, 0)}
    assert not broken, f"readability rules broken: {broken}"
