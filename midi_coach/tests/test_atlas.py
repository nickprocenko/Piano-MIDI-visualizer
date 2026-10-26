"""Tests for the Atlas: building the tree, its layout, and mastery. Uses the made-up sample
syllabus in midi_coach/atlas/sample (the real one lives only in the user's MidiCoach folder)."""

from __future__ import annotations

import datetime as dt
import time
import json

import pytest

from midi_coach import atlas as atlas_pkg
from midi_coach.atlas import build, layout, mastery, store

PIECE = {"id": "minuet-in-c", "title": "Minuet in C", "grade": "initial", "list": "A", "bars": 8}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MIDI_COACH_ATLAS_CONTENT", str(tmp_path / "content"))
    return tmp_path


@pytest.fixture()
def tree():
    syllabus = atlas_pkg.load_syllabus(atlas_pkg.SAMPLE / "syllabus.json")
    t = build.build(syllabus, [PIECE])
    t["by_id"] = {n["id"]: n for n in t["nodes"]}
    return t


def _req(tree, needle, tier=None):
    hits = [n for n in tree["nodes"] if n["level"] == "requirement" and needle in n["id"] and (tier is None or n["tier"] == tier)]
    assert len(hits) == 1, [h["id"] for h in hits]
    return hits[0]


# -- the tree ------------------------------------------------------------------------


def test_tree_shape(tree):
    by_id = tree["by_id"]
    assert len(by_id) == len(tree["nodes"])  # unique ids
    for tier in ("initial", "g1"):
        assert by_id[f"{tier}.review"]["level"] == "review" and by_id[f"{tier}.exam"]["prereqs"][0] == f"{tier}.review"
        for s in atlas_pkg.STRANDS:
            assert by_id[f"{tier}.{s['id']}"]["parent"] == tier
    assert "initial.theory" in by_id["g1.exam"]["prereqs"]  # an entry requirement
    for r in (n for n in tree["nodes"] if n["level"] == "requirement"):
        stages = [by_id[s] for s in r["stages"]]
        assert stages and stages[-1]["final"] and not any(s["final"] for s in stages[:-1])  # last stage = the requirement
        for a, b in zip(stages, stages[1:]):
            assert b["prereqs"] == [a["id"]]
    # Expansion: a minor scale whose forms and touches must all be prepared is 4 requirements.
    a_minor = [n for n in tree["nodes"] if n["level"] == "requirement" and n["tier"] == "g1" and "scale-a-minor" in n["id"]]
    assert sorted(n["title"] for n in a_minor) == sorted([
        "A harmonic minor · 1 oct · HT · legato", "A harmonic minor · 1 oct · HT · staccato",
        "A melodic minor · 1 oct · HT · legato", "A melodic minor · 1 oct · HT · staccato"])
    piece = _req(tree, "minuet-in-c")
    assert piece["family"] == "initial.pieces.list-a" and len(piece["stages"]) == 2 * 3 + 3  # two 4-bar sections


def test_prerequisites_cross_grades_and_strands(tree):
    by_id = tree["by_id"]
    title = lambda ids: sorted(by_id[i]["title"] for i in ids)  # noqa: E731
    c_ht = _req(tree, "scale-c-major", tier="g1")
    assert title(c_ht["prereqs"]) == ["C major", "C major · 1 oct · HS"]  # theory key, then the same scale hands separately
    stacc = _req(tree, "scale-a-minor-melodic-1oct-together-staccato")
    assert title(stacc["prereqs"]) == ["A harmonic minor · 1 oct · HT · staccato", "A melodic minor · 1 oct · HT · legato",
                                       "G major and A minor"]
    arp = _req(tree, "arpeggio-c-major")
    assert "C major · 1 oct · HS" in title(arp["prereqs"])
    reading_g = _req(tree, "sight.keys-times.key-g", tier="g1")
    assert title(reading_g["prereqs"]) == sorted(["G major · 1 oct · HT", "G major and A minor"])
    tied = _req(tree, "tied-notes")
    assert title(tied["prereqs"]) == ["Slurs and ties"]
    pulse1 = _req(tree, "pulse", tier="g1")
    assert "A. Tap the pulse" in title(pulse1["prereqs"])
    # First stages follow the requirement's own prerequisites (their last stages).
    first = by_id[c_ht["stages"][0]]
    assert sorted(first["prereqs"]) == sorted(by_id[p]["stages"][-1] for p in c_ht["prereqs"])
    # Acyclic.
    seen, done = set(), set()

    def visit(nid):
        assert nid not in seen or nid in done, f"cycle through {nid}"
        if nid in done:
            return
        seen.add(nid)
        for p in by_id[nid].get("prereqs", []):
            visit(p)
        done.add(nid)

    for n in tree["nodes"]:
        visit(n["id"])


