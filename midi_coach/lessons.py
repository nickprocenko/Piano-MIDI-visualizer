"""Custom lessons: build MusicXML from compact notation or excerpt a reference.

Lessons are saved to <home>/lessons/<slug>.musicxml, so they are also normal
references for recording, comparison and progress tracking.

Notation (music21 tinyNotation, one string per hand)
----------------------------------------------------
  c d e f g a b     pitches; c = middle C (C4), c' = C5, c'' = C6, C = C3, CC = C2
  # / -             sharp / flat after the letter: f#  b-  (b- = B flat)
  4 8 16 2 1        duration after the pitch: quarter, eighth, 16th, half, whole;
                    a following note without a number reuses the last duration
  .                 dotted: c4.  g2.
  r                 rest: r4  r2
  ~                 tie to the next note: c2~ c8
  chord{C2 E G}     chord; the duration goes on its first note
  trip{c8 d e}      triplet
"""

from __future__ import annotations

import re
import time

from .library import home
from .notes import Score, load_score

_KEY_RE = re.compile(r"^([A-Ga-g])([#b-]?)(m|min|minor)?$")


def lessons_dir():
    path = home() / "lessons"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or time.strftime("lesson-%Y%m%d-%H%M%S")


_TOKEN_RE = re.compile(r"^(r|[a-g]'*|[A-G]+)(#{1,2}|-{1,2}|n)?(\d+)?\.*~?$")
_GROUP_RE = re.compile(r"^(chord|trip|quad)\{(.*)$")


def validate_tiny(text: str) -> None:
    """Reject tokens tinyNotation would silently drop (e.g. 'G,' instead of 'GG')."""
    bad = []
    for raw in text.split():
        token = raw
        m = _GROUP_RE.match(token)
        if m:
            token = m.group(2)
        token = token.rstrip("}")
        if token and not _TOKEN_RE.match(token):
            bad.append(raw)
    if bad:
        raise ValueError(
            f"Unrecognized notes {bad} in {text!r}. Octaves: c = C4, c' = C5, C = C3, CC = C2; "
            "sharps f#, flats b-, durations 1 2 4 8 16 with dots, rests r4, chords chord{c4 e g}."
        )


def _tiny(text: str, time_signature: str):
    validate_tiny(text)
    from music21 import chord
    from music21 import tinyNotation as tn

    class ChordState(tn.State):
        def affectTokenAfterParse(self, n):
            super().affectTokenAfterParse(n)
            return None  # collected into the chord in end()

        def end(self):
            ch = chord.Chord(self.affectedTokens)
            ch.duration = self.affectedTokens[0].duration
            return ch

    conv = tn.Converter(f"{time_signature} {text.strip()}")
    conv.bracketStateMapping["chord"] = ChordState
    stream = conv.parse().stream
    notes = list(stream.flatten().notesAndRests)
    if not notes:
        raise ValueError(f"No notes parsed from: {text!r}")
    return notes


def _key(key: str | int | None):
    from music21 import key as m21key

    if key is None or key == "":
        return None
    if isinstance(key, int) or str(key).lstrip("-").isdigit():
        return m21key.KeySignature(int(key))
    m = _KEY_RE.match(str(key).strip())
    if not m:
        raise ValueError(f"Unrecognized key {key!r} (use e.g. 'G', 'Bb', 'F#m', or a number of sharps like -2)")
    tonic = m.group(1).upper() + {"#": "#", "b": "-", "-": "-"}.get(m.group(2), "")
    return m21key.Key(tonic.lower() if m.group(3) else tonic)


def _part(name: str, items, clef_name: str, time_signature: str, key: str | int | None, tempo_bpm: float | None, total_ql: float):
    from music21 import clef, meter, note, stream, tempo

    part = stream.Part()
    part.partName = name
    part.insert(0, clef.TrebleClef() if clef_name == "treble" else clef.BassClef())
    part.insert(0, meter.TimeSignature(time_signature))
    key_obj = _key(key)
    if key_obj is not None:
        part.insert(0, key_obj)
    if tempo_bpm:
        part.insert(0, tempo.MetronomeMark(number=tempo_bpm))
    offset = 0.0
    for item in items:
        part.insert(offset, item)
        offset += item.quarterLength
    if offset < total_ql:
        part.insert(offset, note.Rest(quarterLength=total_ql - offset))
    return part


