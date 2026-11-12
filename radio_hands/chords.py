"""Chords for a song that isn't in the library: heard from the radio, and played by the hands.

The radio's chroma is compared with each chord's notes (and its bass with the chord's bass
note), and a path through the song's chords is chosen that changes chord only when the music
clearly does (Viterbi). The chords to choose from are the song's own when a chart lists them,
else the 24 major and minor triads. Each chord is then voiced for two hands: the left plays the
bass note and its fifth, the right the chord close above middle C, moving as little as it can
from the chord before.
"""

from __future__ import annotations

import re

import numpy as np

from midi_coach.harmony import TEMPLATES
from midi_coach.web import pitch_class

from . import chroma

NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
TRIADS = [n + q for q in ("", "m") for n in NAMES]
SWITCH = 1.6          # likeness (summed over frames) a new chord must gain to be worth changing to
BASS_SHARE = 0.35     # how much the bass note counts against the chord's notes
NONE_BELOW = 0.18     # frames liking every chord less than this are 'no chord'
LAG_SEC = 1.2         # a chord is settled once this much music has followed it
REDO_SEC = 4.0        # each update re-decides the music this far back from the last settled chord
MIN_SEC = 0.4         # shorter chords are merged into their neighbours
LEFT_LOW, LEFT_HIGH = 36, 50   # the left hand's bass note (C2..D3)
RIGHT_LOW, RIGHT_HIGH = 59, 77  # the right hand's chord (B3..F5)


def parse(name: str) -> tuple[int, tuple[int, ...], int] | None:
    """(root, intervals, bass) of a chord name such as 'F#m7', 'Cadd9' or 'D/F#'; None if it
    isn't one. Suffixes the templates don't have fall back to their triad."""
    m = re.match(r"^([A-G][b#]?)([^/]*)(?:/([A-G][b#]?))?$", (name or "").strip())
    if not m:
        return None
    root = pitch_class(m.group(1))
    if root is None:
        return None
    suffix = m.group(2) or ""
    if suffix in TEMPLATES:
        intervals = TEMPLATES[suffix]
    else:
        minor = suffix.startswith(("m", "min", "-")) and not suffix.startswith("maj")
        base = list(TEMPLATES["m" if minor else ""])
        if "sus4" in suffix or suffix.startswith("sus"):
            base = [0, 5, 7]
        elif "sus2" in suffix:
            base = [0, 2, 7]
        extended = re.sub(r"add\d+", "", suffix)  # 'add9' adds a ninth, not a seventh
        if "maj7" in extended or "maj9" in extended:
            base.append(11)
        elif re.search(r"7|9|11|13", extended):
            base.append(10)
        if "add9" in suffix or "add2" in suffix:
            base.append(2)
        if "dim" in suffix:
            base = [0, 3, 6]
        intervals = tuple(sorted(set(base)))
    bass = pitch_class(m.group(3)) if m.group(3) else root
    return root, tuple(intervals), root if bass is None else bass


