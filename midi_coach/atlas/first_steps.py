"""First steps and Ready to read: the Atlas's own two tiers before Initial, for complete
beginners from about age 4. Nothing is assumed: not where the black keys are, not what a
finger number is, not that a note on a higher line sounds higher.

First steps (no reading yet): the keyboard (high and low, the black-key groups, every
letter), finger numbers, the C five-finger position in each hand, steps, skips and hands
taking turns; rhythm read on one key; listening games; music words; and tunes learnt by ear,
each score with finger numbers above and letter names under the notes.
Ready to read: the stave note by note in each clef, reading pools that add one note at a
time, the G and middle C positions, D minor's five notes, broken chords, thumb under and
finger over, more ear games and the counting words Initial uses.

Each requirement is one small idea (a Khan-style map of many little skills), linked to the
ones it needs, and the Initial tier's starting points are linked to the end of Ready to read,
so a beginner's Path to Initial starts at the very first step and a Path through a
requirement you already know doesn't drag you back here. These tiers are the coach's own
(no exam board's material: the tunes are public domain, data/first_tunes.json), so they live
in git; build.build adds them to every piano Atlas, and this module writes their lessons:

    python -m midi_coach.atlas.first_steps     rebuild atlas.json, then write these tiers' lessons
"""

from __future__ import annotations

import json
import pathlib
import random
import re
import sys
from fractions import Fraction as F

from . import PACKAGE, STRANDS, content_dir, templates

FIRST, READY = "first", "ready"
OURS = (FIRST, READY)
TITLES = {FIRST: "First steps", READY: "Ready to read"}
MADE = "atlas.first_steps (the coach's own, for young beginners)"
LEARN_PASS = {"metric": "notes", "min": 80}
PLAY_PASS = {"metric": "overall", "min": 60}
LEARN_SAYS = " The music waits for you to find each key."
PLAY_SAYS = " Now the music keeps a steady beat: keep going, even after a slip."

# Fingers by hand position: {position: {midi pitch: finger}}.
RH = {"C": {60: 1, 62: 2, 64: 3, 65: 4, 67: 5, 69: 5}, "G": {67: 1, 69: 2, 71: 3, 72: 4, 74: 5},
      "Dm": {62: 1, 64: 2, 65: 3, 67: 4, 69: 5}, "black": {66: 2, 68: 3, 70: 4, 73: 5}}
LH = {"C": {48: 5, 50: 4, 52: 3, 53: 2, 55: 1}, "G": {43: 5, 45: 4, 47: 3, 48: 2, 50: 1},
      "Dm": {50: 5, 52: 4, 53: 3, 55: 2, 57: 1}, "midC": {60: 1, 59: 2, 57: 3, 55: 4, 53: 5}}
LETTER = "CDEFGAB"


# -- what each tier holds ------------------------------------------------------------------------
# Play items: {key, title, text, right?, left?, rf?/lf? (fingers: a position name or digits),
# stages: one | hands | ht, after: keys of other items, tempo, tip?, marks?}. Keys are unique
# across both tiers, so 'after' names an item anywhere in them.

def ex(key, title, text, right=None, left=None, rf=None, lf=None, after=(), stages="one", tempo=72, tip=None, marks=None):
    return {"key": key, "title": title, "text": text, "right": right, "left": left, "rf": rf, "lf": lf,
            "after": list(after), "stages": stages, "tempo": tempo, "tip": tip, "marks": marks or {}}


def _letter_items() -> list[dict]:
    """Find every C, D, ... B: right hand on the two above middle C's octave, left hand below."""
    where = {"C": "just left of the two black keys", "D": "in the middle of the two black keys",
             "E": "just right of the two black keys", "F": "just left of the three black keys",
             "G": "between the first two of the three black keys", "A": "between the last two of the three black keys",
             "B": "just right of the three black keys"}
    out = []
    for k, name in enumerate(LETTER):
        x = name.lower()
        after = [f"find-{LETTER[k - 1].lower()}"] if k else ["twos-and-threes", "where-c-lives"]
        if name == "F":
            after.append("black-threes-lh")
        if name in "DE":
            after.append("finding-d-e")
        if name in "FGAB":
            after.append("finding-f-g-a-b")
        out.append(ex(f"find-{x}", f"Find every {name}", f"{name} lives {where[name]}. Find two {name}s with your right hand, one higher than the other, "
                      f"then two more {name}s down low with your left. Use finger 3 and let it hop.",
                      right=f"{x}2 {x}'2 r1", left=f"r1 {name}2 {name}{name}2", rf="3 3", lf="3 3", after=after, stages="hands",
                      tip=f"point to the black-key group first, then let them find the {name} beside it."))
    return out


