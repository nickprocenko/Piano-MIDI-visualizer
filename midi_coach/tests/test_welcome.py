"""Getting to know you (atlas/welcome.py): the questions, where the answers start you, and
what finishing credits and saves."""

from __future__ import annotations

import json

import pytest

from midi_coach.atlas import store, welcome
from midi_coach.tests.test_atlas import home, tree  # noqa: F401  (fixtures)

PIANO_TIERS = [{"id": t, "order": k} for k, t in enumerate(["initial", "g1", "g2", "g3"])] + [
    {"id": "first", "order": -2}, {"id": "ready", "order": -1}]
CHECKS_RIGHT = {q["id"]: q["answer"] for q in welcome.QUESTIONS if q["kind"] == "check"}


@pytest.mark.parametrize("instrument", ["piano", "flute"])
def test_questions_are_well_formed(instrument):
    qs = welcome.questions(instrument)
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids))
    assert sum(q["kind"] == "check" for q in qs) == len(welcome.CHECKS)  # 'of' is the same either way
    for q in qs:
        assert q["kind"] in ("about", "check") and q["options"]
        if q["kind"] == "check":
            assert 0 <= q["answer"] < len(q["options"])
        if "staff" in q:  # drawn without accidentals: a natural note
            assert q["staff"]["midi"] % 12 in (0, 2, 4, 5, 7, 9, 11)
            letter = "C D E F G A B".split()[[0, 2, 4, 5, 7, 9, 11].index(q["staff"]["midi"] % 12)]
            assert q["options"][q["answer"]] == letter


def test_a_flutist_is_asked_about_the_flute_in_the_treble_clef():
    qs = {q["id"]: q for q in welcome.questions("flute")}
    assert all("piano" not in qs[k]["prompt"] for k in ("played", "exams", "why"))
    assert "flute" in qs["played"]["prompt"]
    assert all(q.get("staff", {}).get("clef", "treble") == "treble" for q in qs.values())
    assert "f3" not in qs and "g4" in qs
    right = {q["id"]: q["answer"] for q in qs.values() if q["kind"] == "check"}
    assert welcome.correct(right) == len(welcome.CHECKS)
    assert welcome.start_tier({"played": 1, "reading": 1, **right}) == "initial"
    # Brand new: First notes, the first tier Pan has.
    pan = [{"id": "initial", "order": 0}, {"id": "g1", "order": 1}, {"id": "g2", "order": 2}]
    assert welcome.placed({"played": 0, "reading": 0}, pan) == ("initial", [])


@pytest.mark.parametrize("answers, start", [
    ({"played": 0, "reading": 0}, "first"),                               # brand new
    ({"played": 1, "reading": 0}, "ready"),                               # has had a go, not reading yet
    ({"played": 1, "reading": 1}, "ready"),                               # reading slowly, checks missed
    ({"played": 1, "reading": 1, **CHECKS_RIGHT}, "initial"),
    ({"played": 3, "reading": 2, **CHECKS_RIGHT}, "g1"),
    ({"played": 3, "reading": 3, **CHECKS_RIGHT}, "g2"),
    ({"played": 3, "reading": 3}, "g1"),
    ({"played": 3, "reading": 2, "exams": 4}, "g4"),                      # passed Grade 3 (any checks)
    ({"played": 3, "reading": 3, "exams": 9}, None),                      # passed Grade 8
])
def test_where_the_answers_start_you(answers, start):
    assert welcome.start_tier(answers) == start


def test_placed_on_a_tree_without_the_beginner_tiers():
    assert welcome.placed({"played": 1, "reading": 2, **CHECKS_RIGHT}, PIANO_TIERS) == ("g1", ["first", "ready", "initial"])
    assert welcome.placed({"played": 0, "reading": 0}, PIANO_TIERS) == ("first", [])
    grades_only = [t for t in PIANO_TIERS if t["order"] >= 0]
    assert welcome.placed({"played": 0, "reading": 0}, grades_only) == ("initial", [])  # nearest there is
    assert welcome.placed({"exams": 9}, grades_only) == (None, ["initial", "g1", "g2", "g3"])


def test_finishing_credits_sets_a_goal_and_tells_the_maestro(home, tree, monkeypatch):  # noqa: F811
    from midi_coach import atlas as atlas_pkg
    from midi_coach.atlas.runtime import AtlasCoach

    content = atlas_pkg.content_dir()
    content.mkdir(parents=True, exist_ok=True)
    (content / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    coach = AtlasCoach()
    assert coach.cmd_welcome({})["last"] is None
    answers = {"played": 3, "reading": 2, "exams": 0, "why": [0, 3], "time": 1, **CHECKS_RIGHT}
    out = coach.cmd_welcome_finish({"answers": answers})
    below = [t["id"] for t in sorted(tree["tiers"], key=lambda t: t["order"]) if t["order"] < 1]
    assert out["tier"] == "g1" and out["credited"] == below and "initial" in below
    assert out["correct"] == out["of"] == len(welcome.CHECKS)
    assert out["summary"].startswith("You're starting at Grade 1!")
    credits = [e for e in store.read_events() if e["type"] == "placement_credit"]
    assert [e["tier"] for e in credits] == below
    goals = store.load_goals()
    assert goals["active"] == out["goal"] and goals["goals"][0]["targets"] == ["g1.exam"]
    assert coach.cmd_welcome({})["last"]["tier"] == "g1"
    assert welcome.about_line() == ("Getting to know you: learning for: playing songs I love, relaxing and having fun; "
                                    "has about 10 minutes a day.")
    # Answering again keeps a goal you already have active.
    again = coach.cmd_welcome_finish({"answers": {**answers, "reading": 1}})
    assert again["tier"] == "initial" and again["goal"] != out["goal"] and store.load_goals()["active"] == out["goal"]
