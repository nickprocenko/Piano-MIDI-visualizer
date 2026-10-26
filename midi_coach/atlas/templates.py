"""Family templates: how syllabus items become requirements, and requirements stages.

A stage is one step of learning a requirement, small enough to practise in one sitting:
right hand alone, left hand alone, hands together slowly, at speed. The last stage of
every requirement is the requirement itself, so a requirement is as far along as its
last stage. Stages are dicts: {key, title, hand, mode, tempo_percent, final}.
"""

from __future__ import annotations

import re

FLAT, SHARP = "♭", "♯"

# Technique families: which family a syllabus item type goes in, and its menu title.
TECHNIQUE_FAMILIES = {
    "scales-ht": "Scales, hands together",
    "scales-hs": "Scales, hands separately",
    "scales-staccato": "Staccato scales",
    "contrary": "Contrary-motion scales",
    "chromatic": "Chromatic & whole-tone scales",
    "apart": "Scales a third / sixth apart",
    "double-notes": "Scales in thirds / sixths",
    "arpeggios-ht": "Arpeggios, hands together",
    "arpeggios-hs": "Arpeggios, hands separately",
    "sevenths": "Dominant & diminished sevenths",
}
TYPE_TITLES = {
    "scale": "", "contrary": "contrary motion", "chromatic": "chromatic scale",
    "chromatic_contrary": "chromatic contrary motion", "chromatic_apart": "chromatic scale",
    "whole_tone": "whole-tone scale", "arpeggio": "arpeggio", "dom7": "dominant 7th",
    "dim7": "diminished 7th", "third_apart": "a third apart", "sixth_apart": "a sixth apart",
    "thirds": "in thirds", "sixths": "in sixths",
}
SPEED_CLASS = {"arpeggio": "arpeggio", "dom7": "arpeggio", "dim7": "arpeggio",
               "third_apart": "apart", "sixth_apart": "apart", "chromatic_apart": "apart"}


def pretty_key(key: str) -> str:
    """'Bb' -> 'B♭', 'F#' -> 'F♯'."""
    return key[0] + key[1:].replace("b", FLAT).replace("#", SHARP)


def slug(text: str) -> str:
    text = text.replace("#", "sharp").replace("♯", "sharp").replace("♭", "flat")
    text = re.sub(r"(?<=[A-Ga-g])b(?=\b|-)", "flat", text)
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def technique_family(item: dict) -> str:
    t, hands = item["type"], item.get("hands", "together")
    if t == "scale":
        if item.get("artic") == ["staccato"]:
            return "scales-staccato"
        return "scales-ht" if hands == "together" else "scales-hs"
    if t in ("contrary", "chromatic_contrary"):
        return "contrary"
    if t in ("chromatic", "chromatic_apart", "whole_tone"):
        return "chromatic"
    if t in ("third_apart", "sixth_apart"):
        return "apart"
    if t in ("thirds", "sixths"):
        return "double-notes"
    if t == "arpeggio":
        return "arpeggios-ht" if hands == "together" else "arpeggios-hs"
    if t in ("dom7", "dim7"):
        return "sevenths"
    raise ValueError(f"Unknown technique type {t!r}")


def expand_technique(item: dict, grade: str, speeds: dict) -> list[dict]:
    """One syllabus line -> its requirements: one per key (or starting note), per minor form
    that must be prepared (not when it's the candidate's choice), per articulation."""
    out = []
    t = item["type"]
    tonics = item.get("keys") or item.get("starts") or [None]
    forms = (item.get("forms") or [None]) if item.get("quality") == "minor" and not item.get("choice") else [None]
    if item.get("quality") == "minor" and item.get("choice"):
        forms = ["choice"]
    artics = item.get("artic") or ["legato"]
    speed = speeds.get(SPEED_CLASS.get(t, "scale"), {}).get(grade)
    if t in ("thirds", "sixths"):
        cls = "thirds_legato" if artics == ["legato"] else "staccato_thirds_sixths"
        speed = speeds.get(cls, {}).get(grade, speed)
    for tonic in tonics:
        for form in forms:
            for artic in artics:
                spec = {k: v for k, v in item.items() if k not in ("keys", "starts", "forms", "choice", "artic")}
                spec.update(tonic=tonic, form=form, artic=artic, speed_notes_per_min=speed,
                            both_artics=len(artics) > 1)
                out.append(spec)
    return out


