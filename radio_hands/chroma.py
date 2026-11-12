"""Line the radio up with a MIDI file: where in the file is the music playing now, and how fast.

Both sides become chroma, the 12 pitch classes' strength ten times a second: the radio from its
spectrum, the MIDI from the notes sounding (with a little of each note's overtones, as an
instrument has them). Lining up compares the last stretch of radio against every place and
every tempo in the file: a fan-made MIDI rarely starts where the record does, its tempo is a
guess, and commercial stations often play songs a few percent fast.

    frames = AudioChroma(sample_rate)      # fed the radio as it arrives
    m = midi_chroma(notes)                 # [(start s, end s, pitch, velocity), ...]
    fit = align(frames.window(a, b), m)    # Fit(midi_at_start, rate, score, margin)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

FPS = 10                      # chroma frames a second, both sides
LOW, HIGH = 45, 100           # MIDI pitches the radio's spectrum is read over (A2..E7)
RATES = np.round(np.arange(0.80, 1.2001, 0.01), 3)  # MIDI seconds per radio second (fan MIDIs are often 10%+ off the record)
PAD_SEC = 12.0                # the radio may start this far before the file's first note
MIN_FRAMES = 6 * FPS          # at least this much music before a fit is tried
QUIET = 1e-3                  # a radio frame this quiet (RMS) is left out of the comparison
SURE_SCORE = 0.52             # a fit this alike (correlation; wrong songs reach ~0.5 on real radio) ...
SURE_CONTRAST = 0.1           # ... and this far above the file's typical place is the song
PRIOR_SLOPE = 0.004           # likeness taken off per second a place is beyond the prior's tolerance


@dataclass
class Fit:
    midi_at: float     # the MIDI time (s) at the window's first frame
    rate: float        # MIDI seconds per radio second
    score: float       # mean likeness of the frames, 0-1
    margin: float      # how far the best place stands above the next best elsewhere (0-1)
    contrast: float    # how far it stands above a typical place in the file (0-1)

    @property
    def sure(self) -> bool:
        """The music is this file's, here or at a repeat of this passage (a chorus heard twice
        has the same notes, so either place shows the right hands)."""
        return self.score >= SURE_SCORE and self.contrast >= SURE_CONTRAST

    @property
    def unique(self) -> bool:
        """And nowhere else in the file fits nearly as well."""
        return self.sure and self.margin >= 0.03

    def midi_time(self, offset: float) -> float:
        """The MIDI time `offset` radio seconds after the window's start."""
        return self.midi_at + self.rate * offset


def _pitch_map(sr: int, n: int, low: int = LOW, high: int = HIGH) -> np.ndarray:
    """(bins, 12): how much of each FFT bin goes to each pitch class (a triangle around each
    semitone, so a slightly sharp or flat station still lands on its notes)."""
    freqs = np.fft.rfftfreq(n, 1 / sr)
    w = np.zeros((len(freqs), 12), dtype=np.float32)
    lo_f = 440 * 2 ** ((low - 0.5 - 69) / 12)
    hi_f = 440 * 2 ** ((high + 0.5 - 69) / 12)
    for k, f in enumerate(freqs):
        if f < lo_f or f > hi_f:
            continue
        p = 69 + 12 * math.log2(f / 440)
        near = round(p)
        w[k, near % 12] = max(0.0, 1 - abs(p - near) * 1.6)
    return w


def _normalize(c: np.ndarray) -> np.ndarray:
    """Log-compressed, each frame's mean taken off and scaled to length 1, so the dot product of
    two frames is their correlation: about 0 for unrelated music (any two chords share notes,
    which plain chroma vectors would count as a likeness), 1 for the same chord."""
    peak = c.max(axis=-1, keepdims=True)
    c = np.log1p(30 * c / (peak + 1e-9)) * (peak > 0)
    c = c - c.mean(axis=-1, keepdims=True)
    return c / (np.linalg.norm(c, axis=-1, keepdims=True) + 1e-9)


BASS_LOW, BASS_HIGH = 36, 55  # the bass line's range (C2..G3), read on its own for chord roots
KEEP_SEC = 600                 # frames older than this are dropped


