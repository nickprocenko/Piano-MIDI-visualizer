"""Marks for a mock exam, from what the coach measured (data/marking.json holds the numbers).

A piece is marked on five things, each 0-100, from one free-play comparison against the
score (analysis.compare):
  pitch        the right notes (note F1)
  time         steady, even, at tempo, without hesitating (less weight on steadiness when the
               piece is lyrical, where give and take is part of it)
  tone         estimated from how varied the touch is (the keyboard's velocity curve decides
               most of this, so it counts little)
  shape        dynamics following the score's, notes held as written, clean pedalling
  performance  keeping going, and playing the whole piece
Their weighted sum is mapped to /30, with caps for many wrong notes, restarts or a slow tempo.
Scales are marked per item (notes, evenness, speed; the wrong scale scores nothing) and the
mean mapped to /21; sight-reading like a piece, mapped to /21; aural is the share of each
test answered well, mapped to /18. Comments come from templates.
"""

from __future__ import annotations

import json
import statistics

from . import PACKAGE

SCHEME_PATH = PACKAGE / "data" / "marking.json"
_scheme: dict | None = None


def scheme() -> dict:
    global _scheme
    if _scheme is None:
        _scheme = json.loads(SCHEME_PATH.read_text(encoding="utf-8"))
    return _scheme


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def to_marks(q: float, points: list[list[float]]) -> int:
    """A quality on the map's scale -> whole marks, by straight lines between the points."""
    q = _clamp(q, points[0][0], points[-1][0])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if q <= x1:
            return round(y0 + (y1 - y0) * (q - x0) / (x1 - x0))
    return round(points[-1][1])


def band(total: float) -> str:
    return next(name for name, low in scheme()["bands"] if total >= low)


def _tempo_factor(pct: float | None) -> float:
    """100 at 95% of the marked tempo or faster, falling to 0 at 55%."""
    if pct is None:
        return 50.0
    return _clamp(100 - (95 - pct) * 2.5) if pct < 95 else 100.0


def _bars(items: list[dict], key: str = "bar", n: int = 3) -> str:
    """The bars that come up most often (in bar order)."""
    from collections import Counter

    top = Counter(i[key] for i in items if i.get(key) is not None).most_common(n)
    return ", ".join(str(b) for b in sorted(b for b, _ in top))


def _tempo_pct(report: dict) -> float | None:
    """The speed you played at, as % of the marked tempo: the median of the bar-by-bar tempos,
    so stopping between bars counts as stopping, not as playing slowly."""
    tempo = report.get("tempo") or {}
    bpms = sorted(b["bpm"] for b in report.get("_per_bar") or [] if b.get("bpm"))
    if bpms and tempo.get("reference_bpm"):
        return 100 * statistics.median(bpms) / tempo["reference_bpm"]
    return tempo.get("percent_of_reference")


def _measures(report: dict, piece_notes: int | None = None, rubato: bool = False) -> dict:
    """The five criteria (0-100) and the facts behind them."""
    s = report.get("scores", {})
    tempo = report.get("tempo", {})
    pct = _tempo_pct(report)
    hes = tempo.get("hesitations") or []
    restarts = sum(1 for h in hes if h.get("extra_pause_ms", 0) >= scheme()["piece"]["restart_pause_ms"])
    pitch = float(s.get("notes", 0))
    timing, steady = float(s.get("timing", 0)), float(s.get("tempo_stability", 0))
    tf = _tempo_factor(pct)
    if rubato:
        time = 0.5 * timing + 0.15 * steady + 0.35 * tf
    else:
        time = 0.45 * timing + 0.25 * steady + 0.3 * tf
    time = _clamp(time - 5 * min(len(hes), 6))
    dyn = report.get("dynamics", {})
    spread = (dyn.get("take_velocity") or {}).get("std", 0.0) or 0.0
    lift = dyn.get("melody_lift_velocity") or 0.0
    tone = _clamp(50 + 3 * spread + min(15, max(0.0, lift) * 2))
    if dyn.get("reference_has_dynamics") and dyn.get("shape_correlation") is not None:
        dynamics = _clamp(50 + 50 * dyn["shape_correlation"])
    else:
        dynamics = _clamp(40 + 3 * spread)
    art = report.get("articulation", {})
    held = _clamp(100 - (art.get("clipped_pct") or 0) - (art.get("overheld_pct") or 0) / 2)
    pedal_flags = (report.get("pedal") or {}).get("bar_flags") or []
    shape = _clamp(0.5 * dynamics + 0.5 * held - min(20, 5 * len(pedal_flags)))
    played = (report.get("scope") or {}).get("reference_notes") or 0
    scope = 100.0 if not piece_notes else _clamp(100 * played / piece_notes)
    continuity = _clamp(100 - 8 * len(hes) - 15 * restarts)
    performance = 0.6 * continuity + 0.4 * scope
    return {"criteria": {"pitch": round(pitch), "time": round(time), "tone": round(tone), "shape": round(shape),
                         "performance": round(performance)},
            "tempo_pct": pct, "hesitations": hes, "restarts": restarts, "scope_pct": round(scope),
            "mistakes": report.get("mistakes") or [], "dynamics": dynamics, "held": held, "pedal_flags": pedal_flags}