def test_layout_fixed_and_non_overlapping(tree):
    by_id = tree["by_id"]
    for n in tree["nodes"]:
        assert len(n["box"]) == 4, n["id"]
    tiers = sorted((n for n in tree["nodes"] if n["level"] == "tier"), key=lambda n: n["order"])
    assert tiers[0]["box"][1] + tiers[0]["box"][3] < tiers[1]["box"][1]  # stacked top to bottom

    def inside(a, b):  # box a within box b
        return b[0] - 1e-6 <= a[0] and a[0] + a[2] <= b[0] + b[2] + 1e-6 and b[1] - 1e-6 <= a[1] and a[1] + a[3] <= b[1] + b[3] + 1e-6

    def overlap(a, b):
        return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]

    reqs = [n for n in tree["nodes"] if n["level"] == "requirement"]
    for r in reqs:
        assert inside(r["box"], by_id[r["family"]]["box"]), r["id"]
        assert inside(by_id[r["family"]]["box"], by_id[f"{r['tier']}.{r['strand']}"]["box"])
        for s in r["stages"]:
            assert inside(by_id[s]["box"], r["box"])
    for i, a in enumerate(reqs):
        for b in reqs[i + 1:]:
            assert not overlap(a["box"], b["box"]), (a["id"], b["id"])
    # Strands are columns in the same place in every tier; lanes sit right of the content.
    geo = tree["geometry"]
    for s in atlas_pkg.STRANDS:
        xs = {by_id[f"{t['id']}.{s['id']}"]["box"][0] for t in tiers}
        assert len(xs) == 1
    assert all(lane["box"][0] >= geo["content_width"] for lane in geo["lanes"])
    # Review and exam sit in the tier's foot, review above exam.
    for t in tiers:
        rv, ex = by_id[f"{t['id']}.review"]["box"], by_id[f"{t['id']}.exam"]["box"]
        assert inside(rv, t["box"]) and inside(ex, t["box"]) and rv[1] + rv[3] <= ex[1]


def test_bundles_per_zoom_level(tree):
    b = tree["bundles"]
    assert set(b) == set(layout.ZOOM_LEVELS)
    tier_pairs = {(x, y) for x, y, _ in b["tier"]}
    assert ("initial", "g1") in tier_pairs  # grade 1 builds on Initial
    stage_edges = {(x, y) for x, y, _ in b["stage"]}
    c_hs = _req(tree, "scale-c-major", tier="initial")
    assert (c_hs["stages"][0], c_hs["stages"][1]) in stage_edges  # the chain inside a requirement
    assert not any(tree["by_id"][x]["level"] == "requirement" and tree["by_id"][y]["level"] == "requirement"
                   for x, y in stage_edges)  # requirement edges are refined by stage edges there
    fam_counts = {(x, y): c for x, y, c in b["family"]}
    assert all(c >= 1 for c in fam_counts.values())


def test_real_syllabus_if_present():
    """The user's own tree (local only): big, and buildable."""
    real = __import__("pathlib").Path.home() / "MidiCoach" / "atlas" / "content" / "syllabus.json"
    if not real.is_file():
        pytest.skip("no local syllabus")
    t = build.build(json.loads(real.read_text(encoding="utf-8")))
    assert len(t["nodes"]) >= 2000
    assert len({n["id"] for n in t["nodes"]}) == len(t["nodes"])


# -- mastery ---------------------------------------------------------------------------


def _pass(node, at, step="main", passed=True):
    return {"node": node, "step": step, "passed": passed, "score": 95 if passed else 40, "at": at}


def test_levels_next_day_credit_and_demote(tree):
    c = _req(tree, "scale-c-major", tier="initial")
    rh, lh, speed = c["stages"]
    states = mastery.compute(tree, [], [])
    assert states[rh]["level"] == "not_started" and states[c["id"]]["level"] == "not_started"

    states = mastery.compute(tree, [_pass(rh, "2026-10-01 10:00:00", passed=False)], [])
    assert states[rh]["level"] == "practised" and states[c["id"]]["level"] == "practised"

    attempts = [_pass(rh, "2026-10-01 10:00:00"), _pass(rh, "2026-10-01 18:00:00")]
    assert mastery.compute(tree, attempts, [])[rh]["level"] == "proficient"  # same day twice: not yet mastered
    attempts.append(_pass(rh, "2026-10-02 09:00:00"))
    assert mastery.compute(tree, attempts, [])[rh]["level"] == "mastered"

    # Two graded steps: both must pass.
    graded = {lh: ["a", "b"]}
    assert mastery.compute(tree, [_pass(lh, "2026-10-01 10:00:00", "a")], [], graded)[lh]["level"] == "practised"
    assert mastery.compute(tree, [_pass(lh, "2026-10-01 10:00:00", "a"), _pass(lh, "2026-10-01 10:05:00", "b")], [], graded)[lh]["level"] == "proficient"

    # Passing the last stage credits the earlier ones, and the requirement follows its last stage.
    states = mastery.compute(tree, [_pass(speed, "2026-10-03 10:00:00")], [])
    assert states[speed]["level"] == "proficient" and states[c["id"]]["level"] == "proficient"
    assert states[rh]["level"] == "proficient" and states[rh]["credited"] and states[lh]["credited"]

    # A demotion drops a mastered stage to proficient; passing on a later day masters it again.
    attempts = [_pass(speed, "2026-10-01 10:00:00"), _pass(speed, "2026-10-02 10:00:00")]
    assert mastery.compute(tree, attempts, [])[speed]["level"] == "mastered"
    demote = [{"type": "demote", "node": c["id"], "at": "2026-11-05 10:00:00"}]
    assert mastery.compute(tree, attempts, demote)[speed]["level"] == "proficient"
    again = attempts + [_pass(speed, "2026-11-05 11:00:00")]
    assert mastery.compute(tree, again, demote)[speed]["level"] == "proficient"  # same day as the demotion
    again.append(_pass(speed, "2026-11-06 11:00:00"))
    assert mastery.compute(tree, again, demote)[speed]["level"] == "mastered"


