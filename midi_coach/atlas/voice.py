"""The Roadmap for singers: Pan's engine (atlas.pan) with the coach's own vocal course.

Three tiers, all the coach's own (no exam board's syllabus): First notes (finding your voice,
then matching pitches a few at a time, do re mi up to the top E, long notes, legato, leaps,
first songs), then Grades 1 and 2 with scales and arpeggios on 'la' and in sol-fa, sight-singing
and public-domain songs (data/voice_songs.json). The syllabus is data/voice_syllabus.json; the
aural tests, the same as every instrument's, come from the flute's local syllabus when there is
one (they are ABRSM's, so never in git).

A high voice reads the treble clef; a low voice sings the same course an octave down from scores
in the treble clef with an 8 below (VOICE_LOW, its own folder). The voice is heard through the
microphone, like the flute.

    python -m midi_coach.atlas.voice [high|low]   build <home>/atlas/voice-high and voice-low
"""

from __future__ import annotations

import dataclasses
import json
import sys

from . import PACKAGE, pan, shared_dir

THEORY_BY_ID = {t[0]: t for tier in pan.THEORY.values() for t in tier}
STRANDS = [
    {"id": "pieces", "title": "Songs", "glyph": "♫"},
    {"id": "technique", "title": "Voice & scales", "glyph": "♯"},
    {"id": "sight", "title": "Sight-singing", "glyph": "◎"},
    {"id": "aural", "title": "Aural", "glyph": "∿"},
    {"id": "theory", "title": "Theory", "glyph": "♭"},
]
LISTS = {"first": "First songs", "A": "Lively songs", "B": "Lyrical songs", "C": "Folk songs"}

NOTE_STEPS = [
    {"key": "do-re-mi", "title": "Do, re, mi (C, D, E)", "new": [60, 62, 64], "tempo": 72,
     "text": "Sing on 'la'. Listen to each note first, then match it: the coach shows whether you're on the note. "
             "Start quietly and slide gently until it settles.",
     "tiny": "c1 d1 e1 d2 c2 e4 d c2 c4 d e2 e4 d c2 c1"},
    {"key": "fa-so", "title": "Fa and so (F, G)", "new": [65, 67], "tempo": 72,
     "text": "Two more steps up. Keep the jaw loose and the breath low; higher notes need more air, not more squeeze.",
     "tiny": "c4 d e f g1 g4 f e d c1 e4 f g2 g4 f e2 c4 e g2 f4 d c2"},
    {"key": "la-ti-do", "title": "La, ti, do (A, B, C)", "new": [69, 71, 72], "tempo": 66,
     "text": "The top of the scale: la, ti and the high do. Ti wants to rise to do; let it.",
     "tiny": "g1 a1 b1 c'1 c'4 b a g a b c'2 c'4 a f d c1"},
    {"key": "low-a-b", "title": "Low A and B", "new": [57, 59], "tempo": 66,
     "text": "Below do: ti and la underneath. Don't push the low notes down; let them be lighter and speak easily.",
     "tiny": "c1 B1 A1 B2 c2 d4 c B A B2 c2 A4 B c d c1"},
    {"key": "upper-d-e", "title": "High D and E", "new": [74, 76], "tempo": 66,
     "text": "Above the high do. Think of the note as forward and easy, an open 'ah' rather than a shout; breathe before the climb.",
     "tiny": "c'1 d'1 e'1 d'2 c'2 g4 a b c' d' e' d' c' b g a b c'1"},
    {"key": "f-sharp-b-flat-c-sharp", "title": "F♯, B♭ and C♯", "new": [66, 70, 73], "tempo": 66,
     "text": "Notes between the notes: F♯ sits just under G, B♭ just under B, C♯ just under D. They open the keys of D "
             "major and F major. Listen for how close each one is to its neighbour.",
     "tiny": "g1 f#1 g2 f#2 e2 d2 f1 b-1 a2 b-2 c'2 b-2 a1 d'1 c'#1 d'2 a2 f#2 d2"},
]
TONE_STEPS = [
    {"key": "long-tones", "title": "Long notes", "tempo": 60, "after": "do-re-mi",
     "text": "Sing each note on 'ah' for four slow beats with one even sound, start to finish. Breathe low before each one.",
     "tiny": "c1 c1 d1 d1 e1 e1"},
    {"key": "legato", "title": "Smooth steps (legato)", "tempo": 66, "after": "fa-so",
     "text": "Join the notes with no gaps: keep the air flowing and change only the pitch, landing right on each note.",
     "tiny": "c2 d2 e2 f2 g1 g2 f2 e2 d2 c1"},
    {"key": "leaps", "title": "Leaps of a third and a fifth", "tempo": 66, "after": "la-ti-do",
     "text": "Hear the top note in your head before you leap, then sing it without sliding up to it.",
     "tiny": "c2 e2 g2 e2 c1 d2 f2 a2 f2 d1 c2 g2 e2 c2 c1"},
]
G2_NOTES = {"key": "new-notes", "title": "New notes: low B♭, E♭, A♭ and the top F", "new": [58, 63, 68, 75, 77], "tempo": 60,
            "text": "Grade 2's flat keys need E♭ and A♭, and its range reaches from low B♭ to the top F. Find each one slowly "
                    "against its neighbours.",
            "tiny": "B-1 e-1 a-1 e'-1 f'1 e'-2 c'2 a-2 f2 e-1"}

