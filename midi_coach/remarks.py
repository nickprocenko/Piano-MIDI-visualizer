"""Spoken teacher remarks after each practice pass.

A strict piano teacher: one verdict, the specific thing that went wrong (the
note, the bar, the pulse), how it compares with the previous pass, and one
instruction. Wording is drawn from phrase pools and never repeats the last few
choices, so loop practice doesn't hear the same sentence twice. Criticism is
about the playing, never the player.
"""

from __future__ import annotations

import random
import re
import statistics

_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
_BLACK = {1, 3, 6, 8, 10}
_SHARPS = ["C", "C sharp", "D", "D sharp", "E", "F", "F sharp", "G", "G sharp", "A", "A sharp", "B"]
_FLATS = ["C", "D flat", "D", "E flat", "E", "F", "G flat", "G", "A flat", "A", "B flat", "B"]
_MIXED = ["C", "C sharp", "D", "E flat", "E", "F", "F sharp", "G", "A flat", "A", "B flat", "B"]
_NAME_RE = re.compile(r"^([A-G])([#b]?)(-?\d+)$")
_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# -- phrase pools --------------------------------------------------------------

VERDICT = {
    "clean": [
        "Clean.", "That's how it's done.", "Now we're talking.", "Good. Don't get comfortable.",
        "Clean pass. I'll take it.", "Accurate. Now make it effortless.", "Yes. That's the standard.",
        "Every note. Good.", "Solid.", "That's more like it.",
    ],
    "close": [
        "Close, but close isn't correct.", "Almost.", "Decent. Not finished.", "Better, but I heard that.",
        "Nearly there. Nearly isn't there.", "Not bad. Not good enough either.", "So close. Tidy it up.",
        "Good effort. Sloppy finish.",
    ],
    "shaky": [
        "Sloppy.", "No. That's guessing, not playing.", "Messy.", "That one fell apart.",
        "You're practising mistakes.", "Too many slips.", "That's not ready.", "Careless.",
    ],
    "rough": [
        "Stop. That was a train wreck.", "We're not there yet. Not even close.",
        "That's not practice, that's hoping.", "Way too many mistakes.", "No. Start over, slower.",
        "That was all over the place.", "That isn't learned yet.",
    ],
}
IMPROVED = ["Better than last time.", "That's progress.", "Improving.", "Better. Keep that direction."]
WORSE = ["Worse than the last one. Focus.", "You went backwards there.", "That slipped. Concentrate.",
         "Last pass was better. What changed?"]

ACCIDENTAL = [
    "Bar {bar}: that's {exp}, not {played}. Respect the key signature.",
    "{Exp}, not {played}, in bar {bar}.",
    "Bar {bar}. {Exp}! Not {played}.",
    "You played {played} in bar {bar}. The key says {exp}.",
]
ACCIDENTAL_AGAIN = [
    "You keep forgetting the {exp}. It's in the key signature for a reason.",
    "{Exp}. Again. That's the same mistake as last time.",
    "The {exp} in bar {bar}, again. Fix it in your head before your hands.",
]
WRONG_NOTE = [
    "In bar {bar} you hit {played} instead of {exp}.",
    "Bar {bar}: {played}? It's {exp}.",
    "Wrong note in bar {bar}. {Exp}, not {played}.",
]
HOT_BAR = [
    "Bar {bar} cost you {count}.", "Bar {bar} is where it falls apart.", "Bar {bar} is a mess.",
    "Bar {bar}. {Count}. That's your problem spot.", "Everything went wrong in bar {bar}.",
]
HOT_BAR_AGAIN = [
    "Bar {bar} again. That's {times} now.", "Bar {bar}, again. Stop running the whole thing and fix that bar.",
    "Same bar, same mistakes. Bar {bar}.",
]
STALL = [
    "You froze in bar {bar} for {secs} seconds. That's a bar you don't know yet.",
    "Bar {bar}: you stopped to think. Think before you play, not during.",
    "Too long in bar {bar}. Read ahead.", "You hesitated a long time in bar {bar}.",
]
FLAG = {
    "rushing": ["You rushed bar {bar}.", "Bar {bar} ran away from you.", "Bar {bar} was in a hurry. Why?"],
    "dragging": ["Bar {bar} dragged.", "You slowed down in bar {bar}.", "Bar {bar} lost the pulse."],
    "hesitation": ["You hesitated in bar {bar}.", "A stutter in bar {bar}.", "Bar {bar} wasn't confident."],
    "clipped notes": ["You're cutting the notes short in bar {bar}. Give them their full value.",
                      "Bar {bar} sounds choppy. Hold the notes."],
    "over-held": ["Notes in bar {bar} are smearing together. Lift on time.", "Bar {bar} is muddy. Release cleanly."],
    "pedal": ["Check your pedalling in bar {bar}.", "The pedal blurred bar {bar}."],
}
TIMING = ["Your pulse is uneven.", "The rhythm's wobbling.", "Uneven beats. I can hear every bump.",
          "Steady. The beat isn't negotiable."]
