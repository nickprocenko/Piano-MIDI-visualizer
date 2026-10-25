"""Voice chat with the Maestro: you talk, Claude answers in character and runs the practice.

Claude Haiku 5.5 handles conversation and commands (start, loop, tempo, stop, play a
passage, progress); writing a new lesson is handed to Claude Sonnet 5.5, and questions that
need real teaching to Claude Code on the pianist's subscription (hand_off, see deep.py).

Needs an Anthropic API key, from ANTHROPIC_API_KEY or the file
%USERPROFILE%\\MidiCoach\\anthropic_api_key.txt. Every request is metered from its token
usage into %USERPROFILE%\\MidiCoach\\ai_spend.json, and a daily cap
(MIDI_COACH_DAILY_CAP, default $0.50) stops further calls for the day.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from .library import home

log = logging.getLogger("midi-coach")

CHAT_MODEL = "claude-haiku-5-5"
LESSON_MODEL = "claude-sonnet-5-5"
# $ per million tokens (input, output). Cache reads bill at 0.1x input, 5-minute cache writes at 1.25x.
PRICES = {CHAT_MODEL: (0.10, 0.50), LESSON_MODEL: (2.00, 10.00)}
DEFAULT_DAILY_CAP = 0.50
MAX_TOOL_ROUNDS = 5
NEW_CONVERSATION_AFTER_SEC = 20 * 60
NEW_CONVERSATION_AFTER_MESSAGES = 40

SYSTEM = """\
You are the Maestro, the piano teacher character in a practice app. The pianist talks to you \
by voice while sitting at their keyboard (a Roland JUNO-DS), and your replies are spoken aloud \
by a text-to-speech voice and shown in a game-style dialogue box.

Character: a teacher who clearly wants the pianist to get better, in the teaching style the \
context names. Warm: encouraging and patient, says what went well before what to fix, never \
sarcastic. Strict: dry-humoured and demanding, praises only what was earned. Either way be \
specific (the bar, the note, the hand) and criticise the playing, never the person. Use the \
words teachers use: isolate the bar, slow practice, count out loud, hands separately, eyes \
ahead, steady pulse, clean repetitions. If the pianist asks you to be gentler or tougher, use \
set_style.

Speech rules: one to three short sentences. Plain spoken words only: no lists, markdown, \
emoji or symbols. Say "bar five", "eighty percent", "F sharp". This is latency-sensitive: \
begin your answer immediately.

You can't hear the keyboard directly. Each message starts with a [Practice context] block \
describing the lesson on screen, whether a run is going, recent passes and the pianist's \
history. Only quote scores and numbers that appear there; never invent them.

Use your tools when the pianist asks you to do something (start, loop, change tempo or hand, \
stop, play a passage for them, switch or write a lesson, check progress), then confirm \
briefly what you did. Learn mode waits for the right notes; Rehearse mode moves at the tempo. \
If they ask for something outside piano practice, answer briefly and steer back to the piano.

Anything that needs real teaching, more than your three sentences, goes to hand_off: a spoken \
lesson on the song or a section of it, how to play a hard passage, a song's background, music \
theory, a practice plan. So does "ask Desktop", "go deeper", or "next section" during such a \
lesson. Then just say you'll think it over; the answer comes in your voice shortly.

The context may include your notebook on the pianist. When they tell you something worth \
keeping (a goal, a piece they're learning, how they like to be taught), use remember.\
"""

TOOLS = [
    {
        "name": "start_practice",
        "description": "Start a practice run on the lesson currently on screen. Replaces any run "
                       "in progress. Bars and tempo apply to this run only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["learn", "rehearse"],
                         "description": "learn: the cursor waits for the right notes. rehearse: moves at tempo."},
                "hand": {"type": "string", "enum": ["both", "right", "left"]},
                "bars": {"type": "string", "description": "Bar range like '5-8', or empty for the whole lesson."},
                "tempo_percent": {"type": "integer", "description": "Rehearse speed, 30-150. Default 100."},
                "loop": {"type": "boolean", "description": "Restart automatically after each completed pass."},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "stop_practice",
        "description": "Stop the current practice run.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "play_passage",
        "description": "Play the lesson on screen through the keyboard so the pianist can hear "
                       "how it should sound.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bars": {"type": "string", "description": "Bar range like '1-4', or empty for all."},
                "hand": {"type": "string", "enum": ["both", "right", "left"]},
                "tempo_percent": {"type": "integer", "description": "Playback speed, 30-150. Default 100."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "progress",
        "description": "The pianist's score history on the lesson on screen: recent scores, and "
                       "bars that improved or keep going wrong.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "switch_lesson",
        "description": "Show a different saved lesson or piece, found by name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Title or part of it, e.g. 'C major scale'."}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_lesson",
        "description": "Compose a new practice exercise (scale, arpeggio, drill on a problem "
                       "bar...) and put it on screen. A specialist composer writes it, which "
                       "takes several seconds; tell the pianist it's coming.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "What to write, with key, hands, length and "
                                                             "difficulty if the pianist said them."},
            },
            "required": ["request"],
            "additionalProperties": False,
        },
    },
    {
        "name": "hand_off",
        "description": "Pass a question that needs real teaching to the senior teacher (Claude on the "
                       "pianist's own subscription, with the keyboard, score and your voice), who "
                       "answers aloud as you within about a minute. If it can't, the question is "
                       "saved for Claude Desktop; the result says which.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The pianist's question in full, with what it "
                                                              "refers to (lesson, bars, hand) spelled out from the context."},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remember",
        "description": "Add one lasting fact about the pianist to your notebook (goals, pieces, weak "
                       "spots, preferences). Not for things that only matter today.",
        "input_schema": {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "One short line."}},
            "required": ["note"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_style",
        "description": "Change how you coach from now on, including the remarks after each pass. "
                       "warm: encouraging and patient. strict: dry and demanding.",
        "input_schema": {
            "type": "object",
            "properties": {"style": {"type": "string", "enum": ["warm", "strict"]}},
            "required": ["style"],
            "additionalProperties": False,
        },
    },
]

