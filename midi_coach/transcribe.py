"""Turn what you played into sheet music.

A take is quantized to a beat grid (the metronome's tempo and the downbeat after its
count-in), split between the hands by register (notes.split_hands), and written as a
two-staff MusicXML lesson.
Each beat is snapped to sixteenths or, when that fits clearly better, to triplets.
Within a hand, notes starting together become a chord that lasts until the hand's next
chord, so held notes under a moving line are shortened: the result is a readable
sketch of what was played, not an engraving.
"""

from __future__ import annotations

import math
import time
from fractions import Fraction

from .notes import Note, split_hands

STRAIGHT = Fraction(1, 4)  # sixteenths
TRIPLET = Fraction(1, 3)  # triplet eighths
EARLY_OK = Fraction(1, 2)  # notes up to half a beat before the downbeat still count (anticipation)


def _snap(x: Fraction, step: Fraction) -> Fraction:
    return Fraction(round(x / step)) * step


def _beat_grids(beats: list[Fraction], triplets: str) -> dict[int, Fraction]:
    """Grid step per beat number: sixteenths, or triplets where they fit clearly better."""
    by_beat: dict[int, list[Fraction]] = {}
    for x in beats:
        by_beat.setdefault(math.floor(x + Fraction(1, 8)), []).append(x)
    grids = {}
    for b, xs in by_beat.items():
        if triplets == "never":
            grids[b] = STRAIGHT
            continue
        if triplets == "always":
            grids[b] = TRIPLET
            continue
        err4 = sum(abs(x - _snap(x, STRAIGHT)) for x in xs)
        err3 = sum(abs(x - _snap(x, TRIPLET)) for x in xs)
        off_beat = any(_snap(x, TRIPLET) % 1 for x in xs)
        grids[b] = TRIPLET if off_beat and err3 < 0.6 * err4 else STRAIGHT
    return grids


def _quantize(x: Fraction, grids: dict[int, Fraction]) -> Fraction:
    return _snap(x, grids.get(math.floor(x + Fraction(1, 8)), STRAIGHT))


def estimate_bpm(notes: list[Note], low: float = 50, high: float = 160) -> float:
    """Rough tempo of a take played without a click: the beat length that best explains the
    gaps between chords. Often off by a factor of two; pass bpm when you know it."""
    onsets: list[float] = []
    for n in sorted(notes, key=lambda n: n.start):
        if not onsets or n.start - onsets[-1] > 0.06:
            onsets.append(n.start)
    gaps = [b - a for a, b in zip(onsets, onsets[1:]) if 0.12 < b - a < 2.5]
    if len(gaps) < 3:
        return 90.0
    best, best_err = 90.0, float("inf")
    for bpm in range(int(low), int(high) + 1):
        beat = 60.0 / bpm
        err = 0.0
        for g in gaps:
            units = g / beat * 2  # in eighth notes
            err += abs(units - max(1, round(units))) / max(1, round(units)) ** 0.5
        err /= len(gaps)
        err += 0.002 * abs(bpm - 90)  # mild preference for moderate tempos
        if err < best_err:
            best, best_err = float(bpm), err
    return best


