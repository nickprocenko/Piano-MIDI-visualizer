"""The instruments a profile can learn, and what each one changes.

Piano is played on the keyboard over MIDI. The others are heard through the microphone: the
coach page tracks the pitch (static/flute.js, with each instrument's limits from mic below)
and posts each note to the server as if a key were pressed. Each has its own Roadmap folder
in <home>/atlas, built by atlas.pan's engine (the flute's, atlas.sax, atlas.voice).

An alto saxophone reads music written a major sixth (9 semitones) above how it sounds: its
scores are in written pitch, so the page adds `transpose` to every pitch it hears and takes it
off the examples it plays. A singer picks a high or a low voice: a low voice sings the same
Roadmap an octave down, from scores in the treble clef with an 8 below (stored at sounding
pitch, so nothing is shifted).
"""

from __future__ import annotations

from . import profiles

# mic: the pitch tracker's limits on the page (Hz, the YIN threshold, the level gate, and
# how far the pitch may wander before it's a new note, in semitones).
INSTRUMENTS = {
    "piano": {"name": "Piano", "input": "midi", "folder": "content", "player": "pianist", "build": "midi_coach.atlas.build"},
    "flute": {"name": "Flute", "input": "mic", "folder": "pan", "player": "flutist", "part": "Flute", "transpose": 0,
              "build": "midi_coach.atlas.pan",
              "mic": {"fmin": 240, "fmax": 2400, "threshold": 0.12, "change": 0.6}},
    "sax": {"name": "Alto saxophone", "input": "mic", "folder": "sax", "player": "saxophonist", "part": "Alto Saxophone",
            "transpose": 9, "build": "midi_coach.atlas.sax",
            "mic": {"fmin": 120, "fmax": 1000, "threshold": 0.15, "change": 0.6}},
    "voice": {"name": "Vocals", "input": "mic", "folder": "voice-high", "player": "singer", "part": "Voice", "transpose": 0,
              "build": "midi_coach.atlas.voice",
              "mic": {"fmin": 150, "fmax": 1100, "threshold": 0.18, "change": 0.75}},  # a voice slides and wavers more
}
VOICES = ("high", "low")
LOW_VOICE = {"folder": "voice-low", "mic": {"fmin": 70, "fmax": 600, "threshold": 0.18, "change": 0.75}}


def get(instrument: str | None = None, voice: str | None = None) -> dict:
    """The instrument's entry (the active profile's by default), with a low voice's changes."""
    if instrument is None:
        p = profiles.active()
        instrument, voice = p["instrument"], p.get("voice")
    out = dict(INSTRUMENTS[instrument], id=instrument)
    if instrument == "voice" and voice == "low":
        out.update(LOW_VOICE)
    return out


def current() -> str:
    return profiles.instrument()


def uses_mic(instrument: str | None = None) -> bool:
    """Whether the instrument is heard through the microphone (everything but the piano)."""
    return get(instrument)["input"] == "mic"


def folder(instrument: str | None = None, voice: str | None = None) -> str:
    """The Roadmap's content folder in <home>/atlas."""
    return get(instrument, voice)["folder"]


def name(instrument: str | None = None) -> str:
    return get(instrument)["name"]


def player_word(instrument: str | None = None) -> str:
    """'pianist', 'flutist', 'saxophonist', 'singer'."""
    return get(instrument)["player"]


def page_config() -> dict:
    """What the coach page needs to hear the active profile's instrument."""
    inst = get()
    return {"id": inst["id"], "name": inst["name"], "input": inst["input"], "voice": profiles.active().get("voice"),
            "transpose": inst.get("transpose", 0), "mic": inst.get("mic")}