def _templates(names: list[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
    """The usable chords among names, with their chroma and bass templates (normalized as the
    radio's frames are, so a dot product is a correlation)."""
    kept, notes, basses = [], [], []
    for n in dict.fromkeys(names):
        p = parse(n)
        if p is None:
            continue
        root, intervals, bass = p
        c = np.zeros(12, np.float32)
        for i in intervals:
            for step, share in chroma.OVERTONES:
                c[(root + i + step) % 12] += share * (1.15 if i == 0 else 1.0)
        b = np.zeros(12, np.float32)
        b[bass] = 1.0
        b[(bass + 7) % 12] = 0.3
        kept.append(n)
        notes.append(c)
        basses.append(b)
    if not kept:
        return [], np.zeros((0, 12), np.float32), np.zeros((0, 12), np.float32)
    return kept, chroma._normalize(np.stack(notes)), chroma._normalize(np.stack(basses))


def viterbi(scores: np.ndarray, switch: float = SWITCH) -> np.ndarray:
    """The chord (column) for each frame (row) that maximizes the summed scores less `switch`
    for every change."""
    n, k = scores.shape
    total = scores[0].copy()
    back = np.zeros((n, k), np.int32)
    for i in range(1, n):
        best = int(np.argmax(total))
        stay = total
        move = total[best] - switch
        back[i] = np.where(stay >= move, np.arange(k), best)
        total = np.maximum(stay, move) + scores[i]
    path = np.zeros(n, np.int32)
    path[-1] = int(np.argmax(total))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]
    return path


def recognize(frames: np.ndarray, bass: np.ndarray, loud: np.ndarray, names: list[str]) -> list[tuple[int, int, str]]:
    """[(first frame, frame after, chord name or '')] for a stretch of radio."""
    kept, tn, tb = _templates(names)
    if not len(frames) or not kept:
        return []
    like = (1 - BASS_SHARE) * (frames @ tn.T) + BASS_SHARE * (bass @ tb.T)
    # 'no chord' is one more choice: likes quiet frames, and frames no chord fits
    none = np.where(loud, NONE_BELOW, 1.0)[:, None]
    path = viterbi(np.concatenate([like, none], axis=1))
    labels = kept + [""]
    out: list[list] = []
    for i, c in enumerate(path):
        if out and out[-1][2] == labels[c]:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1, labels[c]])
    # merge slivers into the longer neighbour
    min_frames = int(MIN_SEC * chroma.FPS)
    merged: list[list] = []
    for seg in out:
        if merged and seg[1] - seg[0] < min_frames:
            merged[-1][1] = seg[1]
        elif merged and merged[-1][1] - merged[-1][0] < min_frames and len(merged) == 1:
            seg[0] = merged[-1][0]
            merged[-1] = seg
        else:
            merged.append(seg)
    joined: list[list] = []
    for seg in merged:
        if joined and joined[-1][2] == seg[2]:
            joined[-1][1] = seg[1]
        else:
            joined.append(seg)
    return [(a, b, n) for a, b, n in joined]


# -- voicing --------------------------------------------------------------------------------

def _nearest(pc: int, low: int, high: int, near: float) -> int:
    options = [p for p in range(low, high + 1) if p % 12 == pc]
    return min(options, key=lambda p: (abs(p - near), p)) if options else low + (pc - low) % 12


def voice(name: str, before: tuple[list[int], list[int]] | None = None) -> tuple[list[int], list[int]]:
    """(left-hand pitches, right-hand pitches) for a chord, close to the voicing before it."""
    p = parse(name)
    if p is None:
        return [], []
    root, intervals, bass = p
    prev_left, prev_right = before if before else ([], [])
    low = _nearest(bass, LEFT_LOW, LEFT_HIGH, prev_left[0] if prev_left else 43)
    left = [low]
    if bass == root and 7 in intervals:
        left.append(low + 7)
    pcs = sorted({(root + i) % 12 for i in intervals})
    if len(pcs) == 2:  # a power chord: root, fifth and the root again on top
        pcs = pcs + [pcs[0]]
    if len(pcs) > 4:
        pcs = [pc for pc in pcs if pc != (root + 7) % 12][:4]
    centre = sum(prev_right) / len(prev_right) if prev_right else 66
    best, best_cost = None, None
    for inversion in range(len(pcs)):
        order = pcs[inversion:] + pcs[:inversion]
        for bottom in range(RIGHT_LOW, RIGHT_HIGH - 4):
            if bottom % 12 != order[0]:
                continue
            chord, last = [bottom], bottom
            for pc in order[1:]:
                nxt = last + ((pc - last) % 12 or 12)
                chord.append(nxt)
                last = nxt
            if chord[-1] > RIGHT_HIGH + 2:
                continue
            if prev_right and len(prev_right) == len(chord):
                cost = sum(abs(a - b) for a, b in zip(chord, prev_right))
            else:
                cost = abs(sum(chord) / len(chord) - centre) * len(chord)
            if best_cost is None or cost < best_cost:
                best, best_cost = chord, cost
    return left, best or []


