"""Aural work: examples to listen to, and grading taps and sung (or played-back) notes.

The examples are short MIDI files the coach plays on the keyboard (never shown on the
sheet: you're meant to hear them): a passage to tap the pulse of, a phrase to echo, the
same phrase with one note or rhythm changed, a passage loud then quiet, a cadence, a
modulation. Each generator returns its file and the answer. Grading:

  grade_taps   taps on any key against the beats (or a rhythm's notes): timing, how many
               were caught, and whether the strong beats were louder
  grade_sung   a sung or played-back line against the one played: the notes in order, an
               octave either way allowed (sing it where your voice is), a semitone off half right
  yin          the pitch of a stretch of microphone audio (the same algorithm and constants
               as the coach page's, which does it live in the browser)
"""

from __future__ import annotations

import math
import random
import statistics

import mido

from .technique import PC, STEPS

TAP_TOLERANCE = 0.15   # seconds a tap may miss its beat by and still count as that beat
YIN_THRESHOLD = 0.15
MIN_NOTE_SEC = 0.12    # a sung note: the pitch held this long
NOTE_CENTS = 40        # ...within this many cents
EXAMPLE_TEMPO = 84


# -- writing examples ------------------------------------------------------------------


def write_midi(path, notes: list[tuple[float, float, int, int]], bpm: float = EXAMPLE_TEMPO, beats_per_bar: int = 4) -> None:
    """notes: (start beat, end beat, pitch, velocity) -> a one-track MIDI file."""
    tpb = 480
    mid = mido.MidiFile(ticks_per_beat=tpb)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    tr.append(mido.MetaMessage("time_signature", numerator=beats_per_bar, denominator=4, time=0))
    ev = []
    for start, end, pitch, vel in notes:
        ev.append((round(start * tpb), 1, mido.Message("note_on", note=pitch, velocity=vel)))
        ev.append((round(end * tpb), 0, mido.Message("note_off", note=pitch, velocity=0)))
    ev.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for tick, _, msg in ev:
        tr.append(msg.copy(time=tick - last))
        last = tick
    mid.save(str(path))


def _degrees(key: str) -> tuple[int, list[int]]:
    minor = key.endswith("m")
    tonic = PC[key[:-1] if minor else key]
    steps = STEPS["harmonic" if minor else "major"]
    offs = [0]
    for k in range(14):
        offs.append(offs[-1] + steps[k % 7])
    return 60 + tonic - (12 if tonic > 6 else 0), offs


def _at(offs: list[int], deg: int) -> int:
    return offs[deg] if deg >= 0 else offs[7 + deg] - 12


def accompanied_passage(rng: random.Random, beats_per_bar: int, bars: int = 4, key: str = "C") -> list[tuple]:
    """A short passage with a clear pulse: a melody over the bass on each beat, the first
    beat of each bar a little louder (for tapping the pulse and naming the metre)."""
    base, offs = _degrees(key)
    notes = []
    deg = 0
    for b in range(bars):
        root = 0 if b in (0, bars - 1) else rng.choice([3, 4, 0])
        for k in range(beats_per_bar):
            t = b * beats_per_bar + k
            strong = k == 0
            notes.append((t, t + 0.9, base - 24 + _at(offs, root if strong else root + 4), 92 if strong else 62))
            for half in (0, 0.5) if rng.random() < 0.4 else (0,):
                deg = max(-2, min(7, deg + rng.choice([-1, 1, 2, -2, 0])))
                if b == bars - 1 and k == beats_per_bar - 1:
                    deg = 0
                notes.append((t + half, t + half + (0.45 if half or len(notes) % 2 else 0.9), base + _at(offs, deg), 80 if strong else 66))
    return notes


def rhythm_phrase(rng: random.Random, beats_per_bar: int, bars: int = 2, key: str = "C") -> list[tuple]:
    """One line to tap (or sing) back: crotchets, quavers, minims, ending on a long note."""
    base, offs = _degrees(key)
    cells = [(1,), (0.5, 0.5), (2,), (1.5, 0.5)]
    notes, t, deg = [], 0.0, 0
    end = bars * beats_per_bar
    while t < end - 1e-9:
        left = end - t
        if left <= 2:
            dur = (left,)
        else:
            dur = rng.choice([c for c in cells if sum(c) <= left - 1] or [(1,)])
        for d in dur:
            deg = max(0, min(4, deg + rng.choice([-1, 1, 0, 2, -2])))
            notes.append((t, t + d * 0.95, base + _at(offs, deg), 76))
            t += d
    return notes