LESSON_SYSTEM = """\
You compose short piano practice exercises for a practice app. Call create_lesson exactly once \
with the finished exercise. Write each hand in music21 tinyNotation, in its own clef \
(right = treble, left = bass):
- Pitches: c d e f g a b = C4 to B4; c' = C5, c'' = C6; C = C3, CC = C2.
- Accidentals after the octave marks: f# (F#4), b- (Bb4), c'# (C#5) - never c#'.
- Durations after the pitch: 1 whole, 2 half, 4 quarter, 8 eighth, 16; dots c4.; a note \
without a number repeats the previous duration. Rests r4. Ties c2~ c8. Chords chord{C2 E G} \
(duration on the first note). Triplets trip{c8 d e}.
- Fill every bar of the time signature exactly in both hands; use rests for a silent hand \
(e.g. hands separate: right hand plays bars 1-4 while the left has r1 r1 r1 r1, then swap).
If the tool reports an error, fix the notation and call it again.\
"""

CREATE_LESSON_TOOL = {
    "name": "create_lesson",
    "description": "Validate, save and show the exercise. Returns a bar-by-bar readout or an error.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "right": {"type": "string", "description": "Right hand tinyNotation, or empty."},
            "left": {"type": "string", "description": "Left hand tinyNotation, or empty."},
            "time_signature": {"type": "string", "description": "e.g. '4/4'"},
            "key": {"type": "string", "description": "'C', 'G', 'Bb', 'F#m' (minor with m)..."},
            "tempo_bpm": {"type": "integer"},
        },
        "required": ["title", "right", "left", "time_signature", "key", "tempo_bpm"],
        "additionalProperties": False,
    },
}


class Unavailable(RuntimeError):
    pass


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip()
    path = home() / "anthropic_api_key.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip() or None
    return None


def daily_cap() -> float:
    try:
        return float(os.environ.get("MIDI_COACH_DAILY_CAP") or DEFAULT_DAILY_CAP)
    except ValueError:
        return DEFAULT_DAILY_CAP


