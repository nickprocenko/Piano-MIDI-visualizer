"""The backlog runner: watches the bug reports and requests (bugs.py) and starts Claude Code
workers on them whenever a worker slot is free, at any hour, with no daily cap.

- Up to two workers at once (MIDI_COACH_WORKERS). Each takes a whole batch (one area of the app)
  with bugs.take_batch, so two workers never change the same file.
- Untriaged items are triaged first, by one worker, read-only.
- Each worker builds in its own git worktree (fixgit.worktree): the user's folder is never touched,
  and its fixes wait on a side branch until the user's ✅ on the coach page.
- A worker only gets what fixing needs: read anything, edit files in its own worktree, the
  project's Python, and read-only git. Anything else is refused.
- An item a worker couldn't finish is set aside as stuck (bugs.stuck), never retried by itself.
- When the account's usage runs out, claims are given back and the runner waits, then tries again.
- One runner at a time (fixgit.acquire). Started at login by a Windows scheduled task (--install).

Log: <home>/runner/<date>.log.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import subprocess
import sys
import threading
import time

from . import bugs, fixgit
from .atlas import claude_run
from .library import home

SLOTS = int(os.environ.get("MIDI_COACH_WORKERS") or 2)
MODEL = os.environ.get("MIDI_COACH_RUNNER_MODEL") or "opus"
POLL_SEC = 60
WORKER_TIMEOUT_SEC = 2 * 3600
LIMIT_PAUSE_SEC = 30 * 60
FIRST_PORT = 8799  # worker-1's throwaway coach; worker-2 gets the next one (the real coach is on 8765)
NAME = "runner"
TASK = "MidiCoach backlog runner"
PY = ".venv/Scripts/python"  # as a worker types it, inside its worktree (linked to the real .venv)


def log(msg: str) -> None:
    folder = home() / "runner"
    folder.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with (folder / f"{datetime.date.today():%Y-%m-%d}.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if sys.stdout:
        print(line, flush=True)


def prepare(name: str) -> pathlib.Path:
    """The worker's worktree, fresh from the user's last commit, with .venv linked in so the
    project's Python runs there (and imports the worktree's own code)."""
    tree = fixgit.worktree(name)
    venv = fixgit.repo() / ".venv"
    link = tree / ".venv"
    if venv.is_dir() and not link.exists():
        if os.name == "nt":  # a junction: no admin rights needed
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(venv)], capture_output=True, check=True)
        else:
            link.symlink_to(venv, target_is_directory=True)
    return tree


def allowed_tools() -> str:
    """What a worker may do: read anything; edit only inside its own worktree (its cwd); run the
    project's Python; read-only git. In dontAsk mode everything else is refused."""
    rules = ["Read", "Glob", "Grep", "Edit(./**)", "Write(./**)"]
    for py in (PY, PY + ".exe", PY.replace("/", "\\"), PY.replace("/", "\\") + ".exe"):
        rules.append(f"Bash({py}:*)")
    for cmd in ("status", "diff", "log", "show", "checkout --", "restore"):
        rules.append(f"Bash(git {cmd}:*)")
    return ",".join(rules)


def _items_text(ids: list[str]) -> str:
    rows = {it["id"]: it for it in bugs.items("open")}
    out = []
    for item_id in ids:
        it = rows.get(item_id)
        if it is None:
            continue
        files = ", ".join((it["triage"] or {}).get("files") or []) or "not named yet"
        where = bugs.stage_dir(it["kind"], "open") / item_id
        out.append(f"- {item_id} ({'bug' if it['kind'] == 'bug' else 'idea'}){' IMPORTANT' if it['important'] else ''}: "
                   f"{it['said'][:400]}\n  Folder: {where}\n  Files: {files}")
    return "\n".join(out)


COMMON = """You are {name}, one of MidiCoach's unattended backlog workers. Nobody is watching, so
don't ask questions in your reply: decide, ask Nick through the backlog (below), or set the item
aside as stuck. An item whose report.md has an "## Answered" section has Nick's answer: follow it.

You're in your own git worktree ({tree}), branch runner/{name}, made from Nick's latest commit.
Work only in this folder. Nick's own folder, his real coach (port 8765) and the Obsidian vault are
off limits.

What you can run is limited, so:
- Look at files with the Read, Grep and Glob tools, never cat/grep/head/ls in Bash.
- In Bash, run one command at a time: no `;`, `&&`, `|` or redirects, and no other programs.
  Allowed: `{py} ...` (the project's Python, from this folder; write a script if you need more),
  read-only git (status, diff, log, show) and `git checkout -- <file>` / `git restore` to throw
  away your own edits.
- If a command is refused, only that command was refused: run it again on its own, in the form
  above. `{py} -m midi_coach.bugs ...` on its own is always allowed.

Each item's folder has report.md (what Nick said, the practice context, the page's errors),
state.json and JPEG screenshots: read them and look at the screenshots."""

