"""Test copies: try a worker's fix in a second coach before it goes anywhere near the real one.

    python -m midi_coach.preview open <report id>    start a test copy of that fix (prints JSON)
    python -m midi_coach.preview close               stop it and clean up
    python -m midi_coach.preview status              what's open (JSON)

A test copy is its own coach process (port 8766) running the fix's commit from a git worktree
under <home>/previews/<id>/code, with its own home under <home>/previews/<id>/home. That home is
filled from the real one when the copy starts: the user's songs, takes, lessons, Roadmap progress
and settings are copied (paths inside the JSON files pointing at the real home are rewritten), and
only the big folders nothing writes to (speech models, downloads) are linked. So the copy sees the
user's real data and nothing it does can change it.

The copy starts with empty bug_reports/ and requests/ folders, so whatever version of the code the
fix was built on, its own check buttons can't touch the real queue. Anything reported from inside
the copy (F9, or said to the Maestro) is moved into the real queue when the copy closes, marked as
found in that fix's test copy.

One test copy at a time: opening another closes the first. Agent Quest's Workshop drives this
(through the coach's /api/fixes, or this command line when the coach is closed).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from . import bugs, fixgit
from .library import home

PORT = 8766       # the test copy's page (the real coach is on 8765)
MCP_PORT = 8781   # its deep-teaching endpoint (the real coach's is 8780)
IDLE_SEC = 30 * 60
START_TIMEOUT = 90

# Top-level folders of the home linked into the test copy, not copied: big, and nothing writes them.
LINKED = {"models", "kokoro", "whisper", "audio-tools", "downloads", "reverie"}
# Not carried over at all: other test copies, the runner's own state, the queue (see above), logs.
SKIPPED = {"previews", "workers", "runner", "runner.lock", "bug_reports", "requests", "maestro_log",
           "crash_logs"}
QUEUES = ("bug_reports", "requests")  # bugs.FOLDERS' folder names
# Copied but not searched for paths to rewrite: thousands of files, and the copy only reads them, so a
# path inside still pointing at the real home is harmless. Saved sheets (derived/) hold no paths; the
# built Roadmap trees inside atlas*/ point at their own built files.
NOT_REWRITTEN = {"derived"}
BUILT_TREES = {"content", "pan", "pan-source", "sax", "voice-high", "voice-low", "fiddle", "guitar", "bass",
               "source", "pieces", "generator"}


def root() -> pathlib.Path:
    return home() / "previews"


def _current_file() -> pathlib.Path:
    return root() / "current.json"


def current() -> dict | None:
    """The open test copy ({id, pid, url, folder, commit, started}), or None."""
    try:
        data = json.loads(_current_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") else None


def _alive(pid: int) -> bool:
    return bool(pid) and fixgit._alive(int(pid))


def status() -> dict:
    cur = current()
    if cur and not _alive(cur.get("pid", 0)):
        return {"open": False, "ended": cur["id"]}  # it exited (or crashed): close() cleans up
    return {"open": bool(cur), **(cur or {})}


# ---- building the copy -----------------------------------------------------------------------

def _link(link: pathlib.Path, target: pathlib.Path) -> None:
    """A folder link that needs no admin rights (a junction on Windows)."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        link.symlink_to(target, target_is_directory=True)


def _is_link(path: pathlib.Path) -> bool:
    return path.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(path))


