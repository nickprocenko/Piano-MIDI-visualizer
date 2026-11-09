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

A key still held when the next chord starts keeps its finger busy: the path's state is every key
down and its finger, so no finger is ever on two keys at once, and the new keys must fit the hand
around the held ones. Letting a held key go early (the pedal holds it) is allowed at a price, for
a hand that can't reach. Past a fifth the hand may shift instead, and a shift costs how far the
whole hand travels, so a bass note before a jump up takes the little finger and the thumb lands
on the top.

The left hand is the right hand in a mirror: a pitch p is fingered as 124 - p (the keyboard is
symmetric about D, so black keys stay black).

This is a teaching suggestion, not an edition's fingering: it never changes a note.
"""

from __future__ import annotations

from bisect import bisect_right
from functools import lru_cache
from itertools import combinations

from .notes import HOLD_WINDOW  # a key down longer than this rings on the pedal (as the hand split takes it)

BLACK = {1, 3, 6, 8, 10}
CHORD_TOL = 0.03  # seconds: notes starting this close together are one chord
FREE_AFTER = 1.0  # seconds of rest after which the hand can be anywhere
MIRROR = 124  # left hand: p -> 124 - p, about D4 (62)
HELD_AFTER = 0.08  # seconds: a key still down this long after the next chord starts is held (less is legato overlap)
# Letting a held key go before its time, per key: RELEASE plus RELEASE_PER_SEC for each second
# cut short, up to RELEASE_MAX, times RELEASE_PEDAL with the sustain pedal down; only
# RELEASE_FREE when it rings anyway (down longer than HOLD_WINDOW, or RINGING keys held at once:
# a broken chord left to ring)
RELEASE = 6.0
RELEASE_PER_SEC = 5.0
RELEASE_MAX = 30.0
RELEASE_PEDAL = 0.5
RELEASE_FREE = 0.5
RINGING = 3
SAME_FINGER = 10.0  # one finger on two keys in a row: the hand must let go and move between them
LEAP_FROM = 7  # semitones: past a fifth the whole hand may shift instead of stretching or crossing
LEAP = 7.0  # a leap, plus LEAP_STEP per semitone the hand travels
LEAP_STEP = 0.5
BEAM = 64  # hand states kept per chord
# where each finger sits in a hand at rest on five white keys (C D E F G), in semitones from the thumb
OFFSET = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7}

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
def pair_cost(f1: int, p1: int, f2: int, p2: int, chord: bool = False, shift: bool = False, hold: bool = False) -> float:
    """What it costs a right hand to have finger f1 on p1 and f2 on p2 (together in a chord,
    or one after the other; shift: the outer keys of one chord moving to the next; hold: f1
    keeps a key down while f2 plays, free within a comfortable stretch)."""
    chord = chord or hold
    if f1 == f2:
        if p1 == p2:
            return 0.0 if not chord else 50.0
        if chord:
            return 50.0
        if shift:
            return 0.5 + abs(p2 - p1) * 0.3  # the whole hand moves with its chord
        if abs(p2 - p1) > LEAP_FROM:
            return leap_cost(f1, p1, f2, p2)
        return SAME_FINGER + abs(p2 - p1) * 0.5  # one finger, two keys
    if f1 > f2:  # always read from the lower finger
        f1, p1, f2, p2 = f2, p2, f1, p1
    d = p2 - p1
    min_prac, min_comf, min_rel, max_rel, max_comf, max_prac = SPANS[(f1, f2)]
    thumb = f1 == 1
    # one key after the other, wider than a fifth: the hand may leap instead of stretching
    leap = leap_cost(f1, p1, f2, p2) if not chord and not shift and abs(d) > LEAP_FROM else float("inf")
    if d < 0 and thumb and not chord:
        # thumb under a finger, or a finger over the thumb: a fixed price, so a scale crosses
        # as seldom as it can (after 3 and 4, not after every 2), and more for a wide one
        return min(leap, 4.0 + 0.5 * -d + (10.0 * (min_prac - d) if d < min_prac else 0.0)
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
    if hold:
        pass  # a held key: only discomfort counts, not leaving the relaxed hand shape
    elif d > max_rel:
        cost += (1.0 if thumb else 2.0) * (d - max_rel)
    elif d < min_rel:
        cost += (2.0 if thumb else 1.0) * (min_rel - d)
    if d < 0 and not thumb:
        cost += 8.0  # crossing two long fingers
    if d < 0 and thumb:
        cost += 20.0  # no thumb under a finger while both are down
    return min(cost, leap)


def leap_cost(f1: int, p1: int, f2: int, p2: int) -> float:
    """The hand leaps from finger f1 on p1 to f2 on p2: what counts is how far the whole hand
    travels (the thumb's place before and after), not which fingers stretch."""
    return LEAP + LEAP_STEP * abs((p2 - OFFSET[f2]) - (p1 - OFFSET[f1]))


def _thumb_at(pitches: tuple[int, ...], fingers: tuple[int, ...]) -> float:
    """Where a hand playing these keys with these fingers has its thumb, give or take."""
    return sum(p - OFFSET[f] for p, f in zip(pitches, fingers)) / len(pitches)


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


@lru_cache(maxsize=None)
def _options(pitches: tuple[int, ...], held: tuple[tuple[int, int], ...]) -> tuple[tuple[tuple[int, ...], float], ...]:
    """Every way to finger a chord's new keys (pitches, low to high) around the keys still held
    ((pitch, finger)...): a free finger each, in order across the hand with the held ones, as
    ((fingers, cost)...). The cost is the chord's own plus each held key with each new one."""
    used = {f for _, f in held}
    out = []
    for fingers in combinations([f for f in range(1, 6) if f not in used], len(pitches)):
        down = sorted(list(zip(pitches, fingers)) + list(held))
        if any(a[1] >= b[1] for a, b in zip(down, down[1:])):
            continue  # fingers crossed over a held key
        cost = _chord_cost(pitches, fingers)
        for hp, hf in held:
            for p, f in zip(pitches, fingers):
                cost += pair_cost(hf, hp, f, p, hold=True)
        out.append((fingers, cost))
    return tuple(out)


def _keep_options(held: dict[int, int]) -> list[dict[int, int]]:
    """Which held keys stay down: all of them, none (let go, the pedal holds them), or, with
    several held, any few (just one of them once there are more than three)."""
    if not held:
        return [{}]
    keys = sorted(held)
    if len(keys) <= 3:
        picks = [c for k in range(len(keys), -1, -1) for c in combinations(keys, k)]
    else:
        picks = [tuple(keys), ()] + [(k,) for k in keys]
    return [{k: held[k] for k in pick} for pick in picks]


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
    elif abs(sum(b) / len(b) - sum(a) / len(a)) > LEAP_FROM:  # to or from a chord, the hand leaps
        cost = LEAP + LEAP_STEP * abs(_thumb_at(b, fb) - _thumb_at(a, fa))
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


def _pedal_down(pedal: list[tuple[float, float]], t: float) -> bool:
    k = bisect_right(pedal, (t, float("inf"))) - 1
    return k >= 0 and pedal[k][0] <= t < pedal[k][1]


def finger_hand(seq: list[tuple], mirrored: bool = False, pedal: list[tuple[float, float]] | None = None) -> list[int | None]:
    """Fingers for one hand's notes, [(start seconds, pitch)] or [(start, pitch, end)] in any
    order, aligned with seq. Without an end a note is let go when the next one starts.
    mirrored: a left hand. pedal: [(down, up) seconds] of the sustain pedal, sorted."""
    pedal = pedal or []
    order = sorted(range(len(seq)), key=lambda i: (seq[i][0], seq[i][1]))
    items = [(seq[i][0], (MIRROR - seq[i][1]) if mirrored else seq[i][1], i) for i in order]
    groups = [(t, _five(notes)) for t, notes in _groups(items)]
    result: list[int | None] = [None] * len(seq)
    if not groups:
        return result
    ends = [s[2] if len(s) > 2 else s[0] for s in seq]
    pitch_of = {i: p for _, notes in groups for p, i in notes}
    # Viterbi over chords. A state is every key down just after a chord, with its finger:
    # ((index, finger)...) sorted. Each holds (cost, the state before, the chord's fingers).
    states: dict[tuple, tuple[float, tuple | None, tuple[int, ...]]] = {(): (0.0, None, ())}
    layers = []
    prev_t, prev_new = None, ()
    for t, notes in groups:
        pitches = tuple(p for p, _ in notes)
        new = tuple(i for _, i in notes)
        gap = t - prev_t if prev_t is not None else FREE_AFTER
        nxt: dict[tuple, tuple[float, tuple | None, tuple[int, ...]]] = {}
        for key, (cost0, _, _) in states.items():
            down = dict(key)
            # still held: down past this chord's start, and not the same key struck again
            held = {i: f for i, f in down.items() if ends[i] > t + HELD_AFTER and pitch_of[i] not in pitches}
            ringing, pedalled = len(held) >= RINGING, bool(held) and _pedal_down(pedal, t)
            release = {i: RELEASE_FREE if ringing or t - seq[i][0] > HOLD_WINDOW
                       else min(RELEASE_MAX, RELEASE + RELEASE_PER_SEC * (ends[i] - t)) * (RELEASE_PEDAL if pedalled else 1.0)
                       for i in held}
            for keep in _keep_options(held):
                # the hand moves from the last chord's keys it lets go of (or, if it holds them
                # all, from nothing: the held keys place it)
                gone = sorted((pitch_of[i], f) for i, f in down.items() if i in prev_new and i not in keep)
                base = cost0 + sum(c for i, c in release.items() if i not in keep)
                held_keys = tuple(sorted((pitch_of[i], f) for i, f in keep.items()))
                for fingers, own in _options(pitches, held_keys):
                    c = base + own
                    if gone:
                        c += _move_cost(tuple(p for p, _ in gone), tuple(f for _, f in gone), pitches, fingers, gap)
                    nkey = tuple(sorted(list(keep.items()) + list(zip(new, fingers))))
                    if c < nxt.get(nkey, (float("inf"),))[0]:
                        nxt[nkey] = (c, key, fingers)
        if len(nxt) > BEAM:
            nxt = dict(sorted(nxt.items(), key=lambda kv: kv[1][0])[:BEAM])
        layers.append(nxt)
        states, prev_t, prev_new = nxt, t, new
    # trace back
    key = min(states, key=lambda k: states[k][0])
    for gi in range(len(groups) - 1, -1, -1):
        _, back, fingers = layers[gi][key]
        for (_, idx), f in zip(groups[gi][1], fingers):
            result[idx] = f
        key = back
    # a duplicate key in a chord takes its twin's finger
    by_key: dict[tuple[float, int], int] = {}
    for i, f in enumerate(result):
        if f is not None:
            by_key[(round(seq[i][0], 3), seq[i][1])] = f
    for i, f in enumerate(result):
        if f is None:
            result[i] = by_key.get((round(seq[i][0], 3), seq[i][1]))
    return result


def finger_notes(notes, side, pedal: list[tuple[float, float]] | None = None) -> dict[int, int]:
    """{id(note): finger} for the notes side(note) gives to 'right' or 'left' (others get none).
    pedal: [(down, up) seconds] of the sustain pedal."""
    out: dict[int, int] = {}
    for hand in ("right", "left"):
        mine = [n for n in notes if side(n) == hand]
        fingers = finger_hand([(n.start, n.pitch, n.end) for n in mine], mirrored=hand == "left", pedal=pedal)
        for n, f in zip(mine, fingers):
            if f is not None:
                out[id(n)] = f
    return out


def score_fingers(score) -> dict[tuple[float, int], tuple[str, int]]:
    """{(start rounded to 4 places, pitch): (hand, finger)} for a piano score's hand notes, the
    same for the falling notes and the coach. Empty for a named part (flute, voice...)."""
    from .analysis import side_resolver
    from .notes import HAND_ROLES, effective_roles, pedal_intervals, playable_parts

    if getattr(score, "playing", None):
        return {}
    roles = effective_roles(score) or {p.index: "both" for p in playable_parts(score)}
    side = side_resolver(score)
    hand_notes = [n for n in score.notes if roles.get(n.part) in HAND_ROLES]
    sides = {id(n): side(n) for n in hand_notes}
    pedal = sorted(pedal_intervals(score.pedal, score.duration)) if getattr(score, "pedal", None) else []
    fingers = finger_notes(hand_notes, lambda n: sides[id(n)], pedal)
    return {(round(n.start, 4), n.pitch): (sides[id(n)], fingers[id(n)]) for n in hand_notes if id(n) in fingers}


HAND_WORDS = {"right": "right hand", "left": "left hand"}


def correction(note_name: str, hand: str, finger: int) -> str:
    """The coach's spoken correction: 'Right hand, finger 3 on E.'"""
    return f"{HAND_WORDS.get(hand, hand).capitalize()}, finger {finger} on {note_name}."
