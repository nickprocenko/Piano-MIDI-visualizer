"""The fix board: everything Agent Quest's Workshop shows and does, in one place.

Agent Quest asks the running Music Hub (POST /cmd/fixes, /cmd/fix_open, …; see server.py), or, when
the Hub is closed, runs this module itself:

    python -m midi_coach.fixes board [--shots]
    python -m midi_coach.fixes open <id>          a test copy of the fix (preview.py)
    python -m midi_coach.fixes close              close the test copy
    python -m midi_coach.fixes works <id> [--save-first]
    python -m midi_coach.fixes still-wrong <id> [--note "…"]
    python -m midi_coach.fixes answer <id> <choice number or words>

Each prints one JSON object. A fix only reaches the user's code through `works`; `still-wrong`
drops it (it never got there), so nothing has to be undone.
"""

from __future__ import annotations

import base64
import json
import sys
import time

from . import bugs, fixgit, preview

DONE_DAYS = 7
# The board's columns, in order.
COLUMNS = ("question", "queued", "building", "ready", "trying", "done")


def _column(it: dict, stage: str, trying: str | None) -> str:
    if stage == "check":
        return "trying" if it["id"] == trying else "ready"
    if stage == "done":
        return "done"
    t = it["triage"] or {}
    if it["claimed"]:
        return "building"
    if t.get("needs") == "question":
        return "question"
    return "queued"


def _outcome(folder) -> str:
    """How a finished item ended: 'works' (its fix was kept) or 'closed' (no fix needed)."""
    text = (folder / "report.md").read_text(encoding="utf-8")
    works, closed = text.rfind(": works\n"), text.rfind(": no fix needed\n")
    return "works" if works > closed else "closed"


def _code_files(commit: str) -> list[str]:
    try:
        out = fixgit.git("diff-tree", "--no-commit-id", "--name-only", "-r", commit, check=False).stdout
    except Exception:
        return []
    return [f for f in out.split("\n") if f.strip()]


def board(shots: bool = False) -> dict:
    """Every item the Workshop shows: open ones (queued, being built, waiting on a question), fixes
    to try, and what was finished in the last week; plus the open test copy, if any."""
    status = preview.status()
    trying = status.get("id") if status.get("open") else None
    rows = []
    cutoff = time.time() - DONE_DAYS * 86400
    for stage in ("open", "check", "done"):
        for it in bugs.items(stage):
            if stage == "done" and it["when"] < cutoff:
                continue
            folder = bugs.stage_dir(it["kind"], bugs.DONE[it["kind"]] if stage == "done" else stage) / it["id"]
            col = _column(it, stage, trying)
            t = it["triage"] or {}
            row = {"id": it["id"], "kind": it["kind"], "column": col, "said": it["said"], "where": it["where"],
                   "fixed": it["fix"], "log": it["log"], "important": it["important"], "reopened": it["reopened"],
                   "area": t.get("area", ""), "size": t.get("size", ""), "needs": t.get("needs", ""),
                   "worker": (it["claimed"] or {}).get("by", ""), "stuck": (it["stuck"] or {}).get("why", "") if it["stuck"] else "",
                   "when": it["when"]}
            if col == "question":
                row.update(question=t.get("question", ""), choices=t.get("choices", []))
            if stage == "check":
                commit, tried = bugs._fix_commits(folder)
                row.update(commit=commit, tried=bool(tried), files=_code_files(commit) if commit else [])
            if stage == "done":
                row["outcome"] = _outcome(folder)
            if shots and it["shot"]:
                row["shot"] = "data:image/jpeg;base64," + base64.b64encode(it["shot"].read_bytes()).decode()
            rows.append(row)
    rows.sort(key=lambda r: (COLUMNS.index(r["column"]), not r["important"],
                             -r["when"] if r["column"] == "done" else r["when"]))
    counts = {c: sum(r["column"] == c for r in rows) for c in COLUMNS}
    return {"items": rows, "counts": counts, "preview": status if status.get("open") else None,
            "columns": list(COLUMNS)}


def open_fix(report_id: str) -> dict:
    return preview.open_copy(report_id)


def close_copy() -> dict:
    return preview.close()


def _close_if_trying(report_id: str) -> None:
    cur = preview.current()
    if cur and cur.get("id") == report_id:
        preview.close()


def works(report_id: str, save_first: bool = False) -> dict:
    """✅: the fix goes into the user's code as one commit. If they have uncommitted edits in a file
    it changes, nothing happens unless save_first: then those edits are committed on their own first
    ("Work in progress"), and the fix goes on top. {"restart": True} when Python code changed (the
    Hub needs a restart to use it); page-only fixes just need the page reloaded."""
    found = bugs.find(report_id)
    if found is None:
        return {"error": f"No report {report_id}."}
    kind, stage, folder = found
    if stage != "check":
        return {"error": f"{report_id} isn't waiting to be tried."}
    commit, _tried = bugs._fix_commits(folder)
    files = _code_files(commit) if commit else []
    saved = None
    if save_first and commit:
        theirs = sorted(set(files) & set(fixgit.dirty_files()))
        if theirs:
            fixed, _log = bugs._fix_parts(folder)
            fixgit.git("add", "--", *theirs)
            fixgit.git("commit", "-q", "-m", f"Work in progress (saved before adding: {fixed[:60]})", "--", *theirs)
            saved = {"files": theirs, "commit": fixgit.git("rev-parse", "--short", "HEAD").stdout.strip()}
    _close_if_trying(report_id)
    out = bugs.verify(report_id, True)
    if "wait" in out:
        return {**out, "can_save_first": True}
    if "error" in out:
        return out
    return {**out, **({"saved": saved} if saved else {}),
            "restart": any(f.endswith((".py", ".json")) for f in files),
            "reload": any(f.startswith(("midi_coach/static/", "docs/")) for f in files)}


def still_wrong(report_id: str, note: str = "") -> dict:
    """↩️: the fix is dropped (it never reached the user's code) and the item goes back to be fixed
    again, with what they said."""
    _close_if_trying(report_id)
    return bugs.verify(report_id, False, note)


def answer(report_id: str, choice: str) -> dict:
    return bugs.answer(report_id, choice, how="in Agent Quest")


def _main() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m midi_coach.fixes", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("board")
    b.add_argument("--shots", action="store_true")
    sub.add_parser("open").add_argument("id")
    sub.add_parser("close")
    w = sub.add_parser("works")
    w.add_argument("id")
    w.add_argument("--save-first", action="store_true")
    s = sub.add_parser("still-wrong")
    s.add_argument("id")
    s.add_argument("--note", default="")
    a = sub.add_parser("answer")
    a.add_argument("id")
    a.add_argument("choice")
    args = ap.parse_args()
    out = {"board": lambda: board(args.shots), "open": lambda: open_fix(args.id), "close": close_copy,
           "works": lambda: works(args.id, args.save_first), "still-wrong": lambda: still_wrong(args.id, args.note),
           "answer": lambda: answer(args.id, args.choice)}[args.cmd]()
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 1 if isinstance(out, dict) and "error" in out else 0


if __name__ == "__main__":
    sys.exit(_main())
