"""MIDI file player for learn/practice mode."""

from __future__ import annotations

import pathlib
from typing import Optional


def _build_tempo_map(mid: object) -> list[tuple[int, int]]:
    """Return sorted list of (abs_tick, tempo_us_per_beat) from all tracks."""
    result: dict[int, int] = {0: 500000}
    for track in mid.tracks:  # type: ignore[attr-defined]
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo":
                result[abs_tick] = msg.tempo
    return sorted(result.items())


def _tick_to_ms(abs_tick: int, tempo_map: list[tuple[int, int]], ticks_per_beat: int) -> float:
    """Convert an absolute tick position to milliseconds using the tempo map."""
    ms = 0.0
    prev_tick = 0
    prev_tempo = 500000
    for map_tick, map_tempo in tempo_map:
        if map_tick >= abs_tick:
            break
        dt = map_tick - prev_tick
        ms += (dt * prev_tempo) / (ticks_per_beat * 1000.0)
        prev_tick = map_tick
        prev_tempo = map_tempo
    dt = abs_tick - prev_tick
    ms += (dt * prev_tempo) / (ticks_per_beat * 1000.0)
    return ms


class MidiFilePlayer:
    """Parses a MIDI file and tracks playback position for visualisation.

    Notes are pre-computed as (midi_note, start_ms, end_ms) tuples.
    ``update(dt_ms)`` advances the playback clock; call each frame.
    """

    _LEAD_IN_MS = 1500.0

    def __init__(
        self,
        path: pathlib.Path,
        enabled_tracks: Optional[set[int]] = None,
    ) -> None:
        self._notes: list[tuple[int, float, float]] = []
        self._pos_ms: float = -self._LEAD_IN_MS
        self._total_ms: float = 0.0
        self._loaded: bool = False
        self._load(path, enabled_tracks)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def get_tracks_info(path: pathlib.Path) -> list[dict]:
        """Scan the MIDI file and return track metadata without full playback parsing.

        Returns a list of dicts with keys: index, name, note_count, channels.
        Only tracks that contain notes are included.
        """
        try:
            import mido  # type: ignore

            mid = mido.MidiFile(str(path))
            results = []
            for i, track in enumerate(mid.tracks):
                name = ""
                note_count = 0
                channels: set[int] = set()
                for msg in track:
                    if msg.type == "track_name":
                        name = msg.name.strip()
                    elif msg.type == "note_on" and msg.velocity > 0:
                        note_count += 1
                        if hasattr(msg, "channel"):
                            channels.add(msg.channel)
                    elif msg.type == "note_off" and hasattr(msg, "channel"):
                        channels.add(msg.channel)
                if note_count > 0:
                    results.append(
                        {
                            "index": i,
                            "name": name or f"Track {i + 1}",
                            "note_count": note_count,
                            "channels": sorted(channels),
                        }
                    )
            return results
        except Exception:
            return []

    def update(self, dt_ms: float) -> None:
        self._pos_ms += dt_ms

    def get_active_notes(self) -> set[int]:
        """Return MIDI note numbers whose window includes the current position."""
        t = self._pos_ms
        return {note for note, start, end in self._notes if start <= t < end}

    def get_notes_in_window(
        self, lookahead_ms: float, lookbehind_ms: float = 500.0
    ) -> list[tuple[int, float, float]]:
        """Return (note, start_ms, end_ms) for notes in [pos - lookbehind_ms, pos + lookahead_ms]."""
        t = self._pos_ms
        return [
            (note, start, end)
            for note, start, end in self._notes
            if end > t - lookbehind_ms and start < t + lookahead_ms
        ]

    @property
    def current_ms(self) -> float:
        return self._pos_ms

    @property
    def done(self) -> bool:
        return self._pos_ms >= self._total_ms + 2000.0

    @property
    def loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self, path: pathlib.Path, enabled_tracks: Optional[set[int]]) -> None:
        try:
            import mido  # type: ignore

            mid = mido.MidiFile(str(path))
            tempo_map = _build_tempo_map(mid)
            tpb = mid.ticks_per_beat

            notes: list[tuple[int, float, float]] = []
            max_tick = 0

            for track_idx, track in enumerate(mid.tracks):
                if enabled_tracks is not None and track_idx not in enabled_tracks:
                    continue

                abs_tick = 0
                active: dict[int, float] = {}

                for msg in track:
                    abs_tick += msg.time
                    if abs_tick > max_tick:
                        max_tick = abs_tick

                    if msg.type == "note_on" and msg.velocity > 0:
                        t_ms = _tick_to_ms(abs_tick, tempo_map, tpb)
                        active[msg.note] = t_ms
                    elif msg.type == "note_off" or (
                        msg.type == "note_on" and msg.velocity == 0
                    ):
                        if msg.note in active:
                            start = active.pop(msg.note)
                            end = _tick_to_ms(abs_tick, tempo_map, tpb)
                            if end > start:
                                notes.append((msg.note, start, end))

                end_ms = _tick_to_ms(abs_tick, tempo_map, tpb)
                for note, start in active.items():
                    if end_ms > start:
                        notes.append((note, start, end_ms))

            self._notes = sorted(notes, key=lambda x: x[1])
            self._total_ms = _tick_to_ms(max_tick, tempo_map, tpb)
            self._loaded = True
        except Exception:
            self._loaded = False
