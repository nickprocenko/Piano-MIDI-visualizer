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
import os
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
IMPORTANT_RE = re.compile(r"^(?:maestro\s+)?(?:important|urgent|priority|high priority)\s+(?=(?:bug|idea|feature|request|suggestion|wish))")
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

    def report(self, said: str, context: str = "", kind: str = "bug", state: dict | None = None,
               important: bool = False) -> dict:
        """A new report ('bug' or 'request'): what was said, a screenshot now and the frames before it,
        and (state) where the page was, for the check step's Go there."""
        now = time.time()
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now))
        reports_dir(kind).mkdir(parents=True, exist_ok=True)
        folder, n = reports_dir(kind) / stamp, 2
        while find(folder.name) is not None or folder.exists():  # two reports in one second keep apart
            folder, n = reports_dir(kind) / f"{stamp}-{n}", n + 1
        folder.mkdir()
        if state:
            (folder / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
        shots = []
        for ago, jpeg in self.ring.recent(now):
            name = f"before-{round(ago):02d}s.jpg"
            (folder / name).write_bytes(jpeg)
            shots.append(name)
        shots += self._shot_now(folder, "now.jpg")
        lines = [f"# {TITLES[kind]} {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}", ""]
        if important:
            lines += ["## Priority", "", "Important (the user said so).", ""]
        lines += ["## What was said", "", said.strip() or "(nothing more was said)", "",
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


def said_important(heard: str) -> tuple[bool, str]:
    """("Important bug: …" → True, the words without "important"), lower-cased and tidied."""
    text = " ".join(re.sub(r"[^a-z0-9' ]+", " ", (heard or "").lower()).split())
    m = IMPORTANT_RE.match(text)
    return (True, text[m.end():]) if m else (False, text)


def heard_command(heard: str) -> tuple[str, str] | None:
    """('report' | 'request' | 'more', the rest of what was said) when speech is a bug or request command."""
    text = said_important(heard)[1]
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
    return " ".join(COMMIT_RE.sub("", LOG_LINK_RE.sub("", body)).split()), (m.group(1) if m else "")


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


CLAIM_STALE_SEC = 3 * 3600  # a claim older than this was left by a worker that stopped
COMMIT_RE = re.compile(r"^Commit: ([0-9a-f]{6,40})\s*$", re.M)


def claimed_by(folder: pathlib.Path) -> dict | None:
    """Who is working on an item now ({by, at, dirty}), if anyone (a stale claim counts as none)."""
    try:
        claim = json.loads((folder / "claim.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return claim if time.time() - float(claim.get("at", 0)) < CLAIM_STALE_SEC else None


def claim(report_id: str, by: str, dirty: dict | None = None) -> dict:
    """A worker takes an open item before touching any code, so no other worker takes it too. Also
    notes which files already had uncommitted changes (the user's), so the fix's commit leaves them be.
    `dirty`: that note given instead (a runner's worker starts in a clean worktree: {})."""
    from . import fixgit

    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage != "open":
        return {"error": f"{report_id} is in {stage}/, not open/."}
    path = folder / "claim.json"
    held = claimed_by(folder)
    if held and held.get("by") != by:
        return {"error": f"{report_id} is being worked on by {held.get('by')}."}
    path.unlink(missing_ok=True)  # a stale claim, or this worker's own
    try:
        dirty = fixgit.dirty_files() if dirty is None else dirty
    except Exception as exc:  # not a git checkout: the fix just won't be committed
        dirty, log_note = None, str(exc)
        log.info("claim: %s", log_note)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # two workers at once: one wins
    except FileExistsError:
        return {"error": f"{report_id} was just taken by another worker."}
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"by": by, "at": time.time(), "dirty": dirty}, f)
    write_backlog()
    return {"claimed": report_id, "by": by}


def release(report_id: str) -> dict:
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    (found[2] / "claim.json").unlink(missing_ok=True)
    write_backlog()
    return {"released": report_id}


def stuck(report_id: str, why: str, by: str = "") -> dict:
    """A worker couldn't finish an item (it can't reproduce it, a command was refused, it ran out of
    time): it's given back and set aside, so no worker retries it until someone looks (`unstick`)."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    folder = found[2]
    (folder / "stuck.json").write_text(json.dumps({"by": by, "at": time.time(), "why": why.strip()}), encoding="utf-8")
    (folder / "claim.json").unlink(missing_ok=True)
    write_backlog()
    return {"stuck": report_id}


def unstick(report_id: str) -> dict:
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    (found[2] / "stuck.json").unlink(missing_ok=True)
    write_backlog()
    return {"unstuck": report_id}


def _stuck_of(folder: pathlib.Path) -> dict | None:
    try:
        return json.loads((folder / "stuck.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def take_next(by: str) -> dict:
    """The next item to build, in batch order, claimed for `by`: {"claimed", "batch", ...} or {"none"}."""
    for batch in batches()["batches"]:
        for it in batch["items"]:
            if it["claimed"] is None:
                out = claim(it["id"], by)
                if "claimed" in out:
                    return {**out, "batch": batch["area"], "kind": it["kind"], "said": it["said"],
                            "files": it["triage"]["files"]}
    return {"none": "Nothing triaged and free to build."}


def take_batch(by: str, dirty: dict | None = None) -> dict:
    """A worker takes a whole batch (one area) to build: every free item in the first batch nobody
    else is working on and whose files don't overlap another worker's batch, so two workers never
    change the same file. {"batch", "claimed": [ids], "files"} or {"none"}."""
    plan = batches()["batches"]
    others = [b for b in plan if any(it["claimed"] and it["claimed"].get("by") != by for it in b["items"])]
    busy_files = {f for b in others for it in b["items"] for f in it["triage"]["files"]}
    for batch in plan:
        if batch in others:
            continue
        files = sorted({f for it in batch["items"] for f in it["triage"]["files"]})
        if busy_files & set(files):
            continue
        got = [it["id"] for it in batch["items"] if "claimed" in claim(it["id"], by, dirty)]
        if got:
            return {"batch": batch["area"], "claimed": got, "files": files}
    return {"none": "No batch is free to build (the rest are taken, or share files with one that is)."}


def mark_ready(report_id: str, summary: str, build_log: str = "", files=(), by: str = "") -> dict:
    """An agent fixed it: open/ → check/, with what changed, for the user to try. With `files`,
    the fix is first committed on its own (fixgit.commit_fix), using the claim's note of which
    files the user was editing; if that can't be done, nothing moves and the reason comes back."""
    from . import fixgit

    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage != "open":
        return {"error": f"{report_id} is in {stage}/, not open/."}
    commit = None
    files = [f for f in files if f and f.strip()]
    if files:
        held = claimed_by(folder)
        if held is None or held.get("dirty") is None:
            return {"error": f"Claim {report_id} before working on it (bugs claim), so its commit can leave your own edits alone."}
        if by and held.get("by") != by:
            return {"error": f"{report_id} is claimed by {held.get('by')}."}
        tag = "Fix" if kind == "bug" else "Request"
        out = fixgit.commit_fix(files, f"{tag}: {summary.strip().splitlines()[0][:72]}\n\n{summary.strip()}\n\n"
                                       f"From {kind} report {report_id}.", held["dirty"])
        if "commit" not in out:
            return out
        commit = out["commit"]
        fixgit.keep(commit, report_id)  # a worker's branch is reset for its next batch
    (folder / "claim.json").unlink(missing_ok=True)
    folder = _move(folder, kind, "check")
    lines = [f"# Fixed {time.strftime('%Y-%m-%d %H:%M')}", "", summary.strip()]
    if build_log.strip():
        lines += ["", f"Build log: [[{build_log.strip()}]]"]
    if commit:
        lines += ["", f"Commit: {commit}"]
    (folder / "fix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_backlog()
    return {"ready": report_id, "kind": kind, **({"commit": commit} if commit else {})}


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
    m = COMMIT_RE.search((folder / "fix.md").read_text(encoding="utf-8")) if (folder / "fix.md").exists() else None
    from . import fixgit

    undone = merged = None
    if works:
        kept = ""
        if m:
            merged = fixgit.merge(m.group(1))  # from a worker's side branch onto the user's
            if "merged" not in merged:
                return merged  # stays in check/: the page says why, and ✅ can be pressed again
            fixgit.forget(report_id)
            kept = (f" (commit {m.group(1)}, kept)" if merged.get("already")
                    else f" (commit {m.group(1)}, added to your code as {merged['commit']})")
        addition = ["", f"## Checked {stamp}: works", "", tried + kept]
        folder = _move(folder, kind, DONE[kind])
    else:
        addition = ["", f"## Checked {stamp}: still wrong", "", note.strip() or "(nothing more was said)",
                    "", f"The fix that was tried: {tried}"]
        if m:
            undone = fixgit.undo(m.group(1))
            fixgit.forget(report_id)
            addition += ["", f"Its commit {m.group(1)} was never added to your code, so nothing needed undoing."
                         if "dropped" in undone else
                         f"Its commit {m.group(1)} was undone ({undone['commit']})." if "commit" in undone else
                         f"**Needs an agent:** its commit {m.group(1)} couldn't be undone automatically "
                         f"({undone.get('error')}). Undo it by hand before fixing again."]
        (folder / "fix.md").unlink(missing_ok=True)
        folder = _move(folder, kind, "open")
    with (folder / "report.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(addition) + "\n")
    write_backlog()
    out = {"checked": report_id, "works": works}
    if undone is not None:
        out["undone"] = "commit" in undone or "dropped" in undone
    if merged is not None:
        out["merged"] = merged["commit"]
    return out


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


# ---- Triage: what each open item touches, and batches of them to work on together ----------------
#
# An agent reads each open report and the code, then records (`python -m midi_coach.bugs triage`)
# its area of the app, size, the files a fix would change, what's risky about it, and whether it
# can be built as it stands ("build"), needs one answer from the user first ("question", with
# choices) or needs a design session ("design"). The batching here is plain code: one batch per
# area, so items that change the same part of the app are done together, ordered important first,
# then bugs, then the smallest, then the oldest.

SIZES = {"S": 1, "M": 3, "L": 8}
NEEDS = ("build", "question", "design")
SHARED = {"docs/notation.html": "the coach's sheet and the website's notation strip",
          "midi_coach/live.py": "Learn and Rehearse runs", "midi_coach/midi_io.py": "MIDI in and out, the recorder",
          "midi_coach/notes.py": "every score and part choice", "midi_coach/analysis.py": "grading of every take"}


def is_important(folder: pathlib.Path) -> bool:
    try:
        return "\n## Priority\n" in "\n" + (folder / "report.md").read_text(encoding="utf-8")
    except OSError:
        return False


def set_important(report_id: str, on: bool = True) -> dict:
    """Mark a report important (or not) after it was made."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    report = found[2] / "report.md"
    text = report.read_text(encoding="utf-8")
    block = "## Priority\n\nImportant (the user said so).\n\n"
    if on and not is_important(found[2]):
        head, _, rest = text.partition("\n\n")
        text = f"{head}\n\n{block}{rest}"
    elif not on:
        text = text.replace(block, "")
    report.write_text(text, encoding="utf-8")
    write_backlog()
    return {"id": report_id, "important": on}


def triage(report_id: str, area: str, size: str, files=(), needs: str = "build", risk: str = "",
           question: str = "", choices=(), depends_on=()) -> dict:
    """Record an agent's triage of an open item (triage.json next to its report)."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    size = (size or "").upper()[:1]
    if size not in SIZES:
        return {"error": "Size is S, M or L."}
    if needs not in NEEDS:
        return {"error": f"Needs is one of {', '.join(NEEDS)}."}
    if needs == "question" and not (question.strip() and len([c for c in choices if c.strip()]) >= 2):
        return {"error": "A question needs its text and at least two choices."}
    files = sorted({f.strip().replace("\\", "/") for f in files if f.strip()})
    shared = [f"{f}: {SHARED[f]}" for f in files if f in SHARED]
    data = {"area": " ".join(area.lower().split()) or "other", "size": size, "files": files, "needs": needs,
            "risk": risk.strip(), "shared": shared, "question": question.strip() if needs == "question" else "",
            "choices": [c.strip() for c in choices if c.strip()] if needs == "question" else [],
            "depends_on": [d for d in depends_on if d], "at": time.strftime("%Y-%m-%d %H:%M")}
    (found[2] / "triage.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    write_backlog()
    return {"triaged": report_id, **data}


def ask(report_id: str, question: str, choices=(), by: str = "") -> dict:
    """A worker building an item found it needs a decision only the user can make: the item goes
    to ❓ Needs you with the question (its triage otherwise kept) and the worker's claim is given
    back, instead of the item being set aside as stuck or built on a guess."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage != "open":
        return {"error": f"{report_id} is in {stage}/, not open/."}
    choices = [c.strip() for c in choices if c and c.strip()]
    if not question.strip() or len(choices) < 2:
        return {"error": "A question needs its text and at least two choices."}
    t = _triage_of(folder) or {"area": "other", "size": "M", "files": [], "risk": "", "shared": [], "depends_on": []}
    t.update(needs="question", question=question.strip(), choices=choices[:4], asked_by=by,
             at=time.strftime("%Y-%m-%d %H:%M"))
    (folder / "triage.json").write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "claim.json").unlink(missing_ok=True)
    write_backlog()
    return {"asked": report_id, "question": t["question"], "choices": t["choices"]}


def answer(report_id: str, choice: str, how: str = "on the coach page") -> dict:
    """The user answered an item's ❓ question: their answer goes in report.md (where a worker reads
    it) and the item joins its area's batch to be built. `choice` is one of the choices as written,
    its number (1-4), or the user's own words."""
    found = find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    t = _triage_of(folder)
    if stage != "open" or not t or t.get("needs") != "question":
        return {"error": f"{report_id} isn't waiting for an answer."}
    choice = (choice or "").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(t["choices"]):
        choice = t["choices"][int(choice) - 1]
    if not choice:
        return {"error": "Pick one of the answers, or write your own."}
    own = choice not in t["choices"]
    with (folder / "report.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## Answered {time.strftime('%Y-%m-%d %H:%M')} ({how})\n\n"
                f"Q: {t['question']}\n\nA: {choice}" + (" (in their own words)" if own else "") + "\n\n"
                "Build it this way. The answer was given after triage, so check the triage's files still fit.\n")
    t.update(needs="build", answered={"question": t["question"], "answer": choice, "own": own},
             question="", choices=[])
    (folder / "triage.json").write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")
    write_backlog()
    return {"answered": report_id, "answer": choice, "area": t["area"]}


ASK_RE = re.compile(r"^(?:maestro\s+)?(?:(?:do you have |have you got |are there |any )+(?:any )?questions?(?: for me)?|"
                    r"what (?:are|is) (?:your|the) questions?|(?:read me |ask me )?(?:the |your )?questions? for me|"
                    r"ask me (?:your|the) questions?)$")
SKIP_RE = re.compile(r"^(?:maestro\s+)?(?:skip(?: (?:it|that|this)(?: one)?)?(?: question)?|next question|ask me later|later)$")
NUMBERS = {"one": 1, "won": 1, "first": 1, "two": 2, "to": 2, "too": 2, "second": 2, "three": 3, "third": 3,
           "four": 4, "for": 4, "fourth": 4, "1": 1, "2": 2, "3": 3, "4": 4}
PICK_RE = re.compile(r"^(?:maestro\s+)?(?:(?:answer|option|number|choice|choose|pick|go with|i'll go with|i pick|i choose)\s+)?"
                     r"(?:the\s+)?(one|won|two|to|too|three|four|for|first|second|third|fourth|[1-4])(?:\s+(?:one|option|please))?$")
OWN_RE = re.compile(r"^(?:maestro\s+)?(?:my )?answer(?: is)?\s+(.+)$")


def heard_answer(heard: str, asking: bool) -> tuple[str, str] | None:
    """Speech about the ❓ questions: ('ask', '') for "any questions?", and while one is being asked
    ('skip', '') or ('answer', '2' | the user's own words). None for anything else."""
    text = " ".join(re.sub(r"[^a-z0-9' ]+", " ", (heard or "").lower()).split())
    if ASK_RE.match(text):
        return "ask", ""
    if not asking:
        return None
    if SKIP_RE.match(text):
        return "skip", ""
    m = PICK_RE.match(text)
    if m:
        return "answer", str(NUMBERS[m.group(1)])
    m = OWN_RE.match(text)
    if m:
        return "answer", m.group(1)
    return None


def spoken_question(q: dict, n: int, total: int) -> str:
    """One ❓ question as the Maestro says it, with its choices numbered."""
    said = q["said"] if len(q["said"]) <= 110 else q["said"][:110].rsplit(" ", 1)[0] + "…"
    head = f"Question {n} of {total}" if total > 1 else "One question"
    choices = " ".join(f"{word}: {c}." for word, c in zip(("One", "Two", "Three", "Four"), q["choices"]))
    return (f"{head}, about your {'idea' if q['kind'] == 'request' else 'bug'}: “{said}” {q['question']} {choices} "
            "Say “answer” and its number, “my answer is” and your own words, or “skip”.")


def questions() -> list[dict]:
    """The ❓ items for the coach page and the Maestro, most urgent first: {id, kind, said, where,
    question, choices, important}."""
    return [{"id": it["id"], "kind": it["kind"], "said": it["said"], "where": it["where"],
             "question": it["triage"]["question"], "choices": it["triage"]["choices"], "important": it["important"]}
            for it in batches()["questions"]]


def _triage_of(folder: pathlib.Path) -> dict | None:
    try:
        return json.loads((folder / "triage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def batches() -> dict:
    """The open items, sorted: {"batches": [{area, items, important, size}], "questions", "design",
    "untriaged"}. A batch holds the buildable items of one area; batches go most urgent first."""
    out = {"batches": [], "questions": [], "design": [], "untriaged": [], "stuck": []}
    areas: dict[str, list] = {}
    for it in items("open"):
        t = it["triage"]
        if it["stuck"]:
            out["stuck"].append(it)
        elif t is None:
            out["untriaged"].append(it)
        elif t["needs"] == "question":
            out["questions"].append(it)
        elif t["needs"] == "design":
            out["design"].append(it)
        else:
            areas.setdefault(t["area"], []).append(it)

    def item_key(it):
        return (not it["important"], it["kind"] != "bug", SIZES[it["triage"]["size"]], it["id"])

    for area, rows in areas.items():
        rows.sort(key=item_key)
        out["batches"].append({"area": area, "items": rows, "important": any(r["important"] for r in rows),
                               "bugs": sum(r["kind"] == "bug" for r in rows),
                               "size": sum(SIZES[r["triage"]["size"]] for r in rows)})
    out["batches"].sort(key=lambda b: (not b["important"], not b["bugs"], b["size"], b["items"][0]["id"]))
    for key in ("questions", "design", "untriaged", "stuck"):
        out[key].sort(key=lambda it: (not it["important"], it["id"]))
    return out


def _item(kind: str, folder: pathlib.Path) -> dict:
    report = folder / "report.md"
    text = report.read_text(encoding="utf-8")
    fixed, build_log = _fix_parts(folder)
    shot = folder / "now.jpg"
    return {"id": folder.name, "kind": kind, "said": _said(text, limit=2000), "where": _where(text),
            "fix": fixed, "log": build_log, "reopened": ": still wrong" in text,
            "important": "\n## Priority\n" in "\n" + text, "triage": _triage_of(folder),
            "claimed": claimed_by(folder), "stuck": _stuck_of(folder),
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
    out = [f"- {mark} {'⭐ ' if it.get('important') else ''}**{tag}:** {said}",
           f"  *{it['where']}* · `{it['id']}`" if it["where"] else f"  `{it['id']}`"]
    if it.get("claimed"):
        out.append(f"  🔧 Being worked on by {it['claimed']['by']} since "
                   f"{time.strftime('%H:%M', time.localtime(it['claimed']['at']))}")
    if it.get("stuck") and mark == "🧱":
        out.append(f"  🧱 {it['stuck'].get('by') or 'A worker'} got stuck: {it['stuck'].get('why') or '(no reason given)'}")
    t = it.get("triage")
    if t and mark not in ("✅",):
        out.append(f"  Size {t['size']} · {', '.join(t['files']) or 'files not named'}"
                   + (f" · ⚠️ {t['risk']}" if t["risk"] else "")
                   + (f" · shared: {'; '.join(t['shared'])}" if t["shared"] else "")
                   + (f" · after {', '.join(t['depends_on'])}" if t["depends_on"] else ""))
        if t["needs"] == "question":
            out.append(f"  ❓ **{t['question']}** " + " · ".join(f"[{c}]" for c in t["choices"]))
        elif t.get("answered"):
            out.append(f"  💬 You answered: {t['answered']['answer']}")
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
        def section(title: str, rows: list, mark: str, intro: str = "") -> None:
            lines.extend([f"## {title}", ""] + ([intro, ""] if intro and rows else []))
            if not rows:
                lines.extend(["*Nothing here.*", ""])
            for it in rows:
                lines.extend(_backlog_lines(it, "↩️" if mark == "🆕" and it["reopened"] else mark, shots) + [""])

        section("👀 Ready to check", items("check"), "👀",
                "[Try them on the coach page](http://127.0.0.1:8765/#checks) (on this PC, with the coach running)")
        plan = batches()
        section("❓ Needs you", plan["questions"], "❓",
                "One answer each, then they join a batch. [Answer on the coach page](http://127.0.0.1:8765/#checks), "
                "or ask the Maestro “any questions?”")
        if plan["stuck"]:
            section("🧱 Stuck", plan["stuck"], "🧱",
                    "A worker couldn't finish these, so they're set aside. Ask an agent session to look, "
                    "or `bugs unstick <id>` to put one back in the queue.")
        lines += ["## 📦 Batches (worked in this order)", ""]
        if not plan["batches"]:
            lines += ["*Nothing triaged and ready to build.*", ""]
        for n, b in enumerate(plan["batches"], 1):
            sizes = "+".join(r["triage"]["size"] for r in b["items"])
            lines += [f"### {n}. {b['area'].capitalize()}{' ⭐' if b['important'] else ''} ({len(b['items'])} · {sizes})", ""]
            for it in b["items"]:
                lines += _backlog_lines(it, "↩️" if it["reopened"] else "🔧", shots) + [""]
        section("🧭 Needs a design session", plan["design"], "🧭",
                "Never built overnight: talk it through first (a grilling session).")
        section("🆕 Not triaged yet", plan["untriaged"], "🆕")
        section(f"✅ Done (last {DONE_SHOWN_DAYS} days)", done, "✅")
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
    ready.add_argument("--files", default="", help="comma-separated repo paths the fix changed: they're committed on their own")
    ready.add_argument("--by", default="", help="the worker that claimed it")
    take = sub.add_parser("claim", help="take an open item before working on it")
    take.add_argument("id")
    take.add_argument("--by", required=True, help="who is working on it, e.g. 'overnight' or 'session'")
    free = sub.add_parser("release", help="give an item back without fixing it")
    free.add_argument("id")
    nxt = sub.add_parser("next", help="claim the next item to build, in batch order")
    nxt.add_argument("--by", required=True)
    stk = sub.add_parser("stuck", help="a worker couldn't finish an item: give it back and set it aside")
    stk.add_argument("id")
    stk.add_argument("why", help="what stopped it, in a sentence")
    stk.add_argument("--by", default="")
    unstk = sub.add_parser("unstick", help="put a stuck item back in the queue")
    unstk.add_argument("id")
    bat = sub.add_parser("take-batch", help="claim the next free batch (one area), skipping any that shares files with another worker's")
    bat.add_argument("--by", required=True)
    shut = sub.add_parser("close", help="done without a fix, on the user's word (not a bug, already works)")
    shut.add_argument("id")
    shut.add_argument("reason", help="why, in the user's terms")
    tri = sub.add_parser("triage", help="record an open item's area, size, files and what it needs")
    tri.add_argument("id")
    tri.add_argument("--area", required=True, help="part of the app, e.g. 'top bar & layout', 'playback & metronome'")
    tri.add_argument("--size", required=True, choices=["S", "M", "L"])
    tri.add_argument("--files", default="", help="comma-separated repo paths a fix would change")
    tri.add_argument("--needs", default="build", choices=NEEDS)
    tri.add_argument("--risk", default="", help="what else this could break, in a few words")
    tri.add_argument("--question", default="", help="with --needs question: the one thing to ask")
    tri.add_argument("--choice", action="append", default=[], help="with --needs question: an answer (two or more)")
    tri.add_argument("--after", default="", help="comma-separated ids this depends on")
    qst = sub.add_parser("ask", help="while building: this needs Nick's decision, so ask him (it goes to ❓ Needs you)")
    qst.add_argument("id")
    qst.add_argument("--question", required=True, help="the one thing to ask, in his terms")
    qst.add_argument("--choice", action="append", default=[], help="an answer he can pick (two to four)")
    qst.add_argument("--by", default="")
    ans = sub.add_parser("answer", help="answer an item's ❓ question (a choice's number or your own words)")
    ans.add_argument("id")
    ans.add_argument("choice")
    sub.add_parser("batches", help="the open items as batches, in the order to work them")
    imp = sub.add_parser("important", help="mark an item important (or --off)")
    imp.add_argument("id")
    imp.add_argument("--off", action="store_true")
    sub.add_parser("backlog", help="rewrite the vault's Backlog.md")
    args = p.parse_args(argv)
    if args.what in ("triage", "important"):
        out = (triage(args.id, args.area, args.size, args.files.split(","), args.needs, args.risk, args.question,
                      args.choice, args.after.split(",")) if args.what == "triage" else set_important(args.id, not args.off))
        print(out.get("error") or f"{args.id}: {args.what} saved")
        return 1 if "error" in out else 0
    if args.what == "batches":
        plan = batches()
        for n, b in enumerate(plan["batches"], 1):
            print(f"batch {n}: {b['area']}{' (important)' if b['important'] else ''}")
            for it in b["items"]:
                t = it["triage"]
                print(f"   {it['id']}  {it['kind']:7} {t['size']}  {it['said'][:70]}  [{', '.join(t['files'])}]")
        for key, label in (("questions", "needs an answer"), ("design", "needs a design session"), ("untriaged", "not triaged")):
            for it in plan[key]:
                print(f"{label}: {it['id']}  {it['kind']:7} {it['said'][:80]}")
        return 0
    if args.what in ("ask", "answer"):
        out = (ask(args.id, args.question, args.choice, args.by) if args.what == "ask"
               else answer(args.id, args.choice, "from the command line"))
        print(out.get("error") or (f"{args.id}: asked, now in ❓ Needs you" if args.what == "ask"
                                   else f"{args.id}: answered ({out['answer']}), now in the {out['area']} batch"))
        return 1 if "error" in out else 0
    if args.what == "close":
        out = close(args.id, args.reason)
        print(out.get("error") or f"{args.id}: closed")
        return 1 if "error" in out else 0
    if args.what == "ready":
        out = mark_ready(args.id, args.summary, args.log, args.files.split(","), args.by)
        print(out.get("error") or f"{args.id}: ready to check" + (f" (commit {out['commit']})" if out.get("commit") else ""))
        return 1 if "error" in out else 0
    if args.what in ("claim", "release"):
        out = claim(args.id, args.by) if args.what == "claim" else release(args.id)
        print(out.get("error") or f"{args.id}: {'claimed' if args.what == 'claim' else 'released'}")
        return 1 if "error" in out else 0
    if args.what == "next":
        out = take_next(args.by)
        if "claimed" in out:
            print(f"{out['claimed']}  ({out['kind']}, batch: {out['batch']})  {out['said'][:100]}  [{', '.join(out['files'])}]")
            return 0
        print(out.get("none") or out.get("error"))
        return 1
    if args.what in ("stuck", "unstick"):
        out = stuck(args.id, args.why, args.by) if args.what == "stuck" else unstick(args.id)
        print(out.get("error") or f"{args.id}: {'set aside' if args.what == 'stuck' else 'back in the queue'}")
        return 1 if "error" in out else 0
    if args.what == "take-batch":
        out = take_batch(args.by)
        if "claimed" in out:
            print(f"batch: {out['batch']}  files: {', '.join(out['files'])}")
            for item_id in out["claimed"]:
                print(f"   {item_id}")
            return 0
        print(out["none"])
        return 1
    if args.what == "list":
        for stage in ("open", "check", "done"):
            for it in items(stage):
                print(f"{stage:5}  {it['kind']:7}  {it['id']}  {it['said'][:90]}")
        return 0
    print(write_backlog() or "No vault: set MIDI_COACH_VAULT to one with a Projects/MidiCoach folder.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
