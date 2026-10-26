"""Batch-writing the lessons the templates can't: theory, one stage at a time, by Claude Code
on the pianist's subscription (claude_run).

Each stage gets one prompt (the grade, the topic, what the grade's other theory topics are,
what the stage is for) and answers in a fixed shape (LESSON_SCHEMA): read / quiz / play
steps, with any music written in tinyNotation. Everything is checked before it is saved:
  - the steps: types, lengths, quiz options and answer index, enough graded steps;
  - the music: built to MusicXML (lessons.build_lesson), every engraving rule passed
    (engraving.lint, full profile), and read back note for note;
and what fails goes back to the same session to be fixed (up to REPAIRS rounds). Lessons
are saved to <content>/lessons/<stage>.json marked checked: false ('Needs review' until
you've played or approved them), music to <content>/lessons/theory/, and each stage's run
to <content>/manifest.json. The batch is sequential and resumable: stages that already
have a lesson are skipped, and it stops cleanly at the account's usage limit.

    python -m midi_coach.atlas.generate --tiers initial,g1,g2 --dry-run
    python -m midi_coach.atlas.generate --tiers initial,g1,g2 [--limit N] [--node ID] [--force] [--model M]

The model is MIDI_COACH_GENERATOR_MODEL (default sonnet).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

from . import claude_run, content_dir, load_atlas

GENERATED_KINDS = ("theory",)
DEFAULT_MODEL = "sonnet"
REPAIRS = 2
MUSIC_FOLDER = "theory"

MUSIC = {"type": "object", "additionalProperties": False,
         "properties": {"right": {"type": "string"}, "left": {"type": "string"}, "time": {"type": "string"},
                        "key": {"type": "string"}, "bpm": {"type": "integer"}},
         "required": ["time", "key"]}
STEP = {"type": "object", "additionalProperties": False,
        "properties": {"type": {"type": "string", "enum": ["read", "quiz", "play"]},
                       "text": {"type": "string"}, "prompt": {"type": "string"},
                       "options": {"type": "array", "items": {"type": "string"}},
                       "answer": {"type": "integer"}, "accept": {"type": "array", "items": {"type": "string"}},
                       "explain": {"type": "string"}, "music": MUSIC,
                       "hand": {"type": "string", "enum": ["right", "left", "both"]},
                       "mode": {"type": "string", "enum": ["learn", "rehearse"]}},
        "required": ["type"]}
LESSON_SCHEMA = {"type": "object", "additionalProperties": False,
                 "properties": {"steps": {"type": "array", "items": STEP}}, "required": ["steps"]}

SYSTEM = """You write short lessons for a piano coach's skill tree, which follows a graded piano syllabus (ABRSM-style, British terms: crotchet, quaver, minim, semibreve, stave, bar). The learner is an adult on an 88-key digital piano; the coach hears what they play over MIDI and grades it, shows music on a scrolling sheet, and can play examples.

Every fact must be right: note names, key signatures, intervals, note values, terms. Keep to the stated topic and grade; don't use ideas from later grades. Plain, warm, exact language; short sentences.

A lesson is a list of steps:
- read: {"type": "read", "text": ...} - one idea, 1-4 sentences (at most 500 characters).
- quiz: {"type": "quiz", "prompt", "options" (2-4 short choices), "answer" (index of the right option, from 0), "accept" (words that count as the answer when said aloud, e.g. ["G"]), "explain" (one sentence on why), "music"?} - one right answer only; vary which position it's in. Add "music" when the question is about notation to read (it's shown on the sheet and can be played).
- play: {"type": "play", "music", "hand" (right / left / both), "mode" (learn: the coach waits for each note; rehearse: in time)} - something to play that uses the topic. Keep it short (2-8 bars) and easy for the grade.

