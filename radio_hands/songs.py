"""From what a station says is playing to the hands' notes: read the title, find the song in the
library (and on bitmidi.com when asked), and get everything the page and the aligner need.

Stations write their titles every which way, so a title is read both ways round:
    "REO Speedwagon - Roll with the Changes"      artist - title
    "IF ONLY I - LOUD LUXURY / BEBE REXHA"        title - artists
    "Cranes in the Sky by Solange"                title by artist
    ". - The Beaches - Edge Of The Earth ~ "      stray punctuation
and ads and station IDs simply aren't found.
"""

from __future__ import annotations

import difflib
import pathlib
import re
import threading
import time
from dataclasses import dataclass, field

from midi_coach import library

FILLER = {"the", "a", "an", "and", "of", "feat", "ft", "featuring", "with", "song", "radio", "edit", "version",
          "remastered", "remaster", "single", "mix", "original", "live", "album", "explicit", "clean", "x", "vs"}
SURE = 0.82           # a match this good is the song
CLOSE = 0.06          # other files this close to the best are offered as other versions
RESCAN_SEC = 120      # look for new files in the library at most this often
SEPARATORS = re.compile(r"\s+[-–—~|:/]\s+|\s+by\s+|\s*\|\s*|\s+/\s*|\s*/\s+", re.I)


def words(text: str) -> list[str]:
    text = re.sub(r"\[[^\]]*\]|\.(mid|midi|kar|mxl|musicxml|xml)$", " ", text or "", flags=re.I)
    text = text.replace("&", " and ").replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def key_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in FILLER] or words(text)


def clean_title(raw: str) -> str:
    """The station's text without the wrapping some add (quotes, leading dots, tildes, 'SONG')."""
    t = (raw or "").strip().strip("'\"").strip()
    t = re.sub(r"^\W+|\W+$", "", t)
    t = re.sub(r"\s{2,}(SONG|MUSIC)$", "", t)
    t = re.sub(r"\((radio edit|edit|clean|explicit|remaster(ed)?( \d{4})?)\)", "", t, flags=re.I)
    return re.sub(r"\s{2,}", " ", t).strip()


def readings(raw: str) -> list[tuple[str, str]]:
    """(artist, title) pairs the station's text could mean, likeliest first. A bare title gives
    ('', title)."""
    t = clean_title(raw)
    if not t:
        return []
    out: list[tuple[str, str]] = []
    by = re.match(r"^(.+?)\s+by\s+(.+)$", t, re.I)
    if by:
        out.append((by.group(2), by.group(1)))
    parts = [p.strip() for p in re.split(r"\s+[-–—~]\s+", t) if p.strip()]
    if len(parts) >= 2:
        for i in range(1, len(parts)):
            a, b = " - ".join(parts[:i]), " - ".join(parts[i:])
            out.append((a, b))   # artist - title
            out.append((b, a))   # title - artist
    out.append(("", t))
    seen, unique = set(), []
    for a, b in out:
        a = re.split(r"\s*/\s*|\s+feat\.?\s+|\s+ft\.?\s+|\s*,\s*", a, flags=re.I)[0] if a else a
        k = (a.lower(), b.lower())
        if k not in seen:
            seen.add(k)
            unique.append((a, b))
    return unique


def _artist_title(path: pathlib.Path) -> tuple[str, str]:
    """A library file's artist and title, from 'Artist - Title [id].mid' or its folder."""
    stem = re.sub(r"\s*\[[^\]]*\]\s*$", "", path.stem)
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist, title
    folder = path.parent.name
    return (folder if folder.lower() not in {"bitmidi", "midiworld", "downloads", "references"} else ""), stem


def _likeness(asked: str, have: str) -> float:
    """How alike two names read, 0-1: every key word of the shorter in the longer counts as a
    match (stations shorten titles: 'This Town Aint Big Enough For')."""
    a, h = key_words(asked), key_words(have)
    if not a or not h:
        return 0.0
    sa, sh = set(a), set(h)
    small, big = (sa, sh) if len(sa) <= len(sh) else (sh, sa)
    if small <= big:
        cover = len(small) / len(big)
        # a whole title inside a longer one: sure when the shorter has a few words of its own
        return 1.0 if cover == 1 else (0.9 if len(small) >= 3 else 0.7 + 0.2 * cover)
    return difflib.SequenceMatcher(None, " ".join(a), " ".join(h)).ratio()


@dataclass
class Match:
    path: str
    name: str
    score: float
    others: list[dict] = field(default_factory=list)  # other versions: {path, name, score}