def test_placement_rings_weakest_and_gates(tree):
    states = mastery.compute(tree, [], [{"type": "placement_credit", "tier": "initial", "at": "2026-10-01 10:00:00"}])
    initial_reqs = [n for n in tree["nodes"] if n["level"] == "requirement" and n["tier"] == "initial"]
    assert all(states[r["id"]]["level"] == "proficient" for r in initial_reqs)
    assert states["initial"]["ring"] == 1.0 and states["g1"]["ring"] == 0.0
    # Weakest child: the family with the lowest ring.
    c_ht = _req(tree, "scale-c-major", tier="g1")
    states = mastery.compute(tree, [_pass(c_ht["stages"][-1], "2026-10-01 10:00:00")], [])
    fam = states[c_ht["family"]]
    assert fam["done"] == 1 and fam["total"] == 6 and fam["weakest"] != c_ht["id"]
    assert states["g1.technique"]["weakest"] == "g1.technique.scales-ht"  # only family there
    # Review and exam nodes.
    ev = [{"type": "review_session", "tier": "g1", "passed_pct": 85, "at": "2026-10-01 10:00:00"},
          {"type": "exam_result", "tier": "g1", "total": 112, "at": "2026-10-02 10:00:00"}]
    states = mastery.compute(tree, [], ev)
    assert states["g1.review"]["level"] == "proficient" and states["g1.exam"]["level"] == "proficient"
    ev += [{"type": "review_session", "tier": "g1", "passed_pct": 90, "at": "2026-10-03 10:00:00"},
           {"type": "exam_result", "tier": "g1", "total": 124, "at": "2026-10-04 10:00:00"}]
    states = mastery.compute(tree, [], ev)
    assert states["g1.review"]["level"] == "mastered" and states["g1.exam"]["level"] == "mastered"
    assert states["g1.exam"]["best"] == 124


def test_recheck_and_review_items(tree):
    c = _req(tree, "scale-c-major", tier="initial")
    attempts = [_pass(c["stages"][-1], "2026-08-01 10:00:00"), _pass(c["stages"][-1], "2026-08-02 10:00:00")]
    states = mastery.compute(tree, attempts, [])
    assert states[c["id"]]["level"] == "mastered"
    assert not mastery.recheck_due(states[c["id"]], dt.date(2026, 8, 20))
    assert mastery.recheck_due(states[c["id"]], dt.date(2026, 9, 5))
    arp = _req(tree, "arpeggio-c-major", tier="initial")
    states = mastery.compute(tree, attempts + [_pass(arp["stages"][-1], "2026-08-03 10:00:00")], [])
    items = mastery.review_items(tree, states, "initial", count=3)
    assert items[:2] == [arp["id"], c["id"]]  # what you know, weakest (proficient) before mastered; then the rest


def test_path_orders_prerequisites_and_skips_known(tree):
    c_hs = _req(tree, "scale-c-major", tier="initial")
    reading_g = _req(tree, "sight.keys-times.key-g", tier="g1")
    path = mastery.path_families(tree, mastery.compute(tree, [], []), [reading_g["id"]])
    order = [r["id"] for f in path for r in f["requirements"]]
    titles = [tree["by_id"][r]["title"] for r in order]
    assert order[-1] == reading_g["id"]
    assert "G major · 1 oct · HT" in titles and titles.index("G major and A minor") < titles.index("G major · 1 oct · HT")
    # What's already proficient drops out; a mastered one due a recheck comes back, marked.
    g_ht = _req(tree, "scale-g-major", tier="g1")
    states = mastery.compute(tree, [_pass(g_ht["stages"][-1], "2026-10-01 10:00:00")], [])
    order2 = [r["id"] for f in mastery.path_families(tree, states, [reading_g["id"]]) for r in f["requirements"]]
    assert g_ht["id"] not in order2
    states = mastery.compute(tree, [_pass(g_ht["stages"][-1], "2026-06-01 10:00:00"), _pass(g_ht["stages"][-1], "2026-06-02 10:00:00")], [])
    path3 = mastery.path_families(tree, states, [reading_g["id"]], today=dt.date(2026, 10, 1))
    rech = {r["id"]: r["recheck"] for f in path3 for r in f["requirements"]}
    assert rech.get(g_ht["id"]) is True
    # Families are listed once each, in the order their first requirement comes up.
    fams = [f["family"] for f in path]
    assert len(fams) == len(set(fams))
    assert c_hs["family"] not in fams  # C major hands separately isn't needed for reading in G


