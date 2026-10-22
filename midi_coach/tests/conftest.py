import pytest


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch):
    """Tests must never open the coach page in the user's browser."""
    monkeypatch.setenv("MIDI_COACH_NO_BROWSER", "1")
    monkeypatch.setattr("webbrowser.open", lambda *args, **kwargs: pytest.fail("a test tried to open a browser tab"))