class Library:
    """The song files, indexed by the words of their titles, rescanned now and then."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.files: list[tuple[pathlib.Path, str, str]] = []
        self.by_word: dict[str, list[int]] = {}
        self.scanned = 0.0

    def refresh(self, force: bool = False) -> None:
        with self.lock:
            if not force and time.time() - self.scanned < RESCAN_SEC and self.files:
                return
            files = []
            by_word: dict[str, list[int]] = {}
            for p in library.scan_references():
                if p.suffix.lower() not in {".mid", ".midi", ".kar"}:
                    continue
                artist, title = _artist_title(p)
                i = len(files)
                files.append((p, artist, title))
                for w in set(key_words(title)):
                    by_word.setdefault(w, []).append(i)
            self.files, self.by_word, self.scanned = files, by_word, time.time()

    def find(self, raw: str) -> Match | None:
        """The library's file for what the station says is playing, or None."""
        self.refresh()
        pairs = readings(raw)
        if not pairs:
            return None
        scored: dict[int, float] = {}
        for artist, title in pairs:
            cands = set()
            for w in key_words(title):
                cands.update(self.by_word.get(w, ()))
            for i in cands:
                p, f_artist, f_title = self.files[i]
                t = _likeness(title, f_title)
                if t < 0.75:
                    continue
                if artist and f_artist:
                    a = _likeness(artist, f_artist)
                    s = t * (0.55 + 0.45 * a) if a >= 0.6 else t * 0.5
                elif artist:  # the file doesn't say who: only a long, exact title will do
                    s = t * (0.9 if len(key_words(f_title)) >= 3 else 0.7)
                else:  # the station gave no artist
                    s = t * (0.88 if len(key_words(f_title)) >= 2 else 0.7)
                if s > scored.get(i, 0):
                    scored[i] = s
        if not scored:
            return None
        ranked = sorted(scored.items(), key=lambda kv: (-kv[1], len(str(self.files[kv[0]][0]))))
        best_i, best = ranked[0]
        if best < SURE:
            return None
        others = [{"path": str(self.files[i][0]), "name": self.files[i][0].stem, "score": round(s, 2)}
                  for i, s in ranked[1:8] if s >= max(SURE, best - CLOSE)]
        p = self.files[best_i][0]
        return Match(path=str(p), name=p.stem, score=round(best, 2), others=others)


def find_online(raw: str) -> Match | None:
    """A bitmidi.com file for the song, downloaded into the library. Only one whose name says the
    same artist and title is taken."""
    from midi_coach import online

    for artist, title in readings(raw)[:4]:
        if not artist or len(key_words(title)) < 1:
            continue
        try:
            results = online.search(f"{artist} {title}", limit=10)
        except ConnectionError:
            return None
        for r in results:
            name = r["title"]
            f_artist, f_title = (name.split(" - ", 1) + [""])[:2] if " - " in name else ("", name)
            if not f_artist or _likeness(artist, f_artist) < 0.8 or _likeness(title, f_title) < 0.9:
                continue
            path = r.get("path") or online.download(r["id"])
            return Match(path=str(path), name=pathlib.Path(path).stem, score=0.9)
    return None


# -- the song's notes, for the page and the aligner -------------------------------------------

TIMELINE_STEP = 0.05  # seconds between the samples of the file's time -> beat map


def prepare(path: str) -> dict:
    """Everything about a song file the app needs: the falling notes with fingers (as the coach
    page gets them, with Clean so the hands can play them), its bars, its time -> beat map, and
    every pitched note for lining it up with the radio."""
    from midi_coach import display, playable

    score = library.get_score(path)
    drums = {p.index for p in score.parts if p.drums}
    sounding = [(n.start, n.end, n.pitch, n.velocity) for n in score.notes if n.part not in drums]
    if score.playing:  # a part named for another instrument: the radio app plays the hands
        score.playing = None
    if score.clean is None:
        try:
            score = playable.apply(score)
        except Exception:  # noqa: BLE001 - Clean is a nicety; the file as it is still plays
            pass
    notes = display.roll_notes(score)
    end = max([n.end for n in score.notes] + [1.0]) + 2.0
    count = int(end / TIMELINE_STEP) + 2
    timeline = [round(score.beat_of(i * TIMELINE_STEP), 4) for i in range(count)]
    bars = [{"number": b.number, "start_beat": round(b.start_beat, 4), "end_beat": round(b.end_beat, 4)}
            for b in score.bars]
    from . import drums as drummod

    kit = sorted([round(n.start, 3), lane] for n in score.notes if n.part in drums
                 if (lane := drummod.gm_lane(n.pitch)) is not None)
    hands = sum(1 for n in notes if n[3] in ("right", "left"))
    return {"path": str(path), "name": pathlib.Path(path).stem, "notes": notes, "bars": bars,
            "timeline": timeline, "step": TIMELINE_STEP, "duration": round(end - 2.0, 3),
            "hand_notes": hands, "sounding": sounding, "drums": kit}
