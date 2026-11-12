"""Drum hits from the radio's audio: kick, snare and hi-hat, found by where the sound is.

A kick is a thump (35-130 Hz), a snare a crack with a body (180-420 Hz) and a hiss (2-6 kHz), a
hi-hat only hiss (7-16 kHz). For each band the spectral flux (how much louder it just got, per
frequency) is compared with its own recent average, and a peak well above that is a hit. It's
the usual onset method, so it follows the main beat well and misses or invents the odd hit in
busy fills; toms and crashes aren't told apart (the page leaves those lanes to the song's own
MIDI drums when it has them).

Lanes, as the page draws them: 0 crash/ride, 1 hi-hat, 2 snare, 3 tom, 4 kick.
"""

from __future__ import annotations

import threading

import numpy as np

LANE_CRASH, LANE_HAT, LANE_SNARE, LANE_TOM, LANE_KICK = range(5)

N = 2048
HOP = 512
BANDS = {"kick": (35, 130), "snare_lo": (180, 420), "snare_hi": (2000, 6000), "hat": (7000, 16000)}
WINDOW = 43            # frames (~0.5 s) of a band's own history the threshold is made from
SPREAD = 0.5           # standard deviations above that history a peak must reach (tuned on live radio against songs' MIDI drums)
FLOOR = {"kick": 0.25, "snare": 0.09, "hat": 0.05}   # flux (per bin) a hit must reach whatever the history
MIN_GAP_SEC = {"kick": 0.14, "snare": 0.12, "hat": 0.06}
KICK_OVER = 1.5       # a snare candidate with this much more thump than body is a kick
HISS_OVER = 2.5       # a kick candidate with this much more hiss than thump is not
KEEP_SEC = 120
LATENCY = 0.012        # seconds from a frame's centre back to where its onset began


def gm_lane(pitch: int) -> int | None:
    """The lane of a General MIDI drum note (channel 10)."""
    if pitch in (35, 36):
        return LANE_KICK
    if pitch in (37, 38, 39, 40):
        return LANE_SNARE
    if pitch in (42, 44, 46):
        return LANE_HAT
    if pitch in (41, 43, 45, 47, 48, 50):
        return LANE_TOM
    if pitch in (49, 51, 52, 53, 55, 57, 59):
        return LANE_CRASH
    return None


class DrumTracker:
    def __init__(self, sr: int, start_sample: int = 0):
        self.sr = sr
        self.window = np.hanning(N).astype(np.float32)
        freqs = np.fft.rfftfreq(N, 1 / sr)
        self.bins = {name: np.flatnonzero((freqs >= lo) & (freqs <= hi)) for name, (lo, hi) in BANDS.items()}
        self._skip = (-start_sample) % HOP
        self._next = start_sample + self._skip   # stream sample the next frame starts at
        self._tail = np.zeros(0, np.float32)
        self._prev: np.ndarray | None = None
        self.base_sample = self._next            # stream sample frame 0 starts at
        self.flux = {"kick": [], "snare": [], "hat": []}
        self.parts = {"lo": [], "hi": []}        # the snare's body and crack, kept for telling it from a kick with a hat
        self.done = 0                            # frames before this have been looked at for peaks
        self.last = {"kick": -10**9, "snare": -10**9, "hat": -10**9}
        self.hits: list[tuple[float, int]] = []
        self.lock = threading.Lock()
        self.min_gap = {k: max(1, int(v * sr / HOP)) for k, v in MIN_GAP_SEC.items()}

    def add(self, mono: np.ndarray) -> None:
        """Append mono float samples (in order, none skipped)."""
        if self._skip:
            drop = min(self._skip, len(mono))
            mono, self._skip = mono[drop:], self._skip - drop
        buf = np.concatenate([self._tail, mono.astype(np.float32)])
        starts = np.arange(0, len(buf) - N + 1, HOP)
        if not len(starts):
            self._tail = buf
            return
        segs = np.stack([buf[s:s + N] for s in starts]) * self.window
        logm = np.log1p(np.abs(np.fft.rfft(segs, axis=1)).astype(np.float32) * 4)
        before = self._prev if self._prev is not None else logm[0]
        diff = np.maximum(0.0, np.diff(np.vstack([before[None, :], logm]), axis=0))
        self._prev = logm[-1]
        per = {k: diff[:, b].mean(axis=1) for k, b in self.bins.items()}
        self.flux["kick"] += per["kick"].tolist()
        self.flux["snare"] += np.sqrt(per["snare_lo"] * per["snare_hi"]).tolist()  # both: a hat has no body, a kick no crack
        self.flux["hat"] += per["hat"].tolist()
        self.parts["lo"] += per["snare_lo"].tolist()
        self.parts["hi"] += (per["snare_hi"] + per["hat"]).tolist()
        self._tail = buf[int(starts[-1]) + HOP:]
        self._pick()

    def _pick(self) -> None:
        n = len(self.flux["kick"])
        found: dict[str, list[int]] = {"kick": [], "snare": [], "hat": []}
        for i in range(max(self.done, 2), n - 2):
            for name, series in self.flux.items():
                v = series[i]
                if v < FLOOR[name] or i - self.last[name] < self.min_gap[name]:
                    continue
                if v < max(series[i - 2:i + 3]):
                    continue
                if name == "snare" and self.flux["kick"][i] > KICK_OVER * self.parts["lo"][i]:
                    continue  # mostly thump: a kick with a hat
                if name == "kick" and self.parts["hi"][i] > HISS_OVER * v:
                    continue  # mostly hiss: a snare or hat whose noise reaches down here
                hist = np.asarray(series[max(0, i - WINDOW):i])
                if len(hist) >= 8 and v < hist.mean() + SPREAD * hist.std():
                    continue
                self.last[name] = i
                found[name].append(i)
        self.done = max(self.done, n - 2)
        lanes = {"kick": LANE_KICK, "snare": LANE_SNARE, "hat": LANE_HAT}
        snares = found["snare"]
        with self.lock:
            for name, frames in found.items():
                for i in frames:
                    if name == "hat" and any(abs(i - s) <= 1 for s in snares):
                        continue  # a snare's hiss isn't a hat as well
                    t = (self.base_sample + i * HOP + N / 2) / self.sr - LATENCY
                    self.hits.append((round(t, 3), lanes[name]))
            self.hits.sort()
            cutoff = self.hits[-1][0] - KEEP_SEC if self.hits else 0
            if self.hits and self.hits[0][0] < cutoff:
                self.hits = [h for h in self.hits if h[0] >= cutoff]
        keep = int(KEEP_SEC * self.sr / HOP)
        if len(self.flux["kick"]) > keep * 2:  # drop old history; frame numbers shift
            cut = len(self.flux["kick"]) - keep
            for series in list(self.flux.values()) + list(self.parts.values()):
                del series[:cut]
            self.done -= cut
            self.base_sample += cut * HOP
            for k in self.last:
                self.last[k] -= cut

    def recent(self, since: float) -> list[list]:
        with self.lock:
            return [[t, lane] for t, lane in self.hits if t >= since]