MISSED = ["You dropped {count}. Keep going, but don't skip.", "{Count} missing. Every note counts.",
          "You left out {count}."]

DIRECTIVE = {
    "accidental": ["Say the sharps out loud before you start.", "Look at the key signature before every pass.",
                   "Name the black keys in your head, then play.", "Slow down at that spot and think it."],
    "wrong": ["Read the note. Don't guess.", "Eyes on the score.", "Slow down and get it right."],
    "hot_bar": ["Isolate bar {bar}, slowly, five clean times in a row.",
                "Take bar {bar} hands separately until it's boring.",
                "Practise bar {bar} at half speed. Accuracy first, speed later.",
                "Loop bar {bar} until you can't get it wrong.",
                "Play bar {bar} three times clean, then put it back in context."],
    "stall": ["Prepare the next hand position before you need it.", "Eyes one beat ahead of your fingers.",
              "Know the fingering before you put your hands down.", "Practise the shift into bar {bar} on its own."],
    "rushing": ["Count out loud.", "Subdivide. One and two and.", "Put the metronome on and stay with it."],
    "dragging": ["Keep the pulse moving. Don't stop to fix things.", "Commit to the beat.",
                 "Count out loud and don't let it slow."],
    "timing": ["Even quarters, like a clock.", "Feel the beat before you start.", "Count a full bar in before you play."],
    "articulation": ["Listen to the length of every note.", "Listen to yourself, not just your fingers."],
    "missed": ["Don't skip notes to keep up. Slow the tempo instead.", "Every note, even at a slower tempo."],
    "clean": ["Again, and this time listen to your tone.", "Again. Make it even and musical.",
              "Now do it without looking at your hands.", "Again. Prove it wasn't luck.",
              "Again, and shape it this time.", "Once more, eyes on the music."],
    "streak": ["{Streak} clean in a row. Take the tempo up five percent.",
               "That's {streak} clean passes. Now try it from memory.",
               "{Streak} in a row. You've earned a faster tempo.", "{Streak} clean. Raise the bar: faster, or from memory."],
    "streak_learn": ["{Streak} clean in a row. Switch to Rehearse and play it in time.",
                     "That's {streak} clean. The notes are learned. Now Rehearse it at tempo.",
                     "{Streak} in a row. Stop waiting for the cursor and play it in time."],
    "rough": ["Slow down. Way down.", "Hands separately. Right now.", "Half tempo. Get it right, not fast.",
              "Go back to Learn mode until the notes are certain."],
    "close": ["Again.", "One more. Clean this time.", "From the top. Concentrate.", "Again, and fix it."],
}


# -- start and end of a run (the Maestro greets you and signs off) -------------

NPC_NAME = "Maestro"

GREET_NEW = [
    "{Title}. New piece. Let's see what you've got.", "Never heard you play {title}. Impress me.",
    "{Title}, first time. Nobody's perfect on day one. Try anyway.", "Ah, {title}. Fresh pages. Show me.",
]
GREET_BACK = [
    "{Title} again. Your best is {best}. Beat it.", "Back to {title}. Last time you topped out at {best}.",
    "{Title}. {Takes} so far, best {best}. Today we raise it.", "You and {title} again. Best score: {best}. I remember.",
]
GREET_AWAY = [
    "{Days} days since you touched {title}. Let's see what stuck.",
    "{Title}. It's been {days} days. Don't tell me you forgot it.",
]
GREET_KEY = [
    "{Count}: {names}. Keep them in your head.", "Remember the key. {Count}: {names}.",
    "{Names}. That's the key. Don't make me remind you twice.",
]
GREET_MODE = {
    "wait": ["Learn mode. Take your time, but get it right.", "The cursor will wait. Mistakes won't hide.",
             "Learn mode. Slow is fine. Wrong is not."],
    "rehearsal": ["{Tempo} percent. The cursor won't wait for you.", "Rehearse at {tempo} percent. Keep up.",
                  "{Tempo} percent, in time. Count yourself in."],
}
MILESTONE = {
    5: ["Pass five. Now it's practice.", "Five passes. Your hands are warming up."],
    10: ["Pass ten. Persistence. I respect that.", "Ten passes. This is how pianists are made."],
    20: ["Twenty passes. Go drink some water after this one.", "Pass twenty. Stubborn. Good."],
}
PERSONAL_BEST = ["New personal best on {title}! {score}.", "{Score}. That's a record for you on {title}.",
                 "Personal best. {Score}. Write that down."]
