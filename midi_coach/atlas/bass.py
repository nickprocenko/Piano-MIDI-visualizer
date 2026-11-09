"""The Roadmap for the bass guitar: Pan's engine (atlas.pan) with the coach's own bass course.

Three tiers, all the coach's own (no exam board's syllabus): First notes (holding the bass and
plucking, the open strings, then first position string by string, F sharp and C sharp; alternating
fingers, muting, root and fifth), then Grades 1 and 2 with scales and arpeggios, sight-reading
and public-domain melodies set low (data/bass_tunes.json). The syllabus is data/bass_syllabus.json;
the aural tests come from the flute's local syllabus when there is one.

Bass music is written an octave above how it sounds: the scores are in the bass clef with an 8
below, stored at sounding pitch, so nothing is shifted. The course's pitches are written pitch
(the open E string is written E2, 40). The page can add a tab staff under the notes.

    python -m midi_coach.atlas.bass   build <home>/atlas/bass
"""

from __future__ import annotations

from . import pan

THEORY_BY_ID = {t[0]: t for tier in pan.THEORY.values() for t in tier}
STRANDS = [
    {"id": "pieces", "title": "Melodies & lines", "glyph": "♫"},
    {"id": "technique", "title": "Scales & groove", "glyph": "♯"},
    {"id": "sight", "title": "Sight-reading", "glyph": "◎"},
    {"id": "aural", "title": "Aural", "glyph": "∿"},
    {"id": "theory", "title": "Theory", "glyph": "♭"},
]
LISTS = {"first": "First melodies", "A": "Lively melodies", "B": "Slow melodies", "C": "Folk melodies"}

NOTE_STEPS = [  # written pitch in the bass clef: open E is written E2 (40) and sounds E1
    {"key": "open-strings", "title": "The open strings: E, A, D and G", "new": [40, 45, 50, 55], "tempo": 60,
     "text": "No fretting yet: pluck each open string with the first and second fingers in turn, resting the thumb on the "
             "pickup or the low E string. The thickest string is E, then A, D and G.",
     "tiny": "EE1 AA1 D1 G1 G2 D2 AA2 EE2 AA2 D2 G1"},
    {"key": "a-string", "title": "B and C on the A string", "new": [47, 48], "tempo": 66,
     "text": "Second finger on the second fret for B, fourth finger on the third fret for C; on a bass the fourth finger "
             "takes the third fret so the hand stays open and relaxed. Press just behind the fret with the fingertip.",
     "tiny": "AA2 BB2 C2 BB2 AA1 AA4 BB C D C BB AA2"},
    {"key": "d-string", "title": "E and F on the D string", "new": [52, 53], "tempo": 66,
     "text": "Second finger on the second fret for E, third or fourth on the third fret for F. Keep the thumb behind the "
             "neck, opposite the second finger.",
     "tiny": "D2 E2 F2 E2 D1 C4 D E F E D C D C1"},
    {"key": "g-string", "title": "A and B on the G string", "new": [57, 59], "tempo": 66,
     "text": "Second fret for A, fourth for B. These are the highest notes in first position; let them sound as long as "
             "the low ones.",
     "tiny": "G2 A2 B2 A2 G1 D4 E F G A B A G G1"},
    {"key": "e-string", "title": "F and G on the low E string", "new": [41, 43], "tempo": 66,
     "text": "First fret for F, third for G. The low E string needs a firmer pluck and a relaxed fretting hand; now you have "
             "every natural note from low E to high B.",
     "tiny": "EE2 FF2 GG2 FF2 EE1 EE4 FF GG AA BB C D E E1"},
    {"key": "f-sharp-c-sharp", "title": "F♯ and C♯", "new": [42, 49, 54], "tempo": 60,
     "text": "F♯ is one fret above F: second fret on the E string, fourth fret on the D string. C♯ is the fourth fret on the "
             "A string. They open G major, E minor and the keys bass lines love.",
     "tiny": "EE2 FF#2 GG1 AA2 BB2 C#2 D2 D2 E2 F#2 G2 G1"},
]
TONE_STEPS = [
    {"key": "alternate-fingers", "title": "Alternating fingers", "tempo": 66, "after": "open-strings",
     "text": "Pluck with the first and second fingers in turn, each stroke coming to rest on the next string. Keep every "
             "note the same volume and length.",
     "tiny": "AA4 AA AA AA D D D D G G G G AA1"},
    {"key": "muting", "title": "Stopping the notes", "tempo": 66, "after": "a-string",
     "text": "A bass note rings until you stop it. On the rests, touch the string with a plucking finger, or lift the "
             "fretting finger just off it, so the silence is as clear as the note.",
     "tiny": "AA4 r AA r D r D r AA2 C2 AA1"},
    {"key": "root-fifth", "title": "Root and fifth", "tempo": 66, "after": "d-string",
     "text": "The bass holds the band together by playing a chord's root, then its fifth. Feel the beat in your body and "
             "land every note exactly on it.",
     "tiny": "AA2 E2 AA2 E2 D2 AA2 D2 AA2 C2 G2 C2 G2 AA1"},
]
G2_NOTES = {"key": "flats-and-c", "title": "New notes: B♭, E♭ and the top C", "new": [46, 51, 58, 60], "tempo": 60,
            "text": "Grade 2's flat keys need B♭ (first fret on the A string, third on the G string) and E♭ (first fret on the "
                    "D string). The top C, fifth fret on the G string, is a small stretch or shift up with the fourth finger.",
            "tiny": "AA2 BB-2 C2 D2 E-2 D2 C1 G2 A2 B-2 c2 B-1 G1"}