TECHNIQUE = {
    FIRST: [
        ("keyboard", "Meet the keyboard", [
            ex("up-high-down-low", "Up high, down low",
               "Your right hand plays way up high, like a little bird. Your left hand plays way down low, like a big bear. "
               "Any finger will do: one key at a time.",
               right="c''2 c''2 r1 c''1 r1", left="r1 CC2 CC2 r1 CC1", after=["high-and-low"], stages="hands", tempo=66,
               tip="the highest and lowest Cs are fine; it's the direction that matters. Point to the keys on the sheet's picture."),
            ex("black-twos-rh", "Two black keys (right hand)",
               "The black keys come in groups. Find a group of two, and play them with fingers 2 and 3. Then find the next group of two, higher up.",
               right="c#2 d#2 c'#2 d'#2 c#4 d# c'# d'# c#1", rf="2 3 2 3 2 3 2 3 2", after=["up-high-down-low", "black-key-groups"]),
            ex("black-twos-lh", "Two black keys (left hand)",
               "Now your left hand: fingers 3 and 2 on a group of two black keys, then the next group down.",
               left="C#2 D#2 CC#2 DD#2 C#4 D# CC# DD# C#1", lf="3 2 3 2 3 2 3 2 3", after=["black-twos-rh"]),
            ex("black-threes-rh", "Three black keys (right hand)",
               "Find a group of three black keys. Fingers 2, 3 and 4 play them, one after another. Then the next group up.",
               right="f#4 g# a#2 f'#4 g'# a'#2 f#4 g# a# g# f#1", rf="2 3 4 2 3 4 2 3 4 3 2", after=["black-twos-lh"]),
            ex("black-threes-lh", "Three black keys (left hand)",
               "Left hand on a group of three black keys: fingers 4, 3 and 2. Then the next group down.",
               left="F#4 G# A#2 FF#4 GG# AA#2 F#4 G# A# G# F#1", lf="4 3 2 4 3 2 4 3 2 3 4", after=["black-threes-rh"]),
            ex("twos-and-threes", "Twos and threes",
               "Hop between a group of two black keys and a group of three, right hand, going up the piano.",
               right="c#4 d# r2 f#4 g# a# r4 c'#4 d'# r2 f'#4 g'# a'# r4", rf="2 3 2 3 4 2 3 2 3 4", after=["black-threes-lh"]),
            *_letter_items(),
            ex("middle-c", "Middle C",
               "Middle C is the C nearest the middle of the piano, right in front of you. Both thumbs can share it: "
               "right thumb first, then left thumb.",
               right="c2 c2 r1 c1 r1", left="r1 c2 c2 r1 c1", rf="1 1 1", lf="1 1 1", after=["find-c", "middle-c-word"], stages="hands"),
            ex("alphabet-up", "The music alphabet, going up",
               "Walk up the white keys from A, saying each letter: A B C D E F G, and A again. Finger 3 walks the whole way.",
               right="a4 b c' d' e' f' g'2 a'1", rf="3 3 3 3 3 3 3 3", after=["find-b", "music-alphabet"]),
            ex("alphabet-down", "The music alphabet, going down",
               "Walk down from G, saying the letters backwards: G F E D C B A G.",
               right="g'4 f' e' d' c' b a2 g1", rf="3 3 3 3 3 3 3 3", after=["alphabet-up"]),
        ]),
        ("fingers", "Finger games", [
            ex("fingers-rh", "Right-hand finger numbers",
               "Right hand: thumb is 1, then 2, 3, 4, and your pinky is 5. Play C D E F G, one finger each, and say the numbers.",
               right="c2 d e f g1", rf="C", after=["finger-numbers", "alphabet-down"]),
            ex("fingers-lh", "Left-hand finger numbers",
               "Left hand: your pinky is 5 and your thumb is 1, just like the right. Play C D E F G with 5 4 3 2 1.",
               left="C2 D E F G1", lf="C", after=["fingers-rh"]),
            ex("thumbs-and-pinkies", "Thumbs and pinkies",
               "Thumb on C, pinky on G, and keep the fingers in between floating over their keys. Right hand, then left.",
               right="c2 g2 c2 g2 r1 r1", left="r1 r1 C2 G2 C2 G2", rf="C", lf="C", after=["fingers-lh"], stages="hands"),
            ex("three-fingers", "1 2 3, 3 2 1",
               "Fingers 1, 2 and 3 on C, D and E. Right hand plays up and down, then the left hand plays its C D E.",
               right="c4 d e2 e4 d c2 r1 r1", left="r1 r1 E4 D C2 C4 D E2", rf="C", lf="C", after=["thumbs-and-pinkies"], stages="hands"),
            ex("same-key-again", "The same key again",
               "Play each key twice, like a little echo: C C, D D, E E.",
               right="c4 c d d e e d d c1", rf="C", after=["three-fingers"]),
        ]),
        ("positions", "Five-finger hands", [
            ex("rh-c-position", "Right hand on C",
               "Put your right hand on C: one finger on each key from C to G. Walk up and back down without looking at your hand.",
               right="c4 d e f g1 g4 f e d c1", rf="C", after=["same-key-again"], tempo=76),
            ex("lh-c-position", "Left hand on C",
               "Left hand on C: pinky on the C below middle C, thumb on G. Up and back down.",
               left="C4 D E F G1 G4 F E D C1", lf="C", after=["rh-c-position"], tempo=76),
            ex("steps-rh", "Steps",
               "A step goes to the very next key, and the very next finger. Step up and down with your right hand.",
               right="c4 d e d c d e f g f e d c1", rf="C", after=["rh-c-position", "steps-and-skips"], tempo=76),
            ex("skips-rh", "Skips",
               "A skip jumps over one key: C to E, E to G. Your fingers skip too: 1 to 3, 3 to 5.",
               right="c4 e g e c e g2 g4 e c e c1", rf="C", after=["steps-rh"], tempo=72),
            ex("steps-lh", "Left-hand steps",
               "Step up and down with your left hand on C.", left="C4 D E D C D E F G F E D C1", lf="C", after=["lh-c-position", "steps-rh"], tempo=76),
            ex("skips-lh", "Left-hand skips",
               "Skip with your left hand: C, E, G and back, fingers 5, 3 and 1.", left="C4 E G E C E G2 G4 E C E C1", lf="C",
               after=["steps-lh", "skips-rh"], tempo=72),
            ex("reach-for-a", "Reaching for A",
               "Sometimes the pinky stretches up one more key, from G to A, and then comes home to G.",
               right="c4 e g a g1 c4 e g a g2 e4 c1", rf="C", after=["skips-rh", "find-a"], tempo=72),
            ex("hands-turns", "Hands take turns",
               "Right hand plays C D E, then the left hand answers C D E down low. Then back down, taking turns.",
               right="c4 d e2 r1 e4 d c2 r1", left="r1 C4 D E2 r1 E4 D C2", rf="C", lf="C", after=["steps-lh"], stages="hands"),
            ex("hold-and-play", "Hold one, play with the other",
               "Your left pinky holds a long, low C while the right hand walks up and down. Keep the C held down the whole bar.",
               right="c4 d e f g1 g4 f e d c1", left="C1 C1 C1 C1", rf="C", lf="5 5 5 5", after=["hands-turns"], stages="ht", tempo=66),
            ex("hands-together-same", "Hands together, same notes",
               "Both hands play the same letters at the same time: right thumb and left pinky on C, then D, then E.",
               right="c4 d e2 e4 d c2 c4 d e d c1", left="C4 D E2 E4 D C2 C4 D E D C1", rf="C", lf="C", after=["hold-and-play"],
               stages="ht", tempo=60, tip="this is the hardest step so far: slow is perfect."),
        ]),
    ],
    READY: [
        ("new-positions", "New hand positions", [
            ex("middle-c-position", "Middle C position",
               "Both thumbs on middle C. The right hand goes up to G; the left hand goes down to F.",
               right="c4 d e f g1 r1 r1", left="r1 r1 c4 B A G F1", rf="C", lf="midC", after=["hands-together-same", "middle-c"], stages="hands"),
            ex("mirror-hands", "Mirror hands",
               "From middle C, both hands move away from each other, then back: like looking in a mirror.",
               right="c4 d e f g f e d c1", left="c4 B A G F G A B c1", rf="C", lf="midC", after=["middle-c-position"], stages="ht", tempo=60),
            ex("g-position-rh", "Right hand on G",
               "Move your whole right hand up so the thumb sits on G. Five fingers, G to D.",
               right="g4 a b c' d'1 d'4 c' b a g1", rf="G", after=["rh-c-position", "find-g", "treble-g"]),
            ex("g-position-lh", "Left hand on G",
               "Left pinky on the low G, thumb on D.", left="GG4 AA BB C D1 D4 C BB AA GG1", lf="G", after=["g-position-rh", "lh-c-position"]),
            ex("c-to-g", "Moving from C to G",
               "Play up from C, lift the whole hand, and land with the thumb on G.", right="c4 d e f g1 g4 a b c' d'1", rf="1 2 3 4 5 1 2 3 4 5",
               after=["g-position-rh"]),
            ex("dm-position-rh", "Right hand on D",
               "Thumb on D: D E F G A. This is the hand shape for D minor.", right="d4 e f g a1 a4 g f e d1", rf="Dm",
               after=["g-position-rh", "find-d"]),
            ex("dm-position-lh", "Left hand on D",
               "Left pinky on D, thumb on A.", left="D4 E F G A1 A4 G F E D1", lf="Dm", after=["dm-position-rh", "g-position-lh"]),
        ]),
        ("patterns", "Patterns & chords", [
            ex("five-together-c", "Five fingers together on C",
               "Both hands up and down C D E F G at the same time.", right="c4 d e f g f e d c1", left="C4 D E F G F E D C1",
               rf="C", lf="C", after=["hands-together-same", "steps-lh"], stages="ht", tempo=60),
            ex("five-together-g", "Five fingers together on G",
               "The same pattern in G position, both hands.", right="g4 a b c' d' c' b a g1", left="GG4 AA BB C D C BB AA GG1",
               rf="G", lf="G", after=["five-together-c", "hot-cross-buns-lh-g"], stages="ht", tempo=60),
            ex("bouncy-notes", "Bouncy notes",
               "A dot over or under a note means staccato: short and bouncy, as if the key were hot. Bounce up and down the C position.",
               right="c4 d e f g f e d c1", rf="C", after=["rh-c-position", "hear-smooth-bouncy"], marks={"staccato": True}),
            ex("loud-and-quiet", "Loud and quiet",
               "f means loud: play the first two bars with quick, strong fingers. p means quiet: play the last two gently.",
               right="c4 e g e c1 c4 e g e c1", rf="C", after=["skips-rh", "loud-and-quiet-words"], marks={"dynamics": {1: "f", 3: "p"}}),
            ex("broken-c-rh", "C chord, one note at a time",
               "C, E and G are the C chord. Play them one at a time with fingers 1, 3 and 5, up and back down.",
               right="c4 e g2 g4 e c2 c4 e g e c1", rf="C", after=["skips-rh", "chords-word"]),
            ex("broken-c-lh", "C chord in the left hand",
               "Left hand: C E G with fingers 5, 3 and 1.", left="C4 E G2 G4 E C2 C4 E G E C1", lf="C", after=["broken-c-rh", "skips-lh"]),
            ex("block-c", "C chord, all together",
               "Now press C, E and G all at once, fingers 1, 3 and 5, and hold it.",
               right="chord{c2 e g} chord{c2 e g} c4 e g2 chord{c1 e g}", rf="1 3 5 1 3 5 1 3 5 1 3 5", after=["broken-c-rh", "hear-one-or-many"], tempo=60),
            ex("broken-dm-rh", "D minor chord, one note at a time",
               "D, F and A make the D minor chord: a darker sound. Fingers 1, 3 and 5 from D.", right="d4 f a2 a4 f d2 d4 f a f d1", rf="Dm",
               after=["dm-position-rh", "block-c", "hear-happy-sad"]),
            ex("broken-dm-lh", "D minor chord in the left hand",
               "Left hand: D F A with fingers 5, 3 and 1.", left="D4 F A2 A4 F D2 D4 F A F D1", lf="Dm", after=["broken-dm-rh", "broken-c-lh", "dm-position-lh"]),
        ]),
        ("thumbs", "Thumb under, finger over", [
            ex("thumb-under-up", "Thumb tucks under",
               "Play C D E with fingers 1 2 3, then tuck your thumb under to play F, and carry on up to C with 2 3 4 5.",
               right="c4 d e f g a b2 c'1", rf="1 2 3 1 2 3 4 5", after=["c-to-g", "steps-rh"], tempo=60),
            ex("thumb-under-down", "Finger 3 crosses over",
               "Coming down from the high C: 5 4 3 2 1 down to F, then finger 3 crosses over the thumb to E.",
               right="c'4 b a g f e d2 c1", rf="5 4 3 2 1 3 2 1", after=["thumb-under-up"], tempo=60),
            ex("cross-over-lh-up", "Left hand: finger 3 crosses over",
               "Left hand from C: 5 4 3 2 1 up to G, then finger 3 crosses over the thumb to A, and on up to C.",
               left="C4 D E F G A B2 c1", lf="5 4 3 2 1 3 2 1", after=["thumb-under-down", "lh-c-position"], tempo=60),
            ex("cross-over-lh-down", "Left hand: thumb tucks under",
               "Coming down: 1 2 3 from C, then the thumb tucks under to G, and on down to C with 1 2 3 4 5.",
               left="c4 B A G F E D2 C1", lf="1 2 3 1 2 3 4 5", after=["cross-over-lh-up"], tempo=60),
        ]),
    ],
}

# Sight-reading: a pool of short pieces per requirement, each new each time.
# {key, title, text, hand, pitches (right) / lpitches (left), rhythm (level), bars, skips?, after, rehearse_only?}
RHYTHM_LEVELS = ["ta", "ta-a", "whole", "rest", "ti-ti"]
RHYTHMS = {
    "ta": [("4", "4", "4", "4")],
    "ta-a": [("2", "2"), ("4", "4", "2"), ("2", "4", "4"), ("4", "2", "4")],
    "whole": [("1",)],
    "rest": [("4", "4", "r4", "4"), ("2", "r2"), ("4", "r4", "2"), ("r4", "4", "4", "4")],
    "ti-ti": [("8", "8", "4", "4", "4"), ("4", "8", "8", "2"), ("8", "8", "8", "8", "2"), ("4", "4", "8", "8", "4")],
}


def sight(key, title, text, pitches=None, lpitches=None, rhythm="whole", bars=4, skips=False, after=(), rhythm_only=False, tempo=66):
    return {"key": key, "title": title, "text": text, "pitches": pitches, "lpitches": lpitches, "rhythm": rhythm, "bars": bars,
            "skips": skips, "after": list(after), "rhythm_only": rhythm_only, "tempo": tempo}


