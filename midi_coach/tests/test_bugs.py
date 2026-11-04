"""Bug reports by voice: what's said, screenshots before and at the report, the context."""

import pytest
from PIL import Image

from midi_coach import bugs


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    return tmp_path


def shots(*colours):
    """A fake screen grabber returning each colour in turn (then the last one again)."""
    queue = [Image.new("RGB", (800, 600), c) for c in colours]
    return lambda: queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.mark.parametrize("heard, expected", [
    ("Bug: the cursor jumped to bar 5.", ("report", "the cursor jumped to bar 5")),
    ("Maestro, bug report. Play doesn't start", ("report", "play doesn't start")),
    ("That's a bug, the metronome is late", ("report", "the metronome is late")),
    ("Report a bug", ("report", "")),
    ("Another screenshot.", ("more", "")),
    ("one more screenshot, it's the left panel", ("more", "it's the left panel")),
    ("Idea: a bigger metronome button", ("request", "a bigger metronome button")),
    ("Maestro, feature request. Show the finger numbers", ("request", "show the finger numbers")),
    ("Wish list, dark mode for the sheet", ("request", "dark mode for the sheet")),
    ("Buggy passage, play bars one to four", None),
    ("Ideally I'd play it slower", None),
    ("Start Learn mode", None),
])
def test_bug_commands_are_recognised_from_speech(heard, expected):
    assert bugs.heard_command(heard) == expected


def test_screen_ring_keeps_only_changed_frames():
    ring = bugs.ScreenRing(active=lambda: True, grab=shots("white", "white", "black"))
    for _ in range(3):
        ring.capture()
    assert len(ring.frames) == 2


def test_report_saves_words_screenshots_context_and_log(home):
    ring = bugs.ScreenRing(active=lambda: True, grab=shots("white", "black"))
    ring.capture()
    ring.capture()
    logs = bugs.LogRing()
    logs.emit(bugs.logging.LogRecord("midi-coach", bugs.logging.WARNING, "", 0, "cursor lost its place", None, None))
    log = bugs.BugLog(ring, grab=shots("red"), logs=logs)
    out = log.report("the cursor jumped to bar 5", "Lesson on screen: Scale, 8 bars.")
    folder = home / "bug_reports" / "open" / out["saved"]
    assert out["screenshots"] == 3
    assert sorted(p.name for p in folder.glob("*.jpg"))[-1] == "now.jpg"
    text = (folder / "report.md").read_text(encoding="utf-8")
    assert "the cursor jumped to bar 5" in text and "Lesson on screen: Scale" in text and "cursor lost its place" in text

    added = log.add("it's the left panel")
    assert added == {"added_to": out["saved"], "screenshots": 1} and (folder / "now-2.jpg").exists()
    assert "it's the left panel" in (folder / "report.md").read_text(encoding="utf-8")
    assert log.open_count() == 1


def test_report_without_screen_capture_still_saves(home):
    log = bugs.BugLog(bugs.ScreenRing(active=lambda: True, grab=lambda: None), grab=lambda: None)
    out = log.report("sound cuts out")
    assert out["screenshots"] == 0
    assert "screen capture unavailable" in (home / "bug_reports" / "open" / out["saved"] / "report.md").read_text(encoding="utf-8")


def test_report_carries_the_coach_pages_console_errors(home):
    page = bugs.PageErrors()
    stack = "TypeError: Cannot set properties of null\n    at renderChip (profiles.js:19:33)\n    at load (profiles.js:79:5)"
    page.add("Uncaught TypeError: Cannot set properties of null (setting 'textContent')", "profiles.js:19:33", stack)
    page.add("Uncaught TypeError: Cannot set properties of null (setting 'textContent')", "profiles.js:19:33", stack)
    assert len(page.lines) == 1  # the same error twice in a row is kept once
    log = bugs.BugLog(bugs.ScreenRing(active=lambda: True, grab=lambda: None), grab=lambda: None, page=page)
    out = log.report("check the console")
    text = (home / "bug_reports" / "open" / out["saved"] / "report.md").read_text(encoding="utf-8")
    assert "## Coach page console errors" in text and "[profiles.js:19:33]" in text and "at renderChip" in text


