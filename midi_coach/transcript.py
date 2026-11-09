"""Today's conversation with the Maestro, as the coach page's panel shows it.

Every line said on the page goes in: what you typed or said, each answer, and what the Maestro,
Claude or the Examiner says unasked (feedback after a pass, the autopilot). A line said while
answering you is a "reply"; anything else is a "remark". Kept in
~/MidiCoach/maestro_log/<date>.jsonl beside bugs.conversation_log's Markdown, so a reload (or a
second page) shows the same day.
"""

import contextlib
import json
import logging
import threading
import time

from .library import home

log = logging.getLogger(__name__)

_local = threading.local()


def _path():
    return home() / "maestro_log" / f"{time.strftime('%Y-%m-%d')}.jsonl"


@contextlib.contextmanager
def answering():
    """Lines said inside this block answer what was just asked."""
    was = getattr(_local, "answering", False)
    _local.answering = True
    try:
        yield
    finally:
        _local.answering = was


def add(who: str, text: str, kind: str = "", link: str = "") -> dict | None:
    """Append one line to today's transcript and return it (None for an empty line). kind:
    "you", "reply", "remark" or "error"; left out, a reply while answering, else a remark.
    link: a web address shown under the line (only http/https is kept)."""
    text = (text or "").strip()
    if not text:
        return None
    line = {"t": time.strftime("%H:%M:%S"), "who": who,
            "kind": kind or ("reply" if getattr(_local, "answering", False) else "remark"), "text": text}
    if link and link.startswith(("https://", "http://")):
        line["link"] = link
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as exc:  # the panel still shows it; only a reload would lose it
        log.info("transcript: %s", exc)
    return line


def today() -> list[dict]:
    """Today's lines, oldest first; a line that doesn't parse is skipped."""
    try:
        raw = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for row in raw:
        try:
            line = json.loads(row)
        except ValueError:
            continue
        if isinstance(line, dict) and line.get("text"):
            out.append(line)
    return out
