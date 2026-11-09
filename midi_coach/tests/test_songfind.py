"""The Maestro's open_song (songfind.py): library, then Downloads, then bitmidi.com, else a link."""

import mido
import pytest

from midi_coach import chat, display, library, online, server, songfind, transcript


def _mid(path):
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    track.append(mido.Message("note_on", note=60, velocity=64, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    mid.tracks.append(track)
    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(path))
    return path


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    monkeypatch.setenv("MIDI_COACH_DOWNLOADS", str(folder))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "config.json"))
    (tmp_path / "config.json").write_text('{"online_search": false}', encoding="utf-8")
    return folder


def test_score_wants_every_word_asked():
    name = "home-for-a-rest-spirit-of-the-west-for-concert-band"
    assert songfind.score("home for a rest", name) == 1.0
    assert songfind.score("Home for a Rest by Spirit of the West", name) == 1.0
    assert songfind.score("thriller", name) < songfind.SURE_RATIO
    assert songfind.score("play halloween", "Halloween") == 1.0


def test_a_download_is_found_and_kept_in_the_library(downloads):
    _mid(downloads / "home-for-a-rest-spirit-of-the-west-for-concert-band.mid")
    _mid(downloads / "Halloween.mid")
    found = songfind.find("home for a rest")
    assert found["where"] == "downloads"
    assert found["path"].startswith(str(library.home() / "references" / "downloads"))
    assert songfind.find("Home for a Rest")["where"] == "library"  # the copy is in the library now


def test_the_library_comes_first(downloads):
    _mid(library.home() / "references" / "Desperado.mid")
    _mid(downloads / "Desperado.mid")
    assert songfind.find("desperado")["where"] == "library"


def test_nothing_anywhere_gives_a_musescore_link(downloads):
    found = songfind.find("Home for a Rest", "Spirit of the West")
    assert found["not_found"] and found["link"] == "https://musescore.com/sheetmusic?text=Home+for+a+Rest+Spirit+of+the+West"


def test_bitmidi_only_when_every_word_matches(downloads, monkeypatch):
    (downloads.parent / "config.json").write_text('{"online_search": true}', encoding="utf-8")
    monkeypatch.setattr(online, "search", lambda q: [{"id": 7, "title": "Home", "all_words": False, "path": None}])
    assert "link" in songfind.find("home for a rest")
    monkeypatch.setattr(online, "search", lambda q: [{"id": 7, "title": "Home for a Rest", "all_words": True, "path": None}])
    monkeypatch.setattr(online, "download", lambda i: "x.mid")
    assert songfind.find("home for a rest") == {"path": "x.mid", "where": "bitmidi", "title": "Home for a Rest"}


def test_open_song_sends_the_link_to_the_panel(downloads, monkeypatch):
    hub = display.DisplayHub()
    monkeypatch.setattr(server, "hub", hub)
    q = hub._subscribe()
    while not q.empty():
        q.get_nowait()
    out = server._voice_open_song("Home for a Rest", "Spirit of the West")
    assert out["not_found"] and out["link_sent_to_panel"]
    line = q.get_nowait()
    assert line["type"] == "line" and line["link"].startswith("https://musescore.com/")
    assert transcript.today()[-1]["link"] == line["link"]  # a reload shows it too


def test_transcript_keeps_only_web_links():
    assert "link" not in transcript.add("Maestro", "hi", "remark", "javascript:alert(1)")
    assert transcript.add("Maestro", "hi", "remark", "https://x.org")["link"] == "https://x.org"


def test_the_maestro_has_the_tools():
    names = {t["name"] for t in chat.TOOLS}
    assert {"open_song", "remove_from_today"} <= names <= set(server._voice.actions) | {"write_lesson"}
    assert "open_song" in chat.PAGE_SYSTEM and "remove_from_today" in chat.PAGE_SYSTEM
