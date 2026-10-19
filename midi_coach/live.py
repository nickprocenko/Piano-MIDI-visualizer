"""Synthesia-style live practice modes, judged while the user plays.

wait       The cursor holds on each chord until every note of it is played
           (like Synthesia's Melody Practice). Wrong keys flash; time spent
           stuck on each bar is recorded.
rehearsal  The cursor moves at a fixed tempo (tempo_percent of the score) once
           the first note is played, and notes are graded hit / missed as they
           pass (like Synthesia's Song Recital).

Judgement happens here, in Python, so every display (coach page, visualizer)
just renders the events pushed through DisplayHub.
"""

from __future__ import annotations

import bisect
import statistics
import threading
import time

from .analysis import REF_GROUP_TOL, group_onsets
from .display import DisplayHub
from .notes import Note, Score, note_name

HIT_WINDOW_SEC = 0.2
MODES = ("wait", "rehearsal")


class LiveSession:
    def __init__(self, mode: str, score: Score, ref_notes: list[Note], hub: DisplayHub | None, tempo_percent: float = 100.0) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode
        self.score = score
        self.hub = hub
        self.speed = max(0.1, tempo_percent / 100)
        self.groups = group_onsets(ref_notes, REF_GROUP_TOL)
        self.notes = sorted(ref_notes, key=lambda n: (n.start, n.pitch))
        self._lock = threading.Lock()
        self.done_reason: str | None = None
        self.hits = 0
        self.misses = 0
        self.wrong = 0
        self.bar_stats: dict[int, dict] = {}
        # wait mode
        self._idx = 0
        self._pending: dict[int, list[Note]] = {}
        self._hit_now: set[int] = set()
        self._group_started: float | None = None
        # rehearsal mode
        self._clock: float | None = None
        self._status_note: dict[int, str] = {}
        self._ticker: threading.Thread | None = None
        self._stop = threading.Event()
        # reference seconds -> beats, for the cursor
        self._sec = [g.onset for g in self.groups]
        self._beat = [min(n.beat for n in g.notes) for g in self.groups]

    # -- helpers -------------------------------------------------------------

    def _bar(self, ref_t: float) -> int:
        return self.score.position(ref_t)[0]

    def _stat(self, bar: int) -> dict:
        return self.bar_stats.setdefault(bar, {"wrong": 0, "missed": 0, "hits": 0, "wait_sec": 0.0})

    def beat_at(self, ref_t: float) -> tuple[float, float]:
        """(beat, beats per reference second) at a reference time."""
        xs, ys = self._sec, self._beat
        if len(xs) < 2:
            return (ys[0] if ys else 0.0), 0.0
        i = max(1, min(len(xs) - 1, bisect.bisect_right(xs, ref_t)))
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        slope = (y1 - y0) / (x1 - x0) if x1 > x0 else 0.0
        return y0 + slope * (ref_t - x0), slope

    def _status(self) -> None:
        if not self.hub:
            return
        total = len(self.notes)
        if self.mode == "wait":
            bar = self._bar(self.groups[min(self._idx, len(self.groups) - 1)].onset) if self.groups else 1
            text = f"Wait mode · bar {bar} · {self.hits}/{total} notes · {self.wrong} wrong"
        elif self._clock is None:
            text = f"Rehearsal {round(self.speed * 100)}% · play the first note to start"
        else:
            text = f"Rehearsal {round(self.speed * 100)}% · {self.hits} hit · {self.misses} missed · {self.wrong} wrong"
        if self.done_reason:
            text += " · finished"
        self.hub.status(text)

    def _set_group(self, idx: int, now: float) -> None:
        self._idx = idx
        self._hit_now = set()
        self._pending = {}
        if idx >= len(self.groups):
            return
        g = self.groups[idx]
        for n in g.notes:
            self._pending.setdefault(n.pitch, []).append(n)
        self._group_started = now
        if self.hub:
            self.hub.marks([(n.beat, n.pitch, "pending") for n in g.notes])
            self.hub.cursor(self._beat[idx])

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if not self.groups:
            self.done_reason = "nothing to play"
            return
        if self.hub:
            self.hub.marks([], reset=True)
            self.hub.heat(None)
        now = time.perf_counter()
        if self.mode == "wait":
            self._set_group(0, now)
            self._group_started = None  # don't count time before the first note
        else:
            if self.hub:
                first = self.groups[0]
                self.hub.marks([(n.beat, n.pitch, "pending") for n in first.notes])
                self.hub.cursor(self._beat[0])
            self._ticker = threading.Thread(target=self._tick, daemon=True)
            self._ticker.start()
        self._status()

    def stop(self) -> None:
        self._stop.set()

    def should_stop(self) -> str | None:
        return self.done_reason

    # -- input -----------------------------------------------------------------

    def on_message(self, now: float, message: list[int]) -> None:
        if len(message) < 3 or message[0] & 0xF0 != 0x90 or message[2] == 0:
            return
        with self._lock:
            if self.done_reason:
                return
            if self.mode == "wait":
                self._wait_note(now, message[1])
            else:
                self._rehearsal_note(now, message[1])

    def _wait_note(self, now: float, pitch: int) -> None:
        if self._group_started is None:
            self._group_started = now
        g = self.groups[self._idx]
        if pitch in self._pending:
            hit = self._pending.pop(pitch)
            self._hit_now.add(pitch)
            self.hits += len(hit)
            self._stat(self._bar(g.onset))["hits"] += len(hit)
            if self.hub:
                self.hub.marks([(n.beat, n.pitch, "hit") for n in hit])
            if not self._pending:
                self._stat(self._bar(g.onset))["wait_sec"] += now - self._group_started
                if self._idx + 1 >= len(self.groups):
                    self.done_reason = "finished the piece"
                    self._idx += 1
                else:
                    self._set_group(self._idx + 1, now)
            self._status()
        elif pitch not in self._hit_now:
            self.wrong += 1
            self._stat(self._bar(g.onset))["wrong"] += 1
            if self.hub:
                self.hub.flash(note_name(pitch))
            self._status()

    def _real(self, n: Note) -> float:
        return self._clock + (n.start - self.groups[0].onset) / self.speed

    def _rehearsal_note(self, now: float, pitch: int) -> None:
        if self._clock is None:
            first = self.groups[0]
            if pitch not in {n.pitch for n in first.notes}:
                return  # noodling before the start doesn't count
            self._clock = now
        candidates = [
            n for n in self.notes
            if n.pitch == pitch and id(n) not in self._status_note and abs(self._real(n) - now) <= HIT_WINDOW_SEC
        ]
        if candidates:
            n = min(candidates, key=lambda c: abs(self._real(c) - now))
            self._status_note[id(n)] = "hit"
            self.hits += 1
            self._stat(self._bar(n.start))["hits"] += 1
            if self.hub:
                self.hub.marks([(n.beat, n.pitch, "hit")])
        else:
            ref_t = self.groups[0].onset + (now - self._clock) * self.speed
            self.wrong += 1
            self._stat(self._bar(ref_t))["wrong"] += 1
            if self.hub:
                self.hub.flash(note_name(pitch))
        self._status()

    def _tick(self) -> None:
        last_cursor = 0.0
        end_ref = max(n.end for n in self.notes)
        while not self._stop.wait(0.05):
            now = time.perf_counter()
            with self._lock:
                if self._clock is None or self.done_reason:
                    continue
                missed = []
                for n in self.notes:
                    if id(n) in self._status_note:
                        continue
                    if self._real(n) + HIT_WINDOW_SEC < now:
                        self._status_note[id(n)] = "missed"
                        self.misses += 1
                        self._stat(self._bar(n.start))["missed"] += 1
                        missed.append((n.beat, n.pitch, "missed"))
                    else:
                        break  # notes are time-sorted
                ref_t = self.groups[0].onset + (now - self._clock) * self.speed
                if self.hub and missed:
                    self.hub.marks(missed)
                if missed:
                    self._status()
                if self.hub and now - last_cursor >= 0.25:
                    beat, slope = self.beat_at(ref_t)
                    self.hub.cursor(beat, slope * self.speed)
                    last_cursor = now
                if ref_t > end_ref + 1.0 * self.speed:
                    self.done_reason = "reached the end"
                    self._status()

    # -- results -----------------------------------------------------------------

    def summary(self) -> dict:
        with self._lock:
            waits = [s["wait_sec"] for s in self.bar_stats.values() if s["wait_sec"] > 0]
            return {
                "mode": self.mode,
                "tempo_percent": round(self.speed * 100),
                "hits": self.hits,
                "missed": self.misses,
                "wrong_presses": self.wrong,
                "notes_total": len(self.notes),
                "median_bar_wait_sec": round(statistics.median(waits), 2) if waits else None,
                "per_bar": {str(k): {**v, "wait_sec": round(v["wait_sec"], 2)} for k, v in sorted(self.bar_stats.items())},
            }


