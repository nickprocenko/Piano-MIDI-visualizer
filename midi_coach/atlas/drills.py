"""Remedial drills: a short drill node for a bar you keep tripping on.

Every graded play pass records the bars it slipped in (the notes it expected there) as a
'slips' event. When the same bar, with some of the same notes, slipped in 2 of the last 3
passes of a step, a drill node 'drill.<node>.<bar>' joins the Atlas margin lane: a short
requirement on that bar (with a bar either side) that reuses the step's own file, hand and
part choice: listen at 70% and learn it, learn it again, then rehearse it at 80%.
Drills never spawn drills, and one that is Proficient retires to the past layer.
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


def record_pass(node: str, step: str, report: dict | None, live: dict | None) -> dict:
    """Log a graded pass's slips (an empty pass too: it breaks a run of slips)."""
    bars = slip_bars(report, live)
    store.append_event("slips", node=node, step=step, bars={str(b): n for b, n in bars.items()})
    return bars


def repeated(node: str, step: str, events: list[dict] | None = None) -> list[int]:
    """Bars that slipped, with overlapping notes, in at least REPEATS of the step's last WINDOW passes."""
    events = store.read_events() if events is None else events
    passes = [e["bars"] for e in events if e.get("type") == "slips" and e.get("node") == node and e.get("step") == step][-WINDOW:]
    if len(passes) < REPEATS:
        return []
    out = []
    for bar in sorted({int(b) for p in passes for b in p}):
        sets = [set(p[str(bar)]) for p in passes if str(bar) in p]
        if any(sum(1 for t in sets if t & s) >= REPEATS for s in sets):
            out.append(bar)
    return out


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
    """The drill for a bar of a step (None when it already has an active one)."""
    nodes = temporary.load()
    did = drill_id(node, bar)
    if any(n["id"] == did and n.get("status", "active") == "active" for n in nodes):
        return None
    source = base["by_id"].get(node) or {}
    tier = source.get("tier") or base["tiers"][0]["id"]
    first, last = max(first_bar, bar - NEIGHBOURS), bar + NEIGHBOURS
    req = {"id": did, "level": "requirement", "parent": f"{tier}.goals", "tier": tier, "strand": source.get("strand") or "pieces",
           "family": f"{tier}.goals", "kind": "drill", "title": f"Drill: {source.get('title', node)}, bar {bar}",
           "prereqs": [], "before": [], "covers": [], "temporary": True, "goal": GOAL, "status": "active",
           "source": {"node": node, "step": step_id, "bar": bar}}
    nodes = [n for n in nodes if not (n["id"] == did or n.get("parent") == did)]  # a retired drill returning
    stage_nodes = temporary._stage_nodes(req, stages(first, last))
    nodes += [req] + stage_nodes
    temporary.save(nodes)
    for st in stage_nodes:
        lesson = _lesson(req, st, file, hand)
        (temporary.lessons_dir() / f"{st['id']}.json").write_text(json.dumps(lesson, indent=1, ensure_ascii=False), encoding="utf-8")
    return req


def retire_proficient(states: dict) -> list[str]:
    """Drills whose final stage is Proficient (or better) move to the past layer."""
    nodes = temporary.load()
    done = []
    for n in nodes:
        if n.get("kind") == "drill" and n.get("status", "active") == "active":
            final = next((s for s in nodes if s.get("parent") == n["id"] and s.get("final")), None)
            if final and mastery.rank((states.get(final["id"]) or {}).get("level", "not_started")) >= mastery.rank("proficient"):
                n["status"] = "past"
                done.append(n["id"])
    if done:
        temporary.save(nodes)
    return done
