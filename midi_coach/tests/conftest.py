import pytest


@pytest.fixture(autouse=True)
def _no_hand_model(monkeypatch):
    """Tests split the hands with notes.split_by_reach, whether or not the trained hand model
    is installed on this machine; tests of the model point MIDI_COACH_HAND_MODEL at it."""
    monkeypatch.setenv("MIDI_COACH_HAND_MODEL", "off")


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch):
    """Tests must never open the coach page in the user's browser."""
    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: pytest.fail("a test tried to open a browser tab"))
