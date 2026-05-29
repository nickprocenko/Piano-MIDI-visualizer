"""MIDI file player for learn/practice mode."""

from __future__ import annotations

import pathlib


class MidiFilePlayer:
    """Parses a MIDI file and tracks playback position for visualisation.

    Notes are pre-computed as (midi_note, start_ms, end_ms) tuples.
    ``update(dt_ms)`` advances the playback clock; call each frame.
    """

    _LEAD_IN_MS = 1500.0  # silence before the first note begins

    def __init__(self, path: pathlib.Path) -> None:
        self._notes: list[tuple[int, float, float]] = []
        self._pos_ms: float = -self._LEAD_IN_MS
        self._total_ms: float = 0.0
        self._loaded: bool = False
        self._load(path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, dt_ms: float) -> None:
        self._pos_ms += dt_ms

    def get_active_notes(self) -> set[int]:
        """Return MIDI note numbers whose window includes the current position."""
        t = self._pos_ms
        return {note for note, start, end in self._notes if start <= t < end}

    def get_notes_in_window(self, lookahead_ms: float) -> list[tuple[int, float, float]]:
        """Return (note, start_ms, end_ms) for notes visible in the upcoming window.

        Includes notes that started slightly before *pos_ms* so their tail is
        still visible.
        """
        t = self._pos_ms
        return [
            (note, start, end)
            for note, start, end in self._notes
            if end > t - 500 and start < t + lookahead_ms
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

    def _load(self, path: pathlib.Path) -> None:
        try:
            import mido  # type: ignore

            mid = mido.MidiFile(str(path))

            # Build absolute-time event list (mido yields time in seconds)
            events: list[tuple[float, str, int]] = []
            current_ms = 0.0
            for msg in mid:
                current_ms += msg.time * 1000.0
                if msg.type == "note_on" and msg.velocity > 0:
                    events.append((current_ms, "on", msg.note))
                elif msg.type == "note_off" or (
                    msg.type == "note_on" and msg.velocity == 0
                ):
                    events.append((current_ms, "off", msg.note))

            # Match note_on → note_off to form (note, start_ms, end_ms)
            active: dict[int, float] = {}
            for t_ms, etype, note in events:
                if etype == "on":
                    active[note] = t_ms
                else:
                    if note in active:
                        start = active.pop(note)
                        if t_ms > start:
                            self._notes.append((note, start, t_ms))

            # Close any notes that were never released
            for note, start in active.items():
                if current_ms > start:
                    self._notes.append((note, start, current_ms))

            self._notes.sort(key=lambda x: x[1])
            self._total_ms = current_ms
            self._loaded = True
        except Exception:
            self._loaded = False
