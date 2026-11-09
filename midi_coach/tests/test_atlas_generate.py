"""Batch lesson writing with a fake Claude Code: a repair round, stopping at the usage limit
and carrying on, and the runner's command line and output parsing."""

from __future__ import annotations

import json
import types

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import claude_run, generate
from midi_coach.tests.test_atlas import home, tree  # noqa: F401  (fixtures)

GOOD_LEARN = {"steps": [
    {"type": "read", "text": "The treble clef curls around the G line, the second line up."},
    {"type": "quiz", "prompt": "Which line does the treble clef curl around?", "options": ["E", "G", "B"], "answer": 1,
     "accept": ["G"], "explain": "The treble clef is a G clef."},
    {"type": "quiz", "prompt": "What is this note?", "options": ["F", "G", "A"], "answer": 1,
     "music": {"right": "g2 r2", "time": "4/4", "key": "C", "bpm": 72}},
    {"type": "quiz", "prompt": "Middle C sits...", "options": ["on a ledger line below", "on the bottom line"], "answer": 0},
    {"type": "quiz", "prompt": "The top line is...", "options": ["F", "E", "D"], "answer": 0},
]}
GOOD_KEYS = {"steps": [
    {"type": "read", "text": "Play these notes slowly, saying each name as you go."},
    {"type": "quiz", "prompt": "The first note is...", "options": ["C", "D"], "answer": 0},
    {"type": "play", "hand": "right", "mode": "learn", "music": {"right": "c4 d e f g1", "time": "4/4", "key": "C", "bpm": 72}},
    {"type": "play", "hand": "right", "mode": "rehearse", "music": {"right": "g4 f e d c1", "time": "4/4", "key": "C", "bpm": 72}},
]}