SIGHT = {
    FIRST: [
        ("rhythm", "Rhythm on one key", [
            sight("rhythm-ta", "Ta, ta, ta, ta", "Every note is a crotchet: one beat, say 'ta'. Play them all on middle C, with your thumb, nice and even.",
                  pitches=[60], rhythm="ta", bars=2, after=["middle-c", "ta-and-ta-a"], rhythm_only=True),
            sight("rhythm-ta-a", "Ta and ta-a", "Now some notes are minims: two beats, 'ta-a'. Hold them down for both beats.",
                  pitches=[60], rhythm="ta-a", bars=2, after=["rhythm-ta"], rhythm_only=True),
            sight("rhythm-whole", "Ta-a-a-a", "A semibreve is four beats: hold it for the whole bar.",
                  pitches=[60], rhythm="whole", bars=4, after=["rhythm-ta-a", "semibreve-word"], rhythm_only=True),
            sight("rhythm-two-keys", "Rhythm on two keys", "Middle C and D, with your thumb and finger 2. Watch: does the note go up or stay the same?",
                  pitches=[60, 62], rhythm="whole", bars=4, after=["rhythm-whole", "fingers-rh"], rhythm_only=True),
        ]),
    ],
    READY: [
        ("treble", "Reading the right hand", [
            sight("read-c-d", "Reading C and D", "Middle C on its little line, D just below the stave. Right thumb on C.",
                  pitches=[60, 62], rhythm="whole", bars=4, after=["treble-c-d", "rhythm-two-keys"]),
            sight("read-c-d-e", "Reading C, D and E", "E sits on the bottom line of the treble stave.", pitches=[60, 62, 64], bars=4,
                  after=["read-c-d", "treble-e"]),
            sight("read-c-to-f", "Reading C to F", "F is in the first space.", pitches=[60, 62, 64, 65], bars=4, after=["read-c-d-e", "treble-f"]),
            sight("read-c-to-g", "Reading C to G", "G sits on the second line: now all five fingers.", pitches=[60, 62, 64, 65, 67], bars=4,
                  after=["read-c-to-f", "treble-g"]),
            sight("read-skips", "Reading steps and skips", "Some notes skip: line to line, or space to space.", pitches=[60, 62, 64, 65, 67],
                  bars=4, skips=True, after=["read-c-to-g", "skips-on-the-stave"]),
            sight("read-g-position", "Reading in G position", "Thumb on G; the notes go up to D on the fourth line.",
                  pitches=[67, 69, 71, 72, 74], bars=4, after=["read-skips", "g-position-rh", "treble-a-b-c-d"]),
            sight("read-d-position", "Reading from D", "Thumb on D: D E F G A. The hand shape for D minor.", pitches=[62, 64, 65, 67, 69],
                  bars=4, after=["read-c-to-g", "dm-position-rh"]),
        ]),
        ("bass", "Reading the left hand", [
            sight("read-lh-c-d-e", "Left hand: C, D and E", "Bass clef: C in the second space, D on the middle line, E in the third space.",
                  lpitches=[48, 50, 52], bars=4, after=["bass-c-d-e", "lh-c-position", "read-c-d-e"]),
            sight("read-lh-c-to-g", "Left hand: C to G", "F on the fourth line, G in the top space.", lpitches=[48, 50, 52, 53, 55], bars=4,
                  after=["read-lh-c-d-e", "bass-f-g"]),
            sight("read-lh-middle-c", "Left hand from middle C", "Left thumb on middle C, reading down: B, A, G, F.",
                  lpitches=[53, 55, 57, 59, 60], bars=4, after=["read-lh-c-to-g", "middle-c-position"]),
        ]),
        ("more", "Reading more", [
            sight("read-rests", "Reading rests", "A rest is a beat of silence: lift your hand and count it.", pitches=[60, 62, 64, 65, 67],
                  rhythm="rest", bars=4, after=["read-c-to-g", "rests-word"]),
            sight("read-ti-ti", "Reading ti-ti", "Two quavers joined together share one beat: 'ti-ti'.", pitches=[60, 62, 64, 65, 67],
                  rhythm="ti-ti", bars=4, after=["read-rests", "ti-ti-word"]),
            sight("read-both-staves", "Hands take turns on two staves", "The right hand reads the top stave, the left hand the bottom; they take turns.",
                  pitches=[60, 62, 64, 65, 67], lpitches=[48, 50, 52, 53, 55], bars=4,
                  after=["read-lh-middle-c", "read-g-position", "grand-stave"]),
        ]),
    ],
}

# Listening, tapping and singing: one requirement per game, one stage, a few graded items.
# {key, title, text, game, after, items}
def game(key, title, text, kind, after=(), items=4, **params):
    return {"key": key, "title": title, "text": text, "game": kind, "after": list(after), "items": items, "params": params}


AURAL = {
    FIRST: [
        ("listening", "Listening games", [
            game("hear-high-low", "High or low?", "Listen: is it way up high, like a bird, or way down low, like a bear?", "high-low",
                 after=["high-and-low"], span="far"),
            game("hear-high-low-near", "High or low? (closer)", "Now the high and low notes are closer together. Listen carefully.",
                 "high-low", after=["hear-high-low"], span="near"),
            game("hear-loud-quiet", "Loud or quiet?", "Is the music loud, like a lion, or quiet, like a mouse?", "loud-quiet",
                 after=["loud-and-quiet-words"]),
            game("hear-fast-slow", "Fast or slow?", "Is the music running fast, or walking slowly?", "fast-slow", after=["hear-loud-quiet"]),
            game("hear-long-short", "Long or short sounds?", "Are the notes long, like a yawn, or short, like a hiccup?", "long-short",
                 after=["hear-fast-slow"]),
            game("hear-up-down", "Going up or going down?", "Do the notes climb up the stairs, or walk down them?", "up-down",
                 after=["hear-high-low-near"]),
            game("hear-up-down-same", "Up, down or the same?", "Up the stairs, down the stairs, or staying on the same step?", "up-down-same",
                 after=["hear-up-down"]),
            game("hear-smooth-bouncy", "Smooth or bouncy?", "Do the notes join up smoothly, or bounce like a ball?", "smooth-bouncy",
                 after=["hear-long-short", "smooth-and-bouncy"]),
            game("hear-same-different", "Same or different?", "You'll hear a little tune twice. Was it exactly the same both times?",
                 "same-different", after=["hear-up-down-same"]),
            game("hear-one-or-many", "One key or lots together?", "Is it one key, or lots of keys pressed together?", "one-many",
                 after=["hear-same-different"]),
            game("hear-happy-sad", "Happy or sad?", "Does the music sound happy and bright, or sad and dark?", "happy-sad",
                 after=["hear-one-or-many", "happy-and-sad"]),
        ]),
        ("tap-sing", "Tap and sing", [
            game("tap-beat-slow", "Tap the slow beat", "Tap any key in time with the music, like a slow heartbeat. Join in when you feel it.",
                 "tap-along", after=["steady-beat"], items=2, bpm=66),
            game("tap-beat", "Tap the beat", "The same game, a little faster: tap, tap, tap, always even.", "tap-along",
                 after=["tap-beat-slow"], items=2, bpm=84),
            game("copy-ta", "Copy my rhythm", "Listen to the rhythm, then tap it straight back on any key: ta and ta-a.", "tap-echo",
                 after=["tap-beat", "ta-and-ta-a"], items=3, level="ta-a", bars=1),
            game("sing-so-mi", "Sing it back: two notes", "Listen to the cuckoo call, then sing it back (or play it on the keys).",
                 "sing", after=["hear-high-low-near"], items=3, notes=[67, 64]),
            game("sing-so-mi-la", "Sing it back: three notes", "Now three notes to copy.", "sing", after=["sing-so-mi"], items=3,
                 notes=[67, 64, 69]),
        ]),
    ],
    READY: [
        ("ear", "Ear games", [
            game("hear-which-higher", "Which is higher?", "Two notes: is the first one higher, or the second?", "which-higher",
                 after=["hear-up-down-same"]),
            game("hear-step-skip", "Step or skip?", "Two notes: next door to each other (a step), or one jumped over (a skip)?", "step-skip",
                 after=["hear-which-higher", "steps-and-skips"]),
            game("hear-louder-quieter", "Getting louder or quieter?", "Is the music getting louder, or getting quieter?", "louder-quieter",
                 after=["hear-loud-quiet"]),
            game("hear-faster-slower", "Getting faster or slower?", "Is the music speeding up, or slowing down?", "faster-slower",
                 after=["hear-fast-slow", "hear-louder-quieter"]),
            game("hear-march-sway", "Marching or swaying?", "Does it march, left right, in twos? Or sway, ONE two three, in threes?",
                 "march-sway", after=["tap-beat"]),
            game("hear-spot-change", "Spot the change", "The tune comes twice, and one note changes. Near the beginning, or near the end?",
                 "spot-change", after=["hear-same-different", "hear-step-skip", "hear-faster-slower", "hear-march-sway"]),
        ]),
        ("echo", "Tap and sing back", [
            game("tap-pulse", "Tap the pulse of a piece", "Tap the beat of a piece, joining in as soon as you can.", "tap-along",
                 after=["tap-beat"], items=2, bpm=92, accompanied=True),
            game("copy-ti-ti", "Copy a rhythm with ti-ti", "Tap the rhythm back: now with quick ti-ti notes too.", "tap-echo",
                 after=["copy-ta", "ti-ti-word"], items=3, level="ti-ti", bars=2),
            game("sing-do-re-mi", "Sing back a short tune", "Sing back the little tune: C, D and E, in any order.", "sing",
                 after=["sing-so-mi-la"], items=3, notes=[60, 62, 64], length=4),
        ]),
    ],
}


# Theory: (key, title, text, quizzes [(prompt, options, answer index, why)], after).
def topic(key, title, text, quizzes, after=()):
    return {"key": key, "title": title, "text": text, "quizzes": quizzes, "after": list(after)}