def test_progress_rebuild_matches_and_caches(home, tree, monkeypatch):
    from midi_coach import library

    c = _req(tree, "scale-c-major", tier="initial")
    take = library.save_take([(0.0, [0x90, 60, 80]), (0.5, [0x80, 60, 0])], {"reference": None})
    take["atlas"] = {"node": c["stages"][0], "step": "main", "passed": True, "score": 96}
    take["created"] = "2026-10-01 10:00:00"
    library.update_take(take)
    store.append_event("quiz", node=c["stages"][1], step="main", passed=True, score=100, at="2026-10-01 10:05:00")
    store.append_event("touch", node=c["stages"][2], at="2026-10-01 10:06:00")
    direct = mastery.compute(tree, store.attempts(), store.read_events())
    cached = store.progress(tree)
    assert cached == json.loads(json.dumps(direct))
    assert cached[c["stages"][0]]["level"] == "proficient" and cached[c["stages"][1]]["level"] == "proficient"
    assert cached[c["stages"][2]]["level"] == "practised"
    assert store.progress(tree) == cached  # from the cache
    store.append_event("demote", node=c["stages"][0], at="2026-10-02 10:00:00")
    assert store.progress(tree)[c["stages"][0]]["proficient_at"] == "2026-10-02 10:00:00"  # the log changed: rebuilt


# -- running steps from the coach page ---------------------------------------------------


def test_page_runs_a_stage_and_grades_it(home, tree, monkeypatch):
    from midi_coach import display, library, midi_io, server
    from midi_coach.notes import load_score
    from midi_coach.tests.test_midi_coach import FakeIn, FakeOut, _post, _until, _write_reference

    monkeypatch.setitem(__import__("sys").modules, "rtmidi", __import__("types").SimpleNamespace(MidiIn=FakeIn, MidiOut=FakeOut))
    monkeypatch.setenv("MIDI_COACH_REFERENCE_DIRS", str(home / "refs"))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(home / "missing.json"))
    content = atlas_pkg.content_dir()
    (content / "lessons").mkdir(parents=True)
    etude = _write_reference(content / "lessons" / "etude.mid")
    (content / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    c = _req(tree, "scale-c-major", tier="initial")
    rh = c["stages"][0]
    lesson = {"id": rh, "version": 1, "steps": [
        {"id": "intro", "type": "read", "text": "Thumb under on F."},
        {"id": "q", "type": "quiz", "prompt": "Which finger plays F?", "options": ["1", "3", "4"], "answer": 0,
         "accept": ["thumb"], "graded": True},
        {"id": "play", "type": "play", "file": "etude.mid", "hand": "right", "bars": "1", "mode": "learn",
         "tempo_percent": 100, "graded": True, "pass": {"metric": "notes", "min": 90}}]}
    (content / "lessons" / f"{rh}.json").write_text(json.dumps(lesson), encoding="utf-8")
    library._score_cache.clear()

    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server._atlas, "hub", server.hub)
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    try:
        whole = _post(url + "atlas")
        assert len(whole["nodes"]) == len(tree["nodes"]) and whole["geometry"]["width"] > 0 and "stage" in whole["bundles"]
        found = _post(url + "search", {"q": "c major hs initial"})["results"]
        assert found[0]["id"] == c["id"]
        assert _post(url + "search", {"q": "A flat"})["results"] == []
        node = _post(url + "node", {"id": rh})
        assert [s["id"] for s in node["lesson"]["steps"]] == ["intro", "q", "play"]
        assert [t["level"] for t in node["trail"]] == ["tier", "strand", "family", "requirement", "stage"]

        _post(url + "step_start", {"node": rh, "step": "intro"})
        assert _post(url + "atlas")["states"][rh]["level"] == "practised"
        assert _post(url + "quiz_answer", {"node": rh, "step": "q", "answer": "3"})["passed"] is False
        assert _post(url + "quiz_answer", {"node": rh, "step": "q", "answer": "the thumb"})["passed"] is True

        started = _post(url + "step_start", {"node": rh, "step": "play", "port": "JUNO-DS 0"})
        assert started["mode"] == "wait", started
        _until(lambda: server.recorder.active and server._live.get("session") is not None and server.recorder.listener is not None)
        score = load_score(etude)
        for n in [n for n in score.notes if n.part == 0 and n.start < score.bars[1].start]:
            FakeIn.instance.send([0x90, n.pitch, 70])
            time.sleep(0.02)
            FakeIn.instance.send([0x80, n.pitch, 0])
        _until(lambda: not server._practice["running"] and library.list_takes() and "passed" in library.list_takes()[-1].get("atlas", {}))
        take = library.list_takes()[-1]
        assert take["atlas"]["node"] == rh and take["atlas"]["passed"] is True and take["atlas"]["score"] >= 90
        states = _post(url + "atlas")["states"]
        assert states[rh]["level"] == "proficient"  # the play step and the quiz both passed
        assert states[c["id"]]["level"] == "practised"  # the requirement follows its last stage
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


# -- technique sheets ----------------------------------------------------------------------


