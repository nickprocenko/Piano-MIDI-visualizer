"""Chord charts (Ultimate Guitar) and YouTube search, for cross-referencing a piece.

Python port of Music Practice's `UltimateGuitarClient`, `ChordSheet` and `YouTubeSearch`
(themselves ports of Band HQ's `api/_ug-client.js`, `ug-tab.js` and `yt-search.js`).
Standard library only; every call is a plain HTTPS GET.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_SEC = 10
UG_API = "https://api.ultimate-guitar.com/api/v1"
UG_USER_AGENT = "UGT_ANDROID/4.11.1 (Pixel; 8.1.0)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# The `type[]` ids of UG's mobile search API.
TAB_TYPES = {"chords": 300, "tabs": 200, "bass": 400, "ukulele": 800, "drums": 700, "guitar pro": 500, "power": 600}
_TYPE_NAMES = {v: k for k, v in TAB_TYPES.items()}


class WebError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _get(url: str, headers: dict[str, str]) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
            return res.status, res.headers.get("Content-Type", ""), res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise WebError(0, f"Network error: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Ultimate Guitar
# ---------------------------------------------------------------------------


def ug_api_key(device_id: str, now_utc: datetime.datetime) -> str:
    payload = f"{device_id}{now_utc:%Y-%m-%d}:{now_utc.hour}createLog()"
    return hashlib.md5(payload.encode()).hexdigest()


def _ug_fetch(path: str, params: list[tuple[str, str]]) -> dict:
    device_id = secrets.token_hex(8)
    headers = {
        "Accept": "application/json",
        "Accept-Charset": "utf-8",
        "User-Agent": UG_USER_AGENT,
        "X-UG-CLIENT-ID": device_id,
        "X-UG-API-KEY": ug_api_key(device_id, datetime.datetime.now(datetime.timezone.utc)),
    }
    status, ctype, body = _get(f"{UG_API}{path}?{urllib.parse.urlencode(params)}", headers)
    if "application/json" not in ctype:
        raise WebError(status, f"Ultimate Guitar returned non-JSON ({status}). Possibly rate limited.")
    if not 200 <= status < 300:
        raise WebError(status, f"Ultimate Guitar error {status}: {body[:200]}")
    return json.loads(body)


def _type_name(tab: dict) -> str:
    return tab.get("type_name") or _TYPE_NAMES.get(tab.get("type"), "").title() or str(tab.get("type") or "Chords")


def parse_summary(tab: dict) -> dict | None:
    if tab.get("id") is None:
        return None
    return {
        "tab_id": tab["id"],
        "song": tab.get("song_name", ""),
        "artist": tab.get("artist_name", ""),
        "type": _type_name(tab),
        "version": tab.get("version"),
        "rating": round(tab["rating"], 2) if isinstance(tab.get("rating"), (int, float)) else None,
        "votes": tab.get("votes"),
        "key": tab.get("tonality_name") or None,
        "difficulty": tab.get("difficulty") or None,
        "url": tab.get("tab_url") or tab.get("urlWeb"),
    }


def ug_search(query: str, types: list[str] | None = None, page: int = 1) -> list[dict]:
    """Search by title/artist text. `types` are TAB_TYPES keys; empty = every type."""
    params = [("title", query.strip()), ("page", str(page))]
    for t in types if types is not None else ["chords"]:
        if t.lower() not in TAB_TYPES:
            raise ValueError(f"Unknown tab type {t!r}; use one of {', '.join(TAB_TYPES)}")
        params.append(("type[]", str(TAB_TYPES[t.lower()])))
    try:
        data = _ug_fetch("/tab/search", params)
    except WebError as exc:
        if exc.status == 404:  # the API answers 404 when nothing matches
            return []
        raise
    return [s for s in (parse_summary(t) for t in data.get("tabs") or [] if isinstance(t, dict)) if s]


def parse_applicature(data: dict) -> list[dict]:
    """Chord fingerings; frets are low E to high e, -1 = muted. The shape varies, so read defensively."""
    shapes, seen = [], set()
    for entry in data.get("applicature") or []:
        if not isinstance(entry, dict) or not entry.get("chord") or entry["chord"] in seen:
            continue
        variations = entry.get("variations")
        variant = variations[0] if isinstance(variations, list) and variations and isinstance(variations[0], dict) else entry

        def ints(key):
            out = []
            for v in variant.get(key) or []:
                try:
                    out.append(int(v))
                except (TypeError, ValueError):
                    pass
            return out

        seen.add(entry["chord"])
        shapes.append({"chord": entry["chord"], "frets": ints("frets"), "fingers": ints("fingers"), "base_fret": variant.get("fret") or 1})
    return shapes


def parse_details(data: dict) -> dict:
    tuning = data.get("tuning")
    if isinstance(tuning, dict):
        tuning = tuning.get("name") or tuning.get("value")
    out = parse_summary({**data, "id": data.get("id", 0)})
    out.update({
        "capo": data.get("capo") or 0,
        "tuning": tuning or None,
        "content": data.get("content") or "",
        "chord_shapes": parse_applicature(data),
    })
    return out


def ug_tab(tab_id: int) -> dict:
    return parse_details(_ug_fetch("/tab/info", [("tab_id", str(tab_id)), ("tab_access_type", "private")]))


# ---------------------------------------------------------------------------
# Chord sheet markup ([ch]Am[/ch], [tab]...[/tab], [Verse])
# ---------------------------------------------------------------------------

_CHORD_TAG = re.compile(r"\[ch\](.*?)\[/ch\]")
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_ENHARMONIC = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E", "E#": "F", "B#": "C"}
_CHORD = re.compile(r"^([A-G][b#]?)(.*)$")
_BASS = re.compile(r"^(.*)/([A-G][b#]?)(.*)$")


def pitch_class(note: str) -> int | None:
    note = _ENHARMONIC.get(note, note)
    return _NOTES.index(note) if note in _NOTES else None


def transpose_note(note: str, semitones: int, flats: bool = False) -> str:
    pc = pitch_class(note)
    if pc is None:
        return note
    return (_FLATS if flats else _NOTES)[(pc + semitones) % 12]


def transpose_chord(chord: str, semitones: int) -> str:
    if semitones == 0:
        return chord
    m = _CHORD.match(chord)
    if not m:
        return chord
    root, suffix = m.groups()
    flats = "b" in root
    new_root = transpose_note(root, semitones, flats)
    bass = _BASS.match(suffix)
    if bass:
        pre, bass_note, post = bass.groups()
        return f"{new_root}{pre}/{transpose_note(bass_note, semitones, flats)}{post}"
    return new_root + suffix


def chart_chords(content: str, semitones: int = 0) -> list[str]:
    """Distinct chord names in order of first appearance."""
    return list(dict.fromkeys(transpose_chord(c, semitones) for c in _CHORD_TAG.findall(content)))


def chart_progression(content: str, semitones: int = 0) -> list[dict]:
    """Chord sequence per section ([Verse], [Chorus]...), repeats kept, for comparing with a score."""
    sections: list[dict] = []
    current = {"section": None, "chords": []}
    for line in content.replace("\r\n", "\n").split("\n"):
        stripped = line.replace("[tab]", "").replace("[/tab]", "").strip()
        header = re.fullmatch(r"\[([^\[\]]+)\]", stripped)
        if header and not _CHORD_TAG.search(stripped):
            if current["chords"] or current["section"]:
                sections.append(current)
            current = {"section": header.group(1), "chords": []}
            continue
        current["chords"] += [transpose_chord(c, semitones) for c in _CHORD_TAG.findall(line)]
    if current["chords"] or current["section"]:
        sections.append(current)
    return [s for s in sections if s["chords"]]


def chart_text(content: str, semitones: int = 0) -> str:
    """Plain monospace text; chords stay aligned over lyrics. Blank-line runs are collapsed."""
    text = _CHORD_TAG.sub(lambda m: transpose_chord(m.group(1), semitones), content.replace("\r\n", "\n"))
    text = text.replace("[tab]", "").replace("[/tab]", "")
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip("\n")


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

_RENDERER = re.compile(r'"videoRenderer":\{"videoId":"([\w-]{11})"[\s\S]{0,2000}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"')
_BARE_ID = re.compile(r'"videoId":"([\w-]{11})"')


def parse_youtube(html: str, limit: int) -> list[dict]:
    seen: set[str] = set()
    videos: list[dict] = []

    def add(vid: str, title: str | None) -> None:
        seen.add(vid)
        videos.append({"title": title, "url": f"https://www.youtube.com/watch?v={vid}", "video_id": vid})

    for m in _RENDERER.finditer(html):
        if len(videos) >= limit:
            break
        if m.group(1) in seen:
            continue
        try:
            title = json.loads(f'"{m.group(2)}"')
        except ValueError:
            title = m.group(2)
        add(m.group(1), title)
    if not videos:
        for m in _BARE_ID.finditer(html):
            if len(videos) >= limit:
                break
            if m.group(1) not in seen:
                add(m.group(1), None)
    return videos


def youtube_search(query: str, limit: int = 5) -> list[dict]:
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query.strip()})
    status, _, body = _get(url, {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"})
    if not 200 <= status < 300:
        raise WebError(status, f"YouTube returned {status}")
    return parse_youtube(body, limit)


def sheet_music_links(query: str) -> list[dict]:
    q = urllib.parse.quote_plus(query.strip())
    return [
        {"name": "MuseScore", "url": f"https://musescore.com/sheetmusic?text={q}"},
        {"name": "Musicnotes", "url": f"https://www.musicnotes.com/search/go?w={q}"},
        {"name": "IMSLP", "url": f"https://imslp.org/index.php?search={q}"},
    ]
