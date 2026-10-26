"""Facts about a song a goal is built on: what its file shows, and what's published about it.

measured(score)   from the file: key, time signatures, tempo, the chord in each bar, range
research(...)     Claude Code on the subscription (WebSearch + WebFetch) gathers published
                  facts: Hooktheory's TheoryTab first (key, BPM, meter, sections, a Roman-
                  numeral progression per section), then Wikipedia, publisher pages
                  (Musicnotes) and well-known lessons; chord sites count least. Every fact
                  carries the URLs it came from.
reconcile(...)    a fact two sources agree on, or one source and the file, is 'confirmed'; one
                  source alone is 'reported'; a source the file disagrees with is 'conflict'.

The file stays the truth for the notes: research only shapes the goal's Path and what the
Maestro says, and a conflict is reported ("TheoryTab says 6/8, the file is written in 3/4"),
never "fixed". Results are cached in <home>/derived/song_facts/<file sha1>.json for 90 days
(TheoryTab's content is Hooktheory's, so it never goes in git). Offline or with nothing
found, the facts are the measured ones alone, and the result says so.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import time
import urllib.parse

from ..library import home
from . import claude_run

REFRESH_DAYS = 90
FIELDS = ("key", "meter", "bpm", "section", "progression", "technique", "form", "difficulty", "other")
MODEL = "sonnet"

RESEARCH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "song": {"type": "string"}, "artist": {"type": "string"},
        "facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"field": {"type": "string", "enum": list(FIELDS)}, "value": {"type": "string"},
                           "section": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}},
            "required": ["field", "value", "sources"]}},
    },
    "required": ["facts"],
}

RESEARCH_SYSTEM = """You research one song for a piano teacher planning a pianist's practice towards it. Gather published facts, each with the URLs it came from (only pages you actually opened or saw in search results):
1. Hooktheory TheoryTab first: https://www.hooktheory.com/theorytab/view/<artist>/<song> (lower case, words joined by hyphens). Its page gives the key, BPM, meter, section names and a Roman-numeral chord progression per section (e.g. "Verse: I V6 IV6 I64"). Fetch it with WebFetch.
2. Then cross-check with other sources: Wikipedia (key, form, tempo, the piano's role), publisher pages such as Musicnotes (original key, difficulty), well-known lessons or analyses. Chord sites (Ultimate Guitar and the like) are the least trusted.
Facts to look for: key, meter, bpm, sections (field 'section', value the section name, with its 'section'), progression (one per section), technique (what the piano part asks of the hands: a walking bass, broken chords, octaves...), form, difficulty. One fact per field and section; list every source that states it. If you find nothing, return an empty list. Never guess."""


def measured(score) -> dict:
    """What the file itself shows."""
    from ..harmony import chords_by_bar, estimate_key
    from ..notes import note_name
    from ..sheet import time_signatures

    notes = [n for n in score.notes if n.end > n.start]
    key = estimate_key(notes) if notes else None
    chords = chords_by_bar(score, notes, key=key) if notes and score.bars else []
    by_bar: dict[str, str] = {}  # bar number (as text, as JSON keeps it) -> its chord
    for c in chords[:96]:
        by_bar.setdefault(str(c["bar"]), c["chord"])
    return {"key": key, "meter": [sig for _, sig in time_signatures(score)] or ["4/4"],
            "bpm": round(score.bpm_at(notes[0].start)) if notes else None, "bars": len(score.bars),
            "chords_by_bar": by_bar,
            "range": [note_name(min(n.pitch for n in notes)), note_name(max(n.pitch for n in notes))] if notes else None}


# -- reconciling ------------------------------------------------------------------------------

_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def parse_key(text: str | None) -> tuple[int, str] | None:
    """'F♯ minor' / 'F#m' / 'Bb' / 'C major' -> (pitch class, 'major' | 'minor')."""
    if not text:
        return None
    m = re.match(r"\s*([A-Ga-g])\s*(#|♯|b|♭|sharp|flat)?\s*(m(?:in(?:or)?)?\b|maj(?:or)?\b)?", text.strip())
    if not m:
        return None
    pc = _PC[m.group(1).upper()] + {"#": 1, "♯": 1, "sharp": 1, "b": -1, "♭": -1, "flat": -1}.get(m.group(2) or "", 0)
    minor = bool(m.group(3) and m.group(3).lower().startswith("m") and not m.group(3).lower().startswith("maj"))
    return pc % 12, "minor" if minor else "major"


def _domain(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _agrees_with_file(fact: dict, m: dict) -> bool | None:
    """True / False when the file can say, None when it can't (sections, technique...)."""
    field, value = fact["field"], fact["value"]
    if field == "key" and m.get("key"):
        a, b = parse_key(value), parse_key(m["key"])
        return None if a is None or b is None else a == b
    if field == "meter" and m.get("meter"):
        sig = re.search(r"\d+\s*/\s*\d+", value)
        return None if not sig else sig.group(0).replace(" ", "") in m["meter"]
    if field == "bpm" and m.get("bpm"):
        num = re.search(r"\d+(\.\d+)?", value)
        if not num:
            return None
        bpm = float(num.group(0))
        return any(abs(bpm * f - m["bpm"]) <= 0.08 * m["bpm"] for f in (1, 2, 0.5))  # half / double time counts
    return None


def reconcile(facts: list[dict], m: dict) -> list[dict]:
    """Each published fact with a status and, for a conflict, what the file says instead."""
    out = []
    file_text = {"key": m.get("key"), "meter": " / ".join(m.get("meter") or []), "bpm": m.get("bpm")}
    for fact in facts:
        sources = [s for s in fact.get("sources") or [] if s.startswith("http")]
        if not sources or not str(fact.get("value", "")).strip():
            continue  # a fact without a source isn't kept
        f = {"field": fact["field"], "value": str(fact["value"]).strip(), "sources": sources}
        if fact.get("section"):
            f["section"] = fact["section"]
        agree = _agrees_with_file(f, m)
        if agree is False:
            name = "TheoryTab" if any("hooktheory" in s for s in sources) else _domain(sources[0])
            f["status"] = "conflict"
            f["note"] = f"{name} says {f['value']}; the file is written in {file_text[f['field']]}."
        elif agree is True or len({_domain(s) for s in sources}) >= 2:
            f["status"] = "confirmed"
        else:
            f["status"] = "reported"
        out.append(f)
    return out


# -- research and cache --------------------------------------------------------------------------


def cache_path(file: str | pathlib.Path) -> pathlib.Path:
    digest = hashlib.sha1(pathlib.Path(file).read_bytes()).hexdigest()
    folder = home() / "derived" / "song_facts"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def research(song: str, artist: str | None, m: dict, run=claude_run.run, model: str = MODEL) -> dict:
    """{facts, found, error?}: published facts, reconciled against the file."""
    prompt = (f"Song: {song}" + (f" by {artist}" if artist else "") + "\n"
              f"For reference, the pianist's file reads: key {m.get('key')}, time {', '.join(m.get('meter') or [])}, "
              f"about {m.get('bpm')} BPM, {m.get('bars')} bars.\nGather the published facts.")
    out = run(prompt, model, schema=RESEARCH_SCHEMA, system=RESEARCH_SYSTEM, tools="WebSearch,WebFetch")
    if out.get("error"):
        return {"facts": [], "found": False, "error": out["error"], "usage_limit": out.get("usage_limit", False)}
    facts = reconcile((out.get("structured") or {}).get("facts") or [], m)
    return {"facts": facts, "found": bool(facts)}


def get(file: str | pathlib.Path, song: str, artist: str | None, score, run=claude_run.run, force: bool = False) -> dict:
    """The song's facts (cached): {song, artist, fetched, measured, facts, found, note}."""
    path = cache_path(file)
    if not force:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("fetched_ts", 0) < REFRESH_DAYS * 86400:
                return data
        except (OSError, ValueError):
            pass
    m = measured(score)
    found = research(song, artist, m, run)
    data = {"song": song, "artist": artist, "fetched": time.strftime("%Y-%m-%d"), "fetched_ts": time.time(),
            "measured": m, "facts": found["facts"], "found": found["found"]}
    if not found["found"]:
        data["note"] = ("No published facts were found" + (f" ({found['error']})" if found.get("error") else "")
                        + ": the plan uses what the file shows alone.")
    if not found.get("usage_limit"):  # a usage limit isn't an answer: try again next time
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def summary(data: dict) -> str:
    """The facts as lines for a prompt or the Maestro."""
    m = data["measured"]
    lines = [f"The file: key {m.get('key')}, time {', '.join(m.get('meter') or [])}, about {m.get('bpm')} BPM, "
             f"{m.get('bars')} bars, range {' to '.join(m.get('range') or [])}."]
    chords = m.get("chords_by_bar") or {}
    if chords:
        lines.append("Chords by bar (from the file): " + " ".join(f"{b}:{c}" for b, c in list(chords.items())[:32]))
    for f in data.get("facts", []):
        where = f" ({f['section']})" if f.get("section") else ""
        lines.append(f"[{f['status']}] {f['field']}{where}: {f['value']}" + (f" - {f['note']}" if f.get("note") else ""))
    if data.get("note"):
        lines.append(data["note"])
    return "\n".join(lines)