def technique_title(spec: dict) -> str:
    t = spec["type"]
    parts = []
    if spec.get("start_lh"):
        parts.append(f"{TYPE_TITLES[t]} from {pretty_key(spec['start_lh'])} (LH) and {pretty_key(spec['start_rh'])} (RH)")
    elif t in ("chromatic", "whole_tone", "dim7"):
        parts.append(f"{TYPE_TITLES[t]} on {pretty_key(spec['tonic'])}")
    elif t == "dom7":
        parts.append(f"dominant 7th in {pretty_key(spec['tonic'])}")
    else:
        q = spec.get("quality", "major")
        form = spec.get("form")
        mode = "major" if q == "major" else (f"{form} minor" if form and form != "choice" else "minor")
        name = f"{pretty_key(spec['tonic'])} {mode}"
        kind = TYPE_TITLES[t]
        if t == "arpeggio":
            inv = spec.get("inversion")
            kind = "arpeggio" + (f", {inv} inversion" if inv else "")
        parts.append(f"{name} {kind}".strip())
    if spec.get("octaves"):
        parts.append(f"{spec['octaves']} oct")
    elif spec.get("range") == "fifth":
        parts.append("a 5th")
    parts.append("HT" if spec.get("hands") == "together" else "HS")
    if spec.get("both_artics") or spec.get("artic") == "staccato":
        parts.append(spec["artic"])
    return " · ".join(parts)


def technique_id(spec: dict) -> str:
    bits = [spec["type"]]
    for k in ("tonic", "quality", "form", "start_lh", "start_rh", "inversion"):
        if spec.get(k):
            bits.append(str(spec[k]))
    bits += [f"{spec['octaves']}oct" if spec.get("octaves") else spec.get("range", ""), spec.get("hands", ""), spec["artic"]]
    return slug("-".join(b for b in bits if b))


def technique_covers(spec: dict) -> list[str]:
    covers = [f"type:{spec['type']}", f"hands:{spec.get('hands', 'together')}", f"artic:{spec['artic']}"]
    if spec.get("tonic") and spec["type"] not in ("chromatic", "whole_tone", "dim7"):
        covers.append(f"key:{spec['tonic']}{'m' if spec.get('quality') == 'minor' else ''}")
    if spec.get("octaves"):
        covers.append(f"octaves:{spec['octaves']}")
    return covers


def stage(key: str, title: str, hand: str = "both", mode: str = "learn", tempo: int = 100, final: bool = False) -> dict:
    return {"key": key, "title": title, "hand": hand, "mode": mode, "tempo_percent": tempo, "final": final}


def technique_stages(spec: dict, variant: bool = False) -> list[dict]:
    """variant: a second articulation of a requirement already learnt legato (only the
    hands-together work at the new touch)."""
    if spec.get("hands") == "separate":
        return [stage("rh", "Right hand, slowly", "right", "learn", 60),
                stage("lh", "Left hand, slowly", "left", "learn", 60),
                stage("speed", "Each hand at exam speed", "separately", "rehearse", 100, final=True)]
    if variant:
        return [stage("slow", f"Hands together, {spec['artic']}, slowly", "both", "rehearse", 60),
                stage("speed", f"Hands together, {spec['artic']}, at exam speed", "both", "rehearse", 100, final=True)]
    return [stage("rh", "Right hand", "right", "learn", 70),
            stage("lh", "Left hand", "left", "learn", 70),
            stage("slow", "Hands together, slowly", "both", "rehearse", 60),
            stage("speed", "Hands together at exam speed", "both", "rehearse", 100, final=True)]


