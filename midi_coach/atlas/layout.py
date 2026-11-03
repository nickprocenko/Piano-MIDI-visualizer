"""Fixed positions for every node of the Atlas, and its edges bundled per zoom level.

Tiers are bands stacked top to bottom; in every tier the five strands are columns in the
same place, so a strand is a straight line down the page. Inside a strand column the
families stack, requirements sit in rows, and each requirement's stages hang below it
top to bottom. Every tier ends in its Review and Exam, centred under the strands, and
keeps a free lane at the right edge for temporary nodes (bridges, drills).

Positions never depend on progress or on temporary nodes, so the tree never moves: the
page zooms in on fixed coordinates and draws clusters (tiers, strands, families) when
zoomed out. Units are SVG user units.
"""

from __future__ import annotations

COLS = {"pieces": 5, "technique": 8, "sight": 5, "aural": 4, "theory": 5}  # requirements per row
REQ_W = 92          # requirement column width
REQ_HEAD = 34       # requirement title area
STAGE_DY = 24       # stage spacing
STAGE_R = 8
REQ_PAD = 10
FAM_HEAD = 30
FAM_GAP = 18
FAM_EMPTY = 44      # a family with no requirements yet (e.g. pieces before the catalog)
STRAND_PAD = 18
TIER_HEAD = 56
TIER_FOOT = 170     # room for the Review and Exam
TIER_GAP = 60
LANE_W = 240        # temporary nodes
LANE_SLOT_H = 44

ZOOM_LEVELS = ("tier", "strand", "family", "requirement", "stage")


def _req_height(req: dict) -> int:
    return REQ_HEAD + len(req.get("stages", [])) * STAGE_DY + REQ_PAD


def layout(atlas: dict) -> None:
    """Give every node a box [x, y, w, h] (stages: their circle's bounding box) and add
    atlas['geometry'] (overall size, strand columns, lanes) and atlas['bundles']."""
    nodes = atlas["nodes"]
    by_id = {n["id"]: n for n in nodes}
    children: dict[str, list[dict]] = {}
    for n in nodes:
        if n.get("parent"):
            children.setdefault(n["parent"], []).append(n)
    strands = [s["id"] for s in atlas["strands"]]
    col_w = {s: COLS[s] * REQ_W + 2 * STRAND_PAD for s in strands}
    col_x, x = {}, 0
    for s in strands:
        col_x[s] = x
        x += col_w[s]
    content_w = x
    width = content_w + LANE_W

    needs = _family_prereqs(nodes, by_id)
    y = 0
    lanes = []
    for tier in sorted((n for n in nodes if n["level"] == "tier"), key=lambda n: n["order"]):
        top = y
        bottom_content = top + TIER_HEAD
        # Families keep their order down their strand, but each one also starts below every
        # family of this tier it builds on, whatever the strand: a link never points up.
        queues = {s: [c for c in children.get(f"{tier['id']}.{s}", []) if c["level"] == "family"] for s in strands}
        cursor = {s: top + TIER_HEAD for s in strands}
        bottom: dict[str, float] = {}
        while any(queues.values()):
            ready = [s for s in strands if queues[s] and all(p in bottom for p in needs.get(queues[s][0]["id"], ()))]
            if not ready:  # links that disagree with a strand's order: place the earliest-starting one anyway
                ready = [min((s for s in strands if queues[s]), key=lambda s: cursor[s])]
            for s in ready:
                fam = queues[s].pop(0)
                fy = max([cursor[s]] + [bottom[p] + FAM_GAP for p in needs.get(fam["id"], ()) if p in bottom])
                cy = _place_family(fam, col_x[s] + STRAND_PAD, fy, COLS[s], children, by_id)
                bottom[fam["id"]] = cy
                cursor[s] = cy + FAM_GAP
        for s in strands:
            strand = by_id[f"{tier['id']}.{s}"]
            cy = cursor[s]
            strand["box"] = [col_x[s] + 4, top + TIER_HEAD - 12, col_w[s] - 8, max(cy - top - TIER_HEAD + 12, 40)]
            bottom_content = max(bottom_content, cy)
        height = bottom_content - top + TIER_FOOT
        tier["box"] = [0, top, width, height]
        mid = content_w / 2
        review, exam = by_id.get(f"{tier['id']}.review"), by_id.get(f"{tier['id']}.exam")
        if review:
            review["box"] = [mid - 80, top + height - TIER_FOOT + 26, 160, 46]
        if exam:
            exam["box"] = [mid - 90, top + height - TIER_FOOT + 96, 180, 56]
        for s in strands:  # strands reach down to the funnel
            strand = by_id[f"{tier['id']}.{s}"]
            strand["box"][3] = top + height - TIER_FOOT - strand["box"][1] + 4
        lanes.append({"tier": tier["id"], "box": [content_w + 10, top + TIER_HEAD, LANE_W - 20, height - TIER_HEAD - 20],
                      "slot_h": LANE_SLOT_H})
        y = top + height + TIER_GAP

    atlas["geometry"] = {"width": width, "height": y, "content_width": content_w,
                         "columns": [{"strand": s, "x": col_x[s], "w": col_w[s]} for s in strands],
                         "lanes": lanes, "stage_r": STAGE_R}
    atlas["bundles"] = bundles(nodes, by_id)


