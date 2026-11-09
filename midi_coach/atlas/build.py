"""Build the Atlas (atlas.json) from the syllabus facts and the family templates.

Deterministic, no AI: the same syllabus always gives the same tree, ids and positions,
so progress recorded against a node id survives a rebuild.

    python -m midi_coach.atlas.build [syllabus.json] [--out atlas.json]
"""

from __future__ import annotations

import json
import pathlib
import sys

from . import STRANDS, content_dir, familiar, first_steps, load_syllabus, templates
from .layout import layout

VERSION = 1

# Sight-reading features that build on a theory topic (by topic id).
SIGHT_THEORY = {
    "tied notes": "slurs-ties", "slurs": "slurs-ties", "anacrusis": "anacrusis", "triplet": "triplets",
    "semiquaver": "semiquavers", "dotted crotchet": "dotted-crotchet", "dotted minim": "dotted-minim-semibreve",
    "semibreve": "dotted-minim-semibreve", "accidental": "accidentals", "chromatic notes": "accidentals",
    "mf and mp": "dynamics-mid", "hairpins": "dynamics-mid", "f and p": "dynamics-f-p", "staccato": "legato-staccato",
    "legato": "legato-staccato", "ornament": "ornaments-1", "clef change": "ledger-lines", "syncopation": "grouping-notes",
    "minims, crotchets": "note-values-basic",
}
# Aural skills (by prefix) that build on a theory topic.
AURAL_THEORY = {"cadence-chords": "chords-in-key", "cadence": "cadences", "modulation": "modulation",
                "texture-structure": "texture-structure", "style-period": "style-periods", "tonality": "minor-forms",
                "metre": "time-3-4"}
# Aural skills answered by describing the music: each grade's builds on the last.
DESCRIBE = {"dynamics", "articulation", "tempo", "tonality", "character", "style-period", "texture-structure",
            "features-any", "describe-features"}


class Tree:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.by_id: dict[str, dict] = {}

    def add(self, node: dict) -> dict:
        if node["id"] in self.by_id:
            raise ValueError(f"Duplicate node id {node['id']}")
        node.setdefault("prereqs", [])
        self.nodes.append(node)
        self.by_id[node["id"]] = node
        return node

    def family(self, tier: str, strand: str, key: str, title: str) -> dict:
        fid = f"{tier}.{strand}.{key}"
        return self.by_id.get(fid) or self.add({"id": fid, "level": "family", "parent": f"{tier}.{strand}",
                                                 "tier": tier, "strand": strand, "title": title})

    def requirement(self, family: dict, key: str, title: str, kind: str, stages: list[dict], **extra) -> dict:
        req = self.add({"id": f"{family['id']}.{key}", "level": "requirement", "parent": family["id"],
                        "tier": family["tier"], "strand": family["strand"], "family": family["id"],
                        "title": title, "kind": kind, **extra})
        req["stages"] = []
        for k, st in enumerate(stages):
            node = self.add({"id": f"{req['id']}.{st['key']}", "level": "stage", "parent": req["id"],
                             "tier": req["tier"], "strand": req["strand"], "family": family["id"],
                             "requirement": req["id"], "title": st["title"], "kind": kind, "stage": st,
                             "final": bool(st.get("final"))})
            if k:
                node["prereqs"].append(req["stages"][-1])
            req["stages"].append(node["id"])
        return req


