"""Temporary nodes: what a goal adds to the Atlas for as long as it lasts.

  bridge   a skill the syllabus doesn't name but the goal needs (Piano Man's walking bass
           in C, say): a requirement with a 'Learn it' and an 'At the keyboard' stage, whose
           lessons the generator writes in the background (the node says 'writing...' till then)
  song     a song goal's capstone: the song file itself, learnt section by section like a piece

They live in <home>/atlas/nodes.json, never in the built tree, and are drawn in the margin
lane at the right of the tier of their first prerequisite (layout.py keeps it free), so the
base layout never moves. Each tier that has some gets a 'Goal bridges' family to hold them.
A bridge also leads into the nodes it was made for ('before'): on the goal's Path it comes
ahead of them. When a goal is done or archived its nodes move to the past-goals layer: kept,
but no longer drawn.

Their lessons live in <home>/atlas/lessons (the base lessons are in the content folder).
"""

from __future__ import annotations

import copy
import json
import pathlib

from . import layout, user_dir
from .templates import piece_stages, slug, theory_stages


def path() -> pathlib.Path:
    return user_dir() / "nodes.json"


def lessons_dir() -> pathlib.Path:
    folder = user_dir() / "lessons"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def load() -> list[dict]:
    try:
        return json.loads(path().read_text(encoding="utf-8"))["nodes"]
    except (OSError, ValueError, KeyError):
        return []


def save(nodes: list[dict]) -> None:
    path().write_text(json.dumps({"nodes": nodes}, indent=1, ensure_ascii=False), encoding="utf-8")


def _tier_of(base: dict, ids: list[str], fallback: str) -> str:
    by_id = base["by_id"]
    for i in ids:
        if i in by_id and by_id[i].get("tier"):
            return by_id[i]["tier"]
    return fallback


def _strand_of(base: dict, ids: list[str], fallback: str = "theory") -> str:
    for i in ids:
        n = base["by_id"].get(i)
        if n and n.get("strand"):
            return n["strand"]
    return fallback


def _new_id(nodes: list[dict], goal: str, title: str) -> str:
    stem = f"tmp.{slug(goal)}.{slug(title)[:40]}"
    taken = {n["id"] for n in nodes}
    rid, k = stem, 1
    while rid in taken:
        k += 1
        rid = f"{stem}-{k}"
    return rid


def _stage_nodes(req: dict, stages: list[dict]) -> list[dict]:
    out = []
    for st in stages:
        out.append({"id": f"{req['id']}.{st['key']}", "level": "stage", "parent": req["id"], "tier": req["tier"],
                    "strand": req["strand"], "family": req["family"], "requirement": req["id"], "title": st["title"],
                    "kind": req["kind"], "stage": st, "final": st["final"], "prereqs": [], "temporary": True,
                    "goal": req["goal"]})
    req["stages"] = [s["id"] for s in out]
    return out


def add_bridge(base: dict, goal: str, title: str, brief: str, after: list[str], before: list[str]) -> dict:
    """A bridge requirement (and its two stages), placed in the tier of its first prerequisite
    (or of what it leads to). Returns the requirement node."""
    nodes = load()
    after = [a for a in after if a in base["by_id"]]
    before = [b for b in before if b in base["by_id"]]
    tier = _tier_of(base, after + before, base["tiers"][0]["id"])
    req = {"id": _new_id(nodes, goal, title), "level": "requirement", "parent": f"{tier}.goals", "tier": tier,
           "strand": _strand_of(base, after + before), "family": f"{tier}.goals", "kind": "bridge", "title": title,
           "brief": brief, "prereqs": after, "before": before, "covers": [], "temporary": True, "goal": goal, "status": "active"}
    nodes += [req] + _stage_nodes(req, theory_stages())
    save(nodes)
    return req


