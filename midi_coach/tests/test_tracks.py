"""Tracks: each of a file's instruments with its part (what the user plays it as) and its own
mix (show, mute, volume; Listen's mute and volume apart), saved per file."""
import pytest

from midi_coach import library, server, tracks
from midi_coach.tests.test_midi_coach import _write_organ, fake_rtmidi, ref  # noqa: F401  (fixtures)
from midi_coach.tests.test_named_parts import _write_band


@pytest.fixture()
def organ(ref, tmp_path):
    _write_organ(tmp_path / "songs" / "Organ Hymn.mid")
    return library.get_score("organ hymn")


@pytest.fixture()
def band(ref, tmp_path):
    _write_band(tmp_path / "songs" / "Band Song.mid")
    return library.get_score("band song")


def _ix(score):
    return {p.name: p.index for p in score.parts}


def test_defaults_your_tracks_shown_backing_hidden_everything_sounds(organ):
    ix = _ix(organ)
    mix = tracks.mix(organ)
    assert set(mix) == set(ix.values())
    assert all(not m["mute"] and m["vol"] == 100 and not m["listen_mute"] and m["listen_vol"] == 100 for m in mix.values())
    assert {name for name, i in ix.items() if mix[i]["show"]} == {"Upper", "Lower", "Pedal", "Choir Vocals"}  # all have a part


def test_band_tracks_are_backing_hidden_until_shown(band):
    ix = _ix(band)
    assert band.roles == {} and tracks.part_of(band, ix["Bass Gtr"]) == "left"  # suggested
    tracks.set_part(band, ix["Flute"], "flute")
    tracks.set_part(band, ix["Bass Gtr"], "backing")
    mix = tracks.mix(band)
    assert mix[ix["Flute"]]["show"] and not mix[ix["Bass Gtr"]]["show"] and not mix[ix["Drums"]]["show"]
    assert not any(m["mute"] for m in mix.values())  # a band file's backing always sounded


def test_an_old_files_off_tracks_stay_off(organ):
    ix = _ix(organ)
    library.save_hands(organ, {ix["Upper"]: "right", ix["Lower"]: "left"})  # Pedal and Choir were "off"
    mix = tracks.mix(organ)
    for name in ("Pedal", "Choir Vocals"):
        assert mix[ix[name]]["mute"] and mix[ix[name]]["listen_mute"] and not mix[ix[name]]["show"]
    assert not mix[ix["Upper"]]["mute"] and mix[ix["Upper"]]["show"]
    tracks.set_mix(organ, ix["Upper"], vol=80)  # the first save fixes the old state
    library._score_cache.clear()
    again = library.get_score("organ hymn")
    library.save_hands(again, {ix["Upper"]: "right"})  # and a later part change doesn't redo it
    assert not tracks.mix(again)[ix["Lower"]]["mute"]


def test_old_band_faders_become_track_volumes(band):
    ix = _ix(band)
    tracks.set_part(band, ix["Flute"], "flute")
    library.save_song_settings(band.path, gains={"Drums": 0.3, "Track 3": 0.0}, tracks={})
    mix = tracks.mix(band)
    assert (mix[ix["Drums"]]["vol"], mix[ix["Drums"]]["mute"]) == (30, False)
    assert mix[ix["Track 3"]]["mute"]
    tracks.set_mix(band, ix["Bass Gtr"], vol=50)
    assert library.song_settings(band.path)["gains"] == {}  # moved into the tracks for good
    assert tracks.mix(band)[ix["Drums"]]["vol"] == 30


def test_mix_values_are_kept_in_range_and_per_track_name(band):
    ix = _ix(band)
    assert tracks.set_mix(band, ix["Drums"], vol=140, listen_vol=-3, mute=1) == \
        {"show": False, "mute": True, "vol": 100, "listen_mute": False, "listen_vol": 0}
    saved = library.song_settings(band.path)["tracks"]
    saved[str(ix["Drums"])]["name"] = "Something else"  # the file's tracks changed since
    library.save_song_settings(band.path, tracks=saved)
    assert not tracks.mix(band)[ix["Drums"]]["mute"]
    with pytest.raises(ValueError):
        tracks.set_mix(band, 99, vol=10)


