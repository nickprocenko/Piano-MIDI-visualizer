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
    time_signature: str | list[tuple[Fraction, str]] = "4/4",
    tempo_marks: list[tuple[Fraction, float]] | None = None,
    legato_gap: Fraction = Fraction(1, 4),
    melody: list[tuple[Fraction, Fraction, int, tuple[str, str] | None]] | None = None,
    melody_name: str = "Vocals",
    source: str | None = None,
    composer: str | None = None,
    clef_every: Fraction | None = None,
    pickup: Fraction | None = None,
    dynamics: list[tuple[Fraction, str]] | None = None,
) -> dict:
    """Write (hand, onset beat, end beat, pitch) events as a two-staff piano score; events
    whose hand is 'pedals' (a bass line played with the feet) get a third staff below.

    Beats are quarter notes from the start of bar 1, already on a grid. Within a hand,
    notes starting together form a chord lasting until the hand's next chord, and a
    chord that stops at most legato_gap (or a quarter of its length) before the next one
    is held up to it, so slightly detached playing doesn't fill the page with tiny rests.
    Notes held well past the hand's next chord (a bass under an arpeggio) get a second
    voice, so they keep their length.

    time_signature: one ("3/4") or the changes, [(beat, "2/4"), ...] from beat 0.
    The key signature follows the music: it changes where the piece moves to a new key for
    a while (a modulation), not for a borrowed chord or a short excursion (those get
    accidentals). melody: an optional tune - [(onset, end, pitch, (lyric, syllabic) or
    None)] - on a staff above the piano (treble, or treble-8vb for a low voice), with its
    lyrics. source: a note on where the score came from, kept in the file's
    <identification><source>. clef_every: choose each staff's clef per span of this many
    beats instead of per bar (a scale running four octaves inside one bar changes clef as it
    climbs). pickup: the music starts with an upbeat this many beats long - written as a
    short bar 0 (implicit in MusicXML), bars numbered from 1 after it, as printed music does.
    dynamics: [(beat, "mf"), ...] marks for the piano, written once under the right hand
    (between the staves, where piano music puts them).
    Returns {xml, bars, notes, key, keys: [(bar, key signature sharps)]}.
    """
    import bisect

    from music21 import chord, clef, dynamics as m21dynamics, key as m21key, metadata, meter, note, stream, tempo, tie
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    if not events and not melody:
        raise ValueError("No notes to write.")
    tune = list(melody or [])
    shift = Fraction(0)
    if pickup:  # lay the upbeat at the end of a full first bar, then cut that bar down (_pickup_bar)
        first_sig = time_signature if isinstance(time_signature, str) else sorted(time_signature)[0][1]
        shift = Fraction(meter.TimeSignature(first_sig).barDuration.quarterLength).limit_denominator(48) - Fraction(pickup)
        events = [(h, on + shift, end + shift, p) for h, on, end, p in events]
        tune = [(on + shift, end + shift, p, lyric) for on, end, p, lyric in tune]
        tempo_marks = [(at + shift if at else at, bpm) for at, bpm in tempo_marks or []]
        dynamics = [(at + shift, mark) for at, mark in dynamics or []]
        if not isinstance(time_signature, str):
            time_signature = [(at + shift if at else at, sig) for at, sig in sorted(time_signature)]
    last = max([e[2] for e in events] + [m[1] for m in tune])
    bar_starts, bar_sigs, total = _bar_grid(time_signature, last)
    bars = len(bar_starts)

    def bar_of(at: Fraction) -> int:
        return max(0, min(bisect.bisect_right(bar_starts, at) - 1, bars - 1))

    # Key from the pitches, for the key signature and sharps-vs-flats spelling.
    every = events + [("tune", on, end, p) for on, end, p, _ in tune]
    probe = stream.Stream([note.Note(p) for *_, p in every])
    try:
        found = probe.analyze("key")
    except Exception:
        found = m21key.Key("C")
    sharps = found.sharps
    if abs(sharps) > 6:  # C sharp major (7 sharps) is written as D flat major (5 flats)
        sharps += -12 if sharps > 0 else 12
        found = m21key.KeySignature(sharps).asKey(found.mode)
    local = _local_sharps(every, bar_of, bars, sharps)
    signatures = _key_signatures(every, bar_of, bars, sharps)
    key_changes = [(bar_starts[b], s) for b, s in enumerate(signatures) if b == 0 or s != signatures[b - 1]]

    def spelled(midi: int, at: Fraction):
        from music21 import pitch

        p = pitch.Pitch(midi=midi)
        diatonic = _diatonic_names(signatures[bar_of(at)]).get(midi % 12)
        if diatonic:  # a note of the key signature is spelled as the key spells it
            return next((q for q in [p, *p.getAllCommonEnharmonics()] if q.name == diatonic), p)
        here = local[bar_of(at)]
        if p.accidental is not None and ((here < 0 and p.accidental.name == "sharp") or (here > 0 and p.accidental.name == "flat")):
            p = p.getEnharmonic()
        return p

    def meters_and_keys(part) -> None:
        for b, sig in enumerate(bar_sigs):
            if b == 0 or sig != bar_sigs[b - 1]:
                part.insert(bar_starts[b], meter.TimeSignature(sig))
        for at, s in key_changes:
            part.insert(at, m21key.KeySignature(s))

    score = stream.Score()
    score.metadata = metadata.Metadata()
    score.metadata.movementName = title  # once: a work title as well would print it twice
    if composer:
        score.metadata.composer = composer

    def accidentals(part) -> None:
        _ottavas(part)  # first: accidentals follow where notes are drawn
        _print_accidentals(part)

    count = 0
    if tune:
        part = stream.Part()
        part.partName = melody_name
        pitches = sorted(p for _, _, p, _ in tune)
        part.insert(0, clef.Treble8vbClef() if pitches[len(pitches) // 2] < 60 else clef.TrebleClef())
        meters_and_keys(part)
        for at, bpm in tempo_marks or []:
            part.insert(at, tempo.MetronomeMark(number=round(bpm)))
        # A sung line is legato: a note let go up to an eighth before the next is held to it.
        count += _write_voice(part, [(on, end, p) for on, end, p, _ in tune], max(legato_gap, TUNE_LEGATO), total, spelled, chord, note, tie, bar_starts)
        words = {on: lyric for on, _, _, lyric in tune if lyric}
        for item in part.notes:
            lyric = words.pop(Fraction(item.offset).limit_denominator(48), None)
            if lyric:
                item.lyrics.append(note.Lyric(text=lyric[0], syllabic=lyric[1]))
        part.makeRests(fillGaps=True, inPlace=True, timeRangeFromBarDuration=False, refStreamOrTimeRange=[0, total])
        _plain_rests(part, bar_starts)
        part.makeMeasures(inPlace=True)
        part.makeTies(inPlace=True)
        if shift:
            _pickup_bar(part, shift)
        accidentals(part)
        _beat_triplets(part)
        score.insert(0, part)
    feet =("pedals",) if any(e[0] == "pedals" for e in events) else ()
    for hand in ("right", "left") + feet:
        part = stream.Part()
        part.partName = {"right": "Right Hand", "left": "Left Hand", "pedals": "Pedals"}[hand]
        hand_events = [(on, end, p) for h, on, end, p in events if h == hand]
        if clef_every:
            spans = [Fraction(k) * clef_every for k in range(int(total / clef_every) + 1)]
            clef_at = _clefs(hand, hand_events, lambda at: min(int(at // clef_every), len(spans) - 1), spans)
        else:
            clef_at = _clefs(hand, hand_events, bar_of, bar_starts, CLEF_MIN_BARS)
        for at, name in clef_at:
            part.insert(at, clef.TrebleClef() if name == "treble" else clef.BassClef())
        meters_and_keys(part)
        if hand == "right" and not tune:
            for at, bpm in tempo_marks or []:
                part.insert(at, tempo.MetronomeMark(number=round(bpm)))
        if hand == "right":
            for at, mark in dynamics or []:
                part.insert(at, m21dynamics.Dynamic(mark))
        voices = _voices(hand_events)
        for k, notes_in_voice in enumerate(voices):
            target = part if len(voices) == 1 else stream.Voice(id=str(k + 1))
            count += _write_voice(target, notes_in_voice, legato_gap, total, spelled, chord, note, tie, bar_starts)
            if target is not part:
                target.makeRests(fillGaps=True, inPlace=True, timeRangeFromBarDuration=False, refStreamOrTimeRange=[0, total])
                _plain_rests(target, bar_starts)
                part.insert(0, target)
        if len(voices) == 1:
            part.makeRests(fillGaps=True, inPlace=True, timeRangeFromBarDuration=False, refStreamOrTimeRange=[0, total])
            _plain_rests(part, bar_starts)
        part.makeMeasures(inPlace=True)
        part.makeTies(inPlace=True)
        if shift:
            _pickup_bar(part, shift)
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
        accidentals(part)
        _beat_triplets(part)
        score.insert(0, part)
    xml = GeneralObjectExporter(score).parse().decode("utf-8")
    xml = xml.replace('<creator type="composer">Music21</creator>', "")  # music21's placeholder, not a composer
    if shift:
        xml = xml.replace('<measure implicit="no" number="0">', '<measure implicit="yes" number="0">')
    if source:
        from xml.sax.saxutils import escape

        xml = xml.replace("</encoding>", f"</encoding>\n    <source>{escape(source)}</source>", 1)
    name = found.tonic.name.replace("-", "b") + ("m" if found.mode == "minor" else "")
    return {"xml": xml, "bars": bars, "notes": count, "key": name,
            "keys": [(bar_of(at) + (0 if shift else 1), s) for at, s in key_changes]}


def _pickup_bar(part, shift: Fraction) -> None:
    """Make the first bar an upbeat: drop what comes before `shift` (rests only - the music
    was laid out to start there), move the rest to the start, and number the bars from 0."""
    from music21 import note as m21note

    measures = list(part.getElementsByClass("Measure"))
    if not measures:
        return
    first = measures[0]
    length = first.barDuration.quarterLength - float(shift)
    for c in [first, *first.voices]:
        keep = [(el.offset - float(shift), el) for el in c.notesAndRests if el.offset >= float(shift) - 1e-9]
        for el in list(c.notesAndRests):
            c.remove(el)
        for off, el in keep:
            c.insert(off, el)
        if not keep and (c is not first or not first.voices):  # with voices, the rests go in the voices
            c.insert(0, m21note.Rest(quarterLength=length))
    first.paddingLeft = float(shift)
    for k, m in enumerate(measures):
        m.number = k


_DIATONIC: dict[int, dict[int, str]] = {}


def _diatonic_names(sharps: int) -> dict[int, str]:
    """Pitch class -> its note name in the key signature with this many sharps (negative:
    flats), e.g. -4 -> {8: 'A-', ...}: the spelling a note of the key should have."""
    if sharps not in _DIATONIC:
        from music21 import key as m21key

        scale = m21key.KeySignature(sharps).asKey("major").getScale("major")
        _DIATONIC[sharps] = {p.pitchClass: p.name for p in scale.pitches[:7]}
    return _DIATONIC[sharps]


def _bar_grid(time_signature: str | list[tuple[Fraction, str]], last: Fraction) -> tuple[list[Fraction], list[str], Fraction]:
    """Bar starts and time signatures covering beats 0..last: (starts, signatures, end)."""
    from music21 import meter

    changes = [(Fraction(0), time_signature)] if isinstance(time_signature, str) else sorted(time_signature)
    starts: list[Fraction] = []
    sigs: list[str] = []
    pos, i, current = Fraction(0), 0, changes[0][1]
    while not starts or pos < last:
        while i < len(changes) and changes[i][0] <= pos:
            current = changes[i][1]
            i += 1
        starts.append(pos)
        sigs.append(current)
        pos += Fraction(meter.TimeSignature(current).barDuration.quarterLength).limit_denominator(48)
    return starts, sigs, pos


TUNE_LEGATO = Fraction(1, 2)  # a sung note let go up to this early is written held to the next one
PLAIN_TYPES = ("whole", "half", "quarter", "eighth", "16th")  # note values a piece of a note or rest may take
HELD_BEATS = 2  # a note still sounding this long after the hand's next chord gets a voice of its own
LEDGER_LIMIT = 3  # ledger lines a note may have before its bar should be in the other clef
CLEF_CHANGE_COST = 4.0  # ledger lines a clef change must save to be worth writing
CLEF_MIN_BARS = 8  # a clef kept for fewer bars is written only if the notes can't be read without it
_STAFF = {"treble": (31, 38), "bass": (19, 26)}  # diatonic numbers of the bottom and top lines (E4-F5, G2-A3)


def _ledger_lines(midi: int, clef_name: str) -> int:
    from music21 import pitch

    d = pitch.Pitch(midi=midi).diatonicNoteNum
    low, high = _STAFF[clef_name]
    return (low - d) // 2 if d < low else (d - high) // 2 if d > high else 0  # a note in a space needs no extra line


def _readable(notes: list[tuple[Fraction, int]], clef_name: str) -> bool:
    """Whether (onset, pitch) notes read in this clef by the engraving lint's ledger-lines
    rule: none on five or more ledger lines, never three chords in a row on four."""
    worst: dict[Fraction, int] = {}
    for on, p in notes:
        worst[on] = max(worst.get(on, 0), _ledger_lines(p, clef_name))
    row = 0
    for on in sorted(worst):
        row = row + 1 if worst[on] == 4 else 0
        if worst[on] > 4 or row == 3:
            return False
    return True


def _clefs(hand: str, events: list[tuple[Fraction, Fraction, int]], bar_of, bar_starts: list[Fraction],
           min_run: int = 0) -> list[tuple[Fraction, str]]:
    """(offset, 'treble' | 'bass') for a hand's staff, bar by bar: the clef that keeps its
    notes nearest the staff. A bar scores each clef by its notes' ledger lines - a note more
    than LEDGER_LIMIT lines off costs ten more - and the clef only changes where that saves
    more than CLEF_CHANGE_COST (Viterbi over the bars), so one low note in a high bar gets the
    bass clef without the staff flickering. Ties go to the hand's own clef. min_run: a clef
    kept for fewer bars goes back to the one around it when its notes read there (engraving's
    brief-clef-change), so a hand dipping low for a few bars is read on ledger lines."""
    home = "treble" if hand == "right" else "bass"
    by_bar: dict[int, list[tuple[Fraction, int]]] = {}
    for on, _, p in events:
        by_bar.setdefault(bar_of(on), []).append((on, p))
    kinds = ("treble", "bass")
    rows = []
    for b in range(len(bar_starts)):
        row = {}
        for k in kinds:
            lines = [_ledger_lines(p, k) for _, p in by_bar.get(b, [])]
            row[k] = sum(n + (10 if n > LEDGER_LIMIT else 0) for n in lines) + (0 if k == home else 0.1 * len(lines))
        rows.append(row)
    cost = {k: rows[0][k] + (0 if k == home else 0.5) for k in kinds}
    back = []
    for row in rows[1:]:
        step, new = {}, {}
        for k in kinds:
            other = "bass" if k == "treble" else "treble"
            stay, switch = cost[k], cost[other] + CLEF_CHANGE_COST
            step[k] = k if stay <= switch else other
            new[k] = min(stay, switch) + row[k]
        back.append(step)
        cost = new
    k = min(kinds, key=lambda x: (cost[x], x != home))
    path = [k]
    for step in reversed(back):
        k = step[k]
        path.append(k)
    path.reverse()
    changed = True
    while min_run and changed:  # shortest brief clef first: undoing it can merge its neighbours
        changed = False
        runs, b = [], 0
        while b < len(path):
            e = b
            while e < len(path) and path[e] == path[b]:
                e += 1
            runs.append((b, e))
            b = e
        for b, e in sorted(runs, key=lambda r: r[1] - r[0]) if len(runs) > 1 else ():
            if e - b >= min_run:
                break
            around = path[b - 1] if b else path[e]
            if _readable([n for x in range(b, e) for n in by_bar.get(x, [])], around):
                path[b:e] = [around] * (e - b)
                changed = True
                break
    return [(bar_starts[b] if b else Fraction(0), k) for b, k in enumerate(path) if b == 0 or k != path[b - 1]]


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


def _beat_triplets(part) -> None:
    """A triplet beat that mixes values (a quarter then two 16ths, all triplets) as one bracket
    over the beat. music21 brackets each value on its own - the quarter's group would need two
    beats, the 16ths' half a beat - and on export cuts the next plain note into triplet pieces to
    fill them (an eighth written as a tied eighth and 16th triplet)."""
    from music21 import duration

    for m in part.getElementsByClass("Measure"):
        for layer in list(m.voices) or [m]:
            beats: dict[int, list] = {}
            for el in layer.notesAndRests:
                t = el.duration.tuplets
                if len(t) == 1 and (t[0].numberNotesActual, t[0].numberNotesNormal) == (3, 2):
                    beats.setdefault(math.floor(el.offset), []).append(el)
            for group in beats.values():
                kinds = {el.duration.tuplets[0].durationNormal.type for el in group}
                if len(kinds) < 2 or sum(Fraction(el.quarterLength) for el in group) != 1:
                    continue
                for el in group:
                    d = duration.Duration(type=el.duration.type, dots=el.duration.dots)
                    d.appendTuplet(duration.Tuplet(3, 2, "eighth"))
                    el.duration = d


def _write_voice(target, events, legato_gap: Fraction, limit: Fraction, spelled, chord, note, tie, bar_starts=None) -> int:
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
        # short), not a 16th and a dotted-eighth rest - in a straight beat only (in a triplet
        # beat it would leave a sixth of a beat before the next triplet note).
        if (on * 2).denominator == 1 and (nxt * 4).denominator == 1 and (end * 4).denominator == 1 \
                and end - on < Fraction(1, 2) <= nxt - on:
            end = on + Fraction(1, 2)
        pitches = sorted({p for _, p in chords[on]})
        pieces = _pieces(on, end - on, bar_starts)
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


def _bar_weights(events: list[tuple[str, Fraction, Fraction, int]], bar_of, bars: int) -> list[list[float]]:
    """Per bar, how long each pitch class sounds."""
    weights = [[0.0] * 12 for _ in range(bars)]
    for _, on, end, p in events:
        weights[bar_of(on)][p % 12] += float(end - on)
    return weights


def _around(weights: list[list[float]], b: int) -> list[float]:
    """A bar's pitch classes with its neighbours' (the bar itself counted twice)."""
    return [sum(weights[k][pc] * (2 if k == b else 1) for k in range(max(0, b - 1), min(len(weights), b + 2))) for pc in range(12)]


KEY_CHANGE_COST = 6.0  # bars in another key it takes for a new key signature (twice that for a passage that returns)
NEAR_BEST = 0.1  # a signature within this share of accidentals of a bar's best one fits that bar too
_SCALE = (0, 2, 4, 5, 7, 9, 11)


def _key_signatures(events: list[tuple[str, Fraction, Fraction, int]], bar_of, bars: int, default: int) -> list[int]:
    """The key signature (sharps +, flats -) for each bar. Each bar (with its neighbours) is
    in the signatures that leave it the fewest accidentals; a signature costs a bar 1 where
    it isn't one of those (plus its share of accidentals, to break ties), and the signature
    only changes where that saves more than KEY_CHANGE_COST - a modulation, not a borrowed
    chord or a short excursion (Viterbi over the bars). Counting bars, not accidentals,
    keeps a key signature from settling between two keys and giving every bar accidentals;
    scoring accidentals rather than major/minor fit keeps modal songs (A with G naturals)
    on the signature their notes use. Ties go to `default`, then the simpler one."""
    weights = _bar_weights(events, bar_of, bars)
    options = list(range(-6, 7))
    fit = []
    for b in range(bars):
        # The bar itself (so a new key starts on its first bar); its neighbours too if it has
        # too few notes to tell. The cost of changing does the smoothing.
        hist = weights[b] if sum(1 for h in weights[b] if h) >= 3 else _around(weights, b)
        total = sum(hist)
        share = {}
        for s in options:
            tonic = (s * 7) % 12  # the major key with s sharps
            inside = {(tonic + d) % 12 for d in _SCALE}
            share[s] = sum(h for pc, h in enumerate(hist) if pc not in inside) / total if total else 0.0
        best = min(share.values())
        fit.append({s: -((1.0 if share[s] > best + NEAR_BEST else 0.0) + share[s])
                    + (0.02 if s == default else 0.0) - 0.001 * abs(s) for s in options})
    cost = {s: -fit[0][s] for s in options}
    back: list[dict[int, int]] = []
    for b in range(1, bars):
        best_prev = min(options, key=lambda s: cost[s])
        step, new = {}, {}
        for s in options:
            stay, switch = cost[s], cost[best_prev] + KEY_CHANGE_COST
            step[s] = s if stay <= switch else best_prev
            new[s] = min(stay, switch) - fit[b][s]
        back.append(step)
        cost = new
    s = min(options, key=lambda s: cost[s])
    out = [s]
    for step in reversed(back):
        s = step[s]
        out.append(s)
    return out[::-1]


def _local_sharps(events: list[tuple[str, Fraction, Fraction, int]], bar_of, bars: int, default: int) -> list[int]:
    """Sharps (+) or flats (-) of the key each bar is in, judged from it and its neighbours,
    for spelling accidentals: a song that moves from G minor to B minor writes F sharp, not G
    flat, though it keeps one key signature. Bars with too little to go on keep `default`."""
    weights = _bar_weights(events, bar_of, bars)
    out = []
    for b in range(bars):
        hist = _around(weights, b)
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


def _ottavas(part) -> int:
    """Write runs of notes more than LEDGER_LIMIT ledger lines off the staff an octave nearer,
    under 8vb (low) or 8va (high), as printed music does: F1 drawn as F2 with '8vb'; two
    octaves (15mb / 15ma) for a long note one octave doesn't bring back, like a held C0. The file keeps
    the true pitch (MusicXML <octave-shift>), so the coach still grades F1. Returns how many
    notes moved."""
    from music21 import spanner

    def staff_of(el) -> tuple[str, int]:
        """The clef's staff and its own octave: a treble-8vb clef already draws notes an
        octave above their sound (so B3 sits on the staff - no 8vb mark on top of that)."""
        clef_ = el.getContextByClass("Clef")
        kind = "bass" if clef_ is not None and clef_.sign == "F" else "treble"
        return kind, -7 * (getattr(clef_, "octaveChange", 0) or 0)

    def written_lines(el) -> tuple[int, str]:
        kind, shift = staff_of(el)
        low, high = _STAFF[kind]
        worst, side = 0, ""
        for p in el.pitches:
            d = p.diatonicNoteNum + shift  # where the clef draws it
            n = (low - d) // 2 if d < low else (d - high) // 2 if d > high else 0
            if n > worst:
                worst, side = n, ("low" if d < low else "high")
        return worst, side

    def fits_moved(el, side, octaves=1) -> bool:
        """Still readable drawn `octaves` nearer: on the staff's side of its middle line
        before, and within LEDGER_LIMIT lines of the other side after."""
        kind, shift = staff_of(el)
        low, high = _STAFF[kind]
        middle = (low + high) / 2
        for p in el.pitches:
            drawn = p.diatonicNoteNum + shift
            d = drawn + (7 if side == "low" else -7) * octaves
            if (side == "low" and drawn > middle) or (side == "high" and drawn < middle):
                return False
            if (d - high) // 2 > LEDGER_LIMIT or (low - d) // 2 > LEDGER_LIMIT:
                return False
        return True

    def runs(seq):
        """Runs of notes needing an octave mark, merged across notes between them that read
        fine moved too, when the gap is within a bar: one 8vb over a low passage, not one per
        note."""
        found: list[list] = []  # [first index, last index, side, notes beyond the limit, most lines, octaves]
        for i, el in enumerate(seq):
            if el.isRest:
                continue
            n, s = written_lines(el)
            if n <= LEDGER_LIMIT:
                continue
            kind, shift = staff_of(el)
            low, high = _STAFF[kind]
            middle = (low + high) / 2
            if any((p.diatonicNoteNum + shift > middle) if s == "low" else (p.diatonicNoteNum + shift < middle) for p in el.pitches):
                continue  # a chord reaching across the staff (B2 under D5): the mark would push its other notes off it
            # Two octaves only for a long note out there on its own (a held C0); in a fast run
            # it would pile up on the run's own 8va / 8vb marks.
            held = el.duration.quarterLength >= 2 or el.tie is not None
            for octaves in (1, 2) if held else (1,):
                moved = [p.diatonicNoteNum + shift + (7 if s == "low" else -7) * octaves for p in el.pitches]
                if not any((low - d) // 2 > LEDGER_LIMIT + 1 or (d - high) // 2 > LEDGER_LIMIT + 1 for d in moved):
                    break
            else:
                continue  # a chord spanning both ways (D2 under A4): an octave mark would only move the problem
            new_note = int(el.tie is None or el.tie.type == "start")  # a held note counts once
            if found and found[-1][2] == s and found[-1][5] == octaves:
                a, b = found[-1][:2]
                between = [x for x in seq[b + 1:i] if not x.isRest]
                near = el.getOffsetInHierarchy(part) - seq[b].getOffsetInHierarchy(part) <= 4
                if near and all(fits_moved(x, s, octaves) for x in between):
                    found[-1][1], found[-1][3], found[-1][4] = i, found[-1][3] + new_note, max(found[-1][4], n)
                    continue
            found.append([i, i, s, new_note, n, octaves])
        for a, b, s, count, most, octaves in found:
            # A lone note on four ledger lines reads fine (an F1 in the bass); an octave mark is
            # for a note further out, or a passage down there.
            if most > LEDGER_LIMIT + 1 or count >= 3:
                yield [x for x in seq[a:b + 1] if not x.isRest], s, octaves

    voices: dict[str, list] = {}
    for m in part.getElementsByClass("Measure"):
        for v in (m.voices or [m]):
            key = str(v.id) if v is not m else "1"
            voices.setdefault(key, []).extend(x for x in v.notesAndRests if not x.duration.isGrace)
    onsets = {key: [float(x.getOffsetInHierarchy(part)) for x in seq if not x.isRest] for key, seq in voices.items()}
    moved = 0
    for key, seq in voices.items():
        for run, side, octaves in runs(seq):
            start = float(run[0].getOffsetInHierarchy(part))
            end = float(run[-1].getOffsetInHierarchy(part)) + run[-1].duration.quarterLength
            if any(start <= at < end for other, ats in onsets.items() if other != key for at in ats):
                continue  # an octave mark covers the whole staff: it would move the other voice's notes too
            interval = "P8" if octaves == 1 else "P15"
            for el in run:
                el.transpose(interval if side == "low" else "-" + interval, inPlace=True)  # where it is drawn
                moved += len(el.pitches)
            mark = ("8v" if octaves == 1 else "15m") + ("b" if side == "low" else "a")
            part.insert(0, spanner.Ottava(run, type=mark, transposing=True))
    return moved


def _print_accidentals(part) -> None:
    """Decide which accidentals to print, by the standard rule (and what engraving.lint checks):
    a note gets one when its sharp/flat/natural differs from what the key signature in force
    and the bar so far give in that octave - across the staff's voices; a note tied over from
    the bar before doesn't; and a courtesy one is printed when the same letter was altered
    differently earlier in the bar (another octave) or in the bar before. Nothing else: no
    flats on every E flat in E flat major, and no A3 left bare after an A2 natural (music21's
    own pass reads accidentals by letter across octaves and reprints repeats)."""
    from music21 import pitch as m21pitch

    def sounding_shift(el) -> int:
        """Octaves between where a note is drawn and where it sounds: under an 8va it sounds an
        octave up. Accidentals follow the sounding pitch, so a note under an octave mark gets
        its own (an A4 natural drawn where an earlier A3 natural sits still shows it)."""
        for sp in el.getSpannerSites():
            if type(sp).__name__ == "Ottava":
                octaves = 2 if str(sp.type).startswith("15") else 1
                return octaves if str(sp.type).startswith(("8va", "15ma")) else -octaves
        return 0

    key_alter: dict[str, float] = {}
    before: dict[str, float] = {}
    for m in part.getElementsByClass("Measure"):
        if m.keySignature is not None:
            key_alter = {p.step: p.alter for p in m.keySignature.alteredPitches}
        state: dict[tuple[str, int], float] = {}
        items = sorted(m.recurse().notes, key=lambda el: (Fraction(el.getOffsetInHierarchy(m)).limit_denominator(96), not el.duration.isGrace))
        for el in items:
            continuing = el.tie is not None and el.tie.type in ("stop", "continue")
            shift = sounding_shift(el)
            for p in el.pitches:
                alter = p.alter
                k = (p.step, p.octave + shift)
                current = state.get(k, key_alter.get(p.step, 0.0))
                courtesy = any(s == p.step and a != alter for (s, _), a in state.items()) or before.get(p.step, alter) != alter
                show = not continuing and (alter != current or courtesy)
                if show and p.accidental is None:
                    p.accidental = m21pitch.Accidental("natural")
                if p.accidental is not None:
                    p.accidental.displayStatus = show
                if not continuing:
                    state[k] = alter
        before = {s: a for (s, _), a in state.items() if a != key_alter.get(s, 0.0)}


def _plain_rests(target, bar_starts: list[Fraction] | None = None) -> None:
    """Split rests no plain value can show (a gap from a 16th into a triplet beat, 23/12 of a
    beat) into plain pieces, as notes are - else MusicXML draws them as 24:23 tuplets."""
    from music21 import note

    for r in list(target.getElementsByClass("Rest")):
        length = Fraction(r.quarterLength).limit_denominator(96)
        start = Fraction(r.offset).limit_denominator(96)
        if len(_pieces(start, length, bar_starts)) == 1:
            continue
        hidden = r.style.hideObjectOnPrint
        target.remove(r)
        for at, piece in _pieces(start, length, bar_starts):
            fill = note.Rest(quarterLength=piece)
            fill.style.hideObjectOnPrint = hidden
            target.insert(at, fill)


def _plain(length: Fraction) -> bool:
    """A length one plain note can show: a standard value with at most one dot, or a plain
    triplet value (3 in the time of 2). Not 7/12 of a beat as one '12:7' tuplet."""
    from music21 import duration

    d = duration.Duration(length)
    if d.type not in PLAIN_TYPES or d.dots > 1:  # music21 calls 19.5 beats 'complex', not 'inexpressible'
        return False
    return not d.tuplets or (len(d.tuplets) == 1 and (d.tuplets[0].numberNotesActual, d.tuplets[0].numberNotesNormal) == (3, 2) and length < 1)


def _pieces(start: Fraction, length: Fraction, bar_starts: list[Fraction] | None = None) -> list[tuple[Fraction, Fraction]]:
    """Split a duration into tied plain pieces: first at barlines (bar_starts), so cutting a
    note into bars never leaves a remainder like 3.5 beats (a double-dotted half); then each
    piece that isn't one plain note (a 16th tied into a triplet beat, two and a half beats) up
    to the next beat, whole beats in the biggest plain values (a half, a dotted half...), and
    what is left."""
    end = start + length
    cuts = [b for b in (bar_starts or []) if start < b < end]
    if cuts:
        out, pos = [], start
        for b in cuts + [end]:
            out += _pieces(pos, b - pos)
            pos = b
        return out
    if _plain(length):
        return [(start, length)]
    out = []
    pos = start
    head = min(end, Fraction(math.ceil(pos)))
    if head > pos:
        out.append((pos, head - pos))
        pos = head
    while end - pos >= 1:
        whole = math.floor(end - pos)
        chunk = next(Fraction(k) for k in (4, 3, 2, 1) if k <= whole and _plain(Fraction(k)))
        out.append((pos, chunk))
        pos += chunk
    if end > pos:
        out.append((pos, end - pos))
    return out


def default_title() -> str:
    return time.strftime("Recording %Y-%m-%d %H-%M")
