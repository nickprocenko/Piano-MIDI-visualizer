"""The Roadmap for the fiddle: Pan's engine (atlas.pan) with the coach's own fiddle course.

Three tiers, all the coach's own (no exam board's syllabus): First notes (holding the fiddle and
bow, the open strings, then the fingers on the A, D, E and G strings in first position, the low
second finger; whole bows, string crossing, slurs), then Grades 1 and 2 with scales and
arpeggios in the fiddle's keys, sight-reading and public-domain tunes (data/fiddle_tunes.json).
The syllabus is data/fiddle_syllabus.json; the aural tests, the same as every instrument's,
come from the flute's local syllabus when there is one (they are ABRSM's, so never in git).

The fiddle reads the treble clef at sounding pitch and is heard through the microphone.

    python -m midi_coach.atlas.fiddle   build <home>/atlas/fiddle
"""

from __future__ import annotations

from . import pan

THEORY_BY_ID = {t[0]: t for tier in pan.THEORY.values() for t in tier}
STRANDS = [
    {"id": "pieces", "title": "Tunes", "glyph": "♫"},
    {"id": "technique", "title": "Scales & bowing", "glyph": "♯"},
    {"id": "sight", "title": "Sight-reading", "glyph": "◎"},
    {"id": "aural", "title": "Aural", "glyph": "∿"},
    {"id": "theory", "title": "Theory", "glyph": "♭"},
]
LISTS = {"first": "First tunes", "A": "Lively tunes", "B": "Slow airs", "C": "Folk tunes"}

NOTE_STEPS = [
    {"key": "open-strings", "title": "The open strings: G, D, A and E", "new": [55, 62, 69, 76], "tempo": 60,
     "text": "No fingers yet: bow each open string with a straight bow halfway between the bridge and the fingerboard. "
             "Tilt the bow arm to change string: low for G, high for E.",
     "tiny": "a1 a2 a2 e'1 e'2 e'2 d1 d2 d2 G1 G2 G2 a2 e'2 a2 d2 a1"},
    {"key": "a-string", "title": "B, C♯ and D on the A string", "new": [71, 73, 74], "tempo": 66,
     "text": "First finger for B, second for C♯ (a whole step on, close to the third), third for D, the same note as the "
             "open D string an octave up. Fingertips land on the string, the thumb stays soft opposite the first finger.",
     "tiny": "a2 b2 c'#2 d'2 d'2 c'#2 b2 a2 a4 b c'# d' e'1 d'4 c'# b a a1"},
    {"key": "d-string", "title": "E, F♯ and G on the D string", "new": [64, 66, 67], "tempo": 66,
     "text": "The same finger pattern one string over: first finger E, second F♯, third G. Now you have the whole D major "
             "scale, D to D across two strings.",
     "tiny": "d2 e2 f#2 g2 a2 g2 f#2 e2 d4 e f# g a b c'# d' d'4 c'# b a g f# e d d1"},
    {"key": "e-string", "title": "F♯, G♯ and A on the E string", "new": [78, 80, 81], "tempo": 66,
     "text": "The same pattern on the E string: first finger F♯, second G♯, third A. With the A string that makes the A "
             "major scale. Keep the bow arm high so the A string stays silent.",
     "tiny": "e'2 f'#2 g'#2 a'2 a'2 g'#2 f'#2 e'2 a4 b c'# d' e' f'# g'# a' a'4 g'# f'# e' d' c'# b a a1"},
    {"key": "g-string", "title": "A, B and C on the G string", "new": [57, 59, 60], "tempo": 66,
     "text": "The low string: first finger A, second B, third C. Lower the bow arm and let the G string ring; it needs a "
             "little more weight in the bow.",
     "tiny": "G2 A2 B2 c2 d1 c4 B A G A2 B2 c4 B A G G1"},
    {"key": "low-two", "title": "Low second finger: C and G", "new": [72, 79], "tempo": 60,
     "text": "Slide the second finger back until it touches the first: C natural on the A string, G natural on the E "
             "string. The low second finger opens G major across all four strings, C major and the minor keys.",
     "tiny": "a2 b2 c'2 d'2 d'2 c'2 b2 a2 e'2 f'#2 g'2 a'2 a'2 g'2 f'#2 e'2 g4 a b c' d' e' f'# g' g'1"},
]
TONE_STEPS = [
    {"key": "whole-bows", "title": "Whole bows", "tempo": 60, "after": "open-strings",
     "text": "Four slow beats to each bow, from the frog to the tip and back, the bow straight and the sound even all "
             "the way. Down bow pulls, up bow pushes. This is how fiddlers build a clear tone.",
     "tiny": "a1 a1 d1 d1 e'1 e'1 G1 G1"},
    {"key": "string-crossing", "title": "String crossing", "tempo": 66, "after": "a-string",
     "text": "Rock between two strings with the elbow, not the wrist alone, so the bow lands on the new string cleanly "
             "without touching a third.",
     "tiny": "a4 e' a e' d a d a a e' d' e' a1"},
    {"key": "slurs", "title": "Two notes to a bow", "tempo": 66, "after": "d-string",
     "text": "A slur joins notes in one bow: change the finger while the bow keeps moving, and share the bow between them.",
     "tiny": "d2 e2 f#2 g2 a2 b2 a2 g2 f#2 e2 d1"},
]
G2_NOTES = {"key": "low-first-finger", "title": "New notes: F, B♭, F on the E string, and B", "new": [65, 70, 77, 83],
            "tempo": 60,
            "text": "Grade 2's flat keys pull the first finger back, close to the nut: F on the D string, B♭ on the A string, "
                    "F on the E string. B on the E string is the fourth finger, a whole step above the third.",
            "tiny": "d2 f2 a2 d'2 a2 b-2 a2 g2 e'2 f'2 e'2 d'2 e'4 f'# g'# a' b'1 a'4 g' f' e' d'1"}

