"""Play along with a recording: taps -> anchors -> the video/score map (synced.py)."""

from __future__ import annotations

import pytest

from midi_coach import synced
from midi_coach.notes import Bar, Score

BAR_SEC = 2.0  # the MIDI file: 4/4 at 120 BPM


def _score(bars=16, path="song.mid"):
    return Score(path=path, notes=[], parts=[], pedal=[], tempos=[(0.0, 120.0)], duration=bars * BAR_SEC,
                 bars=[Bar(i + 1, i * BAR_SEC, (i + 1) * BAR_SEC, 4, 4, i * 4.0, (i + 1) * 4.0) for i in range(bars)])


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path))
    return tmp_path


def test_video_id_from_links():
    assert synced.video_id("https://www.youtube.com/watch?v=RBumgq5yVrA&t=10s") == "RBumgq5yVrA"
    assert synced.video_id("https://youtu.be/RBumgq5yVrA") == "RBumgq5yVrA"
    assert synced.video_id("https://www.youtube.com/shorts/RBumgq5yVrA") == "RBumgq5yVrA"
    assert synced.video_id("RBumgq5yVrA") == "RBumgq5yVrA"
    assert synced.video_id("not a link") is None


def test_no_taps_assumes_the_video_starts_with_bar_one():
    knots = synced.timeline(_score(4), [])
    assert knots[0] == [0.0, 0.0] and knots[-1] == [8.0, 16.0]


def test_steady_recording_fits_one_line_through_wobbly_taps():
    score = _score()
    # The recording: a 5 s intro, then slower than the file (2.5 s a bar); taps off by up to 40 ms.
    wobble = [0.03, -0.04, 0.02, -0.01, 0.04, -0.03]
    taps = [5.0 + k * 2.5 + w for k, w in enumerate(wobble)]
    anchors = synced.taps_to_anchors(score, taps, 1)
    assert [s for _, s in anchors] == [k * BAR_SEC for k in range(6)]
    # Bar 12, far past the taps, lands where the recording plays it.
    assert synced.video_at(anchors, 11 * BAR_SEC) == pytest.approx(5.0 + 11 * 2.5, abs=0.1)
    assert synced.tempo(score, anchors) == pytest.approx(96, abs=2)


def test_drifting_recording_follows_each_anchor():
    score = _score()
    # Speeds up: bars of 2.6 s, then 2.2 s from bar 5.
    starts = [0.0]
    for k in range(1, 9):
        starts.append(starts[-1] + (2.6 if k <= 4 else 2.2))
    anchors = synced.taps_to_anchors(score, starts, 1)
    assert len(anchors) == 9
    for k, v in enumerate(starts):
        assert synced.video_at(anchors, k * BAR_SEC) == pytest.approx(v, abs=1e-6)
    # Past the last tap it carries on at the latest tempo.
    assert synced.video_at(anchors, 10 * BAR_SEC) == pytest.approx(starts[-1] + 2 * 2.2, abs=0.05)


def test_a_missed_downbeat_skips_a_bar_and_a_double_tap_is_dropped():
    score = _score()
    taps = [1.0, 3.0, 5.0, 9.0, 9.15, 11.0]  # bar 4 not tapped; a slip right after bar 5's tap
    anchors = synced.taps_to_anchors(score, taps, 1)
    assert anchors == [[1.0, 0.0], [3.0, 2.0], [5.0, 4.0], [9.0, 8.0], [11.0, 10.0]]


def test_taps_from_a_later_bar_replace_only_those_bars():
    score = _score()
    entry = {"video": {"id": "x"}, "anchors": synced.taps_to_anchors(score, [k * 2.0 for k in range(16)], 1)}
    entry = synced.add_taps(score, entry, [20.5, 22.5, 24.5], 11)
    by_bar = {round(s / BAR_SEC) + 1: v for v, s in entry["anchors"]}
    assert by_bar[10] == 18.0 and by_bar[11] == 20.5 and by_bar[13] == 24.5 and by_bar[14] == 26.0


def test_nudge_moves_the_nearest_bar_line():
    score = _score()
    entry = {"video": {"id": "x"}, "anchors": [[0.0, 0.0], [2.0, 2.0]]}
    entry, bar = synced.nudge(score, entry, 12.3)  # bar 7 starts at 12 s by the map
    assert bar.number == 7
    assert [12.3, 12.0] in entry["anchors"]
    # Still a steady line (the taps sit within STEADY_TOL_SEC of it), which now passes the nudge.
    assert synced.score_at(entry["anchors"], 12.3, score) == pytest.approx(12.0, abs=0.02)
    # A bigger correction breaks the line: the map then goes through the nudged bar exactly.
    entry, bar = synced.nudge(score, entry, 21.0)
    assert bar.number == 11 and synced.video_at(entry["anchors"], 20.0) == pytest.approx(21.0, abs=1e-6)


def test_saved_per_song_and_a_new_video_forgets_the_taps(home):
    score = _score(path=str(home / "song.mid"))
    entry = synced.set_video(score.path, "AAAAAAAAAAA", "Live")
    entry = synced.save(score.path, synced.add_taps(score, entry, [1.0, 3.0, 5.0], 1))
    assert synced.load(score.path)["anchors"] == [[1.0, 0.0], [3.0, 2.0], [5.0, 4.0]]
    view = synced.view(score, synced.load(score.path))
    assert view["video"]["id"] == "AAAAAAAAAAA" and view["tapped"] == [1, 2, 3] and view["bpm"] == pytest.approx(120)
    assert synced.set_video(score.path, "AAAAAAAAAAA")["anchors"]  # same video: taps kept
    assert synced.set_video(score.path, "BBBBBBBBBBB")["anchors"] == []


