"""Download other versions of the songs in the reference library from bitmidi.com.

The same song is often on several MIDI sites, sequenced by different people with very
different care: one has the real 16th-note fills, another plays block chords. This looks
up every "Artist - Title [id].mid" under reference/midiworld on bitmidi and saves the
matching versions as reference/bitmidi/<Artist>/<Artist> - <Title> [bitmidi <id>].mid,
so they show up side by side and `midi_coach.detail` can pick the more detailed one.

Polite and resumable: one request at a time with a pause between, and every finished song
is noted in reference/bitmidi/.alternates_done so a rerun carries on where it stopped.
Songs you have opened in the coach (they have files in ~/MidiCoach/derived) go first.

    python tools/fetch_alternates.py              # whole library
    python tools/fetch_alternates.py "Pink Floyd" # only songs whose name contains this
"""

from __future__ import annotations

import hashlib
import io
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import mido

REPO = pathlib.Path(__file__).resolve().parent.parent
SOURCE = REPO / "reference" / "midiworld"
TARGET = REPO / "reference" / "bitmidi"
DONE = TARGET / ".alternates_done"
DERIVED = pathlib.Path.home() / "MidiCoach" / "derived"
API = "https://bitmidi.com/api/midi/search"
SITE = "https://bitmidi.com"
PAUSE = 1.2  # seconds between requests
PAGE = 50  # the API's largest page
ARTIST_PAGES = 2
MAX_VERSIONS = 4  # per song, most viewed first
NOISE = {"the", "a", "mid", "midi", "kar", "k", "v", "version", "ver", "by"}
SKIP_ARTIST_WORDS = {"the", "and", "band", "of", "orchestra", "group"}

_last_request = 0.0


def get(url: str, retries: int = 3) -> bytes | None:
    global _last_request
    for attempt in range(retries):
        wait = PAUSE - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "midi-coach/1.0 (personal practice library)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(3 * (attempt + 1))  # 502s come and go (though a few queries always fail)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(5 * (attempt + 1))
    return None


def search(query: str, pages: int = 1) -> list[dict]:
    out: list[dict] = []
    for page in range(pages):
        qs = urllib.parse.urlencode({"q": query, "page": page, "pageSize": PAGE})
        body = get(f"{API}?{qs}")
        if body is None:
            break
        try:
            results = json.loads(body)["result"]["results"]
        except (ValueError, KeyError):
            break
        out += results
        if len(results) < PAGE:
            break
    return out


def norm(text: str) -> str:
    text = re.sub(r"\.(mid|midi|kar)$", "", text.lower())
    text = text.replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def song_of(path: pathlib.Path) -> tuple[str, str] | None:
    """(artist, title) from 'Artist - Title [123].mid' or 'Artist - Title (2) [123].mid'."""
    stem = re.sub(r"\s*\[\d+\]$", "", path.stem)
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    if " - " not in stem:
        return None
    artist, title = stem.split(" - ", 1)
    # Titles of the form 'Artist - Artist - Title' (a doubled prefix) keep the last part.
    if title.lower().startswith(artist.lower() + " - "):
        title = title[len(artist) + 3:]
    return artist.strip(), title.strip()


def matches(artist: str, title: str, result: dict) -> bool:
    phrase = norm(re.sub(r"\(.*?\)", "", title)) or norm(title)
    if not phrase:
        return False
    artist_words = [w for w in norm(artist).split() if len(w) >= 3 and w not in SKIP_ARTIST_WORDS]
    for name in [result.get("name") or ""] + list(result.get("alternateNames") or []):
        n = f" {norm(name)} "
        if f" {phrase} " not in n:
            continue
        if any(f" {w} " in n for w in artist_words):
            return True
        # No artist in the name: accept only when the name is just the title (plus a
        # version number), and the title is specific enough not to be some other song.
        rest = n.replace(f" {phrase} ", " ", 1).split()
        if len(phrase.split()) >= 2 and all(w in NOISE or w.isdigit() for w in rest):
            return True
    return False


def safe(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", text).strip(" .")


def valid_midi(data: bytes) -> bool:
    if not data.startswith(b"MThd"):
        return False
    try:
        mid = mido.MidiFile(file=io.BytesIO(data))
        return any(m.type == "note_on" and m.velocity > 0 for tr in mid.tracks for m in tr)
    except Exception:  # noqa: BLE001 - any parse failure means a broken file
        return False


def main() -> None:
    only = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    TARGET.mkdir(parents=True, exist_ok=True)
    done = set(DONE.read_text(encoding="utf-8").splitlines()) if DONE.exists() else set()
    have_ids = {int(m.group(1)) for f in TARGET.rglob("*.mid") if (m := re.search(r"\[bitmidi (\d+)\]", f.name))}
    have_hashes = {hashlib.sha1(f.read_bytes()).hexdigest() for f in TARGET.rglob("*.mid")}

    songs: dict[tuple[str, str], pathlib.Path] = {}
    for f in sorted(SOURCE.rglob("*.mid")):
        if "classical" in f.relative_to(SOURCE).parts:
            continue
        song = song_of(f)
        if song and (not only or only in f.stem.lower()):
            songs.setdefault(song, f)
    opened = {p.name.lower() for p in DERIVED.glob("*")} if DERIVED.is_dir() else set()

    def slug(p: pathlib.Path) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", p.stem).strip("-")[:40].lower()

    order = sorted(songs, key=lambda s: (not any(o.startswith(slug(songs[s]) + "-") for o in opened), s))
    todo = [s for s in order if f"{s[0]} - {s[1]}" not in done]
    print(f"{len(songs)} songs, {len(todo)} to look up", flush=True)

    artist_cache: dict[str, list[dict]] = {}
    saved = 0
    for i, (artist, title) in enumerate(todo, 1):
        found = {r["id"]: r for r in search(title) or search(f"{title} {artist}")}
        if artist not in artist_cache:
            artist_cache = {artist: search(artist, ARTIST_PAGES)}  # songs come grouped by artist
        found.update({r["id"]: r for r in artist_cache[artist]})
        hits = sorted((r for r in found.values() if matches(artist, title, r)), key=lambda r: -(r.get("views") or 0))
        new = 0
        for r in hits[:MAX_VERSIONS]:
            if r["id"] in have_ids:
                continue
            data = get(SITE + r["downloadUrl"])
            if not data or not valid_midi(data):
                continue
            digest = hashlib.sha1(data).hexdigest()
            if digest in have_hashes:
                continue
            folder = TARGET / safe(artist)
            folder.mkdir(exist_ok=True)
            (folder / f"{safe(artist)} - {safe(title)} [bitmidi {r['id']}].mid").write_bytes(data)
            have_ids.add(r["id"])
            have_hashes.add(digest)
            new += 1
        saved += new
        with DONE.open("a", encoding="utf-8") as fh:
            fh.write(f"{artist} - {title}\n")
        if new or i % 50 == 0:
            print(f"[{i}/{len(todo)}] {artist} - {title}: +{new} (total new {saved})", flush=True)
    print(f"finished: {saved} new files", flush=True)


if __name__ == "__main__":
    main()
