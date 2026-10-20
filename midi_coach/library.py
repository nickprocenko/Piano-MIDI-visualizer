"""Reference file discovery and saved-take history."""

from __future__ import annotations

import difflib
import json
import os
import pathlib
import re
import time

import mido

from .notes import MIDI_SUFFIXES, MUSICXML_SUFFIXES, Note, Score, load_score

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
REF_SUFFIXES = MIDI_SUFFIXES | MUSICXML_SUFFIXES
TAKE_PPQ = 480
TAKE_TEMPO = 500000  # 120 bpm -> 960 ticks per second


def home() -> pathlib.Path:
    path = pathlib.Path(os.environ.get("MIDI_COACH_HOME") or pathlib.Path.home() / "MidiCoach")
    (path / "takes").mkdir(parents=True, exist_ok=True)
    (path / "references").mkdir(exist_ok=True)
    return path


def reference_folders() -> list[pathlib.Path]:
    folders: list[pathlib.Path] = []
    config_path = pathlib.Path(os.environ.get("MIDI_COACH_CONFIG") or REPO_ROOT / "config.json")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        folders += [pathlib.Path(f) for f in data.get("search_folders", [])]
    except (OSError, ValueError):
        pass
    extra = os.environ.get("MIDI_COACH_REFERENCE_DIRS", "")
    folders += [pathlib.Path(p) for p in extra.split(os.pathsep) if p.strip()]
    folders.append(home() / "references")
    folders.append(home() / "lessons")
    seen, out = set(), []
    for f in folders:
        key = str(f).lower()
        if key not in seen and f.is_dir():
            seen.add(key)
            out.append(f)
    return out


def scan_references() -> list[pathlib.Path]:
    files: dict[str, pathlib.Path] = {}
    for folder in reference_folders():
        for f in folder.rglob("*"):
            if f.is_file() and f.suffix.lower() in REF_SUFFIXES:
                files.setdefault(str(f).lower(), f)
    return sorted(files.values(), key=lambda p: p.name.lower())


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def find_references(query: str, limit: int = 10) -> list[dict]:
    files = scan_references()
    q = _norm(query)
    scored = []
    for f in files:
        name = _norm(f.stem)
        if not q:
            score = 0.0
        else:
            q_tokens, n_tokens = set(q.split()), set(name.split())
            overlap = len(q_tokens & n_tokens) / len(q_tokens)
            ratio = difflib.SequenceMatcher(None, q, name).ratio()
            score = max(ratio, overlap * 0.9 + 0.1 * ratio, 1.0 if q in name else 0.0)
        scored.append((score, f))
    scored.sort(key=lambda s: (-s[0], s[1].name.lower()))
    if q:
        scored = [s for s in scored if s[0] >= 0.35]
    return [{"name": f.name, "path": str(f), "match": round(s, 2)} for s, f in scored[:limit]]


def resolve_reference(ref: str) -> pathlib.Path:
    path = pathlib.Path(ref).expanduser()
    if path.is_file():
        return path
    hits = find_references(ref, limit=5)
    if not hits:
        folders = [str(f) for f in reference_folders()]
        raise FileNotFoundError(f"No reference matching '{ref}'. Searched: {folders}")
    if len(hits) > 1 and hits[0]["match"] < 1.0 and hits[0]["match"] - hits[1]["match"] < 0.1:
        names = ", ".join(h["name"] for h in hits)
        raise FileNotFoundError(f"'{ref}' is ambiguous: {names}. Pass a more specific name or the full path.")
    return pathlib.Path(hits[0]["path"])


_score_cache: dict[str, tuple[float, Score]] = {}


def get_score(ref: str) -> Score:
    path = resolve_reference(ref)
    mtime = path.stat().st_mtime
    cached = _score_cache.get(str(path))
    if cached and cached[0] == mtime:
        score = cached[1]
    else:
        score = load_score(path)
        _score_cache[str(path)] = (mtime, score)
    score.hands = load_hands(score)
    return score


# ---------------------------------------------------------------------------
# Part choices: which parts of a reference the user plays with which hand
# ---------------------------------------------------------------------------


def _choices_path() -> pathlib.Path:
    return home() / "part_choices.json"


def _load_choices() -> dict:
    try:
        return json.loads(_choices_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_hands(score: Score) -> dict[int, str]:
    """The saved part -> hand choice for a score; empty if none, or if the file's parts changed."""
    saved = _load_choices().get(score.path)
    if not saved:
        return {}
    names = {p.index: p.name for p in score.parts}
    hands = {}
    for key, entry in saved["parts"].items():
        if names.get(int(key)) != entry["name"]:
            return {}
        hands[int(key)] = entry["hand"]
    return hands


def save_hands(score: Score, hands: dict[int, str]) -> None:
    """Save (or with an empty dict, forget) the part -> hand choice for a score."""
    choices = _load_choices()
    if hands:
        names = {p.index: p.name for p in score.parts}
        choices[score.path] = {
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "parts": {str(i): {"name": names[i], "hand": h} for i, h in sorted(hands.items())},
        }
    else:
        choices.pop(score.path, None)
    _choices_path().write_text(json.dumps(choices, indent=2), encoding="utf-8")
    score.hands = dict(hands)


# ---------------------------------------------------------------------------
# Takes
# ---------------------------------------------------------------------------


def save_take(events: list[tuple[float, list[int]]], meta: dict) -> dict:
    """Write a recorded take to <home>/takes/<id>.mid plus <id>.json."""
    take_id = time.strftime("%Y%m%d-%H%M%S")
    folder = home() / "takes"
    while (folder / f"{take_id}.mid").exists():
        take_id += "b"
    t0 = events[0][0] if events else 0.0
    mid = mido.MidiFile(ticks_per_beat=TAKE_PPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=TAKE_TEMPO, time=0))
    ticks_per_sec = TAKE_PPQ * 1_000_000 / TAKE_TEMPO
    last_tick = 0
    for t, data in events:
        tick = int(round((t - t0) * ticks_per_sec))
        try:
            msg = mido.Message.from_bytes(data)
        except ValueError:
            continue
        track.append(msg.copy(time=tick - last_tick))
        last_tick = tick
    mid.save(str(folder / f"{take_id}.mid"))
    meta = {"id": take_id, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "file": str(folder / f"{take_id}.mid"), **meta, "comparisons": []}
    (folder / f"{take_id}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def list_takes() -> list[dict]:
    out = []
    for f in sorted((home() / "takes").glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def get_take(take: str | None) -> dict:
    takes = list_takes()
    if not takes:
        raise FileNotFoundError("No takes recorded yet.")
    if not take or take == "latest":
        return takes[-1]
    for t in takes:
        if t["id"] == take:
            return t
    path = pathlib.Path(take)
    if path.is_file():  # an arbitrary MIDI file treated as a take
        return {"id": path.stem, "file": str(path), "external": True, "comparisons": []}
    raise FileNotFoundError(f"No take '{take}'. Recent: {[t['id'] for t in takes[-5:]]}")


def update_take(meta: dict) -> None:
    if meta.get("external"):
        return
    path = home() / "takes" / f"{meta['id']}.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def take_notes(meta: dict) -> tuple[list[Note], list[tuple[float, int]]]:
    score = load_score(meta["file"])
    return score.notes, score.pedal
