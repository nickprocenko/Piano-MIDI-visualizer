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

A flute profile gets Pan instead: the same kind of tree for the flute (a First notes tier,
then ABRSM Flute Grades 1-2), built by atlas.pan into <home>/atlas/pan with the same
engine, page and progress store. An alto saxophone profile gets atlas.sax (First notes, then
ABRSM Saxophone Grades 1-2, in written pitch) in <home>/atlas/sax, and a singer atlas.voice
(the coach's own vocal course) in <home>/atlas/voice-high or voice-low. A fiddle, electric guitar
or bass guitar profile gets the coach's own course for it (atlas.fiddle, atlas.guitar,
atlas.bass) in <home>/atlas/fiddle, guitar or bass.
"""

from __future__ import annotations

import json
import os
import pathlib

from .. import instruments, profiles
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


def tree_name() -> str:
    """What the active profile's tree is called in the UI: 'Roadmap' for every instrument."""
    return "Roadmap"


def shared_dir() -> pathlib.Path:
    """<home>/atlas: what every profile shares (the syllabus, tree and lessons, the fetched pieces)."""
    path = home() / "atlas"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_dir() -> pathlib.Path:
    """The active profile's atlas folder for its current instrument: its progress, goals,
    temporary nodes and exam results."""
    path = profile_home() / profiles.atlas_folder()
    path.mkdir(parents=True, exist_ok=True)
    return path


def content_dir() -> pathlib.Path:
    """The syllabus facts, built tree and lessons of the active profile's instrument
    (MIDI_COACH_ATLAS_CONTENT overrides)."""
    path = pathlib.Path(os.environ.get("MIDI_COACH_ATLAS_CONTENT") or shared_dir() / instruments.folder())
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_syllabus(path: str | pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path) if path else content_dir() / "syllabus.json"
    if not p.is_file():
        raise FileNotFoundError(f"No syllabus at {p}. It is drafted locally from your copy of the ABRSM syllabus "
                                "(see 'The Roadmap' in midi_coach/README.md).")
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
