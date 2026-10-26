"""Mastery: how far along every node of the Atlas is, worked out from what you did.

Pure functions over the tree, graded attempts and events, so progress can always be
rebuilt from the takes and the event log (store.py keeps only a cache).

Stage levels:
  not started -> practised   anything done on it
              -> proficient  every graded step passed since the last demotion
              -> mastered    every graded step passed again on a later day
Passing a later stage of a requirement credits the earlier ones (they become proficient
at that moment), placement credits a whole tier, and a failed recheck or review item
demotes a node back to proficient. A requirement is as far along as its last stage;
families, strands and tiers show a ring (the share of their requirements proficient or
better) and point at their weakest child.
"""

from __future__ import annotations

import datetime as dt

LEVELS = ("not_started", "practised", "proficient", "mastered")
RECHECK_DAYS = 30
REVIEW_PASS = 0.8       # share of review items passed for the review node to count
EXAM_PROFICIENT, EXAM_MASTERED = 100, 120  # Pass / Merit
DEFAULT_STEPS = ("main",)  # a stage with no lesson yet: one graded step


def rank(level: str) -> int:
    return LEVELS.index(level)


def _day(at: str) -> str:
    return at[:10]


def _blank() -> dict:
    return {"level": "not_started", "practised_at": None, "proficient_at": None, "mastered_at": None,
            "last_pass": None, "last_at": None, "credited": False}


def _stage_state(steps: tuple[str, ...], history: list[tuple]) -> dict:
    """history: time-ordered (at, kind, payload); kinds: attempt {step, passed}, touch, demote, credit."""
    st = _blank()
    passes: dict[str, list[str]] = {}  # step -> pass times since the last demotion
    for at, kind, payload in history:
        st["last_at"] = at
        if kind in ("attempt", "touch") and st["level"] == "not_started":
            st["level"], st["practised_at"] = "practised", at
        if kind == "attempt" and payload.get("passed"):
            passes.setdefault(payload.get("step") or DEFAULT_STEPS[0], []).append(at)
            st["last_pass"] = at
            if rank(st["level"]) < rank("proficient") and all(s in passes for s in steps):
                st["level"], st["proficient_at"] = "proficient", at
            if st["level"] == "proficient" and st["proficient_at"]:
                after = _day(st["proficient_at"])
                if all(any(_day(t) > after for t in passes.get(s, [])) for s in steps):
                    st["level"], st["mastered_at"] = "mastered", at
        elif kind == "demote":
            st.update(level="proficient", proficient_at=at, mastered_at=None, credited=False)
            st["practised_at"] = st["practised_at"] or at
            passes = {}
        elif kind == "credit" and rank(st["level"]) < rank("proficient"):
            st.update(level="proficient", proficient_at=at, credited=True)
            st["practised_at"] = st["practised_at"] or at
    return st


def compute(atlas: dict, attempts: list[dict], events: list[dict], graded_steps: dict[str, list[str]] | None = None) -> dict:
    """{node id: state}. attempts: {node, step, passed, score, at}; events: {type, at, node?,
    tier?, ...} with types touch (read/listen done), demote, credit, placement_credit,
    review_session {tier, passed_pct}, exam_result {tier, total}."""
    graded_steps = graded_steps or {}
    by_id = atlas.get("by_id") or {n["id"]: n for n in atlas["nodes"]}
    stages = [n for n in atlas["nodes"] if n["level"] == "stage"]
    hist: dict[str, list[tuple]] = {}
    for a in attempts:
        if a.get("node") in by_id:
            hist.setdefault(a["node"], []).append((a["at"], "attempt", a))
    for e in events:
        kind = e.get("type")
        if kind == "placement_credit":
            for s in stages:
                if s["tier"] == e.get("tier"):
                    hist.setdefault(s["id"], []).append((e["at"], "credit", e))
        elif kind in ("touch", "demote", "credit") and e.get("node") in by_id:
            node = by_id[e["node"]]
            targets = [node["id"]] if node["level"] == "stage" else node.get("stages", [])[-1:]  # a requirement: its last stage
            for t in targets:
                hist.setdefault(t, []).append((e["at"], kind, e))

    def run() -> dict[str, dict]:
        return {s["id"]: _stage_state(tuple(graded_steps.get(s["id"]) or DEFAULT_STEPS), sorted(hist.get(s["id"], []), key=lambda h: h[0]))
                for s in stages}

    states = run()
    # Passing a later stage credits the earlier stages of the same requirement.
    added = False
    for req in (n for n in atlas["nodes"] if n["level"] == "requirement"):
        ids = req.get("stages", [])
        for i in range(len(ids) - 1, 0, -1):
            later = states[ids[i]]
            if later["proficient_at"] is None or later["credited"]:
                continue
            for j in range(i):
                earlier = states[ids[j]]
                if earlier["proficient_at"] is None or earlier["proficient_at"] > later["proficient_at"]:
                    hist.setdefault(ids[j], []).append((later["proficient_at"], "credit", {"from": ids[i]}))
                    added = True
    if added:
        states = run()

    out: dict[str, dict] = dict(states)
    for req in (n for n in atlas["nodes"] if n["level"] == "requirement"):
        ids = req.get("stages", [])
        final = dict(states[ids[-1]]) if ids else _blank()
        touched = [states[i] for i in ids if states[i]["level"] != "not_started"]
        if final["level"] == "not_started" and touched:
            final["level"] = "practised"
            final["practised_at"] = min(t["practised_at"] for t in touched)
        final["last_at"] = max((states[i]["last_at"] for i in ids if states[i]["last_at"]), default=None)
        out[req["id"]] = final
    _clusters(atlas, out)
    _gates(atlas, out, events)
    return out


