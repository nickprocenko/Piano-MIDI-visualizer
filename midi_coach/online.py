"""Songs from bitmidi.com, for the Songs panel: search by title, download one into the library.

A download is saved as <home>/references/bitmidi/<Name> [bitmidi <id>].mid, the same naming
as tools/fetch_alternates.py, so the library search finds it next time and a second click on
the same result opens the copy already there. Nothing is fetched until the user asks.
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

import mido

from . import library

API = "https://bitmidi.com/api/midi/search"
SITE = "https://bitmidi.com"
USER_AGENT = "midi-coach/1.0 (personal practice library)"
TIMEOUT_SEC = 15
PAGE = 50  # the API's largest page

_seen: dict[int, dict] = {}  # id -> result, from the last searches (its download link and name)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
            return res.read()
    except urllib.error.HTTPError as exc:
        raise ConnectionError(f"bitmidi.com answered {exc.code}. Try again in a moment.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectionError("Couldn't reach bitmidi.com. Check the internet connection.") from exc


def _words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\.(mid|midi|kar)$", "", text.lower())).split()


def _have() -> dict[int, str]:
    """bitmidi id -> path, for the files already in the library."""
    out: dict[int, str] = {}
    for f in library.scan_references():
        if m := re.search(r"\[bitmidi (\d+)\]", f.name):
            out.setdefault(int(m.group(1)), str(f))
    return out


def search(query: str, limit: int = 20) -> list[dict]:
    """bitmidi's results for `query`, those naming its rarer words first (the site also
    returns songs that share only one word, like every '... Theme'), most viewed next."""
    words = _words(query)
    if not words:
        return []
    body = _get(f"{API}?{urllib.parse.urlencode({'q': query, 'page': 0, 'pageSize': PAGE})}")
    try:
        results = json.loads(body)["result"]["results"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ConnectionError("bitmidi.com sent something unexpected. Try again later.") from exc
    matched = []
    for r in results:
        names = [r.get("name") or ""] + list(r.get("alternateNames") or [])
        matched.append({w for n in names for w in _words(n)} & set(words))
    # A word most results share ('theme') says less than a rare one ('halloween').
    share = {w: sum(w in m for m in matched) for w in words}
    scored = [(sum(1 / share[w] for w in m), r.get("views") or 0, len(m), r) for m, r in zip(matched, results) if m]
    scored.sort(key=lambda s: (-s[0], -s[1]))
    have = _have()
    out = []
    for _, views, hit, r in scored[:limit]:
        _seen[int(r["id"])] = r
        out.append({"id": int(r["id"]), "title": re.sub(r"\.(mid|midi|kar)$", "", r.get("name") or "", flags=re.I),
                    "views": views, "all_words": hit == len(set(words)), "path": have.get(int(r["id"]))})
    return out


def _safe(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip(" .")[:120] or "Untitled"


def _valid_midi(data: bytes) -> bool:
    if not data.startswith(b"MThd"):
        return False
    try:
        mid = mido.MidiFile(file=io.BytesIO(data))
    except Exception:  # noqa: BLE001 - any parse failure means a broken file
        return False
    return any(m.type == "note_on" and m.velocity > 0 for tr in mid.tracks for m in tr)


def download(song_id: int) -> str:
    """Save bitmidi song `song_id` into the library (or find the copy already there); its path."""
    song_id = int(song_id)
    if path := _have().get(song_id):
        return path
    r = _seen.get(song_id) or {}
    link = r.get("downloadUrl") or f"/uploads/{song_id}.mid"
    if not link.startswith("/"):
        raise ValueError("That isn't a bitmidi.com download.")
    data = _get(SITE + link)
    if not _valid_midi(data):
        raise ValueError("That file on bitmidi.com isn't a MIDI file with notes in it.")
    folder = library.home() / "references" / "bitmidi"
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"\.(mid|midi|kar)$", "", r.get("name") or f"bitmidi {song_id}", flags=re.I)
    path = folder / f"{_safe(name)} [bitmidi {song_id}].mid"
    path.write_bytes(data)
    return str(path)