FIRST_SOUND = ("holding-fiddle-and-bow", "Holding the fiddle and bow",
               "Rest the fiddle on the left collarbone, the jaw lightly on the chinrest, the scroll pointing out to the left. "
               "Hold the bow with a curved thumb under the frog and the fingers draped over the stick, the little finger "
               "curved on top. Rosin the bow, place it on the A string halfway between the bridge and the fingerboard, and "
               "pull it straight across with the arm's weight. A scratchy sound usually means too much pressure or a crooked "
               "bow; a thin one too little.",
               [("Where does the bow go on the string?", ["Over the fingerboard", "Halfway between the bridge and fingerboard",
                                                          "Touching the bridge"], 1,
                 "Halfway between the bridge and the fingerboard gives a clear, full sound."),
                ("The note scratches. What helps first?", ["Press harder", "Lighten the bow and keep it straight", "Bow faster"], 1,
                 "Too much pressure or a crooked bow scratches; let the arm's weight do the work.")])

THEORY = {
    "initial": [
        ("treble-stave", "Notes on the treble stave",
         "Fiddle music uses the treble clef. The open D string is the space just under the stave, A the second space up, "
         "E the top space. The G string hangs below on two ledger lines: G sits just under the second one.",
         [("Which open string is written in the top space?", ["E", "A", "D"], 0, "The spaces from the bottom are F A C E: E is the top."),
          ("Where is the open A string written?", ["The second space", "The middle line", "Under the stave"], 0,
           "A is the second space up.")]),
        THEORY_BY_ID["note-values"],
        ("bow-marks", "Down bows and up bows",
         "⊓ means down bow: pull from the frog towards the tip. V means up bow: push from the tip back. Without marks, start "
         "a bar on a down bow and take turns.",
         [("What does ⊓ mean?", ["Down bow", "Up bow", "Pluck"], 0, "The square sign is a down bow, pulled from the frog."),
          ("What does V mean?", ["Down bow", "Up bow", "Loud"], 1, "V is an up bow, pushed from the tip.")]),
    ],
    "g1": [
        ("key-signatures-d-a-g", "Key signatures: D, A and G major",
         "G major has one sharp, F♯. D major has two, F♯ and C♯. A major has three, F♯, C♯ and G♯. They are the fiddle's home "
         "keys because the open strings sit in them.",
         [("Which key has F♯ and C♯?", ["G major", "D major", "A major"], 1, "D major: two sharps, F♯ and C♯."),
          ("How many sharps does A major have?", ["One", "Two", "Three"], 2, "F♯, C♯ and G♯.")]),
        THEORY_BY_ID["time-3-4"],
        ("separate-slurred", "Separate and slurred",
         "Separate bows: each note gets its own bow, changing direction every note. Slurred: a curved line joins the notes, "
         "and they share one bow while the fingers change. Learn every scale both ways.",
         [("In a slurred group, how many bows?", ["One for each note", "One for the whole group", "None"], 1,
           "Slurred notes share one bow."),
          ("Separate bows change direction…", ["Every note", "Every bar", "Never"], 0, "Each note gets its own bow.")]),
        ("repeats", "Repeat signs",
         "Two dots before a double bar line mean go back and play again, from the matching sign facing the other way or "
         "from the start. Most fiddle tunes are two parts, each played twice: AABB.",
         [("What do two dots before a double bar mean?", ["Stop", "Play the section again", "Play louder"], 1,
           "It's a repeat sign: go back and play the section again."),
          ("A tune played AABB has…", ["Two parts, each twice", "Four different parts", "One part"], 0,
           "Part A twice, then part B twice.")]),
        ("dynamics-f-mf", "f and mf",
         "f (forte) means loud, mf (mezzo forte) moderately loud. On the fiddle, loud means more arm weight and a little more "
         "bow, closer to the bridge; keep the bow straight so it doesn't crunch.",
         THEORY_BY_ID["dynamics-f-mf"][3]),
    ],
    "g2": [
        THEORY_BY_ID["c-major-a-minor"],
        ("f-major-e-minor", "F major and E minor",
         "F major has one flat, B♭: the low first finger on the A string. E minor shares G major's F♯ but makes E its home. "
         "The Roadmap plays the natural form: E F♯ G A B C D E.",
         [("Which key has one flat?", ["F major", "E minor", "C major"], 0, "F major: B♭."),
          ("Which major key shares E minor's key signature?", ["G major", "C major", "D major"], 0, "Both have one sharp, F♯.")]),
        THEORY_BY_ID["time-2-4"],
        THEORY_BY_ID["dotted-crotchet"],
        ("ties", "Tied notes",
         "A tie is a curve joining two notes of the same pitch: play one note lasting both values, in one bow, without "
         "starting the second again. A slur joins different notes; a tie joins the same note.",
         THEORY_BY_ID["ties"][3]),
        ("staccato", "Staccato",
         "A dot above or below a note means staccato: short and detached. On the fiddle, stop the bow on the string between "
         "notes, a small bite at the start of each, and keep the beat even.",
         THEORY_BY_ID["staccato"][3]),
    ],
}

