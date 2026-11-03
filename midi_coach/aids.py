"""Labels on the sheet where the player needs them: note names and counting.

The coach page's Sheet ▸ Labels picks the level, like a game's difficulty: Easy labels every
bar, Hard none, and Coached (this module) puts them only on the bars you slip on and takes
them off again once you've played those bars clean. Labels are a crutch: the falling notes
with every key named are the quickest start but teach following lights, not reading, so the
help here goes as soon as it isn't needed.

What LiveSession reports (see live.py) decides which label a bar gets:
    pitch   a wrong key                              -> note names
    stuck   a long hunt for the next chord (Learn)  -> note names
    rhythm  the right key off the beat (Rehearse)    -> counting
and a rehearsal pass whose comparison finds a bar's timing loose adds counting there too.
Labels go on mid-pass as soon as a bar earns them (the sheet draws them over the score
without laying it out again) and come off between passes.
"""

from __future__ import annotations

from typing import Callable

from .notes import Score

KINDS = ("names", "counts")
FOR_SLIP = {"pitch": "names", "stuck": "names", "rhythm": "counts"}
ADD_AFTER = 2  # slips of one kind in a bar, in one pass, before the bar gets its label
CLEAR_AFTER = 2  # finished passes through a bar without that kind of slip before the label goes
LOOSE_TIMING_MS = 80  # a bar's timing spread (Rehearse comparison) that adds counting
LABEL_NAMES = {"names": "note names", "counts": "counting"}


class Aids:
    """Which bars of the piece being practiced carry which labels.

    push(bars) receives [{bar, start, end, kinds}] whenever that changes (DisplayHub.aids).
    The labels stay with the piece through a run of passes and reset when another piece
    starts; they aren't kept between sessions."""

    def __init__(self, push: Callable[[list[dict]], None] | None = None) -> None:
        self.push = push
        self.path: str | None = None
        self._score: Score | None = None
        self.labels: dict[str, dict[int, int]] = {k: {} for k in KINDS}  # bar -> clean passes since it got the label
        self._slips: dict[str, dict[int, int]] = {k: {} for k in KINDS}  # this pass
        self._covered: set[int] = set()
        self._added: dict[str, set[int]] = {k: set() for k in KINDS}

    def begin_pass(self, score: Score, bars: set[int]) -> None:
        """A graded pass over these bars of score starts."""
        self._score = score
        if score.path != self.path:
            self.path = score.path
            self.labels = {k: {} for k in KINDS}
        self._send()  # also puts them back after a mock exam hid them
        self._slips = {k: {} for k in KINDS}
        self._covered = set(bars)
        self._added = {k: set() for k in KINDS}

    def slip(self, bar: int, what: str, weight: int = 1) -> None:
        """LiveSession's report of one slip in a bar (what: pitch / stuck / rhythm)."""
        kind = FOR_SLIP.get(what)
        if kind is None or self._score is None:
            return
        n = self._slips[kind][bar] = self._slips[kind].get(bar, 0) + weight
        if bar in self.labels[kind]:
            self.labels[kind][bar] = 0  # slipped again: the clean passes start over
        elif n >= ADD_AFTER:
            self.labels[kind][bar] = 0
            self._added[kind].add(bar)
            self._send()

    def end_pass(self, finished: bool, summary: dict | None = None, report: dict | None = None) -> dict:
        """Close the pass: a rehearsal's loose bars get counting, and a finished pass counts as
        clean for each labeled bar it covered without that kind of slip. Returns
        {"added": {kind: [bars]}, "removed": {kind: [bars]}, "left": total labeled bars}."""
        if self._score is None or not self._covered:
            return {"added": {}, "removed": {}, "left": self.left}
        if summary and summary.get("mode") == "rehearsal" and report:
            for b in report.get("per_bar") or []:
                if (b.get("timing_ms") or 0) > LOOSE_TIMING_MS and b.get("bar") in self._covered:
                    self.slip(b["bar"], "rhythm", ADD_AFTER)
        removed: dict[str, list[int]] = {}
        if finished:
            for kind in KINDS:
                for bar in sorted(self.labels[kind]):
                    if bar not in self._covered or self._slips[kind].get(bar) or bar in self._added[kind]:
                        continue
                    self.labels[kind][bar] += 1
                    if self.labels[kind][bar] >= CLEAR_AFTER:
                        del self.labels[kind][bar]
                        removed.setdefault(kind, []).append(bar)
        if removed:
            self._send()
        added = {k: sorted(v) for k, v in self._added.items() if v}
        self._covered = set()
        return {"added": added, "removed": removed, "left": self.left}

    @property
    def left(self) -> int:
        return len({bar for kind in KINDS for bar in self.labels[kind]})

    def bars(self) -> list[dict]:
        """[{bar, start, end, kinds}] for the sheet, in beats like the heat map."""
        score = self._score
        if score is None or not score.bars:
            return []
        out = []
        for bar in sorted({b for kind in KINDS for b in self.labels[kind]}):
            if not score.bars[0].number <= bar <= score.bars[-1].number:
                continue
            b = score.bar(bar)
            out.append({"bar": bar, "start": round(b.start_beat, 4), "end": round(b.end_beat, 4),
                        "kinds": [k for k in KINDS if bar in self.labels[k]]})
        return out

    def _send(self) -> None:
        if self.push:
            self.push(self.bars())


def _bars_text(bars: list[int]) -> str:
    """'bar 5', 'bars 5 and 9', 'bars 5, 9 and 12'."""
    names = [str(b) for b in bars]
    if len(names) == 1:
        return "bar " + names[0]
    return "bars " + ", ".join(names[:-1]) + " and " + names[-1]


def remark(changes: dict) -> str | None:
    """What the Maestro says about labels it put on or took off in a pass, or None."""
    said = []
    for kind, bars in (changes.get("added") or {}).items():
        said.append(f"I've put {LABEL_NAMES[kind]} on {_bars_text(bars)}; play {'it' if len(bars) == 1 else 'them'} "
                    f"clean twice and {'it goes' if kind == 'counts' else 'they go'}.")
    removed = sorted({b for bars in (changes.get("removed") or {}).values() for b in bars})
    if removed:
        said.append(f"Labels off {_bars_text(removed)}: you've got {'it' if len(removed) == 1 else 'them'}.")
        if not changes.get("left"):
            said.append("No labels left on this piece. Try Hard under Sheet, Labels.")
    return " ".join(said) or None
