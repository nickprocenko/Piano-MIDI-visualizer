"""MIDI device detection and real-time note reading via python-rtmidi."""

from __future__ import annotations

import threading
from typing import Optional

try:
    import rtmidi  # type: ignore
    _RTMIDI_AVAILABLE = True
except ImportError:
    _RTMIDI_AVAILABLE = False

# MIDI status byte constants (high nibble after masking out channel)
_STATUS_MASK = 0xF0
_NOTE_OFF = 0x80
_NOTE_ON = 0x90


class MidiInput:
    """
    Detects available MIDI input ports, opens the first one found, and
    maintains a set of currently-held note numbers via rtmidi callbacks.

    Usage::

        midi = MidiInput()
        midi.connect()           # auto-detect & open first port
        notes = midi.get_active_notes()  # set of held MIDI note numbers
        midi.close()
    """

    def __init__(self) -> None:
        self._midi_in: Optional[object] = None  # rtmidi.MidiIn instance
        self._active_notes: set[int] = set()
        self._lock = threading.Lock()
        self.port_name: str = ""
        self.connected: bool = False
        self.available: bool = _RTMIDI_AVAILABLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_ports(self) -> list[str]:
        """Return a list of available MIDI input port names."""
        if not _RTMIDI_AVAILABLE:
            return []
        try:
            midi_in = rtmidi.MidiIn()
            ports = [midi_in.get_port_name(i) for i in range(midi_in.get_port_count())]
            del midi_in
            return ports
        except Exception:
            return []

    def connect(self) -> bool:
        """
        Auto-detect and open the first available MIDI input port.

        Returns True if a port was successfully opened, False otherwise.
        """
        if not _RTMIDI_AVAILABLE:
            return False

        try:
            ports = self.list_ports()
            if not ports:
                return False

            self._midi_in = rtmidi.MidiIn()
            self._midi_in.open_port(0)
            self._midi_in.set_callback(self._midi_callback)
            self._midi_in.ignore_types(sysex=True, timing=True, active_sense=True)

            self.port_name = ports[0]
            self.connected = True
            return True
        except Exception:
            self._midi_in = None
            return False

    def get_active_notes(self) -> set[int]:
        """Return a *copy* of the set of currently held MIDI note numbers."""
        with self._lock:
            return set(self._active_notes)

    def close(self) -> None:
        """Close the MIDI port and release all resources."""
        if self._midi_in is not None:
            try:
                self._midi_in.cancel_callback()
                self._midi_in.close_port()
            except Exception:
                pass
            self._midi_in = None
        with self._lock:
            self._active_notes.clear()
        self.connected = False
        self.port_name = ""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _midi_callback(self, message: tuple, data: object = None) -> None:
        """rtmidi callback — called from a background thread for every MIDI message.

        Args:
            message: A tuple of ``(midi_bytes, timestamp)`` provided by rtmidi,
                where *midi_bytes* is a list of integers ``[status, note, velocity]``.
            data: User data passed to rtmidi (unused here).
        """
        midi_bytes, _ = message
        if len(midi_bytes) < 3:
            return

        status = midi_bytes[0] & _STATUS_MASK  # strip channel nibble
        note = midi_bytes[1]
        velocity = midi_bytes[2]

        # Note On (with velocity > 0) → add note
        if status == _NOTE_ON and velocity > 0:
            with self._lock:
                self._active_notes.add(note)
        # Note Off OR Note On with velocity 0 → remove note
        elif status == _NOTE_OFF or (status == _NOTE_ON and velocity == 0):
            with self._lock:
                self._active_notes.discard(note)