def _clusters(atlas: dict, out: dict) -> None:
    """Rings and weakest children for families, strands and tiers."""
    children: dict[str, list[dict]] = {}
    for n in atlas["nodes"]:
        if n.get("parent"):
            children.setdefault(n["parent"], []).append(n)
    reqs_under: dict[str, list[str]] = {}
    for n in atlas["nodes"]:
        if n["level"] == "requirement":
            # A goal's temporary nodes count in their own family, not in the syllabus's rings.
            ancestors = (n["family"],) if n.get("temporary") else (n["family"], f"{n['tier']}.{n['strand']}", n["tier"])
            for anc in ancestors:
                reqs_under.setdefault(anc, []).append(n["id"])
    for level in ("family", "strand", "tier"):
        for n in (x for x in atlas["nodes"] if x["level"] == level):
            reqs = reqs_under.get(n["id"], [])
            done = sum(1 for r in reqs if rank(out[r]["level"]) >= rank("proficient"))
            kids = [k for k in children.get(n["id"], []) if k["level"] in ("family", "strand", "requirement") and k["id"] in out]
            weakest = min(kids, key=lambda k: _weakness(out[k["id"]]), default=None)
            out[n["id"]] = {"ring": round(done / len(reqs), 3) if reqs else 0.0, "done": done, "total": len(reqs),
                            "weakest": weakest["id"] if weakest else None,
                            "last_at": max((out[r]["last_at"] for r in reqs if out[r]["last_at"]), default=None)}


def _weakness(state: dict) -> tuple:
    """Sort key: lowest first. Clusters by ring, nodes by level; then the longest untouched."""
    level = state["ring"] * 3 if "ring" in state else rank(state["level"])
    return (level, state.get("last_at") or "")


def _gates(atlas: dict, out: dict, events: list[dict]) -> None:
    """Review and Exam nodes, from review sessions and mock exam results."""
    for n in atlas["nodes"]:
        if n["level"] not in ("review", "exam"):
            continue
        st = _blank()
        mine = sorted((e for e in events if e.get("tier") == n["tier"]
                       and e.get("type") == ("review_session" if n["level"] == "review" else "exam_result")), key=lambda e: e["at"])
        for e in mine:
            st["last_at"] = e["at"]
            if st["level"] == "not_started":
                st["level"], st["practised_at"] = "practised", e["at"]
            if n["level"] == "review":
                if e.get("passed_pct", 0) >= REVIEW_PASS * 100:
                    if st["proficient_at"] and _day(e["at"]) > _day(st["proficient_at"]):
                        st["level"], st["mastered_at"] = "mastered", st["mastered_at"] or e["at"]
                    elif not st["proficient_at"]:
                        st["level"], st["proficient_at"] = "proficient", e["at"]
            else:
                total = e.get("total", 0)
                st["best"] = max(st.get("best", 0), total)
                if total >= EXAM_MASTERED:
                    st["level"] = "mastered"
                    st["mastered_at"] = st["mastered_at"] or e["at"]
                    st["proficient_at"] = st["proficient_at"] or e["at"]
                elif total >= EXAM_PROFICIENT and rank(st["level"]) < rank("proficient"):
                    st["level"], st["proficient_at"] = "proficient", e["at"]
        out[n["id"]] = st


def recheck_due(state: dict, today: dt.date | None = None) -> bool:
    """A mastered node whose last pass is more than RECHECK_DAYS old (checked only when a
    Path goes through it)."""
    if state.get("level") != "mastered" or not state.get("last_pass"):
        return False
    today = today or dt.date.today()
    return (today - dt.date.fromisoformat(_day(state["last_pass"]))).days > RECHECK_DAYS