Music is tinyNotation, one string per hand ("right" on the treble stave, "left" on the bass stave), with "time" (e.g. "4/4"), "key" (e.g. "G", "F", "Am", "D") and "bpm":
- pitches: c d e f g a b = the octave from middle C (c = C4); c' d' ... = the octave above; C D ... B = the octave below; CC = two below. Sharps f#, flats b- (b- is B flat), naturals bn; with octave marks the accidental comes after: c'#, B-.
- durations after the pitch: 1 semibreve, 2 minim, 4 crotchet, 8 quaver, 16 semiquaver; a dot after: g2. ; a duration stays until changed. Rests: r4, r2, r1.
- chords: chord{c4 e g}.
- Each bar must add up to the time signature; fill a hand's last bar with rests. Write accidentals that the key signature already gives too (f# in G major): the pitch is what you write.
- Keep the right hand between middle C and the C two octaves above (c to c''), the left hand between CC and middle C, so nothing needs many ledger lines (unless ledger lines are the topic).
- The pitch is what you write, even inside a bar: after f#, a plain f is F natural and is printed with a natural sign. To show an accidental carrying through the bar, write the sharp or flat again (f#4 g f# a); the sheet then prints it once.
- The music shows only notes, rests, clefs, key and time signatures: no dynamics, hairpins, slurs, ties, staccato dots or words. Never ask about a mark "shown" in the music; describe such marks in words instead.
- Describe sounds plainly (a step and a half, bright, settled); avoid clichés such as "Eastern" or "exotic".
"""

STAGE_BRIEF = {
    "learn": ("This is the topic's 'Learn it' stage: teach it, then check it. Write 2-3 read steps that teach the "
              "idea step by step, each followed by quiz steps about it: 5-6 quiz steps in all, the later ones a little "
              "harder. No play steps."),
    "keyboard": ("This is the topic's 'At the keyboard' stage, after the learner has learnt it: use it at the piano. "
                 "Write 1-2 read steps saying what to do and what to listen for, 1-2 quiz steps, and 2-3 play steps that "
                 "put the topic under the fingers (the first in learn mode, the last in rehearse mode). For a topic about "
                 "reading (clefs, note values, rests, time) the music should exercise exactly that."),
}


def model_name() -> str:
    return os.environ.get("MIDI_COACH_GENERATOR_MODEL") or DEFAULT_MODEL


def targets(atlas: dict, tiers: list[str], node: str | None = None, force: bool = False) -> list[dict]:
    """The stages to write: theory stages of these tiers without a lesson yet (or one node)."""
    folder = content_dir() / "lessons"
    out = []
    for n in atlas["nodes"]:
        if n["level"] != "stage" or n["kind"] not in GENERATED_KINDS:
            continue
        if node and node not in (n["id"], n["requirement"]):
            continue
        if not node and n["tier"] not in tiers:
            continue
        if force or not (folder / f"{n['id']}.json").exists():
            out.append(n)
    return out


def prompt_for(stage: dict, atlas: dict) -> str:
    by_id = atlas["by_id"]
    req = by_id[stage["requirement"]]
    tiers = {t["id"]: t for t in atlas["tiers"]}
    tier = tiers[stage["tier"]]
    same = [n["title"] for n in atlas["nodes"] if n["level"] == "requirement" and n["kind"] == "theory"
            and n["tier"] == stage["tier"] and n["id"] != req["id"]]
    earlier = [n["title"] for n in atlas["nodes"] if n["level"] == "requirement" and n["kind"] == "theory"
               and tiers[n["tier"]]["order"] < tier["order"]]
    key = stage["stage"]["key"]
    return "\n".join([
        f"Grade: {tier['title']}",
        f"Topic: {req['title']}",
        f"Earlier grades taught: {'; '.join(earlier) or 'nothing yet (this is the first grade)'}.",
        f"This grade's other theory topics: {'; '.join(same)}.",
        "",
        STAGE_BRIEF.get(key, STAGE_BRIEF["learn"]),
        *([f"This topic is a bridge the pianist's goal needs, beyond the syllabus. The brief: {req['brief']}"]
          if req.get("brief") else []),
        "",
        "Answer with the lesson's steps only.",
    ])


NOTE_NAME_RE = re.compile(r"^(?:middle\s+)?([a-g])\s*(sharp|flat|natural|♯|♭|#|b)?$", re.IGNORECASE)
ACCIDENTAL = {"sharp": "#", "♯": "#", "#": "#", "flat": "-", "♭": "-", "b": "-", "natural": "", None: ""}


def _named(option: str) -> str | None:
    """'F sharp' -> 'F#', 'Middle C' -> 'C', 'B♭' -> 'B-'; None if it isn't a note name."""
    m = NOTE_NAME_RE.match(option.strip())
    return m.group(1).upper() + ACCIDENTAL[(m.group(2) or "").lower() or None] if m else None


