"""Git for the fixes agents make from bug reports and requests (bugs.py), so they don't step on
each other or on the user's own work:

- a fix is committed on its own when it's marked ready: only the files it changed, and never a
  file the user was already editing (that's asked about instead);
- "Still wrong" on the coach page undoes that commit (git revert), or flags it when the undo
  doesn't apply cleanly;
- one background runner at a time (a lock file in the coach's home).

Nothing here pushes: commits stay on this PC until the user says otherwise.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

from .library import home

LOCK_STALE_SEC = 8 * 3600  # a runner can't take longer than a night; past this its lock is dead


def repo() -> pathlib.Path:
    return pathlib.Path(os.environ.get("MIDI_COACH_REPO") or pathlib.Path(__file__).resolve().parent.parent)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    out = subprocess.run(["git", *args], cwd=repo(), capture_output=True, text=True, encoding="utf-8")
    if check and out.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(out.stderr or out.stdout).strip()}")
    return out


def _norm(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def dirty_files() -> dict[str, str]:
    """Every file with uncommitted changes (or new and not ignored): {repo path: content hash}."""
    out = git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    files: dict[str, str] = {}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in "RC":  # a rename: the old name follows
            i += 1
        full = repo() / path
        files[_norm(path)] = git("hash-object", "--", path).stdout.strip() if full.is_file() else "deleted"
    return files


def commit_fix(files, message: str, before: dict[str, str]) -> dict:
    """Commit just `files` (repo paths) with `message`. `before`: dirty_files() from when the work
    started; a file the user had uncommitted edits in then isn't committed: {"ask": [...]}."""
    paths = sorted({_norm(f) for f in files if f and f.strip()})
    if not paths:
        return {"error": "Name the files the fix changed."}
    theirs = [p for p in paths if p in before]
    if theirs:
        return {"ask": theirs, "error": "These files had your own uncommitted edits before the fix started, so "
                                        "they weren't committed (yours and the fix's would be mixed): " + ", ".join(theirs)}
    now = dirty_files()
    changed = [p for p in paths if p in now]
    if not changed:
        return {"error": "None of those files has changed."}
    git("add", "--", *changed)
    git("commit", "-q", "-m", message, "--", *changed)
    return {"commit": git("rev-parse", "--short", "HEAD").stdout.strip(), "files": changed,
            "unchanged": [p for p in paths if p not in changed]}


def revert(commit: str) -> dict:
    """Undo a fix's commit with a new commit. If it doesn't apply cleanly (a later change touched
    the same lines, or there are edits in the way), nothing is changed and that's said."""
    out = git("revert", "--no-edit", commit, check=False)
    if out.returncode == 0:
        return {"reverted": commit, "commit": git("rev-parse", "--short", "HEAD").stdout.strip()}
    git("revert", "--abort", check=False)
    return {"error": (out.stderr or out.stdout).strip().splitlines()[0] if (out.stderr or out.stdout).strip() else "revert failed"}


# ---- One runner at a time ------------------------------------------------------------------------

def _alive(pid: int) -> bool:
    if sys.platform == "win32":  # os.kill(pid, 0) would *end* the process on Windows
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lock_path() -> pathlib.Path:
    return home() / "runner.lock"


def acquire(name: str) -> dict:
    """Take the runner lock, or say who has it. A lock whose process is gone, or older than a
    night, is taken over."""
    path = lock_path()
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                held = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            if held and _alive(int(held.get("pid", 0))) and time.time() - float(held.get("at", 0)) < LOCK_STALE_SEC:
                return {"error": f"{held.get('by')} is already running (since {time.strftime('%H:%M', time.localtime(held['at']))})."}
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"by": name, "pid": os.getpid(), "at": time.time()}, f)
        return {"locked": name}
    return {"error": "Couldn't take the runner lock."}


def release(name: str) -> None:
    path = lock_path()
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("by") == name:
            path.unlink()
    except (OSError, ValueError):
        pass
