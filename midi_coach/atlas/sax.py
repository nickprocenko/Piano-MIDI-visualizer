"""The Roadmap for the alto saxophone, for a beginner: Pan's engine (atlas.pan) with the sax's
notes, tone steps and theory.

Three tiers: First notes (the coach's own: a first sound on the mouthpiece, the left-hand
notes B A G, then C and D, the low notes, F sharp and B flat, the octave key; long tones,
tonguing, slurs; ABRSM has no woodwind Initial grade), then ABRSM Saxophone Grades 1 and 2.
Everything is in written pitch, as sax music is printed: the alto sounds a major sixth lower,
so the page adds 9 semitones to what the microphone hears (instruments.py) and every score
says it is for an E flat instrument. The pieces are Pan's public-domain tunes, which sit in
the alto's written range.

The ABRSM facts (Grade 1-2 scales, speeds, sight-reading parameters, aural tests) are read
from <home>/atlas/sax/syllabus.json, drafted locally from the woodwind syllabus and never put
in git.

    python -m midi_coach.atlas.sax [syllabus.json]   build <home>/atlas/sax
"""

from __future__ import annotations

from . import pan

THEORY_BY_ID = {t[0]: t for tier in pan.THEORY.values() for t in tier}

NOTE_STEPS = [
    {"key": "b-a-g", "title": "B, A and G", "new": [71, 69, 67], "tempo": 72,
     "text": "Left hand only: first finger for B, add the second for A and the third for G. The left thumb rests below the "
             "octave key without pressing it. Start each note with 'tah', the tongue leaving the reed.",
     "tiny": pan.NOTE_STEPS[0]["tiny"]},
    {"key": "c-d", "title": "C and D", "new": [72, 74], "tempo": 72,
     "text": "C is the left second finger alone. The middle D is all six fingers down with the thumb on the octave key. "
             "Move the fingers together and keep the air going through the change.",
     "tiny": pan.NOTE_STEPS[1]["tiny"]},
    {"key": "low-d-e-f", "title": "Low D, E and F", "new": [62, 64, 65], "tempo": 66,
     "text": "The right hand joins in: first finger for F, first and second for E, all three for D. Low notes need a "
             "relaxed jaw and a steady, warm air stream; don't bite, and let them speak.",
     "tiny": "g1 f1 e1 d1 e2 f2 g2 e2 d4 e f g f e d e d1"},
    {"key": "f-sharp-b-flat", "title": "F♯ and B♭", "new": [66, 70], "tempo": 72,
     "text": "F♯ is G with the right second finger down. B♭ is the bis key: the left first finger covers both its own key "
             "and the small one just below it. These two notes open up G major and F major.",
     "tiny": pan.NOTE_STEPS[3]["tiny"]},
    {"key": "upper-e-f-g", "title": "E, F, F♯ and G an octave up", "new": [76, 77, 78, 79], "tempo": 66,
     "text": "Add the octave key with the left thumb: the same fingers as low E, F, F♯ and G sound an octave higher. "
             "Keep the air steady and the mouth the same; squeaks come from biting.",
     "tiny": pan.NOTE_STEPS[4]["tiny"]},
]
TONE_STEPS = [
    {"key": "long-tones", "title": "Long tones", "tempo": 60, "after": "b-a-g",
     "text": "Hold each note for four slow beats with one even sound, start to finish. Breathe low before each one. "
             "This is how saxophonists build a full, steady tone.",
     "tiny": pan.TONE_STEPS[0]["tiny"]},
    {"key": "tonguing", "title": "Tonguing", "tempo": 72, "after": "b-a-g",
     "text": "Start every note with 'tah': the tip of the tongue touches the tip of the reed and lets go. Keep the air "
             "going between notes; the tongue only interrupts it.",
     "tiny": pan.TONE_STEPS[1]["tiny"]},
    {"key": "slurs", "title": "Two-note slurs", "tempo": 66, "after": "c-d",
     "text": "Tongue the first note of each pair only, then move the fingers while the air keeps flowing.",
     "tiny": pan.TONE_STEPS[2]["tiny"]},
]
G2_NOTES = {"key": "upper-notes", "title": "New notes: C♯, E♭ and the top A to C", "new": [73, 75, 81, 83, 84], "tempo": 60,
            "text": "Grade 2 climbs to the top C. Up there keep the octave key down, the air fast and the jaw relaxed; "
                    "C♯ is the middle note with every finger off.",
            "tiny": "d'1 c'#1 d'2 e'2 f'#2 g'2 a'1 b'1 c''1 b'2 a'2 g'1 e'-1 d'1"}

FIRST_SOUND = ("making-a-sound", "Making a sound",
               "Wet the reed and fix it on the mouthpiece with the ligature, its tip level with the mouthpiece's. Roll the bottom "
               "lip a little over the lower teeth, rest the top teeth on top of the mouthpiece and close the corners of the mouth "
               "around it. Blow a steady stream of warm air and start the note with 'tah'. A squeak usually means biting or too "
               "much mouthpiece in the mouth.",
               [("Where do the top teeth go?", ["On the reed", "Resting on top of the mouthpiece", "Away from the mouthpiece"], 1,
                 "The top teeth rest on the mouthpiece; the bottom lip cushions the reed."),
                ("The saxophone squeaks. What helps first?", ["Bite harder", "Relax the jaw and check how much mouthpiece is in",
                                                             "Blow much harder"], 1,
                 "Biting pinches the reed; a relaxed jaw and the right amount of mouthpiece give a clean sound.")])

