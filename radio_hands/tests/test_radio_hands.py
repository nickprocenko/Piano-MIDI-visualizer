"""Radio Hands without a network: reading station titles, finding songs, naming and voicing
chords, lining synthetic audio up with notes, and the stream plumbing."""

from __future__ import annotations

import io
import pathlib

import numpy as np
import pytest

from radio_hands import chords, chroma, songs
from radio_hands.tuner import CHANNELS, IcyReader, Ring

SR = 22050


# -- station titles -------------------------------------------------------------------------

@pytest.mark.parametrize("raw, want", [
    ("REO Speedwagon - Roll with the Changes", ("REO Speedwagon", "Roll with the Changes")),
    ("IF ONLY I - LOUD LUXURY / BEBE REXHA", ("LOUD LUXURY", "IF ONLY I")),
    ("Cranes in the Sky by Solange", ("Solange", "Cranes in the Sky")),
    (". - The Beaches - Edge Of The Earth ~ ", ("The Beaches", "Edge Of The Earth")),
    ("Katy Perry - Dark Horse  SONG", ("Katy Perry", "Dark Horse")),
])
def test_readings_include_the_right_pair(raw, want):
    pairs = [(a.lower(), t.lower()) for a, t in songs.readings(raw)]
    assert (want[0].lower(), want[1].lower()) in pairs


def test_empty_titles_have_no_readings():
    assert songs.readings("") == []
    assert songs.readings("  ''  ") == []


@pytest.fixture
def fake_library(monkeypatch, tmp_path):
    names = ["REO Speedwagon/REO Speedwagon - Roll with the Changes [12].mid",
             "Sparks/Sparks - This Town Aint Big Enough For Both Of Us [3].mid",
             "Simple Minds/Simple Minds - Alive and Kicking [7].mid",
             "Simple Minds/Simple Minds - Alive and Kicking [8].mid",
             "Eels/Eels - Last Stop This Town [423].mid",
             "George Harrison/George Harrison - Dark Horse [5].mid"]
    files = []
    for n in names:
        p = tmp_path / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"MThd")
        files.append(p)
    monkeypatch.setattr(songs.library, "scan_references", lambda: files)
    return songs.Library()


def test_finds_artist_title(fake_library):
    m = fake_library.find("REO Speedwagon - Roll with the Changes")
    assert m and m.name.startswith("REO Speedwagon - Roll with the Changes")


def test_finds_a_title_the_station_cut_short(fake_library):
    m = fake_library.find("Sparks - This Town Aint Big Enough For")
    assert m and "Sparks" in m.name


def test_offers_other_versions(fake_library):
    m = fake_library.find("SIMPLE MINDS - ALIVE AND KICKING")
    assert m and len(m.others) == 1


def test_same_title_other_artist_is_not_the_song(fake_library):
    assert fake_library.find("Katy Perry - Dark Horse") is None


def test_ads_are_not_found(fake_library):
    assert fake_library.find("LR - McDonalds SWAP-YES") is None


# -- chords ---------------------------------------------------------------------------------

def test_parse_chord_names():
    assert chords.parse("C") == (0, (0, 4, 7), 0)
    assert chords.parse("F#m7")[:2] == (6, (0, 3, 7, 10))
    root, intervals, bass = chords.parse("D/F#")
    assert (root, bass) == (2, 6)
    assert chords.parse("Cadd9")[1] == (0, 2, 4, 7)
    assert chords.parse("N.C.") is None


def test_voicing_moves_little_between_chords():
    left, right = chords.voice("C")
    assert left[0] % 12 == 0 and chords.LEFT_LOW <= left[0] <= chords.LEFT_HIGH
    assert sorted(p % 12 for p in right) == [0, 4, 7]
    _, right2 = chords.voice("F", (left, right))
    assert sorted(p % 12 for p in right2) == [0, 5, 9]
    assert sum(abs(a - b) for a, b in zip(right, right2)) <= 4  # C-E-G to C-F-A, not a leap


