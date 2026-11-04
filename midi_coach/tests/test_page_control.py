"""The Maestro's page_control: the open coach page sets its own controls, as if clicked."""

import pytest

from midi_coach import chat, display, server


@pytest.fixture
def page(monkeypatch):
    """A hub with one coach page open; returns that page's message queue."""
    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    q = hub._subscribe()
    while not q.empty():  # what a page gets on connecting (the status line)
        q.get_nowait()
    return q


def test_page_control_reaches_the_open_page_with_clamped_values(page):
    out = server._voice_page(show="notes", note_names=True, zoom_percent=400, metronome=True,
                             metronome_bpm=5, tempo_percent=70, bars=" 9 – 12 ", view="roadmap", labels=None)
    sent = {"show": "notes", "note_names": True, "zoom_percent": 200, "metronome": True,
            "metronome_bpm": 20, "tempo_percent": 70, "bars": "9-12", "view": "roadmap"}
    assert out == {"done": sent}
    assert page.get_nowait() == {"type": "page", **sent}


def test_page_control_one_bar_and_the_whole_lesson(page):
    assert server._voice_page(bars="5")["done"]["bars"] == "5-5"
    assert server._voice_page(bars="", loop=False)["done"] == {"bars": "", "loop": False}


def test_page_control_refuses_what_it_cant_do(page, monkeypatch):
    assert "error" in server._voice_page(bars="the chorus")
    assert "error" in server._voice_page()
    assert page.empty()
    monkeypatch.setattr(server, "hub", display.DisplayHub())  # no page open
    assert server._voice_page(show="sheet") == {"error": "No coach page is open."}


def test_every_maestro_tool_has_an_action():
    names = {tool["name"] for tool in chat.TOOLS}
    assert "page_control" in names
    assert names - {"write_lesson"} <= set(server._voice.actions)


def test_page_control_opens_a_menu(page):
    assert server._voice_page(menu="sound_out") == {"done": {"menu": "sound_out"}}
    assert page.get_nowait() == {"type": "page", "menu": "sound_out"}


def test_page_control_refuses_a_menu_it_doesnt_know(page):
    out = server._voice_page(menu="mixer")
    assert "can't open 'mixer'" in out["error"] and "sound_out" in out["error"]
    assert page.empty()


def test_the_page_can_open_every_menu_the_maestro_knows():
    """chat.PAGE_MENUS (what the Maestro is told) and coach.html's MENUS (what the page opens) match."""
    import pathlib, re
    html = (pathlib.Path(chat.__file__).parent / "static" / "coach.html").read_text(encoding="utf-8")
    block = html[html.index("const MENUS = {"):]
    block = block[:block.index("};")]
    assert set(re.findall(r"(\w+): \{", block)) == set(chat.PAGE_MENUS)
    assert chat.TOOLS[[t["name"] for t in chat.TOOLS].index("page_control")]["input_schema"]["properties"]["menu"]["enum"] == list(chat.PAGE_MENUS)


def test_start_practice_brings_the_session_up(page, monkeypatch):
    monkeypatch.setattr(server.hub, "score_path", "lesson.musicxml", raising=False)
    monkeypatch.setattr(server._atlas, "current", None)
    monkeypatch.setattr(server, "_busy", lambda: False)
    monkeypatch.setattr(server, "_cmd_start", lambda body: {"mode": body["mode"]})
    assert server._voice_start("learn") == {"mode": "learn"}
    assert page.get_nowait() == {"type": "page", "view": "session", "unguarded": True}


def test_start_practice_in_a_roadmap_lesson_stays_there(page, monkeypatch):
    monkeypatch.setattr(server.hub, "score_path", "stage.musicxml", raising=False)
    monkeypatch.setattr(server._atlas, "current", {"node": "g1.x", "step": None})
    monkeypatch.setattr(server, "_busy", lambda: False)
    monkeypatch.setattr(server, "_cmd_start", lambda body: {"mode": body["mode"]})
    server._voice_start("rehearse")
    assert page.empty()


def test_start_practice_with_nothing_open_asks_which(page, monkeypatch):
    monkeypatch.setattr(server.hub, "score_path", None, raising=False)
    assert "Ask which one" in server._voice_start("learn")["error"]


def test_see_in_song_needs_a_lesson_on_a_song_goal(page, monkeypatch):
    monkeypatch.setattr(server._atlas, "current", None)
    assert "Roadmap lesson" in server._voice_page(menu="see_in_song")["error"]
    monkeypatch.setattr(server._atlas, "current", {"node": "g.song.s1-rh", "step": None})
    monkeypatch.setattr(server._atlas, "song_for", lambda node: {"song": "x.mid", "bars": "1-4"})
    assert server._voice_page(menu="see_in_song") == {"done": {"menu": "see_in_song"}}
