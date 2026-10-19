"""Live MIDI input recording and output playback via python-rtmidi."""

from __future__ import annotations

import os
import threading
import time
from bisect import bisect_left
from dataclasses import dataclass, field

from .notes import Note

PORT_HELP = (
    "On Windows a MIDI input port can only be opened by one program at a time. "
    "If the visualizer (or Chrome) already has the JUNO open, route the keyboard "
    "through a virtual port: install loopMIDI, create a port such as 'Coach', and "
    "use MIDI-OX (or MIDIberry) to forward the JUNO input to both the visualizer's "
    "port and 'Coach'. Then set MIDI_COACH_INPUT=Coach in the Claude Desktop config."
)


class PortError(RuntimeError):
    pass


def _rtmidi():
    try:
        import rtmidi  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on platform
        raise PortError("python-rtmidi is not installed: pip install -r midi_coach/requirements.txt") from exc
    return rtmidi


def _open_client(kind: str):
    rtmidi = _rtmidi()
    try:
        return rtmidi.MidiIn() if kind == "input" else rtmidi.MidiOut()
    except Exception as exc:  # e.g. no MIDI driver / sequencer available
        raise PortError(f"MIDI system unavailable: {exc}") from exc


def list_ports() -> dict:
    return {"inputs": _open_client("input").get_ports(), "outputs": _open_client("output").get_ports()}


def resolve_port(names: list[str], query: str | None, env_var: str, kind: str) -> int:
    """Pick a port index by substring: explicit query > env var > 'JUNO' > only port."""
    query = query or os.environ.get(env_var) or ""
    candidates = [query] if query else ["JUNO"]
    for q in candidates:
        hits = [i for i, n in enumerate(names) if q.lower() in n.lower()]
        if hits:
            return hits[0]
    usable = [i for i, n in enumerate(names) if "microsoft gs" not in n.lower()]
    if not query and len(usable) == 1:
        return usable[0]
    wanted = f"matching '{query}'" if query else "(no JUNO found and several ports exist)"
    raise PortError(f"No MIDI {kind} port {wanted}. Available: {names or 'none'}. Set {env_var} or pass the port name.")


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


@dataclass
class RestProfile:
    """Reference rhythm info used to avoid stopping during written rests.

    onsets[k]   reference time of the k-th note (sorted)
    rests[k]    silence that follows note k in the score (seconds, >= 0)
    """

    onsets: list[float]
    rests: list[float]

    @classmethod
    def from_notes(cls, notes: list[Note]) -> "RestProfile":
        notes = sorted(notes, key=lambda n: n.start)
        onsets = [n.start for n in notes]
        rests = []
        latest_end = -1e9
        for k, n in enumerate(notes):
            latest_end = max(latest_end, n.end)
            nxt = notes[k + 1].start if k + 1 < len(notes) else latest_end
            rests.append(max(0.0, nxt - latest_end))
        return cls(onsets, rests)

    def total(self) -> int:
        return len(self.onsets)

    def remaining_max_rest(self, played: int) -> float:
        """Longest written rest still ahead, with slack for wrong/missed notes."""
        slack = max(20, int(0.1 * len(self.onsets)))
        start = max(0, played - slack)
        ahead = self.rests[start:-1] if len(self.rests) > 1 else []
        return max(ahead, default=0.0)

    def ref_time_of(self, played: int) -> float:
        if not self.onsets:
            return 0.0
        k = max(0, min(played - 1, len(self.onsets) - 1))
        return self.onsets[k] - self.onsets[0]


@dataclass
class RecordingState:
    port_name: str = ""
    started_at: float = 0.0
    first_note_at: float | None = None
    last_activity: float = 0.0
    events: list[tuple[float, list[int]]] = field(default_factory=list)
    held: set[int] = field(default_factory=set)
    pedal_down: bool = False
    note_ons: int = 0
    stop_reason: str | None = None
    current_timeout: float = 0.0


class Recorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._state: RecordingState | None = None
        self._midi_in = None
        self._monitor: threading.Thread | None = None
        self.on_finish = None  # callback(state) run on the monitor thread
        self.listener = None  # callback(now, message) for live judging, run on the MIDI thread
        self.external_stop = None  # callable() -> stop reason or None

    @property
    def active(self) -> bool:
        return self._state is not None and self._state.stop_reason is None

    def start(
        self,
        port: str | None,
        silence_sec: float = 4.0,
        max_sec: float = 600.0,
        lead_in_sec: float = 120.0,
        rests: RestProfile | None = None,
    ) -> str:
        if self.active:
            raise RuntimeError("A recording is already running. Call stop_recording first.")
        midi_in = _open_client("input")
        names = midi_in.get_ports()
        idx = resolve_port(names, port, "MIDI_COACH_INPUT", "input")
        try:
            midi_in.open_port(idx)
        except Exception as exc:
            raise PortError(f"Could not open '{names[idx]}' ({exc}). {PORT_HELP}") from exc
        midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        now = time.perf_counter()
        self._state = RecordingState(port_name=names[idx], started_at=now, last_activity=now, current_timeout=silence_sec)
        self._done.clear()
        self._midi_in = midi_in
        self._params = (silence_sec, max_sec, lead_in_sec, rests)
        midi_in.set_callback(self._on_message)
        self._monitor = threading.Thread(target=self._watch, daemon=True)
        self._monitor.start()
        return names[idx]

    def _on_message(self, event, _data=None) -> None:
        message, _delta = event
        now = time.perf_counter()
        st = self._state
        if st is None or st.stop_reason or not message:
            return
        status = message[0] & 0xF0
        if status not in (0x80, 0x90, 0xB0):
            return
        with self._lock:
            st.events.append((now, list(message)))
            if status == 0x90 and len(message) >= 3 and message[2] > 0:
                st.held.add(message[1])
                st.note_ons += 1
                if st.first_note_at is None:
                    st.first_note_at = now
            elif status in (0x80, 0x90) and len(message) >= 3:
                st.held.discard(message[1])
            elif status == 0xB0 and len(message) >= 3 and message[1] == 64:
                st.pedal_down = message[2] >= 64
            st.last_activity = now
        if self.listener:
            try:
                self.listener(now, message)
            except Exception:  # a display bug must never break recording
                pass

    def _timeout(self, st: RecordingState, now: float) -> float:
        silence_sec, _, _, rests = self._params
        timeout = silence_sec
        if st.pedal_down:
            timeout = max(timeout, 12.0)  # let a pedalled final chord ring
        if rests and rests.total() and st.note_ons < rests.total():
            ref_elapsed = rests.ref_time_of(st.note_ons)
            take_elapsed = now - (st.first_note_at or now)
            factor = take_elapsed / ref_elapsed if st.note_ons >= 8 and ref_elapsed > 1.0 else 1.5
            factor = max(0.5, min(3.0, factor))
            timeout = max(timeout, rests.remaining_max_rest(st.note_ons) * factor * 1.25 + 1.5)
        return timeout

    def _watch(self) -> None:
        _, max_sec, lead_in_sec, _ = self._params
        while True:
            time.sleep(0.05)
            st = self._state
            if st is None:
                return
            now = time.perf_counter()
            with self._lock:
                reason = None
                if st.first_note_at is None:
                    if now - st.started_at > lead_in_sec:
                        reason = "no notes played"
                elif now - st.first_note_at > max_sec:
                    reason = "max duration reached"
                elif self.external_stop and (ext := self.external_stop()):
                    reason = ext
                elif not st.held:
                    st.current_timeout = self._timeout(st, now)
                    if now - st.last_activity > st.current_timeout:
                        reason = "silence"
                if st.stop_reason:
                    reason = st.stop_reason
            if reason:
                self._finish(reason)
                return

    def _finish(self, reason: str) -> None:
        st = self._state
        if st is None:
            return
        with self._lock:
            if st.stop_reason is None:
                st.stop_reason = reason
        if self._midi_in is not None:
            try:
                self._midi_in.cancel_callback()
                self._midi_in.close_port()
            except Exception:
                pass
            self._midi_in = None
        if self.on_finish:
            try:
                self.on_finish(st)
            except Exception as exc:  # keep the error visible to wait()
                st.stop_reason = f"{reason} (saving failed: {exc})"
        self._done.set()

    def stop(self, reason: str = "stopped by request") -> None:
        if self._state is None:
            return
        with self._lock:
            if self._state.stop_reason is None:
                self._state.stop_reason = reason
        if self._monitor and self._monitor.is_alive():
            self._done.wait(5)
        else:
            self._finish(reason)

    def wait(self, timeout: float) -> bool:
        return self._done.wait(timeout)

    def status(self) -> dict:
        st = self._state
        if st is None:
            return {"state": "idle"}
        now = time.perf_counter()
        with self._lock:
            if st.stop_reason:
                state = "stopped"
            elif st.first_note_at is None:
                state = "waiting for first note"
            else:
                state = "recording"
            return {
                "state": state,
                "port": st.port_name,
                "notes_so_far": st.note_ons,
                "elapsed_sec": round((now if not st.stop_reason else st.last_activity) - (st.first_note_at or st.started_at), 1),
                "silence_sec": round(now - st.last_activity, 1) if state == "recording" else None,
                "auto_stop_after_sec": round(st.current_timeout, 1),
                "stop_reason": st.stop_reason,
            }


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------