FIRST_SOUND = ("holding-bass-and-plucking", "Holding the bass and plucking",
               "Sit or stand with a strap so the bass sits the same either way, the neck angled up a little. Rest the right "
               "thumb on the pickup, and pluck the open E string with the first finger, pulling across the string towards "
               "the next one so the finger comes to rest on it. Keep the amp low; the coach listens through the microphone, "
               "and a bass's low notes need the amp, not the bare strings, to be heard well.",
               [("Where does the plucking finger stop?", ["In the air", "Resting on the next string", "On the pickguard"], 1,
                 "A rest stroke: the finger comes to rest on the next string, steady and full."),
                ("A note buzzes. What helps first?", ["Pluck softer", "Press just behind the fret", "Tune lower"], 1,
                 "Just behind the fret, on the fingertip, gives a clean note.")])

THEORY = {
    "initial": [
        ("bass-stave", "Bass music on the stave",
         "Bass music uses the bass clef with a small 8 below it: the bass sounds an octave lower than written. The lines from "
         "the bottom are G B D F A. The open strings: E on the ledger line below the stave, A in the bottom space, D on the "
         "middle line, G in the top space. Tab, under the notes when you turn it on, shows each note as a fret number on a "
         "line for its string.",
         [("Where is the open A string written?", ["The bottom space", "The middle line", "The top space"], 0,
           "A is the bottom space of the bass clef."),
          ("In tab, what does 0 on the bottom line mean?", ["Rest", "The open low E string", "The first fret"], 1,
           "The bottom line is the low E string; 0 is open.")]),
        THEORY_BY_ID["note-values"],
        ("the-pulse", "Locking in with the beat",
         "A bass player is half of the rhythm section: with the drums you are the beat. Count every bar aloud, tap a foot on "
         "the beat, and place each note exactly on it, holding long notes for their full value.",
         [("What does a bass player lock in with first?", ["The singer", "The drums", "The guitar solo"], 1,
           "The bass and drums make the groove together."),
          ("How long should a minim last?", ["As long as you like", "Two full beats", "One beat"], 1,
           "Hold notes for their full value; a bass's length is part of the groove.")]),
    ],
    "g1": [
        ("key-signatures-g", "G major and E minor",
         "G major has one sharp, F♯. E minor shares it but makes E its home; the Roadmap plays the natural form: "
         "E F♯ G A B C D E.",
         [("Which key has one sharp?", ["G major", "C major", "F major"], 0, "G major: F♯."),
          ("Which major key shares E minor's key signature?", ["G major", "C major", "D major"], 0, "Both have one sharp, F♯.")]),
        THEORY_BY_ID["time-3-4"],
        ("roots", "Roots and chord symbols",
         "A chord symbol above the music (G, Em, C, D) names a chord; its letter is the root. The simplest bass line plays the "
         "root of each chord on its first beat. Next add the fifth, five notes up the scale: G to D, C to G, E to B.",
         [("What is the root of an Em chord?", ["E", "G", "B"], 0, "The letter names the root: E."),
          ("What is the fifth above G?", ["B", "C", "D"], 2, "G A B C D: five notes up is D.")]),
        ("dynamics-f-mf", "f and mf",
         "f (forte) means loud, mf (mezzo forte) moderately loud. On the bass, pluck harder or nearer the bridge for loud, "
         "lighter for quiet; leave the amp alone so the change comes from your hands.",
         THEORY_BY_ID["dynamics-f-mf"][3]),
    ],
    "g2": [
        THEORY_BY_ID["c-major-a-minor"],
        ("f-major-g-minor", "F major and G minor",
         "F major has one flat, B♭. G minor has two, B♭ and E♭, the same as B♭ major, and makes G its home: G A B♭ C D E♭ F G.",
         [("How many flats does G minor have?", ["One", "Two", "Three"], 1, "B♭ and E♭."),
          ("Which key has one flat?", ["F major", "G minor", "C major"], 0, "F major: B♭.")]),
        THEORY_BY_ID["time-2-4"],
        THEORY_BY_ID["dotted-crotchet"],
        ("staccato", "Staccato and muting",
         "A dot above or below a note means staccato: short and detached. On the bass, stop each note by lifting the fretting "
         "finger just off the string or touching it with a plucking finger, right on time.",
         THEORY_BY_ID["staccato"][3]),
    ],
}