FIRST_SOUND = ("finding-your-voice", "Finding your voice",
               "Stand tall with your feet apart, knees soft, shoulders down and relaxed. Breathe in low, so the belly and ribs "
               "widen, and sigh out on 'ah' from a high note to a low one. Then sing one comfortable note on 'la' and hold it "
               "steadily. Singing should feel easy: if it pinches or hurts, stop, rest and come back lighter.",
               [("Where should a singing breath go?", ["High in the chest, shoulders up", "Low, so the belly and ribs widen",
                                                       "Into the cheeks"], 1,
                 "A low breath gives steady air; lifting the shoulders tightens the throat."),
                ("A high note feels tight. What helps first?", ["Sing it louder", "Relax the jaw and keep the air flowing",
                                                               "Lift the chin"], 1,
                 "A loose jaw and steady air free the voice; pushing and reaching up tighten it.")])

THEORY = {
    "initial": [
        ("treble-stave", "Notes on the treble stave",
         "Songs are written in the treble clef. A low voice reads the same clef with a small 8 below it, which means it "
         "sings everything an octave lower. Middle C (do) sits on a short ledger line below the stave, D just under the "
         "bottom line, E on the bottom line.",
         [("Where is middle C written?", ["On a ledger line below the stave", "On the middle line", "In the top space"], 0,
           "Middle C has its own short line just below the stave."),
          ("Which note sits on the bottom line?", ["E", "C", "G"], 0, "The lines from the bottom are E G B D F.")]),
        THEORY_BY_ID["note-values"],
        ("breathing", "Breathing and phrases",
         "Breathe in low and quietly, shoulders still. Plan your breaths at the ends of phrases, where the words pause or "
         "a long note ends, and take them in time, without stopping the beat.",
         THEORY_BY_ID["breathing"][3]),
    ],
    "g1": [
        ("sol-fa", "Sol-fa: do, re, mi",
         "Sol-fa names the notes of a scale by their place in it: do re mi fa so la ti do. Do is the home note (the tonic) "
         "in any key, so a tune in sol-fa sounds the same in every key. It helps you hear where a note is before you sing it.",
         [("In sol-fa, what is the home note called?", ["la", "do", "so"], 1, "Do is the tonic, the home note."),
          ("What comes after mi?", ["fa", "re", "so"], 0, "do re mi fa so la ti do.")]),
        ("key-signatures-d-f", "Key signatures: D and F major",
         "D major has two sharps, F♯ and C♯, shown at the start of every stave. F major has one flat, B♭. The key signature "
         "applies to every one of those notes in the song.",
         [("Which key has F♯ and C♯?", ["F major", "D major", "C major"], 1, "D major: two sharps, F♯ and C♯."),
          ("Which key has one flat, B♭?", ["F major", "D major", "C major"], 0, "F major: B♭.")]),
        ("a-minor", "A minor",
         "A minor uses the same notes as C major but makes A its home: la is the home note. It sounds darker. "
         "The Roadmap sings its natural form: A B C D E F G A.",
         [("Which major key shares A minor's notes?", ["C major", "G major", "F major"], 0, "No sharps or flats in either."),
          ("In sol-fa, A minor's home note is…", ["do", "la", "mi"], 1, "Minor keys sit on la.")]),
        THEORY_BY_ID["time-3-4"],
        ("dynamics-f-mf", "f and mf",
         "f (forte) means loud, mf (mezzo forte) moderately loud. A singer gets louder with more air and an open mouth, not "
         "by pushing from the throat; keep the note steady and in tune.",
         THEORY_BY_ID["dynamics-f-mf"][3]),
    ],
    "g2": [
        ("flat-keys", "B♭ and E♭ major",
         "B♭ major has two flats, B♭ and E♭; E♭ major has three, B♭, E♭ and A♭. Their do is B♭ and E♭, so sing the sol-fa "
         "from there.",
         [("How many flats does E♭ major have?", ["One", "Two", "Three"], 2, "B♭, E♭ and A♭."),
          ("In B♭ major, which note is do?", ["B♭", "F", "E♭"], 0, "Do is the key's tonic.")]),
        THEORY_BY_ID["time-2-4"],
        THEORY_BY_ID["dotted-crotchet"],
        ("ties", "Tied notes",
         "A tie is a curve joining two notes of the same pitch: sing one note lasting both values, without starting the "
         "second again. A slur joins different notes; a tie joins the same note.",
         THEORY_BY_ID["ties"][3]),
        ("legato-staccato", "Legato and staccato",
         "Legato means smooth and joined; a slur over the notes asks for it. A dot above or below a note means staccato: "
         "short and detached, a light bounce of breath on each note, still in time.",
         [("What does a dot above a note mean?", ["Hold it longer", "Short and detached", "Louder"], 1, "Staccato: short and detached."),
          ("Legato means…", ["Smooth and joined", "Short", "Loud"], 0, "Legato: no gaps between the notes.")]),
        ("dynamics-mp-cresc", "mp and crescendo",
         "mp (mezzo piano) is moderately quiet. A crescendo, the opening hairpin <, means get gradually louder. Quiet singing "
         "still needs steady air, or the note goes flat and breathy.",
         THEORY_BY_ID["dynamics-mp-cresc"][3]),
    ],
}

