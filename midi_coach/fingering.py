"""Piano fingering: a finger number (1 = thumb ... 5 = little finger) for every note a hand plays.

Learn mode's falling notes print it on each note and the animated hands play with it
(static/roll.js); the coach names the finger when you keep pressing the wrong key (live.py).

Each hand is fingered on its own by dynamic programming over its chords (notes starting
together), the way Parncutt et al. (1997) and Hart, Bosch & Tsai (2000) do it: every chord gets
an ordered set of fingers, and the cheapest path through the piece wins. Costs come from how far
each pair of fingers comfortably reaches (Parncutt's span table), with extra for a thumb on a
black key, crossing fingers other than over or under the thumb, the same finger on two keys in a
row, and the weak fourth finger. A rest lets the hand move freely, so the cost of a jump fades
with the time between the chords.

The left hand is the right hand in a mirror: a pitch p is fingered as 124 - p (the keyboard is
symmetric about D, so black keys stay black).

This is a teaching suggestion, not an edition's fingering: it never changes a note.
"""

from __future__ import annotations

from functools import lru_cache
from itertools import combinations

BLACK = {1, 3, 6, 8, 10}
CHORD_TOL = 0.03  # seconds: notes starting this close together are one chord
FREE_AFTER = 1.0  # seconds of rest after which the hand can be anywhere
MIRROR = 124  # left hand: p -> 124 - p, about D4 (62)

# Parncutt's span table for the right hand, in semitones from the lower finger's key to the
# higher finger's: (MinPrac, MinComf, MinRel, MaxRel, MaxComf, MaxPrac).
SPANS = {
    (1, 2): (-5, -3, 1, 5, 8, 10),
    (1, 3): (-4, -2, 3, 7, 10, 12),
    (1, 4): (-3, -1, 5, 9, 12, 14),
    (1, 5): (-1, 1, 7, 10, 13, 15),
    (2, 3): (1, 1, 1, 2, 3, 5),
    (2, 4): (1, 1, 3, 4, 5, 7),
    (2, 5): (2, 2, 5, 6, 8, 10),
    (3, 4): (1, 1, 1, 2, 2, 4),
    (3, 5): (1, 1, 3, 4, 5, 7),
    (4, 5): (1, 1, 1, 2, 3, 5),
}


def is_black(pitch: int) -> bool:
    return pitch % 12 in BLACK


@lru_cache(maxsize=None)
def pair_cost(f1: int, p1: int, f2: int, p2: int, chord: bool = False, shift: bool = False) -> float:
    """What it costs a right hand to have finger f1 on p1 and f2 on p2 (together in a chord,
    or one after the other; shift: the outer keys of one chord moving to the next)."""
    if f1 == f2:
        if p1 == p2:
            return 0.0 if not chord else 50.0
        if chord:
            return 50.0
        if shift:
            return 0.5 + abs(p2 - p1) * 0.3  # the whole hand moves with its chord
        return 6.0 + abs(p2 - p1) * 0.5  # one finger, two keys
    if f1 > f2:  # always read from the lower finger
        f1, p1, f2, p2 = f2, p2, f1, p1
    d = p2 - p1
    min_prac, min_comf, min_rel, max_rel, max_comf, max_prac = SPANS[(f1, f2)]
    thumb = f1 == 1
    if d < 0 and thumb and not chord:
        # thumb under a finger, or a finger over the thumb: a fixed price, so a scale crosses
        # as seldom as it can (after 3 and 4, not after every 2), and more for a wide one
        return (4.0 + 0.5 * -d + (10.0 * (min_prac - d) if d < min_prac else 0.0)
                + (12.0 if f2 == 5 else 0.0))  # never under the little finger
    cost = 0.0
    if d > max_comf:
        cost += 2.0 * (d - max_comf)
    elif d < min_comf:
        cost += 2.0 * (min_comf - d)
    if d > max_prac:
        cost += 10.0 * (d - max_prac)
    elif d < min_prac:
        cost += 10.0 * (min_prac - d)
    if d > max_rel:
        cost += (1.0 if thumb else 2.0) * (d - max_rel)
    elif d < min_rel:
        cost += (2.0 if thumb else 1.0) * (min_rel - d)
    if d < 0 and not thumb:
        cost += 8.0  # crossing two long fingers
    if d < 0 and thumb:
        cost += 20.0  # no thumb under a finger while both are down
    return cost


def key_cost(finger: int, pitch: int) -> float:
    """A finger on its own key: thumbs and little fingers prefer white keys."""
    cost = 0.0
    if is_black(pitch):
        if finger == 1:
            cost += 4.5
        elif finger == 5:
            cost += 1.0
    if finger == 4:
        cost += 0.3  # the weak finger, used when it helps
    return cost


def _assignments(k: int) -> list[tuple[int, ...]]:
    return list(combinations(range(1, 6), k))


def _chord_cost(pitches: tuple[int, ...], fingers: tuple[int, ...]) -> float:
    cost = sum(key_cost(f, p) for f, p in zip(fingers, pitches))
    for i in range(len(pitches)):
        for j in range(i + 1, len(pitches)):
            cost += pair_cost(fingers[i], pitches[i], fingers[j], pitches[j], True)
    return cost


