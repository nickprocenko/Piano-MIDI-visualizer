"""Local profiles: separate takes, part choices and Atlas progress; shared song library and Atlas content."""

from __future__ import annotations

import pytest

from midi_coach import atlas, library, profiles
from midi_coach.atlas import store


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MIDI_COACH_ATLAS_CONTENT", raising=False)
    return library.home()


def test_default_profile_keeps_the_existing_folders(root):
    assert profiles.load() == {"active": "default",
                               "profiles": [{"id": "default", "name": "Default", "created": None, "instrument": "piano",
                                             "instruments": ["piano"], "young": False, "voice": "high"}]}
    assert library.profile_home() == root and atlas.user_dir() == root / "atlas"


def test_each_profile_has_its_own_takes_and_atlas_progress(root):
    store.append_event("touch", node="n", step="s")
    kid = profiles.create("Sam")
    assert profiles.active()["name"] == "Sam" and library.profile_home() == root / "profiles" / kid["id"]
    assert store.read_events() == [] and library.list_takes() == []
    store.append_event("touch", node="other", step="s")
    assert atlas.content_dir() == root / "atlas" / "content" and atlas.shared_dir() == root / "atlas"  # shared by all
    profiles.select("default")
    assert [e["node"] for e in store.read_events()] == ["n"]
    profiles.select(kid["id"])
    assert [e["node"] for e in store.read_events()] == ["other"]


def test_a_flute_profile_gets_pan_and_the_microphone(root):
    flute = profiles.create("Flute", instrument="flute")
    assert profiles.instrument() == "flute" and atlas.tree_name() == "Roadmap"
    assert atlas.content_dir() == root / "atlas" / "pan"  # Pan's tree, shared by flute profiles
    profiles.select("default")
    assert profiles.instrument() == "piano" and atlas.content_dir() == root / "atlas" / "content"
    profiles.set_instrument("default", "flute")
    assert profiles.instrument() == "flute" and profiles.load()["profiles"][1]["id"] == flute["id"]
    with pytest.raises(ValueError):
        profiles.create("Oboe", instrument="oboe")


def test_a_profile_learns_several_instruments_each_with_its_own_progress(root):
    store.append_event("touch", node="piano-node", step="s")
    assert atlas.user_dir() == root / "atlas"
    profiles.set_instrument("default", "flute")  # Home's "+ Learn flute"
    p = profiles.active()
    assert p["instrument"] == "flute" and p["instruments"] == ["piano", "flute"]
    assert atlas.user_dir() == root / "atlas-flute" and atlas.content_dir() == root / "atlas" / "pan"
    assert store.read_events() == []  # the flute starts fresh
    store.append_event("touch", node="flute-node", step="s")
    profiles.set_instrument("default", "piano")  # back again: the piano progress is where it was
    assert profiles.active()["instruments"] == ["piano", "flute"] and atlas.user_dir() == root / "atlas"
    assert [e["node"] for e in store.read_events()] == ["piano-node"]
    profiles.set_instrument("default", "flute")
    assert [e["node"] for e in store.read_events()] == ["flute-node"]
    # a flute-first profile keeps its flute progress in atlas/, and a piano added later beside it
    kid = profiles.create("Kim", instrument="flute")
    assert atlas.user_dir() == root / "profiles" / kid["id"] / "atlas"
    profiles.set_instrument(kid["id"], "piano")
    assert atlas.user_dir() == root / "profiles" / kid["id"] / "atlas-piano"


def test_names_are_checked_and_default_stays(root):
    a = profiles.create("Anna Lee", select=False)
    assert a["id"] == "anna-lee" and profiles.active()["id"] == "default"
    with pytest.raises(ValueError):
        profiles.create("anna lee")
    with pytest.raises(ValueError):
        profiles.create("   ")
    assert profiles.create("Anna  Lee!", select=False)["id"] == "anna-lee-2"
    with pytest.raises(ValueError):
        profiles.delete("default")
    profiles.select("anna-lee")
    assert library.profile_home().is_dir()
    assert profiles.rename("anna-lee", "Annie")["name"] == "Annie"
    after = profiles.delete("anna-lee")
    assert after["active"] == "default" and [p["id"] for p in after["profiles"]] == ["default", "anna-lee-2"]
    assert (root / "profiles" / "anna-lee").is_dir()  # its data is kept
    with pytest.raises(ValueError):
        profiles.select("anna-lee")


def test_a_young_learner_gets_simple_words_read_aloud_steps_and_first_steps(root, tmp_path):
    import json
    from types import SimpleNamespace as NS

    from midi_coach import chat, server
    from midi_coach.atlas import build, first_steps
    from midi_coach.tests.test_midi_coach import _fake_claude

    tree = build.build(atlas.load_syllabus(atlas.SAMPLE / "syllabus.json"), [])
    (atlas.content_dir() / "atlas.json").write_text(json.dumps(tree), encoding="utf-8")
    out = server._cmd_profile_new({"name": "Mia", "instrument": "piano", "young": True})
    mia = next(p for p in out["profiles"] if p["name"] == "Mia")
    assert mia["young"] and profiles.young() and out["active"] == mia["id"]
    goals = store.load_goals()
    assert goals["active"] == first_steps.START_GOAL and goals["goals"][0]["targets"] == ["ready.review"]
    assert server._coach.style == "friend" and "Pupil: Mia, a young child" in server._voice_context()
    assert first_steps.start_goal() is None  # a goal already: nothing changes

    usage = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    calls = []
    voice = chat.VoiceChat({}, lambda: "", client=_fake_claude([NS(stop_reason="end_turn", usage=usage,
                                                                   content=[NS(type="text", text="Thumb on C!")])], calls),
                           young=profiles.young)
    voice.ask("what do I do")
    assert calls[0]["system"] == chat.SYSTEM + chat.YOUNG_SYSTEM

    server._cmd_profile_young({"id": mia["id"], "young": False})
    assert not profiles.young() and "Pupil:" not in server._voice_context()
    profiles.create("Grown-up")
    assert store.load_goals()["goals"] == []  # only a young learner starts with a goal
