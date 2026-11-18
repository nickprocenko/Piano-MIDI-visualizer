"""The runner tests every fix itself, before the user is asked to try it.

A worker says how its tests went, but nothing checked that, and "this test fails on your latest
commit too" was taken on trust. Here the whole suite runs on the fix's commit in a scratch
worktree (<home>/fixtests/tree), and once per commit of the user's own code (the baseline, kept
in <home>/fixtests/baseline.json), so a fix's failures split into the ones it caused (new) and the
ones that were already there. The result is a "Tests: …" line in the fix's fix.md and a `tested`
history line. A fix with new failures is sent back to be fixed again, once (runner.py); after that
the Workshop warns before Works.

    python -m midi_coach.fixtests <report id>     test one fix now (prints JSON)
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

from . import bugs, fixgit, history
from .library import home

SUITE_TIMEOUT = 30 * 60
SUMMARY_RE = re.compile(r"(\d+) (passed|failed|error|errors)\b")
FAILED_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)


def _root() -> pathlib.Path:
    return home() / "fixtests"


def _scratch(commit: str) -> pathlib.Path:
    """A worktree at `commit`, with the project's Python linked in (made once, moved after)."""
    from .preview import _link

    tree = _root() / "tree"
    if not (tree / ".git").exists():
        tree.parent.mkdir(parents=True, exist_ok=True)
        fixgit.git("worktree", "prune", check=False)
        fixgit.git("worktree", "add", "-q", "--detach", str(tree), commit)
    else:
        run = lambda *a: subprocess.run(["git", *a], cwd=tree, capture_output=True, text=True, check=True,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        run("checkout", "-q", "--detach", "--force", commit)
        run("clean", "-q", "-fd")
    venv = fixgit.repo() / ".venv"
    if venv.is_dir() and not (tree / ".venv").exists():
        _link(tree / ".venv", venv)
    return tree


def parse(output: str) -> dict:
    """pytest's -q -rfE output → {passed, failed: [test ids]}."""
    counts = {"passed": 0, "failed": 0}
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    for n, word in SUMMARY_RE.findall(tail):
        counts["passed" if word == "passed" else "failed"] += int(n)
    failed = sorted(set(FAILED_RE.findall(output)))
    return {"passed": counts["passed"], "failed": failed, "ran": bool(tail) and (counts["passed"] or counts["failed"] or failed)}


def run_suite(commit: str, runner=None) -> dict:
    """The midi_coach suite on `commit`: {passed, failed, ran, error?}."""
    tree = _scratch(commit)
    python = tree / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    args = [str(python if python.exists() else sys.executable), "-m", "pytest", "midi_coach/tests", "-q",
            "-p", "no:cacheprovider", "-rfE"]
    env = {**os.environ, "MIDI_COACH_REPO": str(tree), "PYTHONUTF8": "1"}
    try:
        out = (runner or subprocess.run)(args, cwd=tree, env=env, capture_output=True, text=True, encoding="utf-8",
                                          errors="replace", timeout=SUITE_TIMEOUT,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"passed": 0, "failed": [], "ran": False, "error": f"the tests took over {SUITE_TIMEOUT // 60} minutes"}
    result = parse((out.stdout or "") + "\n" + (out.stderr or ""))
    if not result["ran"]:
        last = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()[-1:] or [""]
        result["error"] = "the tests didn't run: " + last[0][:200]
    return result


def baseline(runner=None) -> dict:
    """The suite on the user's own latest commit, kept until that commit changes."""
    head = fixgit.git("rev-parse", "HEAD").stdout.strip()
    path = _root() / "baseline.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("commit") == head:
            return cached
    except (OSError, ValueError):
        pass
    result = {**run_suite(head, runner), "commit": head, "at": time.time()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def summary_line(result: dict) -> str:
    if result.get("error"):
        return f"not checked ({result['error']})"
    parts = [f"{result['passed']} passed"]
    parts.append("new failures: " + (", ".join(result["new"]) if result["new"] else "none"))
    if result["already"]:
        parts.append("already failing: " + ", ".join(result["already"]))
    return " · ".join(parts)


def parse_line(text: str) -> dict | None:
    """A fix.md's Tests line back into {state: pass|fail|unchecked, passed, new, already, line}."""
    m = bugs.TESTS_RE.search(text or "")
    if not m:
        return None
    line = m.group(1).strip()
    if line.startswith("not checked"):
        return {"state": "unchecked", "line": line, "passed": 0, "new": [], "already": []}
    passed = re.match(r"(\d+) passed", line)
    new = re.search(r"new failures: ([^·]+)", line)
    already = re.search(r"already failing: ([^·]+)", line)
    names = lambda m: [] if not m or m.group(1).strip() == "none" else [s.strip() for s in m.group(1).split(",")]
    out = {"passed": int(passed.group(1)) if passed else 0, "new": names(new), "already": names(already), "line": line}
    out["state"] = "fail" if out["new"] else "pass"
    return out


def check(report_id: str, runner=None) -> dict:
    """Test a fix waiting in check/: its failures against the baseline's. Writes the Tests line."""
    found = bugs.find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    _kind, stage, folder = found
    commit, _tried = bugs._fix_commits(folder)
    if stage != "check" or not commit:
        return {"error": f"{report_id} has no fix waiting to be tested."}
    base = baseline(runner)
    fix = run_suite(commit, runner)
    if fix.get("error") or base.get("error"):
        result = {"passed": fix.get("passed", 0), "new": [], "already": [],
                  "error": fix.get("error") or "your own code's tests didn't run: " + base["error"]}
    else:
        before = set(base["failed"])
        result = {"passed": fix["passed"], "new": [t for t in fix["failed"] if t not in before],
                  "already": [t for t in fix["failed"] if t in before]}
    line = summary_line(result)
    path = folder / "fix.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = bugs.TESTS_RE.sub("", text).rstrip("\n") + f"\nTests: {line}\n"
    path.write_text(text, encoding="utf-8")
    history.add(report_id, "tested", passed=result["passed"], new=result["new"], already=result["already"],
                **({"error": result["error"]} if result.get("error") else {}))
    return {"id": report_id, **result, "line": line}


def sent_back_before(report_id: str) -> bool:
    return any(e.get("event") == "sent_back" for e in history.of(report_id))


def _main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = check(sys.argv[1])
    print(json.dumps(out, ensure_ascii=False))
    return 1 if "error" in out and "line" not in out else 0


if __name__ == "__main__":
    sys.exit(_main())
