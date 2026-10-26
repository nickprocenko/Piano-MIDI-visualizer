"""Turning a goal into a Path: Claude Code on the subscription plans it, the coach checks it.

A goal is a song ("play Piano Man"), a skill ("sight-read hymns") or a grade. The planner
gets the goal, where the pianist stands (each grade's progress, exams passed), for a song
its facts (song_facts: the file's key, metre, chords, plus published facts, reconciled), and
the Atlas's requirements (id, title, what each covers). It answers in a fixed shape
(PLAN_SCHEMA): the requirements, families or exams the goal needs ('targets'), at most five
bridges for what the syllabus doesn't name, which requirements to bring forward, and its
reasons. Unknown ids or a bridge out of place go back for repair (up to REPAIRS rounds).

Then the coach builds it: each bridge becomes a temporary node (temporary.py) whose lessons
the generator writes in the background; a song goal gets the song itself as its capstone,
with the targets as its prerequisites; and the Path is every requirement the capstone or
targets need that isn't known yet, prerequisites first (mastery.path_families), grouped into
families. The goal is saved (store goals.json) and made active.
"""

from __future__ import annotations

import os
import re
import time

from .. import library
from . import claude_run, load_atlas, mastery, store, temporary
from .templates import slug

REPAIRS = 2
MAX_BRIDGES = 5

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "kind": {"type": "string", "enum": ["song", "skill", "grade"]},
        "targets": {"type": "array", "items": {"type": "string"}},
        "bridges": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "brief": {"type": "string"},
                           "after": {"type": "array", "items": {"type": "string"}},
                           "before": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "brief", "after", "before"]}},
        "order_hints": {"type": "array", "items": {"type": "string"}},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "kind", "targets", "bridges", "reasons"],
}

PLANNER_SYSTEM = """You plan a pianist's practice towards one goal, on a skill tree that follows a graded piano syllabus (Initial, then Grade 1 to 8). Each requirement is one exam item (a scale, a piece, an aural test, a sight-reading feature, a theory topic), and requirements come in families.

Answer with:
- title: the goal in a few words ("Piano Man", "Sight-reading hymns").
- kind: song, skill or grade.
- targets: the ids of the requirements, families or exam nodes (e.g. "g3.exam") the goal needs. Use only ids from the list given. Choose what the goal truly needs: for a song, the keys, scales, chords, rhythms and reading skills its music uses, at about the grade its hardest parts sit. Prerequisites are added automatically, so don't list the whole tree; known requirements are skipped automatically.
- bridges: at most 5 skills the goal needs that no requirement covers (e.g. "Walking bass in C"), each with a brief for the lesson writer (what to teach, in which key, which hand, how hard), 'after' (ids it builds on) and 'before' (ids of targets it prepares, may be empty). Only when the tree truly lacks it.
- order_hints: target ids to bring forward, most useful first (e.g. the song's key before anything else).
- reasons: 2-6 short sentences for the pianist on why these steps. For a song, say which facts shaped the plan and cite where they came from ("TheoryTab shows the verse as I V6 IV6 I64"). If a source disagreed with the file, say so; the file is what they'll play. If no published facts were found, say the plan uses the file alone."""


def model_name() -> str:
    return os.environ.get("MIDI_COACH_GENERATOR_MODEL") or "sonnet"


def level_summary(atlas: dict, states: dict) -> list[str]:
    lines = []
    for t in atlas["tiers"]:
        st = states.get(t["id"]) or {}
        ex = states.get(f"{t['id']}.exam") or {}
        if st.get("done") or ex.get("best"):
            lines.append(f"{t['title']}: {st.get('done', 0)} of {st.get('total', 0)} requirements known"
                         + (f"; mock exam best {ex['best']}/150" if ex.get("best") else ""))
    return lines or ["Nothing practised on the tree yet."]


def catalog_lines(atlas: dict) -> list[str]:
    """Every requirement, by family: 'family id - title: req id = title [covers]; ...'."""
    by_family: dict[str, list[dict]] = {}
    for n in atlas["nodes"]:
        if n["level"] == "requirement" and not n.get("temporary"):
            by_family.setdefault(n["family"], []).append(n)
    lines = []
    for fam, reqs in by_family.items():
        title = atlas["by_id"][fam]["title"] if fam in atlas["by_id"] else fam
        items = "; ".join(f"{r['id']} = {r['title']}" + (f" [{', '.join(r['covers'])}]" if r.get("covers") else "") for r in reqs)
        lines.append(f"{fam} ({title}): {items}")
    lines.append("Exams: " + ", ".join(f"{t['id']}.exam" for t in atlas["tiers"]))
    return lines


def validate(plan: dict | None, atlas: dict) -> list[str]:
    if not plan:
        return ["No plan came back."]
    errors = []
    known = atlas["by_id"]
    bad = [t for t in plan.get("targets") or [] if t not in known]
    if bad:
        errors.append(f"These target ids aren't in the tree: {bad[:8]}. Use ids from the list only.")
    if not (plan.get("targets") or plan.get("bridges")):
        errors.append("Give at least one target (or a bridge).")
    bridges = plan.get("bridges") or []
    if len(bridges) > MAX_BRIDGES:
        errors.append(f"At most {MAX_BRIDGES} bridges; there are {len(bridges)}.")
    for k, b in enumerate(bridges, 1):
        if not b.get("title", "").strip() or len(b.get("brief", "").strip()) < 20:
            errors.append(f"Bridge {k} needs a title and a brief of a sentence or two.")
        wrong = [i for i in (b.get("after") or []) + (b.get("before") or []) if i not in known]
        if wrong:
            errors.append(f"Bridge {k} ('{b.get('title')}') names ids that aren't in the tree: {wrong[:6]}.")
    if not plan.get("reasons"):
        errors.append("Give the reasons.")
    return errors


