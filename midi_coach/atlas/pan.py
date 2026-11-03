"""Pan: the Atlas for the flute, for a beginner.

Three tiers: First notes (the coach's own: making a sound, the first notes B A G and on,
long tones, tonguing, first tunes; ABRSM has no woodwind Initial grade), then ABRSM Flute
Grades 1 and 2. The strands, levels, node ids, layout, progress store and page are the
Atlas's; what differs is that a flute plays one line, so a stage is never a hand: scales
are learnt slowly, then tongued, then slurred, then at exam speed from memory, and a piece
in four-bar sections, then whole at rising tempo. The flute is heard through the
microphone (the coach page tracks its pitch), so Learn and Rehearse work as on the piano.

The ABRSM facts (Grade 1-2 scales, ranges, speeds, sight-reading parameters, aural tests)
are read from <home>/atlas/pan/syllabus.json, drafted locally from the woodwind syllabus
and never put in git, like the Atlas's. This module holds the engine, the First notes
tier, the theory (the coach's own) and, in data/pan_tunes.json, public-domain tunes for
the pieces.

    python -m midi_coach.atlas.pan [syllabus.json]   build <home>/atlas/pan: atlas.json, lessons, music
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import random
import sys
from fractions import Fraction as F

from . import PACKAGE, shared_dir, templates
from .build import Tree
from .layout import layout

VERSION = 1
FOLDER = "pan"
PART = "Flute"
STRANDS = [
    {"id": "pieces", "title": "Pieces", "glyph": "♫"},
    {"id": "technique", "title": "Notes, scales & arpeggios", "glyph": "♯"},
    {"id": "sight", "title": "Sight-reading", "glyph": "◎"},
    {"id": "aural", "title": "Aural", "glyph": "∿"},
    {"id": "theory", "title": "Theory", "glyph": "♭"},
]
LISTS = {"first": "First tunes", "A": "List A", "B": "List B", "C": "List C"}
LEARN_PASS = {"metric": "notes", "min": 85}  # the microphone misses the odd note a keyboard wouldn't


def rehearse_pass(tempo: int) -> dict:
    return {"metric": "overall", "min": 70, "tempo_min_pct": max(50, tempo - 10)}


def content_dir() -> pathlib.Path:
    path = shared_dir() / FOLDER
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextlib.contextmanager
def _as_content(folder: pathlib.Path):
    """Run the Atlas's writers (aural lessons) against Pan's folder."""
    old = os.environ.get("MIDI_COACH_ATLAS_CONTENT")
    os.environ["MIDI_COACH_ATLAS_CONTENT"] = str(folder)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MIDI_COACH_ATLAS_CONTENT", None)
        else:
            os.environ["MIDI_COACH_ATLAS_CONTENT"] = old


# -- pitches and tinyNotation -------------------------------------------------------------

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)  # natural: Grade 2's sight-reading form, and the coach's choice of scale
SHARPS = ("c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b")
FLATS = ("c", "d-", "d", "e-", "e", "f", "g-", "g", "a-", "a", "b-", "b")
FLAT_KEYS = {"F", "Bb", "Eb", "Ab", "Dm", "Gm", "Cm", "Fm"}
LOWEST = 60  # C4, the flute's lowest note (without a B foot)
HIGHEST = 96  # C7
DURATIONS = {F(4): "1", F(3): "2.", F(2): "2", F(3, 2): "4.", F(1): "4", F(1, 2): "8", F(1, 4): "16"}


def key_tonic(key: str) -> tuple[int, tuple[int, ...]]:
    """'Bb' -> (10, MAJOR); 'Em' -> (4, MINOR)."""
    minor = key.endswith("m")
    name = key[:-1] if minor else key
    pc = (PC[name[0].upper()] + (1 if "#" in name else -1 if name[1:2] == "b" else 0)) % 12
    return pc, MINOR if minor else MAJOR


def spell(midi: int, key: str) -> str:
    """60 -> 'c', 72 -> "c'", 70 in F -> 'b-'; octave marks before the accidental."""
    name = (FLATS if key in FLAT_KEYS else SHARPS)[midi % 12]
    octave = midi // 12 - 1
    letter, acc = name[0], name[1:]
    if octave >= 4:
        return letter + "'" * (octave - 4) + acc
    return letter.upper() * (4 - octave) + acc


def tiny(notes: list[tuple[int | None, F]], key: str) -> str:
    """[(pitch or None for a rest, quarter notes)] -> tinyNotation. Every value must be one
    a single note can show (DURATIONS)."""
    out = []
    for pitch, dur in notes:
        out.append(("r" if pitch is None else spell(pitch, key)) + DURATIONS[dur])
    return " ".join(out)


def fill_bar(notes: list[tuple[int, F]], beats: F) -> list[tuple[int | None, F]]:
    """Hold the last note to the end of its bar (or add rests after it when the gap isn't one value)."""
    t = sum(d for _, d in notes[:-1])
    pitch, dur = notes[-1]
    end = (t // beats + 1) * beats if t % beats or dur > beats else t + beats
    gap = end - t
    if gap in DURATIONS:
        return notes[:-1] + [(pitch, gap)]
    out = notes[:-1] + [(pitch, dur)]
    rest = gap - dur
    for value in sorted(DURATIONS, reverse=True):
        while rest >= value:
            out.append((None, value))
            rest -= value
    return out


# -- scales and arpeggios ------------------------------------------------------------------

SPAN = {"octave": 7, "twelfth": 11}  # scale degrees above the tonic


def scale_pitches(tonic: str, quality: str, span: str, start_octave: int | None = None) -> list[int]:
    """Up and down from the lowest tonic the flute has (or the given octave's)."""
    pc, steps = key_tonic(tonic + ("m" if quality == "minor" else ""))
    base = (start_octave + 1) * 12 + pc if start_octave else LOWEST + (pc - LOWEST) % 12
    top = SPAN[span]
    up = [base + 12 * (d // 7) + steps[d % 7] for d in range(top + 1)]
    return up + up[-2::-1]


def arpeggio_pitches(tonic: str, quality: str, span: str, start_octave: int | None = None) -> list[int]:
    pc, steps = key_tonic(tonic + ("m" if quality == "minor" else ""))
    base = (start_octave + 1) * 12 + pc if start_octave else LOWEST + (pc - LOWEST) % 12
    degrees = [d for d in (0, 2, 4, 7, 9, 11) if d <= SPAN[span]]
    up = [base + 12 * (d // 7) + steps[d % 7] for d in degrees]
    return up + up[-2::-1]


def technique_music(spec: dict) -> dict:
    """{tiny, key, bpm}: scales in quavers at the syllabus's crotchet speed, arpeggios in
    crotchets at its quaver speed (the same notes per minute, easier to read)."""
    scale = spec["type"] == "scale"
    pitches = (scale_pitches if scale else arpeggio_pitches)(spec["tonic"], spec["quality"], spec["range"], spec.get("start_octave"))
    key = spec["tonic"] + ("m" if spec["quality"] == "minor" else "")
    value = F(1, 2) if scale else F(1)
    return {"tiny": tiny(fill_bar([(p, value) for p in pitches], F(4)), key), "key": key,
            "bpm": spec.get("speed_bpm") or (50 if scale else 72), "pitches": pitches}


def technique_title(spec: dict) -> str:
    q = "major" if spec["quality"] == "major" else "minor"
    kind = "" if spec["type"] == "scale" else " arpeggio"
    span = {"octave": "1 oct", "twelfth": "a 12th"}[spec["range"]]
    start = " · from the upper tonic" if spec.get("start_octave") else ""
    return f"{templates.pretty_key(spec['tonic'])} {q}{kind} · {span}{start}"


def technique_stages() -> list[dict]:
    st = templates.stage
    return [st("notes", "Learn the notes", "both", "learn", 70),
            st("tongued", "Tongued, steadily", "both", "rehearse", 70),
            st("slurred", "Slurred, steadily", "both", "rehearse", 70),
            st("speed", "Tongued and slurred at exam speed, from memory", "both", "rehearse", 100, final=True)]


def expand_technique(item: dict, speeds: dict, grade: str) -> list[dict]:
    out = []
    for tonic in item["keys"]:
        spec = {"type": item["type"], "tonic": tonic, "quality": item.get("quality", "major"), "range": item.get("range", "octave"),
                "hands": "single", "artic": "tongued/slurred", "form": "choice" if item.get("choice") else None,
                "speed_bpm": speeds.get(item["type"], {}).get(grade)}
        if item.get("start_octave"):
            spec["start_octave"] = item["start_octave"]
        out.append(spec)
    return out


# -- First notes: the coach's own tier before Grade 1 -----------------------------------------

# Notes requirements: the pitches each one brings in. Anything that plays a pitch needs the
# requirement that taught it.
NOTE_STEPS = [
    {"key": "b-a-g", "title": "B, A and G", "new": [71, 69, 67], "tempo": 72,
     "text": "Left hand only: thumb on its key, then first, second and third fingers down for B, A and G. "
             "Right little finger rests on its key. Say 'too' into the flute to start each note.",
     "tiny": "b1 a1 g1 b2 a2 g1 b4 a g2 g4 a b2 b4 a g a g1"},
    {"key": "c-d", "title": "C and D", "new": [72, 74], "tempo": 72,
     "text": "C is only the left first finger (thumb off). D is all fingers down except the left first. "
             "Move one finger at a time and keep the air steady.",
     "tiny": "b1 c'1 d'1 c'2 b2 a2 c'2 d'4 c' b a g a b c' d'1 d'4 c' b a g1"},
    {"key": "low-e-f", "title": "Low E and F", "new": [64, 65], "tempo": 66,
     "text": "The low register: lips a little looser, air slower and aimed lower. "
             "Right hand fingers come down for F, then E. Let the low notes speak, don't push.",
     "tiny": "g1 f1 e1 f2 g2 e2 f2 g4 f e f g1 a4 g f e f g a b g1"},
    {"key": "f-sharp-b-flat", "title": "F♯ and B♭", "new": [66, 70], "tempo": 72,
     "text": "F♯ uses the right third finger instead of the first. B♭ uses the thumb B♭ lever (or 1 and 1). "
             "These two notes open up G major and F major.",
     "tiny": "g1 f#1 g2 f#2 g1 a1 b-1 a2 b-2 a1 g4 a b c' d' c' b a g f# g2 f4 g a b- c' b- a g f1"},
    {"key": "upper-e-f-g", "title": "E, F, F♯ and G an octave up", "new": [76, 77, 78, 79], "tempo": 66,
     "text": "Same fingers as low E, F and G; blow faster, a narrower air stream, lips a little firmer. "
             "Slur from the low note up to the high one without changing fingers.",
     "tiny": "e1 e'1 f1 f'1 g1 g'1 f'#2 g'2 d'4 e' f' g' f'1 c'4 d' e' f' g' f' e'2 d'4 e' f' e' d'1"},
]
TONE_STEPS = [
    {"key": "long-tones", "title": "Long tones", "tempo": 60, "after": "b-a-g",
     "text": "Hold each note for four slow beats with one even sound, start to finish. Breathe low before each one. "
             "This is how flute players build a good tone.",
     "tiny": "b1 b1 a1 a1 g1 g1"},
    {"key": "tonguing", "title": "Tonguing", "tempo": 72, "after": "b-a-g",
     "text": "Start every note with 'too', the tongue behind the top teeth. Keep the air going between notes; "
             "the tongue only interrupts it.",
     "tiny": "b4 b b b a a a a g g g g b b a a g g g2"},
    {"key": "slurs", "title": "Two-note slurs", "tempo": 66, "after": "c-d",
     "text": "Tongue the first note of each pair only, then move the fingers while the air keeps flowing.",
     "tiny": "b2 a2 a2 g2 b2 a2 g1 c'2 b2 b2 a2 a2 g2 g1"},
]
G2_NOTES = {"key": "upper-notes", "title": "New notes: E♭ and the top A to D", "new": [75, 81, 82, 83, 84, 86], "tempo": 60,
            "text": "Grade 2 climbs to a twelfth above the low tonic. The top notes need fast, focused air rather than more of it; "
                    "keep the lips relaxed and the flute still.",
            "tiny": "e'-1 f'1 g'1 a'1 b'-1 a'1 b'1 c''1 d''1 c''2 b'2 a'1 g'1"}


# -- theory: the coach's own progression -------------------------------------------------------

def _quiz(qid: str, prompt: str, options: list[str], answer: int, explain: str) -> dict:
    return {"id": qid, "type": "quiz", "prompt": prompt, "options": options, "answer": answer, "graded": True, "explain": explain}


# The very first lesson, a theory-style lesson filed under technique (Your first sound) so a
# beginner's Path opens with it, ahead of the first notes that need it.
FIRST_SOUND = ("making-a-sound", "Making a sound",
               "Rest the lip plate under your bottom lip, lips relaxed and nearly closed, and blow a narrow stream of air across the "
               "hole, as if blowing across a bottle. Start the note with 'too'. A breathy sound means the air is too wide or aimed "
               "too low.",
               [("How do you start a note on the flute?", ["Puff the cheeks", "Say 'too' with the tongue", "Hum"], 1,
                 "The tongue releases the air with 'too'; that's tonguing."),
                ("The sound is breathy and weak. What helps first?", ["Blow much harder", "Make the air stream narrower",
                                                                      "Press the keys harder"], 1,
                 "A narrow, focused air stream gives a clear tone; more air just adds noise.")])
FIRST_SOUND_ID = "initial.technique.sound.making-a-sound"

THEORY = {
    "initial": [
        ("treble-stave", "Notes on the treble stave",
         "Flute music uses the treble clef. The lines from the bottom are E G B D F, the spaces F A C E. "
         "Your first notes: G sits on the second line, A in the space above it, B on the middle line.",
         [("Which note sits on the middle line of the treble stave?", ["G", "B", "D"], 1, "The middle (third) line is B."),
          ("Which note is in the space just above G's line?", ["A", "F", "C"], 0, "Line G, then the space above it is A.")]),
        ("note-values", "Semibreves, minims and crotchets",
         "A crotchet lasts one beat, a minim two, a semibreve four (a whole 4/4 bar). Quavers come in pairs on one beat. "
         "Count out loud in your head while you play: one, two, three, four.",
         [("How many beats is a minim?", ["One", "Two", "Four"], 1, "A minim is two crotchets long."),
          ("A bar of 4/4 holds how many crotchets?", ["Three", "Four", "Two"], 1, "4/4: four crotchet beats in each bar.")]),
        ("breathing", "Breathing and breath marks",
         "Breathe in low, filling from the belly, shoulders still. Breathe at the end of a phrase, where a comma-shaped breath mark "
         "is printed or where a long note ends, never in the middle of a group of quick notes.",
         [("Where is the best place to breathe?", ["In the middle of quick notes", "At the end of a phrase", "Every bar"], 1,
           "Phrases are like sentences: breathe where the music pauses."),
          ("When you breathe in, what should stay still?", ["The shoulders", "The belly", "Nothing"], 0,
           "A low breath moves the belly; lifting the shoulders makes the breath shallow.")]),
    ],
    "g1": [
        ("key-signatures-f-g", "Key signatures: F and G major",
         "G major has one sharp, F♯, shown on the top line at the start of every stave. F major has one flat, B♭, on the middle line. "
         "The key signature applies to every one of those notes in the piece.",
         [("Which key has one sharp, F♯?", ["F major", "G major", "C major"], 1, "G major: F♯."),
          ("Which key has one flat, B♭?", ["F major", "E minor", "G major"], 0, "F major: B♭.")]),
        ("e-minor", "E minor",
         "E minor shares G major's key signature (F♯) but starts and ends on E. It sounds darker. At Grade 1 you may play the natural, "
         "harmonic or melodic form; the Roadmap uses the natural form: E F♯ G A B C D E.",
         [("Which major key shares E minor's key signature?", ["F major", "C major", "G major"], 2, "Both have one sharp, F♯: they're relative keys."),
          ("What note does an E minor scale start and end on?", ["G", "E", "B"], 1, "A scale starts and ends on its tonic: E.")]),
        ("time-3-4", "3/4 time and dotted minims",
         "3/4 has three crotchet beats in a bar, the first one strongest: ONE two three. A dotted minim lasts three beats, a whole 3/4 bar.",
         [("How many beats in a bar of 3/4?", ["Two", "Three", "Four"], 1, "The top number: three beats."),
          ("How long is a dotted minim?", ["Two beats", "Three beats", "Four beats"], 1, "A dot adds half: two plus one.")]),
        ("tonguing-slurs", "Tongued and slurred",
         "Tongued: each note starts with 'too'. Slurred: a curved line joins the notes, and only the first is tongued; the fingers move "
         "while the air carries on. In the exam the examiner chooses which, so learn every scale both ways.",
         [("In a slurred group, which notes are tongued?", ["Every note", "Only the first", "None"], 1,
           "Tongue the first note, then let the air carry the rest."),
          ("What joins slurred notes on the page?", ["A dot", "A curved line", "A straight line"], 1, "A slur is a curve over or under the notes.")]),
        ("dynamics-f-mf", "f and mf",
         "f (forte) means loud, mf (mezzo forte) moderately loud. On the flute, loud means faster air with the same relaxed lips, not "
         "blowing harder until the note cracks; keep the pitch steady.",
         [("What does mf mean?", ["Very quiet", "Moderately loud", "Very loud"], 1, "Mezzo forte: moderately loud."),
          ("What does f mean?", ["Loud", "Quiet", "Slow"], 0, "Forte: loud.")]),
    ],
    "g2": [
        ("c-major-a-minor", "C major and A minor",
         "C major and A minor have no sharps or flats. A minor is C major's relative minor: the same notes from A to A. "
         "At Grade 2, C major starts from the C an octave above the lowest.",
         [("How many sharps or flats does C major have?", ["None", "One", "Two"], 0, "C major uses no sharps or flats."),
          ("Which minor key shares C major's notes?", ["E minor", "A minor", "D minor"], 1, "A minor is the relative minor of C major.")]),
        ("time-2-4", "2/4 time",
         "2/4 has two crotchet beats in a bar: ONE two, like a march. Quavers often come in groups of four, one beat each pair.",
         [("How many crotchet beats in a bar of 2/4?", ["Two", "Three", "Four"], 0, "The top number says two."),
          ("Which feels like a march?", ["2/4", "3/4", "Both"], 0, "Two strong-weak beats: left, right.")]),
        ("dotted-crotchet", "Dotted crotchet and quaver",
         "A dotted crotchet lasts one and a half beats; the quaver after it makes up the second beat. Count 'one-and two': "
         "the quaver falls on the 'and' of two.",
         [("How long is a dotted crotchet?", ["One beat", "One and a half beats", "Two beats"], 1, "A dot adds half: one plus a half."),
          ("A dotted crotchet and a quaver together make…", ["One beat", "Two beats", "Three beats"], 1, "One and a half plus a half: two beats.")]),
        ("ties", "Tied notes",
         "A tie is a curve joining two notes of the same pitch: play one note lasting both values, without tonguing the second. "
         "A slur joins different notes; a tie joins the same note.",
         [("Two tied crotchets on the same note are played as…", ["Two notes", "One note of two beats", "A rest"], 1,
           "Tied notes are held as one."),
          ("A curve joins a G and an A. Is it a tie?", ["Yes", "No, it's a slur"], 1, "A tie only joins notes of the same pitch.")]),
        ("staccato", "Staccato",
         "A dot above or below a note means staccato: short and detached. On the flute, tongue it lightly with 'tut', stopping the air "
         "with the tongue, and keep the beat even.",
         [("What does a dot above a note mean?", ["Hold it longer", "Short and detached", "Louder"], 1, "Staccato: short and detached."),
          ("Staccato notes should keep…", ["A steady beat", "Getting faster", "Getting louder"], 0, "Short notes, but still in time.")]),
        ("dynamics-mp-cresc", "mp and crescendo",
         "mp (mezzo piano) is moderately quiet. A crescendo, the opening hairpin <, means get gradually louder. Quiet notes on the flute "
         "tend to go flat, so keep the air fast and aim a little higher.",
         [("What does mp mean?", ["Moderately quiet", "Moderately loud", "Very quiet"], 0, "Mezzo piano: moderately quiet."),
          ("An opening hairpin < means…", ["Get gradually quieter", "Get gradually louder", "Slow down"], 1, "Crescendo: gradually louder.")]),
    ],
}


def theory_lesson(stage_id: str, req_id: str, text: str, quizzes: list) -> dict:
    steps = [{"id": "read", "type": "read", "text": text}]
    steps += [_quiz(f"quiz-{k}", *q) for k, q in enumerate(quizzes, 1)]
    return {"id": stage_id, "version": 1, "made": "atlas.pan (the coach's own theory)", "checked": True, "requirement": req_id,
            "steps": steps}


# -- sight-reading: one line within the grade's range -------------------------------------------

SIGHT_FIRST = {"bars": 4, "times": ["4/4"], "keys": ["G"], "range": [67, 74], "rhythms": 0, "tempo": 60}
RHYTHMS = {  # bar patterns (quarter notes) by level, cumulative
    0: [(F(4),), (F(2), F(2)), (F(2), F(1), F(1)), (F(1), F(1), F(2)), (F(1),) * 4],
    1: [(F(3),), (F(2), F(1)), (F(1), F(1), F(1)), (F(1), F(1, 2), F(1, 2), F(1), F(1)), (F(1, 2), F(1, 2), F(1), F(2))],
    2: [(F(3, 2), F(1, 2), F(1), F(1)), (F(1, 2),) * 4 + (F(2),), (F(3, 2), F(1, 2), F(2)), (F(1), F(1)), (F(1, 2),) * 4],
}


def _bar_patterns(level: int, beats: F) -> list[tuple]:
    pats = [p for lv in range(level + 1) for p in RHYTHMS.get(lv, []) if sum(p) == beats]
    if not pats and beats in DURATIONS:
        pats = [(beats,)]
    return pats


def _pitch_of(name: str) -> int:
    """'E4' -> 64."""
    pc = PC[name[0]] + (1 if "#" in name else -1 if "b" in name[1:-1] else 0)
    return (int(name[-1]) + 1) * 12 + pc


def sight_params(syllabus: dict, tier: str) -> dict:
    if tier == "initial":
        return dict(SIGHT_FIRST, title="First notes")
    keys, times, level, out = [], [], 0, {}
    for k, g in enumerate(sorted(syllabus["grades"], key=lambda g: g["order"])):
        s = g.get("sight", {})
        keys += [x for x in s.get("keys", []) if x not in keys]
        times += [x for x in s.get("times", []) if x not in times]
        level = k + 1
        out = {"bars": int(s.get("bars", 4)), "times": list(times), "keys": list(keys), "rhythms": level,
               "range": [_pitch_of(s["range"][0]), _pitch_of(s["range"][1])] if s.get("range") else [64, 77],
               "tempo": 60 + 6 * level, "title": g["title"]}
        if g["id"] == tier:
            return out
    raise ValueError(f"No sight-reading parameters for {tier}")


def sight_piece(p: dict, seed: int) -> dict:
    """{tiny, key, time, bpm, pitches}: a one-line tune, mostly by step, starting and ending on the tonic."""
    rng = random.Random(seed)
    key = rng.choice(p["keys"])
    time = rng.choice(p["times"])
    num, den = (int(x) for x in time.split("/"))
    beats = F(num * 4, den)
    pc, steps = key_tonic(key)
    lo, hi = p["range"]
    scale = [m for m in range(lo, hi + 1) if (m - pc) % 12 in steps]
    tonics = [i for i, m in enumerate(scale) if m % 12 == pc]
    mid = (lo + hi) / 2
    home = min(tonics, key=lambda i: abs(scale[i] - mid))
    notes, i = [], home
    for b in range(p["bars"]):
        last = b == p["bars"] - 1
        rhythm = (beats,) if last and beats in DURATIONS else rng.choice(_bar_patterns(p["rhythms"], beats))
        for k, d in enumerate(rhythm):
            if last:
                i = home
            elif not (b == 0 and k == 0):
                if b == p["bars"] - 2:  # head for a note next to the tonic, reaching it on the bar's last note
                    target = home + 1 if i > home or home == 0 else home - 1
                    left = len(rhythm) - k
                    i += -(-(target - i) // left) if target > i else (target - i) // left
                else:
                    step = rng.choice([-1, 1, -1, 1, 0, -2, 2])
                    i = max(0, home - 4, min(len(scale) - 1, home + 4, i + step))
            notes.append((scale[i], d))
    return {"tiny": tiny(notes, key), "key": key, "time": time, "bpm": p["tempo"], "pitches": [n for n, _ in notes]}


def sight_lesson(stage: dict, req: dict) -> dict:
    st = stage["stage"]
    spec = req.get("spec", {})
    if "standard" in spec:
        what = "Read a tune you haven't seen: 30 seconds to look it over and finger it silently, then play it through without stopping."
    elif "key" in spec:
        what = f"{req['title']}: check the key signature and which notes it changes before you play."
    elif "time" in spec:
        what = f"{req['title']}: find the beat and count a bar in your head before you start."
    else:
        what = f"New here: {req['title'].lower()}. Spot it in the tune before you play."
    prepared = st["key"] in ("learn", "prepared")
    text = what + (" Take your time with this one." if prepared else " Keep going whatever happens: the pulse matters more than every note.")
    rule = LEARN_PASS if st["mode"] == "learn" else {"metric": "overall", "min": 65 if not prepared else 70}
    return {"id": stage["id"], "version": 1, "made": "atlas.pan", "checked": True, "requirement": req["id"],
            "steps": [{"id": "read", "type": "read", "text": text},
                      {"id": "play", "type": "play", "pool": f"sight/{req['tier']}-", "hand": "both", "mode": st["mode"],
                       "tempo_percent": st["tempo_percent"], "graded": True, "pass": rule}]}


# -- pieces --------------------------------------------------------------------------------------

def load_tunes(path: str | pathlib.Path | None = None) -> list[dict]:
    p = pathlib.Path(path) if path else PACKAGE / "data" / "pan_tunes.json"
    return json.loads(p.read_text(encoding="utf-8"))["tunes"]


def tune_bars(tune: dict) -> int:
    from ..lessons import _tiny
    from music21 import meter

    total = sum(n.quarterLength for n in _tiny(tune["tiny"], tune["time"]))
    return int(-(-total // meter.TimeSignature(tune["time"]).barDuration.quarterLength))


def tune_pitches(tune: dict) -> list[int]:
    from ..lessons import _tiny

    return [n.pitch.midi for n in _tiny(tune["tiny"], tune["time"]) if n.isNote]


def piece_stages(bars: int) -> list[dict]:
    """Four-bar sections in Learn mode, then the whole tune at rising tempo."""
    st = templates.stage
    out = []
    if bars > 4:
        for k, start in enumerate(range(1, bars + 1, 4), 1):
            end = min(bars, start + 3)
            out.append(dict(st(f"s{k}", f"Bars {start}-{end}", "both", "learn", 80), bars=f"{start}-{end}"))
    else:
        out.append(st("learn", "Learn the notes", "both", "learn", 80))
    return out + [st("whole-60", "Whole tune at 60%", "both", "rehearse", 60),
                  st("whole-80", "Whole tune at 80%", "both", "rehearse", 80),
                  st("whole", "Whole tune at tempo", "both", "rehearse", 100, final=True)]


def _play_lesson(stage: dict, req: dict, file: str, text: str, made: str, checked: bool = True, plays: list[str] | None = None) -> dict:
    st = stage["stage"]
    learn = st["mode"] == "learn"
    bars = st.get("bars")
    listen = {"id": "listen", "type": "listen", "file": file, "hand": "both", "tempo_percent": st["tempo_percent"]}
    steps = [{"id": "read", "type": "read", "text": text + (" Learn mode waits for each note." if learn else " Rehearse keeps the beat.")}, listen]
    for name in plays or ["play"]:
        play = {"id": name, "type": "play", "file": file, "hand": "both", "mode": st["mode"], "tempo_percent": st["tempo_percent"],
                "graded": True, "pass": LEARN_PASS if learn else rehearse_pass(st["tempo_percent"])}
        if name != "play":
            play["title"] = name.split("-", 1)[1].capitalize()
        steps.append(play)
    if bars:
        for s in steps[1:]:
            s["bars"] = bars
    return {"id": stage["id"], "version": 1, "made": made, "checked": checked, "requirement": req["id"], "steps": steps}


# -- the tree ------------------------------------------------------------------------------------

def build(syllabus: dict, tunes: list[dict]) -> tuple[dict, dict]:
    """(atlas, plan): the tree in the Atlas's shape, and what to write for each stage
    ({stage id: (kind, data)}) so write() makes the lessons and music."""
    tree = Tree()
    first = {"id": "initial", "title": "First notes", "order": 0, "aural": syllabus.get("first_notes_aural", [])}
    grades = [first] + sorted(syllabus["grades"], key=lambda g: g["order"])
    order = {g["id"]: g["order"] for g in grades}
    speeds = syllabus.get("speeds", {})
    plan: dict[str, tuple[str, dict]] = {}
    teaches: dict[int, str] = {}  # pitch -> the notes requirement that teaches it
    pitches_of: dict[str, set[int]] = {}

    def stages_plan(req: dict, kind: str, data: dict) -> None:
        for sid in req["stages"]:
            plan[sid] = (kind, dict(data, req=req["id"]))

    def theory_req(fam: dict, tid: str, title: str, text: str, quizzes: list) -> None:
        req = tree.requirement(fam, tid, title, "theory", [dict(templates.stage("learn", "Learn it", final=True), answer="quiz")],
                               spec={"topic": tid})
        stages_plan(req, "theory", {"text": text, "quizzes": quizzes})

    for g in grades:
        gid = g["id"]
        tree.add({"id": gid, "level": "tier", "title": g["title"], "order": g["order"], "tier": gid})
        for s in STRANDS:
            tree.add({"id": f"{gid}.{s['id']}", "level": "strand", "parent": gid, "tier": gid, "strand": s["id"],
                      "title": f"{g['title']} · {s['title']}"})

        # Notes and tone (First notes), new notes (Grade 2), then scales and arpeggios.
        note_steps = NOTE_STEPS if gid == "initial" else [G2_NOTES] if gid == "g2" else []
        if gid == "initial":
            theory_req(tree.family(gid, "technique", "sound", "Your first sound"), *FIRST_SOUND)
        if note_steps:
            fam = tree.family(gid, "technique", "notes", "New notes")
            for ns in note_steps:
                req = tree.requirement(fam, ns["key"], ns["title"], "notes", [
                    templates.stage("learn", "Find the notes", "both", "learn", 70),
                    templates.stage("steady", "In time, steadily", "both", "rehearse", 80),
                    templates.stage("tempo", "In time, at tempo", "both", "rehearse", 100, final=True)],
                    spec={"notes": ns["new"]}, covers=[f"note:{p}" for p in ns["new"]])
                for p in ns["new"]:
                    teaches[p] = req["id"]
                stages_plan(req, "exercise", ns)
        if gid == "initial":
            fam = tree.family(gid, "technique", "tone", "Tone & tonguing")
            for ts in TONE_STEPS:
                req = tree.requirement(fam, ts["key"], ts["title"], "notes", [
                    templates.stage("learn", "Slowly", "both", "learn", 80),
                    templates.stage("tempo", "In time", "both", "rehearse", 100, final=True)], spec={"tone": ts["key"]})
                req["prereqs"] = [f"initial.technique.notes.{ts['after']}"]
                stages_plan(req, "exercise", ts)
        for item in g.get("technique", []):
            fkey = "scales" if item["type"] == "scale" else "arpeggios"
            fam = tree.family(gid, "technique", fkey, "Scales" if fkey == "scales" else "Arpeggios")
            for spec in expand_technique(item, speeds, gid):
                rid = templates.slug(f"{spec['type']}-{spec['tonic']}-{spec['quality']}-{spec['range']}")
                req = tree.requirement(fam, rid, technique_title(spec), "technique", technique_stages(), spec=spec,
                                       covers=[f"type:{spec['type']}", f"key:{spec['tonic']}{'m' if spec['quality'] == 'minor' else ''}"])
                pitches_of[req["id"]] = set(technique_music(spec)["pitches"])
                stages_plan(req, "technique", {"spec": spec, "title": req["title"]})

        # Pieces: public-domain tunes, one family per list.
        for lst in (["first"] if gid == "initial" else ["A", "B", "C"]):
            fam = tree.family(gid, "pieces", "first-tunes" if lst == "first" else f"list-{lst.lower()}", LISTS[lst])
            for t in tunes:
                if t["tier"] == gid and t["list"] == lst:
                    req = tree.requirement(fam, t["id"], f"{t['title']} ({t['composer'].split()[-1]})", "piece",
                                           piece_stages(tune_bars(t)), piece=t["id"], covers=[f"key:{t['key']}"])
                    pitches_of[req["id"]] = set(tune_pitches(t))
                    stages_plan(req, "piece", {"tune": t})

        # Sight-reading.
        sight = SIGHT_FIRST if gid == "initial" else g.get("sight", {})
        if gid != "initial":
            fam = tree.family(gid, "sight", "keys-times", "New keys & times")
            for key in sight.get("keys", []):
                minor = key.endswith("m")
                title = f"Reading in {templates.pretty_key(key[:-1] if minor else key)} {'minor' if minor else 'major'}"
                req = tree.requirement(fam, "key-" + templates.slug(key), title, "sight", templates.sight_stages("feature"),
                                       covers=[f"key:{key}"], spec={"key": key})
                stages_plan(req, "sight", {})
            for time in sight.get("times", []):
                req = tree.requirement(fam, "time-" + templates.slug(time), f"Reading in {time}", "sight",
                                       templates.sight_stages("feature"), covers=[f"time:{time}"], spec={"time": time})
                stages_plan(req, "sight", {})
            if sight.get("features"):
                fam = tree.family(gid, "sight", "features", "New features")
                for f in sight["features"]:
                    req = tree.requirement(fam, templates.slug(f)[:48], f[0].upper() + f[1:], "sight",
                                           templates.sight_stages("feature"), spec={"feature": f})
                    stages_plan(req, "sight", {})
        fam = tree.family(gid, "sight", "standard", "At grade standard")
        req = tree.requirement(fam, "standard", f"{g['title']} sight-reading ({sight.get('bars', 4)} bars)", "sight",
                               templates.sight_stages("standard"), spec={"standard": {k: v for k, v in sight.items() if k != "range"}})
        stages_plan(req, "sight", {})

        # Aural tests (the same as every ABRSM instrument's).
        if g.get("aural"):
            fam = tree.family(gid, "aural", "tests", "Aural tests")
            for test in g["aural"]:
                tree.requirement(fam, templates.slug(test["id"]), f"{test['test']}. {test['title']}", "aural",
                                 templates.aural_stages(test), spec=test, covers=[f"aural:{s}" for s in test["skills"]])

        # Theory.
        fam = tree.family(gid, "theory", "topics", "Theory")
        for tid, title, text, quizzes in THEORY.get(gid, []):
            theory_req(fam, tid, title, text, quizzes)

        tree.add({"id": f"{gid}.review", "level": "review", "parent": gid, "tier": gid, "title": f"{g['title']} review"})
        if gid != "initial":
            tree.add({"id": f"{gid}.exam", "level": "exam", "parent": gid, "tier": gid, "title": f"{g['title']} mock exam",
                      "prereqs": [f"{gid}.review"]})

    for ns in NOTE_STEPS + TONE_STEPS + [G2_NOTES]:
        for n in tree.nodes:
            if n["level"] == "requirement" and n["kind"] == "notes" and n["id"].endswith(f".{ns['key']}"):
                pitches_of[n["id"]] = set(_exercise_pitches(ns["tiny"]))
    _link(tree, order, teaches, pitches_of)
    for n in tree.nodes:  # first stages follow the requirement's own prerequisites
        if n["level"] == "requirement" and n.get("stages"):
            first = tree.by_id[n["stages"][0]]
            first["prereqs"] = [tree.by_id[i]["stages"][-1] for i in n["prereqs"] if tree.by_id.get(i, {}).get("stages")]
    atlas = {"version": VERSION, "name": "Roadmap", "instrument": "flute", "source": syllabus.get("source"),
             "syllabus_version": syllabus.get("version"), "strands": STRANDS,
             "tiers": [{"id": g["id"], "title": g["title"], "order": g["order"]} for g in grades], "nodes": tree.nodes}
    layout(atlas)
    return atlas, plan


def _exercise_pitches(text: str) -> list[int]:
    from ..lessons import _tiny

    return [n.pitch.midi for n in _tiny(text, "4/4") if n.isNote]


def _link(tree: Tree, order: dict, teaches: dict[int, str], pitches_of: dict[str, set[int]]) -> None:
    """Prerequisites: the notes a requirement plays (each needs the requirement that teaches
    it), the scale before its arpeggio and the same scale a grade earlier, a key's scale
    before reading in it, the grade's sight-reading before its standard, the same aural test
    a grade earlier, and the theory topics in order, Making a sound before the first notes."""
    reqs = [n for n in tree.nodes if n["level"] == "requirement"]
    g = lambda n: order[n["tier"]]  # noqa: E731
    tech = [r for r in reqs if r["kind"] == "technique"]
    chain = [r["id"] for r in reqs if r["kind"] == "notes" and "notes" in r.get("spec", {})]  # each needs the one before
    for r in reqs:
        pre = set(r.get("prereqs", []))
        taught = {teaches[p] for p in pitches_of.get(r["id"], ()) if teaches.get(p) and teaches[p] != r["id"]}
        if taught and r["kind"] != "notes":
            pre.add(max(taught, key=chain.index))  # the latest notes step it uses brings the earlier ones
        if r["kind"] == "notes":
            notes = [x for x in reqs if x["kind"] == "notes" and "notes" in x.get("spec", {})]
            k = notes.index(r) if r in notes else -1
            if k > 0:
                pre.add(notes[k - 1]["id"])
            elif r["tier"] == "initial":  # the very first notes come after learning to make a sound
                pre.add(FIRST_SOUND_ID)
        elif r["kind"] == "technique":
            s = r["spec"]
            same = [x for x in tech if x is not r and x["spec"]["tonic"] == s["tonic"] and x["spec"]["quality"] == s["quality"]]
            if s["type"] == "arpeggio":
                pre.update(x["id"] for x in same if x["spec"]["type"] == "scale" and g(x) == g(r))
            pre.update(x["id"] for x in same if x["spec"]["type"] == s["type"] and g(x) == g(r) - 1)
        elif r["kind"] == "piece":
            key = r["covers"][0].split(":")[1]
            pc, quality = key_tonic(key)
            scales = [x for x in tech if x["spec"]["type"] == "scale" and g(x) <= g(r)
                      and key_tonic(x["spec"]["tonic"] + ("m" if x["spec"]["quality"] == "minor" else ""))[0] == pc]
            if scales:
                pre.add(max(scales, key=g)["id"])
        elif r["kind"] == "sight":
            spec = r.get("spec", {})
            if "standard" not in spec:  # a grade's new reading builds on the last grade's standard
                pre.update(x["id"] for x in reqs if x["kind"] == "sight" and "standard" in x.get("spec", {}) and g(x) == g(r) - 1)
            if "key" in spec:
                pc, _ = key_tonic(spec["key"])
                pre.update(x["id"] for x in tech if x["spec"]["type"] == "scale" and g(x) <= g(r)
                           and key_tonic(x["spec"]["tonic"] + ("m" if x["spec"]["quality"] == "minor" else ""))[0] == pc
                           and (x["spec"]["quality"] == "minor") == spec["key"].endswith("m"))
            if "standard" in spec:
                pre.update(x["id"] for x in reqs if x["kind"] == "sight" and x["tier"] == r["tier"] and x is not r)
                pre.update(x["id"] for x in reqs if x["kind"] == "sight" and "standard" in x.get("spec", {}) and g(x) == g(r) - 1)
            if r["tier"] == "initial":
                pre.add("initial.technique.notes.c-d")
        elif r["kind"] == "aural":
            pre.update(x["id"] for x in reqs if x["kind"] == "aural" and x["spec"]["id"] == r["spec"]["id"] and g(x) == g(r) - 1)
        elif r["kind"] == "theory":
            topics = [x for x in reqs if x["kind"] == "theory"]
            k = topics.index(r)
            if k:
                pre.add(topics[k - 1]["id"])
        r["prereqs"] = sorted(p for p in pre if p in tree.by_id and p != r["id"])


# -- writing it all --------------------------------------------------------------------------------

def write(syllabus: dict, out: pathlib.Path | None = None, tunes: list[dict] | None = None, sight_count: int = 8,
          lint: bool = True) -> dict:
    """Build Pan into out (default <home>/atlas/pan): atlas.json, the lessons and their music.
    Every score is linted with the engraving rules and read back note for note."""
    from .. import engraving
    from ..lessons import build_lesson

    out = pathlib.Path(out) if out else content_dir()
    lessons = out / "lessons"
    for sub in ("technique", "first", "pieces", "sight"):
        (lessons / sub).mkdir(parents=True, exist_ok=True)
    tunes = tunes if tunes is not None else load_tunes()
    atlas, plan = build(syllabus, tunes)
    if not (out / "syllabus.json").exists():  # the Atlas's writers read it from the content folder
        (out / "syllabus.json").write_text(json.dumps(syllabus, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "atlas.json").write_text(json.dumps(atlas, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    report = {"nodes": len(atlas["nodes"]), "lessons": 0, "scores": 0, "problems": []}

    def score(folder: str, name: str, title: str, text: str, key: str, time: str, bpm: int) -> str:
        path, parsed = build_lesson(title, text, None, time, key, bpm, out_dir=lessons / folder, filename=name, part_name=PART)
        want = sorted(_tiny_midis(text, time))
        got = sorted(n.pitch for n in parsed.notes)
        if got != want:
            report["problems"].append(f"{folder}/{name}: read back {len(got)} notes, wrote {len(want)}")
        if lint:
            found = engraving.lint(pathlib.Path(path).read_text(encoding="utf-8"))["findings"]
            if found:
                report["problems"].append(f"{folder}/{name}: " + "; ".join(sorted({f['rule'] for f in found})))
        report["scores"] += 1
        return f"{folder}/{name}.musicxml"

    files: dict[str, str] = {}
    by_id = {n["id"]: n for n in atlas["nodes"]}
    tier_title = {t["id"]: t["title"] for t in atlas["tiers"]}
    for sid, (kind, data) in plan.items():
        stage, req = by_id[sid], by_id[data["req"]]
        if kind == "theory":
            lesson = theory_lesson(sid, req["id"], data["text"], data["quizzes"])
        elif kind == "sight":
            lesson = sight_lesson(stage, req)
        elif kind == "exercise":
            if req["id"] not in files:
                files[req["id"]] = score("first", templates.slug(req["id"]), data["title"], data["tiny"], "C", "4/4", data["tempo"])
            lesson = _play_lesson(stage, req, files[req["id"]], f"{data['title']}. {data['text']}", "atlas.pan (First notes)")
        elif kind == "technique":
            spec = data["spec"]
            if req["id"] not in files:
                m = technique_music(spec)
                files[req["id"]] = score("technique", templates.slug(req["id"]), f"{tier_title[req['tier']]} · {data['title']}",
                                         m["tiny"], m["key"], "4/4", m["bpm"])
            st = stage["stage"]
            how = {"notes": "Learn the notes and fingerings slowly, tongued.", "tongued": "Every note tongued with 'too', evenly.",
                   "slurred": "Slurred: tongue the first note only, the air carries the rest; breathe at the top if you need to.",
                   "speed": "As in the exam, from memory: once tongued, once slurred."}[st["key"]]
            minor = " The coach uses the natural minor; the exam lets you choose natural, harmonic or melodic." if spec.get("form") == "choice" else ""
            plays = ["play-tongued", "play-slurred"] if st["key"] == "speed" else None
            lesson = _play_lesson(stage, req, files[req["id"]], f"{data['title'].replace(' · ', ', ')}. {how}{minor}", "atlas.pan (from the syllabus spec)",
                                  plays=plays)
        elif kind == "piece":
            t = data["tune"]
            if req["id"] not in files:
                files[req["id"]] = score("pieces", t["id"], t["title"], t["tiny"], t["key"], t["time"], t["tempo"])
            st = stage["stage"]
            text = f"{t['title']}, {t['composer']}. {st['title']}."
            lesson = _play_lesson(stage, req, files[req["id"]], text, "atlas.pan (public-domain tune)")
            lesson["piece"] = t["id"]
        else:
            continue
        (lessons / f"{sid}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
        report["lessons"] += 1

    # Sight-reading pools: fresh tunes for each tier, checked like the rest.
    for tier in [t["id"] for t in atlas["tiers"]]:
        params = sight_params(syllabus, tier)
        n, seed = 0, 0
        while n < sight_count and seed < sight_count * 20:
            seed += 1
            piece = sight_piece(params, seed * 7919 + len(tier))
            path, parsed = build_lesson(f"Sight-reading · {params['title']}", piece["tiny"], None, piece["time"], piece["key"],
                                        piece["bpm"], out_dir=lessons / "sight", filename=f"{tier}-{n + 1}", part_name=PART)
            if lint and engraving.lint(pathlib.Path(path).read_text(encoding="utf-8"))["findings"]:
                continue
            n += 1
        report["scores"] += n
        if n < sight_count:
            report["problems"].append(f"sight/{tier}: only {n} clean pieces")

    # Aural lessons: the Atlas's writer, pointed at Pan's tree.
    if any(n["level"] == "requirement" and n["kind"] == "aural" for n in atlas["nodes"]):
        from . import aural_lessons

        with _as_content(out):
            report["lessons"] += aural_lessons.write_lessons()
    return report


def _tiny_midis(text: str, time: str) -> list[int]:
    from ..lessons import _tiny

    return [n.pitch.midi for n in _tiny(text, time) if n.isNote]


def load_syllabus(path: str | pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path) if path else content_dir() / "syllabus.json"
    if not p.is_file():
        raise FileNotFoundError(f"No flute syllabus at {p}. It is drafted locally from your copy of the ABRSM woodwind "
                                "syllabus (see 'The Roadmap' in midi_coach/README.md).")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    syllabus = load_syllabus(args[0] if args else None)
    report = write(syllabus)
    print(f"{content_dir()}: {report['nodes']} nodes, {report['lessons']} lessons, {report['scores']} scores")
    for p in report["problems"]:
        print("  problem:", p)


if __name__ == "__main__":
    main()