def request_cost(model: str, usage) -> float:
    price_in, price_out = PRICES.get(model, PRICES[LESSON_MODEL])
    fresh = getattr(usage, "input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return (fresh * price_in + written * price_in * 1.25 + read * price_in * 0.1 + out * price_out) / 1_000_000


class Ledger:
    """Dollars spent per day, kept on disk so the cap survives restarts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _path(self):
        return home() / "ai_spend.json"

    def _load(self) -> dict:
        try:
            return json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def today(self) -> float:
        with self._lock:
            return float(self._load().get(time.strftime("%Y-%m-%d"), 0.0))

    def add(self, dollars: float) -> float:
        with self._lock:
            data = self._load()
            day = time.strftime("%Y-%m-%d")
            data[day] = round(float(data.get(day, 0.0)) + dollars, 6)
            data["total"] = round(float(data.get("total", 0.0)) + dollars, 6)
            self._path().write_text(json.dumps(data, indent=1), encoding="utf-8")
            return data[day]


class VoiceChat:
    """One ongoing conversation with the Maestro.

    actions: name -> callable(**tool_input) -> dict, for every tool in TOOLS except
    write_lesson, plus 'create_lesson' (used by the lesson writer).
    context: callable() -> str describing the practice right now.
    """

    def __init__(self, actions: dict, context, client=None) -> None:
        self.actions = actions
        self.context = context
        self._client = client
        self.ledger = Ledger()
        self.messages: list = []
        self._last_turn = 0.0
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if self._client is not None:
            return True, ""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "The anthropic package isn't installed (pip install anthropic)."
        if not api_key():
            return False, f"No API key. Put it in {home() / 'anthropic_api_key.txt'} or set ANTHROPIC_API_KEY."
        return True, ""

    def status(self) -> dict:
        ok, why = self.available()
        return {"available": ok, "reason": why, "spent_today": round(self.ledger.today(), 4), "cap": daily_cap()}

    def client(self):
        if self._client is None:
            ok, why = self.available()
            if not ok:
                raise Unavailable(why)
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key())
        return self._client

    def _meter(self, model: str, response) -> float:
        cost = request_cost(model, response.usage)
        self.ledger.add(cost)
        return cost

    def ask(self, said: str) -> dict:
        """Answer what the pianist said. Returns {reply, cost, actions, spent_today}."""
        said = " ".join((said or "").split())
        if not said:
            return {"error": "I didn't catch anything."}
        if not self._lock.acquire(blocking=False):
            return {"error": "Still answering the last thing you said."}
        try:
            return self._ask(said)
        finally:
            self._lock.release()

    def _ask(self, said: str) -> dict:
        if self.ledger.today() >= daily_cap():
            return {"reply": "That's enough talking for today. We've hit the daily budget. Play, don't chat.",
                    "cost": 0.0, "actions": [], "spent_today": self.ledger.today(), "capped": True}
        # Start a fresh conversation after a break or a long chat. Earlier turns are never
        # edited: that would invalidate the replayed thinking blocks.
        if time.time() - self._last_turn > NEW_CONVERSATION_AFTER_SEC or len(self.messages) > NEW_CONVERSATION_AFTER_MESSAGES:
            self.messages = []
        self._last_turn = time.time()
        self.messages.append({"role": "user", "content": f"[Practice context]\n{self.context()}\n\n[The pianist said]\n{said}"})
        cost, done = 0.0, []
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client().messages.create(
                model=CHAT_MODEL,
                max_tokens=2000,
                system=SYSTEM,
                tools=TOOLS,
                messages=self.messages,
                output_config={"effort": "low"},
                cache_control={"type": "ephemeral"},
            )
            cost += self._meter(CHAT_MODEL, response)
            if response.stop_reason == "refusal":
                self.messages = []  # start over rather than edit the history
                reply = "Let's keep this about the piano."
                break
            self.messages.append({"role": "assistant", "content": response.content})
            reply = " ".join(b.text for b in response.content if b.type == "text").strip() or reply
            uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not uses:
                break
            results = []
            for use in uses:
                out, extra = self._run_tool(use.name, dict(use.input or {}))
                cost += extra
                done.append(use.name)
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": json.dumps(out, default=str)[:4000],
                                **({"is_error": True} if isinstance(out, dict) and "error" in out else {})})
            self.messages.append({"role": "user", "content": results})
        return {"reply": reply or "Hm.", "cost": round(cost, 5), "actions": done, "spent_today": round(self.ledger.today(), 4)}

    def _run_tool(self, name: str, args: dict) -> tuple[dict, float]:
        try:
            if name == "write_lesson":
                return self._write_lesson(args.get("request", ""))
            action = self.actions.get(name)
            if action is None:
                return {"error": f"unknown tool {name}"}, 0.0
            return action(**args), 0.0
        except Exception as exc:  # the model gets the error and can explain it
            log.warning("voice tool %s failed: %s", name, exc)
            return {"error": str(exc)}, 0.0

    def _write_lesson(self, request: str) -> tuple[dict, float]:
        if self.ledger.today() >= daily_cap():
            return {"error": "Daily AI budget reached; no lesson writing today."}, 0.0
        messages = [{"role": "user", "content": f"{request}\n\nCurrent practice, for reference:\n{self.context()}"}]
        cost = 0.0
        for _ in range(3):
            response = self.client().beta.messages.create(
                model=LESSON_MODEL,
                max_tokens=8000,
                system=LESSON_SYSTEM,
                tools=[CREATE_LESSON_TOOL],
                messages=messages,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            cost += self._meter(LESSON_MODEL, response)
            if response.stop_reason == "refusal":
                return {"error": "The composer declined that request."}, cost
            uses = [b for b in response.content if b.type == "tool_use" and b.name == "create_lesson"]
            if not uses:
                return {"error": "The composer didn't write a lesson."}, cost
            messages.append({"role": "assistant", "content": response.content})
            results, created = [], None
            for use in uses:
                try:
                    out = self.actions["create_lesson"](**dict(use.input))
                except Exception as exc:
                    out = {"error": str(exc)}
                if "error" not in out and created is None:
                    created = out
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": json.dumps(out, default=str)[:6000],
                                **({"is_error": True} if "error" in out else {})})
            if created:
                return {"created": created.get("path"), "bars": created.get("bars"), "on_screen": True}, cost
            messages.append({"role": "user", "content": results})
        return {"error": "The composer couldn't get the notation right."}, cost
