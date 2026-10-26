"""Recover the beat grid of a MIDI file whose notes don't sit on its own bar lines.

Many downloaded files were sequenced on a precise grid but saved with the wrong tempo
map (one flat 120 BPM, say), so the notes slowly drift off the file's beats and every
bar number, the metronome and the sheet music come out wrong. This follows the beat
through the piece the way a drummer would: each chord is snapped to the nearest 16th
or triplet of the beat predicted from the last few seconds, and the tempo is re-fitted
as it goes, so slow drifts and section-by-section tempo changes are followed.

The result is a BeatMap (seconds <-> beats) that only changes the notation side:
notes keep their real times, so playback and grading are untouched. Truly free
playing (rubato, no click) doesn't lock on; track() then returns None.
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass, replace

from .notes import Bar, Note, Score

VERSION = 2  # bump when tracking changes, so cached maps are recomputed

CHORD_GAP = 0.035  # notes starting this close together are one onset
FIT_WINDOW = 24  # onsets used to re-fit the local tempo
RECENCY = 0.8  # weight of each older chord relative to the next in the tempo fit
MAX_STEP = 0.03  # the tempo may change by at most 3% per onset (so a fast fill can't double it)
TEMPO_RANGE = (0.6, 1.6)  # ... and stays within this factor of the file's own tempo
GOOD_MEDIAN_MS = 15.0
GOOD_SHARE = 0.85  # share of onsets within 35 ms of the recovered grid
MAX_WOBBLE = 0.04  # median tempo change from one chord to the next (sequenced ~1%, rubato ~15%)
MIN_STEADY = 0.5  # share of chord-to-chord tempo changes under 3%


TRIPLET_TOL = 0.025  # beats: a note counts as a triplet only when it sits this close to one


def snap(beat: float) -> float:
    """Nearest 16th, or a triplet-8th when the note sits right on one. (Taking whichever is
    nearer would let a slowly drifting grid hide its drift in made-up triplets.)"""
    g4, g3 = round(beat * 4) / 4, round(beat * 3) / 3
    return g3 if abs(beat - g3) < TRIPLET_TOL and abs(beat - g3) < abs(beat - g4) else g4


# Grid levels tried while following the tempo, coarsest first, with how far (in beats) an
# onset may sit from each and still be read as that rhythm.
_TRACK_GRIDS = ((1.0, 0.15), (0.5, 0.1), (0.25, 0.06), (1 / 3, TRIPLET_TOL))


def _track_snap(predicted: float) -> tuple[float, float] | None:
    """(grid beat, error) for an onset, reading it as the simplest rhythm that fits: a chord
    near a beat is on the beat and the tempo has drifted, not a 16th early. Without this a
    one-chord-per-beat passage hides a tempo change in ever-shifting 16ths."""
    for step, tol in _TRACK_GRIDS:
        g = round(predicted / step) * step
        if abs(predicted - g) <= tol:
            return g, predicted - g
    return None


def onsets(notes: list[Note]) -> list[tuple[float, float]]:
    """(time, file beat) of each chord, earliest note of the chord."""
    out: list[tuple[float, float]] = []
    for n in sorted(notes, key=lambda n: n.start):
        if not out or n.start - out[-1][0] > CHORD_GAP:
            out.append((n.start, n.beat))
    return out


@dataclass
class BeatMap:
    """Piecewise-linear seconds <-> beats through the tracked anchors."""

    secs: list[float]
    beats: list[float]

    def beat_at(self, t: float) -> float:
        return _interp(self.secs, self.beats, t)

    def sec_at(self, beat: float) -> float:
        return _interp(self.beats, self.secs, beat)

    def to_json(self) -> dict:
        return {"secs": [round(s, 5) for s in self.secs], "beats": [round(b, 5) for b in self.beats]}

    @classmethod
    def from_json(cls, data: dict) -> "BeatMap":
        return cls(list(data["secs"]), list(data["beats"]))


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if len(xs) == 1:
        return ys[0]
    i = max(1, min(len(xs) - 1, bisect.bisect_right(xs, x)))
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0


def _fit(points: list[tuple[float, float]], previous: float, low: float, high: float) -> tuple[float, float]:
    """Weighted least-squares beat = a + slope * t (recent chords count most, so a real tempo
    change shows within a few beats), with the slope kept near the previous one."""
    n = len(points)
    ws = [RECENCY ** (n - 1 - i) for i in range(n)]
    total = sum(ws)
    mt = sum(w * t for w, (t, _) in zip(ws, points)) / total
    mb = sum(w * b for w, (_, b) in zip(ws, points)) / total
    var = sum(w * (t - mt) ** 2 for w, (t, _) in zip(ws, points))
    slope = sum(w * (t - mt) * (b - mb) for w, (t, b) in zip(ws, points)) / var if var > 1e-9 else previous
    slope = min(max(slope, previous * (1 - MAX_STEP), low), previous * (1 + MAX_STEP), high)
    return mb - slope * mt, slope


def track(notes: list[Note], file_bpm: float) -> tuple[BeatMap, dict] | None:
    """Follow the beat through the notes. Returns (map, quality) or None if it doesn't lock."""
    points = onsets(notes)
    if len(points) < 16:
        return None
    bps = file_bpm / 60.0  # beats per second, refined as we go
    t0, b0 = points[0]
    start = snap(b0)  # the file's own grid is close at the start: keep its bar numbering
    anchors: list[tuple[float, float]] = [(t0, start)]
    a, slope = start - bps * t0, bps
    for t, _ in points[1:]:
        predicted = a + slope * t
        found = _track_snap(predicted)
        if found is None or found[0] <= anchors[-1][1]:
            # Faster than the grid (a roll, a grace note, 32nds) or well off it: placed by
            # the map like every note, but it doesn't steer the tempo.
            continue
        beat = found[0]
        anchors.append((t, beat))
        recent = anchors[-FIT_WINDOW:]
        if recent[-1][1] - recent[0][1] >= 2:  # at least two beats of context
            a, slope = _fit(recent, slope, bps * TEMPO_RANGE[0], bps * TEMPO_RANGE[1])
    if len(anchors) < 8:
        return None
    secs, beats = zip(*anchors)
    beat_map = _align(BeatMap(list(secs), list(beats)), notes)
    secs, beats = beat_map.secs, beat_map.beats
    # Judge the finished map: how far each onset lands from the grid it draws. (The running
    # prediction errors above overstate it while the tempo is catching up after a jump.)
    errors_ms = []
    for t, _ in points:
        b = beat_map.beat_at(t)
        local = beat_map.beat_at(t + 0.05) - beat_map.beat_at(t - 0.05)  # beats per 0.1 s
        errors_ms.append(abs(b - snap(b)) / max(local / 0.1, 1e-6) * 1000)
    good = sum(e <= 35 for e in errors_ms) / len(errors_ms)
    # A map can bend to fit anything, so also ask whether it is steady: on a real grid the
    # tempo barely moves from one chord to the next; forced onto rubato it jumps about.
    rates = [(b1 - b0) / (t1 - t0) for t0, t1, b0, b1 in zip(secs, secs[1:], beats, beats[1:]) if b1 - b0 >= 0.25 and t1 > t0]
    changes = [abs(r1 - r0) / r0 for r0, r1 in zip(rates, rates[1:])]
    steady = sum(c < 0.03 for c in changes) / len(changes) if changes else 0.0
    quality = {"median_ms": round(statistics.median(errors_ms), 1), "within_35ms": round(good, 3), "onsets": len(points),
               "tempo_wobble_pct": round(100 * statistics.median(changes), 1) if changes else None, "steady": round(steady, 2)}
    if quality["median_ms"] > GOOD_MEDIAN_MS or good < GOOD_SHARE or not changes \
            or statistics.median(changes) > MAX_WOBBLE or steady < MIN_STEADY:
        return None
    return beat_map, quality