def _tiny_pitches(text: str, time_signature: str) -> list[int]:
    from ..lessons import _tiny

    out = []
    for n in _tiny(text, time_signature):
        if n.isRest:
            continue
        out += [p.midi for p in n.pitches]
    return sorted(out)


def _written_pitches(path: str) -> list:
    from music21 import converter

    return [p for n in converter.parse(path).flatten().notes for p in n.pitches]


def _spelled(p) -> str:
    """A music21 pitch as 'F#' / 'B-' / 'C' (no octave)."""
    return p.step + {"sharp": "#", "flat": "-"}.get(p.accidental.name if p.accidental else "", "")


def check(spec: dict | None, stage: dict, out_dir: pathlib.Path, req_title: str | None = None) -> tuple[list[dict], list[str], list[str]]:
    """The lesson's steps as saved (ids, files, pass rules), the problems found, and the
    music files written. Music is built and linted here."""
    from ..engraving import lint
    from ..lessons import build_lesson
    from ..notes import load_score

    errors: list[str] = []
    files: list[str] = []
    steps_in = (spec or {}).get("steps") or []
    key = stage["stage"]["key"]
    if not 3 <= len(steps_in) <= 12:
        errors.append(f"A lesson has 3-12 steps; this one has {len(steps_in)}.")
    kinds = [s.get("type") for s in steps_in]
    if key == "learn" and kinds.count("quiz") < 4:
        errors.append(f"The Learn stage needs at least 4 quiz steps; it has {kinds.count('quiz')}.")
    if key == "learn" and "play" in kinds:
        errors.append("The Learn stage has no play steps.")
    if key == "keyboard" and kinds.count("play") < 1:
        errors.append("The At-the-keyboard stage needs at least one play step.")
    if "read" not in kinds:
        errors.append("Start with a read step.")
    stem = stage["id"].replace(".", "-")
    req_title = req_title or load_atlas()["by_id"][stage["requirement"]]["title"]
    out: list[dict] = []
    counts: dict[str, int] = {}
    for k, s in enumerate(steps_in, 1):
        kind = s.get("type")
        counts[kind] = counts.get(kind, 0) + 1
        step: dict = {"id": f"{kind}-{counts[kind]}", "type": kind}
        where = f"Step {k} ({kind})"
        if kind == "read":
            text = (s.get("text") or "").strip()
            if not 20 <= len(text) <= 600:
                errors.append(f"{where}: the text should be 20-600 characters (it is {len(text)}).")
            step["text"] = text
        elif kind == "quiz":
            options = [str(o).strip() for o in s.get("options") or []]
            answer = s.get("answer")
            if not (s.get("prompt") or "").strip():
                errors.append(f"{where}: no prompt.")
            if not 2 <= len(options) <= 5 or len({o.lower() for o in options}) != len(options) or any(not o for o in options):
                errors.append(f"{where}: give 2-5 different, non-empty options.")
            if not isinstance(answer, int) or not 0 <= answer < len(options):
                errors.append(f"{where}: 'answer' must be the index (from 0) of one of the options.")
            accept = [str(a).strip() for a in s.get("accept") or [] if str(a).strip()]
            step.update(prompt=(s.get("prompt") or "").strip(), options=options, answer=answer,
                        accept=accept or ([options[answer]] if isinstance(answer, int) and 0 <= answer < len(options) else []),
                        graded=True)
            if s.get("explain"):
                step["explain"] = s["explain"].strip()
        elif kind == "play":
            if not s.get("music"):
                errors.append(f"{where}: a play step needs music.")
            step.update(hand=s.get("hand") or "both", mode=s.get("mode") or "learn", tempo_percent=100, graded=True)
            step["pass"] = ({"metric": "notes", "min": 90} if step["mode"] == "learn"
                            else {"metric": "overall", "min": 75, "tempo_min_pct": 70})
        else:
            errors.append(f"{where}: unknown step type {kind!r} (read, quiz or play).")
            continue
        music = s.get("music")
        title = req_title if kind == "quiz" else f"{req_title} · exercise {counts[kind]}"
        if music:
            right, left = (music.get("right") or "").strip(), (music.get("left") or "").strip()
            if kind == "play":
                hand = step["hand"]
                if (hand in ("right", "both") and not right) or (hand in ("left", "both") and not left):
                    errors.append(f"{where}: hand '{hand}' but the music has no {'right' if not right else 'left'}-hand part.")
            try:
                path, _ = build_lesson(title, right or None, left or None, music.get("time") or "4/4",
                                           music.get("key") or "C", music.get("bpm") or 72, out_dir=out_dir,
                                           filename=f"{stem}-{k}")
            except Exception as exc:
                errors.append(f"{where}: the music doesn't parse: {exc}")
                continue
            files.append(path)
            found = lint(path)
            for rule, part, bar, detail in found["findings"][:4]:
                errors.append(f"{where}: engraving rule '{rule}' broken ({part}, bar {bar}: {detail}).")
            try:
                wanted = sorted(_tiny_pitches(right, music.get("time") or "4/4") if right else []) + \
                    sorted(_tiny_pitches(left, music.get("time") or "4/4") if left else [])
                got = sorted(n.pitch for n in load_score(path).notes)
                if sorted(wanted) != got:
                    errors.append(f"{where}: the written music doesn't read back with the same notes "
                                  f"({len(wanted)} written, {len(got)} read back): check each bar adds up.")
            except Exception as exc:
                errors.append(f"{where}: the music doesn't read back: {exc}")
            if kind == "quiz" and isinstance(step.get("answer"), int) and 0 <= step["answer"] < len(step["options"]):
                # A note to name: the answer marked right must be the note written.
                right_name = _named(step["options"][step["answer"]])
                shown = {_spelled(p) for p in _written_pitches(path)}
                if right_name and len(shown) == 1 and right_name != next(iter(shown)):
                    errors.append(f"{where}: the music shows {next(iter(shown)).replace('-', ' flat').replace('#', ' sharp')}, "
                                  f"but the answer marked right is {step['options'][step['answer']]!r}.")
            rel = f"{MUSIC_FOLDER}/{pathlib.Path(path).name}"
            step["file"] = rel
            if kind == "quiz":
                step["score"] = rel
        out.append(step)
    return out, errors, files


