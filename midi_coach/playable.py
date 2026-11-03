"""Clean: make the parts you play fit two hands.

A band arrangement often asks the hands for more than they can do: an organ part doubles
the bass line an octave up while it plays the riff, so one hand would need B2 and D5 at
once; two parts play the same key at the same moment; a file has a note written twice.
Clean (Maestro → This sheet) finds every chord a hand can't play and changes as little as
it can, chord by chord:

  1. a key sounded twice at once (two parts, or the file twice) is played once, by the hand
     it sits best in;
  2. a hand's chord wider than HAND_REACH (a ninth) hands its inner notes (the right hand's
     lowest, the left hand's highest) to the other hand, when that hand can take them;
  3. a chord still wider than WIDEST (a tenth) leaves notes out: first those doubling
     another note of the chord an octave away, then the ones out of reach of the hand's outer
     note (the tune on top of the right hand and the bass under the left stay);
  4. a hand with more than MOST_NOTES notes at once leaves out its octave doublings.

It's the user's choice per file (saved with the part choice, see library.playable_chosen)
and undone by the same button. The sheet, the falling notes and the grading all read the
cleaned notes, the sheet records the changes in <identification><source>, and every change
is listed by bar.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from .notes import CHORD_GAP, HAND_REACH, MIDI_SUFFIXES, Note, Score, note_name, octave_up_parts, select_notes

VERSION = 1  # bump when plan() changes, so cleaned sheets are written again
MOST_NOTES = 5  # keys one hand plays at once
WIDEST = 16  # semitones, a tenth: a stretch for one hand, but playable; wider chords lose notes


def _key(n: Note, up: set[int]) -> tuple[int, float, int]:
    """A note of the file, whether given as the file has it or as played (a bass part an
    octave up, notes.as_played)."""
    return n.part, round(n.start, 4), n.pitch - 12 * (n.part in up)


def plan(score: Score) -> dict:
    """What Clean would change: {"drop": Counter of note keys, "move": {note key: hand},
    "changes": [{bar, beat, note, kind, change, why}]} in time order; kind is 'twice' (a
    key sounded twice), 'moved' (to the other hand), 'reach' or 'crowded' (left out)."""
    from .analysis import side_resolver

    notes, _ = select_notes(score, "both")
    side = side_resolver(score)
    up = octave_up_parts(score)
    chords: list[list[Note]] = []
    for n in sorted(notes, key=lambda n: (n.start, n.pitch)):
        if chords and n.start - chords[-1][0].start <= CHORD_GAP:
            chords[-1].append(n)
        else:
            chords.append([n])
    drop: Counter = Counter()
    move: dict[tuple, str] = {}
    changes: list[dict] = []

    def note(n: Note, kind: str, why: str) -> None:
        bar, beat = score.position(n.start)
        change = f"moved to the {hand[id(n)]} hand" if kind == "moved" else "left out"
        changes.append({"bar": bar, "beat": beat, "note": note_name(n.pitch), "kind": kind, "change": change, "why": why})

    for chord in chords:
        hand = {id(n): side(n) for n in chord}
        live = list(chord)

        def mine(s: str) -> list[Note]:
            return sorted((n for n in live if hand[id(n)] == s), key=lambda n: n.pitch)

        def leave_out(n: Note, kind: str, why: str) -> None:
            live.remove(n)
            drop[_key(n, up)] += 1
            note(n, kind, why)

        # 1. The same key twice: keep the copy whose hand's other notes are nearest it.
        for pitch, copies in _by_pitch(live).items():
            if len(copies) < 2:
                continue

            def fit(n: Note) -> tuple:
                others = [m.pitch for m in live if hand[id(m)] == hand[id(n)] and m.pitch != pitch]
                return (min((abs(p - pitch) for p in others), default=0), -n.duration)

            keep = min(copies, key=fit)
            for n in copies:
                if n is not keep:
                    leave_out(n, "twice", f"{note_name(pitch)} is already played {'by the other hand' if hand[id(n)] != hand[id(keep)] else 'here'}")

        # 2-4. Each hand within reach, with at most MOST_NOTES keys.
        for s, other in (("right", "left"), ("left", "right")):
            while True:
                here = mine(s)
                if len(here) < 2:
                    break
                outer, inner = (here[-1], here[0]) if s == "right" else (here[0], here[-1])
                span = here[-1].pitch - here[0].pitch
                if span <= HAND_REACH and len(here) <= MOST_NOTES:
                    break
                doubled = [n for n in here if n is not outer and any(m is not n and m.pitch % 12 == n.pitch % 12 for m in live)]
                if span > HAND_REACH:
                    theirs = [n.pitch for n in mine(other)] + [inner.pitch]
                    if max(theirs) - min(theirs) <= HAND_REACH and len(theirs) <= MOST_NOTES:
                        hand[id(inner)] = other
                        move[_key(inner, up)] = other
                        note(inner, "moved", f"the {s} hand can't reach it from {note_name(outer.pitch)}")
                        continue
                    if span > WIDEST:
                        far = [n for n in doubled if abs(n.pitch - outer.pitch) > WIDEST] or [inner]
                        n = max(far, key=lambda n: abs(n.pitch - outer.pitch))
                        leave_out(n, "reach", f"doubles {_letter(n)} an octave away" if n in doubled
                                  else f"out of the {s} hand's reach from {note_name(outer.pitch)}")
                        continue
                    if len(here) <= MOST_NOTES:
                        break  # a tenth at most: a stretch, but it can be played
                if not doubled:
                    break  # too many notes, none of them doublings: leave the chord as written
                n = max(doubled, key=lambda n: abs(n.pitch - outer.pitch))
                leave_out(n, "crowded", f"doubles {_letter(n)} an octave away, in a hand playing {len(here)} notes at once")
    return {"drop": drop, "move": move, "changes": changes}


def _letter(n: Note) -> str:
    """The note's name without its octave: 'F#'."""
    return note_name(n.pitch).rstrip("-0123456789")