TECHNIQUE_STAGES = [("notes", "Learn the notes, separate bows", "learn", 70), ("separate", "Separate bows, steadily", "rehearse", 70),
                    ("slurred", "Two notes to a bow, steadily", "rehearse", 70),
                    ("speed", "Separate and slurred at tempo, from memory", "rehearse", 100)]
TECHNIQUE_HOW = {"notes": "Learn the notes and fingers slowly, one bow to each note.",
                 "separate": "Separate bows, evenly: the same length of bow for every note.",
                 "slurred": "Two notes to a bow: change the finger while the bow keeps moving.",
                 "speed": "At tempo and from memory: once with separate bows, once slurred."}
SIGHT_FIRST = {"bars": 4, "times": ["4/4"], "keys": ["D"], "range": [62, 69], "rhythms": 0, "tempo": 60}

FIDDLE = pan.Course(instrument="fiddle", folder="fiddle", part="Fiddle", made="atlas.fiddle", lowest=55, highest=83,
                    note_steps=NOTE_STEPS, tone_steps=TONE_STEPS, g2_notes=G2_NOTES, first_sound=FIRST_SOUND, theory=THEORY,
                    tunes="fiddle_tunes.json", sight_first=SIGHT_FIRST, sight_after="d-string",
                    sight_look="finger it silently and plan the bows", technique_stages=TECHNIQUE_STAGES,
                    technique_how=TECHNIQUE_HOW, final_plays=("play-separate", "play-slurred"), artic="separate/slurred",
                    minor_note="", strands=STRANDS, lists=LISTS, tone_title="Bowing & tone",
                    syllabus_hint="the coach's own, in midi_coach/atlas/data/fiddle_syllabus.json")
FIRST_SOUND_ID = FIDDLE.first_sound_id


SYLLABUS = "fiddle_syllabus.json"


def load_syllabus() -> dict:
    return pan.load_own_syllabus(SYLLABUS)


def main() -> None:
    pan.own_main(FIDDLE, SYLLABUS)


if __name__ == "__main__":
    main()