RIGHT_FINGERS = {1: [3], 2: [1, 5], 3: [1, 3, 5], 4: [1, 2, 3, 5]}
LEFT_FINGERS = {1: [5], 2: [5, 1], 3: [5, 3, 1]}
BPS = 2.0  # chord mode's beats a second: the page's notes are placed at stream seconds × BPS


def notes_for(segs: list[dict]) -> list[list]:
    """The falling notes for chord segments ({t0, t1, name, left, right} in stream seconds), as
    the coach page's roll takes them: [beat, length in beats, pitch, hand, finger]."""
    out = []
    for s in segs:
        if not s.get("name"):
            continue
        b = round(s["t0"] * BPS, 3)
        length = round(max(0.1, (s["t1"] - s["t0"]) * BPS - 0.05), 3)
        for hand, pitches, fingers in (("left", s["left"], LEFT_FINGERS), ("right", s["right"], RIGHT_FINGERS)):
            for p, f in zip(sorted(pitches), fingers.get(len(pitches), [1, 2, 3, 4, 5])):
                out.append([b, length, p, hand, f])
    return out


class ChordTracker:
    """Chords heard on the radio as it plays: settled ones, and the one still sounding."""

    def __init__(self) -> None:
        self.names = TRIADS
        self.source = "heard"   # 'heard' (the 24 triads) or 'chart' (the song's chart)
        self.settled: list[dict] = []
        self.pending: list[dict] = []

    def use(self, names: list[str] | None, source: str = "chart") -> None:
        """Choose among these chords from now on (None: the 24 triads)."""
        usable = [n for n in (names or []) if parse(n)]
        self.names, self.source = (usable, source) if usable else (TRIADS, "heard")

    def update(self, audio: chroma.AudioChroma) -> None:
        end = audio.end
        if end - audio.base < chroma.FPS:
            return
        settled_to = self.settled[-1]["f1"] if self.settled else audio.base
        start = max(audio.base, settled_to - int(REDO_SEC * chroma.FPS))
        # keep what's settled before the stretch being re-decided
        while self.settled and self.settled[-1]["f1"] > start:
            start = min(start, self.settled[-1]["f0"])
            self.settled.pop()
        frames, bass, loud, _ = audio.window(audio.time_of(start) - 1e-3, audio.time_of(end) + 1e-3, bass=True)
        segs = recognize(frames, bass, loud, self.names)
        before = (self.settled[-1]["left"], self.settled[-1]["right"]) if self.settled and self.settled[-1]["name"] else None
        done_by = end - int(LAG_SEC * chroma.FPS)
        self.pending = []
        for a, b, name in segs:
            f0, f1 = start + a, start + b
            left, right = voice(name, before) if name else ([], [])
            seg = {"f0": f0, "f1": f1, "name": name, "left": left, "right": right,
                   "t0": round(audio.time_of(f0) - 0.05, 3), "t1": round(audio.time_of(f1) - 0.05, 3)}
            if name:
                before = (left, right)
            if f1 <= done_by:
                if self.settled and self.settled[-1]["name"] == name and self.settled[-1]["f1"] == f0:
                    self.settled[-1].update(f1=f1, t1=seg["t1"])
                else:
                    self.settled.append(seg)
            else:
                self.pending.append(seg)
        if len(self.settled) > 400:
            del self.settled[:100]

    def recent(self, since: float, hold: float = 0.0) -> list[dict]:
        """Chords from stream second `since` on, settled then pending; with hold, the last one
        is held that much longer (it's still sounding: its end isn't known yet)."""
        keys = ("t0", "t1", "name", "left", "right")
        out = [{k: s[k] for k in keys} for s in self.settled + self.pending if s["t1"] >= since]
        if out and hold:
            out[-1]["t1"] = round(out[-1]["t1"] + hold, 3)
        return out

    @property
    def key(self) -> str:
        """Changes when the chords the page draws change (a chord settled, or the one still
        sounding was renamed), not each time the one still sounding grows."""
        tail = self.settled[-6:]  # each update re-decides the last few seconds, mostly the same way
        return ";".join(f"{s['f0']}{s['name']}" for s in tail) + ":" + "|".join(f"{s['f0']}{s['name']}" for s in self.pending)