@pytest.mark.parametrize("spec, tier, first_right, last_right", [
    ({"type": "scale", "quality": "major", "tonic": "Bb", "octaves": 2, "hands": "separate", "artic": "legato"}, "g3", 58, 58),
    ({"type": "scale", "quality": "minor", "form": "melodic", "tonic": "D", "octaves": 1, "hands": "together", "artic": "legato"}, "g2", 62, 62),
    ({"type": "dom7", "tonic": "D", "octaves": 1, "hands": "together", "artic": "legato"}, "g6", 57, 62),
    ({"type": "sixth_apart", "quality": "major", "tonic": "C", "octaves": 1, "hands": "together", "artic": "legato"}, "g8", 60, 60),
])
def test_technique_patterns(spec, tier, first_right, last_right):
    from midi_coach.atlas import technique

    p = technique.pattern(spec)
    assert p["right"][0] == first_right and p["right"][-1] == last_right
    if spec["type"] == "scale" and spec.get("form") == "melodic":
        assert 73 in p["right"] and 72 in p["right"]  # C sharp 5 going up, C natural coming down
    if spec["type"] == "sixth_apart":
        assert p["right"][0] - p["left"][0] == 8  # the left hand a (minor) sixth below the tonic


def test_technique_sheets_lint_clean_and_keep_their_notes(tree):
    from midi_coach import engraving
    from midi_coach.atlas import technique

    reqs = [n for n in tree["nodes"] if n["level"] == "requirement" and n["kind"] == "technique"]
    assert reqs
    for r in reqs:
        out = technique.music(r["spec"], r["tier"])
        assert not engraving.lint(out["xml"])["findings"], r["id"]
    # A four-octave scale a third apart is moved down to stay below C7.
    spec = {"type": "third_apart", "quality": "major", "tonic": "E", "octaves": 4, "hands": "together", "artic": "legato"}
    notes = [n for seq in technique.pattern(spec).values() for n in seq]
    assert max(notes) <= technique.TOP and min(notes) >= technique.BOTTOM
    assert not engraving.lint(technique.music(spec, "g7")["xml"])["findings"]


def test_technique_lessons_for_each_stage(tree):
    from midi_coach.atlas import technique

    req = _req(tree, "scale-c-major", tier="initial")  # hands separately
    lessons = [technique.lesson_for(tree["by_id"][s], req, "technique/x.musicxml") for s in req["stages"]]
    assert [l["steps"][-1]["hand"] for l in lessons] == ["right", "left", "left"]
    final = lessons[-1]
    assert [s["id"] for s in final["steps"] if s["type"] == "play"] == ["play-right", "play-left"]  # each hand at exam speed
    assert all(s["pass"]["metric"] == "overall" for s in final["steps"] if s["type"] == "play")
    assert lessons[0]["steps"][-1]["pass"] == {"metric": "notes", "min": 90}  # Learn mode: the notes


def test_sight_reading_pieces_follow_their_grade():
    from midi_coach import engraving
    from midi_coach.atlas import sightreading

    syllabus = atlas_pkg.load_syllabus(atlas_pkg.SAMPLE / "syllabus.json")
    first = sightreading.params(syllabus, "initial")
    assert first["keys"] == ["C"] and first["times"] == ["4/4"] and not first["together"] and first["five_finger"]
    g1 = sightreading.params(syllabus, "g1")
    assert g1["keys"] == ["C", "G"] and "3/4" in g1["times"] and g1["bars"] == 8
    for grade, p in (("initial", first), ("g1", g1)):
        for seed in range(20):
            piece = sightreading.generate(syllabus, grade, seed)
            assert not engraving.lint(piece["xml"])["findings"], (grade, seed)
            assert piece["key"] in p["keys"] and piece["time"] in p["times"] and piece["bars"] == p["bars"]
            tonic = sightreading.PC[piece["key"].rstrip("m")]
            last = max(e[1] for e in piece["events"])
            assert all(e[3] % 12 == tonic for e in piece["events"] if e[1] == last)  # ends on the tonic
            if grade == "initial":  # one hand at a time
                for t in {e[1] for e in piece["events"]}:
                    assert len({e[0] for e in piece["events"] if e[1] <= t < e[2]}) == 1


# -- aural: tapping, singing, examples --------------------------------------------------------


def test_grade_taps_along_and_echo():
    import math
    import random as rnd

    from midi_coach.atlas import aural

    beat = 60 / 84
    ref = [k * beat for k in range(16)]
    r = rnd.Random(3)
    # Joins on beat 2, a little loose, strong beats louder (four time).
    taps = [(k * beat + r.uniform(-0.02, 0.02), 100 if k % 4 == 0 else 60) for k in range(2, 16)]
    good = aural.grade_taps(ref, taps, along=True, accent_every=4, offset=0.0)  # the music's zero on the taps' clock
    assert good["score"] >= 85 and good["caught"] == 14 and good["accent_ratio"] > 1.15
    sloppy = aural.grade_taps(ref, [(t + r.uniform(-0.12, 0.12), v) for t, v in taps], along=True)
    assert sloppy["timing"] < good["timing"]
    sparse = aural.grade_taps(ref, taps[:4], along=True)
    assert sparse["score"] < 70  # stopped early
    assert aural.grade_taps(ref, [], along=True)["score"] == 0
    # An echo tapped back later and a bit faster is judged on its own pace.
    rhythm = [0, 0.5, 1.0, 1.5, 2.25, 2.5, 3.0]
    echo = [(10 + 0.9 * t, 70) for t in rhythm]
    assert aural.grade_taps(rhythm, echo, along=False)["score"] >= 90
    wrong = [(10 + 0.9 * t, 70) for t in [0, 1, 2, 3]]
    assert aural.grade_taps(rhythm, wrong, along=False)["score"] < 70
    assert math.isclose(aural.grade_taps(rhythm, echo, along=False)["tempo_ratio"], 0.9, abs_tol=0.02)


