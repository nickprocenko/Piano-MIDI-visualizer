"""Open the coach page from the Windows shortcut, always on the code that's on disk.

    python -m midi_coach.launch [piece]        (what "Launch Music Hub.bat" runs)

If a coach is already answering on the display port and it started after the newest source
file changed, the page just opens in it. If it's older (started before an update), a practice
copy is stopped and started fresh; Claude Desktop's midi-coach isn't ours to stop, so the
launcher says to restart Claude Desktop instead of opening a half-working page. Otherwise it
starts the practice page (midi_coach.practice) in this window, as a child process, so the
page's Restart (after an update) can bring it back on the new code in the same window.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

PACKAGE = pathlib.Path(__file__).resolve().parent
SOURCES = (PACKAGE, PACKAGE.parent / "docs" / "notation.html")
SUFFIXES = {".py", ".html", ".js", ".json", ".css"}


def port() -> int:
    from .display import DEFAULT_PORT

    return int(os.environ.get("MIDI_COACH_DISPLAY_PORT") or DEFAULT_PORT)


def running(port: int) -> dict | None:
    """The running coach's {started, pid}; {} for one too old to say; None if nothing answers."""
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url + "version", timeout=2) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError:
        return {}  # a coach, but from before /version
    except (OSError, ValueError):
        return None


def newest_source(roots=SOURCES) -> float:
    """When the coach's code or pages last changed (tests and caches don't count)."""
    newest = 0.0
    for root in roots:
        files = [root] if root.is_file() else (p for p in root.rglob("*") if p.suffix in SUFFIXES)
        for path in files:
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                pass
    return newest


RESTART_EXIT = 75   # the coach page's Restart: the practice copy exits with this, and main() starts it again
SETTLE_SEC = 15     # a file changed more recently than this is still being edited: not an update yet


def code_times(settle: float = SETTLE_SEC, now: float | None = None) -> dict:
    """When the running coach's code and the page's files last changed, counting only changes that
    have settled: {'code': the server's .py/.json, 'page': the files the page loads from disk}."""
    from .display import STATIC_FILES

    cutoff = (time.time() if now is None else now) - settle
    page_files = {file for file, _ in STATIC_FILES.values()}
    newest = {"code": 0.0, "page": 0.0}

    def note(kind: str, path: pathlib.Path) -> None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime <= cutoff:
            newest[kind] = max(newest[kind], mtime)

    for path in page_files:
        note("page", path)
    for path in PACKAGE.rglob("*"):
        if path.suffix in (".py", ".json") and not {"tests", "__pycache__", "static", "youtube_extension"} & set(path.parts):
            note("code", path)
    return newest


def supervise(args: list[str]) -> int:
    """Run the practice page in this window, again each time the page's Restart asks for it."""
    env = {**os.environ, "MIDI_COACH_RESTARTABLE": "1"}
    while True:
        try:
            code = subprocess.call([sys.executable, "-m", "midi_coach.practice", *args], env=env, cwd=PACKAGE.parent)
        except KeyboardInterrupt:
            return 0
        if code != RESTART_EXIT:
            return code
        print("Restarting the Music Hub on the updated code...")
        args = []  # practice.main reopens the piece that was on the page (restart.json)


def is_current(info: dict, newest: float) -> bool:
    return bool(info.get("started")) and info["started"] >= newest


def listener_pid(port: int) -> int | None:
    """The process listening on 127.0.0.1:<port>, from netstat (old coaches don't report their pid)."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 5 and cols[1].endswith(f":{port}") and cols[3] == "LISTENING":
            return int(cols[4])
    return None


def command_line(pid: int) -> str:
    script = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", script],
                              capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def is_practice(cmdline: str) -> bool:
    """A copy this launcher (or `python -m midi_coach.practice`) started, safe to restart."""
    return bool(re.search(r"midi_coach[.\\/]+(practice|launch)\b", cmdline))


def stop(pid: int, port: int) -> bool:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    for _ in range(40):
        if running(port) is None:
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    p = port()
    info = running(p)
    if info is not None:
        if is_current(info, newest_source()):
            webbrowser.open(f"http://127.0.0.1:{p}/")
            return 0
        pid = info.get("pid") or listener_pid(p)
        if not pid or not is_practice(command_line(pid)):
            print("The Music Hub running on port %d is out of date (it was started before an update)." % p)
            print("It looks like Claude Desktop's midi-coach: quit Claude Desktop (File > Exit), then use the shortcut again.")
            return 1
        print("Restarting the Music Hub: the copy that was running started before an update.")
        if not stop(pid, p):
            print(f"Couldn't stop the old copy (process {pid}). Close its window, then use the shortcut again.")
            return 1
    return supervise(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
