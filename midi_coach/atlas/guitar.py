"""The Roadmap for the electric guitar: Pan's engine (atlas.pan) with the coach's own guitar course.

Three tiers, all the coach's own (no exam board's syllabus): First notes (holding the guitar and
pick, then first position string by string from the top E down to the low E, F sharp; alternate
picking, string crossing, hammer-ons and pull-offs), then Grades 1 and 2 with scales and
arpeggios, sight-reading and public-domain melodies (data/guitar_tunes.json). The syllabus is
data/guitar_syllabus.json; the aural tests come from the flute's local syllabus when there is one.

The microphone hears one note at a time, so everything graded is single notes: melodies, scales,
arpeggios. Chords and strumming are taught in the Theory strand (read and quiz, not graded).

Guitar music is written an octave above how it sounds: the scores are in the treble clef with an
8 below (like a low voice's), stored at sounding pitch, so nothing is shifted. The course's
pitches (note steps, ranges, tunes) are written pitch. The page can add a tab staff (strings
and frets) under the notes.

    python -m midi_coach.atlas.guitar   build <home>/atlas/guitar
"""

from __future__ import annotations

from . import pan

THEORY_BY_ID = {t[0]: t for tier in pan.THEORY.values() for t in tier}
STRANDS = [
    {"id": "pieces", "title": "Melodies", "glyph": "♫"},
    {"id": "technique", "title": "Scales & picking", "glyph": "♯"},
    {"id": "sight", "title": "Sight-reading", "glyph": "◎"},
    {"id": "aural", "title": "Aural", "glyph": "∿"},
    {"id": "theory", "title": "Theory & chords", "glyph": "♭"},
]
LISTS = {"first": "First melodies", "A": "Lively melodies", "B": "Slow melodies", "C": "Folk melodies"}

NOTE_STEPS = [  # written pitch: the top E string open is written E5 (76) and sounds E4
    {"key": "e-string", "title": "E, F and G on the top E string", "new": [76, 77, 79], "tempo": 66,
     "text": "The thinnest string, open, is E. First finger on the first fret for F, third finger on the third fret for G. "
             "Press just behind the fret wire with the fingertip, and pick down towards the floor.",
     "tiny": "e'2 f'2 g'2 f'2 e'1 e'4 f' g' f' e' g' e'2 g'4 f' e' f' e'1"},
    {"key": "b-string", "title": "B, C and D on the B string", "new": [71, 72, 74], "tempo": 66,
     "text": "The next string: open for B, first finger on the first fret for C, third finger on the third fret for D. "
             "With the E string that is C major from C to G.",
     "tiny": "b2 c'2 d'2 c'2 b1 c'4 d' e' f' g'1 g'4 f' e' d' c'1"},
    {"key": "g-string", "title": "G and A on the G string", "new": [67, 69], "tempo": 66,
     "text": "The G string open is G; second finger on the second fret is A. Let the other fingers hover close to the strings.",
     "tiny": "g2 a2 b2 a2 g1 g4 a b c' d'1 d'4 c' b a g1"},
    {"key": "d-string", "title": "D, E and F on the D string", "new": [62, 64, 65], "tempo": 66,
     "text": "Open D, second finger on the second fret for E, third finger on the third fret for F.",
     "tiny": "d2 e2 f2 e2 d1 d4 e f g a1 a4 g f e d1"},
    {"key": "a-string", "title": "A, B and C on the A string", "new": [57, 59, 60], "tempo": 66,
     "text": "Open A, second finger on the second fret for B, third finger on the third fret for C: middle C on the page.",
     "tiny": "A2 B2 c2 B2 A1 c4 d e f g a b c' c'1"},
    {"key": "low-e-string", "title": "E, F and G on the low E string", "new": [52, 53, 55], "tempo": 66,
     "text": "The thickest string: open E, first finger on the first fret for F, third finger on the third fret for G. Now "
             "you have every natural note in first position, low E to high G.",
     "tiny": "E2 F2 G2 F2 E1 E4 F G A B c d e e1"},
    {"key": "f-sharp", "title": "F♯ on three strings", "new": [54, 66, 78], "tempo": 60,
     "text": "F♯ is one fret above F: second fret on the low E string, fourth fret on the D string (little finger), second "
             "fret on the top E string. F♯ opens G major and E minor.",
     "tiny": "E2 F#2 G1 e2 f#2 g1 e'2 f'#2 g'1 g4 a b c' d' e' f'# g' g'1"},
]
TONE_STEPS = [
    {"key": "alternate-picking", "title": "Alternate picking", "tempo": 66, "after": "e-string",
     "text": "Down, up, down, up: the pick moves the same small distance each way from the wrist, never stopping. Down on the "
             "beat, up between.",
     "tiny": "e'8 e' e' e' f' f' f' f' g' g' g' g' f' f' f' f' e'1"},
    {"key": "string-crossing", "title": "String crossing", "tempo": 66, "after": "b-string",
     "text": "Move the pick between two strings with a small move from the wrist, landing on the new string without touching "
             "the one beside it.",
     "tiny": "b4 e' c' e' d' e' c' e' b e' d' e' b1"},
    {"key": "hammer-pull", "title": "Hammer-ons and pull-offs", "tempo": 60, "after": "g-string",
     "text": "Pick the first note only. Hammer-on: bring the next finger down hard enough to sound the higher note. Pull-off: "
             "flick the finger sideways off the string to sound the lower one. Every note should be as clear as a picked one.",
     "tiny": "g2 a2 g2 a2 b2 c'2 b2 c'2 e'2 f'2 e'2 g'2 e'1"},
]
G2_NOTES = {"key": "c-sharp-b-flat", "title": "New notes: C♯ and B♭", "new": [58, 61, 70, 73], "tempo": 60,
            "text": "Grade 2's keys need C♯ and B♭. C♯ is one fret above C: fourth fret on the A string, second fret on the B "
                    "string. B♭ is one fret below B: first fret on the A string, third fret on the G string.",
            "tiny": "A2 B-2 c2 c#2 d1 a2 b-2 b2 c'#2 d'1"}