@pytest.fixture()
def content(home, tree):  # noqa: F811
    folder = atlas_pkg.content_dir()
    (folder / "lessons").mkdir(parents=True)
    (folder / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    return folder


class FakeClaude:
    """Answers each prompt from a script: a list of results, or a function of the call."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    def __call__(self, prompt, model, schema=None, system=None, tools="", resume=None, **_):
        self.calls.append({"prompt": prompt, "resume": resume, "schema": schema})
        return self.answer(self, prompt, resume)


def _good_for(prompt: str) -> dict:
    return GOOD_KEYS if "At the keyboard" in prompt else GOOD_LEARN


def test_a_flawed_lesson_is_repaired_then_saved(content):
    stage = next(s for s in generate.targets(atlas_pkg.load_atlas(), ["initial"]) if s["stage"]["key"] == "learn")
    bad = json.loads(json.dumps(GOOD_LEARN))
    bad["steps"][1]["answer"] = 7                                    # no such option
    bad["steps"][2]["music"]["right"] = "g2 r4 G,4"                   # tinyNotation drops 'G,'

    def answer(fake, prompt, resume):
        if resume is None:
            return {"structured": bad, "session_id": "s1", "cost_usd": 0.02}
        assert resume == "s1" and "'answer' must be the index" in prompt and "doesn't parse" in prompt
        return {"structured": GOOD_LEARN, "session_id": "s1", "cost_usd": 0.01}

    fake = FakeClaude(answer)
    result = generate.generate_stage(stage, atlas_pkg.load_atlas(), "sonnet", fake)
    assert result["status"] == "ok" and result["rounds"] == 2, result
    assert fake.calls[0]["schema"] == generate.LESSON_SCHEMA and "Topic:" in fake.calls[0]["prompt"]
    lesson = json.loads((content / "lessons" / f"{stage['id']}.json").read_text(encoding="utf-8"))
    assert lesson["checked"] is False and lesson["made"] == "atlas.generate (sonnet)"
    quiz = lesson["steps"][2]
    assert quiz["id"] == "quiz-2" and quiz["score"] == quiz["file"] and (content / "lessons" / quiz["file"]).is_file()
    assert [s["type"] for s in lesson["steps"]] == ["read", "quiz", "quiz", "quiz", "quiz"]
    assert len(list((content / "lessons" / "theory").glob("*.musicxml"))) == 1  # the failed round's files are gone


def test_a_lesson_that_cant_be_fixed_is_not_saved(content):
    stage = next(s for s in generate.targets(atlas_pkg.load_atlas(), ["initial"]) if s["stage"]["key"] == "keyboard")
    no_play = {"steps": [{"type": "read", "text": "Just read about it, nothing to play here."}]}
    fake = FakeClaude(lambda fake, prompt, resume: {"structured": no_play, "session_id": "s2"})
    result = generate.generate_stage(stage, atlas_pkg.load_atlas(), "sonnet", fake)
    assert result["status"] == "failed" and len(fake.calls) == 1 + generate.REPAIRS
    assert any("at least one play step" in e for e in result["errors"])
    assert not (content / "lessons" / f"{stage['id']}.json").exists()


def test_batch_stops_at_the_usage_limit_and_carries_on_later(content):
    todo = generate.targets(atlas_pkg.load_atlas(), ["initial", "g1"])
    assert len(todo) >= 3 and all(s["kind"] == "theory" for s in todo)

    def limited(fake, prompt, resume):
        if len(fake.calls) == 2:
            return {"error": "Claude AI usage limit reached|1761500000", "usage_limit": True}
        return {"structured": _good_for(prompt), "session_id": f"s{len(fake.calls)}", "cost_usd": 0.01}

    lines: list[str] = []
    first = generate.batch(["initial", "g1"], run=FakeClaude(limited), log=lines.append)
    assert first["ok"] == 1 and first["stopped"] and "usage limit" in lines[-1]
    assert len(generate.load_manifest()["lessons"]) == 1

    later = FakeClaude(lambda fake, prompt, resume: {"structured": _good_for(prompt), "session_id": "x", "cost_usd": 0.01})
    second = generate.batch(["initial", "g1"], run=later, log=lines.append)
    assert second["todo"] == len(todo) - 1 and second["ok"] == len(todo) - 1 and not second["stopped"]
    assert generate.targets(atlas_pkg.load_atlas(), ["initial", "g1"]) == []
    manifest = generate.load_manifest()["lessons"]
    assert len(manifest) == len(todo) and all(m["status"] == "ok" and m["checked"] is False for m in manifest.values())


def test_runner_command_and_output(home):  # noqa: F811
    cmd = claude_run.command("sonnet", schema={"type": "object"}, system="Be exact.", resume="abc")
    assert cmd[1] == "-p" and cmd[-2:] == ["--resume", "abc"] and "--json-schema" in cmd and cmd[cmd.index("--tools") + 1] == ""

    def fake_run(stdout, code=0):
        return lambda *a, **k: types.SimpleNamespace(stdout=stdout, stderr="", returncode=code)

    ok = claude_run.run("hi", "sonnet", runner=fake_run(json.dumps(
        {"is_error": False, "result": "{}", "structured_output": {"steps": []}, "session_id": "s", "total_cost_usd": 0.1})))
    assert ok == {"result": "{}", "structured": {"steps": []}, "session_id": "s", "cost_usd": 0.1}
    limited = claude_run.run("hi", "sonnet", runner=fake_run(json.dumps(
        {"is_error": True, "result": "You've hit your usage limit · resets 5pm", "session_id": "s"}), 1))
    assert limited["usage_limit"] is True
    other = claude_run.run("hi", "sonnet", runner=fake_run(json.dumps({"is_error": True, "result": "Invalid model"}), 1))
    assert other["usage_limit"] is False and other["error"] == "Invalid model"


def test_dry_run_lists_what_would_be_written(content, capsys):
    assert generate.main(["--tiers", "initial", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "stage lesson(s) to write" in out and "First prompt:" in out and "Grade: Initial" in out


def test_a_note_to_name_must_be_the_note_written(content):
    stage = next(s for s in generate.targets(atlas_pkg.load_atlas(), ["initial"]) if s["stage"]["key"] == "learn")
    wrong = json.loads(json.dumps(GOOD_LEARN))
    wrong["steps"][2]["answer"] = 0  # 'F', but the music shows G
    steps, errors, files = generate.check(wrong, stage, content / "lessons" / "theory")
    assert any("the music shows G, but the answer marked right is 'F'" in e for e in errors), errors
    steps, errors, files = generate.check(GOOD_LEARN, stage, content / "lessons" / "theory")
    assert not errors
    xml = (content / "lessons" / steps[2]["file"]).read_text(encoding="utf-8")
    assert atlas_pkg.load_atlas()["by_id"][stage["requirement"]]["title"] in xml and steps[2]["file"].endswith("-3.musicxml")


def test_reviewing_a_generated_lesson(content):
    from midi_coach.atlas import store
    from midi_coach.atlas.runtime import AtlasCoach

    stage = generate.targets(atlas_pkg.load_atlas(), ["initial"])[0]
    path = content / "lessons" / f"{stage['id']}.json"
    path.write_text(json.dumps({"id": stage["id"], "checked": False, "made": "atlas.generate (sonnet)",
                                "steps": [{"id": "read-1", "type": "read", "text": "x" * 30}]}), encoding="utf-8")
    coach = AtlasCoach()
    assert coach.cmd_lesson_feedback({"node": stage["id"], "step": "read-1", "ok": False, "note": "  the  clef is wrong "}) == \
        {"node": stage["id"], "checked": False}
    logged = json.loads((atlas_pkg.user_dir() / "feedback.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert logged["note"] == "the clef is wrong" and logged["step"] == "read-1"
    assert coach.cmd_lesson_feedback({"node": stage["id"], "ok": True})["checked"] is True
    assert json.loads(path.read_text(encoding="utf-8"))["checked"] is True
    assert [e["ok"] for e in store.read_events() if e["type"] == "lesson_reviewed"] == [False, True]
