"""Play along with a recording: a YouTube video drives the sheet's cursor.

The page plays the video and knows its time; this module knows how that time lines up
with the MIDI file. The user taps the downbeats of a few bars while the video plays,
and each tap becomes an anchor (video seconds, score seconds of that bar's downbeat).
From the anchors comes a map video time -> score time: one straight line when the
recording keeps a steady tempo, a line through each anchor when it drifts. The page
gets that map as knots (video seconds, beat) at every bar line and moves the cursor
between them, so the sheet and the visualizer's strip follow the recording.

Nothing here listens to the audio: the video's sound can't be read from the page.
One sync per song and video, saved in <home>/synced.json (shared by every profile).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import statistics
import time

from . import library
from .notes import Bar, Score

STEADY_TOL_SEC = 0.08  # every anchor this close to one straight line: the recording keeps a steady tempo
EDGE_ANCHORS = 4  # the tempo before the first anchor and after the last comes from this many anchors
MIN_RATE, MAX_RATE = 0.4, 2.5  # video seconds per score second: further out is a mistaken tap
DOUBLE_TAP = 0.45  # a tap closer than this share of a bar to the one before is a slip, not a new bar

_ID = re.compile(r"^[\w-]{11}$")
_ID_IN_URL = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/|/live/)([\w-]{11})")


def video_id(text: str) -> str | None:
    """The 11-character video id in a YouTube link (or the id itself), None if there isn't one."""
    text = (text or "").strip()
    if _ID.match(text):
        return text
    m = _ID_IN_URL.search(text)
    return m.group(1) if m else None


# -- storage ---------------------------------------------------------------------


def _path() -> pathlib.Path:
    return library.home() / "synced.json"


def key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _load_all() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load(path: str) -> dict:
    """The saved sync for a file: {video: {id, title}, anchors: [[video_sec, score_sec], ...],
    loop: {from, to, on} or None}."""
    entry = _load_all().get(key(path)) or {}
    return {"video": entry.get("video"), "anchors": [list(a) for a in entry.get("anchors") or []],
            "loop": entry.get("loop")}


def save(path: str, entry: dict) -> dict:
    data = _load_all()
    data[key(path)] = {"file": str(path), "video": entry.get("video"), "anchors": sorted(entry.get("anchors") or []),
                       "loop": entry.get("loop"), "saved": time.strftime("%Y-%m-%d %H:%M:%S")}
    _path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    return load(path)


def saved() -> list[dict]:
    """Every song with a video chosen, newest first: {path, title, video, taps, saved, missing}."""
    out = []
    for name, entry in _load_all().items():
        if not (entry or {}).get("video"):
            continue
        path = entry.get("file") or name  # syncs saved before "file" have only the lower-cased key
        out.append({"path": path, "title": pathlib.Path(path).stem, "video": entry["video"],
                    "taps": len(entry.get("anchors") or []), "saved": entry.get("saved"),
                    "missing": not os.path.exists(path)})
    return sorted(out, key=lambda e: e["saved"] or "", reverse=True)


def set_video(path: str, vid: str, title: str | None = None) -> dict:
    """Choose the video for a file. A different video forgets the taps: they belong to the old one."""
    entry = load(path)
    if (entry["video"] or {}).get("id") != vid:
        entry["anchors"] = []
    entry["video"] = {"id": vid, "title": title}
    return save(path, entry)


# -- the extension -------------------------------------------------------------------
# The Piano Coach for YouTube extension (youtube_extension/) talks to the coach while a
# YouTube tab is open. Its last visit is kept in <home>/youtube_extension.json, so the
# YouTube tab can tell "installed, no YouTube tab open" from "never seen" after a restart.

EXTENSION_DIR = pathlib.Path(__file__).parent / "youtube_extension"
EXTENSION_SAVE_SEC = 300  # remember a visit at most this often (it polls every few seconds)
EXTENSION_LIVE_SEC = 10  # heard from this recently: a YouTube tab is open now


def extension_version() -> str | None:
    """The version of the extension in the repo (what a loaded copy should be)."""
    try:
        return json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None


def _extension_path() -> pathlib.Path:
    return library.home() / "youtube_extension.json"


