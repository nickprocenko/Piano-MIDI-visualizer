"""Getting to know you: where a new pianist starts on the Atlas, from a few friendly questions.

Not an exam. First come questions about you (have you played, can you read music, any exams
passed, why you're learning, how much time you have), then a handful of light music checks
(higher or lower, a note on the stave, beats in a minim), which the page asks one at a time
and can play or draw. The answers pick a starting tier:
  - an exam you've passed starts you at the grade after it;
  - otherwise reading and the checks decide, from First steps up to Grade 2 (higher than
    that, the Mock exams link under Where to start is the way to show it).
Every tier below the start is credited ('placement_credit' events, as placement.py does),
and the start tier becomes the goal. A flute or saxophone profile is asked about its
instrument, and reads a treble G (its first note) in place of the bass-clef check; a singer
reads middle C (do), a fiddler the open A, a guitarist the open top E (written E5) and a
bassist the open A in the bass clef. Their Roadmaps have no tiers below First notes, so someone brand new
starts there. The answers are kept in <home>/atlas/welcome.json, so
the Maestro knows why you're learning and how long you like to practice.
"""

from __future__ import annotations

import json
import pathlib

from .. import profiles
from . import load_atlas, store, user_dir

PLAYED = ["Never, I'm brand new", "A little, for a few weeks or months", "Yes, but years ago", "Yes, I play regularly"]
READING = ["Not yet", "Slowly, one note at a time", "Yes, simple pieces", "Yes, comfortably"]
EXAMS = ["No", "Initial", "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6", "Grade 7", "Grade 8"]
EXAM_TIERS = [None, "initial", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"]
WHY = ["Playing songs I love", "Reading music", "Taking grade exams", "Relaxing and having fun", "Playing with other people"]
TIME = ["5 minutes", "10 minutes", "15 minutes", "20 minutes or more"]

# kind: 'about' (no right answer) or 'check' (answer: the right option). tones: MIDI notes the
# page plays one after the other; staff: a note the page draws ({clef, midi}).
QUESTIONS = [
    {"id": "played", "kind": "about", "prompt": "Have you played the piano before?", "options": PLAYED},
    {"id": "reading", "kind": "about", "prompt": "Can you read sheet music?", "options": READING},
    {"id": "exams", "kind": "about", "prompt": "Have you passed a piano exam? Any exam board counts.", "options": EXAMS},
    {"id": "why", "kind": "about", "multi": True, "prompt": "What brings you to the piano? Pick as many as you like.",
     "options": WHY},
    {"id": "time", "kind": "about", "prompt": "How long could you practice on most days?", "options": TIME},
    {"id": "high", "kind": "check", "prompt": "Listen: is the second note higher or lower?", "tones": [60, 67],
     "options": ["Higher", "Lower", "The same"], "answer": 0},
    {"id": "low", "kind": "check", "prompt": "And this time?", "tones": [69, 62],
     "options": ["Higher", "Lower", "The same"], "answer": 1},
    {"id": "e4", "kind": "check", "prompt": "Which note is this?", "staff": {"clef": "treble", "midi": 64},
     "options": ["C", "E", "G", "B"], "answer": 1},
    {"id": "minim", "kind": "check", "prompt": "How many crotchet (quarter-note) beats does a minim (half note) last?",
     "options": ["One", "Two", "Three", "Four"], "answer": 1},
    {"id": "piano", "kind": "check", "prompt": "What does p (piano) mean in the music?",
     "options": ["Quiet", "Loud", "Fast", "Slow"], "answer": 0},
    {"id": "c5", "kind": "check", "prompt": "Which note is this?", "staff": {"clef": "treble", "midi": 72},
     "options": ["A", "F", "C", "D"], "answer": 2},
    {"id": "three", "kind": "check", "prompt": "In 3/4 time, how many beats are in each bar?",
     "options": ["Two", "Three", "Four", "Six"], "answer": 1},
    {"id": "f3", "kind": "check", "prompt": "This one is in the bass clef. Which note is it?", "staff": {"clef": "bass", "midi": 53},
     "options": ["A", "B", "D", "F"], "answer": 3},
    {"id": "gmajor", "kind": "check", "prompt": "A key signature of one sharp, F sharp, is usually which major key?",
     "options": ["C major", "G major", "D major", "F major"], "answer": 1},
]
CHECKS = [q["id"] for q in QUESTIONS if q["kind"] == "check"]

FLUTE_PROMPTS = {
    "played": "Have you played the flute before?",
    "exams": "Have you passed a flute exam? Any exam board counts.",
    "why": "What brings you to the flute? Pick as many as you like.",
}
FLUTE_CHECK = {"id": "g4", "kind": "check", "prompt": "Which note is this? It's the first one you'll play on the flute.",
               "staff": {"clef": "treble", "midi": 67}, "options": ["E", "B", "G", "D"], "answer": 2}
SAX_PROMPTS = {
    "played": "Have you played the saxophone before?",
    "exams": "Have you passed a saxophone exam? Any exam board counts.",
    "why": "What brings you to the saxophone? Pick as many as you like.",
}
SAX_CHECK = {**FLUTE_CHECK, "prompt": "Which note is this? It's the first one you'll play on the saxophone."}
VOICE_PROMPTS = {
    "played": "Have you had singing lessons or sung in a choir before?",
    "exams": "Have you passed a singing exam? Any exam board counts.",
    "why": "What brings you to singing? Pick as many as you like.",
}
VOICE_CHECK = {"id": "c4", "kind": "check", "prompt": "Which note is this? It's the first one you'll sing: do.",
               "staff": {"clef": "treble", "midi": 60}, "options": ["C", "E", "A", "D"], "answer": 0}
FIDDLE_PROMPTS = {
    "played": "Have you played the fiddle or violin before?",
    "exams": "Have you passed a violin or fiddle exam? Any exam board counts.",
    "why": "What brings you to the fiddle? Pick as many as you like.",
}
FIDDLE_CHECK = {"id": "a4", "kind": "check", "prompt": "Which note is this? It's your open A string, the first you'll play.",
                "staff": {"clef": "treble", "midi": 69}, "options": ["F", "A", "C", "E"], "answer": 1}
GUITAR_PROMPTS = {
    "played": "Have you played the guitar before?",
    "exams": "Have you passed a guitar exam? Any exam board counts.",
    "why": "What brings you to the guitar? Pick as many as you like.",
}
GUITAR_CHECK = {"id": "e5", "kind": "check", "prompt": "Which note is this? It's the open top E string, the first you'll play.",
                "staff": {"clef": "treble", "midi": 76}, "options": ["C", "G", "E", "D"], "answer": 2}
BASS_PROMPTS = {
    "played": "Have you played the bass guitar before?",
    "exams": "Have you passed a bass guitar exam? Any exam board counts.",
    "why": "What brings you to the bass? Pick as many as you like.",
}
BASS_CHECK = {"id": "a2", "kind": "check", "prompt": "Which note is this? It's your open A string.",
              "staff": {"clef": "bass", "midi": 45}, "options": ["C", "F", "A", "E"], "answer": 2}
# Each microphone instrument: its wording of the questions, and the note check that replaces the bass clef's.
WORDING = {"flute": (FLUTE_PROMPTS, FLUTE_CHECK), "sax": (SAX_PROMPTS, SAX_CHECK), "voice": (VOICE_PROMPTS, VOICE_CHECK),
           "fiddle": (FIDDLE_PROMPTS, FIDDLE_CHECK), "guitar": (GUITAR_PROMPTS, GUITAR_CHECK), "bass": (BASS_PROMPTS, BASS_CHECK)}

# Where reading and the checks start you, by tier order (First steps -2 ... Grade 2).
TARGET_ORDER = {"first": -2, "ready": -1, "initial": 0, "g1": 1, "g2": 2}


def path() -> pathlib.Path:
    return user_dir() / "welcome.json"


def load() -> dict | None:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def questions(instrument: str | None = None) -> list[dict]:
    """For the page, answers included: a check shows the right answer straight away. Worded
    for the active profile's instrument."""
    wording = WORDING.get(instrument or profiles.instrument())
    if not wording:
        return QUESTIONS
    prompts, check = wording
    return [check if q["id"] == "f3" else {**q, "prompt": prompts.get(q["id"], q["prompt"])} for q in QUESTIONS]


def correct(answers: dict) -> int:
    checks = QUESTIONS + [FLUTE_CHECK, VOICE_CHECK, FIDDLE_CHECK, GUITAR_CHECK, BASS_CHECK]  # the sax's is the flute's, reworded
    return sum(1 for q in checks if q["kind"] == "check" and answers.get(q["id"]) == q["answer"])


def skips_checks(answers: dict) -> bool:
    """Brand new and not reading yet: no checks, straight to First steps (the page skips them)."""
    return answers.get("played") == 0 and answers.get("reading") == 0


def start_tier(answers: dict) -> str | None:
    """The tier id to start at (piano ids; placed() maps it onto the profile's tree), or None
    for beyond Grade 8."""
    exam = answers.get("exams") or 0
    if exam:
        return EXAM_TIERS[exam + 1] if exam + 1 < len(EXAM_TIERS) else None
    reading, played, score = answers.get("reading") or 0, answers.get("played") or 0, correct(answers)
    if reading == 0:
        return "first" if played == 0 else "ready"
    if reading == 1:
        return "initial" if score >= 5 else "ready"
    if reading == 2:
        return "g1" if score >= 7 else "initial"
    return "g2" if score >= 8 else "g1"


def placed(answers: dict, tiers: list[dict]) -> tuple[str | None, list[str]]:
    """(start tier, tiers credited) on this tree: the target, or the nearest tier below it."""
    tiers = sorted(tiers, key=lambda t: t["order"])
    target = start_tier(answers)
    if target is None:
        return None, [t["id"] for t in tiers]
    ids = {t["id"] for t in tiers}
    if target not in ids:
        order = TARGET_ORDER.get(target, int(target[1:]) if target[1:].isdigit() else 0)
        below = [t for t in tiers if t["order"] <= order]
        target = (below[-1] if below else tiers[0])["id"]
    top = next(t["order"] for t in tiers if t["id"] == target)
    return target, [t["id"] for t in tiers if t["order"] < top]


def finish(answers: dict) -> dict:
    """Credit the tiers below the start, make the start tier the goal, keep the answers.
    Returns {tier, tier_title, credited, credited_titles, goal, correct, of, summary}."""
    from .placement import _set_goal

    atlas = load_atlas()
    titles = {t["id"]: t["title"] for t in atlas["tiers"]}
    tier, credited = placed(answers, atlas["tiers"])
    when = store.now()
    for t in credited:
        store.append_event("placement_credit", tier=t, placement=f"welcome {when}")
    goal = None
    if tier:
        target = f"{tier}.exam" if f"{tier}.exam" in atlas["by_id"] else tier
        goal = _set_goal(tier, [], target=target, source="welcome", activate=not store.load_goals().get("active"))
    out = {"tier": tier, "tier_title": titles.get(tier), "credited": credited,
           "credited_titles": [titles[t] for t in credited], "goal": goal,
           "correct": correct(answers), "of": 0 if skips_checks(answers) else len(CHECKS)}
    out["summary"] = summary(out)
    path().write_text(json.dumps({"answers": answers, "result": out, "finished": when}, indent=1, ensure_ascii=False),
                      encoding="utf-8")
    return out


def summary(out: dict) -> str:
    if not out["tier"]:
        return "Wow, past Grade 8! Every grade is marked as done, so the whole map is yours to explore."
    said = f"You're starting at {out['tier_title']}!"
    done = out["credited_titles"]
    if len(done) > 1:
        said += f" {done[0]} to {done[-1]} are marked as done."
    elif done:
        said += f" {done[0]} is marked as done."
    return said + " Your path is ready in the Planner."


def about_line() -> str | None:
    """One line for the Maestro's context: why they're learning and how long they practice."""
    data = load()
    if not data:
        return None
    a = data.get("answers") or {}
    why = [WHY[k] for k in a.get("why") or [] if isinstance(k, int) and 0 <= k < len(WHY)]
    time = TIME[a["time"]] if isinstance(a.get("time"), int) and 0 <= a["time"] < len(TIME) else None
    parts = []
    if why:
        parts.append("learning for: " + ", ".join(w[:1].lower() + w[1:] for w in why))
    if time:
        parts.append(f"has about {time} a day")
    return ("Getting to know you: " + "; ".join(parts) + ".") if parts else None
