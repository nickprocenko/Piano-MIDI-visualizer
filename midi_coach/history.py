"""Every fix's story, one line per step, for Agent Quest's Workshop and `bugs history <id>`.

<home>/fixes/log.jsonl: {"at", "id", "event", ...}. Events: built (worker, commit, files),
tested (passed, new, already), sent_back (why), opened (a test copy), works (commit in the user's
code), still_wrong (note), answered (answer). The report folders stay the truth for where an item
is; this only remembers what happened on the way, so nothing breaks if it's missing.
"""

from __future__ import annotations

import json
import threading
import time

from .library import home

_lock = threading.Lock()


def _path():
    return home() / "fixes" / "log.jsonl"


def add(report_id: str, event: str, **data) -> None:
    line = {"at": round(time.time(), 1), "id": report_id, "event": event, **data}
    path = _path()
    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass  # a history line is never worth failing the step itself


def all_events() -> list[dict]:
    try:
        text = _path().read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def of(report_id: str) -> list[dict]:
    """One item's steps, oldest first."""
    return [e for e in all_events() if e.get("id") == report_id]


def by_item() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in all_events():
        out.setdefault(e.get("id", ""), []).append(e)
    return out