def test_the_page_posts_its_errors_to_the_coach(monkeypatch):
    from midi_coach import server

    page = bugs.PageErrors()
    monkeypatch.setattr(server, "_page_errors", page)
    assert server.PAGE_COMMANDS["page_error"]({"message": "boom", "where": "atlas.js:5:1"}) == {"ok": True}
    assert page.lines[-1].endswith("boom  [atlas.js:5:1]")


def test_saying_bug_to_the_maestro_saves_a_report_without_the_api(home, monkeypatch):
    from midi_coach import display, server

    hub = display.DisplayHub()
    said = []
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(hub, "say", lambda text, interrupt=False, speaker="Claude": said.append(text) or 0)
    monkeypatch.setattr(server, "_bugs", bugs.BugLog(bugs.ScreenRing(active=lambda: True, grab=shots("white")), grab=shots("red")))
    monkeypatch.setattr(server._voice, "ask", lambda heard: pytest.fail("bug reports don't need the API"))
    out = server._voice_reply("Bug: the play button does nothing")
    assert out["actions"] == ["report_bug"] and said[-1] == out["reply"] == "Bug noted, with 1 screenshot."
    report = next((home / "bug_reports" / "open").glob("*/report.md")).read_text(encoding="utf-8")
    assert "the play button does nothing" in report and "Practice context" in report
    assert server._voice_reply("another screenshot")["reply"] == "Added, with 1 screenshot."


def test_saying_idea_saves_a_request_and_more_screenshots_go_to_it(home, monkeypatch):
    from midi_coach import display, server

    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(hub, "say", lambda text, interrupt=False, speaker="Claude": 0)
    monkeypatch.setattr(server, "_bugs", bugs.BugLog(bugs.ScreenRing(active=lambda: True, grab=lambda: None), grab=shots("red")))
    monkeypatch.setattr(server._voice, "ask", lambda heard: pytest.fail("requests don't need the API"))
    out = server._voice_reply("Idea: a bigger metronome button")
    assert out["actions"] == ["request_feature"] and out["reply"] == "Request noted, with 1 screenshot."
    folder = next((home / "requests" / "open").glob("*"))
    assert "# Request" in (folder / "report.md").read_text(encoding="utf-8")
    server._voice_reply("another screenshot, the top right")
    assert (folder / "now-2.jpg").exists() and not (home / "bug_reports").exists()
    assert server._bugs.open_count("request") == 1 and server._bugs.open_count() == 0


def test_everything_said_to_the_maestro_is_logged(home, monkeypatch):
    from midi_coach import display, server

    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(hub, "say", lambda text, interrupt=False, speaker="Claude": 0)
    monkeypatch.setattr(server._voice, "ask", lambda heard: {"reply": "Sure, bars one to four.", "actions": ["play_passage"]})
    server._voice_reply("Play bars one to four")
    monkeypatch.setattr(server._voice, "ask", lambda heard: (_ for _ in ()).throw(RuntimeError("rate limited")))
    server._voice_reply("Can the sheet be bigger?")
    text = next((home / "maestro_log").glob("*.md")).read_text(encoding="utf-8")
    assert "You:** Play bars one to four" in text and "Maestro:** Sure, bars one to four." in text
    assert "did: play_passage" in text
    assert "You:** Can the sheet be bigger?" in text and "rate limited" in text


CONTEXT = ("Local time: Tuesday 8:38 PM.\nThe page is on Session (practice); its panel tiles: play, start.\n"
           "Lesson on screen: The moody blues   nights in white satin [1495], 116 bars.\n"
           "Cursor at bar 63 (\"here\" / \"this bar\" when they spoke).\n"
           "Run going now (Learn mode, hand flute, bars 56-63, tempo 100.0%, loop on), pass 1.")


