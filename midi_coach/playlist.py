"""Playlists: a lesson category whose pieces play in a set order, like an album's songs.

`build_playlist` takes song titles in order, finds each in the reference library, and gives
every keyboard part of every song its own entry (notes.keyboard_parts: pianos, organs and
synths, one at a time). An entry is a byte-for-byte copy of the song's MIDI file with its
part choice set to that keyboard, so the sheet shows that part, grading follows it, and the
rest of the band plays along. Nothing about the notes changes.

The folder gets "NN Song – part.mid" files and a playlist.json listing them (lessons.py reads
it to order the Songs panel; the coach page steps through it with ◀ ▶).

    python -m midi_coach.playlist "Dark Side of the Moon" --artist "Pink Floyd" Breathe "On the Run" Time
    python -m midi_coach.playlist "My list" "Some Song=C:/path/to/version.mid"

A song given as "Title=path" uses that file; otherwise, of the files whose name has the
artist and every word of the title, the one with the most keyboard notes.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil

from . import library, lessons
from .notes import _KEYBOARD_NAME, Score, keyboard_parts

_COMMON = {"the", "a", "an", "of", "in", "to", "and"}


def _words(text: str) -> set[str]:
    return set(library._norm(text).split())


def candidates(title: str, artist: str | None = None) -> list[pathlib.Path]:
    """Library files (not saved lessons) named with every word of the title, and the artist."""
    want = _words(title) - _COMMON or _words(title)
    who = _words(artist or "")
    root = str(lessons.lessons_dir().resolve()).lower()
    found = []
    for f in library.scan_references():
        name = _words(f.stem)
        if want <= name and who <= name and not str(f.resolve()).lower().startswith(root):
            found.append(f)
    return found


def keyboard_notes(score: Score) -> int:
    counts = {p.index: p.note_count for p in score.parts}
    return sum(counts[i] for group in keyboard_parts(score) for i in group)


def part_label(score: Score, group: dict[int, str]) -> str:
    """What to call a keyboard part: its track name when that names a keyboard ("Organ",
    "electric piano"), else its instrument."""
    p = next(q for q in score.parts if q.index == next(iter(group)))
    words = [w for w in p.name.split() if re.fullmatch(r"[A-Za-z][A-Za-z&.'-]*", w)]
    name = " ".join(words)
    label = name if _KEYBOARD_NAME.search(name.lower()) else p.instrument
    return label[:1].upper() + label[1:]


def build_playlist(name: str, songs: list[str], artist: str | None = None, replace: bool = False) -> dict:
    """Make the playlist `name` (a lesson category) from `songs` in order; see the module notes.
    An existing playlist of that name is rebuilt only with `replace`."""
    folder = lessons.lessons_dir(name)
    old = [f for f in folder.iterdir() if f.is_file()]
    if old and not (replace and lessons.read_playlist(folder) is not None):
        raise FileExistsError(f"{folder.name} already has files." + (" Pass replace=True to rebuild the playlist."
                                                                     if lessons.read_playlist(folder) is not None else
                                                                     " Pick another name: it isn't a playlist."))
    for f in lessons.playlist_files(folder):  # a rebuild: the old copies and their part choices go
        library.save_hands(library.get_score(str(f)), {})
        f.unlink()
    entries, missing, report = [], [], []
    for song in songs:
        title, _, given = song.partition("=")
        title = title.strip()
        files = [pathlib.Path(given.strip())] if given.strip() else candidates(title, artist)
        scored = sorted(((keyboard_notes(library.get_score(str(f))), f) for f in files), key=lambda x: (-x[0], x[1].name))
        if not scored or not scored[0][0]:
            missing.append(title)
            report.append({"song": title, "missing": "no file" if not scored else "no keyboard part in " + ", ".join(f.name for _, f in scored)})
            continue
        source = scored[0][1]
        score = library.get_score(str(source))
        used = {}
        for group in keyboard_parts(score):
            label = part_label(score, group)
            used[label] = used.get(label, 0) + 1
            if used[label] > 1:
                label = f"{label} ({used[label]})"
            stem = re.sub(r'[<>:"/\\|?*]+', "", f"{len(entries) + 1:02d} {title} – {label}").strip(" .")
            copy = folder / f"{stem}{source.suffix.lower()}"
            shutil.copy2(source, copy)
            library.save_hands(library.get_score(str(copy)), group)
            entries.append({"file": copy.name, "song": title, "part": label, "parts": sorted(group),
                            "source": str(source)})
        report.append({"song": title, "source": source.name, "parts": [e["part"] for e in entries if e["song"] == title],
                       "other_versions": [f"{f.name} ({n} keyboard notes)" for n, f in scored[1:]]})
    playlist = {"name": name, "entries": entries, "missing": missing}
    (folder / lessons.PLAYLIST_FILE).write_text(json.dumps(playlist, indent=2), encoding="utf-8")
    return {"folder": str(folder), "entries": len(entries), "songs": report, "missing": missing}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build a playlist of every keyboard part of the songs given, in order.")
    ap.add_argument("name", help="the playlist (a lesson category)")
    ap.add_argument("songs", nargs="+", help='song titles in order; "Title=path" picks the file')
    ap.add_argument("--artist", help="only files whose name has the artist")
    ap.add_argument("--replace", action="store_true", help="rebuild an existing playlist")
    args = ap.parse_args(argv)
    out = build_playlist(args.name, args.songs, args.artist, args.replace)
    for s in out["songs"]:
        if "missing" in s:
            print(f"{s['song']}: MISSING ({s['missing']})")
            continue
        print(f"{s['song']}: {s['source']}\n    parts: {', '.join(s['parts'])}")
        for alt in s["other_versions"]:
            print(f"    also: {alt}")
    print(f"{out['entries']} entries -> {out['folder']}")


if __name__ == "__main__":
    main()