THEORY = {
    FIRST: [
        ("at-the-piano", "At the piano", [
            topic("sitting", "Sitting at the piano",
                  "Sit on the front half of the stool, tall like a tree. Feet flat on the floor, or on a box if they don't reach. "
                  "Your elbows are a little in front of your tummy, and your hands are level with the keys.",
                  [("Where do your feet go?", ["Swinging in the air", "Flat on the floor or a box"], 1, "Flat feet keep you steady."),
                   ("How do you sit?", ["Tall like a tree", "Curled up like a snail"], 0, "Sitting tall lets your arms move freely.")]),
            topic("hand-shape", "Bubble hands",
                  "Make your hand round, as if you're holding a bubble or a small ball. Play on the tips of your fingers, "
                  "and keep your thumb on its side.",
                  [("How do your hands look when you play?", ["Flat like a pancake", "Round, holding a bubble", "Squeezed in a fist"], 1,
                    "A round hand lets every finger reach its key.")], after=["sitting"]),
            topic("finger-numbers", "Finger numbers",
                  "Each finger has a number, the same on both hands: thumbs are 1, pointers 2, middle fingers 3, ring fingers 4, and pinkies are 5. "
                  "Wiggle each one as you say its number.",
                  [("Which finger is number 1?", ["Pinky", "Thumb", "Pointer"], 1, "Thumbs are 1 on both hands."),
                   ("Which finger is number 5?", ["Thumb", "Middle finger", "Pinky"], 2, "Pinkies are 5."),
                   ("Your middle finger is number…", ["2", "4", "3"], 2, "Thumb 1, pointer 2, middle 3.")], after=["hand-shape"]),
            topic("high-and-low", "High and low",
                  "Go to the right, towards your right hand, and the sounds get higher, like a bird. Go to the left and they get lower, "
                  "like a bear.",
                  [("To play higher sounds you go…", ["To the left", "To the right"], 1, "Right is higher."),
                   ("Which animal sounds like the low keys?", ["A tiny bird", "A big bear"], 1, "Low and growly, like a bear.")],
                  after=["finger-numbers"]),
            topic("loud-and-quiet-words", "Loud and quiet",
                  "Press a key quickly and firmly for a loud sound, slowly and gently for a quiet one. Musicians use Italian words: "
                  "forte, written f, means loud; piano, written p, means quiet. The piano's full name is the pianoforte, "
                  "'quiet-loud', because it can play both.",
                  [("What does p mean?", ["Loud", "Quiet"], 1, "p is piano: quiet."),
                   ("How do you play a loud note?", ["Press the key slowly and gently", "Press it quickly and firmly"], 1,
                    "A quick, firm press makes a loud sound.")], after=["high-and-low"]),
            topic("smooth-and-bouncy", "Smooth and bouncy",
                  "Smooth notes join up, one finger holding until the next one plays: musicians say legato. Bouncy, short notes "
                  "let go quickly, like touching something hot: staccato.",
                  [("Short, bouncy notes are called…", ["Legato", "Staccato"], 1, "Staccato: short and detached."),
                   ("Smooth, joined-up notes are called…", ["Legato", "Staccato"], 0, "Legato: smooth.")], after=["loud-and-quiet-words"]),
            topic("happy-and-sad", "Happy and sad sounds",
                  "Some music sounds bright and happy; that's often a major key. Some sounds darker or sadder; that's often a minor key.",
                  [("Music in a major key often sounds…", ["Bright and happy", "Dark and sad"], 0, "Major: bright."),
                   ("Music in a minor key often sounds…", ["Bright and happy", "Darker, or sad"], 1, "Minor: darker.")],
                  after=["smooth-and-bouncy"]),
        ]),
        ("keys", "The keys and their names", [
            topic("black-key-groups", "Black keys in twos and threes",
                  "The black keys come in groups: two, then three, then two, then three, all the way along. They help you find your way, "
                  "like signposts.",
                  [("The black keys come in groups of…", ["Fours and fives", "Twos and threes", "Ones"], 1, "Twos and threes."),
                   ("How many black keys are in the small group?", ["Three", "Two", "Four"], 1, "The small group has two.")],
                  after=["high-and-low"]),
            topic("music-alphabet", "The music alphabet",
                  "The white keys are named with just seven letters: A B C D E F G. After G, it starts again at A.",
                  [("What comes after G?", ["H", "A", "C"], 1, "After G the letters start again at A."),
                   ("How many letters are in the music alphabet?", ["Five", "Twenty-six", "Seven"], 2, "A to G: seven."),
                   ("Which letter comes after C?", ["B", "D", "E"], 1, "C, then D.")], after=["black-key-groups"]),
            topic("where-c-lives", "Where C lives",
                  "C is the white key just to the left of every group of two black keys. There are lots of Cs: one by every group of two.",
                  [("C is just to the left of…", ["The three black keys", "The two black keys"], 1, "C sits by the group of two."),
                   ("How many Cs are on the piano?", ["Just one", "Lots: one by every group of two"], 1, "A C by every two black keys.")],
                  after=["music-alphabet"]),
            topic("finding-d-e", "Where D and E live",
                  "D is in the middle of the two black keys, like a dog in its kennel. E is just to the right of them.",
                  [("Which key is in the middle of the two black keys?", ["C", "E", "D"], 2, "D, in the middle."),
                   ("E is just to the right of…", ["The two black keys", "The three black keys"], 0, "E sits after the group of two.")],
                  after=["where-c-lives"]),
            topic("finding-f-g-a-b", "Where F, G, A and B live",
                  "The group of three black keys has four white keys around it: F on the left, then G and A in between, and B on the right.",
                  [("Which key is just to the left of the three black keys?", ["F", "B", "C"], 0, "F, then G, A and B."),
                   ("Which key is just to the right of the three black keys?", ["E", "F", "B"], 2, "B, and then C comes next.")],
                  after=["finding-d-e"]),
            topic("middle-c-word", "Middle C",
                  "Middle C is the C nearest the middle of the piano, usually right in front of you (by the maker's name). "
                  "It's home: lots of music starts from it.",
                  [("Middle C is…", ["The C nearest the middle", "The very lowest key", "A black key"], 0, "The C in the middle.")],
                  after=["where-c-lives"]),
            topic("steps-and-skips", "Steps and skips",
                  "From one white key to the very next one is a step: C to D. Jumping over a key is a skip: C to E.",
                  [("C to D is…", ["A step", "A skip"], 0, "Next door: a step."),
                   ("C to E is…", ["A step", "A skip"], 1, "D was jumped over: a skip.")], after=["finding-d-e"]),
        ]),
        ("beat", "Beat and rhythm", [
            topic("steady-beat", "The steady beat",
                  "Music has a beat, like your heartbeat, a ticking clock, or feet marching: always even.",
                  [("A steady beat is…", ["Fast, then slow, then fast", "Always even, like a clock"], 1, "Even, like tick, tock."),
                   ("Which has a steady beat?", ["A ticking clock", "Popcorn popping"], 0, "A clock ticks evenly.")],
                  after=["high-and-low"]),
            topic("ta-and-ta-a", "Ta and ta-a",
                  "A crotchet (also called a quarter note) lasts one beat: say 'ta'. A minim (a half note) lasts two beats: 'ta-a'. "
                  "A minim looks like a crotchet with an empty middle.",
                  [("Which note is longer?", ["A crotchet (one beat)", "A minim (two beats)"], 1, "A minim lasts two beats."),
                   ("A crotchet lasts…", ["One beat", "Two beats", "Four beats"], 0, "One beat: ta.")], after=["steady-beat"]),
            topic("semibreve-word", "Ta-a-a-a",
                  "A semibreve (a whole note) lasts four beats: 'ta-a-a-a'. It's an empty oval with no stick.",
                  [("How many beats does a semibreve last?", ["Two", "Four", "One"], 1, "Four beats."),
                   ("Which has no stick?", ["A semibreve", "A crotchet"], 0, "The semibreve is just an oval.")], after=["ta-and-ta-a"]),
        ]),
    ],
    READY: [
        ("stave", "The stave", [
            topic("lines-and-spaces", "Lines and spaces",
                  "Music is written on a stave: five lines with four spaces between them. Each note sits on a line, with the line "
                  "through its middle, or in a space, between two lines.",
                  [("How many lines does a stave have?", ["Four", "Six", "Five"], 2, "Five lines, four spaces."),
                   ("A note with a line through its middle is…", ["In a space", "On a line"], 1, "On a line.")],
                  after=["semibreve-word", "steps-and-skips"]),
            topic("higher-on-the-page", "Higher on the page, higher in sound",
                  "A note higher up the stave sounds higher, so it's further to the right on the piano. Lower on the page is lower in sound.",
                  [("A note higher up the stave sounds…", ["Lower", "Higher", "The same"], 1, "Up the page is up the piano."),
                   ("A note lower on the stave is played…", ["Further left", "Further right"], 0, "Lower sounds are to the left.")],
                  after=["lines-and-spaces"]),
            topic("steps-on-the-stave", "Steps on the stave",
                  "A step on the piano is a step on the stave too: from a line to the space just above it, or from a space to the line.",
                  [("From a line to the next space up is…", ["A skip", "A step"], 1, "Line to space: a step.")], after=["higher-on-the-page"]),
            topic("skips-on-the-stave", "Skips on the stave",
                  "A skip goes from a line to the next line, or from a space to the next space, jumping over one note.",
                  [("From a line to the next line up is…", ["A step", "A skip"], 1, "Line to line: a skip."),
                   ("From a space to the next space is…", ["A skip", "A step"], 0, "Space to space: a skip.")],
                  after=["steps-on-the-stave"]),
            topic("treble-clef", "The treble clef",
                  "The treble clef, the curly sign at the start, says the stave is for high notes, mostly the right hand. "
                  "It curls around the second line, which is G, so it's also called the G clef.",
                  [("The treble clef is mostly for…", ["The left hand", "The right hand"], 1, "High notes, right hand."),
                   ("The treble clef curls around the line for…", ["G", "C", "F"], 0, "The G clef.")], after=["higher-on-the-page"]),
            topic("bass-clef", "The bass clef",
                  "The bass clef, the sign with two dots, says the stave is for low notes, mostly the left hand. Its two dots sit either "
                  "side of the line for F, so it's also called the F clef.",
                  [("Which clef has two dots?", ["Treble clef", "Bass clef"], 1, "The bass clef's dots mark F."),
                   ("The bass clef is mostly for…", ["The left hand", "The right hand"], 0, "Low notes, left hand.")],
                  after=["treble-clef"]),
            topic("grand-stave", "Two staves together",
                  "Piano music uses two staves joined by a brace: the treble stave on top for the right hand, the bass stave below "
                  "for the left. Notes lined up one above the other are played at the same time.",
                  [("Which stave is on top?", ["The bass stave", "The treble stave"], 1, "Treble on top, bass below."),
                   ("Two notes lined up above each other are played…", ["At the same time", "One after the other"], 0, "Together.")],
                  after=["bass-clef"]),
            topic("bars-word", "Bars and bar lines",
                  "Music is split into bars by bar lines, the lines straight down the stave. A double bar line at the very end means "
                  "the piece is finished.",
                  [("What splits music into bars?", ["Bar lines", "Clefs"], 0, "Bar lines."),
                   ("A double bar line means…", ["Start again", "The end"], 1, "The piece is finished.")], after=["grand-stave"]),
        ]),
        ("notes", "Notes on the stave", [
            topic("treble-c-d", "Middle C and D on the treble stave",
                  "Middle C sits below the treble stave on its own short line, a ledger line. D hangs just below the bottom line.",
                  [("Middle C sits on…", ["The middle line", "A short line of its own below the stave"], 1, "A ledger line."),
                   ("Which note hangs just below the bottom line?", ["D", "E", "C"], 0, "D, just under it.")],
                  after=["treble-clef", "middle-c-word"]),
            topic("treble-e", "E on the treble stave", "E sits on the bottom line of the treble stave.",
                  [("Which note sits on the bottom line of the treble stave?", ["D", "F", "E"], 2, "E, on the bottom line.")],
                  after=["treble-c-d"]),
            topic("treble-f", "F on the treble stave", "F is in the first space, between the bottom two lines.",
                  [("Which note is in the bottom space of the treble stave?", ["F", "G", "E"], 0, "F, in the first space.")],
                  after=["treble-e"]),
            topic("treble-g", "G on the treble stave", "G sits on the second line, the one the treble clef curls around.",
                  [("Which note is on the second line of the treble stave?", ["A", "G", "F"], 1, "G, where the clef curls."),
                   ("Count up from middle C: C, D, E, F…", ["G", "A", "B"], 0, "Then G.")], after=["treble-f"]),
            topic("treble-a-b-c-d", "A to D on the treble stave",
                  "Above G: A in the second space, B on the middle line, C in the third space, D on the fourth line.",
                  [("Which note is on the middle line of the treble stave?", ["C", "B", "A"], 1, "B, the middle line."),
                   ("Which note is in the space just above G's line?", ["A", "B", "F"], 0, "Then A.")], after=["treble-g"]),
            topic("bass-c-d-e", "C, D and E on the bass stave",
                  "The left hand's C (the one below middle C) is in the second space of the bass stave. D is on the middle line, "
                  "E in the third space.",
                  [("Which note is on the middle line of the bass stave?", ["D", "C", "E"], 0, "D, the middle line."),
                   ("The C below middle C is in…", ["The top space", "The second space"], 1, "The second space up.")],
                  after=["bass-clef", "treble-g"]),
            topic("bass-f-g", "F and G on the bass stave",
                  "F is on the fourth line, between the bass clef's two dots. G is in the top space.",
                  [("Which line do the bass clef's dots mark?", ["F", "G", "D"], 0, "F, between the dots."),
                   ("Which note is in the top space of the bass stave?", ["A", "G", "F"], 1, "G.")], after=["bass-c-d-e"]),
            topic("sharps-and-flats", "Sharps and flats",
                  "The black keys have names too. A sharp (♯) is the key just to the right, a little higher: the black key after C is C sharp. "
                  "A flat (♭) is the key just to the left: the same black key is also D flat.",
                  [("A sharp sign means play…", ["The key just to the left", "The key just to the right"], 1, "Sharp: one key higher."),
                   ("The black key between C and D can be called…", ["C sharp or D flat", "E sharp"], 0, "Both names.")],
                  after=["treble-a-b-c-d", "finding-f-g-a-b"]),
            topic("chords-word", "Chords",
                  "A chord is notes played together. The C chord is C, E and G: every other white key, skipping one each time. "
                  "On the stave its notes stack up line, line, line or space, space, space.",
                  [("Which notes make the C chord?", ["C D E", "C E G", "C F A"], 1, "C, E and G."),
                   ("On the stave, the notes of a C chord look like…", ["A snowman: stacked skips", "A staircase: steps"], 0,
                    "Stacked skips, like a snowman.")], after=["skips-on-the-stave"]),
        ]),
        ("counting", "Counting", [
            topic("time-signature-word", "Four beats in a bar",
                  "The two numbers at the start are the time signature. 4/4 means four crotchet beats in every bar: count 1 2 3 4. "
                  "2/4 means two: 1 2, like a march.",
                  [("How many beats in a bar of 4/4?", ["Two", "Four", "Three"], 1, "The top number: four."),
                   ("2/4 has how many beats in a bar?", ["Two", "Four"], 0, "Two, like left, right.")], after=["bars-word"]),
            topic("rests-word", "Rests",
                  "A rest is a silence, and it counts beats too. A crotchet rest is one silent beat (a squiggle). A minim rest is two "
                  "silent beats: a little hat sitting on the middle line.",
                  [("A rest means…", ["Play louder", "Be silent for a beat or more"], 1, "Silence, but keep counting."),
                   ("How long is a minim rest?", ["One beat", "Two beats"], 1, "Two beats, like a minim.")],
                  after=["time-signature-word"]),
            topic("ti-ti-word", "Ti-ti: quavers",
                  "A quaver (an eighth note) is half a beat. Two quavers are often joined by a beam and share one beat: 'ti-ti'.",
                  [("Two quavers joined together last…", ["One beat", "Two beats"], 0, "Ti-ti: one beat between them."),
                   ("What joins quavers together?", ["A beam", "A tie"], 0, "A beam.")], after=["rests-word"]),
        ]),
    ],
}


