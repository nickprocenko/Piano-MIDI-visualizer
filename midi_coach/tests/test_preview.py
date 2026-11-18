"""Test copies of fixes (preview.py): the user's real data copied in, nothing of theirs changed."""

import json
import subprocess
import sys

import pytest

from midi_coach import bugs, preview
from midi_coach.tests.test_fixgit import home, repo, report  # noqa: F401  (fixtures)


def _real_home(home):  # noqa: F811
    """A small stand-in for ~/MidiCoach: settings pointing at its own files, a lesson, a model folder."""
    (home / "lessons" / "Songs").mkdir(parents=True)
    lesson = home / "lessons" / "Songs" / "tune.musicxml"
    lesson.write_text("<score-partwise/>", encoding="utf-8")
    (home / "part_choices.json").write_text(json.dumps({str(lesson): {"hands": "right"}}), encoding="utf-8")
    (home / "notes").mkdir()
    (home / "notes" / "take.json").write_text(json.dumps({"score": str(lesson).replace("\\", "/")}), encoding="utf-8")
    (home / "models").mkdir()
    (home / "models" / "voice.bin").write_bytes(b"weights")
    (home / "runner").mkdir()
    (home / "runner" / "today.log").write_text("not carried over", encoding="utf-8")
    return lesson


def test_the_copy_has_the_users_data_pointing_at_its_own_files(home, tmp_path):  # noqa: F811
    home.mkdir()
    lesson = _real_home(home)
    (home / "bug_reports" / "open" / "2026-01-01_00-00-00").mkdir(parents=True)
    copy = tmp_path / "copy"
    out = preview.build_home(home, copy)
    assert "models" in out["linked"] and "lessons" in out["copied"]
    choices = json.loads((copy / "part_choices.json").read_text(encoding="utf-8"))
    assert list(choices) == [str(copy / "lessons" / "Songs" / "tune.musicxml")]
    take = json.loads((copy / "notes" / "take.json").read_text(encoding="utf-8"))
    assert take["score"] == str(copy / "lessons" / "Songs" / "tune.musicxml").replace("\\", "/")
    assert (copy / "models" / "voice.bin").read_bytes() == b"weights"  # linked, not copied
    assert not (copy / "runner").exists()
    assert list((copy / "bug_reports" / "open").iterdir()) == []  # the real queue stays out
    # and the real home is untouched
    assert json.loads((home / "part_choices.json").read_text(encoding="utf-8")) == {str(lesson): {"hands": "right"}}


def test_the_copy_runs_on_its_own_ports_and_counts_the_real_spend(home, tmp_path):  # noqa: F811
    env = preview.environment(tmp_path / "copy", "2026-01-01_00-00-00")
    assert env["MIDI_COACH_HOME"] == str(tmp_path / "copy")
    assert env["MIDI_COACH_DISPLAY_PORT"] == "8766" and env["MIDI_COACH_MCP_PORT"] == "8781"
    assert env["MIDI_COACH_VAULT"] == "off" and env["MIDI_COACH_PREVIEW"] == "2026-01-01_00-00-00"
    assert env["MIDI_COACH_AI_SPEND"] == str(home / "ai_spend.json")


def test_it_closes_itself_when_no_page_is_open(monkeypatch):
    closed = []
    monkeypatch.setattr(preview, "close_from_inside", lambda: closed.append(True))
    clock = iter(range(0, 10_000, 10))
    monkeypatch.setattr(preview.time, "time", lambda: next(clock))
    looks = iter([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    preview.watch_idle(lambda: next(looks), idle_sec=40, poll=0, sleep=lambda _s: None)
    assert closed == [True]


@pytest.fixture
def fake_coach(monkeypatch):
    """Stands in for the test copy's coach: a real process that prints its page address and waits."""
    def spawn(args, **kwargs):
        kwargs.pop("env", None)
        return subprocess.Popen([sys.executable, "-c",
                                 "import time; print('Music Hub page: http://127.0.0.1:8766/', flush=True); time.sleep(60)"],
                                **kwargs)
    monkeypatch.setattr(preview, "_spawn", spawn)
    monkeypatch.setattr(preview, "_real_coach", lambda *a, **k: None)


def test_open_runs_the_fix_and_close_brings_back_what_was_reported(home, repo, fake_coach):  # noqa: F811
    home.mkdir(exist_ok=True)
    _real_home(home)
    item = report("move the video button")
    bugs.claim(item, "worker")
    (repo / "page.html").write_text("<header><button>Video</button></header>\n", encoding="utf-8")
    commit = bugs.mark_ready(item, "The Video button is in the top bar.", files=["page.html"], by="worker")["commit"]
    subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=repo, check=True)  # the fix lives on a side branch

    out = preview.open_copy(item)
    assert out["url"] == "http://127.0.0.1:8766/" and out["commit"] == commit
    folder = home / "previews" / item
    assert (folder / "code" / "page.html").read_text(encoding="utf-8").startswith("<header>")  # the fix's code
    assert (repo / "page.html").read_text(encoding="utf-8") == "<button>Video</button>\n"  # yours, unchanged
    info = json.loads((folder / "home" / "preview.json").read_text(encoding="utf-8"))
    assert info["id"] == item and info["fixed"] == "The Video button is in the top bar."
    assert preview.status()["open"]

    found = folder / "home" / "bug_reports" / "open" / "2026-02-02_10-00-00"  # F9 inside the copy
    found.mkdir(parents=True)
    (found / "report.md").write_text("# Bug\n\n## What was said\n\nthe button overlaps\n", encoding="utf-8")

    closed = preview.close()
    assert closed == {"closed": item, "reports": ["2026-02-02_10-00-00"]}
    moved = (home / "bug_reports" / "open" / "2026-02-02_10-00-00" / "report.md").read_text(encoding="utf-8")
    assert "## Found in a test copy" in moved and item in moved
    assert not folder.exists() and preview.current() is None
    assert (home / "models" / "voice.bin").read_bytes() == b"weights"  # behind a link: never deleted
    trees = subprocess.run(["git", "worktree", "list"], cwd=repo, capture_output=True, text=True).stdout
    assert "previews" not in trees


def test_only_fixes_waiting_to_be_tried_open(home, repo):  # noqa: F811
    item = report("a thing")
    assert "isn't waiting" in preview.open_copy(item)["error"]
    assert "No report" in preview.open_copy("nope")["error"]