def echo_phrase(rng: random.Random, bars: int, key: str, span: int, beats_per_bar: int = 4) -> list[tuple]:
    """A phrase to sing back: steps within `span` scale degrees of the tonic (2 = tonic to
    mediant, 4 = to the dominant, 7 = an octave), starting on the tonic."""
    base, offs = _degrees(key)
    notes, t, deg = [], 0.0, 0
    end = bars * beats_per_bar
    while t < end - 1e-9:
        d = 2 if end - t <= 2 else rng.choice([1, 1, 2, 0.5])
        if d == 0.5:
            for _ in range(2):
                deg = max(0, min(span, deg + rng.choice([-1, 1])))
                notes.append((t, t + 0.45, base + _at(offs, deg), 76))
                t += 0.5
            continue
        if notes:
            deg = max(0, min(span, deg + rng.choice([-1, 1, -1, 1, 2, -2] if span > 2 else [-1, 1])))
        notes.append((t, t + d * 0.95, base + _at(offs, deg), 76))
        t += d
    return notes


def changed(rng: random.Random, notes: list[tuple], kind: str) -> tuple[list[tuple], dict]:
    """The phrase with one change: a note's pitch, or a rhythm (two notes merged/split).
    Returns (second version, {kind, where: 'beginning'|'end', index})."""
    out = list(notes)
    k = rng.randrange(1, len(out) - 1)
    if kind == "pitch":
        s, e, p, v = out[k]
        out[k] = (s, e, p + rng.choice([-2, 2, 1, -1]), v)
    else:
        s, e, p, v = out[k]
        half = (e - s) / 2
        out[k:k + 1] = [(s, s + half, p, v), (s + half, e, p, v)]
    return out, {"kind": kind, "where": "beginning" if notes[k][0] < notes[-1][1] / 2 else "end", "index": k}


def twice(a: list[tuple], b: list[tuple], gap_beats: float = 2.0) -> list[tuple]:
    """Two playings of a phrase, one after the other."""
    shift = max(n[1] for n in a) + gap_beats
    return a + [(s + shift, e + shift, p, v) for s, e, p, v in b]


def feature_passage(rng: random.Random, feature: str, key: str = "C") -> tuple[list[tuple], str, list[str]]:
    """A passage showing one feature, its answer, and the choices."""
    base, offs = _degrees(key if feature != "tonality" else rng.choice(["C", "Cm", "G", "Am", "D", "Em"]))
    line = [base + _at(offs, d) for d in (0, 1, 2, 3, 4, 3, 2, 1, 0, 2, 4, 7, 4, 2, 1, 0)]
    if feature == "dynamics":
        answer = rng.choice(["getting louder", "getting quieter", "loud", "quiet"])
        vel = {"getting louder": lambda k: 35 + 5 * k, "getting quieter": lambda k: 110 - 5 * k,
               "loud": lambda k: 105, "quiet": lambda k: 38}[answer]
        return [(k * 0.5, k * 0.5 + 0.45, p, vel(k)) for k, p in enumerate(line)], answer, \
            ["getting louder", "getting quieter", "loud", "quiet"]
    if feature == "articulation":
        answer = rng.choice(["smooth (legato)", "detached (staccato)"])
        length = 0.5 if answer.startswith("smooth") else 0.18
        return [(k * 0.5, k * 0.5 + length, p, 72) for k, p in enumerate(line)], answer, ["smooth (legato)", "detached (staccato)"]
    if feature == "tempo":
        answer = rng.choice(["getting faster", "getting slower", "staying the same"])
        notes, t = [], 0.0
        for k, p in enumerate(line):
            step = {"getting faster": 0.62 - 0.022 * k, "getting slower": 0.4 + 0.022 * k, "staying the same": 0.5}[answer]
            notes.append((t, t + step * 0.9, p, 72))
            t += step
        return notes, answer, ["getting faster", "getting slower", "staying the same"]
    if feature == "tonality":
        minor = (offs[2] == 3)
        chords = [0, 3, 4, 0]
        notes = []
        for b, root in enumerate(chords):
            for k, deg in enumerate((root, root + 2, root + 4, root + 2)):
                notes.append((b * 2 + k * 0.5, b * 2 + k * 0.5 + 0.45, base + _at(offs, deg), 70))
            notes.append((b * 2, b * 2 + 1.9, base - 12 + _at(offs, root), 60))
        return notes, "minor" if minor else "major", ["major", "minor"]
    raise ValueError(feature)


CADENCES = {"perfect": (4, 0), "imperfect": (0, 4), "interrupted": (4, 5), "plagal": (3, 0)}
CHORD_NAMES = {0: "I (tonic)", 1: "II (supertonic)", 3: "IV (subdominant)", 4: "V (dominant)", 5: "VI (submediant)"}