BUILD = COMMON + """

Your batch is "{area}". You've already claimed these items; work them in this order:
{items}

For each item, following CLAUDE.md (bug reports, triage and batches, the sheet music conventions):
1. Understand it from the report and screenshots, and find the cause in the code.
2. Reproduce it if you can: a throwaway coach on port {port} with MIDI_COACH_HOME set to a copy
   of the data in a temp folder (never write to the real one), headless Chrome for the page.
3. Fix the cause, keeping to the files the triage named where you can.
4. Run the full test suite: `{py} -m pytest midi_coach/tests -q`. Everything must pass.
5. `{py} -m midi_coach.bugs ready <id> "<what changed, a sentence or two for Nick>" --files <the repo paths you changed> --by {name}`
   That commits just those files on your branch. Nick tries it and presses ✅ to take it.
If building it would mean guessing what Nick wants (two fair readings of the report, or a choice
that changes how he'd practise), throw away your edits for it and ask him instead:
`{py} -m midi_coach.bugs ask <id> --question "<one question, in his terms>" --choice "<answer>" --choice "<answer>" --by {name}`
(two to four choices, each one he could just pick). He answers on the coach page or to the
Maestro, and the item comes back to a worker with his answer. Then go on to the next.
If you can't finish an item for any other reason (you can't find or reproduce it, a command was
refused, the tests won't pass), throw away your edits for it, run
`{py} -m midi_coach.bugs stuck <id> "<why, one sentence>" --by {name}` and go on to the next.

End with one line per item: its id, then "ready", "asked" or "stuck", then a few words."""

TRIAGE = COMMON + """

Triage these open items. You've already claimed them. Don't change any code:
{items}

For each, as CLAUDE.md's "Triage and batches" says: read the report and screenshots, find the code
a fix would change, then run
`{py} -m midi_coach.bugs triage <id> --area "<area>" --size S|M|L --files <comma-separated repo paths> [--risk "..."] [--after <ids>] --needs build|question|design`
Reuse an area from `{py} -m midi_coach.bugs batches` when one fits. Use --needs question (one
--question, two to four --choice) when building it would mean guessing what Nick wants, and
--needs design for a new mode or workflow.

End with one line per item: its id, then its area and what it needs."""


