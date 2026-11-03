"""Custom lessons: build MusicXML from compact notation or excerpt a reference.

Lessons are saved to <home>/lessons/<category>/<slug>.musicxml, so they are also normal
references for recording, comparison and progress tracking. Each category is a folder
(CATEGORIES first, then any the user makes); files directly in <home>/lessons are 'Unsorted'.

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

import json
import pathlib
import re
import shutil
import time

from .engraving import tidy_heading
from .library import _choices_path, _load_choices, profile_home
from .notes import MIDI_SUFFIXES, MUSICXML_SUFFIXES, Score, load_score, select_notes

_KEY_RE = re.compile(r"^([A-Ga-g])([#b-]?)(m|min|minor)?$")

# Groups in the coach page's Songs / Lessons panel, in order. Any other folder under lessons/ is a category too.
# Needs review: lessons made from a file (e.g. songs converted from MIDI) nobody has checked yet.
# Exercises: cut from real pieces. AI exercises: composed entirely by Claude or the Maestro.
CATEGORIES = ("Needs review", "Solo piano", "Vocals & accompaniment", "Exercises", "AI exercises", "Recordings")
NEEDS_REVIEW, EXERCISES, AI_EXERCISES, RECORDINGS = "Needs review", "Exercises", "AI exercises", "Recordings"
# Categories holding lessons (teaching material) rather than songs; the coach page lists the
# two apart.
LESSON_CATEGORIES = (EXERCISES, AI_EXERCISES)
UNSORTED = "Unsorted"
LESSON_SUFFIXES = MUSICXML_SUFFIXES | MIDI_SUFFIXES


def lessons_dir(category: str | None = None) -> pathlib.Path:
    path = profile_home() / "lessons"
    if category and category != UNSORTED:
        path = path / _category_folder(category)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _category_folder(category: str) -> str:
    """The folder for a category: a known one matched without case, else the name made safe."""
    for known in CATEGORIES:
        if category.strip().lower() == known.lower():
            return known
    name = re.sub(r'[<>:"/\\|?*]+', "", category).strip(" .")
    if not name:
        raise ValueError(f"Not a usable category name: {category!r}")
    return name


def list_lessons() -> list[dict]:
    """Every lesson, newest first, with its category (the folder it's in). A playlist folder's
    pieces come in the playlist's order instead, each with its `track` number."""
    root = lessons_dir()
    found = []
    for p in [root, *sorted(d for d in root.iterdir() if d.is_dir())]:
        category = UNSORTED if p == root else p.name
        found += [(f, category) for f in p.iterdir() if f.is_file() and f.suffix.lower() in LESSON_SUFFIXES]
    found.sort(key=lambda fc: -fc[0].stat().st_mtime)
    listed = [{"title": f.stem, "path": str(f), "category": c, "source": source_note(f)} for f, c in found]
    for category in {item["category"] for item in listed} - {UNSORTED}:
        tracks = playlist_files(root / category)
        if not tracks:
            continue
        slots = [i for i, item in enumerate(listed) if item["category"] == category]
        rank = {str(f): n for n, f in enumerate(tracks)}
        mine = sorted((listed[i] for i in slots), key=lambda item: rank[item["path"]])
        for n, (i, item) in enumerate(zip(slots, mine), 1):
            listed[i] = {**item, "track": n}
    return listed


# A category folder holding this file is a playlist: {"name", "entries": [{"file", "song", "part",
# "source"}], "missing": [...]}, its pieces in order (midi_coach.playlist writes it).
PLAYLIST_FILE = "playlist.json"


def read_playlist(folder) -> dict | None:
    try:
        return json.loads((pathlib.Path(folder) / PLAYLIST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def playlist_files(folder) -> list[pathlib.Path]:
    """A playlist folder's pieces in order: those it lists, then any others by name. Empty if
    the folder isn't a playlist."""
    folder = pathlib.Path(folder)
    playlist = read_playlist(folder)
    if playlist is None:
        return []
    listed = [folder / e["file"] for e in playlist.get("entries", [])]
    here = {f.name for f in folder.iterdir() if f.is_file() and f.suffix.lower() in LESSON_SUFFIXES}
    named = [f for f in listed if f.name in here]
    return named + sorted((folder / n for n in here - {f.name for f in named}), key=lambda f: f.name.lower())


def playlist_position(path) -> dict | None:
    """Where a piece sits in its folder's playlist: {"playlist", "track", "total", "previous",
    "next"} (previous / next are paths or None), or None if it isn't in one."""
    p = pathlib.Path(path)
    files = playlist_files(p.parent)
    keys = [str(f).lower() for f in files]
    if str(p).lower() not in keys:
        return None
    i = keys.index(str(p).lower())
    playlist = read_playlist(p.parent) or {}
    return {"playlist": playlist.get("name") or p.parent.name, "track": i + 1, "total": len(files),
            "previous": str(files[i - 1]) if i else None, "next": str(files[i + 1]) if i + 1 < len(files) else None}


_SOURCE_RE = re.compile(r"<source>(.*?)</source>", re.S)


def source_note(path) -> str | None:
    """Where a lesson came from (MusicXML <identification><source>), e.g. 'X.mid, converted
    from MIDI: ...', or None. Only the file's head is read."""
    import html

    p = pathlib.Path(path)
    if p.suffix.lower() not in (".xml", ".musicxml"):
        return None
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            head = f.read(8192)
    except OSError:
        return None
    m = _SOURCE_RE.search(head)
    return html.unescape(" ".join(m.group(1).split())) if m else None


def made_from(source: str | None) -> str | None:
    """A short tag for the menu: 'from MIDI' when the notes were converted from a MIDI file."""
    return "from MIDI" if source and "from MIDI" in source else None


def categories(listed: list[dict]) -> list[str]:
    """Menu order: the standard categories, then the user's own, then Unsorted (empty ones left out)."""
    used = {item["category"] for item in listed}
    extra = sorted(used - set(CATEGORIES) - {UNSORTED}, key=str.lower)
    return [c for c in (*CATEGORIES, *extra, UNSORTED) if c in used]


def move_lesson(source: str, category: str, title: str | None = None) -> str:
    """Move a lesson (or any reference file) into a category, optionally renaming it. Takes and
    the saved part choice that point at the old path are updated, so progress history follows."""
    old = pathlib.Path(source).resolve()
    if not old.is_file():
        raise FileNotFoundError(f"No lesson file {source}")
    name = re.sub(r'[<>:"/\\|?*]+', "", title).strip(" .") if title else old.stem
    new = lessons_dir(category).resolve() / f"{name or old.stem}{old.suffix}"
    if new.exists() and new.resolve() == old:  # the same file: nothing to do, or only its capitals change
        if new.name == old.name:
            return str(old)
        step = old.with_name(old.name + ".renaming")  # Windows won't rename to a name differing only in case
        old.rename(step)
        step.rename(new)
    elif new.exists():
        raise FileExistsError(f"{new.name} is already in {category}.")
    else:
        old.rename(new)
    _repoint(str(old), str(new))
    return str(new)


def _file_name(title: str | None, fallback: str) -> str:
    return (re.sub(r'[<>:"/\\|?*]+', "", title).strip(" .") if title else "") or fallback


def copy_lesson(source: str, category: str, title: str | None = None) -> str:
    """Save a copy of a lesson or reference into a category (the coach page's File → Save as).
    The copy takes the original's part choice; its practice history starts empty."""
    old = pathlib.Path(source).resolve()
    if not old.is_file():
        raise FileNotFoundError(f"No lesson file {source}")
    new = lessons_dir(category).resolve() / f"{_file_name(title, old.stem)}{old.suffix}"
    if new.exists():
        raise FileExistsError(f"{new.name} is already in {category}.")
    shutil.copy2(old, new)
    choices = _load_choices()
    if str(old) in choices:
        choices[str(new)] = choices[str(old)]
        _choices_path().write_text(json.dumps(choices, indent=2), encoding="utf-8")
    return str(new)


def import_file(name: str, data: bytes, category: str = UNSORTED) -> str:
    """Keep a MIDI or MusicXML file opened from the computer (File → Open) among the lessons.
    Opening the same file again reuses the copy; a different file with the same name gets ' (2)'."""
    p = pathlib.Path(name)
    if p.suffix.lower() not in LESSON_SUFFIXES:
        raise ValueError(f"{p.name} isn't a MIDI or MusicXML file.")
    folder = lessons_dir(category).resolve()
    stem = _file_name(p.stem, "Opened file")
    for n in range(1, 100):
        new = folder / f"{stem}{f' ({n})' if n > 1 else ''}{p.suffix.lower()}"
        if not new.exists():
            new.write_bytes(data)
            return str(new)
        if new.read_bytes() == data:
            return str(new)
    raise FileExistsError(f"Too many files called {p.name} in {category}.")


def _repoint(old: str, new: str) -> None:
    def swap(value):
        if isinstance(value, str):
            return new if value == old else value
        if isinstance(value, list):
            return [swap(v) for v in value]
        if isinstance(value, dict):
            return {k: swap(v) for k, v in value.items()}
        return value

    for f in (profile_home() / "takes").glob("*.json"):
        text = f.read_text(encoding="utf-8")
        if json.dumps(old)[1:-1] not in text:
            continue
        f.write_text(json.dumps(swap(json.loads(text)), indent=2), encoding="utf-8")
    choices = _load_choices()
    if old in choices:
        choices[new] = choices.pop(old)
        _choices_path().write_text(json.dumps(choices, indent=2), encoding="utf-8")
    old_p, new_p = pathlib.Path(old), pathlib.Path(new)
    playlist = read_playlist(old_p.parent)
    if playlist and any(e.get("file") == old_p.name for e in playlist.get("entries", [])):
        # Renamed in place: the entry follows it. Moved to another folder: it leaves the playlist.
        same = new_p.parent == old_p.parent
        playlist["entries"] = [{**e, "file": new_p.name} if e.get("file") == old_p.name and same else e
                               for e in playlist["entries"] if same or e.get("file") != old_p.name]
        (old_p.parent / PLAYLIST_FILE).write_text(json.dumps(playlist, indent=2), encoding="utf-8")


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
            "sharps f#, flats b- (after octave marks: c'#, not c#'), durations 1 2 4 8 16 with dots, "
            "rests r4, chords chord{c4 e g}."
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
    category: str = AI_EXERCISES,
    out_dir: str | pathlib.Path | None = None,
    filename: str | None = None,
    part_name: str | None = None,
) -> tuple[str, Score]:
    """Create and save a lesson. Returns (path, parsed score). out_dir: write it there (e.g.
    the Atlas's lesson folder) instead of a category of the page's lesson panel; filename: its
    name there (without .musicxml) when the title isn't one. part_name: the treble part's
    name when it isn't a right hand (a flute line is 'Flute')."""
    from music21 import converter, metadata, meter, stream
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    folder = pathlib.Path(out_dir) if out_dir else lessons_dir(category)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{filename or _slug(title)}.musicxml"
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
            score.insert(0, _part(part_name or "Right Hand", rh, "treble", time_signature, key, tempo_bpm, total))
        if lh:
            score.insert(0, _part("Left Hand", lh, "bass", time_signature, key, tempo_bpm if not rh else None, total))
        from .transcribe import _print_accidentals

        for part in score.parts:
            part.makeMeasures(inPlace=True)
            part.makeNotation(inPlace=True)
            _print_accidentals(part)  # music21 prints a sharp again on a repeat in the bar; the standard rule doesn't
        xml = tidy_heading(GeneralObjectExporter(score).parse().decode("utf-8"))
        path.write_text(xml, encoding="utf-8")
    return str(path), load_score(path)


def excerpt_lesson(reference_path: str, bars: tuple[int, int], hand: str, title: str, category: str = EXERCISES) -> tuple[str, Score]:
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
    xml = tidy_heading(GeneralObjectExporter(excerpt).parse().decode("utf-8"))
    path = lessons_dir(category) / f"{_slug(title)}.musicxml"
    path.write_text(xml, encoding="utf-8")
    return str(path), load_score(path)


def learn_events(score: Score, side) -> list[dict]:
    """Note events for the visualizer's Learn Mode: channel 0 = right hand, 1 = left. beat (quarter
    notes, as the sheet counts them) lets its sheet follow the music through tempo changes."""
    return [
        {"ms": round(n.start * 1000, 1), "durationMs": round(max(50.0, n.duration * 1000), 1), "note": n.pitch,
         "channel": 0 if side(n) == "right" else 1, "beat": round(n.beat, 4)}
        for n in select_notes(score)[0]  # drums and parts the user left out don't belong in Learn Mode
    ]


def key_spelling(key: str | int | None) -> str | None:
    """'sharps' / 'flats' to match a lesson key, None if unknown or C major / A minor."""
    try:
        k = _key(key)
    except ValueError:
        return None
    sharps = getattr(k, "sharps", 0) if k is not None else 0
    return "sharps" if sharps > 0 else "flats" if sharps < 0 else None


def describe(score: Score, side, spelling: str | None = None) -> list[str]:
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
                    groups.setdefault(round(n.beat - bar.start_beat, 3), []).append(note_name(n.pitch, spelling))
            hands[label] = ["+".join(v) + f"@{k + 1:g}" for k, v in sorted(groups.items())]
        lines.append(f"{bar.number}: RH {' '.join(hands['RH']) or '-'} | LH {' '.join(hands['LH']) or '-'}")
    return lines