def test_set_part_shows_your_tracks_and_keeps_one_to_play(band):
    ix = _ix(band)
    assert tracks.set_part(band, ix["Bass Gtr"], "left")[ix["Bass Gtr"]] == "left"
    assert tracks.mix(band)[ix["Bass Gtr"]]["show"]
    tracks.set_part(band, ix["Flute"], "right")
    tracks.set_part(band, ix["Bass Gtr"], "backing")
    assert band.roles == {ix["Flute"]: "right"} and not tracks.mix(band)[ix["Bass Gtr"]]["show"]
    with pytest.raises(ValueError, match="yours to play"):
        tracks.set_part(band, ix["Flute"], "backing")
    with pytest.raises(ValueError, match="yours to play"):
        tracks.set_part(band, ix["Flute"], "vocals")
    assert tracks.valid_part("off") == "backing" and tracks.valid_part("Sax") == "sax"


def test_confirm_keeps_the_suggestion_and_its_mix(organ):
    assert not organ.roles
    roles = tracks.confirm(organ)
    assert organ.roles == roles and set(roles.values()) >= {"right", "left"}
    assert not any(m["mute"] for m in tracks.mix(organ).values())  # nothing turned off by confirming


def test_describe_lists_your_tracks_first(band):
    ix = _ix(band)
    tracks.set_part(band, ix["Flute"], "backing")
    tracks.set_part(band, ix["Track 3"], "right")  # the suggestion had Flute right, Bass left
    rows = tracks.describe(band, "left")
    assert [(r["name"], r["part"], r["yours"]) for r in rows] == [
        ("Bass Gtr", "left", True), ("Track 3", "right", False), ("Flute", "backing", False), ("Drums", "backing", False)]
    assert rows[1]["instrument"] == "String Ensemble 1" and rows[1]["range"] == "C4-C4"


def test_learn_on_one_hand_plays_the_other_along(organ, fake_rtmidi, monkeypatch):
    from midi_coach import display, midi_io

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_live", {"session": None})
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    ix = _ix(organ)
    tracks.set_mix(organ, ix["Choir Vocals"], mute=True)
    server.hub.start()
    try:
        out = server._begin(organ.path, hand="right", mode="wait", input_port="JUNO-DS 0", source="page", show_score=False)
        assert out["mode"] == "wait", out
        session = server._live["session"]
        assert set(session.lanes) == {str(ix["Lower"]), str(ix["Pedal"]), str(ix["Choir Vocals"])}
        assert session.accompanist.gains == {str(ix["Lower"]): 1.0, str(ix["Pedal"]): 1.0, str(ix["Choir Vocals"]): 0.0}
        assert str(ix["Upper"]) not in session.lanes  # what you play never sounds for you
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


def test_lead_in_needs_a_backing_that_sounds(organ, fake_rtmidi, monkeypatch):
    from midi_coach import display, midi_io

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_live", {"session": None})
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.start()
    try:
        server._begin(organ.path, hand="both", bars="3-4", mode="wait", input_port="JUNO-DS 0", source="page", show_score=False)
        assert server._live["session"].lead_in == organ.bars[0].start  # 2 bars of pedals and choir first
        server._practice["stopping"] = True
        server.recorder.stop()
        server._live["session"].stop()
        for i in tracks.mix(organ):
            tracks.set_mix(organ, i, mute=True)
        server._practice["stopping"] = False
        server._begin(organ.path, hand="both", bars="3-4", mode="wait", input_port="JUNO-DS 0", source="page", show_score=False)
        assert server._live["session"].lead_in is None  # all muted: nothing to bring you in
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


def test_showing_a_backing_track_redraws_the_sheet_with_its_staff(band, monkeypatch):
    from midi_coach import display

    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server, "_busy", lambda: False)
    ix = _ix(band)
    try:
        server._show(band, [])
        assert "track:" not in "".join(server.hub._score_payload["staves"])
        version = server.hub._score_payload["version"]
        server._cmd_track({"index": ix["Track 3"], "show": True})
        payload = server.hub._score_payload
        assert payload["version"] > version and payload["staves"][0] == f"track:{ix['Track 3']}"
        assert any(r[3] == f"track:{ix['Track 3']}" for r in payload["notes"])  # it falls too
        server._cmd_track({"index": ix["Track 3"], "show": False})
        assert server.hub._score_payload["staves"][0] != f"track:{ix['Track 3']}"
    finally:
        server.hub.shutdown()
