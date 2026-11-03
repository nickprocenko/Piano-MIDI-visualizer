"""Song folders (File → Song folders) and the Songs panel's bitmidi.com search, network faked."""

from __future__ import annotations

import io
import json

import mido
import pytest

from midi_coach import library, online


def _midi_bytes() -> bytes:
    mid = mido.MidiFile()
    track = mido.MidiTrack([mido.Message("note_on", note=60, velocity=80), mido.Message("note_off", note=60, time=480)])
    mid.tracks.append(track)
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MIDI_COACH_REFERENCE_DIRS", "")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"search_folders": [], "note_style": {"width_px": 18}}), encoding="utf-8")
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(config))
    online._seen.clear()
    return tmp_path


def test_song_folders_saved_keeping_other_settings(home):
    songs = home / "My MIDI"
    songs.mkdir()
    out = library.set_song_sources([str(songs), str(songs), ""], online=False)
    assert [f["path"] for f in out["folders"]] == [str(songs.resolve()).replace("\\", "/")]
    assert out["online"] is False
    saved = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert saved["note_style"] == {"width_px": 18}  # the desktop visualizer's settings survive
    assert songs.resolve() in [f.resolve() for f in library.reference_folders()]
    with pytest.raises(FileNotFoundError):
        library.set_song_sources([str(home / "nowhere")])


def test_search_ranks_songs_naming_every_word_first(home, monkeypatch):
    results = [
        {"id": 1, "name": "Saint Seiya - Ikki's theme.mid", "views": 900, "downloadUrl": "/uploads/1.mid"},
        {"id": 2, "name": "Halloween.mid", "views": 50, "downloadUrl": "/uploads/2.mid"},
        {"id": 3, "name": "Halloween Theme.mid", "views": 10, "downloadUrl": "/uploads/3.mid"},
        {"id": 4, "name": "Tetris.mid", "views": 5000, "downloadUrl": "/uploads/4.mid"},
        {"id": 5, "name": "Zelda - Main Theme.mid", "views": 800, "downloadUrl": "/uploads/5.mid"},
        {"id": 6, "name": "Mario Theme.mid", "views": 700, "downloadUrl": "/uploads/6.mid"},
    ]
    monkeypatch.setattr(online, "_get", lambda url: json.dumps({"result": {"results": results}}).encode())
    hits = online.search("halloween theme")
    # Both words first, then the rarer word ahead of the popular 'theme' songs; Tetris shares none.
    assert [h["id"] for h in hits] == [3, 2, 1, 5, 6]
    assert hits[0] == {"id": 3, "title": "Halloween Theme", "views": 10, "all_words": True, "path": None}


def test_download_saves_once_into_the_library(home, monkeypatch):
    calls = []

    def fake_get(url):
        calls.append(url)
        if "api" in url:
            return json.dumps({"result": {"results": [{"id": 7, "name": "Halloween.mid", "views": 1, "downloadUrl": "/uploads/7.mid"}]}}).encode()
        return _midi_bytes()

    monkeypatch.setattr(online, "_get", fake_get)
    online.search("halloween")
    path = online.download(7)
    assert path.endswith("Halloween [bitmidi 7].mid")
    assert calls[-1] == "https://bitmidi.com/uploads/7.mid"
    assert path in [str(f) for f in library.scan_references()]
    assert online.download(7) == path and len(calls) == 2  # the copy already there
    assert online.search("halloween")[0]["path"] == path


def test_download_refuses_a_file_that_isnt_midi(home, monkeypatch):
    monkeypatch.setattr(online, "_get", lambda url: b"<html>not found</html>")
    with pytest.raises(ValueError):
        online.download(9)
    assert not list((home / "home" / "references").rglob("*.mid"))
