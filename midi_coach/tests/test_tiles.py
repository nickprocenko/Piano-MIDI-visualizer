"""The Maestro panel's quick-action tiles: defaults, a profile's own layouts, the Maestro's
set_tiles, and the page knowing every tile the server does."""

import pathlib
import re

import pytest

from midi_coach import chat, display, profiles, server, tiles


@pytest.fixture
def page(monkeypatch):
    """A hub with one coach page open; returns that page's message queue."""
    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    q = hub._subscribe()
    while not q.empty():
        q.get_nowait()
    return q


def test_a_view_never_changed_shows_its_defaults():
    assert tiles.layouts() == tiles.DEFAULTS


def test_a_layout_is_saved_in_order_once_each():
    assert tiles.save("progress", ["exam", "today", "exam"]) == {"view": "progress", "tiles": ["exam", "today"]}
    assert tiles.layouts()["progress"] == ["exam", "today"]
    assert tiles.layouts()["home"] == tiles.DEFAULTS["home"]


def test_bad_views_and_tiles_are_refused():
    assert "No view" in tiles.save("mixer", ["play"])["error"]
    assert "No tile 'reverb'" in tiles.save("home", ["reverb"])["error"]


def test_each_profile_keeps_its_own_tiles():
    tiles.save("home", ["play"])
    other = profiles.create("Sam")["id"]
    assert profiles.load()["active"] == other
    assert tiles.layouts()["home"] == tiles.DEFAULTS["home"]


def test_the_maestro_adds_takes_off_and_resets(page):
    assert server._voice_tiles("progress", add=["play"], remove=["exam"])["tiles"] == ["today", "next", "planner", "play"]
    assert page.get_nowait() == {"type": "page", "tiles": {"view": "progress", "tiles": ["today", "next", "planner", "play"]}}
    assert server._voice_tiles("progress", add=["today"])["tiles"][-1] == "today"  # moved to the end
    assert server._voice_tiles("progress", reset=True)["tiles"] == tiles.DEFAULTS["progress"]


def test_the_page_edit_reaches_every_page(page):
    server._cmd_tiles_set({"view": "record", "tiles": ["metronome", "play"]})
    assert page.get_nowait()["tiles"] == {"view": "record", "tiles": ["metronome", "play"]}
    assert server._cmd_tiles({})["layouts"]["record"] == ["metronome", "play"]


def test_the_maestro_is_told_which_view_the_page_is_on():
    server._cmd_view({"view": "lesson"})
    assert "The page is on Roadmap (progress); its panel tiles: today, next, planner, exam." in server._voice_context()


def test_the_page_knows_every_tile():
    html = (pathlib.Path(chat.__file__).parent / "static" / "coach.html").read_text(encoding="utf-8")
    block = html[html.index("const TILES = {"):]
    block = block[:block.index("\n};")]
    assert set(re.findall(r"^  (\w+): \{", block, re.M)) == set(tiles.TILES)
    tool = next(t for t in chat.TOOLS if t["name"] == "set_tiles")
    assert tool["input_schema"]["properties"]["add"]["items"]["enum"] == list(tiles.TILES)