def build_events(
    notes: list[Note],
    pedal: list[tuple[float, int]],
    t0: float,
    t1: float,
    speed: float = 1.0,
    channel: int = 0,
) -> list[tuple[float, list[int]]]:
    """Schedule notes in [t0, t1) starting at 0, time-scaled by 1/speed."""
    ch = channel & 0x0F
    ev: list[tuple[float, int, list[int]]] = []
    for n in notes:
        if not (t0 - 1e-6 <= n.start < t1):
            continue
        on = (n.start - t0) / speed
        off = (min(n.end, t1 + 0.5) - t0) / speed
        ev.append((on, 1, [0x90 | ch, n.pitch, max(1, min(127, n.velocity))]))
        ev.append((max(off, on + 0.02), 0, [0x80 | ch, n.pitch, 0]))
    times = [p[0] for p in pedal]
    k = bisect_left(times, t0)
    if k > 0 and pedal[k - 1][1] >= 64:
        ev.append((0.0, 0, [0xB0 | ch, 64, 127]))
    for t, v in pedal[k:]:
        if t >= t1:
            break
        ev.append(((t - t0) / speed, 0, [0xB0 | ch, 64, v]))
    end = max((e[0] for e in ev), default=0.0)
    ev.append((end + 0.05, 0, [0xB0 | ch, 64, 0]))
    ev.sort(key=lambda e: (e[0], e[1]))  # note-offs before note-ons at equal times
    return [(t, msg) for t, _, msg in ev]


class Player:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._status: dict = {"state": "idle"}

    @property
    def playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def play(self, segments: list[tuple[str, list[tuple[float, list[int]]]]], port: str | None, gap_sec: float = 1.5) -> str:
        """Play labelled event lists one after another on a background thread."""
        self.stop()
        out = _open_client("output")
        names = out.get_ports()
        idx = resolve_port(names, port, "MIDI_COACH_OUTPUT", "output")
        try:
            out.open_port(idx)
        except Exception as exc:
            raise PortError(f"Could not open output '{names[idx]}' ({exc}).") from exc
        self._stop.clear()
        total = sum(seg[-1][0] for _, seg in segments if seg) + gap_sec * (len(segments) - 1)
        self._status = {"state": "playing", "port": names[idx], "segments": [label for label, _ in segments], "total_sec": round(total, 1)}
        self._thread = threading.Thread(target=self._run, args=(out, segments, gap_sec), daemon=True)
        self._thread.start()
        return names[idx]

    def _run(self, out, segments, gap_sec) -> None:
        sounding: set[tuple[int, int]] = set()
        try:
            for k, (label, events) in enumerate(segments):
                self._status["current"] = label
                start = time.perf_counter()
                for t, msg in events:
                    while not self._stop.is_set():
                        delay = start + t - time.perf_counter()
                        if delay <= 0:
                            break
                        time.sleep(min(delay, 0.02))
                    if self._stop.is_set():
                        return
                    out.send_message(msg)
                    status = msg[0] & 0xF0
                    if status == 0x90 and msg[2] > 0:
                        sounding.add((msg[0] & 0x0F, msg[1]))
                    elif status in (0x80, 0x90):
                        sounding.discard((msg[0] & 0x0F, msg[1]))
                if k + 1 < len(segments) and self._stop.wait(gap_sec):
                    return
        finally:
            for ch, pitch in sounding:
                out.send_message([0x80 | ch, pitch, 0])
            for ch in {c for c, _ in sounding} | {0}:
                out.send_message([0xB0 | ch, 64, 0])
                out.send_message([0xB0 | ch, 123, 0])
            out.close_port()
            self._status["state"] = "stopped" if self._stop.is_set() else "finished"

    def stop(self) -> None:
        if self.playing:
            self._stop.set()
            self._thread.join(2)

    def status(self) -> dict:
        return dict(self._status)