class AudioChroma:
    """The radio's chroma, a frame every 1/FPS s, computed as audio is added. Frame k is the
    window starting at sample k * hop (its centre is half a window later). Each frame has the
    whole range's chroma and the bass range's on its own (for naming chords)."""

    def __init__(self, sr: int, start_sample: int = 0):
        """start_sample: the stream sample the first audio added is (frames keep the stream's
        numbering, so their times stay stream seconds)."""
        self.sr = sr
        self.hop = sr // FPS
        self.n = 1 << int(math.ceil(math.log2(sr * 0.18)))  # ~0.19-0.37 s: fine enough for low notes
        self.window_fn = np.hanning(self.n).astype(np.float32)
        self.map = _pitch_map(sr, self.n)
        self.bass_map = _pitch_map(sr, self.n, BASS_LOW, BASS_HIGH)
        self._skip = (-start_sample) % self.hop  # samples to drop so frames start on the stream's grid
        self._next = start_sample + self._skip  # the sample index of the next frame's start
        self.base = self._next // self.hop  # the frame number of frames[0]
        self.frames: list[np.ndarray] = []
        self.bass: list[np.ndarray] = []
        self.levels: list[float] = []
        self._tail = np.zeros(0, dtype=np.float32)

    @property
    def centre(self) -> float:
        """Seconds from a frame's start to its centre."""
        return self.n / 2 / self.sr

    @property
    def end(self) -> int:
        """The frame number after the last one."""
        return self.base + len(self.frames)

    def add(self, mono: np.ndarray) -> None:
        """Append mono float samples (in order, none skipped)."""
        if self._skip:
            drop = min(self._skip, len(mono))
            mono, self._skip = mono[drop:], self._skip - drop
        buf = np.concatenate([self._tail, mono.astype(np.float32)])
        base = self._next  # sample index of buf[0]
        starts = np.arange(0, len(buf) - self.n + 1, self.hop)
        if len(starts):
            segs = np.stack([buf[s:s + self.n] for s in starts]) * self.window_fn
            mags = np.abs(np.fft.rfft(segs, axis=1)).astype(np.float32)
            levels = np.sqrt((segs ** 2).mean(axis=1))
            for c, b, lv in zip(_normalize(mags @ self.map), _normalize(mags @ self.bass_map), levels):
                self.frames.append(c)
                self.bass.append(b)
                self.levels.append(float(lv))
            start = int(starts[-1]) + self.hop
        else:
            start = 0
        self._tail = buf[start:]
        self._next = base + start
        extra = len(self.frames) - KEEP_SEC * FPS
        if extra > FPS * 60:  # drop old frames a minute's worth at a time
            del self.frames[:extra], self.bass[:extra], self.levels[:extra]
            self.base += extra

    def time_of(self, frame: int) -> float:
        """Stream seconds at a frame's centre."""
        return frame * self.hop / self.sr + self.centre

    def frame_at(self, seconds: float) -> int:
        return max(0, int(round((seconds - self.centre) * self.sr / self.hop)))

    def window(self, start_sec: float, end_sec: float, bass: bool = False):
        """(frames, loud enough?, stream seconds at the first frame's centre) between two times;
        with bass, (frames, bass frames, loud, start)."""
        a = max(self.base, self.frame_at(start_sec))
        b = min(self.end, self.frame_at(end_sec))
        if b <= a:
            empty = np.zeros((0, 12), np.float32)
            return (empty, empty, np.zeros(0, bool), self.time_of(a)) if bass else (empty, np.zeros(0, bool), self.time_of(a))
        frames = np.stack(self.frames[a - self.base:b - self.base])
        loud = np.array(self.levels[a - self.base:b - self.base]) > QUIET
        if bass:
            return frames, np.stack(self.bass[a - self.base:b - self.base]), loud, self.time_of(a)
        return frames, loud, self.time_of(a)


# Overtones heard with a note, by pitch class above it: the octaves add to the note's own class,
# the 3rd harmonic is a fifth up (7), the 5th a major third (4).
OVERTONES = ((0, 1.0), (7, 0.35), (4, 0.12))


