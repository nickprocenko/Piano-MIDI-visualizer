"""How hard a piece is: measured features, and a grade estimated from them.

features() measures a score, or a passage of it: how densely the notes come in each hand,
the shortest note values and how varied the rhythms are, chords and the widest stretch inside
one hand, leaps, the key signature and how chromatic the music is, range, length, and how much
the hands play together. estimate() turns the features into two grades (0 = Initial .. 8):

- the playing grade, from the notes alone, with no length in it. This is the one for a
  passage, a stage or a song section: being short does not make music easy.
- the whole-piece grade: the playing grade plus a length term (stamina and memory), capped at
  LENGTH_CAP grades and reported as its own reason. Exam boards set longer pieces at higher
  grades, so length predicts a board's grade well, but it says nothing about what is hard.

Note density is counted per beat, not per second, and length in beats, not minutes: the
tempos in source MIDI files are often an engraver's default (LilyPond writes 60 when no tempo
is marked), so anything measured in seconds inherits that error.

The model is plain coefficients (data/difficulty_model.json): no new dependencies. It is
fitted by calibrate() on the catalog pieces whose grade an exam board set (ABRSM, Trinity, or
RCM converted to ABRSM grades). It rates the easiest pieces too high (no Initial piece has a
board grade yet), so it is a prior for the AI placement and the user's override, never the
last word. Refit: python tools/fetch_pd_pieces.py calibrate.

    python -m midi_coach.atlas.difficulty <file> [first last]   features and the estimate
"""

from __future__ import annotations

import json
import math
import pathlib
import statistics
import sys

from . import PACKAGE

MODEL_PATH = PACKAGE / "data" / "difficulty_model.json"
# The playing grade's inputs: all of them tempo-free. The slower hand's density and the voices
# held inside one hand stand in for counterpoint. Other measured features are kept for reasons.
PLAYING = ("peak_npb", "fast_hand_npb", "slow_hand_npb", "shortest_beats_inv", "rhythm_variety", "max_chord",
           "max_span", "leap_rate", "key_accidentals", "chromatic_share", "hand_poly")
LENGTH = "log_beats"  # the whole-piece grade adds this, capped
LENGTH_CAP = 1.0  # grades
FEATURES = PLAYING + (LENGTH,)
CHORD_GAP = 0.03  # seconds: notes this close in one hand are one chord
PEAK_WINDOW = 4.0  # beats: the busiest stretch of this length sets peak_npb