def generate_stage(stage: dict, atlas: dict, model: str | None = None, run=claude_run.run,
                   lessons_dir: pathlib.Path | None = None) -> dict:
    """Write one stage's lesson: {status: ok | failed | usage_limit, rounds, errors?, cost_usd}."""
    model = model or model_name()
    lessons_dir = lessons_dir or content_dir() / "lessons"  # a goal's bridges: <home>/atlas/lessons
    out_dir = lessons_dir / MUSIC_FOLDER
    out = run(prompt_for(stage, atlas), model=model, schema=LESSON_SCHEMA, system=SYSTEM)
    cost, errors, files = 0.0, [], []
    for rnd in range(REPAIRS + 1):
        if out.get("error"):
            return {"status": "usage_limit" if out.get("usage_limit") else "failed", "error": out["error"],
                    "rounds": rnd, "cost_usd": round(cost, 4)}
        cost += out.get("cost_usd") or 0.0
        spec = out.get("structured")
        if spec is None:
            try:
                spec = json.loads(out.get("result") or "")
            except ValueError:
                spec = None
        for f in files:  # the last round's music, rewritten or left over
            pathlib.Path(f).unlink(missing_ok=True)
        steps, errors, files = check(spec, stage, out_dir, atlas["by_id"][stage["requirement"]]["title"])
        if not errors:
            lesson = {"id": stage["id"], "version": 1, "made": f"atlas.generate ({model})", "checked": False,
                      "requirement": stage["requirement"], "steps": steps}
            (lessons_dir / f"{stage['id']}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False),
                                                                          encoding="utf-8")
            return {"status": "ok", "rounds": rnd + 1, "files": [pathlib.Path(f).name for f in files], "cost_usd": round(cost, 4)}
        if rnd == REPAIRS:
            break
        out = run("These problems were found in your lesson:\n- " + "\n- ".join(errors)
                  + "\n\nSend the whole lesson again, corrected.", model=model, schema=LESSON_SCHEMA, system=SYSTEM,
                  resume=out.get("session_id"))
    for f in files:
        pathlib.Path(f).unlink(missing_ok=True)
    return {"status": "failed", "rounds": REPAIRS + 1, "errors": errors[:8], "cost_usd": round(cost, 4)}


