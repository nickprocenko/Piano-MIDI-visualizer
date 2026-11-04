import pytest


@pytest.fixture(autouse=True)
def _no_hand_model(monkeypatch):
    """Tests split the hands with notes.split_by_reach, whether or not the trained hand model
    is installed on this machine; tests of the model point MIDI_COACH_HAND_MODEL at it."""
    monkeypatch.setenv("MIDI_COACH_HAND_MODEL", "off")


@pytest.fixture(autouse=True)
def _own_home(monkeypatch, tmp_path):
    """Tests never read or write the user's ~/MidiCoach (their profiles, takes, progress): each
    gets an empty home of its own. A test that sets MIDI_COACH_HOME itself still wins."""
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))


@pytest.fixture(autouse=True)
def _no_vault(monkeypatch):
    """Tests never write Backlog.md into the user's Obsidian vault; test_bugs.py points it at a temp one."""
    monkeypatch.setenv("MIDI_COACH_VAULT", "off")


@pytest.fixture(autouse=True)
def _no_song_watch(monkeypatch):
    """No background thread watching folders for new songs; test_songwatch.py polls by hand."""
    monkeypatch.setenv("MIDI_COACH_SONG_WATCH", "off")


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch):
    """Tests must never open the coach page in the user's browser."""
    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: pytest.fail("a test tried to open a browser tab"))