def _extension_saved() -> dict:
    try:
        return json.loads(_extension_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def note_extension(version: str | None) -> None:
    """The extension just sent a command: remember it (now and then, not on every poll)."""
    before = _extension_saved()
    if before.get("version") == version and time.time() - float(before.get("seen") or 0) < EXTENSION_SAVE_SEC:
        return
    _extension_path().write_text(json.dumps({"seen": time.time(), "version": version}), encoding="utf-8")


def extension_status(live: dict | None) -> dict:
    """Is the extension installed and talking to the coach? live is the display hub's record
    of its last command this run. {state: live | installed | unknown, seen (seconds ago),
    version, latest, outdated}."""
    last = live or _extension_saved() or None
    latest = extension_version()
    if not last:
        return {"state": "unknown", "seen": None, "version": None, "latest": latest, "outdated": False}
    ago = max(0.0, time.time() - float(last.get("seen") or 0))
    version = last.get("version")
    return {"state": "live" if live and ago <= EXTENSION_LIVE_SEC else "installed", "seen": round(ago),
            "version": version, "latest": latest, "outdated": bool(latest and version != latest)}


# -- the map -------------------------------------------------------------------------


def _line(points: list[list[float]]) -> tuple[float, float]:
    """Least-squares (intercept, slope) of video seconds on score seconds."""
    if len(points) == 1:
        return points[0][0] - points[0][1], 1.0
    xs = [s for _, s in points]
    ys = [v for v, _ in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx > 0 else 1.0
    slope = min(MAX_RATE, max(MIN_RATE, slope))
    return my - slope * mx, slope


def _clean(anchors: list[list[float]]) -> list[list[float]]:
    """Anchors in score order with time moving forward in both: a tap out of order is dropped."""
    out: list[list[float]] = []
    for v, s in sorted(anchors, key=lambda a: a[1]):
        if out and (s <= out[-1][1] + 1e-6 or v <= out[-1][0] + 1e-6):
            continue
        out.append([v, s])
    return out


def video_at(anchors: list[list[float]], score_sec: float) -> float:
    """Where in the video a moment of the score falls."""
    points = _clean(anchors)
    if not points:
        return score_sec
    a, b = _line(points)
    if len(points) < 3 or all(abs(v - (a + b * s)) <= STEADY_TOL_SEC for v, s in points):
        return a + b * score_sec  # a steady recording: one line ignores the wobble of each tap
    if score_sec <= points[0][1]:
        _, slope = _line(points[:EDGE_ANCHORS])
        return points[0][0] + (score_sec - points[0][1]) * slope
    if score_sec >= points[-1][1]:
        _, slope = _line(points[-EDGE_ANCHORS:])
        return points[-1][0] + (score_sec - points[-1][1]) * slope
    for (v0, s0), (v1, s1) in zip(points, points[1:]):
        if s0 <= score_sec <= s1:
            return v0 + (score_sec - s0) * (v1 - v0) / (s1 - s0)
    return score_sec  # unreachable


def score_at(anchors: list[list[float]], video_sec: float, score: Score) -> float:
    """The score time playing at a moment of the video (the inverse of video_at)."""
    lo, hi = -score.duration - 600.0, score.duration * MAX_RATE + 600.0
    for _ in range(60):  # video_at only moves forward, so halving the range finds it
        mid = (lo + hi) / 2
        if video_at(anchors, mid) < video_sec:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def timeline(score: Score, anchors: list[list[float]]) -> list[list[float]]:
    """Knots [video_sec, beat] at every bar line, for the page to move the cursor between."""
    if not score.bars:
        return []
    knots = [[round(video_at(anchors, bar.start), 4), round(bar.start_beat, 4)] for bar in score.bars]
    last = score.bars[-1]
    knots.append([round(video_at(anchors, last.end), 4), round(last.end_beat, 4)])
    return knots


def tempo(score: Score, anchors: list[list[float]]) -> float | None:
    """The recording's tempo in quarter notes a minute over the tapped stretch, None before two taps."""
    points = _clean(anchors)
    if len(points) < 2:
        return None
    (v0, s0), (v1, s1) = points[0], points[-1]
    return round(60 * (score.beat_of(s1) - score.beat_of(s0)) / (v1 - v0), 1)


# -- taps ----------------------------------------------------------------------------


def _bars_from(score: Score, first_bar: int) -> list[Bar]:
    return [bar for bar in score.bars if bar.number >= first_bar]


def taps_to_anchors(score: Score, taps: list[float], first_bar: int) -> list[list[float]]:
    """Anchors for downbeats tapped one after another from first_bar. A gap of about two
    bars means a downbeat was missed (the bar is skipped, not squeezed); a tap right after
    another is a slip and is dropped."""
    bars = _bars_from(score, first_bar)
    taps = sorted(taps)
    if not bars or not taps:
        return []
    out = [[taps[0], bars[0].start]]
    i = 0
    rates: list[float] = []  # video seconds per score second, from the taps so far
    for tap in taps[1:]:
        gap = tap - out[-1][0]
        rate = statistics.median(rates) if rates else None
        if rate is None:
            step = 1
        else:
            # how many bars ahead best matches the gap at the tempo tapped so far
            best, step = None, 1
            for k in range(1, 9):
                if i + k >= len(bars):
                    break
                miss = abs(gap - (bars[i + k].start - bars[i].start) * rate)
                if best is None or miss < best:
                    best, step = miss, k
            if gap < DOUBLE_TAP * (bars[min(i + 1, len(bars) - 1)].start - bars[i].start) * rate:
                continue
        if i + step >= len(bars):
            break
        span = bars[i + step].start - bars[i].start
        if span <= 0 or not MIN_RATE <= gap / span <= MAX_RATE:
            continue
        rates.append(gap / span)
        i += step
        out.append([tap, bars[i].start])
    return out


def add_taps(score: Score, entry: dict, taps: list[float], first_bar: int) -> dict:
    """Replace the anchors over the tapped bars with these taps."""
    new = taps_to_anchors(score, taps, first_bar)
    if not new:
        return entry
    lo, hi = new[0][1], new[-1][1]
    if len(new) == 1:  # one tap moves that bar only
        keep = [a for a in entry["anchors"] if abs(a[1] - lo) > 1e-6]
    else:
        keep = [a for a in entry["anchors"] if not lo - 1e-6 <= a[1] <= hi + 1e-6]
    return {**entry, "anchors": _clean(keep + new)}


def nudge(score: Score, entry: dict, at: float) -> tuple[dict, Bar | None]:
    """A single tap while the video plays: the bar line nearest to it is put at that moment."""
    if not score.bars:
        return entry, None
    guess = score_at(entry["anchors"], at, score)
    bar = min(score.bars, key=lambda b: abs(b.start - guess))
    keep = [a for a in entry["anchors"] if abs(a[1] - bar.start) > 1e-6]
    return {**entry, "anchors": _clean(keep + [[at, bar.start]])}, bar


def set_loop(score: Score, entry: dict, first: int | None, last: int | None, on: bool) -> dict:
    """The bars to repeat while the video plays (kept in range, first <= last)."""
    numbers = [bar.number for bar in score.bars]
    if not numbers:
        return {**entry, "loop": None}
    lo = min(max(int(first if first is not None else numbers[0]), numbers[0]), numbers[-1])
    hi = min(max(int(last if last is not None else numbers[-1]), lo), numbers[-1])
    return {**entry, "loop": {"from": lo, "to": hi, "on": bool(on)}}


def view(score: Score, entry: dict) -> dict:
    """What the pages need: the video, the map as knots (one per bar line, then the end), the
    tempo, the bars tapped and the loop."""
    points = _clean(entry["anchors"])
    tapped = sorted({score.bar_at(s).number for _, s in points if score.bar_at(s)})
    first = next((bar.number for bar in score.bars if bar.number >= 1), score.bars[0].number if score.bars else 1)
    return {"path": score.path, "title": pathlib.Path(score.path).stem, "video": entry["video"], "taps": len(points),
            "tapped": tapped, "first_bar": first, "bpm": tempo(score, points), "knots": timeline(score, points),
            "loop": entry.get("loop"),
            "bars": [{"number": bar.number, "beat": round(bar.start_beat, 4)} for bar in score.bars]}