WRAP = [
    "{Passes} passes. Best was pass {best_pass}{best_score}.", "That's {passes} passes today. Pass {best_pass} was your best{best_score}.",
]
WRAP_WEAK = ["Bar {bar} is still your weak spot.", "Bar {bar} needs work tomorrow.", "Your homework is bar {bar}."]
WRAP_GOOD = ["Good session. Same time tomorrow.", "Remember this feeling. It's called progress.",
             "That's real progress. Rest your hands."]
WRAP_FLAT = ["Same time tomorrow.", "Go rest your hands. It settles overnight.", "Don't skip tomorrow."]

_FIFTHS_SHARPS = ["F", "C", "G", "D", "A", "E", "B"]
_FIFTHS_FLATS = ["B", "E", "A", "D", "G", "C", "F"]


def key_reminder(fifths: int | None) -> tuple[str, str] | None:
    """('two sharps', 'F sharp and C sharp') for a key signature, or None for C major / unknown."""
    if not fifths:
        return None
    k = min(abs(fifths), 7)
    letters = (_FIFTHS_SHARPS if fifths > 0 else _FIFTHS_FLATS)[:k]
    acc = "sharp" if fifths > 0 else "flat"
    names = [f"{x} {acc}" for x in letters]
    listed = names[0] if k == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{_num(k)} {acc}{'' if k == 1 else 's'}", listed


def _num(k: int) -> str:
    return _WORDS[k] if 0 <= k < len(_WORDS) else str(k)


def _num_or_digits(value) -> str:
    try:
        k = round(float(value))
    except (TypeError, ValueError):
        return "full"
    return _num(k) if k <= 10 else str(k)


def _count(k: int, word: str = "note") -> str:
    return f"{_num(k)} {word}{'' if k == 1 else 's'}"


def _times(k: int) -> str:
    return {1: "once", 2: "twice"}.get(k, f"{_num(k)} times")


def _pitch(name: str) -> int | None:
    m = _NAME_RE.match(name or "")
    if not m:
        return None
    pc = _LETTER_PC[m.group(1)] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    return pc + 12 * (int(m.group(3)) + 1)


def _slip(played: int, expected: list[int]) -> tuple[str, str, str] | None:
    """(kind, expected, played) spoken; 'accidental' when it's a semitone off around a black key."""
    if not expected:
        return None
    exp = min(expected, key=lambda e: abs(e - played))
    if abs(exp - played) == 1 and (exp % 12 in _BLACK) != (played % 12 in _BLACK):
        # Spell both on the same letter: F sharp vs F, B flat vs B.
        black, white = (exp, played) if exp % 12 in _BLACK else (played, exp)
        names = _SHARPS if black == white + 1 else _FLATS
        exp_name = names[exp % 12] + ("" if exp % 12 in _BLACK else " natural")
        return "accidental", exp_name, names[played % 12]
    return "wrong", _MIXED[exp % 12], _MIXED[played % 12]


