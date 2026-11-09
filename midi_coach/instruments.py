"""The instruments a profile can learn, and what each one changes.

Piano is played on the keyboard over MIDI. The others are heard through the microphone: the
coach page tracks the pitch (static/flute.js, with each instrument's limits from mic below)
and posts each note to the server as if a key were pressed. Each has its own Roadmap folder
in <home>/atlas, built by atlas.pan's engine (the flute's, atlas.sax, atlas.voice, atlas.fiddle,
atlas.guitar, atlas.bass).

An alto saxophone reads music written a major sixth (9 semitones) above how it sounds: its
scores are in written pitch, so the page adds `transpose` to every pitch it hears and takes it
off the examples it plays. A singer picks a high or a low voice: a low voice sings the same
Roadmap an octave down, from scores in the treble clef with an 8 below (stored at sounding
pitch, so nothing is shifted).

A guitar and a bass guitar are written an octave above how they sound, so their scores are in
the treble or bass clef with an 8 below, stored at sounding pitch: nothing is shifted either.
They have strings (`strings`: the open strings' sounding MIDI notes, low to high), so the page
can draw a tab staff under their notes when the player turns it on. The microphone hears one
note at a time: a guitar's graded work is single notes, its chords are taught but not graded.
"""

from __future__ import annotations

from . import profiles

# mic: the pitch tracker's limits on the page (Hz, the YIN threshold, the level gate, and
# how far the pitch may wander before it's a new note, in semitones; size: the shortest analysis
# window in samples, as YIN needs two periods of the lowest note: a guitar's E is 82 Hz, a bass's 41).
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
    "fiddle": {"name": "Fiddle", "input": "mic", "folder": "fiddle", "player": "fiddler", "part": "Fiddle", "transpose": 0,
               "build": "midi_coach.atlas.fiddle",
               "mic": {"fmin": 180, "fmax": 2000, "threshold": 0.15, "change": 0.6}},
    "guitar": {"name": "Electric guitar", "input": "mic", "folder": "guitar", "player": "guitarist", "part": "Guitar",
               "transpose": 0, "build": "midi_coach.atlas.guitar", "strings": [40, 45, 50, 55, 59, 64], "frets": 22,
               "look": {"clef": "treble8vb", "octave": -12},
               "mic": {"fmin": 75, "fmax": 1200, "threshold": 0.15, "change": 0.6, "size": 2048}},
    "bass": {"name": "Bass guitar", "input": "mic", "folder": "bass", "player": "bassist", "part": "Bass Guitar",
             "transpose": 0, "build": "midi_coach.atlas.bass", "strings": [28, 33, 38, 43], "frets": 20,
             "look": {"clef": "bass8vb", "octave": -12},
             "mic": {"fmin": 38, "fmax": 450, "threshold": 0.15, "change": 0.6, "size": 4096}},  # a low E is 41 Hz
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
    """'pianist', 'flutist', 'saxophonist', 'singer', 'fiddler', 'guitarist', 'bassist'."""
    return get(instrument)["player"]


def score_look(instrument: str | None = None) -> dict:
    """build_lesson's clef and octave for a one-line lesson written for the instrument: a guitar's
    and a bass's are written an octave up under an 8 clef and stored at sounding pitch."""
    return dict(get(instrument).get("look", {}))


def page_config() -> dict:
    """What the coach page needs to hear the active profile's instrument."""
    inst = get()
    return {"id": inst["id"], "name": inst["name"], "input": inst["input"], "voice": profiles.active().get("voice"),
            "transpose": inst.get("transpose", 0), "mic": inst.get("mic"), "strings": inst.get("strings"),
            "frets": inst.get("frets")}