# -- the tree ------------------------------------------------------------------------------------

def tunes() -> list[dict]:
    return json.loads((PACKAGE / "data" / "first_tunes.json").read_text(encoding="utf-8"))["tunes"]


TUNE_FAMILIES = {"black": "Black-key tunes", "by-ear": "Tunes to learn by ear", "two-hands": "Two hands",
                 "g-tunes": "Tunes in G position", "together": "Hands together, from the music"}


def play_stages(kind: str) -> list[dict]:
    st = templates.stage
    if kind == "hands":  # the hands take turns in one score: each alone, then all of it in time
        return [st("rh", "Right hand", "right", "learn", 80), st("lh", "Left hand", "left", "learn", 80),
                st("play", "All of it, in time", "both", "rehearse", 100, final=True)]
    if kind == "ht":
        return [st("rh", "Right hand", "right", "learn", 80), st("lh", "Left hand", "left", "learn", 80),
                st("together", "Hands together, slowly", "both", "learn", 70),
                st("play", "Hands together, in time", "both", "rehearse", 100, final=True)]
    return [st("learn", "Find the keys", "both", "learn", 80), st("play", "In time", "both", "rehearse", 100, final=True)]


def tune_stages(tune: dict) -> list[dict]:
    """Four-bar sections when the tune is longer than eight bars; each hand first when there are two."""
    st = templates.stage
    two = bool(tune.get("right")) and bool(tune.get("left"))
    bars = tune_bars(tune)
    out = []
    spans = [(s, min(bars, s + 3)) for s in range(1, bars + 1, 4)] if bars > 8 else [(1, bars)]
    for k, (a, b) in enumerate(spans, 1):
        label = f"bars {a}-{b}" if len(spans) > 1 else ""
        extra = {"bars": f"{a}-{b}"} if len(spans) > 1 else {}
        tag = f"s{k}-" if len(spans) > 1 else ""
        if two:
            out += [dict(st(f"{tag}rh", f"{label} right hand".strip().capitalize(), "right", "learn", 80), **extra),
                    dict(st(f"{tag}lh", f"{label} left hand".strip().capitalize(), "left", "learn", 80), **extra)]
        out.append(dict(st(f"{tag}learn", (f"{label.capitalize()}, find the keys" if label else "Find the keys"), "both", "learn", 80), **extra))
    return out + [st("slow", "In time, slowly", "both", "rehearse", 70), st("play", "In time", "both", "rehearse", 100, final=True)]