def build_lesson(
    title: str,
    right: str | None = None,
    left: str | None = None,
    time_signature: str = "4/4",
    key: str | int | None = "C",
    tempo_bpm: float = 80,
    musicxml: str | None = None,
) -> tuple[str, Score]:
    """Create and save a lesson. Returns (path, parsed score)."""
    from music21 import converter, metadata, meter, stream
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    path = lessons_dir() / f"{_slug(title)}.musicxml"
    if musicxml:
        converter.parseData(musicxml)  # raises if it isn't valid MusicXML
        path.write_text(musicxml, encoding="utf-8")
    else:
        if not right and not left:
            raise ValueError("Give at least one hand (right/left) or musicxml.")
        rh = _tiny(right, time_signature) if right else []
        lh = _tiny(left, time_signature) if left else []
        bar_ql = meter.TimeSignature(time_signature).barDuration.quarterLength
        total = max(sum(n.quarterLength for n in rh), sum(n.quarterLength for n in lh))
        total = -(-total // bar_ql) * bar_ql  # round up to whole bars
        _key(key)  # validate before building anything
        score = stream.Score()
        score.metadata = metadata.Metadata(title=title)
        if rh:
            score.insert(0, _part("Right Hand", rh, "treble", time_signature, key, tempo_bpm, total))
        if lh:
            score.insert(0, _part("Left Hand", lh, "bass", time_signature, key, tempo_bpm if not rh else None, total))
        for part in score.parts:
            part.makeMeasures(inPlace=True)
            part.makeNotation(inPlace=True)
        xml = GeneralObjectExporter(score).parse().decode("utf-8")
        path.write_text(xml, encoding="utf-8")
    return str(path), load_score(path)


def excerpt_lesson(reference_path: str, bars: tuple[int, int], hand: str, title: str) -> tuple[str, Score]:
    """Cut bars (and optionally one hand) out of a reference into a new lesson."""
    from music21 import converter, metadata, stream
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    source = converter.parse(reference_path)
    excerpt = source.measures(bars[0], bars[1])
    parts = list(excerpt.parts)
    if hand in ("right", "left") and len(parts) >= 2:
        def mean_pitch(p):
            ps = [pp.midi for n in p.flatten().notes for pp in n.pitches]
            return sum(ps) / len(ps) if ps else 0

        ordered = sorted(parts, key=mean_pitch, reverse=True)
        keep = ordered[0] if hand == "right" else ordered[-1]
        new = stream.Score()
        new.insert(0, keep)
        excerpt = new
    excerpt.metadata = metadata.Metadata(title=title)
    xml = GeneralObjectExporter(excerpt).parse().decode("utf-8")
    path = lessons_dir() / f"{_slug(title)}.musicxml"
    path.write_text(xml, encoding="utf-8")
    return str(path), load_score(path)


def learn_events(score: Score, side) -> list[dict]:
    """Note events for the visualizer's Learn Mode: channel 0 = right hand, 1 = left."""
    return [
        {"ms": round(n.start * 1000, 1), "durationMs": round(max(50.0, n.duration * 1000), 1), "note": n.pitch, "channel": 0 if side(n) == "right" else 1}
        for n in score.notes
    ]


def describe(score: Score, side) -> list[str]:
    """One line per bar listing the notes of each hand, so the author can check the lesson."""
    from .notes import note_name

    lines = []
    for bar in score.bars:
        hands = {"RH": [], "LH": []}
        in_bar = [n for n in score.notes if bar.start - 1e-6 <= n.start < bar.end - 1e-6]
        for label, want in (("RH", "right"), ("LH", "left")):
            groups: dict[float, list[str]] = {}
            for n in in_bar:
                if side(n) == want:
                    groups.setdefault(round(n.beat - bar.start_beat, 3), []).append(note_name(n.pitch))
            hands[label] = ["+".join(v) + f"@{k + 1:g}" for k, v in sorted(groups.items())]
        lines.append(f"{bar.number}: RH {' '.join(hands['RH']) or '-'} | LH {' '.join(hands['LH']) or '-'}")
    return lines
