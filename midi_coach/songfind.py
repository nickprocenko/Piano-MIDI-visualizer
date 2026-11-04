"""The Maestro's open_song: find a song by name wherever it is, or send a link to it.

In order:
  1. the library (the song folders, ~/MidiCoach/references, the profile's lessons);
  2. the Downloads folder (top level only), where a file from MuseScore or a website lands: a
     match is copied into <home>/references/downloads so the library has it from then on;
  3. bitmidi.com, when online search is on (File → Song folders), only a result naming every
     word asked for, downloaded like the Songs panel's button;
  4. none of those: a MuseScore search link for the Maestro panel (MuseScore needs a sign-in to
     download, so the pianist fetches it there and asks again).
"""

from __future__ import annotations

import difflib
import os
import pathlib
import re
import shutil
import urllib.parse

from . import library, online

FILLER = {"the", "song", "piece", "tune", "by", "please", "play", "open", "load", "put", "on", "my", "from", "musescore"}
SURE_RATIO = 0.85  # a whole-name likeness this close counts as the song, even with a word off
CLOSE = 0.1        # two matches this close in score: ask which


def downloads_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MIDI_COACH_DOWNLOADS") or pathlib.Path.home() / "Downloads")


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\.(mid|midi|kar|mxl|musicxml|xml)$", "", (text or "").lower())).split()


def score(query: str, name: str) -> float:
    """How surely a file called `name` is the song asked for, 0-1: 1 when every word asked
    (fillers aside) is in its name, else how alike the two read."""
    asked = [w for w in _words(query) if w not in FILLER] or _words(query)
    have = set(_words(name))
    if asked and set(asked) <= have:
        return 1.0
    return difflib.SequenceMatcher(None, " ".join(asked), " ".join(_words(name))).ratio()


def _best(query: str, files: list[pathlib.Path]) -> list[tuple[float, pathlib.Path]]:
    scored = sorted(((score(query, f.stem), f) for f in files), key=lambda s: (-s[0], len(s[1].stem)))
    return [s for s in scored if s[0] >= SURE_RATIO]


def _pick(hits: list[tuple[float, pathlib.Path]]) -> dict | None:
    if not hits:
        return None
    if len(hits) > 1 and hits[0][0] < 1.0 and hits[0][0] - hits[1][0] < CLOSE:
        return {"ask": [f.stem for _, f in hits[:4]]}
    return {"path": str(hits[0][1])}


def in_downloads() -> list[pathlib.Path]:
    folder = downloads_dir()
    try:
        return [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in library.REF_SUFFIXES]
    except OSError:
        return []


def keep(path: pathlib.Path) -> pathlib.Path:
    """Copy a file from Downloads into the library (or find the copy already there)."""
    folder = library.home() / "references" / "downloads"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    if not target.exists():
        shutil.copy2(path, target)
    return target


def link(name: str, artist: str = "") -> str:
    return "https://musescore.com/sheetmusic?" + urllib.parse.urlencode({"text": " ".join(filter(None, [name, artist]))})


def find(name: str, artist: str = "") -> dict:
    """Where the song is: {path, where} (library / downloads / bitmidi), {ask: [names]} when two
    files fit about as well, or {link} when it can't be had here."""
    name = (name or "").strip()
    if not name:
        return {"error": "Which song?"}
    picked = _pick(_best(name, library.scan_references()))
    if picked:
        return {**picked, "where": "library"}
    picked = _pick(_best(name, in_downloads()))
    if picked:
        if "path" in picked:
            picked["path"] = str(keep(pathlib.Path(picked["path"])))
        return {**picked, "where": "downloads"}
    tried_online = ""
    if library.song_sources()["online"]:
        try:
            exact = [r for r in online.search(" ".join(filter(None, [name, artist]))) if r["all_words"]]
            if not exact and artist:  # an upload's name often leaves the artist out
                exact = [r for r in online.search(name) if r["all_words"]]
            if exact:
                return {"path": exact[0]["path"] or online.download(exact[0]["id"]), "where": "bitmidi",
                        "title": exact[0]["title"]}
            tried_online = "bitmidi.com has no file by that name"
        except (ConnectionError, ValueError) as exc:
            tried_online = str(exc)
    return {"link": link(name, artist), "not_found": True, "tried_online": tried_online}