def add(tree, below: dict[str, int]) -> list[dict]:
    """Add both tiers to a Tree being built (after its own links are made) and link the lowest
    syllabus tier's starting points to Ready to read. below: {tier id: order} of the syllabus
    grades. Returns the two tiers' entries for atlas['tiers'], lowest first."""
    lowest = min(below, key=below.get) if below else None
    base = below[lowest] if lowest else 0
    tiers = [{"id": FIRST, "title": TITLES[FIRST], "order": base - 2}, {"id": READY, "title": TITLES[READY], "order": base - 1}]
    ids: dict[str, str] = {}
    after: dict[str, list[str]] = {}
    for t in tiers:
        tid = t["id"]
        tree.add({"id": tid, "level": "tier", "title": t["title"], "order": t["order"], "tier": tid})
        for s in STRANDS:
            tree.add({"id": f"{tid}.{s['id']}", "level": "strand", "parent": tid, "tier": tid, "strand": s["id"],
                      "title": f"{t['title']} · {s['title']}"})

        def req(strand, fkey, ftitle, item, kind, stages, **extra):
            fam = tree.family(tid, strand, fkey, ftitle)
            r = tree.requirement(fam, item["key"], item["title"], kind, stages, **extra)
            if item["key"] in ids:
                raise ValueError(f"Duplicate key {item['key']}")
            ids[item["key"]] = r["id"]
            after[r["id"]] = item.get("after", [])
            return r

        for fkey, ftitle, items in THEORY[tid]:
            for item in items:
                req("theory", fkey, ftitle, item, "theory", [dict(templates.stage("learn", "Learn it", final=True), answer="quiz")],
                    spec={"topic": item["key"], "young": True})
        for fkey, ftitle, items in TECHNIQUE[tid]:
            for item in items:
                req("technique", fkey, ftitle, item, "notes", play_stages(item["stages"]), spec={"exercise": item["key"], "young": True})
        for tune in (t2 for t2 in tunes() if t2["tier"] == tid):
            req("pieces", tune["family"], TUNE_FAMILIES[tune["family"]], {"key": tune["id"], "title": tune["title"], "after": tune["after"]},
                "piece", tune_stages(tune), piece=tune["id"], young=True)
        for fkey, ftitle, items in SIGHT[tid]:
            for item in items:
                st = templates.stage
                stages = ([st("slow", "Slowly", "both", "rehearse", 70), st("read", "In time", "both", "rehearse", 100, final=True)]
                          if item["rhythm_only"] else
                          [st("learn", "Find the notes", "both", "learn", 100), st("read", "Read it in time", "both", "rehearse", 100, final=True)])
                req("sight", fkey, ftitle, item, "sight", stages, spec={"pool": item["key"], "young": True})
        for fkey, ftitle, items in AURAL[tid]:
            for item in items:
                req("aural", fkey, ftitle, item, "aural", [dict(templates.stage("play", "Play the game", final=True), answer="game")],
                    spec={"game": item["game"], "young": True})
        tree.add({"id": f"{tid}.review", "level": "review", "parent": tid, "tier": tid, "title": f"{t['title']} review"})

    for rid, keys in after.items():
        missing = [k for k in keys if k not in ids]
        if missing:
            raise ValueError(f"{rid} comes after unknown {missing}")
        tree.by_id[rid]["prereqs"] = sorted({ids[k] for k in keys})
    if lowest:
        _gateways(tree, lowest, ids)
    return tiers


# What the lowest syllabus tier's requirements need from Ready to read (by the key of ours).
GATE_TECHNIQUE = {"scale": ["thumb-under-down", "cross-over-lh-down"], "arpeggio": ["broken-c-lh"], "contrary": ["mirror-hands"]}
GATE_AURAL = {"pulse": ["tap-pulse"], "rhythm-echo": ["copy-ti-ti"], "sing-echo": ["sing-do-re-mi"],
              "dynamics": ["hear-louder-quieter"], "articulation": ["hear-smooth-bouncy"], "tempo": ["hear-faster-slower"]}
GATE_THEORY = {"staff-treble": ["treble-a-b-c-d"], "staff-bass": ["bass-f-g"], "keyboard": ["sharps-and-flats"],
               "note-values": ["ti-ti-word"], "time": ["time-signature-word"], "dynamics": ["loud-and-quiet"],
               "legato": ["bouncy-notes"]}
GATE_SIGHT = {"key:C": ["read-skips", "read-lh-c-to-g"], "key:Dm": ["read-d-position"], "time:": ["time-signature-word"],
              "minims": ["read-ti-ti"], "staccato": ["bouncy-notes"], "legato": ["bouncy-notes"], "f-and-p": ["loud-and-quiet"],
              "five-finger": ["read-both-staves"]}
GATE_DEFAULT = {"technique": ["five-together-g", "broken-dm-lh"], "pieces": ["twinkle-together"], "sight": ["read-both-staves"],
                "aural": ["hear-spot-change"], "theory": ["grand-stave"]}


def _gateways(tree, lowest: str, ids: dict[str, str]) -> None:
    for r in [n for n in tree.nodes if n["level"] == "requirement" and n["tier"] == lowest]:
        spec = r.get("spec") or {}
        keys: list[str] = []
        if r["kind"] == "technique":
            keys += GATE_TECHNIQUE.get(spec.get("type"), [])
            if spec.get("tonic") == "D":
                keys += ["broken-dm-lh", "dm-position-lh"]
        elif r["kind"] == "aural":
            for skill in spec.get("skills", []):
                keys += GATE_AURAL.get(skill, [])
        elif r["kind"] == "theory":
            keys += [k for word, ks in GATE_THEORY.items() if word in str(spec.get("topic", "")) for k in ks]
        elif r["kind"] == "sight":
            covers = " ".join(r.get("covers", [])) + " " + r["id"].rsplit(".", 1)[-1]
            keys += [k for word, ks in GATE_SIGHT.items() if word in covers for k in ks]
        if not r["prereqs"]:  # a starting point: it needs the end of its strand here
            keys += GATE_DEFAULT.get(r["strand"], [])
        r["prereqs"] = sorted(set(r["prereqs"]) | {ids[k] for k in keys if k in ids})


# -- music ---------------------------------------------------------------------------------------

def _tiny_pitches(text: str, time: str = "4/4", sounded: bool = False) -> list[list[int]]:
    """Each note or chord of a tinyNotation line, as its pitches (rests left out). sounded:
    leave out the notes a tie carries on (as a score reads back)."""
    from ..lessons import _tiny

    out = []
    for n in _tiny(text, time):
        if sounded and n.tie is not None and n.tie.type in ("stop", "continue"):
            continue
        if n.isChord:
            out.append([p.midi for p in n.pitches])
        elif n.isNote:
            out.append([n.pitch.midi])
    return out


