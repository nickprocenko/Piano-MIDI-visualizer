"""The Maestro's autopilot ("Maestro decides" on the coach page).

Between loop passes it changes the practice the way a teacher would and says what it did.
After each finished pass, counting only the passes since its last change, the first rule
that fits wins:

- two rough passes in a row with both hands: right hand alone, then left, then both
- the same problem bar in the last two passes: loop it with a bar either side
- a rough pass in Rehearse: tempo down 10% (not below 50%)
- looping a problem bar, three clean passes: back to the whole section
- one hand alone, two clean passes: the next hand
- Learn, three clean passes in a row: Rehearse at 70%
- Rehearse, three clean passes in a row: tempo up 5% (up to 100%)

The last change can be undone ("no", "undo"), which also restarts the count.
"""

from __future__ import annotations

KEYS = ("mode", "hand", "bars", "tempo_percent")
TEMPO_STEP_UP, TEMPO_STEP_DOWN, TEMPO_FLOOR, TEMPO_TOP = 5, 10, 50, 100
REHEARSE_FROM_LEARN = 70
CLEAN_TO_ADVANCE, CLEAN_PER_HAND, ROUGH_FOR_HANDS = 3, 2, 2


def _range(bars: str | None, last_bar: int) -> tuple[int, int]:
    if bars:
        lo, _, hi = str(bars).partition("-")
        try:
            lo_n = int(lo)
            return lo_n, min(last_bar, int(hi or lo))
        except ValueError:
            pass
    return 1, last_bar


def _bars_text(bars: str | None, last_bar: int) -> str:
    lo, hi = _range(bars, last_bar)
    if (lo, hi) == (1, last_bar):
        return "the whole piece"
    return f"bar {lo}" if lo == hi else f"bars {lo} to {hi}"


class Autopilot:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.base: dict = {}
        self.focus: int | None = None  # the problem bar being looped
        self.hands: str | None = None  # 'right' / 'left' while taking the hands separately
        self.since = 0  # passes before this index are from before the last change
        self._passes = 0
        self._undo: tuple[dict, dict, str] | None = None

    def start(self, settings: dict) -> None:
        """A new run: remember the section you chose, to come back to after a bar loop."""
        self.reset()
        self.base = {k: settings.get(k) for k in KEYS}

    def decide(self, history: list[dict], settings: dict, last_bar: int) -> tuple[dict, str] | None:
        """After a finished pass: (setting changes, what to say) or None. history: the
        Coach's per-pass facts (grade, hot_bar, ...), the latest last."""
        recent = history[self.since:]
        if not recent:
            return None
        self._passes = len(history)
        mode, hand = settings.get("mode"), settings.get("hand") or "both"
        tempo = round(float(settings.get("tempo_percent") or 100))
        grades = [h["grade"] for h in recent]

        def tail(grade: str, n: int) -> bool:
            return len(grades) >= n and all(g == grade for g in grades[-n:])

        if hand == "both" and tail("rough", ROUGH_FOR_HANDS):
            return self._change(settings, {"hand": "right"}, "That's too much at once; right hand alone for a few passes.",
                                hands="right")
        hot = recent[-1].get("hot_bar")
        lo, hi = _range(self.base.get("bars"), last_bar)
        if (self.focus is None and hot and len(recent) >= 2 and recent[-2].get("hot_bar") == hot
                and hi - lo > 2 and lo <= hot <= hi):
            a, b = max(lo, hot - 1), min(hi, hot + 1)
            return self._change(settings, {"bars": f"{a}-{b}"}, f"Let's loop bars {a} to {b} for a while.", focus=hot)
        if mode == "rehearsal" and grades[-1] == "rough" and tempo > TEMPO_FLOOR:
            new = max(TEMPO_FLOOR, tempo - TEMPO_STEP_DOWN)
            return self._change(settings, {"tempo_percent": new}, f"Let's slow it to {new} percent.")
        if self.focus is not None and tail("clean", CLEAN_TO_ADVANCE):
            back = self.base.get("bars")
            return self._change(settings, {"bars": back}, f"Bar {self.focus} is clean; back to {_bars_text(back, last_bar)}.",
                                focus=None)
        if self.hands and tail("clean", CLEAN_PER_HAND):
            if self.hands == "right":
                return self._change(settings, {"hand": "left"}, "Good; now the left hand alone.", hands="left")
            return self._change(settings, {"hand": "both"}, "Now both hands together.", hands=None)
        if mode == "wait" and tail("clean", CLEAN_TO_ADVANCE):
            return self._change(settings, {"mode": "rehearsal", "tempo_percent": REHEARSE_FROM_LEARN},
                                f"The notes are learned; let's Rehearse it at {REHEARSE_FROM_LEARN} percent.")
        if mode == "rehearsal" and tail("clean", CLEAN_TO_ADVANCE) and tempo < TEMPO_TOP:
            new = min(TEMPO_TOP, tempo + TEMPO_STEP_UP)
            return self._change(settings, {"tempo_percent": new}, f"Tempo up to {new} percent.")
        return None

    def _change(self, settings: dict, changes: dict, said: str, **state) -> tuple[dict, str]:
        before = {k: settings.get(k) for k in changes}
        self._undo = (before, {"focus": self.focus, "hands": self.hands}, said)
        for k, v in state.items():
            setattr(self, k, v)
        self.since = self._passes  # count from the next pass
        return changes, said

    def undo(self, passes: int) -> dict | None:
        """Reverse the last change: the settings to put back, or None if there is none."""
        if self._undo is None:
            return None
        before, state, _ = self._undo
        self._undo = None
        self.focus, self.hands = state["focus"], state["hands"]
        self.since = passes
        return before

    @property
    def can_undo(self) -> bool:
        return self._undo is not None