def _weight(n: Note, beat_map: BeatMap) -> float:
    """How strongly a note marks a beat: low notes and long notes do (bass, chords)."""
    length = beat_map.beat_at(n.end) - beat_map.beat_at(n.start)
    return (2.0 if n.pitch < 55 else 1.0) * min(4.0, max(0.25, length))


REPAIR_SPAN = 16  # beats per stretch when checking for a slipped grid
REPAIR_MARGIN = 1.5  # a stretch counts as slipped when another offset fits this much better


def _on_grid(weights: list[tuple[float, float]], shift: float, period: float) -> float:
    return sum(w for b, w in weights if abs(((b - shift) / period) - round((b - shift) / period)) * period < 0.06)


def _repair_slips(beat_map: BeatMap, weights: list[tuple[float, float]]) -> BeatMap:
    """Undo fractional-beat slips. In a hard passage (a sudden tempo change with one chord
    per beat, say) the tracker can lose half a beat and then follow the tempo perfectly but
    offset, so everything after is written on the off-beats. Each stretch of REPAIR_SPAN
    beats gets the offset that puts its weight on the beats; where that offset changes and
    stays changed, the correction is eased in across the stretch where it happened."""
    if not weights:
        return beat_map
    last = max(b for b, _ in weights)
    offsets: list[float] = []
    for start in range(0, int(last) + 1, REPAIR_SPAN):
        span = [(b, w) for b, w in weights if start <= b < start + REPAIR_SPAN]
        prev = offsets[-1] if offsets else 0.0
        if len(span) < 4:
            offsets.append(prev)
            continue
        scores = {s: _on_grid(span, s, 1.0) for s in (0.0, 0.25, 0.5, 0.75)}
        best = max(scores, key=scores.get)
        keep = min(scores, key=lambda s: min(abs(s - prev), 1 - abs(s - prev)))  # the current offset
        offsets.append(best if scores[best] > REPAIR_MARGIN * max(scores[keep], 1e-9) else keep)
    # Only trust a change that the next stretch agrees with (one odd stretch is the music).
    for i in range(1, len(offsets) - 1):
        if offsets[i] != offsets[i - 1] and offsets[i + 1] != offsets[i]:
            offsets[i] = offsets[i - 1]
    if all(o == offsets[0] for o in offsets):
        return beat_map
    # Unwrap (0.75 -> 0.0 is a step of +0.25, not -0.75) and ease each change in.
    unwrapped = [offsets[0]]
    for o in offsets[1:]:
        step = (o - unwrapped[-1] + 0.5) % 1 - 0.5
        unwrapped.append(unwrapped[-1] + step)

    def correction(b: float) -> float:
        i = int(b // REPAIR_SPAN)
        if i <= 0:
            return unwrapped[0]
        if i >= len(unwrapped):
            return unwrapped[-1]
        frac = (b - i * REPAIR_SPAN) / REPAIR_SPAN
        return unwrapped[i - 1] + (unwrapped[i] - unwrapped[i - 1]) * frac

    return BeatMap(beat_map.secs, [b - correction(b) for b in beat_map.beats])


def _align(beat_map: BeatMap, notes: list[Note], beats_per_bar: int = 4) -> BeatMap:
    """Shift the tracked grid so that the weight falls on the beats, then the strongest notes
    on beat 1, and so the first note is in bar 1 - what a person writing it down would do.
    Tracking only fixes the tempo; this fixes where the beats and bar lines are."""
    pitched = [n for n in notes if n.part >= 0]
    weights = [(beat_map.beat_at(n.start), _weight(n, beat_map)) for n in pitched]
    beat_map = _repair_slips(beat_map, weights)
    weights = [(beat_map.beat_at(n.start), w) for n, (_, w) in zip(pitched, weights)]

    def on_grid(shift: float, period: float) -> float:
        return _on_grid(weights, shift, period)

    beat_shift = max((0.0, 0.25, 0.5, 0.75), key=lambda s: (on_grid(s, 1.0), -s))
    # Bar lines: harmony usually changes on beat 1, so a low chord that differs from the one
    # before counts extra (a left hand on beats 1 and 3 alone can't tell beat 1 from beat 3).
    changes: list[tuple[float, float]] = []
    previous: frozenset = frozenset()
    for t, _ in onsets([n for n in pitched if n.pitch < 60]):
        chord = frozenset(n.pitch % 12 for n in pitched if n.pitch < 60 and abs(n.start - t) <= CHORD_GAP)
        if chord != previous:
            changes.append((beat_map.beat_at(t), 3.0))
        previous = chord
    bar_weights = weights + changes
    bar_shift = max((beat_shift + k for k in range(beats_per_bar)),
                    key=lambda s: (_on_grid(bar_weights, s, beats_per_bar), -s))
    first = min((b for b, _ in weights), default=0.0) - bar_shift
    bar_shift += beats_per_bar * (first // beats_per_bar)  # start in bar 1
    return BeatMap(beat_map.secs, [b - bar_shift for b in beat_map.beats])


def apply(score: Score, beat_map: BeatMap, quality: dict) -> Score:
    """The score on its recovered grid. Bar lines stay on the same beats (so the file's bar
    numbers still hold) but move in time with the music; notes keep their real times."""
    notes = [replace(n, beat=snap(beat_map.beat_at(n.start))) for n in score.notes]
    last_beat = max((n.beat for n in notes), default=0.0)
    bars: list[Bar] = []
    template = score.bars or [Bar(1, 0.0, 0.0, 4, 4, 0.0, 4.0)]
    beat = template[0].start_beat
    while beat <= last_beat or not bars:
        src = template[min(len(bars), len(template) - 1)]
        length = src.end_beat - src.start_beat if len(bars) < len(template) else src.numerator * 4 / src.denominator
        bars.append(Bar(len(bars) + 1, beat_map.sec_at(beat), beat_map.sec_at(beat + length), src.numerator, src.denominator,
                        beat, beat + length))
        beat += length
    tempos: list[tuple[float, float]] = []
    for b in bars:
        bpm = round(60 * (b.end_beat - b.start_beat) / max(b.end - b.start, 1e-6), 1)
        if not tempos or abs(bpm - tempos[-1][1]) >= 0.5:
            tempos.append((b.start, bpm))
    out = Score(score.path, notes, score.parts, score.pedal, bars, tempos, score.duration, dict(score.hands), dict(score.roles))
    out.beat_map = beat_map
    out.regrid = quality
    out._played_live = False
    return out