# Aural: each test is a requirement; its stages are the skills it uses, then the test as
# the examiner gives it.
AURAL_SKILLS = {
    "pulse": "Tap the pulse along with the music",
    "strong-beats": "Tap the pulse, louder on the strong beats",
    "metre-2-3": "Two time or three time?",
    "metre-2-3-4": "Two, three or four time?",
    "metre-2-3-4-68": "Two, three, four or 6/8 time?",
    "rhythm-echo": "Tap back a rhythm",
    "sing-echo": "Sing back a phrase",
    "pitch-change-place": "Where did the pitch change?",
    "pitch-or-rhythm-change": "What changed: pitch or rhythm?",
    "dynamics": "Loud or quiet, sudden or gradual",
    "articulation": "Smooth or detached",
    "tempo": "Getting faster, slower, or the same",
    "tonality": "Major or minor",
    "character": "Describe the character",
    "style-period": "Style and period",
    "texture-structure": "Texture and structure",
    "features-any": "Any two features of a piece",
    "describe-features": "Describe a piece's characteristic features",
    "melody-memory": "Sing or play back a melody",
    "sight-sing": "Sing a few notes from the score",
    "sight-sing-accompanied": "Sing a melody from the score with accompaniment",
    "sight-sing-upper": "Sing the upper part from the score",
    "sight-sing-lower": "Sing the lower part from the score",
    "rhythm-clap-extract": "Tap the rhythm of an extract",
    "upper-part-memory": "Sing or play back the upper part",
    "lower-part-memory": "Sing or play back the lower part",
    "lowest-part-memory": "Sing or play back the lowest of three parts",
    "cadence-perfect-imperfect": "Perfect or imperfect cadence",
    "cadence-pii": "Perfect, imperfect or interrupted cadence",
    "cadence-piip": "Perfect, imperfect, interrupted or plagal cadence",
    "cadence-chords-2": "Name the two chords of a cadence",
    "cadence-chords-3": "Name three chords and their positions",
    "modulation-major": "Modulation from a major key",
    "modulation-minor": "Modulation from a minor key",
}
# How each skill is answered (the step type its lesson uses).
AURAL_ANSWER = {"pulse": "tap", "strong-beats": "tap", "rhythm-echo": "tap", "rhythm-clap-extract": "tap",
                "sing-echo": "sing", "sight-sing": "sing", "sight-sing-accompanied": "sing", "sight-sing-upper": "sing",
                "sight-sing-lower": "sing", "melody-memory": "sing", "upper-part-memory": "sing",
                "lower-part-memory": "sing", "lowest-part-memory": "sing"}


def aural_stages(test: dict) -> list[dict]:
    stages = [dict(stage(slug(s), AURAL_SKILLS.get(s, s)), answer=AURAL_ANSWER.get(s, "quiz")) for s in test["skills"]]
    stages.append(dict(stage("test", f"Test {test['test']} as in the exam", final=True), answer="exam"))
    return stages


def sight_stages(kind: str) -> list[dict]:
    if kind == "standard":
        return [stage("prepared", "With time to prepare", "both", "rehearse", 80),
                stage("cold", "At sight, 30 seconds to look", "both", "rehearse", 100, final=True)]
    return [stage("learn", "Learn it", "both", "learn", 100),
            stage("read", "Read it at sight", "both", "rehearse", 100, final=True)]


def theory_stages() -> list[dict]:
    return [dict(stage("learn", "Learn it"), answer="quiz"),
            dict(stage("keyboard", "At the keyboard", final=True), answer="play")]


def piece_stages(bars: int, first: int = 1) -> list[dict]:
    """Sections of 4-8 bars, each hand then hands together; then the whole piece at rising
    tempo. first: 0 when the piece starts with an upbeat (bar 0)."""
    size = 4 if bars <= 16 else 8
    last = first + bars - 1
    out = []
    for k, start in enumerate(range(first, last + 1, size), 1):
        end = min(last, start + size - 1)
        span = f"bars {start}-{end}"
        out += [dict(stage(f"s{k}-rh", f"{span}, right hand", "right", "learn", 80), bars=f"{start}-{end}"),
                dict(stage(f"s{k}-lh", f"{span}, left hand", "left", "learn", 80), bars=f"{start}-{end}"),
                dict(stage(f"s{k}-ht", f"{span}, hands together", "both", "learn", 80), bars=f"{start}-{end}")]
    out += [stage("whole-60", "Whole piece at 60%", "both", "rehearse", 60),
            stage("whole-80", "Whole piece at 80%", "both", "rehearse", 80),
            stage("whole", "Whole piece at tempo", "both", "rehearse", 100, final=True)]
    return out
