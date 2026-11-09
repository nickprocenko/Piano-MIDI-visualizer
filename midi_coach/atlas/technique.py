"""Scales, arpeggios and sevenths as sheet music, and the lessons for their stages.

Every technique requirement of the Atlas is written out from its spec (atlas/templates.py):
the notes of the pattern up and down its range, in even notes - quavers to Grade 4,
semiquavers from Grade 5 - at the exam speed, one staff per hand, through the coach's
grand-staff writer, so it reads like the coach's other sheets and passes the same
engraving rules. Hands together are an octave apart; contrary motion starts on the tonic in
unison; scales a third apart start with the tonic as the lower note, a sixth apart with the
tonic as the upper note; dominant sevenths resolve on the tonic.

    python -m midi_coach.atlas.technique [--tier g3]    write <content>/lessons for technique stages
"""

from __future__ import annotations

import json
import sys
from fractions import Fraction

from . import content_dir, load_atlas

PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
      "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
STEPS = {"major": [2, 2, 1, 2, 2, 2, 1], "natural": [2, 1, 2, 2, 1, 2, 2], "harmonic": [2, 1, 2, 2, 1, 3, 1],
         "melodic": [2, 1, 2, 2, 2, 2, 1]}
CHORDS = {"major": [0, 4, 7], "minor": [0, 3, 7], "dom7": [0, 4, 7, 10], "dim7": [0, 3, 6, 9]}
FIVE_FINGER = 5  # notes of a five-finger range (tonic to dominant)


def notes_per_beat(tier: str) -> int:
    return 4 if tier in ("g5", "g6", "g7", "g8") else 2


def _start(tonic: str, octaves: int | None, hand: str) -> int:
    """Starting MIDI note: around middle C for short ranges, lower for 4 octaves; the left
    hand an octave below the right."""
    base = 48 if (octaves or 1) >= 4 else 60
    p = base + PC[tonic]
    if PC[tonic] > 6:
        p -= 12
    return p - 12 if hand == "left" else p


def _scale_degrees(form: str, count: int, descending_form: str | None = None) -> tuple[list[int], list[int]]:
    """Semitone offsets from the tonic for `count` steps up, and the way back down
    (melodic minor comes down natural)."""
    up = [0]
    steps = STEPS[form]
    for k in range(count):
        up.append(up[-1] + steps[k % 7])
    down_steps = STEPS[descending_form or form]
    down = [up[-1]]
    for k in range(count - 1, -1, -1):
        down.append(down[-1] - down_steps[k % 7])
    return up, down[1:]


def _form(spec: dict) -> str:
    if spec.get("quality") != "minor":
        return "major"
    form = spec.get("form")
    return "harmonic" if form in (None, "choice") else form


def _span(spec: dict) -> int:
    """Scale steps covered: 7 per octave, or a five-finger range."""
    return FIVE_FINGER - 1 if spec.get("range") == "fifth" else 7 * (spec.get("octaves") or 1)


TOP, BOTTOM = 96, 21  # C7 and A0: higher reads only on 15ma; lower is off the keyboard


def pattern(spec: dict) -> dict[str, list]:
    """{'right': [...], 'left': [...]}: each hand's notes in order (a note is a MIDI number,
    or a tuple for a double note), moved down an octave at a time while it would climb past
    C7 (a four-octave scale a tenth apart) and staying on the keyboard."""
    hands = _raw_pattern(spec)
    flat = [p for seq in hands.values() for n in seq for p in (n if isinstance(n, tuple) else (n,))]
    shift = 0
    while max(flat) + shift > TOP and min(flat) + shift - 12 >= BOTTOM:
        shift -= 12
    if not shift:
        return hands
    move = lambda n: tuple(p + shift for p in n) if isinstance(n, tuple) else n + shift  # noqa: E731
    return {h: [move(n) for n in seq] for h, seq in hands.items()}