def manifest_path() -> pathlib.Path:
    return content_dir() / "manifest.json"


def load_manifest() -> dict:
    try:
        return json.loads(manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"lessons": {}}


def batch(tiers: list[str], node: str | None = None, force: bool = False, limit: int | None = None,
          model: str | None = None, run=claude_run.run, log=print) -> dict:
    """Write the missing lessons one by one; stops at the usage limit. Returns a summary."""
    atlas = load_atlas()
    todo = targets(atlas, tiers, node, force)[:limit] if limit else targets(atlas, tiers, node, force)
    manifest = load_manifest()
    summary = {"todo": len(todo), "ok": 0, "failed": 0, "stopped": None, "cost_usd": 0.0}
    for k, stage in enumerate(todo, 1):
        started = time.time()
        result = generate_stage(stage, atlas, model, run)
        summary["cost_usd"] = round(summary["cost_usd"] + (result.get("cost_usd") or 0), 4)
        if result["status"] == "usage_limit":
            summary["stopped"] = result["error"]
            log(f"[{k}/{len(todo)}] {stage['id']}: usage limit reached - stopping. Run again later to carry on.")
            break
        manifest["lessons"][stage["id"]] = {**result, "model": model or model_name(), "when": time.strftime("%Y-%m-%d %H:%M:%S"),
                                            "seconds": round(time.time() - started), "checked": False}
        manifest_path().write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
        summary["ok" if result["status"] == "ok" else "failed"] += 1
        log(f"[{k}/{len(todo)}] {stage['id']}: {result['status']} in {result.get('rounds')} round(s)"
            + (f" - {result.get('errors') or result.get('error')}" if result["status"] != "ok" else ""))
    return summary


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m midi_coach.atlas.generate", description=__doc__.split("\n\n")[0])
    ap.add_argument("--tiers", default="initial,g1,g2")
    ap.add_argument("--node", help="one stage or requirement id")
    ap.add_argument("--force", action="store_true", help="rewrite lessons that exist")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model")
    ap.add_argument("--dry-run", action="store_true", help="list what would be written and show the first prompt")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    atlas = load_atlas()
    todo = targets(atlas, tiers, args.node, args.force)
    if args.dry_run:
        print(f"{len(todo)} stage lesson(s) to write with {args.model or model_name()}:")
        for n in todo:
            print(f"  {n['id']}  ({atlas['by_id'][n['requirement']]['title']} · {n['title']})")
        if todo:
            print("\nFirst prompt:\n" + prompt_for(todo[0], atlas))
        return 0
    summary = batch(tiers, args.node, args.force, args.limit, args.model)
    print(f"{summary['ok']} written, {summary['failed']} failed of {summary['todo']}"
          + (f"; stopped: {summary['stopped']}" if summary["stopped"] else "") + f" (list price ${summary['cost_usd']:.2f})")
    return 2 if summary["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