THEORY = {
    "initial": [
        ("treble-stave", "Notes on the treble stave",
         "Saxophone music uses the treble clef. The lines from the bottom are E G B D F, the spaces F A C E. "
         "Your first notes: G sits on the second line, A in the space above it, B on the middle line.",
         THEORY_BY_ID["treble-stave"][3]),
        THEORY_BY_ID["note-values"],
        ("breathing", "Breathing and breath marks",
         "Breathe in low, filling from the belly, shoulders still, through the corners of the mouth without letting go of the "
         "mouthpiece. Breathe at the end of a phrase, where a comma-shaped breath mark is printed or where a long note ends, "
         "never in the middle of a group of quick notes.",
         THEORY_BY_ID["breathing"][3]),
    ],
    "g1": [
        THEORY_BY_ID["key-signatures-f-g"],
        ("d-minor", "D minor",
         "D minor shares F major's key signature (B♭) but starts and ends on D. It sounds darker. At Grade 1 you may play the "
         "natural, harmonic or melodic form; the Roadmap uses the natural form: D E F G A B♭ C D.",
         [("Which major key shares D minor's key signature?", ["F major", "G major", "C major"], 0,
           "Both have one flat, B♭: they're relative keys."),
          ("What note does a D minor scale start and end on?", ["F", "D", "A"], 1, "A scale starts and ends on its tonic: D.")]),
        ("written-pitch", "Written and sounding notes",
         "The alto saxophone is an E♭ instrument: its music is written a major sixth higher than it sounds, so your written C "
         "sounds the E♭ below it on a piano. Every alto saxophone reads the same way, so the fingerings match the page. "
         "The coach shows and hears your notes as written.",
         [("You finger a written C. Which note sounds?", ["C", "The E♭ below", "The A above"], 1,
           "An alto sounds a major sixth below the written note: C sounds E♭."),
          ("Why is sax music written this way?", ["So every saxophone shares fingerings", "To make it harder", "It isn't"], 0,
           "Written pitch keeps the same fingering for the same written note on every saxophone.")]),
        THEORY_BY_ID["time-3-4"],
        ("tonguing-slurs", "Tongued and slurred",
         "Tongued: each note starts with 'tah', the tongue on the reed. Slurred: a curved line joins the notes, and only the "
         "first is tongued; the fingers move while the air carries on. In the exam the examiner chooses which, so learn every "
         "scale both ways.",
         THEORY_BY_ID["tonguing-slurs"][3]),
        ("dynamics-f-mf", "f and mf",
         "f (forte) means loud, mf (mezzo forte) moderately loud. On the saxophone, loud means more air with the same relaxed "
         "mouth, not biting; keep the sound round and the pitch steady.",
         THEORY_BY_ID["dynamics-f-mf"][3]),
    ],
    "g2": [
        THEORY_BY_ID["c-major-a-minor"],
        THEORY_BY_ID["time-2-4"],
        THEORY_BY_ID["dotted-crotchet"],
        THEORY_BY_ID["ties"],
        ("staccato", "Staccato",
         "A dot above or below a note means staccato: short and detached. On the saxophone, stop each note lightly by "
         "touching the tongue back on the reed ('tat'), and keep the beat even.",
         THEORY_BY_ID["staccato"][3]),
        ("dynamics-mp-cresc", "mp and crescendo",
         "mp (mezzo piano) is moderately quiet. A crescendo, the opening hairpin <, means get gradually louder. Quiet notes on "
         "the saxophone still need supported air; ease the air, not the support, so the note doesn't drop out.",
         THEORY_BY_ID["dynamics-mp-cresc"][3]),
    ],
}

TECHNIQUE_HOW = dict(pan.TECHNIQUE_HOW, notes="Learn the notes and fingerings slowly, tongued.",
                     tongued="Every note tongued with 'tah', evenly.")

SAX = pan.Course(instrument="sax", folder="sax", part="Alto Saxophone", made="atlas.sax", lowest=58, highest=89,
                 note_steps=NOTE_STEPS, tone_steps=TONE_STEPS, g2_notes=G2_NOTES, first_sound=FIRST_SOUND, theory=THEORY,
                 tunes="pan_tunes.json", sight_first=pan.SIGHT_FIRST, sight_after="c-d", sight_look="finger it silently",
                 technique_how=TECHNIQUE_HOW, written_above=9,
                 syllabus_hint="drafted locally from the Saxophone pages of your copy of the ABRSM woodwind syllabus "
                               "(see 'The Roadmap' in midi_coach/README.md)")
FIRST_SOUND_ID = SAX.first_sound_id


def main(argv: list[str] | None = None) -> None:
    pan.main(argv, SAX)


if __name__ == "__main__":
    main()