def _by_pitch(notes: list[Note]) -> dict[int, list[Note]]:
    out: dict[int, list[Note]] = {}
    for n in notes:
        out.setdefault(n.pitch, []).append(n)
    return out


def apply(score: Score) -> Score:
    """The score with Clean's changes: notes left out, notes handed to the other hand
    (Note.hand). score.clean holds the list of changes and a summary."""
    found = plan(score)
    drop, move = Counter(found["drop"]), found["move"]
    notes = []
    for n in score.notes:
        k = _key(n, set())  # the file's own note, not as played
        if drop[k] > 0:
            drop[k] -= 1
            continue
        notes.append(replace(n, hand=move[k]) if k in move else n)
    clean = {"version": VERSION, "changes": found["changes"], "summary": summary(found["changes"])}
    return replace(score, notes=notes, clean=clean, _sides=score._sides)


def unplayable_bars(score: Score) -> list[int]:
    """The bars where a hand is asked for something it can't play (what Clean would change)."""
    if not str(score.path).lower().endswith(tuple(MIDI_SUFFIXES)):
        return []
    return sorted({c["bar"] for c in plan(score)["changes"]})


def _bars_text(bars: list[int]) -> str:
    """'bar 4', 'bars 4, 9 and 12', or 'bars 4-7, 9 and 12-20'."""
    runs: list[list[int]] = []
    for b in sorted(set(bars)):
        if runs and b == runs[-1][1] + 1:
            runs[-1][1] = b
        else:
            runs.append([b, b])
    parts = [f"{a}" if a == b else f"{a}-{b}" for a, b in runs]
    if len(parts) > 6:
        parts = parts[:5] + [f"{len(parts) - 5} more places"]
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return ("bar " if len(runs) == 1 and runs[0][0] == runs[0][1] else "bars ") + text


def summary(changes: list[dict]) -> str:
    """One line for the page: what Clean changed, and where."""
    if not changes:
        return "Both hands can already play every note."
    kinds = Counter(c["kind"] for c in changes)
    once, moved, left = kinds["twice"], kinds["moved"], kinds["reach"] + kinds["crowded"]
    said = []
    if once:
        said.append(f"{once} note{'s' * (once != 1)} sounding twice now played once")
    if moved:
        said.append(f"{moved} handed to the other hand")
    if left:
        said.append(f"{left} out of reach or doubling an octave left out")
    text = "; ".join(said)
    return text[0].upper() + text[1:] + f" ({_bars_text([c['bar'] for c in changes])})."