def heat_from_live(score: Score, summary: dict) -> list[dict]:
    """Heat-map bars from a live session summary (wait or rehearsal)."""
    per_bar = summary.get("per_bar", {})
    waits = [v["wait_sec"] for v in per_bar.values() if v.get("wait_sec")]
    median_wait = statistics.median(waits) if waits else 0.0
    out = []
    for key, v in per_bar.items():
        bar = int(key)
        sev = 2 * v.get("wrong", 0) + 2 * v.get("missed", 0)
        label_parts = []
        if v.get("wrong"):
            label_parts.append(f"{v['wrong']} wrong")
        if v.get("missed"):
            label_parts.append(f"{v['missed']} missed")
        if summary.get("mode") == "wait" and median_wait > 0 and v.get("wait_sec", 0) > 1.8 * median_wait:
            sev += 2
            label_parts.append(f"slow {v['wait_sec']:.0f}s")
        out.append(_heat_bar(score, bar, sev, label_parts))
    return [b for b in out if b]


def heat_from_comparison(score: Score, per_bar: list[dict]) -> list[dict]:
    out = []
    for b in per_bar:
        sev = 2 * (b["wrong"] + b["missed"]) + b["extra"] + (1 if (b.get("timing_ms") or 0) > 60 else 0)
        parts = [f"{b[k]} {k}" for k in ("wrong", "missed", "extra") if b[k]]
        if (b.get("timing_ms") or 0) > 60:
            parts.append(f"±{b['timing_ms']}ms")
        out.append(_heat_bar(score, b["bar"], sev, parts))
    return [b for b in out if b]


def _heat_bar(score: Score, bar: int, severity: float, parts: list[str]) -> dict | None:
    if not 1 <= bar <= len(score.bars):
        return None
    b = score.bars[bar - 1]
    return {
        "bar": bar,
        "start": round(b.start_beat, 4),
        "end": round(b.end_beat, 4),
        "value": round(min(1.0, severity / 6), 3),
        "label": ", ".join(parts) if parts else "clean",
    }