def _chord_frames(names: list[str], seconds_each: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frames, basses = [], []
    for name in names:
        root, intervals, bass = chords.parse(name)
        c = np.zeros(12)
        for i in intervals:
            c[(root + i) % 12] += 1
            c[(root + i + 7) % 12] += 0.2
        b = np.zeros(12)
        b[bass] = 1
        n = int(seconds_each * chroma.FPS)
        rng = np.random.default_rng(len(frames))
        frames += [c + 0.15 * rng.random(12) for _ in range(n)]
        basses += [b + 0.15 * rng.random(12) for _ in range(n)]
    return chroma._normalize(np.array(frames)), chroma._normalize(np.array(basses)), np.ones(len(frames), bool)


def test_recognizes_a_progression():
    frames, bass, loud = _chord_frames(["C", "G", "Am", "F"], 2.0)
    segs = chords.recognize(frames, bass, loud, chords.TRIADS)
    assert [n for _, _, n in segs] == ["C", "G", "Am", "F"]
    assert abs(segs[1][0] - 20) <= 2  # the change to G at 2 s


def test_bass_tells_relative_chords_apart():
    # A minor and C major share two notes: the bass decides
    frames, bass, loud = _chord_frames(["Am", "C"], 2.0)
    segs = chords.recognize(frames, bass, loud, ["C", "Am", "F", "G"])
    assert [n for _, _, n in segs] == ["Am", "C"]


def test_chord_notes_have_fingers():
    segs = [{"t0": 1.0, "t1": 3.0, "name": "C", "left": [36, 43], "right": [60, 64, 67]}]
    notes = chords.notes_for(segs)
    assert [n[4] for n in notes if n[3] == "right"] == [1, 3, 5]
    assert [n[4] for n in notes if n[3] == "left"] == [5, 1]
    assert notes[0][0] == 1.0 * chords.BPS


# -- lining up ------------------------------------------------------------------------------

def _song(seed: int, seconds: float = 90.0) -> list[tuple]:
    """A made-up song: a chord every 2 s from a random progression, a melody on top."""
    rng = np.random.default_rng(seed)
    roots = rng.integers(0, 12, size=int(seconds / 2))
    notes = []
    for i, r in enumerate(roots):
        t = i * 2.0
        minor = rng.random() < 0.4
        for iv in (0, 3 if minor else 4, 7):
            notes.append((t, t + 1.9, 48 + (r + iv) % 12, 80))
        for k in range(4):
            notes.append((t + k * 0.5, t + k * 0.5 + 0.45, 67 + int(rng.integers(0, 12)), 90))
    return notes


def _render(notes, start: float, seconds: float, speed: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    out = np.zeros_like(t)
    for a, b, p, v in notes:
        ra, rb = (a - start) / speed, (b - start) / speed
        if rb < 0 or ra > seconds:
            continue
        i0, i1 = max(0, int(ra * SR)), min(len(t), int(rb * SR))
        if i1 <= i0:
            continue
        tt = t[i0:i1] - ra
        f = 440 * 2 ** ((p - 69) / 12)
        for h, amp in ((1, 1), (2, 0.5), (3, 0.25)):
            out[i0:i1] += amp * (v / 127) * np.exp(-tt / 0.9) * np.sin(2 * np.pi * f * h * tt)
    return out / (np.abs(out).max() + 1e-9)


def test_finds_place_and_speed():
    notes = _song(1)
    audio = chroma.AudioChroma(SR)
    audio.add(_render(notes, start=30.0, seconds=16.0, speed=1.03))
    frames, loud, t0 = audio.window(0, 16)
    fit = chroma.align(frames, loud, chroma.midi_chroma(notes))
    assert fit is not None and fit.sure
    assert abs(fit.midi_at - (30.0 + t0 * 1.03)) < 0.25
    assert abs(fit.rate - 1.03) <= 0.011


def test_another_song_is_not_sure():
    audio = chroma.AudioChroma(SR)
    audio.add(_render(_song(1), start=30.0, seconds=16.0, speed=1.0))
    frames, loud, _ = audio.window(0, 16)
    fit = chroma.align(frames, loud, chroma.midi_chroma(_song(2)))
    assert fit is None or not fit.sure


def test_analysis_started_late_keeps_stream_time():
    # after falling behind (or a retune race) the analysis restarts mid-stream: its frames must
    # still be numbered, and timed, as the stream's
    x = _render(_song(3), start=0.0, seconds=8.0, speed=1.0)
    full = chroma.AudioChroma(SR)
    full.add(x)
    late = chroma.AudioChroma(SR, start_sample=12345)
    late.add(x[12345:])
    assert late.base * late.hop >= 12345
    k = late.base - full.base
    assert np.allclose(late.frames[0], full.frames[k], atol=1e-5)
    a, _, t_late = late.window(3.0, 6.0)
    b, _, t_full = full.window(3.0, 6.0)
    assert t_late == t_full and np.allclose(a, b, atol=1e-5)


def test_too_little_music_says_nothing():
    audio = chroma.AudioChroma(SR)
    audio.add(np.zeros(SR * 10))
    frames, loud, _ = audio.window(0, 10)
    assert chroma.align(frames, loud, chroma.midi_chroma(_song(1))) is None


# -- the stream ------------------------------------------------------------------------------

def test_icy_reader_cuts_titles_out():
    audio = bytes(range(256)) * 4  # 1024 bytes of "audio"
    meta = b"StreamTitle='Toto - Africa';".ljust(32, b"\0")
    stream = audio[:512] + bytes([2]) + meta + audio[512:] + bytes([0])
    titles = []
    reader = IcyReader(io.BytesIO(stream), 512, titles.append)
    out = io.BufferedReader(reader).read()
    assert out == audio
    assert titles == ["Toto - Africa"]


def test_ring_wraps_and_skips_what_was_overwritten():
    ring = Ring(seconds=1)
    block = np.arange(30000 * CHANNELS, dtype=np.int16).reshape(-1, CHANNELS)
    ring.write(block)
    ring.write(block)  # 60000 samples into a ring of 44100
    start, got = ring.read(0, 100000)
    assert start == 60000 - ring.cap
    assert len(got) == ring.cap
    assert (got[-30000:] == block).all()