FIRST_SOUND = ("holding-guitar-and-pick", "Holding the guitar and pick",
               "Sit with the guitar's waist on your right leg (left leg for left-handers), the neck pointing up a little. Hold "
               "the pick between the thumb and the side of the first finger with just its tip showing. Rest the forearm on the "
               "body's edge and pick the open top E string with a small down stroke from the wrist. Plug in and keep the "
               "volume low; the coach listens through the microphone, so let the amp or the strings be heard.",
               [("How much of the pick should show?", ["Most of it", "Just the tip", "None"], 1,
                 "Just the tip: the pick stays steady and the stroke stays small."),
                ("Where do you press a string?", ["On top of the fret wire", "Just behind the fret wire", "Halfway between frets"], 1,
                 "Just behind the fret gives a clean note with the least pressure.")])

THEORY = {
    "initial": [
        ("treble-stave", "Guitar music on the stave",
         "Guitar music uses the treble clef with a small 8 below it: the guitar sounds an octave lower than written. The open "
         "top E string is written in the top space; middle C on a ledger line below the stave is the third fret on the A "
         "string. Tab, under the notes when you turn it on, shows each note as a fret number on a line for its string.",
         [("What does the 8 below the clef mean?", ["Play eight notes", "It sounds an octave lower than written", "Eight beats"], 1,
           "The guitar sounds an octave below the written notes."),
          ("In tab, what does a number on a line mean?", ["A finger", "The fret to press on that string", "How long to hold it"], 1,
           "Each line is a string, each number a fret; 0 is the open string.")]),
        THEORY_BY_ID["note-values"],
        ("first-chords", "First chords: E minor and A minor",
         "A chord is several notes strummed together. E minor: second finger on the A string and third on the D string, both "
         "at the second fret; strum all six strings. A minor: first finger B string first fret, second D string second fret, "
         "third G string second fret; strum from the A string. The coach hears one note at a time, so chords aren't graded: "
         "pick each string of the shape slowly and listen that every note rings.",
         [("How many strings do you strum for E minor?", ["Four", "Five", "All six"], 2, "E minor uses all six strings."),
          ("A note in a chord buzzes. What helps first?", ["Strum harder", "Press just behind the fret on the fingertip", "Tune up"], 1,
           "A fingertip just behind the fret, arched so it doesn't touch the next string.")]),
    ],
    "g1": [
        ("key-signatures-g", "G major and E minor",
         "G major has one sharp, F♯, shown at the start of every stave. E minor shares it but makes E its home; the Roadmap "
         "plays the natural form: E F♯ G A B C D E.",
         [("Which key has one sharp?", ["G major", "C major", "F major"], 0, "G major: F♯."),
          ("Which major key shares E minor's key signature?", ["G major", "C major", "D major"], 0, "Both have one sharp, F♯.")]),
        THEORY_BY_ID["time-3-4"],
        ("open-chords", "Open chords: C, G and D",
         "C: first finger B string first fret, second D string second fret, third A string third fret; strum from the A string. "
         "G: second finger low E third fret, first A string second fret, third top E third fret; all six. D: first G string "
         "second fret, third B string third fret, second top E second fret; strum from the D string.",
         [("Which string does a C chord's strum start on?", ["Low E", "A", "D"], 1, "C is strummed from the A string."),
          ("How many strings ring in a D chord?", ["Four", "Five", "Six"], 0, "D is strummed from the open D string: four strings.")]),
        ("strumming", "Strumming patterns",
         "Strum down on the beats and up between, keeping the hand moving like alternate picking even when it misses the "
         "strings. A first pattern in 4/4: down, down-up, up-down-up (D DU UDU). Count it aloud, then change chords on beat 1.",
         [("When does the strumming hand stop?", ["Between chords", "Never; it keeps the beat", "On every up stroke"], 1,
           "The hand keeps moving down and up; missing the strings is how the pattern's gaps are made."),
          ("Down strums usually fall…", ["On the beats", "Between the beats", "Anywhere"], 0, "Down on the beat, up between.")]),
        ("dynamics-f-mf", "f and mf",
         "f (forte) means loud, mf (mezzo forte) moderately loud. On the guitar, pick harder or with more of the pick for loud, "
         "lighter for quiet; leave the amp where it is so the change comes from your hands.",
         THEORY_BY_ID["dynamics-f-mf"][3]),
    ],
    "g2": [
        THEORY_BY_ID["c-major-a-minor"],
        ("d-f-d-minor", "D major, F major and D minor",
         "D major has two sharps, F♯ and C♯. F major has one flat, B♭. D minor shares F major's B♭ and makes D its home: "
         "D E F G A B♭ C D.",
         [("Which key has F♯ and C♯?", ["D major", "G major", "F major"], 0, "D major: two sharps."),
          ("Which major key shares D minor's key signature?", ["F major", "D major", "C major"], 0, "Both have one flat, B♭.")]),
        THEORY_BY_ID["time-2-4"],
        THEORY_BY_ID["dotted-crotchet"],
        ("power-chords", "Power chords",
         "A power chord is just two notes: a root and the fifth above it, often with the root doubled an octave up. First "
         "finger on the root on the low E or A string, third finger two frets up on the next string. Slide the same shape "
         "anywhere: written E5, A5, G5. Mute the other strings with the side of the fretting fingers.",
         [("Which notes make a power chord?", ["Root and third", "Root and fifth", "Root, third and fifth"], 1,
           "Root and fifth: no third, so it's neither major nor minor."),
          ("Moving a power chord shape up two frets…", ["Changes its shape", "Moves the chord up a whole step", "Makes it minor"], 1,
           "The shape stays; the chord moves up a whole step.")]),
        ("palm-muting", "Palm muting and staccato",
         "A dot above or below a note means staccato: short and detached. On the guitar, lift the fretting finger just off the "
         "string after the note, or rest the side of the picking hand on the strings by the bridge (P.M.) for a short, chunky "
         "sound.",
         THEORY_BY_ID["staccato"][3]),
    ],
}