def _place_family(fam: dict, cx: float, fy: float, cols: int, children: dict, by_id: dict) -> float:
    """Box a family, its requirements (in rows of `cols`) and their stages from fy down;
    returns the family's bottom."""
    cy = fy + FAM_HEAD
    reqs = [c for c in children.get(fam["id"], []) if c["level"] == "requirement"]
    if not reqs:
        cy += FAM_EMPTY - FAM_HEAD + 14
    for row in range(0, len(reqs), cols):
        chunk = reqs[row:row + cols]
        row_h = max(_req_height(r) for r in chunk)
        for c, req in enumerate(chunk):
            rx = cx + c * REQ_W
            req["box"] = [rx + 4, cy, REQ_W - 8, _req_height(req)]
            for k, sid in enumerate(req.get("stages", [])):
                sx = rx + REQ_W / 2
                sy = cy + REQ_HEAD + k * STAGE_DY + STAGE_DY / 2
                by_id[sid]["box"] = [sx - STAGE_R, sy - STAGE_R, 2 * STAGE_R, 2 * STAGE_R]
        cy += row_h + 6
    fam["box"] = [cx - 6, fy, cols * REQ_W + 12, cy - fy + 4]
    return cy + 4


def _family_prereqs(nodes: list[dict], by_id: dict) -> dict[str, set[str]]:
    """{family: the other families of its tier that anything inside it builds on}."""
    out: dict[str, set[str]] = {}
    for n in nodes:
        for p in n.get("prereqs", []):
            if p not in by_id or n["level"] in ("tier", "strand", "review", "exam"):
                continue
            a, b = _ancestor(by_id[p], "family", by_id), _ancestor(n, "family", by_id)
            if a != b and by_id[a]["level"] == by_id[b]["level"] == "family" and a.split(".")[0] == b.split(".")[0]:
                out.setdefault(b, set()).add(a)
    return out


def _ancestor(node: dict, level: str, by_id: dict) -> str:
    """The node's cluster at a zoom level; review/exam nodes and anything coarser than the
    level stand for themselves."""
    if node["level"] in ("review", "exam"):
        return node["id"]
    want = ZOOM_LEVELS.index(level)
    n = node
    while ZOOM_LEVELS.index(n["level"]) > want and n.get("parent"):
        n = by_id[n["parent"]]
    return n["id"]


def bundles(nodes: list[dict], by_id: dict) -> dict:
    """{level: [[from, to, count], ...]} - one line per pair of clusters linked by any
    prerequisite inside them, at every zoom level (stage level: every stage edge)."""
    edges = [(by_id[p], n) for n in nodes for p in n.get("prereqs", []) if p in by_id]
    out: dict[str, list] = {}
    for level in ZOOM_LEVELS:
        counts: dict[tuple[str, str], int] = {}
        for a, b in edges:
            staged = a["level"] == "stage" or b["level"] == "stage"
            if staged != (level == "stage") and not {a["level"], b["level"]} & {"review", "exam"}:
                continue  # stage edges only at stage zoom; there the requirement edges they refine are left out
            ka, kb = _ancestor(a, level, by_id), _ancestor(b, level, by_id)
            if ka != kb:
                counts[(ka, kb)] = counts.get((ka, kb), 0) + 1
        out[level] = [[a, b, c] for (a, b), c in sorted(counts.items())]
    return out