def piece_mark(report: dict, piece_notes: int | None = None, rubato: bool = False) -> dict:
    """{mark, of, q, criteria, capped, comments} for one piece."""
    cfg = scheme()["piece"]
    if not report or "error" in report:
        why = (report or {}).get("error") or "nothing was played"
        return {"mark": 0, "of": cfg["of"], "q": 0, "criteria": {}, "capped": None,
                "comments": [f"Not marked: {why}"]}
    m = _measures(report, piece_notes, rubato)
    c = m["criteria"]
    q = sum(cfg["weights"][k] * c[k] for k in cfg["weights"])
    mark = to_marks(q, cfg["map"])
    capped = None
    caps = cfg["caps"]
    for why, (limit, most), hit in (
            ("many wrong or missing notes", caps["pitch_below"], c["pitch"] < caps["pitch_below"][0]),
            ("several restarts", caps["restarts_over"], m["restarts"] > caps["restarts_over"][0]),
            ("well below the marked tempo", caps["tempo_below_pct"], m["tempo_pct"] is not None and m["tempo_pct"] < caps["tempo_below_pct"][0])):
        if hit and mark > most:
            mark, capped = most, why
    return {"mark": mark, "of": cfg["of"], "q": round(q, 1), "criteria": c, "capped": capped,
            "comments": _piece_comments(m)}


def _piece_comments(m: dict) -> list[str]:
    c = m["criteria"]
    out = []
    slips = [x for x in m["mistakes"] if x.get("type") in ("wrong", "missed")]
    if c["pitch"] >= 95:
        out.append("Secure notes throughout.")
    elif c["pitch"] >= 80:
        out.append(f"Mostly accurate notes, with some slips (bars {_bars(slips)})." if slips else "Mostly accurate notes.")
    else:
        out.append(f"Many notes went astray (bars {_bars(slips)}); the notes need to be more secure." if slips
                   else "The notes need to be more secure.")
    pct = m["tempo_pct"]
    if pct is not None and pct < 85:
        out.append(f"The tempo was well below the marked speed (about {round(pct)}%).")
    if m["hesitations"]:
        out.append(f"Hesitations broke the flow in bars {_bars(m['hesitations'])}.")
    elif c["time"] >= 85:
        out.append("A steady, well-judged pulse.")
    if c["shape"] >= 80:
        out.append("The phrases had a sense of shape.")
    elif c["shape"] < 70:  # say what held it back
        if m["pedal_flags"]:
            out.append(f"Pedal where the music asks for it (bars {_bars(m['pedal_flags'])}).")
        if m["held"] < 70:
            out.append("Hold the notes for their full length.")
        if m["dynamics"] < 65:
            out.append("More dynamic contrast would bring the music to life.")
    if m["scope_pct"] < 90:
        out.append(f"Only part of the piece was played (about {m['scope_pct']}%).")
    return out


def scale_q(report: dict | None) -> dict:
    """One scale or arpeggio: {q (0-100), detail}. The wrong scale (few right notes) scores 0."""
    cfg = scheme()["scales"]
    if not report or "error" in report:
        return {"q": 0.0, "detail": (report or {}).get("error") or "not played"}
    s = report.get("scores", {})
    notes = float(s.get("notes", 0))
    if notes < cfg["wrong_notes_below"]:
        return {"q": 0.0, "detail": "mostly wrong notes (the wrong key or pattern?)"}
    pct = (report.get("tempo") or {}).get("percent_of_reference")
    tempo = _tempo_factor(pct)
    w = cfg["weights"]
    q = w["notes"] * notes + w["timing"] * float(s.get("timing", 0)) + w["tempo"] * tempo
    bits = [f"notes {round(notes)}", f"evenness {s.get('timing', 0)}"]
    if pct is not None:
        bits.append(f"speed {round(pct)}%")
    return {"q": round(q, 1), "detail": ", ".join(bits)}


def scales_mark(qs: list[float], not_played: int = 0) -> dict:
    """qs: each scale's quality, those not played (skipped) included as 0."""
    cfg = scheme()["scales"]
    mean = statistics.fmean(qs) if qs else 0.0
    mark = to_marks(mean, cfg["map"])
    good = sum(1 for q in qs if q >= 80)
    comments = [f"{good} of {len(qs)} scales and arpeggios fluent and secure."] if qs else ["No scales played."]
    if not_played:
        comments.append(f"{not_played} not played.")
    if sum(1 for q in qs if q == 0) > not_played:
        comments.append("Some were not recognisable: check the keys and patterns.")
    return {"mark": mark, "of": cfg["of"], "q": round(mean, 1), "comments": comments}


def sight_mark(report: dict | None) -> dict:
    cfg = scheme()["sight"]
    if not report or "error" in report:
        return {"mark": 0, "of": cfg["of"], "q": 0, "criteria": {},
                "comments": [f"Not marked: {(report or {}).get('error') or 'nothing was played'}"]}
    m = _measures(report)
    c = m["criteria"]
    parts = {"notes": c["pitch"], "time": c["time"], "tempo": _tempo_factor(m["tempo_pct"]), "shape": c["shape"]}
    q = sum(cfg["weights"][k] * parts[k] for k in cfg["weights"])
    comments = ["A fluent, continuous reading." if not m["hesitations"] and c["pitch"] >= 85 else
                "Keep going through the slips: the pulse matters more than every note." if m["hesitations"] else
                "The pulse held, but more of the notes need to be right."]
    return {"mark": to_marks(q, cfg["map"]), "of": cfg["of"], "q": round(q, 1),
            "criteria": {k: round(v) for k, v in parts.items()}, "comments": comments}


def aural_mark(test_scores: list[float]) -> dict:
    """test_scores: each test 0-1."""
    cfg = scheme()["aural"]
    mean = statistics.fmean(test_scores) if test_scores else 0.0
    return {"mark": to_marks(mean, cfg["map"]), "of": cfg["of"], "q": round(mean, 3),
            "comments": [f"{sum(1 for s in test_scores if s >= 0.67)} of {len(test_scores)} tests answered well."]}