class Coach:
    """Keeps the context of one practice run (previous passes, recent wording)."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.history: list[dict] = []
        self.context: dict = {}
        self._recent: dict[str, list[str]] = {}

    def reset(self) -> None:
        self.history.clear()
        self.context = {}

    def start(self, context: dict) -> str:
        """Begin a run and greet it. context: title, mode, tempo_percent, fifths (key signature),
        best_before (best earlier score on this piece and hand), takes_before, days_away."""
        self.reset()
        self.context = dict(context)
        title = context.get("title") or "this piece"
        best, takes, days = context.get("best_before"), context.get("takes_before") or 0, context.get("days_away")
        if days and days >= 2:
            parts = [self._pick("greet-away", GREET_AWAY, title=title, days=_num(days))]
        elif best is not None:
            parts = [self._pick("greet-back", GREET_BACK, title=title, best=str(best), takes=_count(takes, "take"))]
        else:
            parts = [self._pick("greet-new", GREET_NEW, title=title)]
        key = key_reminder(context.get("fifths"))
        if key and (best is None or self.rng.random() < 0.5):
            parts.append(self._pick("greet-key", GREET_KEY, count=key[0], names=key[1]))
        mode = context.get("mode")
        if mode in GREET_MODE:
            parts.append(self._pick("greet-" + mode, GREET_MODE[mode], tempo=_num_or_digits(context.get("tempo_percent"))))
        return " ".join(parts)

    def wrap_up(self) -> str | None:
        """Sign-off for a run of two or more finished passes."""
        if len(self.history) < 2:
            return None
        scored = [(i, h["score"]) for i, h in enumerate(self.history, 1) if h["score"] is not None]
        if scored:
            best_pass, best_score = max(scored, key=lambda p: p[1])
            score_text = f", {best_score}"
        else:
            best_pass = min(range(len(self.history)), key=lambda i: self.history[i]["errors"]) + 1
            score_text = ""
        parts = [self._pick("wrap", WRAP, passes=_num(len(self.history)), best_pass=_num(best_pass), best_score=score_text)]
        weak: dict[int, int] = {}
        for h in self.history:
            if h["hot_bar"]:
                weak[h["hot_bar"]] = weak.get(h["hot_bar"], 0) + h["hot_count"]
        if weak:
            parts.append(self._pick("wrap-weak", WRAP_WEAK, bar=max(weak, key=weak.get)))
        half = len(self.history) // 2
        early = statistics.fmean(h["errors"] for h in self.history[:half])
        late = statistics.fmean(h["errors"] for h in self.history[half:])
        good = late < early or all(h["grade"] == "clean" for h in self.history[half:])
        parts.append(self._pick("wrap-good" if good else "wrap-flat", WRAP_GOOD if good else WRAP_FLAT))
        return " ".join(parts)

    def _pick(self, pool_key: str, options: list[str], **values) -> str:
        recent = self._recent.setdefault(pool_key, [])
        fresh = [o for o in options if o not in recent] or options
        choice = self.rng.choice(fresh)
        recent.append(choice)
        del recent[: max(0, len(recent) - min(4, len(options) - 1))]
        caps = {k[:1].upper() + k[1:]: (v[:1].upper() + v[1:] if isinstance(v, str) else v) for k, v in values.items()}
        return choice.format(**values, **caps)

    # -- facts -----------------------------------------------------------------

    @staticmethod
    def _facts(summary: dict, report: dict | None) -> dict:
        wait = summary.get("mode") == "wait"
        total = max(1, summary.get("notes_total") or 0)
        wrong = summary.get("wrong_presses") or 0
        missed = 0 if wait else summary.get("missed") or 0
        per_bar = summary.get("per_bar") or {}
        hot = max(per_bar.items(), key=lambda kv: kv[1].get("wrong", 0) + kv[1].get("missed", 0), default=None)
        hot_count = hot[1].get("wrong", 0) + hot[1].get("missed", 0) if hot else 0
        stall = None
        if wait and len(per_bar) > 1:
            waits = [v["wait_sec"] for v in per_bar.values() if v.get("wait_sec")]
            med = statistics.median(waits) if waits else 0
            bar, v = max(per_bar.items(), key=lambda kv: kv[1].get("wait_sec", 0))
            if v.get("wait_sec", 0) > max(2.0, 2.2 * med):
                stall = (int(bar), v["wait_sec"])
        slip = None
        for s in summary.get("slips") or []:
            found = _slip(s["played"], s["expected"])
            if found:
                slip = (found, s["bar"])
                if found[0] == "accidental":
                    break
        if slip is None and report:
            for m in report.get("mistakes") or []:
                if m.get("type") == "wrong":
                    exp, played = _pitch(m.get("expected", "")), _pitch(m.get("played", ""))
                    if exp is not None and played is not None:
                        slip = (_slip(played, [exp]), m["bar"])
                        break
        flag = None
        if report and not wait:
            for b in report.get("worst_bars") or []:
                for f in b.get("flags") or []:
                    if f in FLAG:
                        flag = (f, b["bar"])
                        break
                if flag:
                    break
        timing_ms = (report or {}).get("timing", {}).get("median_error_ms") if not wait else None
        score = ((report or {}).get("scores") or {}).get("overall")
        accuracy = (summary.get("hits") or 0) / total
        errors = wrong + missed
        if errors == 0 and not stall:
            grade = "clean"
        elif accuracy >= 0.9 and errors <= 3:
            grade = "close"
        elif accuracy >= 0.75:
            grade = "shaky"
        else:
            grade = "rough"
        return {
            "grade": grade, "errors": errors, "missed": missed, "accuracy": accuracy, "score": score,
            "hot_bar": int(hot[0]) if hot and hot_count else None, "hot_count": hot_count,
            "stall": stall, "slip": slip, "flag": flag, "timing_ms": timing_ms,
        }

    # -- remark ----------------------------------------------------------------

    def remark(self, summary: dict | None, report: dict | None = None) -> str | None:
        if not summary or not summary.get("notes_total"):
            return None
        f = self._facts(summary, report)
        prev = self.history[-1] if self.history else None
        self.history.append(f)
        streak = 0
        for h in reversed(self.history):
            if h["grade"] != "clean":
                break
            streak += 1

        parts = []
        # Beating the best from earlier sessions is announced once per run.
        best = self.context.get("best_before")
        if f["score"] is not None and best is not None and f["score"] > best and not self.context.get("pb_said"):
            parts.append(self._pick("pb", PERSONAL_BEST, title=self.context.get("title") or "this piece", score=str(f["score"])))
            self.context["pb_said"] = True
        if len(self.history) in MILESTONE:
            parts.append(self._pick(f"milestone-{len(self.history)}", MILESTONE[len(self.history)]))
        parts.append(self._pick("verdict-" + f["grade"], VERDICT[f["grade"]]))
        if prev and f["grade"] != "clean":
            if f["errors"] < prev["errors"]:
                parts.append(self._pick("improved", IMPROVED))
            elif f["errors"] > prev["errors"] + 1:
                parts.append(self._pick("worse", WORSE))

        # The one thing worth naming, most instructive first.
        issue, bar = None, None
        slip, hot = f["slip"], f["hot_bar"]
        if slip and slip[0][0] == "accidental":
            (_, exp, played), bar = slip
            same = prev and prev["slip"] and prev["slip"][0] == slip[0]
            parts.append(self._pick("acc-again" if same else "acc", ACCIDENTAL_AGAIN if same else ACCIDENTAL,
                                    exp=exp, played=played, bar=bar))
            issue = "accidental"
        elif hot and prev and prev["hot_bar"] == hot and max(f["hot_count"], prev["hot_count"]) >= 2:
            times = 1 + sum(1 for h in self.history[:-1] if h["hot_bar"] == hot)
            parts.append(self._pick("hot-again", HOT_BAR_AGAIN, bar=hot, times=_times(times)))
            issue, bar = "hot_bar", hot
        elif f["stall"] and (not hot or f["hot_count"] < 2):
            bar, secs = f["stall"]
            parts.append(self._pick("stall", STALL, bar=bar, secs=_num(round(secs))))
            issue = "stall"
        elif hot and f["hot_count"] >= 2:
            parts.append(self._pick("hot", HOT_BAR, bar=hot, count=_count(f["hot_count"])))
            issue, bar = "hot_bar", hot
        elif slip:
            (_, exp, played), bar = slip
            parts.append(self._pick("wrong", WRONG_NOTE, exp=exp, played=played, bar=bar))
            issue = "wrong"
        elif f["flag"]:
            flag, bar = f["flag"]
            parts.append(self._pick("flag-" + flag, FLAG[flag], bar=bar))
            issue = {"rushing": "rushing", "dragging": "dragging", "hesitation": "stall"}.get(flag, "articulation")
        elif f["timing_ms"] and f["timing_ms"] > 60:
            parts.append(self._pick("timing", TIMING))
            issue = "timing"
        elif f["missed"] >= 2:
            parts.append(self._pick("missed", MISSED, count=_count(f["missed"])))
            issue = "missed"

        if f["grade"] == "clean" and f["score"] is not None and self.rng.random() < 0.4:
            parts.append(f"{f['score']} out of 100.")
        elif f["grade"] in ("close", "shaky") and f["errors"] and self.rng.random() < 0.35:
            parts.append(f"{_count(f['errors'], 'mistake').capitalize()}.")

        if f["grade"] == "clean" and not issue:
            if streak >= 2:
                pool = "streak_learn" if summary.get("mode") == "wait" and streak >= 3 else "streak"
                parts.append(self._pick(pool, DIRECTIVE[pool], streak=_num(streak)))
            else:
                parts.append(self._pick("clean", DIRECTIVE["clean"]))
        elif f["grade"] == "rough" and issue not in ("hot_bar", "accidental"):
            parts.append(self._pick("rough", DIRECTIVE["rough"]))
        elif issue:
            parts.append(self._pick("dir-" + issue, DIRECTIVE[issue], bar=bar))
        else:
            parts.append(self._pick("close", DIRECTIVE["close"]))
        return " ".join(parts)