@pytest.fixture
def vault(monkeypatch, tmp_path):
    root = tmp_path / "vault"
    (root / "Projects" / "MidiCoach").mkdir(parents=True)
    monkeypatch.setenv("MIDI_COACH_VAULT", str(root))
    return root


def reporter():
    return bugs.BugLog(bugs.ScreenRing(active=lambda: True, grab=lambda: None), grab=shots("red"))


def test_a_fix_waits_for_the_user_then_goes_to_fixed(home, vault):
    bug = reporter().report("the loop didn't go back at bar 63", CONTEXT)["saved"]
    backlog = vault / "Projects" / "MidiCoach" / "Backlog.md"
    text = backlog.read_text(encoding="utf-8")
    assert "## 🆕 Open" in text and "the loop didn't go back at bar 63" in text
    assert "*Session · The moody blues nights in white satin · bar 63 · Learn mode*" in text
    assert f"![[bug-{bug}.jpg|320]]" in text and (vault / "attachments" / "backlog" / f"bug-{bug}.jpg").exists()
    assert bugs.to_check() == {"count": 0, "items": []}

    assert bugs.mark_ready(bug, "The loop now restarts on the last bar's release.", "flute-loop-build") == {"ready": bug, "kind": "bug"}
    assert (home / "bug_reports" / "check" / bug / "fix.md").exists()
    rows = bugs.to_check(with_shots=True)["items"]
    assert [r["id"] for r in rows] == [bug] and rows[0]["shot"].startswith("data:image/jpeg;base64,")
    assert rows[0]["fix"] == "The loop now restarts on the last bar's release." and rows[0]["log"] == "flute-loop-build"
    text = backlog.read_text(encoding="utf-8")
    assert text.index("## 👀 Ready to check") < text.index(bug) < text.index("## 🆕 Open")
    assert "Fix: The loop now restarts on the last bar's release. ([[flute-loop-build]])" in text
    assert bugs.mark_ready(bug, "again")["error"]

    assert bugs.verify(bug, works=True) == {"checked": bug, "works": True}
    report = (home / "bug_reports" / "fixed" / bug / "report.md").read_text(encoding="utf-8")
    assert ": works" in report and "restarts on the last bar's release" in report
    assert "## ✅ Done" in backlog.read_text(encoding="utf-8").split("## 🆕 Open")[1] and bugs.to_check()["count"] == 0


def test_still_wrong_sends_a_fix_back_to_open_with_what_was_said(home, vault):
    idea = reporter().report("a bigger metronome button", kind="request")["saved"]
    bugs.mark_ready(idea, "The metronome button is twice the size.")
    assert bugs.verify(idea, works=False, note="still tiny on the Session page")["works"] is False
    folder = home / "requests" / "open" / idea
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert ": still wrong" in report and "still tiny on the Session page" in report and "twice the size" in report
    assert not (folder / "fix.md").exists() and bugs.verify(idea, works=True)["error"]
    assert "- ↩️ **Idea:** a bigger metronome button" in (vault / "Projects" / "MidiCoach" / "Backlog.md").read_text(encoding="utf-8")
    bugs.mark_ready(idea, "Bigger on every page now.")
    assert bugs.verify(idea, works=True)["works"] and (home / "requests" / "done" / idea).is_dir()


def test_no_vault_means_no_backlog_and_nothing_fails(home):
    reporter().report("sound cuts out")
    assert bugs.write_backlog() is None


def test_the_cli_marks_a_report_ready(home, capsys):
    bug = reporter().report("play does nothing")["saved"]
    assert bugs._main(["ready", bug, "Play starts the run again.", "--log", "play-fix"]) == 0
    assert bugs._main(["ready", "nope", "x"]) == 1
    bugs._main(["list"])
    assert f"check  bug      {bug}  play does nothing" in capsys.readouterr().out


