"""Sight-reading pieces generated for each grade of the Atlas.

What a grade's pieces may use builds up grade by grade, as the syllabus's parameters do
(<content>/syllabus.json, 'sight'): keys and time signatures, length, hand position (one
hand at a time in a five-finger position at first, hands together from Grade 2, outside
five-finger position from Grade 3) and the rhythms. Melodies move mostly by step, harmony
is the key's primary chords, and every piece ends on the tonic. Each piece is written with
the coach's grand-staff writer and must pass the engraving rules and read back with the
notes it was given, else another seed is tried.

    python -m midi_coach.atlas.sightreading [--count 8]   write <content>/lessons/sight/<grade>-<n>.musicxml
"""

from __future__ import annotations

import random
import re
import sys
from fractions import Fraction as F

from . import content_dir, load_syllabus
from .technique import PC, STEPS

# Rhythm patterns (beats, as quarter notes), cumulative by grade, for simple and compound time.
SIMPLE_RHYTHMS = {
    0: [(F(2),), (F(1),), (F(1, 2), F(1, 2))],
    1: [(F(3),)],
    2: [(F(4),), (F(3, 2), F(1, 2))],
    3: [(F(1, 4),) * 4, (F(1, 2), F(1, 4), F(1, 4))],
    5: [(F(1, 2), F(1), F(1, 2))],  # simple syncopation
    6: [(F(1, 3),) * 3],  # triplet quavers
}
COMPOUND_RHYTHMS = {  # in dotted-crotchet beats (3 quavers)
    3: [(F(3, 2),), (F(1), F(1, 2)), (F(1, 2),) * 3],
    6: [(F(1, 2), F(1)), (F(3, 4), F(1, 4), F(1, 2))],
}
TEMPO = {0: 72, 1: 76, 2: 80, 3: 84, 4: 88, 5: 92, 6: 96, 7: 100, 8: 104}
MAX_TRIES = 12


def params(syllabus: dict, grade: str) -> dict:
    """What a grade's sight-reading may use: everything introduced up to that grade."""
    grades = sorted(syllabus["grades"], key=lambda g: g["order"])
    order = next(g["order"] for g in grades if g["id"] == grade)
    keys, times, feats = [], [], []
    bars = 4
    for g in grades[: order + 1]:
        s = g.get("sight", {})
        keys += s.get("keys", [])
        times += s.get("times", [])
        feats += s.get("features", [])
        nums = [int(n) for n in re.findall(r"\d+", s.get("bars", ""))]
        if nums:
            bars = max(nums)
        elif "page" in s.get("bars", ""):
            bars = 24
    times = [t for t in times if t in ("2/4", "3/4", "4/4", "3/8", "6/8", "9/8", "12/8")] or ["4/4"]
    return {"order": order, "title": grades[order]["title"], "keys": keys or ["C"], "times": times, "bars": bars, "features": feats,
            "together": order >= 2, "five_finger": order <= 2, "tempo": TEMPO.get(order, 80)}


def _scale(key: str) -> tuple[int, list[int]]:
    """Tonic pitch class and the semitone offsets of 15 degrees (two octaves) from the tonic;
    minor keys use the harmonic minor (the raised seventh: the syllabus's 'occasional
    accidentals')."""
    minor = key.endswith("m")
    tonic = PC[key[:-1] if minor else key]
    steps = STEPS["harmonic" if minor else "major"]
    offs = [0]
    for k in range(14):
        offs.append(offs[-1] + steps[k % 7])
    return tonic, offs


def _bar_rhythm(rng: random.Random, beats: F, compound: bool, order: int) -> list[F]:
    pool = []
    table = COMPOUND_RHYTHMS if compound else SIMPLE_RHYTHMS
    for g, pats in table.items():
        if g <= order:
            pool += pats
    out: list[F] = []
    left = beats
    beat_unit = F(3, 2) if compound else F(1)
    while left > 0:
        fits = [p for p in pool if sum(p) <= left and (sum(p) % beat_unit == 0 or left == sum(p) or sum(p) < beat_unit)]
        fits = [p for p in fits if _on_grid(beats - left, p, beat_unit)]
        if not fits:
            out.append(left)
            break
        pat = rng.choice(fits)
        out += list(pat)
        left -= sum(pat)
    return out