def features(path: str | pathlib.Path, bars: tuple[int, int] | None = None) -> dict:
    """Measured features of a MIDI or MusicXML file (see FEATURES); bars=(first, last) measures
    only that passage (bar numbers as the score counts them, both included)."""
    from ..harmony import estimate_key
    from ..notes import load_score

    score = load_score(path)
    notes = sorted((n for n in score.notes if n.end > n.start), key=lambda n: (n.start, n.pitch))
    if bars:
        span = [b for b in score.bars if bars[0] <= b.number <= bars[1]]
        if not span:
            raise ValueError(f"No bars {bars[0]}-{bars[1]} in {path}")
        lo, hi_beat = span[0].start_beat, span[-1].end_beat
        notes = [n for n in notes if lo - 1e-3 <= n.beat < hi_beat - 1e-3]
    if not notes:
        raise ValueError(f"No notes in {path}" + (f" bars {bars[0]}-{bars[1]}" if bars else ""))
    parts = [p for p in score.parts if p.note_count]
    hi = max(parts, key=lambda p: p.mean_pitch).index if len(parts) > 1 else None
    hands = {"right": [n for n in notes if hi is None or n.part == hi]}
    hands["left"] = [n for n in notes if hi is not None and n.part != hi] or []
    if hi is None:  # one part: split at middle C
        hands = {"right": [n for n in notes if n.pitch >= 60], "left": [n for n in notes if n.pitch < 60]}
    seconds = max(n.end for n in notes) - notes[0].start or 1.0

    def chords(seq):
        groups, cur = [], []
        for n in seq:
            if cur and n.start - cur[0].start > CHORD_GAP:
                groups.append(cur)
                cur = []
            cur.append(n)
        if cur:
            groups.append(cur)
        return groups

    hand_groups = {h: chords(seq) for h, seq in hands.items()}
    all_groups = [g for gs in hand_groups.values() for g in gs]
    beats = sorted({round(n.beat, 4) for n in notes})
    durs = [round(score.beat_of(n.end) - n.beat, 3) for n in notes]
    shortest = min((d for d in durs if d > 0.02), default=1.0)
    top = [max(g, key=lambda n: n.pitch).pitch for g in hand_groups["right"]] or [n.pitch for n in notes]
    leaps = sum(1 for a, b in zip(top, top[1:]) if abs(a - b) > 7)
    key = estimate_key(notes) or "C"
    from .technique import PC, STEPS

    minor = key.endswith("m")
    tonic = PC.get(key[:-1] if minor else key, 0)
    scale = {(tonic + sum(STEPS["natural" if minor else "major"][:k])) % 12 for k in range(7)}
    fifths = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 5: 1, 10: 2, 3: 3, 8: 4, 1: 5}[(tonic + (3 if minor else 0)) % 12]
    poly = 0  # most notes one hand holds at once
    for seq in hands.values():
        ends: list[float] = []
        for n in seq:
            ends = [e for e in ends if e > n.start + 0.01] + [n.end]
            poly = max(poly, len(ends))
    rh_times = {round(g[0].start, 2) for g in hand_groups["right"]}
    lh_times = {round(g[0].start, 2) for g in hand_groups["left"]}
    together = len(rh_times & lh_times) / max(len(rh_times | lh_times), 1)
    total_beats = max(score.beat_of(max(n.end for n in notes)) - notes[0].beat, 1.0)

    def peak(groups):  # most onsets in any PEAK_WINDOW beats, per beat
        on = [g[0].beat for g in groups]
        best, j = 0, 0
        for i, b in enumerate(on):
            while on[j] < b - PEAK_WINDOW:
                j += 1
            best = max(best, i - j + 1)
        return best / PEAK_WINDOW

    return {
        "fast_hand_npb": round(max(len(gs) for gs in hand_groups.values()) / total_beats, 3),
        "slow_hand_npb": round(min(len(gs) for gs in hand_groups.values()) / total_beats, 3),
        "peak_npb": round(max(peak(gs) for gs in hand_groups.values()), 3),
        "log_beats": round(math.log(total_beats), 3),
        "beats": round(total_beats, 1),
        # In seconds, so only as good as the file's tempo: kept to show, never fitted.
        "notes_per_sec": round(len(notes) / seconds, 2),
        "fast_hand_nps": round(max(len(gs) for gs in hand_groups.values()) / seconds, 2),
        "slow_hand_nps": round(min(len(gs) for gs in hand_groups.values()) / seconds, 2),
        "hand_poly": poly,
        "shortest_beats_inv": round(1 / shortest, 2),
        "rhythm_variety": len({d for d in durs if d > 0.02}),
        "chord_share": round(sum(1 for g in all_groups if len(g) >= 2) / max(len(all_groups), 1), 3),
        "max_chord": max(len(g) for g in all_groups),
        "max_span": max(max(n.pitch for n in g) - min(n.pitch for n in g) for g in all_groups),
        "leap_rate": round(leaps / max(len(top) - 1, 1), 3),
        "key_accidentals": fifths,
        "chromatic_share": round(sum(1 for n in notes if n.pitch % 12 not in scale) / len(notes), 3),
        "range": max(n.pitch for n in notes) - min(n.pitch for n in notes),
        "together_share": round(together, 3),
        "minutes": round(seconds / 60, 2),
        "log_minutes": round(math.log(seconds / 60 + 0.25), 3),
        "bars": bars[1] - bars[0] + 1 if bars else len(score.bars),
        "key": key,
        "bpm": round(score.bpm_at(notes[0].start)),
        "time": f"{score.bars[0].numerator}/{score.bars[0].denominator}" if score.bars else "4/4",
        "_beats": len(beats),
    }