TECHNIQUE_STAGES = [("notes", "Learn the notes", "learn", 70), ("alternate", "Alternate picking, steadily", "rehearse", 80),
                    ("speed", "At tempo, from memory", "rehearse", 100)]
TECHNIQUE_HOW = {"notes": "Learn the notes and frets slowly, one finger per fret.",
                 "alternate": "Alternate picking, down and up, evenly.",
                 "speed": "At tempo and from memory, alternate picking."}
SIGHT_FIRST = {"bars": 4, "times": ["4/4"], "keys": ["C"], "range": [71, 79], "rhythms": 0, "tempo": 60}
SYLLABUS = "guitar_syllabus.json"

GUITAR = pan.Course(instrument="guitar", folder="guitar", part="Guitar", made="atlas.guitar", lowest=52, highest=79,
                    note_steps=NOTE_STEPS, tone_steps=TONE_STEPS, g2_notes=G2_NOTES, first_sound=FIRST_SOUND, theory=THEORY,
                    tunes="guitar_tunes.json", sight_first=SIGHT_FIRST, sight_after="b-string",
                    sight_look="find the frets for each note", technique_stages=TECHNIQUE_STAGES, technique_how=TECHNIQUE_HOW,
                    final_plays=None, artic="alternate picking", minor_note="", strands=STRANDS, lists=LISTS,
                    tone_title="Picking & tone", clef="treble8vb", octave=-12,
                    syllabus_hint="the coach's own, in midi_coach/atlas/data/guitar_syllabus.json")
FIRST_SOUND_ID = GUITAR.first_sound_id


def load_syllabus() -> dict:
    return pan.load_own_syllabus(SYLLABUS)


def main() -> None:
    pan.own_main(GUITAR, SYLLABUS)


if __name__ == "__main__":
    main()
