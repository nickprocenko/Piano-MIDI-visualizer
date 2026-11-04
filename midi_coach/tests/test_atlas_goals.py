"""Goals and Paths with a fake Claude Code: planning (with a repair round), bridges in the margin
lane and their lessons, song research reconciled against the file, a song's capstone, and the
page's goal commands."""

from __future__ import annotations

import hashlib
import json

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import layout, planner, song_facts, store, temporary
from midi_coach.tests.test_atlas import _req, home, tree  # noqa: F401  (fixtures)
from midi_coach.tests.test_atlas_generate import GOOD_KEYS, GOOD_LEARN


@pytest.fixture()
def content(home, tree):  # noqa: F811
    folder = atlas_pkg.content_dir()
    (folder / "lessons").mkdir(parents=True)
    layout.layout(tree)
    (folder / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    return tree


class FakeClaude:
    """Plans, research and lessons from scripts, told apart by the schema asked for."""

    def __init__(self, plans=(), research=None):
        self.plans = list(plans)
        self.research = research
        self.calls: list[dict] = []

    def __call__(self, prompt, model, schema=None, system=None, tools="", resume=None, **_):
        self.calls.append({"prompt": prompt, "schema": schema, "resume": resume, "tools": tools})
        if schema is planner.PLAN_SCHEMA:
            return {"structured": self.plans.pop(0), "session_id": "plan-1", "cost_usd": 0.05}
        if schema is song_facts.RESEARCH_SCHEMA:
            return self.research
        lesson = GOOD_KEYS if "At the keyboard" in prompt else GOOD_LEARN
        return {"structured": lesson, "session_id": "lesson", "cost_usd": 0.01}


def _plan(tree, **extra):  # noqa: F811
    c_scale = _req(tree, "scale-c-major", tier="initial")["id"]
    g1_family = next(n["id"] for n in tree["nodes"] if n["level"] == "family" and n["tier"] == "g1" and n["strand"] == "technique")
    return {"title": "Scales in G", "kind": "skill", "targets": [g1_family],
            "bridges": [{"title": "Thumb-under drill", "brief": "Short right-hand drills passing the thumb under in G major, slowly.",
                         "after": [c_scale], "before": [g1_family]}],
            "order_hints": [], "reasons": ["G major scales build on C major.", "A thumb-under drill smooths the turn."], **extra}


def test_a_goal_is_planned_repaired_and_built_with_a_bridge(content):
    bad = _plan(content, targets=["g1.technique.no-such-thing"])
    fake = FakeClaude(plans=[bad, _plan(content)])
    goal = planner.plan_goal("I want my G major scales smooth", run=fake)
    assert "error" not in goal, goal
    assert fake.calls[1]["resume"] == "plan-1" and "aren't in the tree" in fake.calls[1]["prompt"]
    assert "Where the pianist stands" in fake.calls[0]["prompt"] and "Exams:" in fake.calls[0]["prompt"]
    data = store.load_goals()
    assert data["active"] == goal["id"] and goal["status"] == "active" and len(goal["bridges"]) == 1

    merged = temporary.merged(atlas_pkg.load_atlas())
    bridge = merged["by_id"][goal["bridges"][0]]
    lane = next(lane for lane in merged["geometry"]["lanes"] if lane["tier"] == bridge["tier"])
    lx, ly, lw, lh = lane["box"]
    assert bridge["temporary"] and bridge["tier"] == "initial" and lx <= bridge["box"][0] < lx + lw  # in the margin lane
    assert all(merged["by_id"][s]["writing"] for s in bridge["stages"])  # its lessons aren't written yet
    assert [bridge["id"], goal["targets"][0]] in merged["temp_edges"]  # drawn dashed into the family it prepares
    # The base layout never moves.
    base = atlas_pkg.load_atlas()
    assert all(merged["by_id"][n["id"]].get("box") == n.get("box") for n in base["nodes"])

    families = planner.path(goal)
    order = [r["id"] for f in families for r in f["requirements"]]
    g1_reqs = [r for r in order if r.startswith("g1.technique")]
    assert bridge["id"] in order and order.index(bridge["id"]) < order.index(g1_reqs[0])  # the bridge leads into its target


def test_bridge_lessons_are_written_in_the_background_and_next_finds_them(content):
    from midi_coach.atlas.runtime import AtlasCoach

    coach = AtlasCoach()
    coach.plan_run = FakeClaude(plans=[_plan(content)])
    out = coach.cmd_goal_plan({"text": "G major scales", "wait": True})
    assert out["planning"]["text"] == "G major scales"
    for _ in range(50):  # the bridge worker runs after the plan
        if not any(n.get("writing") for n in coach.tree()["nodes"]):
            break
        __import__("time").sleep(0.1)
    state = coach.cmd_goals({})
    assert state["planning"]["done"] == state["active"] and state["path"]
    bridge_stages = [s for f in state["path"] for r in f["requirements"] if r["temporary"] for s in r["stages"]]
    assert bridge_stages and all(s["lesson"] for s in bridge_stages)
    lesson = coach.lesson(bridge_stages[0]["id"])
    assert lesson["checked"] is False and (temporary.lessons_dir() / f"{bridge_stages[0]['id']}.json").is_file()
    nxt = coach.cmd_path_next({})
    assert "stage" in nxt and coach.lesson(nxt["stage"]) is not None
    assert any("Active goal: Scales in G" in line for line in coach.context_lines())

    archived = coach.cmd_goal_archive({"id": state["active"]})
    assert archived["active"] is None and not any(n.get("temporary") for n in coach.tree()["nodes"])
    assert all(n["status"] == "past" for n in temporary.load())


@pytest.fixture()
def song(tmp_path):
    from midi_coach.notes import load_score
    from midi_coach.tests.test_midi_coach import _write_reference

    path = _write_reference(tmp_path / "Piano Man.mid", rest_bars=())
    return path, load_score(path)


def test_song_research_is_reconciled_against_the_file(home, song):  # noqa: F811
    path, score = song
    before = hashlib.sha1(path.read_bytes()).hexdigest()
    m = song_facts.measured(score)
    assert m["key"] and m["meter"] == ["4/4"] and m["bars"] == 16 and m["chords_by_bar"]
    tt = "https://www.hooktheory.com/theorytab/view/billy-joel/piano-man"
    facts = [
        {"field": "key", "value": m["key"] + (" minor" if m["key"].endswith("m") else " major"), "sources": [tt]},
        {"field": "meter", "value": "6/8", "sources": [tt]},
        {"field": "bpm", "value": f"{m['bpm'] * 2} BPM", "sources": ["https://en.wikipedia.org/wiki/Piano_Man_(song)"]},
        {"field": "technique", "value": "walking bass in the left hand", "sources": [tt, "https://www.musicnotes.com/x"]},
        {"field": "difficulty", "value": "intermediate", "sources": ["https://www.musicnotes.com/x"]},
        {"field": "form", "value": "verse and chorus", "sources": []},  # no source: dropped
    ]
    fake = FakeClaude(research={"structured": {"song": "Piano Man", "facts": facts}, "session_id": "r", "cost_usd": 0.2})
    data = song_facts.get(path, "Piano Man", "Billy Joel", score, run=fake)
    status = {f["field"]: f["status"] for f in data["facts"]}
    assert status == {"key": "confirmed", "meter": "conflict", "bpm": "confirmed", "technique": "confirmed", "difficulty": "reported"}
    meter = next(f for f in data["facts"] if f["field"] == "meter")
    assert meter["note"] == "TheoryTab says 6/8; the file is written in 4/4."
    assert fake.calls[0]["tools"] == "WebSearch,WebFetch" and "Piano Man by Billy Joel" in fake.calls[0]["prompt"]
    assert hashlib.sha1(path.read_bytes()).hexdigest() == before  # the file is never touched
    assert song_facts.get(path, "Piano Man", "Billy Joel", score, run=FakeClaude()) == data  # cached
    assert "[conflict] meter: 6/8" in song_facts.summary(data)


def test_a_song_goal_offline_uses_the_file_alone_and_gets_a_capstone(content, song):
    path, score = song
    c_scale = _req(content, "scale-c-major", tier="initial")["id"]
    plan = {"title": "Piano Man", "kind": "song", "targets": [c_scale], "bridges": [], "order_hints": [c_scale],
            "reasons": ["The song sits in C, so the C major scale comes first."]}
    fake = FakeClaude(plans=[plan], research={"error": "Could not reach the web", "usage_limit": False})
    goal = planner.plan_goal("Play Piano Man", song=str(path), run=fake)
    assert goal["kind"] == "song" and goal["song"] == str(path)
    assert any("No published facts were found" in r for r in goal["planner"]["reasons"])
    assert "No published facts were found" in fake.calls[1]["prompt"]  # the planner was told
    merged = temporary.merged(atlas_pkg.load_atlas())
    cap = merged["by_id"][goal["targets"][0]]
    assert cap["kind"] == "song" and cap["prereqs"] == [c_scale] and len(cap["stages"]) > 4
    lesson = json.loads((temporary.lessons_dir() / f"{cap['stages'][-1]}.json").read_text(encoding="utf-8"))
    assert any(s.get("file") == str(path) for s in lesson["steps"])
    order = [r["id"] for f in planner.path(goal) for r in f["requirements"]]
    assert order.index(c_scale) < order.index(cap["id"])  # the scale before the song


def test_save_goal_checks_a_plan_from_claude_desktop(content):
    assert planner.validate({"title": "x", "kind": "skill", "targets": [], "bridges": [], "reasons": []}, atlas_pkg.load_atlas())
    errors = planner.validate({"title": "x", "kind": "skill", "targets": ["g1.exam"], "reasons": ["Grade 1."],
                               "bridges": [{"title": "b", "brief": "short", "after": ["nope"], "before": []}] * 6},
                              atlas_pkg.load_atlas())
    assert any("At most 5 bridges" in e for e in errors) and any("names ids that aren't in the tree" in e for e in errors)


def test_a_bridge_belongs_to_its_own_goal(content):
    first = planner.build_goal(_plan(content), "G scales", atlas_pkg.load_atlas(), {})
    second = planner.build_goal(_plan(content, title="Same scales, no bridge", bridges=[]), "again", atlas_pkg.load_atlas(), {})
    mine = [r["id"] for f in planner.path(first) for r in f["requirements"]]
    theirs = [r["id"] for f in planner.path(second) for r in f["requirements"]]
    assert first["bridges"][0] in mine and first["bridges"][0] not in theirs
    assert set(theirs) == set(mine) - {first["bridges"][0]}


def test_a_route_to_a_lesson_is_shown_then_quick_saved_once(content):
    from midi_coach.atlas.runtime import AtlasCoach

    coach = AtlasCoach()
    g1 = next(n for n in content["nodes"] if n["level"] == "requirement" and n["tier"] == "g1" and n.get("prereqs"))
    stage = g1["stages"][0]
    route = coach.cmd_route({"id": stage})  # an exercise's route is its lesson's
    order = [r["id"] for f in route["path"] for r in f["requirements"]]
    assert route["target"] == g1["id"] and order[-1] == g1["id"] and set(g1["prereqs"]) & set(order[:-1])
    assert all(any(s["id"] for s in r["stages"]) for f in route["path"] for r in f["requirements"])
    assert store.load_goals()["goals"] == []  # looking saves nothing

    state = coach.cmd_goal_quick({"id": stage})
    assert state["goal"]["title"] == g1["title"] and state["goal"]["targets"] == [g1["id"]]
    assert [r["id"] for f in state["path"] for r in f["requirements"]] == order
    again = coach.cmd_goal_quick({"id": g1["id"]})
    assert len(again["goals"]) == 1 and again["active"] == state["active"]


def test_see_in_the_song_finds_each_lesson_in_its_song(content, song):
    """A song's sections open at their own bars, a bridge at the bars the planner gave, and a
    syllabus requirement on the way at the start; the Session's sheet comes back after."""
    path, score = song
    c_scale = _req(content, "scale-c-major", tier="initial")["id"]
    plan = {"title": "Piano Man", "kind": "song", "targets": [c_scale], "order_hints": [], "reasons": ["In C."],
            "bridges": [{"title": "Walking bass in C", "brief": "Left-hand walking bass in C, crotchets, slowly at first.",
                         "after": [c_scale], "before": [], "song_bars": "9-12"}]}
    assert planner.validate(plan, atlas_pkg.load_atlas()) == []
    goal = planner.build_goal(plan, "Play Piano Man", atlas_pkg.load_atlas(), {}, song_path=path, score=score)
    merged = temporary.merged(atlas_pkg.load_atlas())
    cap = merged["by_id"][goal["targets"][0]]
    bridge = merged["by_id"][goal["bridges"][0]]
    assert bridge["song_bars"] == "9-12"

    from midi_coach.atlas.runtime import AtlasCoach

    shown = []
    hub = type("Hub", (), {"score_path": "session.mid", "atlas": lambda self, msg: None})()
    coach = AtlasCoach(hub=hub, show=lambda p: (shown.append(p), setattr(hub, "score_path", p)))
    assert coach.song_for(cap["stages"][0])["bars"] == "1-4"
    assert coach.song_for(cap["stages"][-1]) == {"song": str(path), "title": "Piano Man", "bars": "", "why": "the whole song"}
    assert coach.song_for(bridge["stages"][0])["bars"] == "9-12"
    plain = coach.song_for(c_scale)  # on the way, but the planner didn't place it in the song
    assert plain["bars"] == "" and "from the start" in plain["why"]

    out = coach.cmd_stage_song({"node": bridge["stages"][0]})
    assert out["bars"] == "9-12" and shown == [str(path)]
    assert coach.cmd_stage_close({}) == {"restored": "session.mid"} and shown[-1] == "session.mid"
    coach.cmd_stage_open({"node": cap["stages"][0]})  # Practise the whole song in the Session
    coach.cmd_stage_song({"node": cap["stages"][0], "keep": True})
    assert coach.cmd_stage_close({}) == {"restored": None} and hub.score_path == str(path)  # the song stays up


def test_song_bars_must_be_bar_numbers(content):
    plan = _plan(content)
    plan["bridges"][0]["song_bars"] = "the chorus"
    assert any("song_bars" in e for e in planner.validate(plan, atlas_pkg.load_atlas()))


def test_see_in_the_song_without_a_song_goal(content):
    from midi_coach.atlas.runtime import AtlasCoach

    assert AtlasCoach().cmd_stage_song({"node": "nope"}) == {"error": "This lesson isn't part of a song goal."}
