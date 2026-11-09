"""Familiar tunes: songs everyone knows (Twinkle, Old MacDonald, Silent Night...), in the
graded tiers beside the exam lists. They follow no syllabus: each is a public-domain melody
note for note in the right hand over the coach's own simple left hand (data/familiar_tunes.json,
in git), so a learner has more to play at their grade than the exam pieces. They are pieces of
the tier (on its Path, in its review) but never exam pieces: a mock exam takes only the
catalog's List A/B/C.

    python -m midi_coach.atlas.familiar     write their lessons into the built Atlas
"""

from __future__ import annotations

import json
import pathlib

from . import PACKAGE, content_dir, templates

FAMILY = "familiar"
TITLE = "Familiar tunes"
MADE = "atlas.familiar (public-domain tune, the coach's own left hand)"
FOLDER = "tunes"


def tunes() -> list[dict]:
    return json.loads((PACKAGE / "data" / "familiar_tunes.json").read_text(encoding="utf-8"))["tunes"]


def add(tree, grades: list[str]) -> None:
    """A 'Familiar tunes' family in each grade that has tunes. Run after the tree's own links
    (those reset every requirement's prerequisites), so each tune keeps its 'after'."""
    from .first_steps import tune_bars

    ids: dict[str, str] = {}
    for tune in tunes():
        if tune["tier"] not in grades:
            continue
        fam = tree.family(tune["tier"], "pieces", FAMILY, TITLE)
        req = tree.requirement(fam, tune["id"], tune["title"], "piece", templates.piece_stages(tune_bars(tune)),
                               piece=tune["id"], covers=[f"key:{tune['key']}"])
        ids[tune["id"]] = req["id"]
    for tune in tunes():
        if tune["id"] in ids:
            tree.by_id[ids[tune["id"]]]["prereqs"] = sorted(ids[k] for k in tune.get("after", []) if k in ids)


def lesson_for(stage: dict, req: dict, tune: dict, file: str) -> dict:
    """The same steps and pass marks as a catalog piece's stage."""
    st = stage["stage"]
    learn = st["mode"] == "learn"
    about = f"{tune['title']} ({tune['composer']}). {tune['text']} " if st["key"] in ("s1-rh", "whole-60") else ""
    what = {"right": "right hand", "left": "left hand", "both": "hands together"}[st["hand"]]
    where = f"bars {st['bars']}" if st.get("bars") else "the whole tune"
    text = (about + f"{where.capitalize()}, {what}" + (f", at {st['tempo_percent']}%" if st["tempo_percent"] != 100 else ", at tempo")
            + (". Learn mode waits for each note." if learn else ". Keep going through slips, as in a performance."))
    steps = [{"id": "read", "type": "read", "text": text},
             {"id": "listen", "type": "listen", "file": file, "hand": st["hand"], "bars": st.get("bars"), "tempo_percent": st["tempo_percent"]},
             {"id": "play", "type": "play", "file": file, "hand": st["hand"], "bars": st.get("bars"), "mode": st["mode"],
              "tempo_percent": st["tempo_percent"], "graded": True,
              "pass": {"metric": "notes", "min": 90} if learn else
                      {"metric": "overall", "min": 80 if st["tempo_percent"] == 100 else 75, "tempo_min_pct": max(50, st["tempo_percent"] - 10)}}]
    return {"id": stage["id"], "version": 1, "made": MADE, "checked": True, "requirement": req["id"], "steps": steps, "piece": tune["id"]}


def write_lessons(atlas: dict | None = None, lessons: pathlib.Path | None = None, lint: bool = True) -> dict:
    """Write each tune's score (checked note for note and linted) and its stages' lessons."""
    from . import load_atlas
    from .first_steps import Writer

    atlas = atlas or load_atlas()
    by_id = atlas.get("by_id") or {n["id"]: n for n in atlas["nodes"]}
    lessons = pathlib.Path(lessons) if lessons else content_dir() / "lessons"
    (lessons / FOLDER).mkdir(parents=True, exist_ok=True)
    w = Writer(lessons, lint=lint)
    by_tune = {t["id"]: t for t in tunes()}
    for req in atlas["nodes"]:
        if req["level"] != "requirement" or req.get("family", "").rsplit(".", 1)[-1] != FAMILY:
            continue
        t = by_tune.get(req.get("piece"))
        if not t:
            continue
        file = w.score(FOLDER, t["id"], t["title"], t["right"], t["left"], t["time"], t["key"], t["tempo"])
        for sid in req["stages"]:
            w.lesson(lesson_for(by_id[sid], req, t, file))
    return w.report


def main(argv: list[str] | None = None, atlas: dict | None = None) -> None:
    from . import load_atlas

    report = write_lessons(atlas or load_atlas())
    print(f"Familiar tunes: {report['lessons']} lessons, {report['scores']} scores")
    for p in report["problems"]:
        print("  problem:", p)


if __name__ == "__main__":
    main()
