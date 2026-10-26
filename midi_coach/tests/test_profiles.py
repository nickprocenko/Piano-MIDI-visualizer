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
    assert profiles.load() == {"active": "default", "profiles": [{"id": "default", "name": "Default", "created": None}]}
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