def test_place_comes_from_state_json_or_from_the_practice_context(home):
    log = reporter()
    saved = log.report("cursor stuck", "Lesson on screen: Scale, 8 bars.",
                       state={"score": "C:/songs/scale.mid", "bar": 3, "view": "session", "mode": "learn"})["saved"]
    assert bugs.place(saved) == {"score": "C:/songs/scale.mid", "bar": 3, "view": "session", "mode": "learn"}
    old = log.report("the loop didn't go back", CONTEXT)["saved"]
    (home / "bug_reports" / "open" / old / "state.json").unlink(missing_ok=True)
    assert bugs.place(old) == {"view": "practice", "title": "The moody blues   nights in white satin [1495]", "bar": 63,
                               "mode": "learn", "hand": "flute", "bars": "56-63", "tempo_percent": 100, "loop": True}
    assert "error" in bugs.place("nope")


def test_go_there_opens_the_piece_and_hands_the_page_its_settings(home, monkeypatch, tmp_path):
    from midi_coach import display, server

    song = tmp_path / "The Moody Blues - Nights in White Satin [1495].mid"
    song.write_bytes(b"")
    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(server, "_busy", lambda: False)
    monkeypatch.setattr(server.library, "scan_references", lambda: [song])
    loaded = []
    monkeypatch.setattr(server, "_cmd_load", lambda body: loaded.append(body["lesson"]) or {"title": "x"})
    old = reporter().report("the loop didn't go back", CONTEXT)["saved"]
    out = server.PAGE_COMMANDS["goto_report"]({"id": old})
    assert loaded == [str(song)] and out["loaded"] and out["bar"] == 63
    assert out["page"] == {"view": "practice", "mode": "learn", "bars": "56-63", "tempo_percent": 100, "loop": True}

    monkeypatch.setattr(server, "_busy", lambda: True)
    assert server.PAGE_COMMANDS["goto_report"]({"id": old})["error"] == "Stop the run first."


def test_f9_saves_a_typed_report_with_where_the_page_was(home, monkeypatch, tmp_path):
    from midi_coach import display, server

    hub = display.DisplayHub()
    hub.score_path = str(tmp_path / "scale.mid")
    monkeypatch.setattr(server, "hub", hub)
    monkeypatch.setattr(server, "_bugs", reporter())
    monkeypatch.setattr(server, "_voice_context", lambda: "Lesson on screen: Scale, 8 bars.")
    monkeypatch.setattr(server, "_report_state", lambda: {"score": hub.score_path, "bar": 4, "view": "practice"})
    assert "error" in server.PAGE_COMMANDS["report"]({"text": "  "})
    out = server.PAGE_COMMANDS["report"]({"text": "the bar numbers overlap", "kind": "request"})
    assert out["kind"] == "request" and out["screenshots"] == 1
    folder = home / "requests" / "open" / out["saved"]
    assert "the bar numbers overlap" in (folder / "report.md").read_text(encoding="utf-8")
    assert bugs.place(out["saved"]) == {"score": hub.score_path, "bar": 4, "view": "practice"}
    assert "(typed, F9) Idea: the bar numbers overlap" in next((home / "maestro_log").glob("*.md")).read_text(encoding="utf-8")


def test_report_state_never_breaks_a_report(monkeypatch):
    from midi_coach import display, server

    hub = display.DisplayHub()
    hub.score_path = "C:/gone.mid"
    monkeypatch.setattr(server, "hub", hub)
    assert server._report_state() == {}  # the file can't be read: no state, no error


def test_close_moves_a_report_to_done_without_a_fix(home, vault):
    bug = reporter().report("check console send to Claude code")["saved"]
    assert bugs._main(["close", bug, "Not a bug: a request to the Maestro, and it worked."]) == 0
    report = (home / "bug_reports" / "fixed" / bug / "report.md").read_text(encoding="utf-8")
    assert "no fix needed" in report and "it worked" in report
    assert bugs.close(bug, "again")["error"] and bugs._main(["close", "nope", "x"]) == 1
    assert "✅ **Bug:** check console" in (vault / "Projects" / "MidiCoach" / "Backlog.md").read_text(encoding="utf-8")
