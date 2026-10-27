"""Remedial drills: a short drill node for a bar you keep tripping on.

Every graded play pass records the bars it slipped in (the notes it expected there) as a
'slips' event. When the same bar, with some of the same notes, slipped in 2 of the last 3
passes of a step, a drill node 'drill.<node>.<bar>' joins the Atlas margin lane: a short
requirement on that bar (with a bar either side) that reuses the step's own file, hand and
part choice: listen at 70% and learn it, learn it again, then rehearse it at 80%.
Drills never spawn drills, and one that is Proficient retires to the past layer.

A drill leads into the requirement it came from, so on any goal's Path that has that
requirement the drill comes first (and Next goes there).

Not every slip is a habit:
  - ungraded and stopped-halfway passes aren't counted (nor exam takes or fresh sight-reading)
  - a 'broad' pass, slipping in more than half the bars it played, says the passage as a whole
    isn't ready yet (the stage itself works on that): it's logged but doesn't count
  - a bar inside an active drill of the same step is already being drilled
  - a pass makes at most MAX_NEW drills, the bars that slipped most often first
  - a pickup bar (bar 0) can't be chosen on its own, so it gets no drill
"""

from __future__ import annotations

import json

from ..notes import note_name
from . import mastery, store, temporary
from .templates import stage

GOAL = "drills"  # the 'goal' the temporary nodes hang under
WINDOW = 3       # passes looked at
REPEATS = 2      # slips in this many of them make a drill
NEIGHBOURS = 1   # bars of lead-in and lead-out around the slip
BROAD = 0.5      # a pass slipping in more than this share of its bars doesn't count
MAX_NEW = 2      # drills one pass can make


def slip_bars(report: dict | None, live: dict | None) -> dict[int, list[str]]:
    """{bar: expected note names} of one pass: wait-mode slips (a wrong key for the chord
    waited on) and the comparison's wrong and missed notes."""
    bars: dict[int, set[str]] = {}
    for s in (live or {}).get("slips") or []:
        if s.get("bar") is not None:
            bars.setdefault(int(s["bar"]), set()).update(note_name(int(p)) for p in s.get("expected") or [])
    for m in (report or {}).get("mistakes") or []:
        if m.get("type") in ("wrong", "missed") and m.get("bar") is not None and m.get("expected"):
            bars.setdefault(int(m["bar"]), set()).add(m["expected"])
    return {b: sorted(n) for b, n in sorted(bars.items())}


def record_pass(node: str, step: str, report: dict | None, live: dict | None, played: int | None = None) -> dict:
    """Log a graded pass's slips (an empty pass too: it breaks a run of slips). played: how
    many bars the pass covered, to tell a broad pass (see above)."""
    bars = slip_bars(report, live)
    broad = bool(played) and len(bars) > max(1, played * BROAD)
    store.append_event("slips", node=node, step=step, bars={str(b): n for b, n in bars.items()},
                       **({"broad": True} if broad else {}))
    return bars


def _span(source: dict) -> range:
    first, _, last = str(source.get("bars") or source.get("bar")).partition("-")
    return range(int(first), int(last or first) + 1)


def repeated(node: str, step: str, events: list[dict] | None = None) -> list[int]:
    """Bars that slipped, with overlapping notes, in at least REPEATS of the step's last WINDOW
    (not broad) passes: the most often first, then in bar order. A drill's bars start counting
    afresh once it retires: the slips that made it don't make it again."""
    events = store.read_events() if events is None else events
    passes: list[tuple[int, dict]] = []
    fresh: dict[int, int] = {}  # bar -> the event its count starts after
    for k, e in enumerate(events):
        if e.get("type") == "slips" and e.get("node") == node and e.get("step") == step and not e.get("broad"):
            passes.append((k, e["bars"]))
        elif e.get("type") == "drill_retired" and (e.get("source") or {}).get("node") == node and e["source"].get("step") == step:
            fresh.update((b, k) for b in _span(e["source"]))
    passes = passes[-WINDOW:]
    found = []
    for bar in sorted({int(b) for _, p in passes for b in p if int(b) >= 1}):
        sets = [set(p[str(bar)]) for k, p in passes if str(bar) in p and k > fresh.get(bar, -1)]
        hits = max((sum(1 for t in sets if t & s) for s in sets), default=0)
        if hits >= REPEATS:
            found.append((-hits, bar))
    return [bar for _, bar in sorted(found)]