def build(syllabus: dict, catalog: list[dict] | None = None, first: bool = True) -> dict:
    """first: put the coach's own beginner tiers (First steps, Ready to read) before the
    syllabus's first grade."""
    tree = Tree()
    grades = sorted(syllabus["grades"], key=lambda g: g["order"])
    order = {g["id"]: g["order"] for g in grades}
    theory = {t["grade"]: t["topics"] for t in syllabus.get("theory", [])}
    speeds = syllabus.get("speeds", {})
    pieces = catalog or []

    for g in grades:
        gid = g["id"]
        tree.add({"id": gid, "level": "tier", "title": g["title"], "order": g["order"], "tier": gid})
        for s in STRANDS:
            tree.add({"id": f"{gid}.{s['id']}", "level": "strand", "parent": gid, "tier": gid, "strand": s["id"],
                      "title": f"{g['title']} · {s['title']}"})

        # Pieces: one family per list; requirements come from the piece catalog.
        for lst in ("A", "B", "C"):
            fam = tree.family(gid, "pieces", f"list-{lst.lower()}", f"List {lst}")
            for p in pieces:
                if p.get("grade") == gid and p.get("list") == lst:
                    tree.requirement(fam, templates.slug(p["id"]), p["title"] + (f" ({p['composer'].split()[-1]})" if p.get("composer") else ""), "piece",
                                     templates.piece_stages(int(p.get("bars") or 16), int(p.get("first_bar", 1))), piece=p["id"],
                                     covers=list(p.get("covers", [])))

        # Scales and arpeggios.
        for item in g.get("technique", []):
            fkey = templates.technique_family(item)
            fam = tree.family(gid, "technique", fkey, templates.TECHNIQUE_FAMILIES[fkey])
            for spec in templates.expand_technique(item, gid, speeds):
                variant = spec["artic"] == "staccato" and spec.get("both_artics")
                tree.requirement(fam, templates.technique_id(spec), templates.technique_title(spec), "technique",
                                 templates.technique_stages(spec, variant), spec=spec,
                                 covers=templates.technique_covers(spec))

        # Sight-reading: new keys and times, new features, then the grade's standard.
        sight = g.get("sight", {})
        if sight.get("keys") or sight.get("times"):
            fam = tree.family(gid, "sight", "keys-times", "New keys & times")
            for key in sight.get("keys", []):
                minor = key.endswith("m")
                title = f"Reading in {templates.pretty_key(key[:-1] if minor else key)} {'minor' if minor else 'major'}"
                tree.requirement(fam, "key-" + templates.slug(key), title, "sight", templates.sight_stages("feature"),
                                 covers=[f"key:{key}"], spec={"key": key})
            for time in sight.get("times", []):
                tree.requirement(fam, "time-" + templates.slug(time), f"Reading in {time}", "sight",
                                 templates.sight_stages("feature"), covers=[f"time:{time}"], spec={"time": time})
        feats = list(sight.get("features", [])) + ([sight["hands"]] if sight.get("hands") else [])
        if feats:
            fam = tree.family(gid, "sight", "features", "New features")
            for f in feats:
                tree.requirement(fam, templates.slug(f)[:48], f[0].upper() + f[1:], "sight",
                                 templates.sight_stages("feature"), covers=[f"sight:{templates.slug(f)}"], spec={"feature": f})
        fam = tree.family(gid, "sight", "standard", "At grade standard")
        tree.requirement(fam, "standard", f"{g['title']} sight-reading ({sight.get('bars', '')} bars)".replace(" ( bars)", ""),
                         "sight", templates.sight_stages("standard"), spec={"standard": sight})

        # Aural tests.
        fam = tree.family(gid, "aural", "tests", "Aural tests")
        for test in g.get("aural", []):
            tree.requirement(fam, templates.slug(test["id"]), f"{test['test']}. {test['title']}", "aural",
                             templates.aural_stages(test), spec=test, covers=[f"aural:{s}" for s in test["skills"]])

        # Theory, practised at the keyboard (the coach's own progression).
        topics = theory.get(gid, [])
        if topics:
            fam = tree.family(gid, "theory", "topics", "Theory")
            for t in topics:
                tree.requirement(fam, templates.slug(t["id"]), t["title"], "theory", templates.theory_stages(),
                                 covers=list(t.get("covers", [])), spec={"topic": t["id"]})

        tree.add({"id": f"{gid}.review", "level": "review", "parent": gid, "tier": gid, "title": f"{g['title']} review"})
        tree.add({"id": f"{gid}.exam", "level": "exam", "parent": gid, "tier": gid, "title": f"{g['title']} mock exam",
                  "prereqs": [f"{gid}.review"] + [f"{e.split(':')[1]}.{e.split(':')[0]}" for e in g.get("entry", [])]})

    _link(tree, order)
    familiar.add(tree, list(order))
    young = first_steps.add(tree, order) if first else []
    for n in tree.nodes:  # first stages follow the requirement's own prerequisites
        if n["level"] == "requirement" and n.get("stages"):
            first = tree.by_id[n["stages"][0]]
            first["prereqs"] = _final_stages(tree, n["prereqs"])
    atlas = {"version": VERSION, "source": syllabus.get("source"), "syllabus_version": syllabus.get("version"),
             "strands": STRANDS, "tiers": young + [{"id": g["id"], "title": g["title"], "order": g["order"]} for g in grades],
             "nodes": tree.nodes}
    layout(atlas)
    return atlas