def transcribe(
    notes: list[Note],
    bpm: float,
    beats_per_bar: int = 4,
    downbeat: float | None = None,
    split_note: int = 60,
    title: str = "Recording",
    triplets: str = "auto",
) -> dict:
    """Quantize notes (times in seconds) into a MusicXML score.

    downbeat: time of beat 1 of bar 1 (default: the first note, snapped to a beat).
    triplets: 'auto' | 'never' | 'always'.
    Returns {xml, bars, notes, key, dropped}.
    """
    if not notes:
        raise ValueError("Nothing was played.")
    if bpm <= 0:
        raise ValueError("bpm must be positive.")
    spb = 60.0 / bpm
    if downbeat is None:
        downbeat = min(n.start for n in notes)

    def to_beats(t: float) -> Fraction:
        return Fraction(round((t - downbeat) / spb * 48), 48)

    kept = [n for n in notes if to_beats(n.start) >= -EARLY_OK]
    dropped = len(notes) - len(kept)
    if not kept:
        raise ValueError("Every note came before the count-in finished.")
    starts = [max(Fraction(0), to_beats(n.start)) for n in kept]
    grids = _beat_grids(starts, triplets)
    sides = split_hands(kept, split_note)
    events = []  # (hand, onset, end, pitch)
    for n, s in zip(kept, starts):
        on = _quantize(s, grids)
        end = _quantize(max(s, to_beats(n.end)), grids)
        step = grids.get(math.floor(on + Fraction(1, 8)), STRAIGHT)
        events.append((sides[(round(n.start, 4), n.pitch)], on, max(end, on + step), n.pitch))

    out = grand_staff(events, title, f"{beats_per_bar}/4", [(Fraction(0), bpm)])
    return {**out, "dropped": dropped}


