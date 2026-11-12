"""Drum detection on a synthesized kit over a chord pad."""

from __future__ import annotations

import numpy as np

from radio_hands import drums

SR = 44100


def _band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Noise limited to a band, as a drum's noise is (a snare has little below its body)."""
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec = np.fft.rfft(x) * ((f >= lo) & (f <= hi))
    return np.fft.irfft(spec, len(x))


def _kit(seconds: float, pattern: list[tuple[float, int]], seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = 0.12 * (np.sin(2 * np.pi * 220 * t) + 0.6 * np.sin(2 * np.pi * 277 * t) + 0.5 * np.sin(2 * np.pi * 330 * t))
    for at, lane in pattern:
        i = int(at * SR)
        if lane == drums.LANE_KICK:
            n = int(0.18 * SR); tt = np.arange(n) / SR
            hit = np.sin(2 * np.pi * (110 * np.exp(-tt * 18) + 45) * tt) * np.exp(-tt * 20) * 0.9
        elif lane == drums.LANE_SNARE:
            n = int(0.16 * SR); tt = np.arange(n) / SR
            hit = (np.sin(2 * np.pi * 220 * tt) * 0.4 + _band(rng.standard_normal(n), 180, 9000) * 0.5) * np.exp(-tt * 28)
        else:
            n = int(0.05 * SR); tt = np.arange(n) / SR
            noise = rng.standard_normal(n)
            hit = np.diff(np.concatenate([[0], noise])) * 0.35 * np.exp(-tt * 70)  # high-passed noise
        x[i:i + n] += hit[:len(x) - i]
    return x.astype(np.float32)


def _score(found, want, tol=0.06):
    got = {lane: [t for t, l in found if l == lane] for lane in (drums.LANE_KICK, drums.LANE_SNARE, drums.LANE_HAT)}
    out = {}
    for lane in got:
        w = [t for t, l in want if l == lane]
        hit = sum(any(abs(t - g) <= tol for g in got[lane]) for t in w)
        out[lane] = (hit, len(w), len(got[lane]))
    return out


def test_finds_a_rock_beat():
    pattern = []
    for bar in range(8):  # kick on 1 and 3, snare on 2 and 4, hats on every eighth, at 120 bpm
        b0 = 1.0 + bar * 2.0
        pattern += [(b0, drums.LANE_KICK), (b0 + 1.0, drums.LANE_KICK), (b0 + 0.5, drums.LANE_SNARE), (b0 + 1.5, drums.LANE_SNARE)]
        pattern += [(b0 + 0.25 * k, drums.LANE_HAT) for k in range(8) if k not in (2, 6)]
    audio = _kit(18.0, pattern)
    d = drums.DrumTracker(SR)
    for i in range(0, len(audio), 4410):  # arriving in tenths of a second
        d.add(audio[i:i + 4410])
    s = _score(d.recent(0), pattern)
    (kh, kn, kg), (sh, sn, sg), (hh, hn, hg) = s[drums.LANE_KICK], s[drums.LANE_SNARE], s[drums.LANE_HAT]
    # Tuned on live radio, where it finds most kicks and hats and about half the snares; the
    # detector prefers an extra hit to a missed one, so only a floor on what it finds is checked
    assert kh >= 0.85 * kn, s
    assert sh >= 0.35 * sn, s
    assert hh >= 0.5 * hn, s
    assert kg + sg + hg <= 4 * (kn + sn + hn), s  # and it isn't firing on everything


def test_silence_and_a_pad_have_no_hits():
    d = drums.DrumTracker(SR)
    d.add(_kit(8.0, []))
    assert d.recent(0) == []


def test_started_late_keeps_stream_time():
    pattern = [(1.0 + 0.5 * k, drums.LANE_KICK) for k in range(12)]
    audio = _kit(8.0, pattern)
    d = drums.DrumTracker(SR, start_sample=22222)
    d.add(audio[22222:])
    times = [t for t, lane in d.recent(0) if lane == drums.LANE_KICK]
    want = [w for w, _ in pattern if w > 1.2]
    assert sum(any(abs(t - w) < 0.06 for t in times) for w in want) >= 0.8 * len(want)


def test_gm_lanes():
    assert drums.gm_lane(36) == drums.LANE_KICK and drums.gm_lane(38) == drums.LANE_SNARE
    assert drums.gm_lane(42) == drums.LANE_HAT and drums.gm_lane(49) == drums.LANE_CRASH and drums.gm_lane(60) is None
