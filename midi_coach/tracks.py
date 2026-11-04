"""Tracks: a file's instruments (its parts with notes), each with the part it is for the user
and how it shows and sounds.

A track's *part* is what the user plays it as: a hand ('right', 'left', 'both' = split by
register), 'pedals', 'vocals' (sung: shown, heard, never graded), a named part ('flute'), or
BACKING (not the user's). The part choice is saved in part_choices.json as before (score.roles;
a backing track is simply not listed). Every track also has its own mix, saved with the song
(library SETTINGS 'tracks'):

    show         drawn on the sheet and the falling notes
    mute / vol   when the user plays: a track not played this run sounds on the MIDI output
                 at vol (0-100) unless muted
    listen_mute / listen_vol   the same for Listen, kept apart from the practice mix

Defaults: a track in one of the user's parts is shown; a backing track is hidden; everything
sounds at 100. A file saved before tracks had a mix, with its parts chosen and no named part,
had its other tracks "off" (not drawn, not heard): they load hidden and muted. A band file's
old per-lane faders ('gains', {lane name: 0..1}) load as each track's volume.
"""

from __future__ import annotations

from . import library
from .notes import HAND_ROLES, ROLES, Score, effective_roles, is_named, named_roles, note_name

BACKING = "backing"
MIX_KEYS = ("show", "mute", "vol", "listen_mute", "listen_vol")


def names(score: Score) -> dict[int, str]:
    """Each track with notes -> its name: the part's name, else 'Part <n>'; a name two tracks
    share gets the track's number after it."""
    out: dict[int, str] = {}
    for p in score.parts:
        if not p.note_count:
            continue
        name = p.name.replace("\x00", "").strip() or f"Part {p.index + 1}"  # some files pad names with NULs
        if name in out.values():
            name = f"{name} {p.index + 1}"
        out[p.index] = name
    return out


def key(index: int) -> str:
    """A track's lane on the Accompanist (and its key in a saved mix)."""
    return str(index)


def part_of(score: Score, index: int) -> str:
    return effective_roles(score).get(index, BACKING)


def mix(score: Score) -> dict[int, dict]:
    """Every track's mix, {index: {show, mute, vol, listen_mute, listen_vol}}, defaults filled in."""
    settings = library.song_settings(score.path)
    saved, legacy = settings["tracks"], settings["gains"]
    roles = effective_roles(score)
    was_off = bool(score.roles) and not named_roles(score)
    out = {}
    for index, name in names(score).items():
        mine = index in roles
        entry = {"show": mine, "mute": not mine and was_off, "vol": 100, "listen_mute": not mine and was_off, "listen_vol": 100}
        if name in legacy:
            gain = float(legacy[name])
            entry.update(mute=gain <= 0, vol=round(gain * 100) or 100)
        own = saved.get(key(index))
        if own and own.get("name") == name:  # a track renamed since is a different file: its mix goes
            entry.update({k: own[k] for k in MIX_KEYS if k in own})
        out[index] = entry
    return out


def _save(score: Score, entries: dict[int, dict]) -> None:
    named = names(score)
    library.save_song_settings(score.path, gains={},
                               tracks={key(i): {"name": named[i], **e} for i, e in sorted(entries.items())})


def _clean(changes: dict) -> dict:
    out = {}
    for k in ("show", "mute", "listen_mute"):
        if k in changes:
            out[k] = bool(changes[k])
    for k in ("vol", "listen_vol"):
        if k in changes:
            out[k] = max(0, min(100, int(round(float(changes[k])))))
    return out


def set_mix(score: Score, index: int, **changes) -> dict:
    """Change one track's mix (any of MIX_KEYS) and save it with the song; returns its entry."""
    entries = mix(score)
    if index not in entries:
        raise ValueError(f"No track {index} with notes. Tracks: {sorted(entries)}")
    entries[index].update(_clean(changes))
    _save(score, entries)
    return entries[index]


def valid_part(part: str) -> str:
    part = (part or "").strip().lower()
    if part in ("", "off"):
        return BACKING
    if part in (*ROLES, BACKING) or is_named(part):
        return part
    raise ValueError(f"Not a part: {part!r}")


def set_part(score: Score, index: int, part: str) -> dict[int, str]:
    """Make track `index` the given part (BACKING = not the user's). The mix is fixed first (so
    an old file's off tracks stay off), and the track is shown if it's now the user's, hidden
    if it's backing. Something must stay the user's to play. Returns the saved roles."""
    part = valid_part(part)
    entries = mix(score)
    if index not in entries:
        raise ValueError(f"No track {index} with notes. Tracks: {sorted(entries)}")
    roles = dict(effective_roles(score))
    if part == BACKING:
        roles.pop(index, None)
    else:
        roles[index] = part
    if not any(r in HAND_ROLES or is_named(r) for r in roles.values()):
        raise ValueError("Something has to be yours to play: give another track a part first.")
    library.save_hands(score, roles)
    entries[index]["show"] = part != BACKING
    _save(score, entries)
    return roles


def confirm(score: Score) -> dict[int, str]:
    """Save the suggested parts as the user's own (the mix is fixed first, so nothing changes)."""
    entries = mix(score)
    roles = dict(effective_roles(score))
    library.save_hands(score, roles)
    _save(score, entries)
    return roles


def describe(score: Score, play: str | None = None) -> list[dict]:
    """The Playing menu's rows: one per track, what the user plays (`play`) first, then their
    other parts, then the backing, each in file order."""
    roles = effective_roles(score)
    entries = mix(score)
    parts = {p.index: p for p in score.parts}
    base, _, extra = (play or "both").partition("+")
    played = {"both": {"right", "left", "both"}, "right": {"right", "both"}, "left": {"left", "both"}}.get(base, {base}) | ({extra} if extra else set())
    rows = []
    for index, name in names(score).items():
        p, part = parts[index], roles.get(index, BACKING)
        rows.append({"index": index, "key": key(index), "name": name, "instrument": p.instrument, "notes": p.note_count,
                     "range": f"{note_name(p.low)}-{note_name(p.high)}", "part": part,
                     "yours": part in played, **entries[index]})
    rows.sort(key=lambda r: (not r["yours"], r["part"] == BACKING, r["index"]))
    return rows
