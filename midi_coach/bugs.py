"""Bug reports by voice: "Maestro, bug: the cursor jumped to bar five" saves what was said,
screenshots, the practice context, the coach page's console errors and the coach's recent log to
~/MidiCoach/bug_reports/open/<when>/, to be fixed later in Claude Code ("fix the bug reports").
Requests for the app ("Idea: a bigger metronome button") are saved the same way to
~/MidiCoach/requests/open/<when>/ ("do the requests").

The screenshots are of the window in front: one at the moment of the report, and a few from
the seconds before it, because the trouble has usually just happened by the time the report
is spoken, transcribed and understood. Those come from a small in-memory ring that only runs
while a coach page is open and is never written to disk unless a report is made.

Everything said to the Maestro, and its answer, is also kept in a daily log,
~/MidiCoach/maestro_log/<date>.md, so a request made in other words isn't lost.
"""

from __future__ import annotations

import collections
import io
import json
import logging
import pathlib
import re
import sys
import threading
import time

from .library import home

log = logging.getLogger("midi-coach")

RING_EVERY_SEC = 3.0
RING_KEEP = 5            # about fifteen seconds before the report
RING_MAX_AGE_SEC = 60    # an unchanged screen leaves old frames; past this they say nothing
ADD_TO_LAST_WITHIN_SEC = 10 * 60
MAX_WIDTH = 1600
LOG_LINES = 40
PAGE_ERRORS = 20

# Said to the Maestro, handled on the PC without an API call.
REPORT_RE = re.compile(r"^(?:maestro\s+)?(?:bug report|report (?:a )?bug|(?:that's |that is |thats )?a bug|bug)\b\s*(.*)$")
REQUEST_RE = re.compile(r"^(?:maestro\s+)?(?:feature request|app request|new feature|feature|idea|suggestion|wish list|wishlist|wish)\b\s*(.*)$")
MORE_RE = re.compile(r"^(?:maestro\s+)?(?:take )?(?:another|one more|more) screenshots?\b\s*(.*)$")

FOLDERS = {"bug": "bug_reports", "request": "requests"}
TITLES = {"bug": "Bug report", "request": "Request"}


def reports_dir(kind: str = "bug") -> pathlib.Path:
    return home() / FOLDERS[kind] / "open"


def conversation_log(heard: str, reply: str = "", actions=(), error: str = "") -> None:
    """Add one exchange with the Maestro to today's log (never fails the conversation)."""
    if not (heard or "").strip():
        return
    try:
        folder = home() / "maestro_log"
        folder.mkdir(parents=True, exist_ok=True)
        lines = [f"**{time.strftime('%H:%M:%S')} You:** {heard.strip()}"]
        if reply:
            lines.append(f"**Maestro:** {reply.strip()}")
        if error:
            lines.append(f"**Error:** {error.strip()}")
        if actions:
            lines.append(f"*did: {', '.join(actions)}*")
        with (folder / f"{time.strftime('%Y-%m-%d')}.md").open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    except OSError as exc:
        log.info("conversation log: %s", exc)


def _foreground_box() -> tuple[int, int, int, int] | None:
    """Screen rectangle of the window in front (Windows), in physical pixels."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:  # per-monitor DPI aware, to match the pixels ImageGrab returns
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    hwnd = user32.GetForegroundWindow()
    rect = wintypes.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    if rect.right - rect.left < 200 or rect.bottom - rect.top < 150:  # a tooltip or the taskbar
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def grab():
    """The window in front as a PIL image (the whole screen if that can't be found), or None."""
    try:
        from PIL import ImageGrab

        box = _foreground_box()
        if box is None:
            return ImageGrab.grab()
        full = ImageGrab.grab(all_screens=True)
        # all_screens images start at the virtual screen's top-left, which can be negative
        x0, y0 = (_virtual_origin() if sys.platform == "win32" else (0, 0))
        left, top, right, bottom = box
        crop = (max(0, left - x0), max(0, top - y0), min(full.width, right - x0), min(full.height, bottom - y0))
        return full.crop(crop) if crop[2] > crop[0] and crop[3] > crop[1] else full
    except Exception as exc:  # no display, locked screen...
        log.info("screenshot failed: %s", exc)
        return None


def _virtual_origin() -> tuple[int, int]:
    import ctypes

    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)  # SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN


