"""The Atlas: a skill tree built on the ABRSM Piano Practical Grades.

Tiers (Initial, Grade 1-8) run top to bottom; strands (Pieces, Scales & arpeggios,
Sight-reading, Aural, Theory) run left to right. Inside a tier a strand holds families
("Grade 3 - arpeggios"), families hold requirements (one exam item: "B flat major,
2 octaves, hands separately"), and requirements hold stages (the steps of learning it:
right hand, left hand, hands together slowly, at speed). The last stage of a
requirement is the requirement itself. Each tier ends in a Review and an Exam node.

ABRSM reserves the copyright on its requirement lists, so the syllabus facts, the built
tree and its generated lessons live in <home>/atlas/content (never in git): this package
holds only the engine, the templates and made-up sample data for the tests.

    python -m midi_coach.atlas.build        build <home>/atlas/content/atlas.json
"""

from __future__ import annotations

import json
import os
import pathlib

from ..library import home, profile_home

PACKAGE = pathlib.Path(__file__).parent
SAMPLE = PACKAGE / "sample"  # a made-up two-grade syllabus for the tests

STRANDS = [
    {"id": "pieces", "title": "Pieces", "glyph": "♫"},
    {"id": "technique", "title": "Scales & arpeggios", "glyph": "♯"},
    {"id": "sight", "title": "Sight-reading", "glyph": "◎"},
    {"id": "aural", "title": "Aural", "glyph": "∿"},
    {"id": "theory", "title": "Theory", "glyph": "♭"},
]
LEVELS = ("tier", "strand", "family", "requirement", "stage")  # far to near; plus "review" and "exam"


def shared_dir() -> pathlib.Path:
    """<home>/atlas: what every profile shares (the syllabus, tree and lessons, the fetched pieces)."""
    path = home() / "atlas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_dir() -> pathlib.Path:
    """The active profile's atlas folder: its progress, goals, temporary nodes and exam results."""
    path = profile_home() / "atlas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def content_dir() -> pathlib.Path:
    """The syllabus facts, built tree and lessons (MIDI_COACH_ATLAS_CONTENT overrides)."""
    path = pathlib.Path(os.environ.get("MIDI_COACH_ATLAS_CONTENT") or shared_dir() / "content")
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_syllabus(path: str | pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path) if path else content_dir() / "syllabus.json"
    if not p.is_file():
        raise FileNotFoundError(f"No syllabus at {p}. It is drafted locally from your copy of the ABRSM syllabus "
                                "(see 'The Atlas' in midi_coach/README.md).")
    return json.loads(p.read_text(encoding="utf-8"))


_atlas_cache: dict = {}


def load_atlas(path: str | pathlib.Path | None = None) -> dict:
    """The built tree (atlas.json), cached until the file changes."""
    p = pathlib.Path(path) if path else content_dir() / "atlas.json"
    mtime = p.stat().st_mtime
    hit = _atlas_cache.get(str(p))
    if hit and hit[0] == mtime:
        return hit[1]
    atlas = json.loads(p.read_text(encoding="utf-8"))
    atlas["by_id"] = {n["id"]: n for n in atlas["nodes"]}
    _atlas_cache[str(p)] = (mtime, atlas)
    return atlas