def test_page_commands_pick_a_video_tap_and_move_the_cursor(tmp_path, monkeypatch):
    import mido

    from midi_coach import display, library, server

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "missing.json"))
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    for _ in range(8):
        track.append(mido.Message("note_on", note=60, velocity=70, time=0))
        track.append(mido.Message("note_off", note=60, velocity=0, time=4 * 480))
    mid.tracks.append(track)
    path = tmp_path / "Song.mid"
    mid.save(str(path))
    library._score_cache.clear()
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})

    assert server._cmd_synced({})["error"]  # nothing loaded yet
    server._cmd_load({"lesson": str(path)})
    try:
        assert server._cmd_synced({"link": "nope"})["error"]
        out = server._cmd_synced({"link": "https://youtu.be/AAAAAAAAAAA", "title": "Song (live)"})
        assert out["video"] == {"id": "AAAAAAAAAAA", "title": "Song (live)"} and out["taps"] == 0
        out = server._cmd_synced({"taps": [3.0, 5.5, 8.0, 10.5], "bar": 1})
        assert out["tapped"] == [1, 2, 3, 4] and out["bpm"] == pytest.approx(96)
        assert out["knots"][0] == [3.0, 0.0] and out["knots"][4] == [13.0, 16.0]
        assert server._cmd_synced({"nudge": 13.4})["nudged"] == 5

        assert server._cmd_synced_cursor({"beat": 6.5, "bps": 1.6}) == {}
        assert server.hub._cursor == {"type": "cursorBeat", "beat": 6.5, "bps": 1.6, "live": True}
        assert server._cmd_synced({"clear": True})["taps"] == 0

        # The loop is kept in range, saved with the sync, and kept when the video changes.
        assert server._cmd_synced({"loop": {"from": 6, "to": 3, "on": True}})["loop"] == {"from": 6, "to": 6, "on": True}
        assert server._cmd_synced({"loop": {"from": 2, "to": 99, "on": True}})["loop"] == {"from": 2, "to": 8, "on": True}
        assert server._cmd_synced({})["loop"] == {"from": 2, "to": 8, "on": True}
        assert server._cmd_synced({"link": "BBBBBBBBBBB"})["loop"]["on"] is True
    finally:
        server.hub.shutdown()


def test_youtube_tab_lists_synced_songs_and_knows_the_extension(tmp_path, monkeypatch):
    import json
    import urllib.request

    import mido

    from midi_coach import display, library, server

    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "missing.json"))
    paths = []
    for name in ("First Song", "Second Song"):
        mid = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        for _ in range(4):
            track.append(mido.Message("note_on", note=60, velocity=70, time=0))
            track.append(mido.Message("note_off", note=60, velocity=0, time=4 * 480))
        mid.tracks.append(track)
        paths.append(tmp_path / f"{name}.mid")
        mid.save(str(paths[-1]))
    library._score_cache.clear()
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_practice", {**server._practice, "settings": None, "last": None, "running": False})

    out = server._cmd_youtube({})
    assert out["song"] is None and out["videos"] == [] and out["extension"]["state"] == "unknown"
    assert out["folder"].endswith("youtube_extension") and out["extension"]["latest"] == synced.extension_version()

    synced.set_video(str(paths[0]), "AAAAAAAAAAA", "First (live)")
    server._cmd_load({"lesson": str(paths[1])})
    server.hub.extension_hook = synced.note_extension
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start()
    try:
        server._cmd_synced({"link": "BBBBBBBBBBB"})
        out = server._cmd_youtube({})
        assert out["song"]["title"] == "Second Song" and out["song"]["video"]["id"] == "BBBBBBBBBBB"
        # In the file's own spelling (the keys are lower-cased on Windows), the open one marked.
        assert {v["title"]: v["current"] for v in out["videos"]} == {"First Song": False, "Second Song": True}

        # The page's own commands aren't the extension; its worker's are (by origin, or its version header).
        urllib.request.urlopen(urllib.request.Request(url + "cmd/youtube", data=b"{}", method="POST"))
        assert server._cmd_youtube({})["extension"]["state"] == "unknown"
        req = urllib.request.Request(url + "cmd/synced", data=b"{}", method="POST",
                                     headers={"Origin": "chrome-extension://abcdefghijklmnop", "Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["title"] == "Second Song"
        ext = server._cmd_youtube({})["extension"]
        assert ext["state"] == "live" and ext["version"] is None and ext["outdated"]  # 1.0 sent no version
        req = urllib.request.Request(url + "cmd/synced", data=b"{}", method="POST",
                                     headers={"X-Piano-Coach-Extension": synced.extension_version()})
        urllib.request.urlopen(req)
        ext = server._cmd_youtube({})["extension"]
        assert ext["state"] == "live" and not ext["outdated"]

        # After a restart the visit is remembered: installed, just not open now.
        server.hub.extension = None
        ext = server._cmd_youtube({})["extension"]
        assert ext["state"] == "installed" and ext["version"] == synced.extension_version()
    finally:
        server.hub.shutdown()