def _final_stages(tree: Tree, ids: list[str]) -> list[str]:
    out = []
    for i in ids:
        n = tree.by_id.get(i)
        if n and n["level"] == "requirement" and n.get("stages"):
            out.append(n["stages"][-1])
    return out


def _link(tree: Tree, order: dict[str, int]) -> None:
    """Requirement prerequisites: the same skill at an earlier grade, the easier form of it
    (hands separately before together, legato before staccato, the scale before its
    arpeggio), and across strands (a key's signature before its scale, a scale before
    reading in that key, theory before the sight-reading feature that uses it)."""
    reqs = [n for n in tree.nodes if n["level"] == "requirement"]
    g = lambda n: order[n["tier"]]  # noqa: E731

    def latest(cands: list[dict], at_most: int, strict: bool = False) -> dict | None:
        ok = [c for c in cands if (g(c) < at_most if strict else g(c) <= at_most)]
        return max(ok, key=lambda c: (g(c), reqs.index(c))) if ok else None

    tech = [r for r in reqs if r["kind"] == "technique"]
    theory = [r for r in reqs if r["kind"] == "theory"]

    def theory_for(cover: str, at: int) -> dict | None:
        hits = [t for t in theory if cover in t.get("covers", []) or (cover.startswith("key:") and "key:all" in t.get("covers", []))]
        return latest(hits, at)

    for r in reqs:
        pre: list[dict | None] = []
        if r["kind"] == "technique":
            s = r["spec"]
            same = lambda o, **kw: [x for x in tech if x is not r and all(x["spec"].get(k) == v for k, v in kw.items())]  # noqa: E731
            earlier = latest(same(r, type=s["type"], tonic=s.get("tonic"), quality=s.get("quality"), artic="legato"), g(r), strict=True)
            pre.append(earlier)
            if s.get("hands") == "together" and not (earlier and earlier["spec"].get("hands") == "together"):
                pre.append(latest(same(r, type=s["type"], tonic=s.get("tonic"), quality=s.get("quality"), hands="separate"), g(r)))
            if s["artic"] == "staccato" and s.get("both_artics"):
                pre += same(r, **{k: s.get(k) for k in ("type", "tonic", "quality", "form", "hands", "octaves")}, artic="legato")
            if s.get("form") == "melodic":
                pre += same(r, type=s["type"], tonic=s.get("tonic"), quality="minor", form="harmonic", artic=s["artic"], hands=s.get("hands"))
            if s["type"] in ("arpeggio", "contrary", "third_apart", "sixth_apart", "thirds", "sixths"):
                pre.append(latest(same(r, type="scale", tonic=s.get("tonic"), quality=s.get("quality"), artic="legato"), g(r)))
            if s["type"] == "dom7":
                pre.append(latest(same(r, type="arpeggio", tonic=s.get("tonic"), quality="major", artic="legato"), g(r)))
            for c in r.get("covers", []):
                if c.startswith("key:"):
                    pre.append(theory_for(c, g(r)))
            if s["type"] in ("chromatic", "chromatic_contrary", "chromatic_apart"):
                pre.append(latest([t for t in theory if t["spec"]["topic"] == "chromatic-scale"], g(r)))
        elif r["kind"] == "sight":
            spec = r.get("spec", {})
            if "key" in spec:
                key = spec["key"]
                minor = key.endswith("m")
                tonic = key[:-1] if minor else key
                pre.append(latest([x for x in tech if x["spec"]["type"] == "scale" and x["spec"].get("tonic") == tonic
                                   and x["spec"].get("quality") == ("minor" if minor else "major")], g(r)))
                pre.append(theory_for(f"key:{key}", g(r)))
            if "time" in spec:
                pre.append(theory_for(f"time:{spec['time']}", g(r)))
            if "feature" in spec:
                low = spec["feature"].lower()
                for word, topic in SIGHT_THEORY.items():
                    if word in low:
                        pre.append(latest([t for t in theory if t["spec"]["topic"] == topic], g(r)))
            if "standard" in spec:
                pre += [x for x in reqs if x["kind"] == "sight" and x["tier"] == r["tier"] and x is not r]
                pre.append(latest([x for x in reqs if x["kind"] == "sight" and "standard" in x.get("spec", {})], g(r), strict=True))
        elif r["kind"] == "aural":
            # The same test, or one using the same skill, at an earlier grade; failing that,
            # one answered the same way (singing back, tapping, describing).
            skills = set(r["spec"]["skills"])
            answers = {templates.AURAL_ANSWER.get(s, "quiz") for s in skills}
            earlier = [x for x in reqs if x["kind"] == "aural" and x is not r]
            stems = {s.split("-")[0] for s in skills} - {"metre", "rhythm"}  # 'cadence-pii' grows from 'cadence-perfect-imperfect'
            found = latest([x for x in earlier if x["spec"]["id"] == r["spec"]["id"] or skills & set(x["spec"]["skills"])
                            or stems & {s.split("-")[0] for s in x["spec"]["skills"]}], g(r), strict=True)
            for skill in skills:
                for prefix, topic in AURAL_THEORY.items():
                    if skill.startswith(prefix):
                        pre.append(latest([t for t in theory if t["spec"]["topic"] == topic], g(r)))
            for answer in sorted(answers - {"quiz"}):
                pre.append(latest([x for x in earlier if answer in {templates.AURAL_ANSWER.get(s, "quiz") for s in x["spec"]["skills"]}],
                                  g(r), strict=True))
            if skills & DESCRIBE:
                pre.append(latest([x for x in earlier if set(x["spec"]["skills"]) & DESCRIBE], g(r), strict=True))
            pre.append(found)
        elif r["kind"] == "theory":
            keyish = any(c.startswith("key:") for c in r.get("covers", []))
            if keyish:
                pre.append(latest([t for t in theory if t is not r and any(c.startswith("key:") for c in t.get("covers", []))],
                                  g(r), strict=True))
        r["prereqs"] = sorted({p["id"] for p in pre if p is not None and p is not r})


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    out = content_dir() / "atlas.json"
    if "--out" in args:
        k = args.index("--out")
        out = pathlib.Path(args[k + 1])
        del args[k:k + 2]
    syllabus = load_syllabus(args[0] if args else None)
    from .pieces import fetched, load_catalog

    catalog = [p for p in load_catalog() if fetched(p) and p.get("bars")]  # only pieces you have
    atlas = build(syllabus, catalog)
    out.write_text(json.dumps(atlas, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    counts: dict[str, int] = {}
    for n in atlas["nodes"]:
        counts[n["level"]] = counts.get(n["level"], 0) + 1
    print(f"{out}: {len(atlas['nodes'])} nodes " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
