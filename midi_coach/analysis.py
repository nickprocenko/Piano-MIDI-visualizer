"""Performance analysis: standalone take stats and take-vs-reference comparison.

Comparison pipeline
-------------------
1. Group notes into onset "chords" (reference: 30 ms, take: 70 ms tolerance).
2. Align the chord sequences with dynamic programming (Jaccard cost on pitch
   sets, near-miss pitches count as substitutions). Leading/trailing reference
   material is free when no bar range is given, so a take of bars 9-16 is
   detected automatically.
3. Match individual notes inside aligned chords -> correct / wrong / missed /
   extra, then rescue split chords using the time map.
4. Build a time map (reference seconds -> take seconds) from matched chords.
   Timing errors are residuals against a *local* fit, so playing slower than
   the score is not punished; tempo drift is reported separately.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

from .notes import Note, Score, note_name, pedal_intervals, _name_side

REF_GROUP_TOL = 0.03
TAKE_GROUP_TOL = 0.07
GAP_COST = 0.6
NEAR_PITCH = 2


# ---------------------------------------------------------------------------
# Grouping + alignment
# ---------------------------------------------------------------------------


@dataclass
class Group:
    notes: list[Note]
    onset: float
    mask: int = 0


def group_onsets(notes: list[Note], tol: float) -> list[Group]:
    groups: list[Group] = []
    for n in sorted(notes, key=lambda n: (n.start, n.pitch)):
        if groups and n.start - groups[-1].onset <= tol:
            groups[-1].notes.append(n)
        else:
            groups.append(Group([n], n.start))
        groups[-1].mask |= 1 << n.pitch
    return groups


def _min_pitch_distance(a: int, b: int) -> int:
    pa = [p for p in range(128) if a >> p & 1]
    pb = [p for p in range(128) if b >> p & 1]
    return min(abs(x - y) for x in pa for y in pb)


def _match_cost(a: int, b: int) -> float:
    inter = (a & b).bit_count()
    if inter:
        return 1.0 - inter / (a | b).bit_count()
    return 1.0 if _min_pitch_distance(a, b) <= NEAR_PITCH else 1.5


def align_groups(ref: list[Group], take: list[Group], free_ref_ends: bool) -> list[tuple[int | None, int | None]]:
    """Semi-global alignment of chord sequences. Returns (ref_idx, take_idx) pairs."""
    n, m = len(ref), len(take)
    take_masks = [g.mask for g in take]
    prev = [j * GAP_COST for j in range(m + 1)]
    back = [bytearray(m + 1) for _ in range(n + 1)]  # 0 diag, 1 skip ref, 2 skip take
    for j in range(1, m + 1):
        back[0][j] = 2
    end_cost = [prev[m]]  # cost of having consumed the whole take at each ref row
    cost_cache: dict[tuple[int, int], float] = {}
    for i in range(1, n + 1):
        cur = [0.0] * (m + 1)
        cur[0] = 0.0 if free_ref_ends else i * GAP_COST
        row = back[i]
        row[0] = 1
        rm = ref[i - 1].mask
        for j in range(1, m + 1):
            key = (rm, take_masks[j - 1])
            c = cost_cache.get(key)
            if c is None:
                c = cost_cache[key] = _match_cost(*key)
            best, move = prev[j - 1] + c, 0
            up = prev[j] + GAP_COST
            if up < best:
                best, move = up, 1
            left = cur[j - 1] + GAP_COST
            if left < best:
                best, move = left, 2
            cur[j] = best
            row[j] = move
        end_cost.append(cur[m])
        prev = cur

    end_i = n
    if free_ref_ends:
        end_i = min(range(n + 1), key=lambda i: (end_cost[i], i))  # ties -> earliest
    pairs: list[tuple[int | None, int | None]] = []
    i, j = end_i, m
    while i > 0 or j > 0:
        if j == 0 and free_ref_ends:
            break
        move = back[i][j]
        if move == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif move == 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


# ---------------------------------------------------------------------------
# Time map
# ---------------------------------------------------------------------------


def _linfit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least squares y = a + b x. Returns (a, b)."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx < 1e-12:
        return my, 1.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


class TimeMap:
    """Monotone mapping between reference time and take time."""

    def __init__(self, points: list[tuple[float, float]]) -> None:
        pts = sorted(points)
        clean: list[tuple[float, float]] = []
        for r, t in pts:
            if clean and (r - clean[-1][0] < 1e-6 or t <= clean[-1][1]):
                continue
            clean.append((r, t))
        if not clean:
            clean = [(0.0, 0.0)]
        self.ref = [p[0] for p in clean]
        self.take = [p[1] for p in clean]
        if len(clean) >= 2:
            self.a, self.slope = _linfit(self.ref, self.take)
            if self.slope <= 0.05:
                self.slope = 1.0
        else:
            self.slope = 1.0
            self.a = self.take[0] - self.ref[0]

    def take_at(self, r: float) -> float:
        xs, ys = self.ref, self.take
        if r <= xs[0]:
            return ys[0] + (r - xs[0]) * self.slope
        if r >= xs[-1]:
            return ys[-1] + (r - xs[-1]) * self.slope
        i = bisect_right(xs, r)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return y0 + (y1 - y0) * (r - x0) / (x1 - x0)

    def ref_at(self, t: float) -> float:
        xs, ys = self.take, self.ref
        if t <= xs[0]:
            return ys[0] + (t - xs[0]) / self.slope
        if t >= xs[-1]:
            return ys[-1] + (t - xs[-1]) / self.slope
        i = bisect_right(xs, t)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return y0 + (y1 - y0) * (t - x0) / (x1 - x0)

    def local_slope(self, r0: float, r1: float, min_points: int = 3) -> float | None:
        lo, hi = bisect_left(self.ref, r0), bisect_right(self.ref, r1)
        if hi - lo < min_points:
            return None
        xs, ys = self.ref[lo:hi], self.take[lo:hi]
        if xs[-1] - xs[0] < 0.3 * (r1 - r0):
            return None
        _, b = _linfit(xs, ys)
        return b if b > 0.05 else None

    def predict_excluding(self, r: float, window: float) -> float:
        lo, hi = bisect_left(self.ref, r - window), bisect_right(self.ref, r + window)
        xs, ys = [], []
        for k in range(lo, hi):
            if abs(self.ref[k] - r) > 1e-6:
                xs.append(self.ref[k])
                ys.append(self.take[k])
        if len(xs) >= 2 and xs[-1] - xs[0] > 1e-3:
            a, b = _linfit(xs, ys)
            return a + b * r
        return self.a + self.slope * r


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stats(values: list[float]) -> dict:
    if not values:
        return {}
    vs = sorted(values)
    return {
        "mean": round(statistics.fmean(vs), 1),
        "median": round(statistics.median(vs), 1),
        "std": round(statistics.pstdev(vs), 1) if len(vs) > 1 else 0.0,
        "min": round(vs[0], 1),
        "max": round(vs[-1], 1),
    }


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx < 1e-9 or sy < 1e-9:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def side_resolver(score: Score, split_note: int = 60):
    """Return a function Note -> 'right'/'left' for reference notes."""
    playable = [p for p in score.parts if p.note_count > 0]
    sides = {p.index: _name_side(p.name) for p in playable}
    if any(s == "right" for s in sides.values()) and any(s == "left" for s in sides.values()):
        return lambda n: sides.get(n.part) or ("right" if n.pitch >= split_note else "left")
    if len(playable) == 2:
        hi, lo = sorted(playable, key=lambda p: -p.mean_pitch)
        return lambda n: "right" if n.part == hi.index else "left"
    return lambda n: "right" if n.pitch >= split_note else "left"


def _pedal_coverage(intervals: list[tuple[float, float]], t0: float, t1: float) -> tuple[float, int]:
    """Fraction of [t0, t1) with pedal down, and number of releases inside it."""
    span = max(t1 - t0, 1e-6)
    covered = 0.0
    releases = 0
    for a, b in intervals:
        covered += max(0.0, min(b, t1) - max(a, t0))
        if t0 < b < t1:
            releases += 1
    return covered / span, releases


# ---------------------------------------------------------------------------
# Standalone analysis (no reference)
# ---------------------------------------------------------------------------


def analyze_take(notes: list[Note], pedal: list[tuple[float, int]], split_note: int = 60) -> dict:
    if not notes:
        return {"error": "Take contains no notes."}
    t0 = notes[0].start
    t_end = max(n.end for n in notes)
    duration = t_end - t0
    groups = group_onsets(notes, TAKE_GROUP_TOL)
    iois = [b.onset - a.onset for a, b in zip(groups, groups[1:])]

    # Pulse estimate from the most common inter-onset interval cluster.
    pulse = None
    short = sorted(i for i in iois if 0.08 <= i <= 1.5)
    if len(short) >= 8:
        best_count, best_center = 0, None
        for center in short:
            count = sum(1 for i in short if abs(i - center) <= 0.15 * center)
            if count > best_count:
                best_count, best_center = count, center
        cluster = [i for i in short if abs(i - best_center) <= 0.15 * best_center]
        unit = statistics.median(cluster)
        pulse = {
            "most_common_interval_ms": round(unit * 1000),
            "as_bpm": round(60 / unit, 1),
            "note": "Interval-based estimate; the true beat may be half or double this.",
        }

    # Evenness of runs: consecutive intervals within 35% of each other.
    run_cvs: list[float] = []
    run: list[float] = []
    for ioi in iois:
        if run and abs(ioi - statistics.fmean(run)) <= 0.35 * statistics.fmean(run):
            run.append(ioi)
        else:
            if len(run) >= 4:
                run_cvs.append(statistics.pstdev(run) / statistics.fmean(run))
            run = [ioi] if 0.05 <= ioi <= 1.5 else []
    if len(run) >= 4:
        run_cvs.append(statistics.pstdev(run) / statistics.fmean(run))

    pauses = sorted(
        ({"at_sec": round(a.onset - t0 + (b.onset - a.onset), 2), "gap_sec": round(b.onset - a.onset, 2)}
         for a, b in zip(groups, groups[1:]) if b.onset - a.onset > 1.0),
        key=lambda p: -p["gap_sec"],
    )[:6]

    right = [n for n in notes if n.pitch >= split_note]
    left = [n for n in notes if n.pitch < split_note]

    # Velocity contour in ~10 segments.
    segments = []
    if duration > 0:
        step = duration / 10
        for k in range(10):
            a, b = t0 + k * step, t0 + (k + 1) * step
            vs = [n.velocity for n in notes if a <= n.start < b]
            segments.append(round(statistics.fmean(vs)) if vs else None)

    melody_lift = []
    for g in groups:
        if len(g.notes) >= 2:
            top = max(g.notes, key=lambda n: n.pitch)
            others = [n.velocity for n in g.notes if n is not top]
            melody_lift.append(top.velocity - statistics.fmean(others))

    singles = [g.notes[0] for g in groups if len(g.notes) == 1]
    gaps = [b.start - a.end for a, b in zip(singles, singles[1:]) if b.start - a.start < 1.0]

    p_int = pedal_intervals(pedal, t_end)
    pedal_time = sum(b - a for a, b in p_int)

    return {
        "duration_sec": round(duration, 2),
        "notes": len(notes),
        "notes_per_sec": round(len(notes) / duration, 2) if duration > 0 else None,
        "range": f"{note_name(min(n.pitch for n in notes))}-{note_name(max(n.pitch for n in notes))}",
        "chords_3plus": sum(1 for g in groups if len(g.notes) >= 3),
        "pulse": pulse,
        "evenness": {
            "runs_measured": len(run_cvs),
            "median_interval_cv_pct": round(statistics.median(run_cvs) * 100, 1) if run_cvs else None,
            "note": "Lower is steadier; under ~8% is even, over ~15% is uneven.",
        },
        "longest_pauses": pauses,
        "velocity": _stats([n.velocity for n in notes]),
        "velocity_contour_10_segments": segments,
        "hands_by_split": {
            "split_at": note_name(split_note),
            "right": {"notes": len(right), "mean_velocity": round(statistics.fmean([n.velocity for n in right]), 1) if right else None},
            "left": {"notes": len(left), "mean_velocity": round(statistics.fmean([n.velocity for n in left]), 1) if left else None},
        },
        "melody_lift_velocity": round(statistics.fmean(melody_lift), 1) if melody_lift else None,
        "articulation": {
            "median_note_ms": round(statistics.median(n.duration for n in notes) * 1000),
            "single_note_legato_overlap_pct": round(100 * sum(1 for g in gaps if g <= 0) / len(gaps), 1) if gaps else None,
            "median_gap_between_single_notes_ms": round(statistics.median(gaps) * 1000) if gaps else None,
        },
        "pedal": {
            "presses": len(p_int),
            "down_pct_of_take": round(100 * pedal_time / duration, 1) if duration > 0 else 0,
            "mean_press_sec": round(pedal_time / len(p_int), 2) if p_int else None,
        },
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


@dataclass
class Alignment:
    correct: list[tuple[Note, Note]] = field(default_factory=list)
    wrong: list[tuple[Note, Note]] = field(default_factory=list)
    missed: list[Note] = field(default_factory=list)
    extra: list[Note] = field(default_factory=list)
    tmap: TimeMap | None = None
    ref_scope: tuple[float, float] = (0.0, 0.0)


def align(ref_notes: list[Note], take_notes: list[Note], free_ref_ends: bool) -> Alignment:
    ref_groups = group_onsets(ref_notes, REF_GROUP_TOL)
    take_groups = group_onsets(take_notes, TAKE_GROUP_TOL)
    pairs = align_groups(ref_groups, take_groups, free_ref_ends)
    res = Alignment()
    points: list[tuple[float, float]] = []
    matched_ref_idx = [i for i, j in pairs if i is not None and j is not None]
    for gi, gj in pairs:
        if gi is not None and gj is None:
            res.missed.extend(ref_groups[gi].notes)
            continue
        if gi is None and gj is not None:
            res.extra.extend(take_groups[gj].notes)
            continue
        r_left = list(ref_groups[gi].notes)
        t_left = list(take_groups[gj].notes)
        onsets = []
        for r in list(r_left):
            same = [t for t in t_left if t.pitch == r.pitch]
            if same:
                t = same[0]
                res.correct.append((r, t))
                onsets.append(t.start)
                r_left.remove(r)
                t_left.remove(t)
        # Leftovers: nearest-pitch substitutions, rest missed / extra.
        for r in sorted(r_left, key=lambda n: n.pitch):
            if not t_left:
                res.missed.append(r)
                continue
            t = min(t_left, key=lambda n: abs(n.pitch - r.pitch))
            if abs(t.pitch - r.pitch) <= 4:
                res.wrong.append((r, t))
                onsets.append(t.start)
                t_left.remove(t)
            else:
                res.missed.append(r)
        res.extra.extend(t_left)
        if onsets:
            points.append((ref_groups[gi].onset, statistics.fmean(onsets)))

    res.tmap = TimeMap(points)
    if matched_ref_idx:
        first, last = ref_groups[matched_ref_idx[0]], ref_groups[matched_ref_idx[-1]]
        res.ref_scope = (first.onset, last.onset)

    # Rescue chords the take split into two onset groups.
    remaining_extra = list(res.extra)
    still_missed = []
    for r in res.missed:
        predicted = res.tmap.take_at(r.start)
        cand = [t for t in remaining_extra if t.pitch == r.pitch and abs(t.start - predicted) <= 0.15]
        if cand:
            t = min(cand, key=lambda n: abs(n.start - predicted))
            res.correct.append((r, t))
            remaining_extra.remove(t)
        else:
            still_missed.append(r)
    res.missed = still_missed
    res.extra = remaining_extra
    return res


def compare(
    score: Score,
    ref_notes: list[Note],
    take_notes: list[Note],
    take_pedal: list[tuple[float, int]],
    bars_given: bool,
    split_note: int = 60,
    detail: str = "normal",
) -> dict:
    if not ref_notes:
        return {"error": "Reference selection contains no notes (check hand / bars)."}
    if not take_notes:
        return {"error": "Take contains no notes."}

    al = align(ref_notes, take_notes, free_ref_ends=not bars_given)
    if len(al.correct) < max(2, 0.1 * min(len(ref_notes), len(take_notes))):
        return {"error": "Almost nothing in the take matches the reference - check the piece, hand and bars."}
    tm = al.tmap
    side = side_resolver(score, split_note)

    # Restrict reference to the detected scope when bars weren't given.
    if not bars_given:
        s0, s1 = al.ref_scope
        in_scope = lambda n: s0 - 1e-6 <= n.start <= s1 + 1e-6  # noqa: E731
        ref_scope_notes = [n for n in ref_notes if in_scope(n)]
    else:
        ref_scope_notes = ref_notes
    first_bar = score.position(ref_scope_notes[0].start)[0] if ref_scope_notes else 1
    last_bar = score.position(ref_scope_notes[-1].start)[0] if ref_scope_notes else 1
    bar_list = [b for b in score.bars if first_bar <= b.number <= last_bar]

    n_ref = len(ref_scope_notes)
    n_correct = len(al.correct)
    n_take = len(take_notes)
    precision = n_correct / n_take if n_take else 0.0
    recall = n_correct / n_ref if n_ref else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    # --- Timing -----------------------------------------------------------
    typical_bar = statistics.median([b.end - b.start for b in bar_list]) if bar_list else 2.0
    window = max(2.0, 2 * typical_bar)
    group_pred: dict[float, float] = {}
    timing: list[tuple[Note, Note, float]] = []
    for r, t in al.correct + al.wrong:
        key = round(r.start, 4)
        if key not in group_pred:
            group_pred[key] = tm.predict_excluding(r.start, window)
        timing.append((r, t, t.start - group_pred[key]))
    abs_ms = sorted(abs(d) * 1000 for _, _, d in timing)
    timing_mad = statistics.median(abs_ms) if abs_ms else 0.0

    by_side_dev: dict[str, list[float]] = {"right": [], "left": []}
    for r, _, d in timing:
        by_side_dev[side(r)].append(abs(d) * 1000)

    # Hand asynchrony: chords containing both hands in the reference.
    chord_sides: dict[float, dict[str, list[float]]] = {}
    for r, t in al.correct:
        chord_sides.setdefault(round(r.start, 4), {"right": [], "left": []})[side(r)].append(t.start)
    asyncs = [
        (statistics.fmean(v["right"]) - statistics.fmean(v["left"])) * 1000
        for v in chord_sides.values() if v["right"] and v["left"]
    ]

    # --- Tempo ------------------------------------------------------------
    ref_bpm0 = score.bpm_at(ref_scope_notes[0].start) if ref_scope_notes else 120.0
    global_bpm = ref_bpm0 / tm.slope
    bar_bpm: dict[int, float] = {}
    for b in bar_list:
        slope = tm.local_slope(b.start, b.end)
        if slope:
            bar_bpm[b.number] = score.bpm_at(b.start) / slope
    bpms = list(bar_bpm.values())
    tempo_cv = statistics.pstdev(bpms) / statistics.fmean(bpms) if len(bpms) >= 2 else 0.0
    med_bpm = statistics.median(bpms) if bpms else global_bpm
    trend = None
    if len(bpms) >= 4:
        xs = [float(k) for k in bar_bpm]
        _, b = _linfit(xs, bpms)
        trend = round(b * 10, 1)

    hesitations = []
    for (r0, t0), (r1, t1) in zip(zip(tm.ref, tm.take), list(zip(tm.ref, tm.take))[1:]):
        local = tm.local_slope(r0 - window, r1 + window) or tm.slope
        expected = (r1 - r0) * local
        actual = t1 - t0
        if actual - expected > max(0.25, 0.5 * expected):
            bar, beat = score.position(r1)
            hesitations.append({"bar": bar, "beat": beat, "extra_pause_ms": round((actual - expected) * 1000), "take_sec": round(t1 - take_notes[0].start, 2)})
    hesitations.sort(key=lambda h: -h["extra_pause_ms"])

    # --- Dynamics ---------------------------------------------------------
    ref_v = [r.velocity for r, _ in al.correct]
    take_v = [t.velocity for _, t in al.correct]
    expressive = len(ref_v) >= 3 and statistics.pstdev(ref_v) >= 4
    dynamics: dict = {
        "take_velocity": _stats([n.velocity for n in take_notes]),
        "by_hand_mean_velocity": {
            s: round(statistics.fmean([t.velocity for r, t in al.correct if side(r) == s]), 1)
            for s in ("right", "left") if any(side(r) == s for r, _ in al.correct)
        },
    }
    melody_lift = []
    for g in group_onsets(take_notes, TAKE_GROUP_TOL):
        if len(g.notes) >= 2:
            top = max(g.notes, key=lambda n: n.pitch)
            melody_lift.append(top.velocity - statistics.fmean(n.velocity for n in g.notes if n is not top))
    dynamics["melody_lift_velocity"] = round(statistics.fmean(melody_lift), 1) if melody_lift else None
    bar_vel: dict[int, tuple[float, float]] = {}
    for r, t in al.correct:
        bar = score.position(r.start)[0]
        bar_vel.setdefault(bar, ([], []))
        bar_vel[bar][0].append(r.velocity)
        bar_vel[bar][1].append(t.velocity)
    if expressive:
        corr = _pearson(ref_v, take_v)
        offset = statistics.fmean(take_v) - statistics.fmean(ref_v)
        dev_bars = []
        for bar, (rv, tv) in bar_vel.items():
            d = (statistics.fmean(tv) - statistics.fmean(rv)) - offset
            dev_bars.append({"bar": bar, "relative_to_score": round(d, 1)})
        dev_bars.sort(key=lambda x: -abs(x["relative_to_score"]))
        dynamics.update({
            "reference_has_dynamics": True,
            "shape_correlation": round(corr, 2) if corr is not None else None,
            "mean_offset_vs_score": round(offset, 1),
            "bars_off_dynamic_shape": [b for b in dev_bars if abs(b["relative_to_score"]) >= 10][:8],
        })
    else:
        dynamics["reference_has_dynamics"] = False
        dynamics["bar_mean_velocity"] = {bar: round(statistics.fmean(v[1])) for bar, v in sorted(bar_vel.items())}

    # --- Articulation -----------------------------------------------------
    ratios = []
    bar_ratios: dict[int, list[float]] = {}
    for r, t in al.correct:
        slope = tm.local_slope(r.start - window, r.start + window) or tm.slope
        expected = r.duration * slope
        if expected > 0.06:
            ratio = t.duration / expected
            ratios.append(ratio)
            bar_ratios.setdefault(score.position(r.start)[0], []).append(ratio)
    legato_gaps = []
    by_part: dict[int, list[tuple[Note, Note]]] = {}
    for r, t in sorted(al.correct, key=lambda p: p[0].start):
        by_part.setdefault(r.part, []).append((r, t))
    ref_onset_counts: dict[float, int] = {}
    for n in ref_notes:
        ref_onset_counts[round(n.start, 3)] = ref_onset_counts.get(round(n.start, 3), 0) + 1
    for seq in by_part.values():
        for (r0, t0), (r1, t1) in zip(seq, seq[1:]):
            single = ref_onset_counts.get(round(r0.start, 3)) == 1 and ref_onset_counts.get(round(r1.start, 3)) == 1
            if single and abs(r1.start - r0.end) <= 0.02 and r1.start > r0.start:
                legato_gaps.append((t1.start - t0.end) * 1000)
    rs = sorted(ratios)
    articulation = {
        "median_held_vs_written_pct": round(statistics.median(rs) * 100) if rs else None,
        "clipped_pct": round(100 * sum(1 for x in rs if x < 0.5) / len(rs), 1) if rs else None,
        "overheld_pct": round(100 * sum(1 for x in rs if x > 1.5) / len(rs), 1) if rs else None,
        "legato_passages": {
            "pairs_measured": len(legato_gaps),
            "median_gap_ms": round(statistics.median(legato_gaps)) if legato_gaps else None,
            "audible_breaks_pct": round(100 * sum(1 for g in legato_gaps if g > 60) / len(legato_gaps), 1) if legato_gaps else None,
            "note": "Negative gap = overlapping (finger legato). Breaks may be hidden by pedal.",
        },
        "note": "Held-vs-written compares key-down time to the notated length at your tempo.",
    }

    # --- Pedal ------------------------------------------------------------
    take_end = max(n.end for n in take_notes)
    take_int = pedal_intervals(take_pedal, take_end)
    take_int_ref = [(tm.ref_at(a), tm.ref_at(b)) for a, b in take_int]
    ref_int = pedal_intervals(score.pedal, score.duration)
    take_span = take_end - take_notes[0].start
    pedal_info: dict = {
        "take_presses": len(take_int),
        "take_down_pct": round(100 * sum(b - a for a, b in take_int) / take_span, 1) if take_span > 0 else 0,
        "reference_has_pedal": bool(ref_int),
    }
    pedal_flags: dict[int, str] = {}
    for b in bar_list:
        t_cov, t_rel = _pedal_coverage(take_int_ref, b.start, b.end)
        if ref_int:
            r_cov, r_rel = _pedal_coverage(ref_int, b.start, b.end)
            if r_rel >= 1 and t_cov > 0.9 and t_rel == 0:
                pedal_flags[b.number] = "held pedal through a change (blur)"
            elif r_cov > 0.5 and t_cov < 0.1:
                pedal_flags[b.number] = "no pedal where score pedals"
            elif r_cov == 0 and t_cov > 0.5:
                pedal_flags[b.number] = "pedal where score has none"
    if not ref_int:
        for a, b_ in take_int_ref:
            first = score.position(a)[0]
            last = score.position(b_)[0]
            if last - first >= 2:
                pedal_flags.setdefault(first, f"one pedal held over bars {first}-{last} (may blur)")
    pedal_info["bar_flags"] = [{"bar": k, "issue": v} for k, v in sorted(pedal_flags.items())][:12]

    # --- Mistakes + per-bar ----------------------------------------------
    t_first = take_notes[0].start
    mistakes = []
    for r, t in al.wrong:
        bar, beat = score.position(r.start)
        mistakes.append({"bar": bar, "beat": beat, "type": "wrong", "expected": note_name(r.pitch), "played": note_name(t.pitch), "hand": side(r), "take_sec": round(t.start - t_first, 2)})
    for r in al.missed:
        if r not in ref_scope_notes:
            continue
        bar, beat = score.position(r.start)
        mistakes.append({"bar": bar, "beat": beat, "type": "missed", "expected": note_name(r.pitch), "hand": side(r)})
    for t in al.extra:
        bar, beat = score.position(tm.ref_at(t.start))
        mistakes.append({"bar": bar, "beat": beat, "type": "extra", "played": note_name(t.pitch), "take_sec": round(t.start - t_first, 2)})
    mistakes.sort(key=lambda m: (m["bar"], m["beat"]))

    bar_dev: dict[int, list[float]] = {}
    for r, _, d in timing:
        bar_dev.setdefault(score.position(r.start)[0], []).append(abs(d) * 1000)
    hes_bars = {h["bar"] for h in hesitations}
    bars_out = []
    for b in bar_list:
        counts = {k: sum(1 for m in mistakes if m["bar"] == b.number and m["type"] == k) for k in ("wrong", "missed", "extra")}
        devs = bar_dev.get(b.number, [])
        mad = round(statistics.median(devs)) if devs else None
        flags = []
        bpm = bar_bpm.get(b.number)
        if bpm and med_bpm:
            if bpm > med_bpm * 1.08:
                flags.append("rushing")
            elif bpm < med_bpm * 0.92:
                flags.append("dragging")
        if b.number in hes_bars:
            flags.append("hesitation")
        if b.number in pedal_flags:
            flags.append("pedal")
        rlist = bar_ratios.get(b.number, [])
        if len(rlist) >= 3:
            med = statistics.median(rlist)
            if med < 0.5:
                flags.append("clipped notes")
            elif med > 1.6:
                flags.append("over-held")
        severity = 2 * counts["wrong"] + 2 * counts["missed"] + counts["extra"] + (1 if mad and mad > 60 else 0) + 2 * ("hesitation" in flags) + len(flags) * 0.5
        bars_out.append({"bar": b.number, **counts, "timing_ms": mad, "bpm": round(bpm) if bpm else None, "flags": flags, "severity": severity})

    note_score = 100 * f1
    timing_score = 100 * max(0.0, 1 - timing_mad / 100)
    stability_score = 100 * max(0.0, 1 - tempo_cv * 5)
    overall = 0.5 * note_score + 0.3 * timing_score + 0.2 * stability_score

    worst = sorted([b for b in bars_out if b["severity"] > 0], key=lambda b: -b["severity"])
    limit_bars, limit_mistakes = (len(worst), len(mistakes)) if detail == "full" else (12, 25)

    report = {
        "scope": {
            "bars": f"{first_bar}-{last_bar}",
            "auto_detected": not bars_given,
            "reference_notes": n_ref,
            "take_notes": n_take,
        },
        "scores": {
            "overall": round(overall),
            "notes": round(note_score),
            "timing": round(timing_score),
            "tempo_stability": round(stability_score),
            "method": "overall = 50% note F1 + 30% timing (100 - median ms error) + 20% tempo stability",
        },
        "notes": {
            "correct": n_correct,
            "wrong": len(al.wrong),
            "missed": sum(1 for m in mistakes if m["type"] == "missed"),
            "extra": len(al.extra),
            "accuracy_pct": round(100 * recall, 1),
            "precision_pct": round(100 * precision, 1),
        },
        "timing": {
            "median_error_ms": round(timing_mad),
            "p90_error_ms": round(_pct(abs_ms, 0.9)),
            "by_hand_median_error_ms": {s: round(statistics.median(v)) for s, v in by_side_dev.items() if v},
            "hands_together_offset_ms": round(statistics.median(asyncs)) if asyncs else None,
            "hands_offset_note": "Positive = right hand lands after left.",
        },
        "tempo": {
            "reference_bpm": round(ref_bpm0, 1),
            "your_bpm": round(global_bpm, 1),
            "percent_of_reference": round(100 / tm.slope, 1),
            "bar_to_bar_variation_pct": round(tempo_cv * 100, 1),
            "trend_bpm_per_10_bars": trend,
            "hesitations": hesitations[: (len(hesitations) if detail == "full" else 10)],
        },
        "dynamics": dynamics,
        "articulation": articulation,
        "pedal": pedal_info,
        "worst_bars": [{k: v for k, v in b.items() if k != "severity"} for b in worst[:limit_bars]],
        "mistakes": mistakes[:limit_mistakes],
        "mistakes_truncated": max(0, len(mistakes) - limit_mistakes),
        "_per_bar": [{k: v for k, v in b.items() if k != "severity"} for b in bars_out],
    }
    return report


def take_range_for_bars(score: Score, ref_notes: list[Note], take_notes: list[Note], bars: tuple[int, int]) -> tuple[float, float, float]:
    """Find the take time span (start, end, take/ref slope) that corresponds to a reference bar range."""
    al = align(ref_notes, take_notes, free_ref_ends=True)
    r0, r1 = score.bar_range_times(*bars)
    return al.tmap.take_at(r0), al.tmap.take_at(r1), al.tmap.slope