def add_song(base: dict, goal: str, title: str, file: str, bars: int, first_bar: int, targets: list[str]) -> dict:
    """A song goal's capstone: the song file, with piece-style stages (sections of 4-8 bars, each
    hand then together, then the whole song at rising tempo); its lessons are written now."""
    from .pieces import lesson_for

    nodes = load()
    tier = max((base["by_id"][t]["tier"] for t in targets if t in base["by_id"]),
               key=lambda t: next(x["order"] for x in base["tiers"] if x["id"] == t), default=base["tiers"][0]["id"])
    req = {"id": _new_id(nodes, goal, title), "level": "requirement", "parent": f"{tier}.goals", "tier": tier,
           "strand": "pieces", "family": f"{tier}.goals", "kind": "song", "title": title, "file": file,
           "prereqs": [t for t in targets if t in base["by_id"]], "before": [], "covers": [], "temporary": True,
           "goal": goal, "status": "active"}
    stage_nodes = _stage_nodes(req, piece_stages(bars, first_bar))
    nodes += [req] + stage_nodes
    save(nodes)
    piece = {"id": req["id"], "title": title, "composer": "the song file", "list": None}
    for st in stage_nodes:
        lesson = lesson_for(st, req, piece, file)
        lesson["made"] = "atlas.temporary (song)"
        (lessons_dir() / f"{st['id']}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
    return req


def retire_goal(goal: str) -> int:
    """The goal is done or archived: its nodes move to the past-goals layer."""
    nodes = load()
    count = 0
    for n in nodes:
        if n.get("goal") == goal and n.get("status", "active") == "active":
            n["status"] = "past"
            count += 1
    save(nodes)
    return count


def _requirements(base: dict, node_id: str) -> list[str]:
    """The requirements a node stands for: itself, a stage's requirement, or every requirement
    in a family, strand, grade, review or exam (what a bridge leading into it comes before)."""
    n = base["by_id"].get(node_id)
    if n is None:
        return []
    if n["level"] == "requirement":
        return [n["id"]]
    if n["level"] == "stage":
        return [n["requirement"]]
    reqs = (r for r in base["nodes"] if r["level"] == "requirement")
    if n["level"] == "family":
        return [r["id"] for r in reqs if r["family"] == n["id"]]
    if n["level"] == "strand":
        return [r["id"] for r in reqs if f"{r['tier']}.{r['strand']}" == n["id"]]
    return [r["id"] for r in reqs if r["tier"] == n["tier"]]


def needs_lesson(node: dict) -> bool:
    return node["level"] == "stage" and not (lessons_dir() / f"{node['id']}.json").exists()


def merged(base: dict) -> dict:
    """The built tree plus the active temporary nodes, placed in their tiers' lanes:
    'extra_prereqs' gives, per goal, each node a bridge of that goal leads into its bridges
    (for that goal's Path only), and 'temp_edges' the links to draw dashed."""
    active = [n for n in load() if n.get("status", "active") == "active" and n.get("goal")]
    stages = {n["id"]: [] for n in active if n["level"] == "requirement"}
    for n in active:
        if n["level"] == "stage" and n["parent"] in stages:
            stages[n["parent"]].append(n)
    reqs = [n for n in active if n["level"] == "requirement"]
    if not reqs:
        return base
    out = dict(base)
    nodes = list(base["nodes"])
    lanes = {lane["tier"]: lane for lane in base.get("geometry", {}).get("lanes", [])}
    tiers = {t["id"]: t for t in base["tiers"]}
    extra: dict[str, dict[str, list[str]]] = {}  # goal -> node -> its prerequisites with the goal's bridges
    edges = []
    for tier in sorted({r["tier"] for r in reqs}, key=lambda t: tiers[t]["order"]):
        lx, ly, lw, lh = lanes.get(tier, {}).get("box", [0, 0, 220, 400])
        fam = {"id": f"{tier}.goals", "level": "family", "parent": tier, "tier": tier, "title": "Goal bridges",
               "kind": "temporary", "temporary": True, "prereqs": []}
        y = ly + layout.FAM_HEAD
        for req in (r for r in reqs if r["tier"] == tier):
            req = copy.deepcopy(req)
            kids = [copy.deepcopy(s) for s in stages[req["id"]]]
            req["stages"] = [s["id"] for s in kids]
            h = layout.REQ_HEAD + len(kids) * layout.STAGE_DY + layout.REQ_PAD
            req["box"] = [lx + 8, y, lw - 16, h]
            for k, st in enumerate(kids):
                cx, cy = lx + lw / 2, y + layout.REQ_HEAD + k * layout.STAGE_DY + layout.STAGE_DY / 2
                st["box"] = [cx - layout.STAGE_R, cy - layout.STAGE_R, 2 * layout.STAGE_R, 2 * layout.STAGE_R]
                st["writing"] = req["kind"] == "bridge" and needs_lesson(st)
            y += h + 8
            nodes += [req] + kids
            edges += [[p, req["id"]] for p in req["prereqs"]] + [[req["id"], b] for b in req.get("before", [])]
            mine = extra.setdefault(req["goal"], {})
            for b in (r for target in req.get("before", []) for r in _requirements(base, target)):
                mine.setdefault(b, list(base["by_id"][b].get("prereqs", []))).append(req["id"])
        fam["box"] = [lx, ly, lw, max(y - ly + 6, 60)]
        nodes.append(fam)
    out["nodes"] = nodes
    out["by_id"] = {n["id"]: n for n in nodes}
    out["extra_prereqs"] = extra
    out["temp_edges"] = edges
    out["version"] = f"{base.get('version')}+{len(reqs)}t"
    return out
