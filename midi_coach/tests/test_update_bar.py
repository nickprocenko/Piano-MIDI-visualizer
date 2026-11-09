"""The page's update bar: what changed since the coach started, and Restart through the launcher."""

import json
import os
import threading

import pytest

from midi_coach import display, launch, server


def test_code_times_split_page_files_from_code_and_wait_for_edits_to_settle(monkeypatch, tmp_path):
    pkg = tmp_path / "midi_coach"
    for rel in ("a.py", "data/x.json", "tests/test_a.py", "static/coach.html", "youtube_extension/content.js",
                "youtube_extension/manifest.json"):
        (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
        (pkg / rel).write_text("")
    times = {"a.py": 1000, "data/x.json": 1100, "tests/test_a.py": 9000, "static/coach.html": 2000,
             "youtube_extension/content.js": 9000, "youtube_extension/manifest.json": 9000}
    for rel, t in times.items():
        os.utime(pkg / rel, (t, t))
    monkeypatch.setattr(launch, "PACKAGE", pkg)
    monkeypatch.setattr(display, "STATIC_FILES", {"/": (pkg / "static" / "coach.html", "text/html")})
    assert launch.code_times(settle=15, now=3000) == {"code": 1100, "page": 2000}
    os.utime(pkg / "a.py", (2990, 2990))  # still being edited
    assert launch.code_times(settle=15, now=3000)["code"] == 1100
    assert launch.code_times(settle=15, now=3010)["code"] == 2990


def test_the_launcher_starts_practice_again_after_a_restart(monkeypatch):
    calls, codes = [], [launch.RESTART_EXIT, launch.RESTART_EXIT, 0]
    monkeypatch.setattr(launch.subprocess, "call", lambda cmd, env, cwd: calls.append((cmd[-1], env["MIDI_COACH_RESTARTABLE"])) or codes.pop(0))
    assert launch.supervise(["great", "gig"]) == 0
    assert calls == [("gig", "1"), ("midi_coach.practice", "1"), ("midi_coach.practice", "1")]  # the piece comes from restart.json


def test_code_status_and_restart(monkeypatch, tmp_path):
    hub = display.DisplayHub()
    hub.started, hub.score_path = 500.0, str(tmp_path / "song.mid")
    (tmp_path / "song.mid").write_bytes(b"")
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(server, "_code_cache", {"at": 0.0, "times": {}})
    monkeypatch.setattr(launch, "code_times", lambda: {"code": 600.0, "page": 400.0})
    monkeypatch.delenv("MIDI_COACH_RESTARTABLE", raising=False)
    status = server.PAGE_COMMANDS["code_status"]({})
    assert status == {"started": 500.0, "code": 600.0, "page": 400.0, "busy": False, "restartable": False}
    assert "Claude Desktop" in server.PAGE_COMMANDS["restart"]({})["error"]

    monkeypatch.setenv("MIDI_COACH_RESTARTABLE", "1")
    monkeypatch.setattr(server, "_busy", lambda: True)
    assert server.PAGE_COMMANDS["restart"]({})["error"].startswith("Stop the run")

    monkeypatch.setattr(server, "_busy", lambda: False)
    exited = threading.Event()
    monkeypatch.setattr(server.os, "_exit", lambda code: exited.set() if code == launch.RESTART_EXIT else pytest.fail(code))
    monkeypatch.setattr(server.recorder, "stop", lambda: None)
    assert server.PAGE_COMMANDS["restart"]({}) == {"restarting": True}
    assert exited.wait(5)
    assert json.loads((server.library.home() / server.RESTART_NOTE).read_text())["score"] == hub.score_path
    assert server.restarted_score() == hub.score_path
    assert server.restarted_score() is None  # once only