def midi_chroma(notes, duration: float | None = None) -> np.ndarray:
    """The MIDI's chroma at FPS frames a second from time 0. notes: (start, end, pitch, velocity)
    for every pitched note (no drums). A note is loudest as it starts and fades to a sustain, as
    most instruments do."""
    notes = list(notes)
    end = max([n[1] for n in notes] + [duration or 0.0, 1.0])
    frames = int(math.ceil(end * FPS)) + 1
    c = np.zeros((frames, 12), dtype=np.float32)
    for start, stop, pitch, vel in notes:
        a = int(start * FPS)
        b = max(a + 1, int(math.ceil(stop * FPS)))
        t = (np.arange(a, b) - start * FPS) / FPS
        level = (0.25 + vel / 127) * np.maximum(0.35, np.exp(-t / 1.2))
        for step, share in OVERTONES:
            c[a:b, (pitch + step) % 12] += share * level
    return _normalize(c)


def align(audio: np.ndarray, loud: np.ndarray, midi: np.ndarray, near: tuple[float, float] | None = None,
          rates: np.ndarray | None = None, prior: tuple[float, float] | None = None) -> Fit | None:
    """The best place (and tempo) for this stretch of radio in the MIDI.

    audio: (n, 12) frames at FPS; loud: which of them have music. midi: (m, 12) from
    midi_chroma. near: (midi seconds, ± seconds) to look only around where it should be.
    prior: (midi seconds, ± seconds) where it probably is (from when the song started), which
    settles a passage the file repeats without ruling anywhere out. None when there isn't
    enough music in the stretch to say."""
    keep = np.flatnonzero(loud)
    if len(keep) < MIN_FRAMES:
        return None
    rates = RATES if rates is None else np.asarray(rates)
    pad = int(PAD_SEC * FPS)
    m = np.concatenate([np.zeros((pad, 12), np.float32), midi, np.zeros((pad, 12), np.float32)])
    sim = audio[keep] @ m.T  # (frames kept, padded midi frames)
    if near is None:
        offsets = np.arange(0, len(m))
    else:
        centre, spread = near
        lo = int((centre - spread) * FPS) + pad
        hi = int((centre + spread) * FPS) + pad + 1
        offsets = np.arange(max(0, lo), min(len(m), hi))
    if not len(offsets):
        return None
    penalty = np.zeros(len(offsets))
    if prior is not None:
        expected, tolerance = prior
        beyond = np.abs((offsets - pad) / FPS - expected) - tolerance
        penalty = PRIOR_SLOPE * np.maximum(0.0, beyond)
    best = (-1.0, 0, 1.0, -1.0)
    surface = []  # best score at each offset over the rates, for the margin
    rows = np.arange(len(keep))[None, :]
    for r in rates:
        cols = offsets[:, None] + np.round(keep * r).astype(int)[None, :]
        inside = cols < len(m)
        scores = np.where(inside, sim[rows, np.minimum(cols, len(m) - 1)], 0.0).sum(axis=1) / len(keep)
        surface.append(scores)
        ranked = scores - penalty
        i = int(np.argmax(ranked))
        if ranked[i] > best[3]:
            best = (float(scores[i]), i, float(r), float(ranked[i]))
    surface = np.max(np.stack(surface), axis=0)
    score, i, rate, _ = best
    typical = float(np.median(surface))
    # Sub-frame: a parabola through the best offset and its neighbours (at the best rate)
    frac = 0.0
    if 0 < i < len(offsets) - 1:
        cols = offsets[[i - 1, i, i + 1]][:, None] + np.round(keep * rate).astype(int)[None, :]
        y = np.where(cols < len(m), sim[rows, np.minimum(cols, len(m) - 1)], 0.0).sum(axis=1) / len(keep)
        den = y[0] - 2 * y[1] + y[2]
        if den < 0:
            frac = float(np.clip(0.5 * (y[0] - y[2]) / den, -0.5, 0.5))
    # Margin: the best score more than 2.5 s away from this place
    away = np.abs(np.arange(len(offsets)) - i) > 2.5 * FPS
    others = (surface - penalty)[away]
    margin = score - penalty[i] - float(others.max()) if len(others) else score
    midi_at = (offsets[i] + frac - pad) / FPS
    return Fit(midi_at=midi_at, rate=rate, score=score, margin=margin, contrast=score - typical)
