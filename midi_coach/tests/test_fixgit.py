"""Fixes committed on their own, undone on "Still wrong", claimed by one worker, one runner at a time."""

import json
import subprocess

import pytest
from PIL import Image

from midi_coach import bugs, fixgit


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def repo(monkeypatch, tmp_path):
    """A throwaway git repo with two committed files, standing in for the code."""
    root = tmp_path / "repo"
    root.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    run("config", "core.autocrlf", "false")
    (root / "page.html").write_text("<button>Video</button>\n", encoding="utf-8")
    (root / "notes.py").write_text("TEMPO = 100\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "start")
    monkeypatch.setenv("MIDI_COACH_REPO", str(root))
    return root


def log_of(root):
    return subprocess.run(["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True).stdout.split("\n")


def report(text="move the video button", kind="request"):
    log = bugs.BugLog(bugs.ScreenRing(active=lambda: True, grab=lambda: None), grab=lambda: Image.new("RGB", (80, 60)))
    return log.report(text, kind=kind)["saved"]


def test_a_fix_is_committed_alone_and_your_own_edits_are_left_out(home, repo):
    (repo / "notes.py").write_text("TEMPO = 90  # the user's own edit\n", encoding="utf-8")
    item = report()
    assert bugs.claim(item, "session")["by"] == "session"
    (repo / "page.html").write_text("<header><button>Video</button></header>\n", encoding="utf-8")  # the fix
    out = bugs.mark_ready(item, "The Video button is in the top bar.", files=["page.html"], by="session")
    assert out["ready"] == item and out["commit"]
    assert log_of(repo)[0] == "Request: The Video button is in the top bar."
    assert fixgit.dirty_files().keys() == {"notes.py"}  # the user's edit is still there, uncommitted
    fix = (home / "requests" / "check" / item / "fix.md").read_text(encoding="utf-8")
    assert f"Commit: {out['commit']}" in fix and not (home / "requests" / "check" / item / "claim.json").exists()
    assert bugs.items("check")[0]["fix"] == "The Video button is in the top bar."  # the commit line isn't shown


def test_a_file_you_were_editing_is_asked_about_not_committed(home, repo):
    (repo / "page.html").write_text("<button>Video</button><!-- mine -->\n", encoding="utf-8")
    item = report()
    bugs.claim(item, "overnight")
    (repo / "page.html").write_text("<header><button>Video</button></header><!-- mine -->\n", encoding="utf-8")
    out = bugs.mark_ready(item, "Moved it.", files=["page.html"])
    assert out["ask"] == ["page.html"] and "your own uncommitted edits" in out["error"]
    assert (home / "requests" / "open" / item).is_dir() and log_of(repo)[0] == "start"


def test_committing_needs_a_claim_and_a_changed_file(home, repo):
    item = report()
    assert "Claim" in bugs.mark_ready(item, "Moved it.", files=["page.html"])["error"]
    bugs.claim(item, "session")
    assert "None of those files has changed" in bugs.mark_ready(item, "Moved it.", files=["page.html"])["error"]
    assert "claimed by session" in bugs.mark_ready(item, "x", files=["page.html"], by="overnight")["error"]
    assert bugs.mark_ready(item, "Nothing to commit: a settings change.")["ready"] == item  # no files: no commit


def test_still_wrong_undoes_the_commit_and_works_keeps_it(home, repo):
    first, second = report("move the video button"), report("tempo 120", kind="bug")
    bugs.claim(first, "s")
    (repo / "page.html").write_text("<header><button>Video</button></header>\n", encoding="utf-8")
    bugs.mark_ready(first, "Moved it.", files=["page.html"])
    bugs.claim(second, "s")
    (repo / "notes.py").write_text("TEMPO = 120\n", encoding="utf-8")
    kept = bugs.mark_ready(second, "Tempo is 120.", files=["notes.py"])["commit"]

    out = bugs.verify(first, works=False, note="it's in the wrong corner")
    assert out["undone"] is True and (repo / "page.html").read_text(encoding="utf-8") == "<button>Video</button>\n"
    assert log_of(repo)[0].startswith('Revert "Request: Moved it."')
    assert "was undone" in (home / "requests" / "open" / first / "report.md").read_text(encoding="utf-8")
    assert bugs.verify(second, works=True)["works"] and (repo / "notes.py").read_text(encoding="utf-8") == "TEMPO = 120\n"
    assert f"commit {kept}, kept" in (home / "bug_reports" / "fixed" / second / "report.md").read_text(encoding="utf-8")


def test_an_undo_that_doesnt_apply_cleanly_is_flagged_and_changes_nothing(home, repo):
    item = report()
    bugs.claim(item, "s")
    (repo / "page.html").write_text("<header><button>Video</button></header>\n", encoding="utf-8")
    bugs.mark_ready(item, "Moved it.", files=["page.html"])
    (repo / "page.html").write_text("<header><button>Video ▶</button></header>\n", encoding="utf-8")  # a later change, same line
    subprocess.run(["git", "commit", "-qam", "later"], cwd=repo, check=True)
    out = bugs.verify(item, works=False, note="still wrong")
    assert out["undone"] is False and log_of(repo)[0] == "later"
    assert "<button>Video ▶</button>" in (repo / "page.html").read_text(encoding="utf-8")
    assert not fixgit.dirty_files() and not (repo / ".git" / "REVERT_HEAD").exists()
    assert "**Needs an agent:**" in (home / "requests" / "open" / item / "report.md").read_text(encoding="utf-8")


def test_one_worker_per_item_and_next_takes_them_in_order(home, repo, monkeypatch):
    a, b = report("video button"), report("tiles overlap", kind="bug")
    bugs.triage(a, "top bar", "S", ["page.html"])
    bugs.triage(b, "top bar", "S", ["page.html"])
    assert bugs.take_next("overnight")["claimed"] == b  # the bug first
    assert "being worked on by overnight" in bugs.claim(b, "session")["error"]
    assert bugs.take_next("session")["claimed"] == a
    assert "none" in bugs.take_next("third")
    assert bugs.items("open")[1]["claimed"]["by"] == "overnight"
    claim = home / "bug_reports" / "open" / b / "claim.json"  # a claim left behind by a worker that stopped
    claim.write_text(json.dumps({"by": "overnight", "at": 0, "dirty": {}}), encoding="utf-8")
    assert bugs.claim(b, "session")["by"] == "session"
    assert bugs.release(b)["released"] == b and not claim.exists()


def test_two_workers_take_whole_batches_that_share_no_files(home, repo):
    video, tiles = report("video button"), report("tiles overlap", kind="bug")
    tempo = report("metronome too fast", kind="bug")
    names = report("note names on the sheet")
    bugs.triage(video, "top bar", "S", ["page.html"])
    bugs.triage(tiles, "top bar", "M", ["page.html", "notes.py"])
    bugs.triage(tempo, "metronome", "S", ["notes.py"])  # shares notes.py with the top bar batch
    bugs.triage(names, "sheet", "S", ["sheet.html"])
    first = bugs.take_batch("worker-1")  # the smallest batch with a bug goes first
    assert first["batch"] == "metronome" and first["claimed"] == [tempo]
    second = bugs.take_batch("worker-2")
    assert second["batch"] == "sheet" and second["claimed"] == [names]  # top bar skipped: notes.py is busy
    assert "none" in bugs.take_batch("worker-3")
    bugs.release(tempo)  # given back: it's first in line again
    assert bugs.take_batch("worker-3")["claimed"] == [tempo]
    bugs.close(tempo, "done")  # once it's finished, notes.py is free for the top bar batch
    third = bugs.take_batch("worker-1")
    assert third["batch"] == "top bar" and set(third["claimed"]) == {video, tiles}  # the whole batch


def worker_fixes(monkeypatch, repo, item, name="worker-1", text="<button>Video</button> <!-- top -->\n"):
    """A worker builds a fix in its own copy of the code and marks it ready; back to the user's after."""
    tree = fixgit.worktree(name)
    monkeypatch.setenv("MIDI_COACH_REPO", str(tree))
    bugs.claim(item, name)
    (tree / "page.html").write_text(text, encoding="utf-8")
    out = bugs.mark_ready(item, "Video button moved to the top bar.", files=["page.html"], by=name)
    monkeypatch.setenv("MIDI_COACH_REPO", str(repo))
    return tree, out


def test_a_workers_fix_stays_on_its_side_branch_until_you_say_it_works(home, repo, monkeypatch):
    item = report()
    (repo / "notes.py").write_text("TEMPO = 90  # yours\n", encoding="utf-8")  # your own edit, elsewhere
    tree, out = worker_fixes(monkeypatch, repo, item)
    assert "commit" in out
    assert (repo / "page.html").read_text(encoding="utf-8") == "<button>Video</button>\n"  # yours untouched
    assert log_of(repo)[0] == "start"
    done = bugs.verify(item, works=True)
    assert done["merged"] and log_of(repo)[0].startswith("Request: Video button moved")
    assert "top" in (repo / "page.html").read_text(encoding="utf-8")
    assert (repo / "notes.py").read_text(encoding="utf-8") == "TEMPO = 90  # yours\n"  # still yours, uncommitted
    assert "added to your code as" in (home / "requests" / "done" / item / "report.md").read_text(encoding="utf-8")
    assert fixgit.git("show-ref", f"refs/fixes/{item}", check=False).returncode  # no longer held


def test_a_fix_waits_while_you_are_editing_its_file(home, repo, monkeypatch):
    item = report()
    worker_fixes(monkeypatch, repo, item)
    (repo / "page.html").write_text("<button>Video</button><!-- mine -->\n", encoding="utf-8")
    out = bugs.verify(item, works=True)
    assert out["wait"] == ["page.html"] and "unsaved changes" in out["error"]
    assert (home / "requests" / "check" / item).is_dir() and log_of(repo)[0] == "start"
    subprocess.run(["git", "checkout", "--", "page.html"], cwd=repo, check=True)  # you put yours away
    assert bugs.verify(item, works=True)["merged"]


def test_still_wrong_drops_a_side_branch_fix_without_touching_your_code(home, repo, monkeypatch):
    item = report()
    tree, _ = worker_fixes(monkeypatch, repo, item)
    out = bugs.verify(item, works=False, note="it's in the wrong corner")
    assert out["undone"] is True and log_of(repo)[0] == "start"
    text = (home / "requests" / "open" / item / "report.md").read_text(encoding="utf-8")
    assert "never added to your code" in text
    assert fixgit.worktree("worker-1") == tree  # next batch: the worker starts again from your code
    assert (tree / "page.html").read_text(encoding="utf-8") == "<button>Video</button>\n"


def test_try_it_puts_a_side_branch_fix_in_your_code_and_works_keeps_it(home, repo, monkeypatch):
    item = report()
    worker_fixes(monkeypatch, repo, item)
    row = bugs.to_check(with_shots=True)["items"][0]
    assert row["try"] is True and row["tried"] is False
    out = bugs.try_fix(item)
    assert out["tried"] == item and "top" in (repo / "page.html").read_text(encoding="utf-8")
    assert log_of(repo)[0].startswith("Request: Video button moved")
    row = bugs.to_check(with_shots=True)["items"][0]
    assert row["try"] is False and row["tried"] is True
    assert "Tried" not in row["fix"]  # the note on what changed stays clean
    assert bugs.try_fix(item)["already"]  # a second press changes nothing
    assert len([s for s in log_of(repo) if s]) == 2
    done = bugs.verify(item, works=True)
    assert done["merged"] == out["commit"] and len([s for s in log_of(repo) if s]) == 2  # not added twice
    assert "when you tried it" in (home / "requests" / "done" / item / "report.md").read_text(encoding="utf-8")
    assert fixgit.git("show-ref", f"refs/fixes/{item}", check=False).returncode


def test_still_wrong_after_try_it_takes_the_fix_out_again(home, repo, monkeypatch):
    item = report()
    worker_fixes(monkeypatch, repo, item)
    tried = bugs.try_fix(item)["commit"]
    out = bugs.verify(item, works=False, note="still in the wrong corner")
    assert out["undone"] is True and (repo / "page.html").read_text(encoding="utf-8") == "<button>Video</button>\n"
    assert log_of(repo)[0].startswith('Revert "Request: Video button moved')
    assert f"commit {tried} was undone" in (home / "requests" / "open" / item / "report.md").read_text(encoding="utf-8")


def test_try_it_waits_while_you_are_editing_its_file(home, repo, monkeypatch):
    item = report()
    worker_fixes(monkeypatch, repo, item)
    (repo / "page.html").write_text("<button>Video</button><!-- mine -->\n", encoding="utf-8")
    out = bugs.try_fix(item)
    assert out["wait"] == ["page.html"] and log_of(repo)[0] == "start"
    assert bugs.to_check(with_shots=True)["items"][0]["try"] is True


def test_a_fix_made_in_your_own_code_has_nothing_to_try(home, repo):
    item = report()
    bugs.claim(item, "session")
    (repo / "page.html").write_text("<header><button>Video</button></header>\n", encoding="utf-8")
    bugs.mark_ready(item, "Moved it.", files=["page.html"], by="session")
    assert bugs.to_check(with_shots=True)["items"][0]["try"] is False
    assert bugs.try_fix(item)["already"] and log_of(repo)[0] == "Request: Moved it."


def test_one_runner_at_a_time(home):
    home.mkdir(parents=True, exist_ok=True)
    assert fixgit.acquire("overnight") == {"locked": "overnight"}
    assert "overnight is already running" in fixgit.acquire("idle")["error"]
    fixgit.release("idle")  # not its lock: nothing happens
    assert fixgit.lock_path().exists()
    fixgit.release("overnight")
    assert fixgit.acquire("idle") == {"locked": "idle"}
    fixgit.lock_path().write_text(json.dumps({"by": "gone", "pid": 999999, "at": 0}), encoding="utf-8")  # its process ended
    assert fixgit.acquire("overnight") == {"locked": "overnight"}