def _on_grid(start: F, pat: tuple, unit: F) -> bool:
    """A pattern shorter than a beat must not cross a beat line (keeps the beat readable)."""
    if sum(pat) >= unit:
        return start % unit == 0
    return (start % unit) + sum(pat) <= unit


def generate(syllabus: dict, grade: str, seed: int) -> dict:
    """{xml, key, time, bars, events} for one sight-reading piece, lint-clean; raises if no
    seed near this one gives a clean piece."""
    from .. import engraving
    from ..transcribe import grand_staff

    p = params(syllabus, grade)
    for attempt in range(MAX_TRIES):
        rng = random.Random(seed * 1000 + attempt)
        key = rng.choice(p["keys"][-4:] if len(p["keys"]) > 4 else p["keys"])
        time = rng.choice(p["times"][-3:])
        num, den = (int(x) for x in time.split("/"))
        beats = F(num * 4, den)
        compound = den == 8 and num % 3 == 0
        tonic, offs = _scale(key)
        base_rh = 60 + tonic  # the tonic from middle C up: the tune sits in the treble
        base_lh = base_rh - 12  # an octave lower: the bass clef
        acc = base_lh - 12 if tonic > 4 else base_lh  # accompaniment roots, F2 to E3
        bars = p["bars"]
        lo, hi = (0, 4) if p["five_finger"] else (-2, 9)
        unit = F(3, 2) if compound else F(1)
        events = []
        deg = 0  # every piece starts on the tonic...
        harmony = []  # a root degree per bar: I, IV, V, then V-I at the end
        for b in range(bars):
            harmony.append(0 if b == 0 or b == bars - 1 else 4 if b == bars - 2 else rng.choice([0, 3, 4, 0]))
        for b in range(bars):
            start = beats * b
            last = b == bars - 1
            # Which hand reads the melody: at the first grades the hands take turns by phrase.
            melody_hand = "right" if p["together"] or b < (bars + 1) // 2 else "left"
            base = base_rh if melody_hand == "right" else base_lh
            rhythm = [_last_value(beats, compound)] if last else _bar_rhythm(rng, beats, compound, p["order"])
            t = start
            for k, d in enumerate(rhythm):
                if last:
                    deg = 0  # ...and ends on it
                elif b == 0 and k == 0:
                    deg = 0
                elif k == len(rhythm) - 1 and b == bars - 2:
                    deg = rng.choice([1, 4, -1]) if lo < 0 else rng.choice([1, 4])  # leading into the final tonic
                else:
                    step = rng.choice([-1, 1, -1, 1, 0, -2, 2] + ([3, -3] if p["order"] >= 3 else []))
                    deg = max(lo, min(hi, deg + step))
                events.append((melody_hand, t, t + d, base + _deg(offs, deg)))
                t += d
            if p["together"]:
                root = harmony[b]
                units = beats / unit
                whole = units in (1, 2, 3) and not (compound and units == 3)
                lh_len = beats if whole and (p["order"] < 4 or rng.random() < 0.5) else unit * (2 if units % 2 == 0 else 1)
                if last:
                    lh_len = _last_value(beats, compound)
                tt = start
                while tt + lh_len <= start + beats:
                    events.append(("left", tt, tt + lh_len, acc + _deg(offs, root)))
                    if p["order"] >= 5 and not last and rng.random() < 0.4:  # a 2-note chord in the left hand
                        events.append(("left", tt, tt + lh_len, acc + _deg(offs, root + 4)))
                    tt += lh_len
                    if last:
                        break
        out = grand_staff(events, f"Sight-reading · {p['title']}", time, [(F(0), p["tempo"])])
        if engraving.lint(out["xml"])["findings"]:
            continue
        return {"xml": out["xml"], "key": key, "time": time, "bars": bars, "events": events, "seed": seed * 1000 + attempt}
    raise RuntimeError(f"No clean sight-reading piece for {grade} near seed {seed}")