def tune_bars(tune: dict) -> int:
    from ..lessons import _tiny
    from music21 import meter

    total = max(sum(n.quarterLength for n in _tiny(tune[h], tune["time"])) for h in ("right", "left") if tune.get(h))
    return int(-(-total // meter.TimeSignature(tune["time"]).barDuration.quarterLength))


def fingers(text: str | None, spec: str | None, hand: str, time: str = "4/4") -> list[int] | None:
    """One finger per note written (each chord note too): from digits, or from a hand position."""
    if not text or not spec:
        return None
    notes = [p for chord in _tiny_pitches(text, time) for p in chord]
    if re.fullmatch(r"[1-5]( [1-5])*", spec):
        out = [int(d) for d in spec.split()]
    else:
        table = (RH if hand == "right" else LH)[spec]
        out = [table[p] for p in notes]
    if len(out) != len(notes):
        raise ValueError(f"{len(out)} fingers for {len(notes)} notes in {text!r}")
    return out


def _letter(note_xml: str) -> str | None:
    step = re.search(r"<step>([A-G])</step>", note_xml)
    alter = re.search(r"<alter>(-?\d)</alter>", note_xml)
    if not step:
        return None
    return step.group(1) + {"1": "♯", "-1": "♭"}.get(alter.group(1) if alter else "", "")


def mark_up(xml: str, hands: list[str], rf: list[int] | None = None, lf: list[int] | None = None, letters: bool = False,
            staccato: bool = False, dynamics: dict[int, str] | None = None) -> str:
    """Finger numbers (above the right hand, below the left), letter names under the notes,
    staccato dots and dynamics (on the first part), written into a lesson's MusicXML. hands:
    its parts' hands in score order (build_lesson writes the right hand first)."""
    parts = re.findall(r'<part id="[^"]+">.*?</part>', xml, flags=re.S)
    for part, hand in zip(parts, hands):
        fing = list((rf if hand == "right" else lf) or [])
        # No bar numbers: beside the finger numbers they read as fingers.
        new = re.sub(r'(<measure [^>]*number="1"[^>]*>)', r'\1<print><measure-numbering>none</measure-numbering></print>', part, count=1)

        def note(m: re.Match) -> str:
            body = m.group(0)
            if "<rest" in body:
                return body
            bits = []
            if fing:
                where = "above" if hand == "right" else "below"
                bits.append(f'<technical><fingering placement="{where}">{fing.pop(0)}</fingering></technical>')
            if staccato and "<type>whole</type>" not in body:
                bits.append("<articulations><staccato/></articulations>")
            if bits:
                if "<notations>" in body:
                    body = body.replace("</notations>", "".join(bits) + "</notations>", 1)
                else:
                    body = body.replace("</note>", f"<notations>{''.join(bits)}</notations></note>")
            name = _letter(body)
            if letters and name and "<chord/>" not in body:
                body = body.replace("</note>", f'<lyric number="1"><syllabic>single</syllabic><text>{name}</text></lyric></note>')
            return body
        new = re.sub(r"<note[ >].*?</note>", note, new, flags=re.S)
        if dynamics and hand == hands[0]:
            for bar, mark in dynamics.items():
                d = f'<direction placement="below"><direction-type><dynamics><{mark}/></dynamics></direction-type></direction>'
                m = re.search(rf'<measure [^>]*number="{bar}"[^>]*>(.*?)</measure>', new, flags=re.S)
                if m:
                    inner = m.group(1)
                    at = inner.find("</attributes>")
                    inner = inner[:at + len("</attributes>")] + d + inner[at + len("</attributes>"):] if at >= 0 else d + inner
                    new = new[:m.start(1)] + inner + new[m.end(1):]
        xml = xml.replace(part, new)
    return xml


class Writer:
    """Writes scores into <lessons>/<folder>, checks each one (engraving lint, read back note
    for note) and keeps a report."""

    def __init__(self, lessons: pathlib.Path, lint: bool = True) -> None:
        self.lessons = lessons
        self.lint = lint
        self.report = {"lessons": 0, "scores": 0, "problems": []}

    def score(self, folder: str, name: str, title: str, right: str | None, left: str | None, time: str = "4/4", key: str = "C",
              bpm: int = 72, rf=None, lf=None, letters: bool = False, staccato: bool = False, dynamics=None) -> str:
        from .. import engraving
        from ..lessons import build_lesson
        from ..notes import load_score

        out = self.lessons / folder
        path, _ = build_lesson(title, right, left, time, key, bpm, out_dir=out, filename=name)
        path = pathlib.Path(path)
        path.write_text(mark_up(path.read_text(encoding="utf-8"), [h for h, t in (("right", right), ("left", left)) if t], rf, lf, letters, staccato, dynamics), encoding="utf-8")
        want = sorted(p for text in (right, left) if text for chord in _tiny_pitches(text, time, sounded=True) for p in chord)
        got = sorted(n.pitch for n in load_score(path).notes)
        if got != want:
            self.report["problems"].append(f"{folder}/{name}: read back {len(got)} notes, wrote {len(want)}")
        if self.lint:
            found = engraving.lint(path.read_text(encoding="utf-8"))["findings"]
            if found:
                self.report["problems"].append(f"{folder}/{name}: " + "; ".join(sorted({f['rule'] for f in found})))
        self.report["scores"] += 1
        return f"{folder}/{name}.musicxml"

    def lesson(self, lesson: dict) -> None:
        (self.lessons / f"{lesson['id']}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
        self.report["lessons"] += 1


def _lesson(stage: dict, req: dict, steps: list[dict]) -> dict:
    return {"id": stage["id"], "version": 1, "made": MADE, "checked": True, "requirement": req["id"], "steps": steps}


def _play_steps(stage: dict, file: str, text: str) -> list[dict]:
    st = stage["stage"]
    learn = st["mode"] == "learn"
    hand = st["hand"]
    rule = LEARN_PASS if learn else PLAY_PASS
    steps = [{"id": "read", "type": "read", "text": f"{st['title']}. {text}{LEARN_SAYS if learn else PLAY_SAYS}"},
             {"id": "listen", "type": "listen", "file": file, "hand": hand, "tempo_percent": st["tempo_percent"]},
             {"id": "play", "type": "play", "file": file, "hand": hand, "mode": st["mode"], "tempo_percent": st["tempo_percent"],
              "graded": True, "pass": rule}]
    if st.get("bars"):
        for s in steps[1:]:
            s["bars"] = st["bars"]
    return steps


def _say(item: dict) -> str:
    return item["text"] + (f" Grown-ups: {item['tip']}" if item.get("tip") else "")


# -- sight-reading pools ---------------------------------------------------------------------------

def _spell(midi: int) -> str:
    from .pan import spell

    return spell(midi, "C")


def pool_piece(item: dict, seed: int) -> dict:
    """{right, left}: a short piece in the item's notes and rhythms, mostly by step, ending on
    its first note (C, G or D: the thumb or pinky's home)."""
    rng = random.Random(seed)
    level = RHYTHM_LEVELS.index(item["rhythm"])
    pats = [p for lv in RHYTHM_LEVELS[:level + 1] for p in RHYTHMS[lv]]
    hands = [h for h, key in (("right", "pitches"), ("left", "lpitches")) if item.get(key)]
    turns = len(hands) == 2
    lines = {"right": [], "left": []}
    walk = {h: 0 for h in hands}
    started: set[str] = set()
    for b in range(item["bars"]):
        hand = hands[b % 2] if turns else hands[0]
        other = [h for h in hands if h != hand]
        pitches = item["pitches"] if hand == "right" else item["lpitches"]
        home = len(pitches) - 1 if hand == "left" and pitches[-1] == 60 else 0  # the left hand from middle C reads down
        last = b == item["bars"] - 1 or turns and b == item["bars"] - 2 and hand == "right"
        pat = ("1",) if last and level >= 2 else rng.choice(pats)
        if last and level < 2:
            pat = rng.choice([p for p in pats if not any(t.startswith("r") for t in p)])
        for k, tok in enumerate(pat):
            if tok.startswith("r"):
                lines[hand].append(tok)
                continue
            if hand not in started:  # each hand starts at home
                i = home
                started.add(hand)
            elif last and k == len(pat) - 1:
                i = home
            else:
                choices = [-1, 1, 0, -1, 1] + ([-2, 2] if item["skips"] else [])
                i = max(0, min(len(pitches) - 1, walk[hand] + rng.choice(choices)))
                if last and k == len(pat) - 2:
                    i = max(0, min(len(pitches) - 1, home + (1 if home == 0 else -1)))
            walk[hand] = i
            lines[hand].append(_spell(pitches[i]) + tok)
        for o in other:
            lines[o].append("r1")
    return {h: " ".join(lines[h]) for h in hands} | {h: None for h in ("right", "left") if h not in hands}


def write_pools(w: Writer, count: int = 8) -> None:
    for tid in OURS:
        for _, _, items in SIGHT[tid]:
            for item in items:
                seen, n, seed = set(), 0, 0
                while n < count and seed < count * 15:
                    seed += 1
                    piece = pool_piece(item, seed * 7919)
                    sig = (piece["right"], piece["left"])
                    if sig in seen:
                        continue
                    seen.add(sig)
                    n += 1
                    w.score("sight", f"{tid}-{item['key']}-{n}", f"{TITLES[tid]} · {item['title']}", piece["right"], piece["left"],
                            bpm=item["tempo"], letters=tid == FIRST)
                if n == 0:
                    w.report["problems"].append(f"sight/{tid}-{item['key']}: no pieces")


# -- listening games -------------------------------------------------------------------------------

def _midi(w: Writer, name: str, notes: list[tuple], bpm: float = 84, beats: int = 4) -> str:
    from . import aural

    folder = w.lessons / "aural"
    folder.mkdir(parents=True, exist_ok=True)
    aural.write_midi(folder / f"{name}.mid", notes, bpm=bpm, beats_per_bar=beats)
    return f"aural/{name}.mid"


def _tune(rng: random.Random, base: int = 60, count: int = 8) -> list[int]:
    steps = [0, 2, 4, 5, 7, 9]
    out, i = [], 0
    for _ in range(count):
        out.append(base + steps[i])
        i = max(0, min(len(steps) - 1, i + rng.choice([-1, 1, 1, -1, 2, -2])))
    return out


def _quiz(qid, name, prompt, options, answer, file) -> dict:
    return {"id": qid, "type": "quiz", "file": file, "prompt": prompt, "options": options, "answer": answer,
            "accept": [options[answer].split(" (")[0]], "graded": True}


def game_items(w: Writer, item: dict, sid: str, rng: random.Random) -> list[dict]:
    from . import aural

    kind, p, out = item["game"], item["params"], []
    tag = sid.replace(".", "_")
    answers = [k % 2 for k in range(item["items"])]
    rng.shuffle(answers)  # a balanced mix, in a random order
    for k in range(1, item["items"] + 1):
        name, a = f"{tag}-{k}", answers[k - 1]
        if kind == "high-low":
            far = p.get("span") == "far"
            base = (84 if far else 72) if a == 0 else (36 if far else 48)
            notes = [(j, j + 0.9, base + d, 80) for j, d in enumerate(rng.choice([(0, 4, 7), (7, 4, 0), (0, 2, 4, 2, 0)]))]
            out.append(_quiz(f"q{k}", name, item["title"], ["high", "low"], a, _midi(w, name, notes)))
        elif kind == "loud-quiet":
            notes = [(j * 0.5, j * 0.5 + 0.45, m, 110 if a == 0 else 34) for j, m in enumerate(_tune(rng))]
            out.append(_quiz(f"q{k}", name, item["title"], ["loud", "quiet"], a, _midi(w, name, notes)))
        elif kind == "fast-slow":
            notes = [(j * 0.5, j * 0.5 + 0.45, m, 76) for j, m in enumerate(_tune(rng))]
            out.append(_quiz(f"q{k}", name, item["title"], ["fast", "slow"], a, _midi(w, name, notes, bpm=168 if a == 0 else 52)))
        elif kind == "long-short":
            notes = ([(j * 2, j * 2 + 1.95, m, 72) for j, m in enumerate(_tune(rng, count=4))] if a == 0 else
                     [(j * 0.5, j * 0.5 + 0.12, m, 72) for j, m in enumerate(_tune(rng, count=8))])
            out.append(_quiz(f"q{k}", name, item["title"], ["long", "short"], a, _midi(w, name, notes)))
        elif kind in ("up-down", "up-down-same"):
            three = kind == "up-down-same"
            which = rng.randrange(3) if three else a
            start = rng.choice([60, 62, 64, 65, 67])
            scale = [m for m in range(start - 9, start + 10) if m % 12 in (0, 2, 4, 5, 7, 9, 11)]
            i = scale.index(start)
            seq = [scale[i + j] for j in range(5)] if which == 0 else [scale[i - j] for j in range(5)] if which == 1 else [start] * 5
            notes = [(j, j + 0.9, m, 76) for j, m in enumerate(seq)]
            opts = ["going up", "going down"] + (["the same"] if three else [])
            out.append(_quiz(f"q{k}", name, item["title"], opts, which, _midi(w, name, notes)))
        elif kind == "smooth-bouncy":
            notes = [(j * 0.5, j * 0.5 + (0.5 if a == 0 else 0.15), m, 72) for j, m in enumerate(_tune(rng))]
            out.append(_quiz(f"q{k}", name, item["title"], ["smooth", "bouncy"], a, _midi(w, name, notes)))
        elif kind in ("same-different", "spot-change"):
            phrase = aural.echo_phrase(rng, 1 if kind == "same-different" else 2, "C", 4)
            if kind == "same-different":
                second = phrase if a == 0 else aural.changed(rng, phrase, rng.choice(["pitch", "rhythm"]))[0]
                out.append(_quiz(f"q{k}", name, item["title"], ["the same", "different"], a,
                                 _midi(w, name, aural.twice(phrase, second))))
            else:
                second, ans = aural.changed(rng, phrase, "pitch")
                out.append(_quiz(f"q{k}", name, item["title"], ["near the beginning", "near the end"],
                                 0 if ans["where"] == "beginning" else 1, _midi(w, name, aural.twice(phrase, second))))
        elif kind == "one-many":
            root = rng.choice([48, 53, 55, 60])
            pitches = [root] if a == 0 else [root, root + 4, root + 7] + ([root + 12] if rng.random() < 0.5 else [])
            notes = [(0, 1.8, m, 80) for m in pitches] + [(2, 3.8, m, 80) for m in pitches]
            out.append(_quiz(f"q{k}", name, item["title"], ["one key", "lots together"], a, _midi(w, name, notes)))
        elif kind == "happy-sad":
            notes, answer, _ = aural.feature_passage(rng, "tonality")
            out.append(_quiz(f"q{k}", name, item["title"], ["happy (major)", "sad (minor)"], 0 if answer == "major" else 1,
                             _midi(w, name, notes)))
        elif kind == "which-higher":
            low = rng.choice([55, 57, 60, 62, 64])
            high = low + rng.choice([3, 4, 5, 7, 12])
            pair = (high, low) if a == 0 else (low, high)
            notes = [(0, 1.4, pair[0], 80), (2, 3.4, pair[1], 80)]
            out.append(_quiz(f"q{k}", name, item["title"], ["the first", "the second"], a, _midi(w, name, notes)))
        elif kind == "step-skip":
            scale = [60, 62, 64, 65, 67, 69, 71, 72]
            i = rng.randrange(0, 5)
            j = i + (1 if a == 0 else 2)
            pair = (scale[i], scale[j]) if rng.random() < 0.5 else (scale[j], scale[i])
            notes = [(0, 0.95, pair[0], 80), (1, 1.95, pair[1], 80)]
            out.append(_quiz(f"q{k}", name, item["title"], ["a step", "a skip"], a, _midi(w, name, aural.twice(notes, notes))))
        elif kind == "louder-quieter":
            line = _tune(rng, count=12)
            vel = (lambda j: 34 + 7 * j) if a == 0 else (lambda j: 112 - 7 * j)
            notes = [(j * 0.5, j * 0.5 + 0.45, m, vel(j)) for j, m in enumerate(line)]
            out.append(_quiz(f"q{k}", name, item["title"], ["getting louder", "getting quieter"], a, _midi(w, name, notes)))
        elif kind == "faster-slower":
            notes, t = [], 0.0
            for j, m in enumerate(_tune(rng, count=12)):
                step = 0.7 - 0.04 * j if a == 0 else 0.3 + 0.04 * j
                notes.append((t, t + step * 0.9, m, 76))
                t += step
            out.append(_quiz(f"q{k}", name, item["title"], ["getting faster", "getting slower"], a, _midi(w, name, notes)))
        elif kind == "march-sway":
            beats = 2 if a == 0 else 3
            notes = aural.accompanied_passage(rng, beats, bars=6)
            out.append(_quiz(f"q{k}", name, item["title"], ["marching (in twos)", "swaying (in threes)"], a,
                             _midi(w, name, notes, beats=beats)))
        elif kind == "tap-along":
            bpm = p.get("bpm", 80)
            if p.get("accompanied"):
                notes = aural.accompanied_passage(rng, rng.choice([2, 4]), bars=6)
            else:  # a plain, steady beat with a simple tune over it
                notes = [(b, b + 0.9, 48 if b % 4 == 0 else 55, 84 if b % 4 == 0 else 62) for b in range(16)]
                notes += [(b, b + 0.9, m, 70) for b, m in enumerate(_tune(rng, count=16))]
            beats = sorted({n[0] for n in notes if n[0] == int(n[0])})
            out.append({"id": f"tap-{k}", "type": "tap", "file": _midi(w, name, notes, bpm=bpm), "along": True,
                        "ref": [round(b * 60 / bpm, 4) for b in beats], "accent_every": None, "graded": True,
                        "pass": {"metric": "taps", "min": 60}})
        elif kind == "tap-echo":
            level = RHYTHM_LEVELS.index(p["level"])
            pats = [x for lv in RHYTHM_LEVELS[:level + 1] for x in RHYTHMS[lv] if not any(t.startswith("r") for t in x)]
            t, notes = 0.0, []
            for b in range(p["bars"]):
                for tok in rng.choice(pats[1:] if len(pats) > 1 else pats):
                    d = {"1": 4, "2": 2, "4": 1, "8": 0.5}[tok]
                    notes.append((t, t + d * 0.92, rng.choice([60, 64, 67]), 78))
                    t += d
            out.append({"id": f"tap-{k}", "type": "tap", "file": _midi(w, name, notes, bpm=76), "along": False,
                        "ref": [round(n[0] * 60 / 76, 4) for n in notes], "graded": True, "pass": {"metric": "taps", "min": 60}})
        elif kind == "sing":
            pool, length = p["notes"], p.get("length", 3)
            seq = [pool[0]] + [rng.choice(pool) for _ in range(length - 1)]
            if len(set(seq)) == 1:
                seq[-1] = pool[1]
            notes = [(j, j + 0.9, m, 80) for j, m in enumerate(seq)]
            out.append({"id": f"sing-{k}", "type": "sing", "file": _midi(w, name, notes, bpm=72), "ref": seq, "keyboard_ok": True,
                        "graded": True, "pass": {"metric": "pitch", "min": 60}})
        else:
            raise ValueError(f"Unknown game {kind}")
    return out


# -- writing it all --------------------------------------------------------------------------------

def _items(table: dict) -> dict[str, dict]:
    return {i["key"]: i for tid in OURS for _, _, items in table[tid] for i in items}


def write_lessons(atlas: dict | None = None, lessons: pathlib.Path | None = None, pool_count: int = 8, lint: bool = True) -> dict:
    """Write every lesson of both tiers, and their music, into <content>/lessons."""
    from . import load_atlas

    atlas = atlas or load_atlas()
    by_id = atlas.get("by_id") or {n["id"]: n for n in atlas["nodes"]}
    lessons = pathlib.Path(lessons) if lessons else content_dir() / "lessons"
    for sub in ("first", "sight", "aural"):
        (lessons / sub).mkdir(parents=True, exist_ok=True)
    for old in (lessons / "first").glob("*.musicxml"):  # every sheet here is written below
        old.unlink()
    w = Writer(lessons, lint=lint)
    exercises, topics, sights, games = _items(TECHNIQUE), _items(THEORY), _items(SIGHT), _items(AURAL)
    tune_by = {t["id"]: t for t in tunes()}
    files: dict[str, str] = {}
    for req in atlas["nodes"]:
        if req["level"] != "requirement" or req["tier"] not in OURS:
            continue
        key = req["id"].rsplit(".", 1)[-1]
        young = req["tier"] == FIRST
        for sid in req["stages"]:
            stage = by_id[sid]
            if req["kind"] == "theory":
                t = topics[key]
                steps = [{"id": "read", "type": "read", "text": t["text"]}]
                steps += [{"id": f"quiz-{k}", "type": "quiz", "prompt": q, "options": o, "answer": a, "graded": True, "explain": why}
                          for k, (q, o, a, why) in enumerate(t["quizzes"], 1)]
            elif req["kind"] == "notes":
                e = exercises[key]
                if key not in files:
                    files[key] = w.score("first", key, f"{TITLES[req['tier']]} · {e['title']}", e["right"], e["left"], bpm=e["tempo"],
                                         rf=fingers(e["right"], e["rf"], "right"), lf=fingers(e["left"], e["lf"], "left"),
                                         letters=young and not re.search(r"#", (e["right"] or "") + (e["left"] or "")),
                                         staccato=bool(e["marks"].get("staccato")), dynamics=e["marks"].get("dynamics"))
                steps = _play_steps(stage, files[key], _say(e))
            elif req["kind"] == "piece":
                t = tune_by[key]
                if key not in files:
                    files[key] = w.score("first", key, t["title"], t.get("right"), t.get("left"), t["time"], t["key"], t["tempo"],
                                         rf=fingers(t.get("right"), t.get("rh"), "right", t["time"]),
                                         lf=fingers(t.get("left"), t.get("lh"), "left", t["time"]),
                                         letters=young and t.get("letters", True))
                steps = _play_steps(stage, files[key], f"{t['title']} ({t['composer']}). {t['text']}")
            elif req["kind"] == "sight":
                s = sights[key]
                st = stage["stage"]
                rule = LEARN_PASS if st["mode"] == "learn" else PLAY_PASS
                steps = [{"id": "read", "type": "read", "text": f"{st['title']}. {s['text']}" + (LEARN_SAYS if st["mode"] == "learn" else PLAY_SAYS)},
                         {"id": "play", "type": "play", "pool": f"sight/{req['tier']}-{key}-", "hand": "both", "mode": st["mode"],
                          "tempo_percent": st["tempo_percent"], "graded": True, "pass": rule}]
            elif req["kind"] == "aural":
                g = games[key]
                steps = [{"id": "read", "type": "read", "text": g["text"]}] + game_items(w, g, sid, random.Random(f"first-steps:{sid}"))
            else:
                continue
            w.lesson(_lesson(stage, req, steps))
    write_pools(w, pool_count)
    return w.report


START_GOAL = "first-steps"


def start_goal() -> str | None:
    """A young learner's first goal: Ready to read (so the Path starts at First steps), set
    active when the profile has no goal of its own yet. Returns its id, or None if there are
    goals already or no built Atlas with these tiers."""
    from . import load_atlas, mastery, store

    goals = store.load_goals()
    if any(g["status"] == "active" for g in goals["goals"]):
        return None
    try:
        atlas = load_atlas()
    except OSError:
        return None
    if f"{READY}.review" not in atlas["by_id"]:
        return None
    families = mastery.path_families(atlas, store.progress(atlas), [f"{READY}.review"])
    goals["goals"] = [g for g in goals["goals"] if g["id"] != START_GOAL]
    goals["goals"].append({"id": START_GOAL, "title": TITLES[READY], "kind": "grade", "targets": [f"{READY}.review"],
                           "families": [f["family"] for f in families], "first": [], "bridges": [], "status": "active",
                           "created": store.now(), "source": "young learner"})
    goals["active"] = START_GOAL
    store.save_goals(goals)
    return START_GOAL


def main(argv: list[str] | None = None) -> None:
    from . import build, load_atlas

    args = list(sys.argv[1:] if argv is None else argv)
    if "--no-build" not in args:
        build.main([a for a in args if a != "--no-build"])
    from . import familiar

    atlas = load_atlas()
    report = write_lessons(atlas)
    print(f"First steps and Ready to read: {report['lessons']} lessons, {report['scores']} scores")
    for p in report["problems"]:
        print("  problem:", p)
    familiar.main(atlas=atlas)


if __name__ == "__main__":
    main()