def _copy_tree(src: pathlib.Path, dst: pathlib.Path) -> None:
    if os.name == "nt" and shutil.which("robocopy"):
        out = subprocess.run(["robocopy", str(src), str(dst), "/E", "/MT:16", "/R:0", "/W:0",
                              "/NFL", "/NDL", "/NJH", "/NJS", "/NP"], capture_output=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode < 8:  # robocopy: 0-7 mean it copied (or had nothing to copy)
            return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _path_spellings(path: pathlib.Path) -> list[str]:
    """How a folder's path can appear inside a JSON file, longest first: backslashes escaped as JSON
    writes them, forward slashes, plain backslashes."""
    text = str(path)
    return [text.replace("\\", "\\\\"), text.replace("\\", "/"), text]


def _rewrite_paths(folder: pathlib.Path, real: pathlib.Path, copy: pathlib.Path) -> int:
    """Point the copied JSON files at the copy: every spelling of the real home's path becomes the
    copy's, so the part choices, takes and progress the copy reads match the files it has."""
    pairs = list(zip(_path_spellings(real), _path_spellings(copy)))
    changed = 0
    files = [p for p in folder.glob("*.json")]
    for top in folder.iterdir():
        if not top.is_dir() or _is_link(top) or top.name in NOT_REWRITTEN:  # links are the real files
            continue
        if top.name.startswith("atlas"):  # the learner's progress, not the built Roadmap trees
            files += top.glob("*.json")
            for sub in top.iterdir():
                if sub.is_dir() and sub.name not in BUILT_TREES:
                    files += sub.rglob("*.json")
        else:
            files += top.rglob("*.json")
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new = text
        for old, repl in pairs:  # the coach writes these from home() itself, so the spelling matches
            new = new.replace(old, repl)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def build_home(real: pathlib.Path, copy: pathlib.Path) -> dict:
    """Fill the test copy's home from the real one (see the module docstring). Returns what it did."""
    copy.mkdir(parents=True, exist_ok=True)
    copied, linked = [], []
    for item in sorted(real.iterdir()):
        name = item.name
        if name in SKIPPED or name.startswith("."):
            continue
        target = copy / name
        if name in LINKED and item.is_dir():
            _link(target, item)
            linked.append(name)
        elif item.is_dir():
            _copy_tree(item, target)
            copied.append(name)
        elif item.is_file():
            shutil.copy2(item, target)
            copied.append(name)
    for queue in QUEUES:
        (copy / queue / "open").mkdir(parents=True, exist_ok=True)
    rewritten = _rewrite_paths(copy, real, copy)
    return {"copied": copied, "linked": linked, "rewritten": rewritten}


def _repo_extras(code: pathlib.Path, home_copy: pathlib.Path) -> None:
    """What a worktree doesn't have because git ignores it: the Python environment and the reference
    library are linked (read-only use); config.json is copied into the copy's home."""
    repo = fixgit.repo()
    for name in (".venv", "reference"):
        src = repo / name
        if src.is_dir() and not (code / name).exists():
            _link(code / name, src)
    config = pathlib.Path(os.environ.get("MIDI_COACH_CONFIG") or repo / "config.json")
    if config.is_file():
        shutil.copy2(config, home_copy / "config.json")


def environment(home_copy: pathlib.Path, report_id: str) -> dict:
    """The environment the test copy runs with."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("MIDI_COACH_")}
    config = home_copy / "config.json"
    env.update({
        "MIDI_COACH_HOME": str(home_copy),
        "MIDI_COACH_DISPLAY_PORT": str(PORT),
        "MIDI_COACH_MCP_PORT": str(MCP_PORT),
        "MIDI_COACH_VAULT": "off",
        "MIDI_COACH_NO_BROWSER": "1",
        "MIDI_COACH_PREVIEW": report_id,
        "MIDI_COACH_PREVIEW_IDLE": str(IDLE_SEC),
        "MIDI_COACH_PREVIEW_OWNER": str(fixgit.repo()),  # where `preview close` runs from
        "MIDI_COACH_PREVIEW_REAL_HOME": str(home()),
        "MIDI_COACH_AI_SPEND": str(home() / "ai_spend.json"),  # the Maestro's daily cap counts both coaches
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",  # its "Music Hub page: …" line reaches the log at once
    })
    if config.is_file():
        env["MIDI_COACH_CONFIG"] = str(config)
    for key in ("MIDI_COACH_DAILY_CAP", "MIDI_COACH_REFERENCE_DIRS"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


# ---- the real coach ---------------------------------------------------------------------------

def _real_coach(name: str, body: dict | None = None, timeout: float = 3.0) -> dict | None:
    """POST a command to the real coach on 8765; None when it isn't running."""
    port = int(os.environ.get("MIDI_COACH_DISPLAY_PORT") or 8765)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/cmd/{name}", data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8") or "{}")
    except Exception:
        return None


# ---- open / close -----------------------------------------------------------------------------