def test_grade_sung_octaves_and_mistakes():
    from midi_coach.atlas import aural

    ref = [60, 62, 64, 62, 60]
    assert aural.grade_sung(ref, ref)["score"] == 100
    assert aural.grade_sung(ref, [p - 12 for p in ref])["score"] == 100  # a lower voice
    assert aural.grade_sung(ref, [60, 62, 65, 62, 60])["score"] == 90  # a semitone out: half right
    assert aural.grade_sung(ref, [60, 67, 64, 62, 60])["score"] == 80  # a wrong note
    assert aural.grade_sung(ref, [60, 62])["score"] == 40  # stopped short
    assert aural.grade_sung(ref, [])["score"] == 0


def test_yin_and_note_tracking():
    import math

    from midi_coach.atlas import aural

    sr = 16000
    for f in (110.0, 220.0, 440.0):
        buf = [0.5 * math.sin(2 * math.pi * f * i / sr) + 0.2 * math.sin(4 * math.pi * f * i / sr) for i in range(1024)]
        assert abs(aural.yin(buf, sr) - f) < 1.0
    assert aural.yin([0.0] * 1024, sr) is None
    # Three sung notes, with a wobble and a gap: C4, D4, E4.
    track = []
    for k, (midi, frames) in enumerate([(60, 10), (62, 8), (64, 12)]):
        for i in range(frames):
            hz = 440 * 2 ** ((midi + 0.15 * math.sin(i) - 69) / 12)
            track.append((len(track) * 0.03, hz))
        track.append((len(track) * 0.03, None))
    track.append((len(track) * 0.03, 300.0))  # a blip: too short to be a note
    notes = aural.notes_from_track(track)
    assert [n["midi"] for n in notes] == [60, 62, 64]