def cadence(rng: random.Random, kinds: list[str], key: str = "C") -> tuple[list[tuple], str, list[str], tuple[int, int]]:
    """A four-chord phrase ending in a cadence: (notes, kind, choices, the cadence's two chord degrees)."""
    kind = rng.choice(kinds)
    base, offs = _degrees(key)
    a, b = CADENCES[kind]
    lead = [0, rng.choice([3, 5, 1])]
    notes = []
    for k, root in enumerate(lead + [a, b]):
        t = k * 1.0
        dur = 1.9 if k == 3 else 0.95
        notes.append((t, t + dur, base - 12 + _at(offs, root), 68))
        for d in (root, root + 2, root + 4):
            notes.append((t, t + dur, base + _at(offs, d), 64))
    return notes, kind, kinds, (a, b)


def modulation(rng: random.Random, start_minor: bool = False) -> tuple[list[tuple], str, list[str]]:
    """A passage that settles in a new key: dominant, subdominant, or relative minor/major."""
    choices = ["dominant", "subdominant", "relative major" if start_minor else "relative minor"]
    target = rng.choice(choices)
    key = "Am" if start_minor else "C"
    base, offs = _degrees(key)
    shift = {"dominant": 7, "subdominant": 5, "relative minor": 9, "relative major": 3}[target]
    new_minor = (target == "relative minor") or (start_minor and target != "relative major")
    new_base, new_offs = base + shift - (12 if shift > 6 else 0), _degrees("Cm" if new_minor else "C")[1]
    notes, t = [], 0.0
    for root in (0, 3, 4, 0):
        for d in (root, root + 2, root + 4):
            notes.append((t, t + 0.95, base + _at(offs, d), 64))
        t += 1
    for root in (1, 4, 0) if not new_minor else (3, 4, 0):  # a cadence in the new key (II/IV - V - I)
        for d in (root, root + 2, root + 4):
            notes.append((t, t + (1.9 if root == 0 else 0.95), new_base + _at(new_offs, d), 66))
        t += 1
    return notes, target, choices


# -- grading ---------------------------------------------------------------------------


def grade_taps(ref: list[float], taps: list[tuple[float, int]], along: bool = True, beat_sec: float | None = None,
               accent_every: int | None = None, offset: float | None = None) -> dict:
    """Taps (seconds, velocity) against the reference onsets (seconds). along=True: tapping
    with the music (joined late is fine; the tempo must match); along=False: an echo,
    played back afterwards at its own pace (offset and tempo are both fitted). offset: where
    the reference's zero falls on the taps' clock, when known (tapping along: a steady pulse
    fits any beat, so only the real clock says which beats were the strong ones).
    Returns {score, timing, caught, extra, accent_ratio, detail}; timing and score 0-100."""
    if not taps or not ref:
        return {"score": 0.0, "timing": 0.0, "caught": 0, "extra": len(taps), "accent_ratio": None, "detail": "no taps"}
    beat = beat_sec or (statistics.median(b - a for a, b in zip(ref, ref[1:])) if len(ref) > 1 else 0.5)
    tol = max(TAP_TOLERANCE, beat / 3)
    times = [t for t, _ in taps]
    best = None
    span_ratio = (times[-1] - times[0]) / (ref[-1] - ref[0]) if len(times) > 1 and ref[-1] > ref[0] else 1.0
    starts = [offset] if offset is not None else None
    for j in range(1 if starts else min(4, len(ref))):  # the first tap could answer any of the first few onsets
        scale = 1.0 if along else span_ratio
        offset = starts[0] if starts else times[0] - scale * ref[j]
        for _ in range(2 if not along else 1):
            matched = _match(ref, times, offset, scale, tol)
            if not along and len(matched) >= 3:  # fit tempo and offset to the matches (least squares)
                xs = [ref[i] for i, _ in matched]
                ys = [times[k] for _, k in matched]
                mx, my = statistics.fmean(xs), statistics.fmean(ys)
                var = sum((x - mx) ** 2 for x in xs)
                if var > 0:
                    scale = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
                    offset = my - scale * mx
        matched = _match(ref, times, offset, scale, tol)
        errs = [abs(times[k] - (offset + scale * ref[i])) for i, k in matched]
        key = (len(matched), -statistics.median(errs) if errs else 0)
        if best is None or key > best[0]:
            best = (key, matched, errs, offset, scale)
    _, matched, errs, offset, scale = best
    first = min(i for i, _ in matched) if matched else 0
    due = ref[first:] if along else ref  # tapping along: joining late is fine, stopping early isn't
    caught = len(matched)
    extra = len(taps) - caught
    timing = max(0.0, 100 * (1 - (statistics.median(errs) if errs else 1) / 0.1))
    coverage = caught / max(len(due), 1)
    if along and len(due) < len(ref) * 0.5:  # joined in only for the last few beats
        coverage *= len(due) / (len(ref) * 0.5)
    score = max(0.0, 0.5 * timing + 50 * coverage - 5 * extra)
    accent = None
    if accent_every and matched:
        strong = [taps[k][1] for i, k in matched if i % accent_every == 0]
        weak = [taps[k][1] for i, k in matched if i % accent_every]
        if strong and weak:
            accent = statistics.fmean(strong) / max(statistics.fmean(weak), 1)
    detail = f"{caught} of {len(due)} beats, timing {timing:.0f}" + (f", strong beats x{accent:.2f}" if accent else "")
    return {"score": round(min(100.0, score), 1), "timing": round(timing, 1), "caught": caught, "extra": extra,
            "accent_ratio": round(accent, 2) if accent else None, "tempo_ratio": round(scale, 3), "detail": detail}