def _fix_info(report_id: str) -> dict:
    found = bugs.find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage != "check":
        return {"error": f"{report_id} isn't waiting to be tried."}
    commit, _tried = bugs._fix_commits(folder)
    if not commit:
        return {"error": "This fix was made straight in your own code, so there's no separate copy to try."}
    fixed, _log = bugs._fix_parts(folder)
    place = bugs.place(report_id)
    return {"kind": kind, "folder": folder, "commit": commit, "fixed": fixed,
            "said": bugs._item(kind, folder).get("said", ""), "place": {} if "error" in place else place}


def open_copy(report_id: str, wait: bool = True) -> dict:
    """Start a test copy of a fix (closing any other first). {url, id, ...} or {error}."""
    info = _fix_info(report_id)
    if "error" in info:
        return info
    cur = current()
    if cur and cur["id"] == report_id and _alive(cur.get("pid", 0)):
        return {**cur, "already": True}
    if cur:
        close()
    busy = _real_coach("code_status")
    if busy and busy.get("busy"):
        return {"error": "The Music Hub is in the middle of a run. Stop it there first, so the test copy can use the keyboard."}
    if busy is not None:
        _real_coach("bluetooth_release")  # a Bluetooth keyboard is free for the test copy

    folder = root() / report_id
    if folder.exists():
        _remove_folder(folder)
    code, home_copy = folder / "code", folder / "home"
    folder.mkdir(parents=True)
    fixgit.git("worktree", "prune")
    fixgit.git("worktree", "add", "-q", "--detach", str(code), info["commit"])
    home_copy.mkdir(parents=True)
    # Written first, so build_home points the report's piece at the copy's files like the rest.
    (home_copy / "preview.json").write_text(json.dumps({
        "id": report_id, "kind": info["kind"], "commit": info["commit"], "fixed": info["fixed"],
        "said": info["said"], "place": info["place"]}, indent=2), encoding="utf-8")
    filled = build_home(home(), home_copy)
    _repo_extras(code, home_copy)

    log = (folder / "coach.log").open("w", encoding="utf-8")
    python = code / ".venv" / "Scripts" / "python.exe" if os.name == "nt" else code / ".venv" / "bin" / "python"
    proc = _spawn([str(python if python.exists() else sys.executable), "-m", "midi_coach.practice"],
                            cwd=code, env=environment(home_copy, report_id), stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    state = {"id": report_id, "pid": proc.pid, "url": "", "folder": str(folder), "commit": info["commit"],
             "fixed": info["fixed"], "said": info["said"], "started": time.time(), "home": filled}
    _current_file().write_text(json.dumps(state, indent=2), encoding="utf-8")
    if not wait:
        return state
    url = _wait_for_url(folder / "coach.log", proc)
    if not url:
        tail = _log_tail(folder / "coach.log")
        close()
        return {"error": "The test copy didn't start." + (f" Its last words: {tail}" if tail else "")}
    state["url"] = url
    _current_file().write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def _spawn(*args, **kwargs) -> subprocess.Popen:  # tests swap this for a fake coach
    return subprocess.Popen(*args, **kwargs)


URL_RE = re.compile(r"(http://127\.0\.0\.1:\d+/)")


def _wait_for_url(log: pathlib.Path, proc: subprocess.Popen) -> str:
    """The page address the copy prints once it's serving ("Music Hub page: http://…")."""
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        try:
            m = URL_RE.search(log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            m = None
        if m:
            return m.group(1)
        if proc.poll() is not None:
            return ""
        time.sleep(0.3)
    return ""


def _log_tail(log: pathlib.Path) -> str:
    try:
        lines = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        return ""
    return lines[-1][:300] if lines else ""


def _kill(pid: int) -> None:
    if not _alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(50):
        if not _alive(pid):
            return
        time.sleep(0.1)


def _remove_folder(folder: pathlib.Path) -> None:
    """Delete a test copy's folder. Links are removed first, on their own, so nothing behind them
    (the real models, the real .venv) is ever touched."""
    for parent in (folder / "home", folder / "code"):
        if parent.is_dir():
            for item in parent.iterdir():
                if _is_link(item):
                    os.rmdir(item) if os.name == "nt" else item.unlink()
    code = folder / "code"
    if code.exists():
        fixgit.git("worktree", "remove", "--force", str(code), check=False)
    shutil.rmtree(folder, ignore_errors=True)
    fixgit.git("worktree", "prune", check=False)


def _bring_back_reports(copy_home: pathlib.Path, report_id: str, fixed: str) -> list[str]:
    """Reports and requests made inside the test copy join the real queue, marked as found there."""
    moved = []
    for queue in QUEUES:
        src = copy_home / queue / "open"
        if not src.is_dir():
            continue
        for item in sorted(src.iterdir()):
            if not (item / "report.md").exists():
                continue
            dst = home() / queue / "open" / item.name
            if dst.exists():
                continue
            with (item / "report.md").open("a", encoding="utf-8") as f:
                f.write(f"\n## Found in a test copy\n\nThis was reported while trying the fix for {report_id}"
                        + (f" ({fixed})" if fixed else "") + ". The test copy was running that fix, "
                        "not your own code.\n")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(dst))
            moved.append(item.name)
    return moved


def close() -> dict:
    """Stop the test copy, bring back what was reported in it, and delete its folder."""
    cur = current()
    if not cur:
        return {"closed": None}
    _kill(int(cur.get("pid") or 0))
    folder = pathlib.Path(cur.get("folder") or root() / cur["id"])
    moved = _bring_back_reports(folder / "home", cur["id"], cur.get("fixed", ""))
    _remove_folder(folder)
    _current_file().unlink(missing_ok=True)
    if moved:
        bugs.write_backlog()
    return {"closed": cur["id"], "reports": moved}


# ---- inside the test copy ---------------------------------------------------------------------

def inside() -> dict | None:
    """In a test copy: what it's testing (its home's preview.json); None in the real coach."""
    if not os.environ.get("MIDI_COACH_PREVIEW"):
        return None
    try:
        return json.loads((home() / "preview.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"id": os.environ["MIDI_COACH_PREVIEW"]}


def close_from_inside() -> None:
    """The test copy's own Close (or its idle timer): `preview close` has to run from the real code
    and the real home, in a process of its own, since it ends this one and deletes its folder."""
    owner = pathlib.Path(os.environ.get("MIDI_COACH_PREVIEW_OWNER") or "")
    real_home = os.environ.get("MIDI_COACH_PREVIEW_REAL_HOME") or ""
    if not owner.is_dir() or not real_home:
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith("MIDI_COACH_")}
    env["MIDI_COACH_HOME"] = real_home
    quiet = {"cwd": owner, "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
             "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        # Through a cmd that exits at once, so the closer isn't in this copy's process tree: close()
        # ends that whole tree (taskkill /T), and would otherwise end the closer with it.
        pythonw = owner / ".venv" / "Scripts" / "pythonw.exe"
        exe = str(pythonw if pythonw.exists() else pathlib.Path(sys.executable).with_name("pythonw.exe"))
        subprocess.Popen(["cmd", "/c", "start", "", "/b", exe, "-m", "midi_coach.preview", "close"],
                         creationflags=subprocess.CREATE_NO_WINDOW, **quiet)
    else:
        python = owner / ".venv" / "bin" / "python"
        subprocess.Popen([str(python if python.exists() else sys.executable), "-m", "midi_coach.preview", "close"],
                         start_new_session=True, **quiet)


def watch_idle(clients, idle_sec: float | None = None, poll: float = 15.0, sleep=time.sleep) -> None:
    """Close the test copy once no page has been connected for idle_sec (runs on a thread)."""
    idle_sec = float(idle_sec if idle_sec is not None else os.environ.get("MIDI_COACH_PREVIEW_IDLE") or IDLE_SEC)
    quiet_since = time.time()
    while True:
        sleep(poll)
        if clients():
            quiet_since = time.time()
        elif time.time() - quiet_since >= idle_sec:
            close_from_inside()
            return


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m midi_coach.preview", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    op = sub.add_parser("open", help="start a test copy of a fix waiting to be tried")
    op.add_argument("id")
    sub.add_parser("close", help="stop the test copy and clean up")
    sub.add_parser("status", help="what's open")
    args = ap.parse_args()
    out = open_copy(args.id) if args.cmd == "open" else close() if args.cmd == "close" else status()
    print(json.dumps(out, default=str, ensure_ascii=False))
    return 1 if "error" in out else 0


if __name__ == "__main__":
    sys.exit(_main())