def _jpeg(image) -> bytes:
    image = image.convert("RGB")
    if image.width > MAX_WIDTH:
        image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=80)
    return out.getvalue()


def _thumb(image) -> bytes:
    return image.convert("L").resize((64, 36)).tobytes()


def _same(a: bytes, b: bytes) -> bool:
    return len(a) == len(b) and sum(abs(x - y) for x, y in zip(a, b)) / len(a) < 2


class ScreenRing:
    """The last few distinct screenshots, taken every few seconds while active() is true."""

    def __init__(self, active, grab=grab, every: float = RING_EVERY_SEC, keep: int = RING_KEEP) -> None:
        self.active = active
        self.grab = grab
        self.every = every
        self.frames: collections.deque = collections.deque(maxlen=keep)  # (time, thumb, jpeg)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="bug-screen-ring", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            time.sleep(self.every)
            try:
                if self.active():
                    self.capture()
                else:
                    with self._lock:
                        self.frames.clear()
            except Exception as exc:
                log.info("screen ring: %s", exc)

    def capture(self) -> None:
        image = self.grab()
        if image is None:
            return
        thumb = _thumb(image)
        with self._lock:
            if self.frames and _same(self.frames[-1][1], thumb):
                return  # nothing changed on screen; keep the older frames
        jpeg = _jpeg(image)
        with self._lock:
            self.frames.append((time.time(), thumb, jpeg))

    def recent(self, now: float) -> list[tuple[float, bytes]]:
        """(seconds before now, jpeg) for the frames still worth showing, oldest first."""
        with self._lock:
            return [(now - t, jpeg) for t, _, jpeg in self.frames if now - t <= RING_MAX_AGE_SEC]


class LogRing(logging.Handler):
    """The coach's last log lines, so a report shows the warnings around the bug."""

    def __init__(self, keep: int = LOG_LINES) -> None:
        super().__init__(logging.INFO)
        self.lines: collections.deque = collections.deque(maxlen=keep)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            pass


class PageErrors:
    """The coach page's last console errors (uncaught exceptions and rejected promises), posted by
    the page as they happen, so a report carries the stack trace and not just a screenshot of it."""

    def __init__(self, keep: int = PAGE_ERRORS) -> None:
        self.lines: collections.deque = collections.deque(maxlen=keep)

    def add(self, message: str, where: str = "", stack: str = "") -> None:
        text = (message or "").strip()[:500] or "(no message)"
        if where:
            text += f"  [{where.strip()[:200]}]"
        stack = "\n".join(line.rstrip() for line in (stack or "").strip().splitlines()[:8])
        entry = f"{time.strftime('%H:%M:%S')} {text}" + (f"\n{stack}" if stack else "")
        if self.lines and self.lines[-1].split(" ", 1)[1] == entry.split(" ", 1)[1]:
            return  # the same error again (a render loop): once is enough
        self.lines.append(entry)