def grand_staff(
    events: list[tuple[str, Fraction, Fraction, int]],
    title: str,
    time_signature: str = "4/4",
    tempo_marks: list[tuple[Fraction, float]] | None = None,
    legato_gap: Fraction = Fraction(1, 4),
) -> dict:
    """Write (hand, onset beat, end beat, pitch) events as a two-staff piano score.

    Beats are quarter notes from the start of bar 1, already on a grid. Within a hand,
    notes starting together form a chord lasting until the hand's next chord, and a
    chord that stops at most legato_gap (or a quarter of its length) before the next one
    is held up to it, so slightly detached playing doesn't fill the page with tiny rests.
    Notes held well past the hand's next chord (a bass under an arpeggio) get a second
    voice, so they keep their length. Returns {xml, bars, notes, key}.
    """
    from music21 import chord, clef, key as m21key, metadata, meter, note, stream, tempo, tie
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    if not events:
        raise ValueError("No notes to write.")
    bar_ql = Fraction(meter.TimeSignature(time_signature).barDuration.quarterLength).limit_denominator(48)
    last = max(e[2] for e in events)
    bars = max(1, math.ceil(last / bar_ql))
    total = bars * bar_ql

    # Key from the pitches, for the key signature and sharps-vs-flats spelling.
    probe = stream.Stream([note.Note(p) for *_, p in events])
    try:
        found = probe.analyze("key")
    except Exception:
        found = m21key.Key("C")
    sharps = found.sharps
    if abs(sharps) > 6:  # C sharp major (7 sharps) is written as D flat major (5 flats)
        sharps += -12 if sharps > 0 else 12
        found = m21key.KeySignature(sharps).asKey(found.mode)
    local = _local_sharps(events, bar_ql, bars, sharps)

    def spelled(midi: int, at: Fraction):
        from music21 import pitch

        here = local[min(int(at // bar_ql), bars - 1)]
        p = pitch.Pitch(midi=midi)
        if p.accidental is not None and ((here < 0 and p.accidental.name == "sharp") or (here > 0 and p.accidental.name == "flat")):
            p = p.getEnharmonic()
        return p

    score = stream.Score()
    score.metadata = metadata.Metadata(title=title)
    count = 0
    for hand in ("right", "left"):
        part = stream.Part()
        part.partName = "Right Hand" if hand == "right" else "Left Hand"
        hand_events = [(on, end, p) for h, on, end, p in events if h == hand]
        for at, name in _clefs(hand, hand_events, bar_ql, bars):
            part.insert(at, clef.TrebleClef() if name == "treble" else clef.BassClef())
        part.insert(0, meter.TimeSignature(time_signature))
        part.insert(0, m21key.KeySignature(sharps))
        if hand == "right":
            for at, bpm in tempo_marks or []:
                part.insert(at, tempo.MetronomeMark(number=round(bpm)))
        voices = _voices(hand_events)
        for k, notes_in_voice in enumerate(voices):
            target = part if len(voices) == 1 else stream.Voice(id=str(k + 1))
            count += _write_voice(target, notes_in_voice, legato_gap, total, spelled, chord, note, tie)
            if target is not part:
                target.makeRests(fillGaps=True, inPlace=True, timeRangeFromBarDuration=False, refStreamOrTimeRange=[0, total])
                part.insert(0, target)
        if len(voices) == 1:
            part.makeRests(fillGaps=True, inPlace=True, timeRangeFromBarDuration=False, refStreamOrTimeRange=[0, total])
        part.makeMeasures(inPlace=True)
        part.makeTies(inPlace=True)
        for m in part.getElementsByClass("Measure"):
            # A voice with nothing to play in a bar is left out of it, rather than drawing a whole rest.
            idle = [v for v in m.voices if not v.notes]
            for v in idle[: len(m.voices) - 1]:
                m.remove(v)
            # Nor is a rest drawn under the other voice's held note.
            for v in m.voices:
                others = [n for w in m.voices if w is not v for n in w.notes]
                for r in v.getElementsByClass("Rest"):
                    if any(n.offset < r.offset + r.quarterLength and r.offset < n.offset + n.quarterLength for n in others):
                        r.style.hideObjectOnPrint = True
        score.insert(0, part)
    xml = GeneralObjectExporter(score).parse().decode("utf-8")
    name = found.tonic.name.replace("-", "b") + ("m" if found.mode == "minor" else "")
    return {"xml": xml, "bars": bars, "notes": count, "key": name}


HELD_BEATS = 2  # a note still sounding this long after the hand's next chord gets a voice of its own
TO_BASS, TO_TREBLE = 55, 65  # a bar whose middle note is below G3 / above F4 changes to that clef


def _clefs(hand: str, events: list[tuple[Fraction, Fraction, int]], bar_ql: Fraction, bars: int) -> list[tuple[Fraction, str]]:
    """(offset, 'treble' | 'bass') for a hand's staff: its own clef, changed for bars that sit
    well into the other clef's range rather than writing them on three or more ledger lines,
    and changed back once the hand is on its own side of middle C again."""
    home = "treble" if hand == "right" else "bass"
    by_bar: dict[int, list[int]] = {}
    for on, _, p in events:
        by_bar.setdefault(min(int(on // bar_ql), bars - 1), []).append(p)
    out: list[tuple[Fraction, str]] = []
    current = home
    for b in range(bars):
        ps = sorted(by_bar.get(b, []))
        if not ps:
            continue
        mid = ps[len(ps) // 2]
        want = current
        if current == "treble" and mid < TO_BASS or current == "bass" and mid > TO_TREBLE:
            want = "bass" if current == "treble" else "treble"
        elif current != home and (mid >= 60) == (home == "treble"):
            want = home
        if want != current or not out:
            out.append((b * bar_ql if out else Fraction(0), want))
            current = want
    return out or [(Fraction(0), home)]


def _voices(events: list[tuple[Fraction, Fraction, int]]) -> list[list[tuple[Fraction, Fraction, int]]]:
    """One hand's (onset, end, pitch) notes as one voice, or two - the notes held at least
    HELD_BEATS past the hand's next chord, and the rest - upper voice first."""
    import bisect

    ends: dict[tuple[Fraction, int], Fraction] = {}
    for on, end, p in events:
        ends[(on, p)] = max(end, ends.get((on, p), end))
    onsets = sorted({on for on, _ in ends})
    by_pitch: dict[int, list[Fraction]] = {}
    for on, p in sorted(ends):
        by_pitch.setdefault(p, []).append(on)
    held, moving = [], []
    for (on, p), end in sorted(ends.items()):
        again = by_pitch[p]
        k = bisect.bisect_right(again, on)
        if k < len(again):
            end = min(end, again[k])  # a key struck again was let go first
        k = bisect.bisect_right(onsets, on)
        long = k < len(onsets) and end - onsets[k] >= HELD_BEATS
        (held if long else moving).append((on, end, p))
    if not held or not moving:
        return [held + moving]
    mean = lambda xs: sum(p for *_, p in xs) / len(xs)  # noqa: E731
    return [moving, held] if mean(moving) >= mean(held) else [held, moving]


def _write_voice(target, events, legato_gap: Fraction, limit: Fraction, spelled, chord, note, tie) -> int:
    """Insert one voice's notes into a Part or Voice as chords, none past `limit` (the end of
    the last bar); returns how many notes."""
    chords: dict[Fraction, list[tuple[Fraction, int]]] = {}
    for on, end, p in events:
        chords.setdefault(on, []).append((end, p))
    onsets = sorted(chords)
    count = 0
    for i, on in enumerate(onsets):
        end = max(e for e, _ in chords[on])
        nxt = onsets[i + 1] if i + 1 < len(onsets) else limit
        if i + 1 < len(onsets):
            # Released a little early (up to a 16th, or a quarter of the note): write it held.
            end = nxt if nxt - end <= max(legato_gap, (end - on) / 4) else min(end, nxt)
        # A short note on an eighth with nothing until the next eighth is an eighth (played
        # short), not a 16th and a dotted-eighth rest.
        if (on * 2).denominator == 1 and end - on < Fraction(1, 2) <= nxt - on:
            end = on + Fraction(1, 2)
        pitches = sorted({p for _, p in chords[on]})
        pieces = _pieces(on, end - on)
        for k, (start, length) in enumerate(pieces):
            item = chord.Chord([spelled(p, on) for p in pitches]) if len(pitches) > 1 else note.Note(spelled(pitches[0], on))
            item.quarterLength = length
            if len(pieces) > 1:
                item.tie = tie.Tie("start" if k == 0 else "stop" if k == len(pieces) - 1 else "continue")
            target.insert(start, item)
        count += len(pitches)
    return count


# Krumhansl-Kessler key profiles, C major / C minor.
_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def _local_sharps(events: list[tuple[str, Fraction, Fraction, int]], bar_ql: Fraction, bars: int, default: int) -> list[int]:
    """Sharps (+) or flats (-) of the key each bar is in, judged from it and its neighbours,
    for spelling accidentals: a song that moves from G minor to B minor writes F sharp, not G
    flat, though it keeps one key signature. Bars with too little to go on keep `default`."""
    weights = [[0.0] * 12 for _ in range(bars)]
    for _, on, end, p in events:
        weights[min(int(on // bar_ql), bars - 1)][p % 12] += float(end - on)
    out = []
    for b in range(bars):
        hist = [sum(weights[k][pc] * (2 if k == b else 1) for k in range(max(0, b - 1), min(bars, b + 2))) for pc in range(12)]
        if sum(1 for h in hist if h) < 3:
            out.append(default)
            continue
        best, best_r = default, -2.0
        for tonic in range(12):
            for profile, major in ((_MAJOR, True), (_MINOR, False)):
                r = _correlation(hist, [profile[(pc - tonic) % 12] for pc in range(12)])
                if r > best_r:
                    # Of the two spellings (F sharp or G flat major), the one nearer the key signature.
                    fifths = ((tonic if major else tonic + 3) * 7) % 12
                    best = min((s for s in (fifths, fifths - 12) if abs(s) <= 7), key=lambda s: (abs(s - default), abs(s)))
                    best_r = r
        out.append(best)
    return out


def _correlation(xs: list[float], ys: list[float]) -> float:
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx, syy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else -1.0


def _pieces(start: Fraction, length: Fraction) -> list[tuple[Fraction, Fraction]]:
    """Split a duration MusicXML can't write as one note (e.g. a triplet tied into a
    straight beat) into tied pieces at beat boundaries."""
    from music21 import duration

    if duration.Duration(length).type != "inexpressible":
        return [(start, length)]
    out = []
    pos, end = start, start + length
    while pos < end:
        nxt = min(end, Fraction(math.floor(pos) + 1))
        out.append((pos, nxt - pos))
        pos = nxt
    return out


def default_title() -> str:
    return time.strftime("Recording %Y-%m-%d %H-%M")