def load_model() -> dict | None:
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def estimate(feats: dict, model: dict | None = None) -> dict:
    """{grade: whole-piece grade (float), level (0-8), playing: the grade from the notes alone
    (use it for a passage), length: what length added (within ±LENGTH_CAP),
    reasons: [(feature, effect in grades)], with length as its own reason}."""
    model = model or load_model()
    if not model or "playing" not in model:
        raise FileNotFoundError("No difficulty model yet: run calibrate().")
    p = model["playing"]
    effects = {f: p["coef"][f] * (feats[f] - p["mean"][f]) / (p["sd"][f] or 1) for f in PLAYING}
    playing = p["intercept"] + sum(effects.values())
    ln = model["length"]
    length = max(-ln["cap"], min(ln["cap"], ln["coef"] * (feats[LENGTH] - ln["mean"])))
    reasons = sorted(effects.items(), key=lambda kv: -abs(kv[1]))[:4]
    if abs(length) >= 0.25:
        reasons.append(("length", length))
    grade = playing + length
    return {"grade": round(grade, 2), "level": max(0, min(8, round(grade))), "playing": round(playing, 2),
            "playing_level": max(0, min(8, round(playing))), "length": round(length, 2),
            "reasons": [(f, round(v, 2)) for f, v in reasons]}


def _ridge(data: list[tuple[dict, float]], names: tuple[str, ...], ridge: float) -> dict:
    """Ridge regression on standardised features, solved by Gauss-Jordan elimination."""
    mean = {f: statistics.fmean(r[0][f] for r in data) for f in names}
    sd = {f: statistics.pstdev([r[0][f] for r in data]) for f in names}
    X = [[(r[0][f] - mean[f]) / (sd[f] or 1) for f in names] for r in data]
    y = [r[1] for r in data]
    ym = statistics.fmean(y)
    k = len(names)
    a = [[sum(x[i] * x[j] for x in X) + (ridge if i == j else 0) for j in range(k)] + [sum(x[i] * (yy - ym) for x, yy in zip(X, y))]
         for i in range(k)]
    for c in range(k):  # Gauss-Jordan
        piv = max(range(c, k), key=lambda r: abs(a[r][c]))
        a[c], a[piv] = a[piv], a[c]
        for r in range(k):
            if r != c and a[c][c]:
                f = a[r][c] / a[c][c]
                a[r] = [x - f * yv for x, yv in zip(a[r], a[c])]
    coef = {f: (a[i][k] / a[i][i] if a[i][i] else 0.0) for i, f in enumerate(names)}
    return {"intercept": ym, "coef": coef, "mean": mean, "sd": sd}


def calibrate(rows: list[tuple[dict, float]], ridge: float = 1.0) -> dict:
    """Fit the model on rows of (features, known grade 0-8): the playing grade first, then the
    length term on what the playing grade leaves unexplained. Reports leave-one-out accuracy
    of both grades (within one grade, and the mean error)."""
    def fit(data):
        playing = _ridge(data, PLAYING, ridge)
        model = {"playing": playing, "length": {"coef": 0.0, "mean": 0.0, "cap": LENGTH_CAP}}
        resid = [(r[0][LENGTH], r[1] - estimate(r[0], model)["playing"]) for r in data]
        mean = statistics.fmean(x for x, _ in resid)
        var = sum((x - mean) ** 2 for x, _ in resid)
        model["length"].update(mean=mean, coef=sum((x - mean) * e for x, e in resid) / var if var else 0.0)
        return model

    model = fit(rows)
    errs: dict[str, list[float]] = {"grade": [], "playing": []}
    for i in range(len(rows)):  # leave one out
        est = estimate(rows[i][0], fit(rows[:i] + rows[i + 1:]))
        for k in errs:
            errs[k].append(abs(est[k] - rows[i][1]))
    n = max(len(rows), 1)
    model["within_one_grade"] = round(sum(e <= 1.0 for e in errs["grade"]) / n, 3)
    model["mean_error"] = round(statistics.fmean(errs["grade"]), 2) if rows else None
    model["playing_within_one_grade"] = round(sum(e <= 1.0 for e in errs["playing"]) / n, 3)
    model["playing_mean_error"] = round(statistics.fmean(errs["playing"]), 2) if rows else None
    model["pieces"] = len(rows)
    return model


if __name__ == "__main__":
    span = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else None
    f = features(sys.argv[1], span)
    print(json.dumps(f, indent=1))
    if load_model():
        print(estimate(f))
