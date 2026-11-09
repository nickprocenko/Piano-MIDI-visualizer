"""Cut a medley MIDI file (a whole album side, say) into one file per song.

Every note keeps its pitch, velocity, length and place in the bar: a section is the source's
own messages from its first bar up to the next section's, moved to start at tick 0, with the
tempo, meter, key, programs and controllers in force at the cut copied to the start. A note
still sounding at a cut belongs to the section it started in and keeps its full length.

    python tools/split_midi.py <medley.mid>                        # list its markers and bars
    python tools/split_midi.py <medley.mid> "Breathe@19" "On the Run@63" "Time@101"

Bars are counted from 0 in the file's first time signature. Each section is saved next to the
source as "<Artist> - <Title> (from <source title>) [<source id>].mid", where Artist and the
[id] come from the source's "Artist - Title [id].mid" name.
"""

from __future__ import annotations

import pathlib
import re
import sys

import mido

STATE_META = ("set_tempo", "time_signature", "key_signature", "track_name", "instrument_name")


def _absolute(track: mido.MidiTrack) -> list[tuple[int, mido.Message]]:
    t, out = 0, []
    for msg in track:
        t += msg.time
        out.append((t, msg))
    return out


def bar_ticks(mid: mido.MidiFile) -> int:
    for _, msg in sorted((x for tr in mid.tracks for x in _absolute(tr)), key=lambda x: x[0]):
        if msg.type == "time_signature":
            return mid.ticks_per_beat * 4 * msg.numerator // msg.denominator
    return mid.ticks_per_beat * 4


def section(mid: mido.MidiFile, start: int, end: int | None) -> mido.MidiFile:
    """Ticks [start, end) of `mid` as a new file starting at tick 0."""
    out = mido.MidiFile(type=mid.type, ticks_per_beat=mid.ticks_per_beat)
    for track in mid.tracks:
        state: dict = {}
        events: list[tuple[int, mido.Message]] = []
        # (channel, pitch) -> the notes sounding, oldest first: True if it started inside the section.
        # A note-off ends the oldest one, so overlapping notes of one pitch pair up as in the source.
        sounding: dict[tuple[int, int], list[bool]] = {}
        for t, msg in _absolute(track):
            if msg.type == "end_of_track":
                continue
            off = msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0)
            if msg.type in ("note_on", "note_off"):
                key = (msg.channel, msg.note)
                inside = start <= t and (end is None or t < end)
                if off:
                    if sounding.get(key) and sounding[key].pop(0):  # ends a note that started inside: keep its full length
                        events.append((t - start, msg))
                else:
                    sounding.setdefault(key, []).append(inside)
                    if inside:
                        events.append((t - start, msg))
                continue
            if t < start:
                if msg.is_meta and msg.type in STATE_META:
                    state[msg.type] = msg
                elif msg.type == "program_change":
                    state[("program", msg.channel)] = msg
                elif msg.type == "control_change":
                    state[("cc", msg.channel, msg.control)] = msg
                elif msg.type == "pitchwheel":
                    state[("bend", msg.channel)] = msg
            elif end is None or t < end:
                events.append((t - start, msg))
        for t, msg in events:  # the section sets its own tempo (or program...) at its first tick
            if t == 0:
                for key in (msg.type, ("program", getattr(msg, "channel", None)),
                            ("cc", getattr(msg, "channel", None), getattr(msg, "control", None))):
                    if key in state and state[key].type == msg.type:
                        del state[key]
        new = mido.MidiTrack()
        last = 0
        for t, msg in [(0, m) for m in state.values()] + sorted(events, key=lambda x: x[0]):
            new.append(msg.copy(time=t - last))
            last = t
        new.append(mido.MetaMessage("end_of_track", time=0))
        out.tracks.append(new)
    return out


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = pathlib.Path(sys.argv[1])
    mid = mido.MidiFile(src)
    bar = bar_ticks(mid)
    if len(sys.argv) == 2:
        for tr in mid.tracks:
            for t, msg in _absolute(tr):
                if msg.type in ("marker", "text", "key_signature", "time_signature"):
                    print(f"bar {t / bar:7.2f}  {msg.type:15} {getattr(msg, 'text', '') or getattr(msg, 'key', '') or msg}")
        return
    cuts = []
    for arg in sys.argv[2:]:
        title, _, at = arg.rpartition("@")
        cuts.append((title.strip(), int(at)))
    cuts.sort(key=lambda c: c[1])
    m = re.match(r"^(.*?) - (.*?)\s*(\[[^\]]+\])?$", src.stem)
    artist, whole, tag = (m.group(1), m.group(2), m.group(3) or "") if m else ("", src.stem, "")
    for i, (title, first) in enumerate(cuts):
        end = cuts[i + 1][1] * bar if i + 1 < len(cuts) else None
        part = section(mid, first * bar, end)
        name = f"{artist + ' - ' if artist else ''}{title} (from {whole}) {tag}".strip()
        path = src.with_name(re.sub(r'[<>:"/\\|?*]', "", name) + ".mid")
        part.save(path)
        print(f"{path.name}: bars {first}-{cuts[i + 1][1] - 1 if i + 1 < len(cuts) else 'end'}, {part.length:.0f}s")


if __name__ == "__main__":
    main()