class BugLog:
    def __init__(self, ring: ScreenRing, grab=grab, logs: LogRing | None = None, page: PageErrors | None = None) -> None:
        self.ring = ring
        self.grab = grab
        self.logs = logs
        self.page = page

    def report(self, said: str, context: str = "", kind: str = "bug", state: dict | None = None) -> dict:
        """A new report ('bug' or 'request'): what was said, a screenshot now and the frames before it,
        and (state) where the page was, for the check step's Go there."""
        now = time.time()
        folder = reports_dir(kind) / time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now))
        folder.mkdir(parents=True, exist_ok=True)
        if state:
            (folder / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
        shots = []
        for ago, jpeg in self.ring.recent(now):
            name = f"before-{round(ago):02d}s.jpg"
            (folder / name).write_bytes(jpeg)
            shots.append(name)
        shots += self._shot_now(folder, "now.jpg")
        lines = [f"# {TITLES[kind]} {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}", "",
                 "## What was said", "", said.strip() or "(nothing more was said)", "",
                 "## Screenshots (window in front)", ""]
        lines += [f"- {name}" for name in shots] or ["- none (screen capture unavailable)"]
        if context:
            lines += ["", "## Practice context", "", context.strip()]
        if self.page is not None and self.page.lines:
            lines += ["", "## Coach page console errors", "", "```", *self.page.lines, "```"]
        if self.logs is not None and self.logs.lines:
            lines += ["", "## Coach log before the report", "", "```", *self.logs.lines, "```"]
        (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info("%s saved: %s", TITLES[kind].lower(), folder)
        write_backlog()
        return {"saved": folder.name, "screenshots": len(shots)}

    def add(self, said: str = "", kind: str = "bug") -> dict:
        """Another screenshot (and anything more that was said) on the latest report or request;
        with none in the last few minutes, a new one of `kind`."""
        folder = self.latest()
        if folder is None:
            return self.report(said, kind=kind)
        n = 2
        while (folder / f"now-{n}.jpg").exists():
            n += 1
        shots = self._shot_now(folder, f"now-{n}.jpg")
        addition = [f"", f"## Added {time.strftime('%H:%M:%S')}", ""]
        if said.strip():
            addition += [said.strip(), ""]
        addition += [f"- {name}" for name in shots] or ["- (screen capture unavailable)"]
        with (folder / "report.md").open("a", encoding="utf-8") as f:
            f.write("\n".join(addition) + "\n")
        write_backlog()
        return {"added_to": folder.name, "screenshots": len(shots)}

    def latest(self) -> pathlib.Path | None:
        """The report or request written to most recently, if within the last few minutes."""
        reports = [p for kind in FOLDERS for p in reports_dir(kind).glob("*/report.md")]
        if not reports:
            return None
        newest = max(reports, key=lambda p: p.stat().st_mtime)
        return newest.parent if time.time() - newest.stat().st_mtime <= ADD_TO_LAST_WITHIN_SEC else None

    def open_count(self, kind: str = "bug") -> int:
        return sum(1 for p in reports_dir(kind).glob("*/report.md"))

    def _shot_now(self, folder: pathlib.Path, name: str) -> list[str]:
        image = self.grab()
        if image is None:
            return []
        (folder / name).write_bytes(_jpeg(image))
        return [name]


def heard_command(heard: str) -> tuple[str, str] | None:
    """('report' | 'request' | 'more', the rest of what was said) when speech is a bug or request command."""
    text = re.sub(r"[^a-z0-9' ]+", " ", (heard or "").lower())
    text = " ".join(text.split())
    for kind, pattern in (("more", MORE_RE), ("report", REPORT_RE), ("request", REQUEST_RE)):
        m = pattern.match(text)
        if m:
            return kind, m.group(1)
    return None


# ---- After the fix: ready to check, then checked by the user ------------------------------------
#
# A report lives in <folder>/open/ until an agent fixes it, then waits in <folder>/check/ with a
# fix.md (what changed, and the build log it's written up in) until the user tries it on the
# coach page: "Works" moves it to fixed/ (requests: done/), "Still wrong" sends it back to open/
# with what they said. Agents move it with `python -m midi_coach.bugs ready <id> "<what changed>"`.
# Every change rewrites Backlog.md in the Obsidian vault, so the list can be read on the phone.

DONE = {"bug": "fixed", "request": "done"}
BACKLOG_NOTE = "Projects/MidiCoach/Backlog.md"
BACKLOG_SHOTS = "attachments/backlog"
DONE_SHOWN_DAYS = 14
LOG_LINK_RE = re.compile(r"^Build log: \[\[([^\]]+)\]\]\s*$", re.M)


def stage_dir(kind: str, stage: str) -> pathlib.Path:
    return home() / FOLDERS[kind] / stage


def find(report_id: str) -> tuple[str, str, pathlib.Path] | None:
    """(kind, stage, folder) of a report or request by its folder name."""
    for kind in FOLDERS:
        for stage in ("open", "check", DONE[kind]):
            folder = stage_dir(kind, stage) / report_id
            if (folder / "report.md").exists():
                return kind, stage, folder
    return None


def _move(folder: pathlib.Path, kind: str, stage: str) -> pathlib.Path:
    target = stage_dir(kind, stage)
    target.mkdir(parents=True, exist_ok=True)
    return pathlib.Path(folder.rename(target / folder.name))


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def _said(text: str, limit: int = 160) -> str:
    said = " ".join(_section(text, "What was said").split()) or "(nothing said)"
    return said if len(said) <= limit else said[:limit - 1].rstrip() + "…"


def _where(text: str) -> str:
    """Where it happened, in a few words: the page, the lesson, the bar, the run."""
    context = _section(text, "Practice context")
    bits = []
    for pattern, shown in ((r"The page is on ([^;.(]+)", "{}"), (r"Lesson on screen: (.+?)(?:\s*\[\d+\])?, \d+ bars", "{}"),
                           (r"Cursor at bar (\d+)", "bar {}"), (r"Run going now \(([^,)]+)", "{}")):
        m = re.search(pattern, context)
        if m:
            bits.append(shown.format(" ".join(m.group(1).split())))
    return " · ".join(bits)


def _fix_parts(folder: pathlib.Path) -> tuple[str, str]:
    """(what changed, build log note name) from a fix.md."""
    fix = folder / "fix.md"
    if not fix.exists():
        return "", ""
    body = fix.read_text(encoding="utf-8").split("\n", 1)[-1]
    m = LOG_LINK_RE.search(body)
    return " ".join(LOG_LINK_RE.sub("", body).split()), (m.group(1) if m else "")


PAGE_MODES = {"wait": "learn", "rehearsal": "rehearse", "listen": "listen", "learn": "learn", "rehearse": "rehearse"}
RUN_RE = re.compile(r"(?:Run going now \(|Last run: )(\w+) mode, hand ([^,]+), bars ([^,]+), tempo ([\d.]+)%, loop (on|off)")


def place(report_id: str) -> dict:
    """Where the page was when a report was made: {score | title, bar, view, mode, bars, tempo_percent,
    loop}. From its state.json, or read back from the report's practice context (older reports)."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    folder = found[2]
    try:
        return json.loads((folder / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    context = _section((folder / "report.md").read_text(encoding="utf-8"), "Practice context")
    out: dict = {}
    m = re.search(r"The page is on [^(\n]*\((\w+)\)", context)
    if m:
        out["view"] = m.group(1)
    m = re.search(r"Lesson on screen: (.+?), \d+ bars", context)
    if m:
        out["title"] = m.group(1).strip()
    m = re.search(r"Cursor at bar (\d+)", context)
    if m:
        out["bar"] = int(m.group(1))
    m = RUN_RE.search(context)
    if m:
        mode = PAGE_MODES.get(m.group(1).lower())  # "Learn", "Rehearse", "Listen"; not free play or Record
        if mode:
            out["mode"] = mode
        out["hand"] = m.group(2).strip()
        if re.fullmatch(r"\d+-\d+", m.group(3).strip()):
            out["bars"] = m.group(3).strip()
        out["tempo_percent"] = round(float(m.group(4)))
        out["loop"] = m.group(5) == "on"
    return out


def mark_ready(report_id: str, summary: str, build_log: str = "") -> dict:
    """An agent fixed it: open/ → check/, with what changed, for the user to try."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage != "open":
        return {"error": f"{report_id} is in {stage}/, not open/."}
    folder = _move(folder, kind, "check")
    lines = [f"# Fixed {time.strftime('%Y-%m-%d %H:%M')}", "", summary.strip()]
    if build_log.strip():
        lines += ["", f"Build log: [[{build_log.strip()}]]"]
    (folder / "fix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_backlog()
    return {"ready": report_id, "kind": kind}


def verify(report_id: str, works: bool, note: str = "") -> dict:
    """The user tried a fix: check/ → fixed/ (requests: done/), or back to open/ with what's still wrong."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage != "check":
        return {"error": f"{report_id} isn't waiting to be checked."}
    fixed, build_log = _fix_parts(folder)
    tried = (fixed or "(no fix note)") + (f" (build log: {build_log})" if build_log else "")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if works:
        addition = ["", f"## Checked {stamp}: works", "", tried]
        folder = _move(folder, kind, DONE[kind])
    else:
        addition = ["", f"## Checked {stamp}: still wrong", "", note.strip() or "(nothing more was said)",
                    "", f"The fix that was tried: {tried}"]
        (folder / "fix.md").unlink(missing_ok=True)
        folder = _move(folder, kind, "open")
    with (folder / "report.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(addition) + "\n")
    write_backlog()
    return {"checked": report_id, "works": works}


def close(report_id: str, reason: str) -> dict:
    """Done without a fix, on the user's word (not a bug, already works, a request said in passing):
    straight to fixed/ (requests: done/), from open/ or check/, with why."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage == DONE[kind]:
        return {"error": f"{report_id} is already in {stage}/."}
    (folder / "fix.md").unlink(missing_ok=True)
    folder = _move(folder, kind, DONE[kind])
    with (folder / "report.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## Closed {time.strftime('%Y-%m-%d %H:%M')}: no fix needed\n\n{reason.strip()}\n")
    write_backlog()
    return {"closed": report_id, "kind": kind}


def _item(kind: str, folder: pathlib.Path) -> dict:
    report = folder / "report.md"
    text = report.read_text(encoding="utf-8")
    fixed, build_log = _fix_parts(folder)
    shot = folder / "now.jpg"
    return {"id": folder.name, "kind": kind, "said": _said(text, limit=2000), "where": _where(text),
            "fix": fixed, "log": build_log, "reopened": ": still wrong" in text,
            "shot": shot if shot.exists() else None, "when": report.stat().st_mtime}


def items(stage: str) -> list[dict]:
    """Every report and request in a stage ('open', 'check' or 'done'), oldest first."""
    out = []
    for kind in FOLDERS:
        base = stage_dir(kind, DONE[kind] if stage == "done" else stage)
        out += [_item(kind, p.parent) for p in base.glob("*/report.md")]
    return sorted(out, key=lambda it: it["id"])


def to_check(with_shots: bool = False) -> dict:
    """For the coach page: how many fixes wait for the user, and (if asked) each with its screenshot."""
    import base64

    rows = items("check")
    if not with_shots:
        return {"count": len(rows), "items": []}
    for row in rows:
        shot = row.pop("shot")
        row["shot"] = "data:image/jpeg;base64," + base64.b64encode(shot.read_bytes()).decode() if shot else ""
    return {"count": len(rows), "items": rows}


def vault() -> pathlib.Path | None:
    """The Obsidian vault Backlog.md goes in: MIDI_COACH_VAULT (default ~/Vault, 'off' for none),
    used only if it has a Projects/MidiCoach folder."""
    import os

    setting = os.environ.get("MIDI_COACH_VAULT", "")
    if setting.lower() in ("off", "none", "0"):
        return None
    path = pathlib.Path(setting) if setting else pathlib.Path.home() / "Vault"
    return path if (path / BACKLOG_NOTE).parent.is_dir() else None


def _backlog_lines(it: dict, mark: str, shots: pathlib.Path) -> list[str]:
    tag = "Idea" if it["kind"] == "request" else "Bug"
    said = it["said"] if len(it["said"]) <= 160 else it["said"][:159].rstrip() + "…"
    out = [f"- {mark} **{tag}:** {said}",
           f"  *{it['where']}* · `{it['id']}`" if it["where"] else f"  `{it['id']}`"]
    if it["fix"]:
        out.append(f"  Fix: {it['fix']}" + (f" ([[{it['log']}]])" if it["log"] else ""))
    if it["shot"] is not None:
        name = f"{it['kind']}-{it['id']}.jpg"
        if not (shots / name).exists():
            shots.mkdir(parents=True, exist_ok=True)
            (shots / name).write_bytes(it["shot"].read_bytes())
        out.append(f"  ![[{name}|320]]")
    return ["  \n".join(out)]


def write_backlog() -> pathlib.Path | None:
    """Rewrite the vault's Backlog.md from the folders (never fails the caller)."""
    try:
        root = vault()
        if root is None:
            return None
        shots = root / BACKLOG_SHOTS
        cutoff = time.time() - DONE_SHOWN_DAYS * 86400
        done = [it for it in items("done") if it["when"] >= cutoff][::-1]
        lines = ["---", "project: MidiCoach", "tags: [backlog]", "---", "", "# MidiCoach backlog", "",
                 "> Written by MidiCoach from `~/MidiCoach/bug_reports` and `requests`, so edits here are "
                 "overwritten. Add to it by telling the Maestro “Bug: …” or “Idea: …”. Try fixes from the "
                 "coach page's 👀 button.", ""]
        for title, rows, mark in (("👀 Ready to check", items("check"), "👀"), ("🆕 Open", items("open"), "🆕"),
                                  (f"✅ Done (last {DONE_SHOWN_DAYS} days)", done, "✅")):
            lines += [f"## {title}", ""]
            if mark == "👀" and rows:
                lines += ["[Try them on the coach page](http://127.0.0.1:8765/#checks) (on this PC, with the coach running)", ""]
            if not rows:
                lines += ["*Nothing here.*", ""]
            for it in rows:
                lines += _backlog_lines(it, "↩️" if mark == "🆕" and it["reopened"] else mark, shots) + [""]
        lines += ["## Related", "", "- [[index|MidiCoach index]]", ""]
        note = root / BACKLOG_NOTE
        text = "\n".join(lines)
        if not note.exists() or note.read_text(encoding="utf-8") != text:
            note.write_text(text, encoding="utf-8")
        return note
    except Exception as exc:
        log.info("backlog: %s", exc)
        return None


def _main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="python -m midi_coach.bugs",
                                description="Bug reports and requests: list them, mark one fixed, rewrite the backlog.")
    sub = p.add_subparsers(dest="what", required=True)
    sub.add_parser("list", help="every report and request, by stage")
    ready = sub.add_parser("ready", help="a fix is in: move a report to check/ for the user to try")
    ready.add_argument("id", help="the report's folder name, e.g. 2026-11-03_20-38-42")
    ready.add_argument("summary", help="what changed, in a sentence or two the user will read")
    ready.add_argument("--log", default="", help="the build log's note name in the vault")
    shut = sub.add_parser("close", help="done without a fix, on the user's word (not a bug, already works)")
    shut.add_argument("id")
    shut.add_argument("reason", help="why, in the user's terms")
    sub.add_parser("backlog", help="rewrite the vault's Backlog.md")
    args = p.parse_args(argv)
    if args.what == "close":
        out = close(args.id, args.reason)
        print(out.get("error") or f"{args.id}: closed")
        return 1 if "error" in out else 0
    if args.what == "ready":
        out = mark_ready(args.id, args.summary, args.log)
        print(out.get("error") or f"{args.id}: ready to check")
        return 1 if "error" in out else 0
    if args.what == "list":
        for stage in ("open", "check", "done"):
            for it in items(stage):
                print(f"{stage:5}  {it['kind']:7}  {it['id']}  {it['said'][:90]}")
        return 0
    print(write_backlog() or "No vault: set MIDI_COACH_VAULT to one with a Projects/MidiCoach folder.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
