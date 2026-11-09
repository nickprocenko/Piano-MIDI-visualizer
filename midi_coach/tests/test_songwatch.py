"""New songs are noticed without a rescan (songwatch.py): song folders, and Downloads when it's on."""

import os

import mido
import pytest

from midi_coach import library, server, songwatch


def _mid(path):
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    track.append(mido.Message("note_on", note=60, velocity=64, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    mid.tracks.append(track)
    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(path))
    _bump(path.parent)
    return path


def _bump(folder):
    """Windows bumps a folder's modified time when a file lands in it, but not always within the
    clock's resolution of the last look; the tests move it on by hand."""
    st = os.stat(folder)
    os.utime(folder, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))


@pytest.fixture
def places(tmp_path, monkeypatch):
    songs, downloads = tmp_path / "Songs", tmp_path / "Downloads"
    songs.mkdir()
    downloads.mkdir()
    monkeypatch.setenv("MIDI_COACH_DOWNLOADS", str(downloads))
    monkeypatch.setenv("MIDI_COACH_REFERENCE_DIRS", "")
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "config.json"))
    (tmp_path / "config.json").write_text('{"online_search": false}', encoding="utf-8")
    library.set_song_sources([str(songs)])
    return songs, downloads


def _settle(watcher):
    """Two looks: one to see the file, one to see its size hold still."""
    return songwatch.handle(watcher, watcher.poll() + watcher.poll())


def test_whats_there_already_isnt_new(places):
    songs, downloads = places
    _mid(songs / "Old.mid")
    _mid(downloads / "Old download.mid")
    watcher = songwatch.Watcher()
    watcher.prime()
    assert _settle(watcher) == []


def test_a_file_dropped_into_a_song_folder_is_noticed(places):
    songs, _ = places
    watcher = songwatch.Watcher()
    watcher.prime()
    _mid(songs / "Band" / "Inner" / "New one.mid")  # folders inside folders too
    _bump(songs)
    found = _settle(watcher)
    assert [s["title"] for s in found] == ["New one"]
    assert _settle(watcher) == []  # once only


def test_a_download_is_copied_into_the_library(places):
    _, downloads = places
    watcher = songwatch.Watcher()
    watcher.prime()
    _mid(downloads / "home-for-a-rest.mid")
    (downloads / "notes.txt").write_text("not a song")
    found = _settle(watcher)
    assert len(found) == 1
    copy = library.home() / "references" / "downloads" / "home-for-a-rest.mid"
    assert found[0]["path"] == str(copy) and copy.is_file()
    assert _settle(watcher) == []  # the copy isn't news again


def test_downloads_can_be_left_alone(places):
    _, downloads = places
    library.set_song_sources(watch_downloads=False)
    assert library.song_sources()["watch_downloads"] is False
    watcher = songwatch.Watcher()
    watcher.prime()
    _mid(downloads / "Ignored.mid")
    assert _settle(watcher) == []


def test_a_file_still_being_written_waits(places):
    songs, _ = places
    watcher = songwatch.Watcher()
    watcher.prime()
    path = _mid(songs / "Growing.mid")
    assert watcher.poll() == []  # first seen
    with open(path, "ab") as f:
        f.write(b"\0" * 10)
    assert watcher.poll() == []  # still growing
    assert [p.name for p in watcher.poll()] == ["Growing.mid"]


def test_the_lessons_folder_isnt_watched(places):
    watcher = songwatch.Watcher()
    watcher.prime()
    _mid(library.profile_home() / "lessons" / "Unsorted" / "My take.mid")
    _bump(library.profile_home() / "lessons")
    assert _settle(watcher) == []


def test_arrivals_reach_the_page_and_the_next_search(places, monkeypatch):
    sent = []
    monkeypatch.setattr(server.hub, "songs_added", sent.append)
    server._cmd_songs({})
    server._song_files["at"] = 10**9  # pretend the list was just scanned
    server._songs_arrived([{"title": "X", "path": "x", "folder": "f"}])
    assert sent == [[{"title": "X", "path": "x", "folder": "f"}]]
    assert server._song_files["at"] < 0


def test_rescan_and_the_switch_from_the_page(places):
    songs, _ = places
    _mid(songs / "One.mid")
    assert server._cmd_rescan({})["total"] == 1
    assert server.PAGE_COMMANDS["set_song_sources"]({"watch_downloads": False})["watch_downloads"] is False


def test_off_means_no_thread(monkeypatch):
    assert songwatch.start(lambda songs: None) is False  # conftest sets MIDI_COACH_SONG_WATCH=off
