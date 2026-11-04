"""The Maestro panel's transcript: every line said on the page, kept for the day."""

import pytest

from midi_coach import display, server, transcript


@pytest.fixture
def page(monkeypatch):
    """A hub with one coach page open; returns that page's message queue."""
    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    q = hub._subscribe()
    while not q.empty():
        q.get_nowait()
    return q


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_a_line_is_kept_and_read_back():
    assert transcript.add("Maestro", "  Nice and even.  ")["text"] == "Nice and even."
    assert transcript.add("Maestro", "   ") is None
    lines = transcript.today()
    assert [(x["who"], x["kind"], x["text"]) for x in lines] == [("Maestro", "remark", "Nice and even.")]


def test_lines_said_while_answering_are_replies():
    with transcript.answering():
        assert transcript.add("Maestro", "Bars 5 to 8, then.")["kind"] == "reply"
    assert transcript.add("Maestro", "Steady now.")["kind"] == "remark"


def test_a_bad_row_is_skipped(tmp_path):
    transcript.add("You", "hello", "you")
    with transcript._path().open("a", encoding="utf-8") as f:
        f.write("not json\n")
    assert [x["text"] for x in transcript.today()] == ["hello"]


def test_say_reaches_the_panel_and_the_transcript(page):
    server.hub.say("Watch the left hand.", speaker="Maestro")
    msgs = _drain(page)
    assert [m["type"] for m in msgs] == ["line", "say"]
    assert msgs[0]["who"] == "Maestro" and msgs[0]["kind"] == "remark"
    assert server._cmd_transcript({})["lines"][-1]["text"] == "Watch the left hand."


def test_a_question_and_its_answer(page, monkeypatch):
    monkeypatch.setattr(server, "_answer", lambda heard: (server.hub.say("Try bar 3.", speaker="Maestro"),
                                                          {"heard": heard, "reply": "Try bar 3."})[1])
    server._voice_reply("where do I start?")
    lines = [m for m in _drain(page) if m["type"] == "line"]
    assert [(m["who"], m["kind"]) for m in lines] == [("You", "you"), ("Maestro", "reply")]


def test_an_error_is_shown_too(page, monkeypatch):
    monkeypatch.setattr(server, "_answer", lambda heard: {"heard": heard, "error": "No key."})
    server._voice_reply("hi")
    assert [(m["kind"], m["text"]) for m in _drain(page) if m["type"] == "line"] == [("you", "hi"), ("error", "No key.")]


def test_a_fresh_conversation_draws_a_line_above_the_question(page, monkeypatch):
    monkeypatch.setattr(server, "_answer", lambda heard: {"heard": heard, "reply": "Hi."})
    monkeypatch.setattr(server._voice, "messages", [{"role": "user", "content": "earlier"}])
    monkeypatch.setattr(server._voice, "_last_turn", 0.0)  # long ago
    server._voice_reply("back again")
    assert [m["kind"] for m in _drain(page) if m["type"] == "line"] == ["divider", "you"]
    assert server._voice.messages == []
    server._voice_reply("and again")  # nothing left to forget: no second line
    assert [m["kind"] for m in _drain(page) if m["type"] == "line"] == ["you"]