def _raw_pattern(spec: dict) -> dict[str, list]:
    t = spec["type"]
    tonic = spec.get("tonic") or spec.get("start_rh") or "C"
    octaves = spec.get("octaves") or 1
    if t in ("scale", "third_apart", "sixth_apart"):
        form = _form(spec)
        up, down = _scale_degrees(form, _span(spec), "natural" if form == "melodic" else None)
        offs = up + down
        rh0, lh0 = _start(tonic, octaves, "right"), _start(tonic, octaves, "left")
        if t == "third_apart":  # tonic as the lower note: the right hand starts a third (a tenth) above
            rh_up, rh_down = _scale_degrees_from(form, 2, _span(spec))
            return {"left": [lh0 + o for o in offs], "right": [lh0 + 12 + o for o in rh_up + rh_down]}
        if t == "sixth_apart":  # tonic as the upper note: the left hand starts on the mediant a sixth below
            lh_up, lh_down = _scale_degrees_from(form, 2, _span(spec))
            return {"right": [rh0 + o for o in offs], "left": [rh0 - 12 + o for o in lh_up + lh_down]}
        return {"right": [rh0 + o for o in offs], "left": [lh0 + o for o in offs]}
    if t == "contrary":
        form = _form(spec)
        up, down = _scale_degrees(form, _span(spec), "natural" if form == "melodic" else None)
        mirror_up = [-o for o in _scale_degrees_desc(form, _span(spec))]
        start = 60 + PC[tonic] - (12 if PC[tonic] > 6 else 0)
        right = [start + o for o in up + down]
        left_offs = mirror_up + mirror_up[-2::-1]
        return {"right": right, "left": [start + o for o in left_offs]}
    if t in ("chromatic", "whole_tone"):
        step = 1 if t == "chromatic" else 2
        n = 12 * octaves // step
        offs = [k * step for k in range(n + 1)]
        offs += offs[-2::-1]
        rh0, lh0 = _start(tonic, octaves, "right"), _start(tonic, octaves, "left")
        return {"right": [rh0 + o for o in offs], "left": [lh0 + o for o in offs]}
    if t == "chromatic_contrary":
        n = 12 * octaves
        rh0 = 60 + PC[spec["start_rh"]] - (12 if PC[spec["start_rh"]] > 6 else 0)
        lh0 = rh0 - ((PC[spec["start_rh"]] - PC[spec["start_lh"]]) % 12)
        up = list(range(n + 1))
        return {"right": [rh0 + o for o in up + up[-2::-1]], "left": [lh0 - o for o in up + up[-2::-1]]}
    if t == "chromatic_apart":
        n = 12 * octaves
        lh0 = _start(spec["start_lh"], octaves, "left") + 12
        rh0 = lh0 + ((PC[spec["start_rh"]] - PC[spec["start_lh"]]) % 12)
        offs = list(range(n + 1))
        offs += offs[-2::-1]
        return {"right": [rh0 + o for o in offs], "left": [lh0 - 12 + o for o in offs]}
    if t in ("arpeggio", "dom7", "dim7"):
        if t == "arpeggio":
            chord = CHORDS["major" if spec.get("quality") == "major" else "minor"]
            root = PC[tonic]
            inv = {"first": 1, "second": 2}.get(spec.get("inversion") or "", 0)
        elif t == "dom7":
            chord, root, inv = CHORDS["dom7"], PC[tonic] + 7, 0
        else:
            chord, root, inv = CHORDS["dim7"], PC[tonic], 0
        tones = chord[inv:] + [c + 12 for c in chord[:inv]]
        per = len(tones)
        count = 2 if spec.get("range") == "fifth" else per * octaves
        offs = [tones[k % per] + 12 * (k // per) for k in range(count + 1)]
        offs += offs[-2::-1]
        rh0 = _start(_name(root % 12), octaves, "right")
        if t == "dom7":  # resolve on the tonic, a fourth above the dominant
            offs.append(offs[-1] + 5)
        lh0 = rh0 - 12
        return {"right": [rh0 + o for o in offs], "left": [lh0 + o for o in offs]}
    if t in ("thirds", "sixths"):
        form = _form(spec)
        span = _span(spec)
        lower_up, lower_down = _scale_degrees(form, span, None)
        if t == "thirds":  # tonic as the lower note
            upper_up, upper_down = _scale_degrees_from(form, 2, span)
            lower = lower_up + lower_down
            upper = upper_up + upper_down
        else:  # sixths: tonic as the upper note, the mediant a sixth below it
            low_up, low_down = _scale_degrees_from(form, 2, span)
            lower = [o - 12 for o in low_up + low_down]
            upper = lower_up + lower_down
        rh0, lh0 = _start(tonic, spec.get("octaves"), "right"), _start(tonic, spec.get("octaves"), "left")
        return {"right": [(rh0 + a, rh0 + b) for a, b in zip(lower, upper)],
                "left": [(lh0 + a, lh0 + b) for a, b in zip(lower, upper)]}
    raise ValueError(f"No pattern for {t}")


def _name(pc: int) -> str:
    return ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"][pc]


def _degree_offset(form: str, degree: int) -> int:
    """Semitones from the tonic to a scale degree (0-based, may be negative)."""
    steps = STEPS[form]
    off, k = 0, 0
    while k < degree:
        off += steps[k % 7]
        k += 1
    while k > degree:
        k -= 1
        off -= steps[k % 7]
    return off


def _scale_degrees_from(form: str, first: int, count: int) -> tuple[list[int], list[int]]:
    """Offsets of a scale walked from degree `first` for `count` steps up and back (a scale a
    third or sixth apart from the tonic's)."""
    up = [_degree_offset(form, first + k) for k in range(count + 1)]
    return up, up[-2::-1]


def _scale_degrees_desc(form: str, count: int) -> list[int]:
    """Offsets for the left hand of a contrary-motion scale: the scale walked downwards from
    the tonic (mirror image of the right hand), as positive distances."""
    desc_form = "natural" if form == "melodic" else form
    return [-_degree_offset(desc_form, -k) for k in range(count + 1)]


def music(spec: dict, tier: str) -> dict:
    """The requirement written out: {xml, bpm, beats, notes}. Uses transcribe.grand_staff."""
    from ..transcribe import grand_staff
    from .templates import technique_title

    hands = pattern(spec)
    per_beat = notes_per_beat(tier)
    dur = Fraction(1, per_beat)
    events = []
    for hand, seq in hands.items():
        t = Fraction(0)
        for k, note in enumerate(seq):
            end = t + dur if k < len(seq) - 1 else _bar_end(t, dur)
            for p in (note if isinstance(note, tuple) else (note,)):
                events.append((hand, t, end, p))
            t += dur
    npm = spec.get("speed_notes_per_min") or 120
    bpm = round(npm / per_beat)
    # Clefs chosen per beat: a run up two to four octaves changes clef where it climbs,
    # as scale books print it, rather than going under an octave mark.
    out = grand_staff(events, technique_title(spec), "4/4", [(Fraction(0), bpm)], legato_gap=Fraction(0),
                      clef_every=Fraction(1))
    xml = out["xml"]
    if spec.get("artic") == "staccato":
        xml = _staccato(xml)
    return {"xml": xml, "bpm": bpm, "beats": 4, "notes": out["notes"]}


def _bar_end(t: Fraction, dur: Fraction) -> Fraction:
    """The last note is held to the end of its bar (at least a crotchet)."""
    end = t + max(dur, Fraction(1))
    return Fraction(int(-(-end // 4)) * 4) if end % 4 else end


def _staccato(xml: str) -> str:
    """Staccato dots on every note (not rests, not the last held note)."""
    import re

    def dot(m: re.Match) -> str:
        note = m.group(0)
        if "<rest" in note or "<notations>" in note or "<type>whole</type>" in note or "<type>half</type>" in note:
            return note
        return note.replace("</note>", "<notations><articulations><staccato/></articulations></notations></note>")
    return re.sub(r"<note[ >].*?</note>", dot, xml, flags=re.S)


# -- lessons -------------------------------------------------------------------------------


def lesson_for(stage: dict, req: dict, file: str) -> dict:
    """A technique stage's lesson: what it is, listen, then the graded play step(s)."""
    st = stage["stage"]
    spec = req["spec"]
    hand = st["hand"]
    learn = st["mode"] == "learn"
    what = req["title"].replace(" · ", ", ").replace("HT", "hands together").replace("HS", "hands separately")
    speed = "" if "speed" in st["title"] else f", at {st['tempo_percent']}% of exam speed" if st["tempo_percent"] != 100 else ", at exam speed"
    text = (f"{what}. {st['title']}{speed}"
            + (". Learn mode waits for each note." if learn else ". Rehearse keeps the beat; keep the notes even.")
            + (" Play it from memory once you know it, as in the exam." if st.get("final") else ""))
    steps = [{"id": "read", "type": "read", "text": text}]
    listen_hand = "both" if hand in ("both", "separately") else hand
    steps.append({"id": "listen", "type": "listen", "file": file, "hand": listen_hand, "tempo_percent": st["tempo_percent"]})
    rule = {"metric": "notes", "min": 90} if learn else {"metric": "overall", "min": 80, "tempo_min_pct": max(50, st["tempo_percent"] - 10)}
    play_hands = ["right", "left"] if hand == "separately" else [hand]
    for h in play_hands:
        steps.append({"id": f"play-{h}" if len(play_hands) > 1 else "play", "type": "play", "file": file,
                      "hand": h, "mode": st["mode"], "tempo_percent": st["tempo_percent"], "graded": True, "pass": rule})
    return {"id": stage["id"], "version": 1, "made": "atlas.technique (from the syllabus spec)", "checked": True, "steps": steps,
            "requirement": req["id"], "artic": spec.get("artic")}


def write_all(tiers: list[str] | None = None, check: bool = True) -> dict:
    """Write the sheet music of every technique requirement and the lessons of its stages.
    With check, every file goes through the engraving lint and a note read-back first."""
    from .. import engraving
    from ..notes import load_score

    import re

    atlas = load_atlas()
    folder = content_dir() / "lessons"
    (folder / "technique").mkdir(parents=True, exist_ok=True)
    if not tiers:  # every sheet here is written by this function: start clean
        for old in (folder / "technique").glob("*.musicxml"):
            old.unlink()
    tier_titles = {t["id"]: t["title"] for t in atlas["tiers"]}
    report = {"requirements": 0, "lessons": 0, "problems": []}
    for req in atlas["nodes"]:
        if req["level"] != "requirement" or req["kind"] != "technique" or (tiers and req["tier"] not in tiers):
            continue
        out = music(req["spec"], req["tier"])
        # Named as it reads (the page and the take history show the file's name).
        name = re.sub(r'[<>:"/\\|?*]+', "", f"{tier_titles[req['tier']]} · {req['title']}")
        rel = f"technique/{name}.musicxml"
        path = folder / rel
        path.write_text(out["xml"], encoding="utf-8")
        if check:
            findings = engraving.lint(out["xml"])["findings"]
            want = sorted(p for hand in pattern(req["spec"]).values() for n in hand for p in (n if isinstance(n, tuple) else (n,)))
            got = sorted(n.pitch for n in load_score(path).notes)
            if findings or got != want:
                report["problems"].append({"id": req["id"], "lint": findings[:3], "notes_match": got == want})
        report["requirements"] += 1
        for sid in req["stages"]:
            lesson = lesson_for(atlas["by_id"][sid], req, rel)
            (folder / f"{sid}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
            report["lessons"] += 1
    return report


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    tiers = args[args.index("--tier") + 1].split(",") if "--tier" in args else None
    report = write_all(tiers)
    print(f"{report['requirements']} requirements, {report['lessons']} lessons; {len(report['problems'])} problems")
    for p in report["problems"][:20]:
        print(" ", p)


if __name__ == "__main__":
    main()