def active(nodes: list[dict] | None = None) -> list[dict]:
    """The drill requirements on the Atlas now."""
    nodes = temporary.load() if nodes is None else nodes
    return [n for n in nodes if n.get("kind") == "drill" and n["level"] == "requirement" and n.get("status", "active") == "active"]


def covered(node: str, step: str, bar: int, nodes: list[dict] | None = None) -> bool:
    """Is the bar inside an active drill of this step?"""
    for d in active(nodes):
        src = d.get("source") or {}
        if src.get("node") == node and src.get("step") == step and bar in _span(src):
            return True
    return False


def drill_id(node: str, bar: int) -> str:
    return f"drill.{node}.{bar}"


def stages(first: int, last: int) -> list[dict]:
    span = f"bars {first}-{last}" if last > first else f"bar {first}"
    bars = f"{first}-{last}"
    return [dict(stage("learn-a", f"{span}: listen, then learn", "both", "learn", 70), bars=bars, listen=True),
            dict(stage("learn-b", f"{span}: learn again", "both", "learn", 80), bars=bars),
            dict(stage("rehearse", f"{span}: rehearse at 80%", "both", "rehearse", 80, final=True), bars=bars)]


def _lesson(req: dict, st: dict, file: str, hand: str) -> dict:
    spec = st["stage"]
    learn = spec["mode"] == "learn"
    steps = [{"id": "read", "type": "read", "text": f"A drill for {req['title']}, which slipped in recent passes."
              + (" Listen first, then learn it." if spec.get("listen") else "")}]
    if spec.get("listen"):
        steps.append({"id": "listen", "type": "listen", "file": file, "hand": hand, "bars": spec["bars"],
                      "tempo_percent": spec["tempo_percent"]})
    steps.append({"id": "play", "type": "play", "file": file, "hand": hand, "bars": spec["bars"], "mode": spec["mode"],
                  "tempo_percent": spec["tempo_percent"], "graded": True,
                  "pass": {"metric": "notes", "min": 90} if learn else
                          {"metric": "overall", "min": 75, "tempo_min_pct": 70}})
    return {"id": st["id"], "version": 1, "made": "atlas.drills", "checked": True, "requirement": req["id"], "steps": steps}


def add_drill(base: dict, node: str, step_id: str, bar: int, file: str, hand: str, first_bar: int = 1) -> dict | None:
    """The drill for a bar of a step (None when the bar is already being drilled).
    base: the tree with the temporary nodes merged in (a song goal's stages can slip too)."""
    nodes = temporary.load()
    if covered(node, step_id, bar, nodes):
        return None
    did, taken, k = drill_id(node, bar), {n["id"] for n in nodes}, 1
    while did in taken:  # the bar slips again after its drill retired: a fresh one, whose stages start unpractised
        k += 1
        did = f"{drill_id(node, bar)}.r{k}"
    source = base["by_id"].get(node) or {}
    tier = source.get("tier") or base["tiers"][0]["id"]
    first, last = max(first_bar, bar - NEIGHBOURS), bar + NEIGHBOURS
    leads = source.get("requirement") or (node if source.get("level") == "requirement" else None)
    req = {"id": did, "level": "requirement", "parent": f"{tier}.goals", "tier": tier, "strand": source.get("strand") or "pieces",
           "family": f"{tier}.goals", "kind": "drill", "title": f"Drill: {source.get('title', node)}, bar {bar}",
           "prereqs": [], "before": [leads] if leads else [], "covers": [], "temporary": True, "goal": GOAL, "status": "active",
           "source": {"node": node, "step": step_id, "bar": bar, "bars": f"{first}-{last}"}}
    stage_nodes = temporary._stage_nodes(req, stages(first, last))
    nodes += [req] + stage_nodes
    temporary.save(nodes)
    for st in stage_nodes:
        lesson = _lesson(req, st, file, hand)
        (temporary.lessons_dir() / f"{st['id']}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
    store.append_event("drill_created", node=did, source=req["source"])
    return req


def retire_proficient(states: dict) -> list[str]:
    """Drills whose final stage is Proficient (or better) move to the past layer."""
    nodes = temporary.load()
    done = []
    for n in active(nodes):
        final = next((s for s in nodes if s.get("parent") == n["id"] and s.get("final")), None)
        if final and mastery.rank((states.get(final["id"]) or {}).get("level", "not_started")) >= mastery.rank("proficient"):
            n["status"] = "past"
            done.append(n)
    if done:
        temporary.save(nodes)
        for n in done:
            store.append_event("drill_retired", node=n["id"], source=n.get("source"))
    return [n["id"] for n in done]
