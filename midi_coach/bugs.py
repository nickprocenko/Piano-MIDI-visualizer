"""Bug reports by voice: "Maestro, bug: the cursor jumped to bar five" saves what was said,
screenshots, the practice context and the coach's recent log to
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


class BugLog:
    def __init__(self, ring: ScreenRing, grab=grab, logs: LogRing | None = None) -> None:
        self.ring = ring
        self.grab = grab
        self.logs = logs

    def report(self, said: str, context: str = "", kind: str = "bug") -> dict:
        """A new report ('bug' or 'request'): what was said, a screenshot now and the frames before it."""
        now = time.time()
        folder = reports_dir(kind) / time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now))
        folder.mkdir(parents=True, exist_ok=True)
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
        if self.logs is not None and self.logs.lines:
            lines += ["", "## Coach log before the report", "", "```", *self.logs.lines, "```"]
        (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info("%s saved: %s", TITLES[kind].lower(), folder)
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