def _match(ref, times, offset, scale, tol) -> list[tuple[int, int]]:
    """Each onset to its nearest unused tap within tol: [(ref index, tap index)]."""
    used, out = set(), []
    for i, r in enumerate(ref):
        want = offset + scale * r
        k = min((k for k in range(len(times)) if k not in used), key=lambda k: abs(times[k] - want), default=None)
        if k is not None and abs(times[k] - want) <= tol:
            used.add(k)
            out.append((i, k))
    return out


def grade_sung(ref: list[int], sung: list[int], any_octave: bool = True) -> dict:
    """A sung (or played-back) line against the reference pitches, in order. An octave either
    way is fine (any_octave); a note a semitone off counts half; notes left out or added
    cost. Returns {score 0-100, matched, detail}."""
    if not sung:
        return {"score": 0.0, "matched": 0, "detail": "nothing heard"}
    shift = 0
    if any_octave:
        shift = 12 * round((statistics.median(sung) - statistics.median(ref)) / 12)
    s = [p - shift for p in sung]
    n, m = len(ref), len(s)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d = abs(ref[i - 1] - s[j - 1])
            gain = 1.0 if d == 0 else 0.5 if d == 1 else 0.0
            dp[i][j] = max(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1] + gain)
    got = dp[n][m]
    extra = max(0, m - n - 1)
    score = max(0.0, 100 * got / n - 4 * extra)
    return {"score": round(score, 1), "matched": got, "detail": f"{got:g} of {n} notes" + (f", {m - n} extra" if m > n else "")}


# -- pitch detection (the same as the coach page's, for tests and offline use) -----------------


def yin(samples, sr: int, threshold: float = YIN_THRESHOLD, fmin: float = 70.0, fmax: float = 1100.0) -> float | None:
    """The fundamental frequency of a short window (YIN, de Cheveigne & Kawahara 2002), or
    None when no clear pitch. samples: a sequence of floats."""
    n = len(samples)
    tmax = min(n // 2, int(sr / fmin))
    tmin = max(2, int(sr / fmax))
    diff = [0.0] * (tmax + 1)
    for tau in range(1, tmax + 1):
        acc = 0.0
        for i in range(n - tmax):
            d = samples[i] - samples[i + tau]
            acc += d * d
        diff[tau] = acc
    cmnd = [1.0] * (tmax + 1)
    running = 0.0
    for tau in range(1, tmax + 1):
        running += diff[tau]
        cmnd[tau] = diff[tau] * tau / running if running else 1.0
    tau = tmin
    while tau < tmax:
        if cmnd[tau] < threshold:
            while tau + 1 < tmax and cmnd[tau + 1] < cmnd[tau]:
                tau += 1
            break
        tau += 1
    else:
        return None
    if 0 < tau < tmax:  # parabolic interpolation between the neighbours
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        den = a - 2 * b + c
        tau = tau + (a - c) / (2 * den) if den else tau
    return sr / tau


def notes_from_track(track: list[tuple[float, float | None]]) -> list[dict]:
    """A pitch track [(seconds, Hz or None)] -> sung notes [{midi, start, end, cents}]: a run
    of frames within NOTE_CENTS of one note, lasting MIN_NOTE_SEC or more."""
    out = []
    run: list[tuple[float, float]] = []

    def flush():
        if len(run) >= 2 and run[-1][0] - run[0][0] >= MIN_NOTE_SEC:
            mids = [m for _, m in run]
            mid = statistics.median(mids)
            out.append({"midi": round(mid), "start": run[0][0], "end": run[-1][0], "cents": round(100 * (mid - round(mid)))})

    for t, hz in track:
        m = 69 + 12 * math.log2(hz / 440) if hz else None
        if m is not None and run and abs(m - statistics.median(x for _, x in run)) * 100 <= NOTE_CENTS:
            run.append((t, m))
            continue
        flush()
        run = [(t, m)] if m is not None else []
    flush()
    return out