def plan_goal(text: str, song: str | None = None, artist: str | None = None, run=claude_run.run, model: str | None = None,
              research: bool = True) -> dict:
    """Plan a goal and save it as the active one. Returns the goal (or {error})."""
    from . import song_facts

    model = model or model_name()
    base = load_atlas()
    states = store.progress(temporary.merged(base))
    facts, song_path, score = None, None, None
    if song:
        song_path = library.resolve_reference(song)
        score = library.get_score(str(song_path))
        title = re.sub(r"[-_]+", " ", song_path.stem).strip()
        if research:
            facts = song_facts.get(song_path, title, artist, score, run)
        else:
            facts = {"measured": song_facts.measured(score), "facts": [], "found": False,
                     "note": "Research was skipped: the plan uses what the file shows alone."}
    prompt = "\n".join(
        [f"Today: {time.strftime('%A %d %B %Y')}", f"Goal: {text}"]
        + ([f"Song file: {song_path.name}", song_facts.summary(facts)] if facts else [])
        + ["", "Where the pianist stands:"] + level_summary(base, states)
        + ["", "The tree's requirements (family (title): id = title [covers]; ...):"] + catalog_lines(base))
    out = run(prompt, model, schema=PLAN_SCHEMA, system=PLANNER_SYSTEM)
    plan, errors = None, []
    for rnd in range(REPAIRS + 1):
        if out.get("error"):
            return {"error": out["error"], "usage_limit": out.get("usage_limit", False)}
        plan = out.get("structured")
        errors = validate(plan, base)
        if not errors:
            break
        if rnd == REPAIRS:
            return {"error": "The plan didn't check out: " + " ".join(errors)}
        out = run("These problems were found in your plan:\n- " + "\n- ".join(errors) + "\n\nSend the whole plan again, corrected.",
                  model, schema=PLAN_SCHEMA, system=PLANNER_SYSTEM, resume=out.get("session_id"))
    return build_goal(plan, text, base, states, song_path=song_path, score=score, facts=facts,
                      planner={"session_id": out.get("session_id"), "model": model, "cost_usd": out.get("cost_usd")})


def build_goal(plan: dict, text: str, base: dict, states: dict | None = None, song_path=None, score=None,
               facts: dict | None = None, planner: dict | None = None) -> dict:
    """Make a checked plan real: bridges and capstone as temporary nodes, the goal saved and active."""
    goal_id = f"{slug(plan['title'])[:40] or 'goal'}-{time.strftime('%Y%m%d-%H%M%S')}"
    targets = [t for t in plan.get("targets") or [] if t in base["by_id"]]
    bridges = []
    for b in (plan.get("bridges") or [])[:MAX_BRIDGES]:
        node = temporary.add_bridge(base, goal_id, b["title"].strip(), b["brief"].strip(), b.get("after") or [], b.get("before") or [])
        bridges.append(node["id"])
    goal_targets = targets + [b for b in bridges if not temporary_before(b)]
    if song_path is not None:
        first = score.bars[0].number if score.bars else 1
        cap = temporary.add_song(base, goal_id, plan["title"], str(song_path), len(score.bars), first, targets)
        goal_targets = [cap["id"]] + [b for b in bridges if not temporary_before(b)]
    goal = {"id": goal_id, "title": plan["title"], "text": text, "kind": "song" if song_path is not None else plan.get("kind", "skill"),
            "song": str(song_path) if song_path is not None else None, "targets": goal_targets, "bridges": bridges,
            "first": [t for t in plan.get("order_hints") or [] if t in base["by_id"]],
            "status": "active", "created": store.now(),
            "planner": {**(planner or {}), "reasons": plan.get("reasons") or [],
                        "sources": sorted({s for f in (facts or {}).get("facts", []) for s in f["sources"]}),
                        "conflicts": [f["note"] for f in (facts or {}).get("facts", []) if f.get("status") == "conflict"]}}
    if facts and facts.get("note"):
        goal["planner"]["reasons"].append(facts["note"])
    goal["families"] = [f["family"] for f in path(goal, states)]
    data = store.load_goals()
    data["goals"].append(goal)
    data["active"] = goal_id
    store.save_goals(data)
    return goal


def temporary_before(node_id: str) -> list[str]:
    n = next((x for x in temporary.load() if x["id"] == node_id), None)
    return (n or {}).get("before") or []


def path(goal: dict, states: dict | None = None) -> list[dict]:
    """The goal's Path now: families in order, each with the requirements still to do."""
    atlas = temporary.merged(load_atlas())
    states = states if states is not None else store.progress(atlas)
    return mastery.path_families(atlas, states, goal["targets"], extra_prereqs=(atlas.get("extra_prereqs") or {}).get(goal["id"]),
                                 first=goal.get("first"))