def _move_cost(a: tuple[int, ...], fa: tuple[int, ...], b: tuple[int, ...], fb: tuple[int, ...], gap: float) -> float:
    """From chord a (pitches, fingers) to chord b, gap seconds later."""
    if len(a) == 1 and len(b) == 1:
        cost = pair_cost(fa[0], a[0], fb[0], b[0])
    else:  # a chord: its outer fingers lead the hand
        cost = (pair_cost(fa[0], a[0], fb[0], b[0], shift=True) + pair_cost(fa[-1], a[-1], fb[-1], b[-1], shift=True)) / 2
    # 3-4 and 4-5 one after the other on neighbouring keys is fine; 3 to 4 over a leap is not
    if len(a) == len(b) == 1 and {fa[0], fb[0]} in ({3, 4}, {4, 5}) and abs(b[0] - a[0]) > 2:
        cost += 1.0
    fade = max(0.0, 1.0 - gap / FREE_AFTER)
    return cost * (0.15 + 0.85 * fade)


def _groups(seq: list[tuple[float, int, int]]) -> list[tuple[float, list[tuple[int, int]]]]:
    """[(start, pitch, index)] sorted -> [(onset, [(pitch, index)...] sorted by pitch)]."""
    out: list[tuple[float, list[tuple[int, int]]]] = []
    for start, pitch, idx in seq:
        if out and start - out[-1][0] <= CHORD_TOL:
            out[-1][1].append((pitch, idx))
        else:
            out.append((start, [(pitch, idx)]))
    for _, notes in out:
        notes.sort()
        # a key sounded twice at once is played once: drop duplicates of one pitch
        seen, uniq = set(), []
        for p, i in notes:
            if p not in seen:
                seen.add(p)
                uniq.append((p, i))
        notes[:] = uniq
    return out


def _five(notes: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """A chord of more than five keys in one hand: the five a hand can take (lowest, highest,
    and three spread between); the rest go unfingered."""
    if len(notes) <= 5:
        return notes
    n = len(notes)
    pick = sorted({0, n - 1, round((n - 1) * 0.25), round((n - 1) * 0.5), round((n - 1) * 0.75)})
    return [notes[i] for i in pick]


def finger_hand(seq: list[tuple[float, int]], mirrored: bool = False) -> list[int | None]:
    """Fingers for one hand's notes, [(start seconds, pitch)] in any order, aligned with seq.
    mirrored: a left hand."""
    order = sorted(range(len(seq)), key=lambda i: (seq[i][0], seq[i][1]))
    items = [(seq[i][0], (MIRROR - seq[i][1]) if mirrored else seq[i][1], i) for i in order]
    groups = [(t, _five(notes)) for t, notes in _groups(items)]
    result: list[int | None] = [None] * len(seq)
    if not groups:
        return result
    # Viterbi over chords
    prev_states: list[tuple[int, ...]] = []
    prev_cost: list[float] = []
    back: list[list[int]] = []
    prev_pitches: tuple[int, ...] = ()
    prev_t = 0.0
    for gi, (t, notes) in enumerate(groups):
        pitches = tuple(p for p, _ in notes)
        states = _assignments(len(pitches))
        own = [_chord_cost(pitches, s) for s in states]
        if gi == 0:
            cost = own
            back.append([-1] * len(states))
        else:
            gap = t - prev_t
            cost, ptr = [], []
            for s, c0 in zip(states, own):
                best, arg = float("inf"), 0
                for j, (ps, pc) in enumerate(zip(prev_states, prev_cost)):
                    c = pc + _move_cost(prev_pitches, ps, pitches, s, gap)
                    if c < best:
                        best, arg = c, j
                cost.append(best + c0)
                ptr.append(arg)
            back.append(ptr)
        prev_states, prev_cost, prev_pitches, prev_t = states, cost, pitches, t
    # trace back
    k = min(range(len(prev_cost)), key=prev_cost.__getitem__)
    for gi in range(len(groups) - 1, -1, -1):
        notes = groups[gi][1]
        states = _assignments(len(notes))
        for (p, idx), f in zip(notes, states[k]):
            result[idx] = f
        k = back[gi][k]
    # a duplicate key in a chord takes its twin's finger
    by_key: dict[tuple[float, int], int] = {}
    for i, f in enumerate(result):
        if f is not None:
            by_key[(round(seq[i][0], 3), seq[i][1])] = f
    for i, f in enumerate(result):
        if f is None:
            result[i] = by_key.get((round(seq[i][0], 3), seq[i][1]))
    return result


def finger_notes(notes, side) -> dict[int, int]:
    """{id(note): finger} for the notes side(note) gives to 'right' or 'left' (others get none)."""
    out: dict[int, int] = {}
    for hand in ("right", "left"):
        mine = [n for n in notes if side(n) == hand]
        fingers = finger_hand([(n.start, n.pitch) for n in mine], mirrored=hand == "left")
        for n, f in zip(mine, fingers):
            if f is not None:
                out[id(n)] = f
    return out


def score_fingers(score) -> dict[tuple[float, int], tuple[str, int]]:
    """{(start rounded to 4 places, pitch): (hand, finger)} for a piano score's hand notes, the
    same for the falling notes and the coach. Empty for a named part (flute, voice...)."""
    from .analysis import side_resolver
    from .notes import HAND_ROLES, effective_roles, playable_parts

    if getattr(score, "playing", None):
        return {}
    roles = effective_roles(score) or {p.index: "both" for p in playable_parts(score)}
    side = side_resolver(score)
    hand_notes = [n for n in score.notes if roles.get(n.part) in HAND_ROLES]
    sides = {id(n): side(n) for n in hand_notes}
    fingers = finger_notes(hand_notes, lambda n: sides[id(n)])
    return {(round(n.start, 4), n.pitch): (sides[id(n)], fingers[id(n)]) for n in hand_notes if id(n) in fingers}


HAND_WORDS = {"right": "right hand", "left": "left hand"}


def correction(note_name: str, hand: str, finger: int) -> str:
    """The coach's spoken correction: 'Right hand, finger 3 on E.'"""
    return f"{HAND_WORDS.get(hand, hand).capitalize()}, finger {finger} on {note_name}."