def review_items(atlas: dict, states: dict, tier: str, count: int = 10) -> list[str]:
    """The tier review: requirements of the tier, weakest first (lowest level, then the
    longest since practised); not-started ones last, as a review rechecks what you know."""
    reqs = [n["id"] for n in atlas["nodes"] if n["level"] == "requirement" and n["tier"] == tier]
    known = [r for r in reqs if states[r]["level"] != "not_started"]
    rest = [r for r in reqs if states[r]["level"] == "not_started"]
    known.sort(key=lambda r: _weakness(states[r]))
    return (known + rest)[:count]


def path_families(atlas: dict, states: dict, targets: list[str], today: dt.date | None = None,
                  extra_prereqs: dict[str, list[str]] | None = None, first: list[str] | None = None) -> list[dict]:
    """A goal's Path: every requirement the targets need (their prerequisites, recursively)
    that isn't proficient yet - or is mastered but due a recheck - in an order that keeps
    prerequisites first, then by tier, strand and position; grouped into families in the
    order their first requirement comes up. extra_prereqs: temporary bridge nodes' links.
    first: requirements to bring forward (a placement exam's weak items), in that order, as
    soon as their own prerequisites allow.
    Returns [{family, requirements: [{id, recheck}]}]."""
    by_id = atlas.get("by_id") or {n["id"]: n for n in atlas["nodes"]}
    extra_prereqs = extra_prereqs or {}
    tier_order = {t["id"]: t["order"] for t in atlas["tiers"]}
    strand_order = {s["id"]: k for k, s in enumerate(atlas["strands"])}
    position = {n["id"]: k for k, n in enumerate(atlas["nodes"])}

    def requirements_of(node_id: str) -> list[str]:
        n = by_id.get(node_id)
        if n is None:
            return [node_id] if node_id in extra_prereqs else []
        if n["level"] == "requirement":
            return [n["id"]]
        if n["level"] == "stage":
            return [n["requirement"]]
        if n["level"] in ("review", "exam", "tier"):
            return [r["id"] for r in atlas["nodes"] if r["level"] == "requirement" and r["tier"] == n["tier"]]
        key = "family" if n["level"] == "family" else None
        return [r["id"] for r in atlas["nodes"] if r["level"] == "requirement"
                and (r.get(key) == n["id"] if key else f"{r['tier']}.{r['strand']}" == n["id"])]

    def prereqs(rid: str) -> list[str]:
        if rid in extra_prereqs:
            raw = extra_prereqs[rid]
        else:
            raw = by_id[rid].get("prereqs", [])
        return [r for p in raw for r in requirements_of(p)]

    wanted: set[str] = set()
    stack = [r for t in targets for r in requirements_of(t)]
    while stack:
        rid = stack.pop()
        if rid in wanted:
            continue
        wanted.add(rid)
        stack += prereqs(rid)

    def needed(rid: str) -> tuple[bool, bool]:
        st = states.get(rid)
        if st is None:
            return True, False
        if rank(st["level"]) < rank("proficient"):
            return True, False
        return recheck_due(st, today), True

    keep = {}
    for rid in wanted:
        need, recheck = needed(rid)
        if need:
            keep[rid] = recheck

    lead = {r: k for k, r in enumerate(first or [])}

    def sort_key(rid: str) -> tuple:
        n = by_id.get(rid)
        if n is None:
            return (len(lead), 99, 99, 0)
        return (lead.get(rid, len(lead)), tier_order[n["tier"]], strand_order[n["strand"]], position[rid])

    # Kahn's algorithm over the kept requirements, taking the earliest-placed ready one first.
    indeg = {r: 0 for r in keep}
    after: dict[str, list[str]] = {r: [] for r in keep}
    for r in keep:
        for p in set(prereqs(r)):
            if p in keep and p != r:
                indeg[r] += 1
                after[p].append(r)
    ready = sorted((r for r in keep if indeg[r] == 0), key=sort_key)
    order: list[str] = []
    while ready:
        r = ready.pop(0)
        order.append(r)
        for nxt in after[r]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=sort_key)
    order += sorted((r for r in keep if r not in order), key=sort_key)  # a cycle (shouldn't happen): append

    families: list[dict] = []
    index: dict[str, dict] = {}
    for r in order:
        fam = by_id[r]["family"] if r in by_id else f"bridge:{r}"
        if fam not in index:
            index[fam] = {"family": fam, "requirements": []}
            families.append(index[fam])
        index[fam]["requirements"].append({"id": r, "recheck": keep[r]})
    return families
