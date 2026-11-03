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