class Runner:
    """One runner: fills free slots with workers each tick. `launch` runs Claude Code
    (claude_run.run), replaceable in tests; `wait` makes tick() wait for the workers it started."""

    def __init__(self, launch=claude_run.run, slots: int = SLOTS, wait: bool = False):
        self.launch, self.slots, self.wait = launch, slots, wait
        self.busy: dict[str, str] = {}  # worker name -> what it is doing ("triage" / "build")
        self.paused_until = 0.0
        self.lock = threading.Lock()

    def free_names(self) -> list[str]:
        with self.lock:
            return [f"worker-{n}" for n in range(1, self.slots + 1) if f"worker-{n}" not in self.busy]

    def tick(self) -> list[str]:
        """Start a worker in each free slot that has something to do. Returns what was started."""
        if time.time() < self.paused_until:
            return []
        started = []
        for name in self.free_names():
            job = self._next_job(name)
            if job is None:
                break
            started.append(f"{name}: {job['what']}")
            thread = threading.Thread(target=self._work, args=(name, job), daemon=True)
            with self.lock:
                self.busy[name] = job["kind"]
            thread.start()
            if self.wait:
                thread.join()
        return started

    def _next_job(self, name: str) -> dict | None:
        triaging = "triage" in self.busy.values()
        free = [it for it in bugs.batches()["untriaged"] if not it["claimed"]]
        if free and not triaging:
            tree = prepare(name)
            ids = [it["id"] for it in free if "claimed" in bugs.claim(it["id"], name, dirty={})]
            if ids:
                return {"kind": "triage", "ids": ids, "tree": tree, "what": f"triage {len(ids)} item(s)",
                        "prompt": TRIAGE.format(name=name, tree=tree, py=PY, items=_items_text(ids))}
        plan = bugs.take_batch(name, dirty={})
        if "claimed" not in plan:
            return None
        tree = prepare(name)
        port = FIRST_PORT + int(name.rsplit("-", 1)[1]) - 1
        return {"kind": "build", "ids": plan["claimed"], "tree": tree, "what": f"batch '{plan['batch']}' ({len(plan['claimed'])})",
                "prompt": BUILD.format(name=name, tree=tree, py=PY, area=plan["batch"], port=port,
                                       items=_items_text(plan["claimed"]))}

    def _work(self, name: str, job: dict) -> None:
        log(f"{name} starts: {job['what']}: {', '.join(job['ids'])}")
        try:
            out = self.launch(job["prompt"], MODEL, tools="Read,Glob,Grep,Edit,Write,Bash", cwd=job["tree"],
                              timeout=WORKER_TIMEOUT_SEC, env={"MIDI_COACH_REPO": str(job["tree"])},
                              extra=["--allowedTools", allowed_tools()])
        except Exception as exc:  # never let one worker take the runner down
            out = {"error": f"{type(exc).__name__}: {exc}", "usage_limit": False}
        try:
            self._finish(name, job, out)
        finally:
            with self.lock:
                self.busy.pop(name, None)

    def _finish(self, name: str, job: dict, out: dict) -> None:
        said = (out.get("result") or out.get("error") or "").strip()
        left = [it for it in bugs.items("open") if it["id"] in job["ids"] and (it["claimed"] or {}).get("by") == name]
        if out.get("usage_limit"):
            self.paused_until = time.time() + LIMIT_PAUSE_SEC
            for it in left:
                bugs.release(it["id"])
            log(f"{name}: usage limit reached; gave back {len(left)} item(s), waiting {LIMIT_PAUSE_SEC // 60} min")
            return
        for it in left:
            if job["kind"] == "triage" and it["triage"] is not None:
                bugs.release(it["id"])  # triaged: back in the queue for a build worker
            else:
                why = ("it didn't finish: " + said.splitlines()[-1][:200]) if said else "it stopped without saying why"
                bugs.stuck(it["id"], why, name)
        log(f"{name} done ({'error' if 'error' in out else 'ok'}): " + (said[-600:] or "(nothing said)").replace("\n", " | "))


def run_forever() -> int:
    held = fixgit.acquire(NAME)
    if "error" in held:
        log(held["error"])
        return 1
    log(f"runner started: {SLOTS} worker slot(s), model {MODEL}")
    runner = Runner()
    try:
        while True:
            try:
                for line in runner.tick():
                    log("started " + line)
            except Exception as exc:  # a bad report, git trouble: say so and carry on next tick
                log(f"tick failed: {type(exc).__name__}: {exc}")
            time.sleep(POLL_SEC)
    finally:
        fixgit.release(NAME)


def install() -> int:
    """A Windows scheduled task that starts the runner at login, windowless, from this checkout."""
    pyw = fixgit.repo() / ".venv" / "Scripts" / "pythonw.exe"
    ps = (f"$a = New-ScheduledTaskAction -Execute '{pyw}' -Argument '-m midi_coach.runner' -WorkingDirectory '{fixgit.repo()}'; "
          "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
          "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
          f"Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s -Force | Out-Null")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print(done.stderr.strip() or f"Installed: '{TASK}' starts at login.")
    return done.returncode


def uninstall() -> int:
    done = subprocess.run(["powershell", "-NoProfile", "-Command",
                           f"Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false"], capture_output=True, text=True)
    print(done.stderr.strip() or f"Removed '{TASK}'.")
    return done.returncode


def _main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="python -m midi_coach.runner", description=__doc__.split("\n\n")[0])
    p.add_argument("--install", action="store_true", help="start it at Windows login (a scheduled task)")
    p.add_argument("--uninstall", action="store_true", help="remove that scheduled task")
    p.add_argument("--once", action="store_true", help="fill the free slots once, wait for those workers, then stop")
    args = p.parse_args(argv)
    if args.install:
        return install()
    if args.uninstall:
        return uninstall()
    if args.once:
        held = fixgit.acquire(NAME)
        if "error" in held:
            print(held["error"])
            return 1
        try:
            started = Runner(wait=True).tick()
            print("\n".join(started) or "Nothing to do.")
        finally:
            fixgit.release(NAME)
        return 0
    return run_forever()


if __name__ == "__main__":
    sys.exit(_main())
