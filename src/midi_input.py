"""MIDI device detection and real-time note reading via python-rtmidi."""

from __future__ import annotations

import collections
import threading
from typing import Optional
import pygame

try:
    import rtmidi  # type: ignore
    _RTMIDI_AVAILABLE = True
except ImportError:
    _RTMIDI_AVAILABLE = False

# MIDI status byte constants (high nibble after masking out channel)
_STATUS_MASK = 0xF0
_NOTE_OFF = 0x80
_NOTE_ON = 0x90
_CC = 0xB0  # Control Change (CC 64 = sustain pedal)
_CC_SUSTAIN = 64

VIRTUAL_PORT_NAME = "Computer Keyboard (Virtual MIDI)"

# Two-row QWERTY piano layout (C3..F5-ish)
_VIRTUAL_KEY_TO_NOTE: dict[int, int] = {
    pygame.K_z: 48,
    pygame.K_s: 49,
    pygame.K_x: 50,
    pygame.K_d: 51,
    pygame.K_c: 52,
    pygame.K_v: 53,
    pygame.K_g: 54,
    pygame.K_b: 55,
    pygame.K_h: 56,
    pygame.K_n: 57,
    pygame.K_j: 58,
    pygame.K_m: 59,
    pygame.K_COMMA: 60,
    pygame.K_q: 60,
    pygame.K_2: 61,
    pygame.K_w: 62,
    pygame.K_3: 63,
    pygame.K_e: 64,
    pygame.K_r: 65,
    pygame.K_5: 66,
    pygame.K_t: 67,
    pygame.K_6: 68,
    pygame.K_y: 69,
    pygame.K_7: 70,
    pygame.K_u: 71,
    pygame.K_i: 72,
    pygame.K_9: 73,
    pygame.K_o: 74,
    pygame.K_0: 75,
    pygame.K_p: 76,
    pygame.K_LEFTBRACKET: 77,
}


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
        self._sustained_notes: set[int] = set()  # notes held only by sustain pedal
        self._sustain_active: bool = False
        self.sustain_latch: bool = False          # settable from outside
        self._cc_events: collections.deque[tuple[int, int]] = collections.deque(maxlen=64)
        self._lock = threading.Lock()
        self._virtual_mode: bool = False
        self.port_name: str = ""
        self.connected: bool = False
        self.available: bool = _RTMIDI_AVAILABLE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _list_hardware_ports(self) -> list[str]:
        """Return hardware MIDI input ports only."""
        if not _RTMIDI_AVAILABLE:
            return []
        try:
            midi_in = rtmidi.MidiIn()
            ports = [midi_in.get_port_name(i) for i in range(midi_in.get_port_count())]
            del midi_in
            return ports
        except Exception:
            return []

    def list_ports(self) -> list[str]:
        """Return selectable input ports including virtual computer keyboard."""
        return [VIRTUAL_PORT_NAME] + self._list_hardware_ports()

    def connect(self, port_index: int = 0) -> bool:
        """
        Open the MIDI input port at *port_index*.

        Returns True if the port was successfully opened, False otherwise.
        """
        self.close()

        # Virtual keyboard is always selectable as index 0.
        if port_index == 0:
            self._virtual_mode = True
            self.port_name = VIRTUAL_PORT_NAME
            self.connected = True
            return True

        if not _RTMIDI_AVAILABLE:
            return False

        try:
            ports = self._list_hardware_ports()
            hw_index = port_index - 1
            if not ports or hw_index < 0 or hw_index >= len(ports):
                return False

            self._midi_in = rtmidi.MidiIn()
            self._midi_in.open_port(hw_index)
            self._midi_in.set_callback(self._midi_callback)
            self._midi_in.ignore_types(sysex=True, timing=True, active_sense=True)

            self.port_name = ports[hw_index]
            self.connected = True
            return True
        except Exception:
            self._midi_in = None
            return False

    def handle_keydown(self, key: int) -> bool:
        """Apply a computer-key press when virtual mode is active."""
        if not self._virtual_mode or not self.connected:
            return False
        note = _VIRTUAL_KEY_TO_NOTE.get(key)
        if note is None:
            return False
        with self._lock:
            self._active_notes.add(note)
        return True

    def handle_keyup(self, key: int) -> bool:
        """Apply a computer-key release when virtual mode is active."""
        if not self._virtual_mode or not self.connected:
            return False
        note = _VIRTUAL_KEY_TO_NOTE.get(key)
        if note is None:
            return False
        with self._lock:
            self._active_notes.discard(note)
        return True

    def get_active_notes(self) -> set[int]:
        """Return a *copy* of the set of currently held MIDI note numbers."""
        with self._lock:
            return set(self._active_notes)

    def drain_cc_events(self) -> list[tuple[int, int]]:
        """Atomically drain and return all queued CC events as (cc_number, value) pairs."""
        with self._lock:
            events = list(self._cc_events)
            self._cc_events.clear()
        return events

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
            self._sustained_notes.clear()
            self._sustain_active = False
        self._virtual_mode = False
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
                self._sustained_notes.discard(note)  # physical press overrides sustain hold
        # Note Off OR Note On with velocity 0 → remove note
        elif status == _NOTE_OFF or (status == _NOTE_ON and velocity == 0):
            with self._lock:
                if self.sustain_latch and self._sustain_active:
                    # Keep note sounding; mark it as sustain-held
                    self._sustained_notes.add(note)
                else:
                    self._active_notes.discard(note)
        # Control Change → queue for polling and handle sustain pedal latch
        elif status == _CC:
            with self._lock:
                self._cc_events.append((note, velocity))  # note=cc number, velocity=cc value
            if note == _CC_SUSTAIN:
                pedal_down = velocity >= 64
                with self._lock:
                    if pedal_down:
                        self._sustain_active = True
                    elif self._sustain_active:
                        self._sustain_active = False
                        # Release all sustain-held notes that aren't physically held
                        self._active_notes -= self._sustained_notes
                        self._sustained_notes.clear()
