"""Chord names per bar for a score, so a chord chart can be checked against the notes.

Each segment's notes become a duration-weighted pitch-class profile, which is matched
against chord templates for all 12 roots. The lowest note decides the bass (C/E).
"""

from __future__ import annotations

import re
from collections import Counter

from .notes import Note, Score
from .web import pitch_class

_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_SHARPS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
# Keys spelled with flats (majors and their relative minors).
_FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Dm", "Gm", "Cm", "Fm", "Bbm", "Ebm"}

# suffix -> intervals above the root. Order breaks ties (simpler chords first).
TEMPLATES = {
    "": (0, 4, 7),
    "m": (0, 3, 7),
    "7": (0, 4, 7, 10),
    "m7": (0, 3, 7, 10),
    "maj7": (0, 4, 7, 11),
    "sus4": (0, 5, 7),
    "sus2": (0, 2, 7),
    "dim": (0, 3, 6),
    "m7b5": (0, 3, 6, 10),
    "dim7": (0, 3, 6, 9),
    "aug": (0, 4, 8),
    "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9),
    "5": (0, 7),
}

# Krumhansl-Kessler key profiles.
_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _profile(notes: list[Note], t0: float, t1: float) -> tuple[list[float], int | None]:
    weights = [0.0] * 12
    bass_pitch, bass_weight = None, 0.0
    for n in notes:
        overlap = min(n.end, t1) - max(n.start, t0)
        if overlap <= 0:
            continue
        weights[n.pitch % 12] += overlap
        if bass_pitch is None or n.pitch < bass_pitch:
            bass_pitch, bass_weight = n.pitch, overlap
    if bass_pitch is not None and bass_weight < 0.1 * (t1 - t0):
        # A passing low note is not the bass; use the lowest note that lasts.
        lasting = [n.pitch for n in notes if min(n.end, t1) - max(n.start, t0) >= 0.1 * (t1 - t0)]
        bass_pitch = min(lasting) if lasting else bass_pitch
    return weights, (bass_pitch % 12 if bass_pitch is not None else None)


def spelling_for(key: str | None) -> list[str]:
    if key is None:
        return _NAMES
    return _FLATS if key in _FLAT_KEYS else _SHARPS


def name_chord(weights: list[float], bass: int | None, names: list[str] = _NAMES) -> tuple[str | None, float]:
    """Best chord name and a 0-1 fit (share of the sounding weight its tones explain)."""
    total = sum(weights)
    if total <= 0:
        return None, 0.0
    best, best_score, best_fit = None, float("-inf"), 0.0
    for root in range(12):
        if weights[root] < 0.05 * total:
            continue  # never name a chord whose root is silent
        for k, (suffix, ivs) in enumerate(TEMPLATES.items()):
            tones = {(root + i) % 12 for i in ivs}
            inside = sum(weights[p] for p in tones)
            missing = sum(1 for p in tones if weights[p] < 0.05 * total)
            if len(ivs) == 4:
                # A 7th/6th only counts when it is held about as long as the triad tones,
                # not when it is a passing note.
                triad = sum(weights[(root + i) % 12] for i in ivs[:3]) / 3
                if weights[(root + ivs[3]) % 12] < 0.6 * triad:
                    continue
            score = inside - (total - inside) - missing * 0.25 * total / len(tones) - k * 0.001 * total
            if bass == root:
                score += 0.1 * total
            elif bass is not None and bass not in tones:
                score -= 0.05 * total
            if score > best_score:
                best, best_score, best_fit = (root, suffix, tones), score, inside / total
    root, suffix, tones = best
    name = names[root] + suffix
    if bass is not None and bass != root and bass in tones:
        name += "/" + names[bass]
    return name, round(best_fit, 2)


def chords_by_bar(score: Score, notes: list[Note], bars: tuple[int, int] | None = None, per_bar: int = 1, key: str | None = None) -> list[dict]:
    """[{bar, beat, chord, fit}] with per_bar segments per bar; consecutive repeats are kept.
    key (e.g. from estimate_key) picks sharp or flat spelling."""
    names = spelling_for(key)
    first, last = bars or (1, len(score.bars))
    out = []
    for bar in score.bars[first - 1:last]:
        span = (bar.end - bar.start) / per_bar
        for k in range(per_bar):
            t0 = bar.start + k * span
            weights, bass = _profile(notes, t0, t0 + span)
            chord, fit = name_chord(weights, bass, names)
            out.append({"bar": bar.number, "beat": round(1 + k * bar.numerator / per_bar, 2), "chord": chord or "N.C.", "fit": fit})
    return out


def estimate_key(notes: list[Note]) -> str | None:
    weights = [0.0] * 12
    for n in notes:
        weights[n.pitch % 12] += n.duration
    if not any(weights):
        return None

    def corr(profile, tonic):
        xs = [weights[(tonic + i) % 12] for i in range(12)]
        mx, my = sum(xs) / 12, sum(profile) / 12
        num = sum((x - mx) * (y - my) for x, y in zip(xs, profile))
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in profile)) ** 0.5
        return num / den if den else 0.0

    best = max(((corr(p, t), t, mode) for t in range(12) for p, mode in ((_MAJOR, ""), (_MINOR, "m"))))
    return _NAMES[best[1]] + best[2]


def _root_and_quality(chord: str) -> tuple[int, str] | None:
    m = re.match(r"([A-G][b#]?)(.*)", chord.split("/")[0])
    pc = pitch_class(m.group(1)) if m else None
    if pc is None:
        return None
    rest = m.group(2)
    minor = (rest.startswith("m") and not rest.startswith("maj")) or "dim" in rest
    return pc, "m" if minor else ""


def best_transpose(chart_chords: list[str], score_chords: list[str]) -> list[dict]:
    """Semitone shifts of the chart ranked by how well its harmony matches the score's.

    Both are reduced to (root, major/minor) histograms (pass every occurrence, not just
    distinct chords); match_pct is their overlap, so 100 means the same chords in the
    same proportions.
    """

    def histogram(chords):
        counts = Counter(rq for rq in map(_root_and_quality, chords) if rq)
        total = sum(counts.values())
        return {rq: c / total for rq, c in counts.items()} if total else {}

    chart, score = histogram(chart_chords), histogram(score_chords)
    if not chart or not score:
        return []
    ranked = []
    for shift in range(-5, 7):
        shifted = {((r + shift) % 12, q): w for (r, q), w in chart.items()}
        overlap = sum(min(w, shifted.get(rq, 0.0)) for rq, w in score.items())
        ranked.append({"transpose": shift, "match_pct": round(100 * overlap, 1)})
    ranked.sort(key=lambda r: (-r["match_pct"], abs(r["transpose"])))
    return ranked[:3]