def test_aural_lessons_from_the_sample(home, tree):
    import shutil

    from midi_coach.atlas import aural_lessons

    content = atlas_pkg.content_dir()
    shutil.copy(atlas_pkg.SAMPLE / "syllabus.json", content / "syllabus.json")
    (content / "lessons").mkdir(parents=True, exist_ok=True)
    (content / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    count = aural_lessons.write_lessons()
    stages = [n for n in tree["nodes"] if n["level"] == "stage" and n["kind"] == "aural"]
    assert count == len(stages)
    kinds = set()
    for st in stages:
        lesson = json.loads((content / "lessons" / f"{st['id']}.json").read_text(encoding="utf-8"))
        for s in lesson["steps"]:
            kinds.add(s["type"])
            if s.get("file"):
                assert (content / "lessons" / s["file"]).is_file()
            if s["type"] == "quiz":
                assert 0 <= s["answer"] < len(s["options"])
            if s["type"] == "tap":
                assert s["ref"] == sorted(s["ref"]) and s["pass"]["metric"] == "taps"
            if s["type"] == "sing":
                assert s["ref"] and s["pass"]["metric"] == "pitch"
    assert {"tap", "sing", "read"} <= kinds  # the sample's tests: pulse, strong beats, singing back


def test_page_grades_a_tapped_echo(home, tree, monkeypatch):
    from midi_coach import display, library, midi_io, server
    from midi_coach.tests.test_midi_coach import FakeIn, FakeOut, _post, _until

    monkeypatch.setitem(__import__("sys").modules, "rtmidi", __import__("types").SimpleNamespace(MidiIn=FakeIn, MidiOut=FakeOut))
    monkeypatch.setattr("midi_coach.atlas.runtime.TAP_SILENCE_SEC", 1.0)
    content = atlas_pkg.content_dir()
    (content / "lessons").mkdir(parents=True)
    (content / "atlas.json").write_text(json.dumps({k: v for k, v in tree.items() if k != "by_id"}), encoding="utf-8")
    stage = next(n for n in tree["nodes"] if n["level"] == "stage" and n["kind"] == "aural")
    rhythm = [0.0, 0.5, 1.0, 1.5, 2.25, 2.5]
    lesson = {"id": stage["id"], "version": 1, "steps": [
        {"id": "echo", "type": "tap", "file": "x.mid", "along": False, "ref": rhythm, "graded": True, "pass": {"metric": "taps", "min": 65}}]}
    (content / "lessons" / f"{stage['id']}.json").write_text(json.dumps(lesson), encoding="utf-8")
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    monkeypatch.setattr(server._atlas, "hub", server.hub)
    monkeypatch.setattr(server, "_practice", {**server._practice, "pass": 0, "last": None, "settings": None})
    server.hub.commands.update(server.PAGE_COMMANDS)
    url = server.hub.start() + "cmd/"
    try:
        out = _post(url + "step_start", {"node": stage["id"], "step": "echo", "port": "JUNO-DS 0"})
        assert out.get("mode") == "free", out
        _until(lambda: server.recorder.active)
        t0 = time.perf_counter()
        for t in rhythm:
            while time.perf_counter() < t0 + t * 0.8:  # tapped back a bit faster
                time.sleep(0.002)
            FakeIn.instance.send([0x90, 60, 80])
            time.sleep(0.03)
            FakeIn.instance.send([0x80, 60, 0])
        _until(lambda: library.list_takes() and "passed" in library.list_takes()[-1].get("atlas", {}), timeout=10)
        verdict = library.list_takes()[-1]["atlas"]
        assert verdict["passed"] is True and verdict["score"] >= 65, verdict
    finally:
        server._practice["stopping"] = True
        server.recorder.stop()
        server.hub.shutdown()


# -- pieces --------------------------------------------------------------------------------------


def _two_staff_midi(path, grace=False):
    """A LilyPond-like file: one track per staff; optionally a grace note as a sliver of time."""
    import mido

    mid = mido.MidiFile(ticks_per_beat=384)
    for name, notes in (("upper", [(0, 384, 72), (384, 384, 74), (768, 768, 76)]), ("lower", [(0, 1536, 48)])):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        t = 0
        seq = list(notes)
        if grace and name == "upper":
            seq = [(0, 384, 72), (384, 10, 73), (394, 374, 74), (768, 768, 76)]  # a grace note: 10 ticks, no note value shows it
        for start, dur, pitch in seq:
            tr.append(mido.Message("note_on", note=pitch, velocity=70, time=start - t))
            tr.append(mido.Message("note_off", note=pitch, velocity=0, time=dur))
            t = start + dur
        mid.tracks.append(tr)
    mid.save(str(path))
    return path


def test_musescore_upbeat_and_split_bars_are_mended(tmp_path):
    """MuseScore's MIDI (PDMX) writes an upbeat as a short first bar and a written-out repeat
    as a split bar (6/8 = 5/8 + 1/8): one upbeat, whole 6/8 bars, and the real 2/4 change kept."""
    from fractions import Fraction as F

    import mido

    from midi_coach import engraving
    from midi_coach.atlas import pieces
    from midi_coach.notes import load_score

    mid = mido.MidiFile(ticks_per_beat=384)
    meta, last = mido.MidiTrack(), 0
    for tick, (n, d) in ((0, (1, 8)), (192, (6, 8)), (2496, (5, 8)), (3456, (1, 8)), (3648, (6, 8)), (4800, (2, 4))):
        meta.append(mido.MetaMessage("time_signature", numerator=n, denominator=d, time=tick - last))
        last = tick
    mid.tracks.append(meta)
    for name, pitch in (("upper", 76), ("lower", 52)):
        tr = mido.MidiTrack([mido.MetaMessage("track_name", name=name)])
        for _ in range(6336 // 192):  # eighths from the upbeat to the end
            tr.append(mido.Message("note_on", note=pitch, velocity=70, time=0))
            tr.append(mido.Message("note_off", note=pitch, velocity=0, time=192))
        mid.tracks.append(tr)
    path = tmp_path / "musescore.mid"
    mid.save(str(path))

    score = load_score(path)
    assert pieces.upbeat_bar(score) == F(1, 2)
    assert pieces._sigs(score, F(1, 2)) == [(F(0), "6/8"), (F(25, 2), "2/4")]
    out = pieces.to_musicxml(path, "Siciliano", "Anon", "test source", pickup=F(1, 2))
    assert out["first_bar"] == 0 and out["bars"] == 1 + 4 + 2  # the upbeat, four 6/8 bars, two 2/4 bars
    assert not engraving.lint(out["xml"], profile="published")["findings"]
    assert pieces.upbeat_bar(load_score(_two_staff_midi(tmp_path / "plain.mid"))) is None  # LilyPond's MIDI: no short bar


def test_pieces_written_exactly_or_snapped_with_a_note(tmp_path):
    from midi_coach import engraving
    from midi_coach.atlas import pieces
    from midi_coach.notes import load_score

    exact = pieces.to_musicxml(_two_staff_midi(tmp_path / "a.mid"), "Study", "Anon", "test source")
    assert not exact["snapped"] and not engraving.lint(exact["xml"], profile="published")["findings"]
    (tmp_path / "a.musicxml").write_text(exact["xml"], encoding="utf-8")
    back = load_score(tmp_path / "a.musicxml")
    assert sorted((round(n.beat, 3), n.pitch) for n in back.notes) == [(0.0, 48), (0.0, 72), (1.0, 74), (2.0, 76)]
    assert "<source>test source</source>" in exact["xml"]
    hands = {p.name: sorted(n.pitch for n in back.notes if n.part == p.index) for p in back.parts if p.note_count}
    assert hands == {"Right Hand": [72, 74, 76], "Left Hand": [48]}
    graced = pieces.to_musicxml(_two_staff_midi(tmp_path / "b.mid", grace=True), "Study", "Anon", "test source")
    # one grace note: only it is snapped, the rest stays exact, and the source says so
    assert not graced["snapped"] and graced["ornaments"] >= 1 and "grace or ornament note" in graced["xml"]
    assert not engraving.lint(graced["xml"], profile="published")["findings"]
    assert sorted(e[3] for e in graced["events"]) == [48, 72, 73, 74, 76]  # every pitch kept


def test_difficulty_features_and_model(tmp_path):
    from midi_coach.atlas import difficulty

    f = difficulty.features(_two_staff_midi(tmp_path / "a.mid"))
    assert f["max_chord"] == 1 and f["range"] == 28 and f["key_accidentals"] == 0  # a chord is inside one hand
    assert f["together_share"] > 0  # the hands start together on beat 1
    rows = [({k: (v * (1 + g / 4) if isinstance(v, (int, float)) else v) for k, v in f.items()}, g) for g in range(9)]
    for row, g in rows:  # make the features rise with the grade, a little noisily
        row["notes_per_sec"] = 1 + g * 0.8 + (g % 3) * 0.1
        row["shortest_beats_inv"] = 1 + g * 0.5
    model = difficulty.calibrate(rows)
    assert model["within_one_grade"] >= 0.75 and model["playing_within_one_grade"] >= 0.75
    est = difficulty.estimate(rows[6][0], model)
    assert 5 <= est["grade"] <= 7 and est["reasons"]
    assert est["grade"] == round(est["playing"] + est["length"], 2)
    # Length moves the whole-piece grade by at most the cap, and never the playing grade.
    endless = dict(rows[6][0], log_beats=rows[6][0]["log_beats"] + 50)
    long_est = difficulty.estimate(endless, model)
    assert long_est["playing"] == est["playing"] and long_est["length"] == difficulty.LENGTH_CAP
    assert ("length", difficulty.LENGTH_CAP) in long_est["reasons"]
    # Nothing fitted is measured in seconds: the files' tempos can't be trusted.
    assert not any(f.endswith("nps") or "minutes" in f for f in difficulty.FEATURES)
    # A passage is measured on its own.
    one_bar = difficulty.features(_two_staff_midi(tmp_path / "b.mid"), bars=(1, 1))
    assert one_bar["bars"] == 1 and one_bar["beats"] <= f["beats"]


def test_piece_catalog_is_public_domain_and_covers_every_grade():
    import collections
    import hashlib

    from midi_coach.atlas import pieces

    catalog = pieces.load_catalog()
    assert catalog, "midi_coach/atlas/data/pieces.json"
    tiers = ("initial", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8")
    per_grade = collections.Counter(p["grade"] for p in catalog)
    assert all(per_grade[t] >= 3 for t in tiers), per_grade
    for p in catalog:
        assert p["grade"] in tiers and p["list"] in ("A", "B", "C")
        pdmx = bool(p.get("pdmx"))  # a MuseScore score from PDMX: its CC0/PD label is self-declared
        assert p["id"] == (f"pdmx-{p['pdmx_id']}" if pdmx else f"mutopia-{p['mutopia']}")
        if pdmx:
            assert p["died"] and p["died"] < 1955  # the death-year rule stands in for the uploader's word
        if p.get("fetched"):
            if pdmx:
                assert p["licence"] in ("CC0 1.0", "Public Domain Mark 1.0") and p["source_url"].startswith("https://zenodo.org/records/")
            else:
                assert p["licence"] == "Public Domain" and p["source_url"].startswith("https://www.mutopiaproject.org/")
            assert p["sha1"] and (p["died"] is None or p["died"] < 1955)
        mid = pieces.pieces_dir() / f"{p['id']}.mid"
        if mid.is_file() and p.get("sha1"):  # a local copy is the file that was catalogued
            assert hashlib.sha1(mid.read_bytes()).hexdigest() == p["sha1"], p["id"]
            xml = (pieces.pieces_dir() / f"{p['id']}.musicxml").read_text(encoding="utf-8")
            assert p["licence"] in xml and (p["pdmx"] if pdmx else str(p["mutopia"])) in xml  # source and licence in the file


def test_piece_times_are_kept_only_on_grids_music_is_written_on():
    from fractions import Fraction as F

    import pytest

    from midi_coach.atlas.pieces import _exact

    assert _exact(2.75) == F(11, 4)
    assert _exact(1 + 1 / 3) == F(4, 3)
    assert _exact(0.2) == F(1, 5)  # a quintuplet 16th
    with pytest.raises(ValueError, match="inexpressible duration"):
        _exact(5.8698)  # a grace note taking time from its neighbour


def test_a_piece_off_every_grid_is_snapped_whole_with_a_note(tmp_path):
    """Every note a little after its beat (a file that starts with a sliver of silence): too
    many to call ornaments, so the whole piece is snapped and the source says so."""
    import mido

    from midi_coach import engraving
    from midi_coach.atlas import pieces

    mid = mido.MidiFile(ticks_per_beat=384)
    for name, base in (("upper", 72), ("lower", 48)):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name))
        tr.append(mido.Message("note_on", note=base, velocity=70, time=43))
        tr.append(mido.Message("note_off", note=base, velocity=0, time=192))
        for k in range(1, 32):
            tr.append(mido.Message("note_on", note=base + k % 5, velocity=70, time=0))
            tr.append(mido.Message("note_off", note=base + k % 5, velocity=0, time=192))
        mid.tracks.append(tr)
    mid.save(str(tmp_path / "drift.mid"))
    out = pieces.to_musicxml(tmp_path / "drift.mid", "Study", "Anon", "test source")
    assert out["snapped"] and "snapped to a sixteenth" in out["xml"]
    assert not engraving.lint(out["xml"], profile="published")["findings"]
    assert len(out["events"]) == 64