def _last_value(beats: F, compound: bool = False) -> F:
    """The final note: the whole bar when one plain (or dotted) note can show it, else the
    longest that can - in compound time a dotted value - followed by a rest."""
    for v in ((F(6), F(3), F(3, 2)) if compound else (F(4), F(3), F(2), F(3, 2), F(1))):
        if v <= beats:
            return v
    return beats


def _deg(offs: list[int], deg: int) -> int:
    """Semitones from the tonic to a scale degree (negative degrees: below the tonic)."""
    if deg >= 0:
        return offs[deg]
    return offs[7 + deg] - 12


def write_pool(count: int = 8, grades: list[str] | None = None) -> dict:
    """Write `count` pieces per grade to <content>/lessons/sight/, checked (lint + read-back)."""
    from ..notes import load_score

    syllabus = load_syllabus()
    folder = content_dir() / "lessons" / "sight"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"written": 0, "problems": []}
    for g in syllabus["grades"]:
        if grades and g["id"] not in grades:
            continue
        for n in range(1, count + 1):
            piece = generate(syllabus, g["id"], seed=n)
            path = folder / f"{g['id']}-{n}.musicxml"
            path.write_text(piece["xml"], encoding="utf-8")
            want = sorted(e[3] for e in piece["events"])
            got = sorted(x.pitch for x in load_score(path).notes)
            if got != want:
                report["problems"].append({"file": path.name, "missing": len(set(want) - set(got))})
            report["written"] += 1
    return report


def lesson_for(stage: dict, req: dict) -> dict:
    """A sight-reading stage's lesson: what to look for, then a graded reading of a fresh
    piece from the grade's pool (a new one each time)."""
    st = stage["stage"]
    spec = req.get("spec", {})
    if "standard" in spec:
        what = "Read a piece you haven't seen, at the grade's standard: 30 seconds to look it over and try bits out, then play it through without stopping."
    elif "key" in spec:
        what = f"{req['title']}: check the key signature and where the hands start before you play."
    elif "time" in spec:
        what = f"{req['title']}: find the beat and count a bar before you start."
    else:
        what = f"New at this grade: {req['title'].lower()}. Spot it in the piece before you play."
    prepared = st["key"] in ("learn", "prepared")
    text = what + (" Take your time with this one." if prepared else " Keep going whatever happens: the pulse matters more than every note.")
    rule = {"metric": "notes", "min": 85} if st["mode"] == "learn" else {"metric": "overall", "min": 70 if not prepared else 75}
    return {"id": stage["id"], "version": 1, "made": "atlas.sightreading", "checked": True, "requirement": req["id"],
            "steps": [{"id": "read", "type": "read", "text": text},
                      {"id": "play", "type": "play", "pool": f"sight/{req['tier']}-", "hand": "both", "mode": st["mode"],
                       "tempo_percent": st["tempo_percent"], "graded": True, "pass": rule}]}


def write_lessons() -> int:
    """Lessons for every sight-reading stage of the Atlas (they read from the pools)."""
    import json

    from . import first_steps, load_atlas

    atlas = load_atlas()
    folder = content_dir() / "lessons"
    count = 0
    for req in atlas["nodes"]:
        if req["level"] == "requirement" and req["kind"] == "sight" and req["tier"] not in first_steps.OURS:
            for sid in req["stages"]:
                lesson = lesson_for(atlas["by_id"][sid], req)
                (folder / f"{sid}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
                count += 1
    return count


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    count = int(args[args.index("--count") + 1]) if "--count" in args else 8
    report = write_pool(count)
    print(f"{report['written']} pieces; {len(report['problems'])} problems; {write_lessons()} lessons")
    for p in report["problems"][:10]:
        print(" ", p)


if __name__ == "__main__":
    main()