TECHNIQUE_STAGES = [("notes", "Learn the notes on 'la'", "learn", 70), ("solfa", "In sol-fa, steadily", "rehearse", 70),
                    ("legato", "Legato, steadily", "rehearse", 80), ("speed", "At tempo, from memory", "rehearse", 100)]
TECHNIQUE_HOW = {"notes": "Sing each note on 'la', slowly: listen first, then match.",
                 "solfa": "Sing the sol-fa names (do re mi…) so you hear where each note sits in the key.",
                 "legato": "Join the notes smoothly on steady air; breathe at the top if you need to.",
                 "speed": "At tempo and from memory, on 'la' or in sol-fa."}
SIGHT_FIRST = {"bars": 4, "times": ["4/4"], "keys": ["C"], "range": [60, 67], "rhythms": 0, "tempo": 60}

VOICE_HIGH = pan.Course(instrument="voice", folder="voice-high", part="Voice", made="atlas.voice", lowest=57, highest=79,
                        note_steps=NOTE_STEPS, tone_steps=TONE_STEPS, g2_notes=G2_NOTES, first_sound=FIRST_SOUND, theory=THEORY,
                        tunes="voice_songs.json", sight_first=SIGHT_FIRST, sight_after="fa-so",
                        sight_look="hear the first note and sing it through in your head",
                        technique_stages=TECHNIQUE_STAGES, technique_how=TECHNIQUE_HOW, final_plays=None, artic="legato",
                        minor_note="", strands=STRANDS, lists=LISTS, tone_title="Voice & breath",
                        learn_pass={"metric": "notes", "min": 80},  # a voice wavers onto a note more than a key presses it
                        syllabus_hint="the coach's own, in midi_coach/atlas/data/voice_syllabus.json")
VOICE_LOW = dataclasses.replace(VOICE_HIGH, folder="voice-low", clef="treble8vb", octave=-12)
COURSES = {"high": VOICE_HIGH, "low": VOICE_LOW}
FIRST_SOUND_ID = VOICE_HIGH.first_sound_id


def load_syllabus(path=None) -> dict:
    """The coach's vocal syllabus, with the aural tests from the flute's local syllabus when
    there is one (every instrument's aural tests are the same)."""
    p = path or PACKAGE / "data" / "voice_syllabus.json"
    syllabus = json.loads(open(p, encoding="utf-8").read())
    flute = shared_dir() / pan.FOLDER / "syllabus.json"
    if flute.is_file():
        aural = json.loads(flute.read_text(encoding="utf-8"))
        by_id = {g["id"]: g.get("aural", []) for g in aural.get("grades", [])}
        for g in syllabus["grades"]:
            g.setdefault("aural", by_id.get(g["id"], []))
        syllabus.setdefault("first_notes_aural", aural.get("first_notes_aural", []))
    return syllabus


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    syllabus = load_syllabus()
    for voice in args or list(COURSES):
        course = COURSES[voice]
        report = pan.write(syllabus, course=course)
        print(f"{pan.content_dir(course)}: {report['nodes']} nodes, {report['lessons']} lessons, {report['scores']} scores")
        for problem in report["problems"]:
            print("  problem:", problem)


if __name__ == "__main__":
    main()