TECHNIQUE_STAGES = [("notes", "Learn the notes", "learn", 70), ("steady", "Alternating fingers, steadily", "rehearse", 80),
                    ("speed", "At tempo, from memory", "rehearse", 100)]
TECHNIQUE_HOW = {"notes": "Learn the notes and frets slowly, one finger per fret.",
                 "steady": "Alternate the plucking fingers, every note even and full length.",
                 "speed": "At tempo and from memory, locked to the beat."}
SIGHT_FIRST = {"bars": 4, "times": ["4/4"], "keys": ["C"], "range": [45, 50], "rhythms": 0, "tempo": 60}
SYLLABUS = "bass_syllabus.json"

BASS = pan.Course(instrument="bass", folder="bass", part="Bass Guitar", made="atlas.bass", lowest=40, highest=60,
                  note_steps=NOTE_STEPS, tone_steps=TONE_STEPS, g2_notes=G2_NOTES, first_sound=FIRST_SOUND, theory=THEORY,
                  tunes="bass_tunes.json", sight_first=SIGHT_FIRST, sight_after="a-string",
                  sight_look="find the frets for each note", technique_stages=TECHNIQUE_STAGES, technique_how=TECHNIQUE_HOW,
                  final_plays=None, artic="alternating fingers", minor_note="", strands=STRANDS, lists=LISTS,
                  tone_title="Plucking & groove", clef="bass8vb", octave=-12,
                  syllabus_hint="the coach's own, in midi_coach/atlas/data/bass_syllabus.json")
FIRST_SOUND_ID = BASS.first_sound_id


def load_syllabus() -> dict:
    return pan.load_own_syllabus(SYLLABUS)


def main() -> None:
    pan.own_main(BASS, SYLLABUS)


if __name__ == "__main__":
    main()
