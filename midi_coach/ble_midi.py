"""MIDI over Bluetooth LE (the BLE-MIDI spec), for keyboards with no cable, through bleak.

A Bluetooth keyboard is listed with the MIDI ports as "Bluetooth: <its name>" once
Find Bluetooth keyboards (Preferences > Connections, cmd/ports with bluetooth) has seen it;
the name and address are remembered in <home>/bluetooth.json, so it stays listed after a
restart. It works as a MIDI input (Input, shaped like python-rtmidi's MidiIn for Recorder)
and as Sound out (Output, shaped like MidiOut for Player and Accompanist).

The link opens on first use and stays open for IDLE_SEC after the last run lets go, so
back-to-back passes don't each wait for it. If it drops while a run is using it, it is
retried in the background, and on_status tells the page what happened.

Bluetooth is less reliable than a cable, which is why the page warns about it: every note
waits for the next connection event (7.5 to 30 ms, more when Wi-Fi or other Bluetooth
devices are busy), notes can arrive in bursts, and the link can drop mid-song. Notes that
arrive together in one packet are put back at their own times from the packet's
millisecond timestamps, which takes out some of the burstiness."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from collections import deque
from typing import Callable

MIDI_SERVICE = "03b80e5a-ede8-4b33-a751-6ce34ec4c700"
MIDI_CHAR = "7772e5db-3868-4112-a1a9-f2669d106bf3"
PREFIX = "Bluetooth: "
SCAN_SEC = 5.0
CONNECT_SEC = 12.0
IDLE_SEC = 60.0
RECONNECT_TRIES = 8

WARNING = ("Bluetooth is less reliable than a USB cable: notes can arrive late or in bursts "
           "(more when Wi-Fi or other Bluetooth devices are busy), and the connection can drop "
           "mid-song. For grading and Rehearse, a cable is best.")

on_status: Callable[[str], None] | None = None  # the page's status line (server.py sets it)


class BluetoothError(RuntimeError):
    pass


def available() -> bool:
    try:
        import bleak  # noqa: F401  # type: ignore
    except ImportError:
        return False
    return True


def is_port(name: str | None) -> bool:
    return bool(name) and name.startswith(PREFIX)


# ---------------------------------------------------------------------------
# BLE-MIDI packets
# ---------------------------------------------------------------------------

_DATA_LEN = {0x80: 2, 0x90: 2, 0xA0: 2, 0xB0: 2, 0xC0: 1, 0xD0: 1, 0xE0: 2}
_SYSTEM_LEN = {0xF1: 1, 0xF2: 2, 0xF3: 1}  # other system common and real-time: no data


def parse_packet(data: bytes) -> list[tuple[int, list[int]]]:
    """The channel messages in one BLE-MIDI packet, each with its 13-bit millisecond
    timestamp. A packet is a header byte (bit 7 set: the timestamp's high 6 bits), then
    messages, each led by a timestamp byte (bit 7 set: the low 7 bits) unless it continues
    the previous one by running status. System exclusive, system common and real-time
    messages (clock, active sensing) are skipped: the coach has no use for them."""
    out: list[tuple[int, list[int]]] = []
    if len(data) < 2 or not data[0] & 0x80:
        return out
    high, last_low, ts = data[0] & 0x3F, None, 0
    status: int | None = None
    sysex = False
    i, n = 1, len(data)
    while i < n:
        b = data[i]
        if sysex:  # until a timestamp then 0xF7 (a real-time message may sit inside it)
            if b & 0x80 and i + 1 < n and data[i + 1] & 0x80:
                sysex = data[i + 1] != 0xF7
                i += 2
            else:
                i += 1
            continue
        if b & 0x80:  # a timestamp
            low = b & 0x7F
            if last_low is not None and low < last_low:
                high = (high + 1) & 0x3F  # the low bits wrapped within this packet
            last_low, ts = low, (high << 7) | low
            i += 1
            if i >= n:
                break
            b = data[i]
            if b & 0x80:  # its status byte
                i += 1
                if b == 0xF0:
                    sysex, status = True, None
                    continue
                if b >= 0xF8:  # real-time: keeps the running status
                    continue
                if b >= 0xF0:
                    i += _SYSTEM_LEN.get(b, 0)
                    status = None
                    continue
                status = b
        if status is None:  # a stray data byte
            i += 1
            continue
        length = _DATA_LEN[status & 0xF0]
        body = data[i:i + length]
        if len(body) < length or any(x & 0x80 for x in body):
            break  # cut short or malformed: keep what came before
        out.append((ts, [status, *body]))
        i += length
    return out


def encode(messages: list[list[int]], ms: int) -> bytes:
    """One BLE-MIDI packet carrying `messages`, all stamped `ms` (milliseconds, any clock)."""
    ms &= 0x1FFF
    packet = bytearray([0x80 | (ms >> 7) & 0x3F])
    for msg in messages:
        packet.append(0x80 | ms & 0x7F)
        packet.extend(msg)
    return bytes(packet)


def arrival_times(messages: list[tuple[int, list[int]]], now: float) -> list[float]:
    """When each message of a packet was played (perf_counter seconds): the packet's last
    message arrived `now`, the others its timestamp difference earlier (at most 0.1 s)."""
    if not messages:
        return []
    last = messages[-1][0]
    return [now - min(0.1, ((last - ts) & 0x1FFF) / 1000) for ts, _ in messages]


# ---------------------------------------------------------------------------
# The Bluetooth thread: one asyncio loop for every bleak call
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_loop: asyncio.AbstractEventLoop | None = None


def _event_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="bluetooth-midi", daemon=True).start()
            _loop = loop
        return _loop


def _run(coro, timeout: float):
    future = asyncio.run_coroutine_threadsafe(coro, _event_loop())
    try:
        return future.result(timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise BluetoothError("timed out") from None


def _say(text: str) -> None:
    if on_status:
        try:
            on_status(text)
        except Exception:  # the page's status line must never break the link
            pass


# ---------------------------------------------------------------------------
# Remembered devices
# ---------------------------------------------------------------------------


def _store_path():
    from . import library
    return library.home() / "bluetooth.json"


def _remembered() -> dict[str, str]:
    """Port name -> Bluetooth address, for every keyboard found so far."""
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _remember(found: dict[str, str]) -> None:
    devices = {**_remembered(), **found}
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(devices, indent=1), encoding="utf-8")


def ports() -> list[str]:
    """Every Bluetooth MIDI keyboard found so far (none when bleak isn't installed)."""
    if not available():
        return []
    with _lock:
        names = set(_remembered()) | set(_links)
    return sorted(names, key=str.lower)


def scan(seconds: float = SCAN_SEC) -> list[str]:
    """Look for Bluetooth MIDI devices for `seconds` and remember them. Returns the names of
    those seen now; one already connected doesn't advertise, so it's kept from before."""
    if not available():
        raise BluetoothError("Bluetooth MIDI needs the bleak package: pip install -r midi_coach/requirements.txt")

    async def look() -> dict[str, str]:
        from bleak import BleakScanner  # type: ignore
        seen = await BleakScanner.discover(timeout=seconds, return_adv=True)
        hits: dict[str, str] = {}
        for address, (device, adv) in seen.items():
            if MIDI_SERVICE not in {str(u).lower() for u in adv.service_uuids or []}:
                continue
            hits[address] = (adv.local_name or device.name or address).strip()
        return hits

    try:
        hits = _run(look(), seconds + 10)
    except BluetoothError:
        raise
    except Exception as exc:  # no adapter, radio off...
        raise BluetoothError(f"Bluetooth isn't available on this PC ({exc}). Is it turned on?") from exc
    names: dict[str, str] = {}
    for address, label in hits.items():
        name = PREFIX + label
        if name in names and names[name] != address:  # two keyboards of the same model
            name = f"{PREFIX}{label} ({address[-5:]})"
        names[name] = address
    with _lock:
        _remember(names)
    return sorted(names, key=str.lower)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

_links: dict[str, "_Link"] = {}


class _Link:
    """One Bluetooth connection to a keyboard, shared by the run's input and its Sound out."""

    def __init__(self, name: str, address: str) -> None:
        self.name, self.address = name, address
        self.label = name[len(PREFIX):]
        self.client = None
        self.users = 0  # open Inputs and Outputs; while any is open a dropped link is retried
        self.listeners: list[Callable[[float, list[int]], None]] = []
        self.size = 20  # bytes per packet: the smallest MTU's, until the link says more
        self._pending: deque[list[int]] = deque()
        self._flushing = False
        self._retrying = False
        self._idle: asyncio.TimerHandle | None = None
        self._connect_lock = asyncio.Lock()

    # -- on the Bluetooth thread --

    async def ensure(self) -> None:
        if self._idle:
            self._idle.cancel()
            self._idle = None
        async with self._connect_lock:
            if self.client is not None and self.client.is_connected:
                return
            await self._connect()

    async def _connect(self) -> None:
        from bleak import BleakClient  # type: ignore
        client = BleakClient(self.address, disconnected_callback=self._dropped, timeout=CONNECT_SEC)
        await client.connect()
        try:
            await client.start_notify(MIDI_CHAR, self._notify)
            char = client.services.get_characteristic(MIDI_CHAR)
            if char is not None:
                self.size = max(20, min(244, int(getattr(char, "max_write_without_response_size", 20) or 20)))
        except Exception:
            await client.disconnect()
            raise
        self.client = client

    def _notify(self, _char, data: bytearray) -> None:
        now = time.perf_counter()
        messages = parse_packet(bytes(data))
        for at, (_, msg) in zip(arrival_times(messages, now), messages):
            for listener in list(self.listeners):
                try:
                    listener(at, msg)
                except Exception:  # a listener's bug must never stop the notes
                    pass

    def _dropped(self, client) -> None:
        if client is not self.client:  # we let go of it ourselves
            return
        self.client = None
        self._pending.clear()  # notes queued for a dropped link would sound late
        if self.users:
            _say(f"Bluetooth: lost {self.label}. Reconnecting…")
            asyncio.ensure_future(self._retry())

    async def _retry(self) -> None:
        if self._retrying:
            return
        self._retrying = True
        try:
            for attempt in range(RECONNECT_TRIES):
                await asyncio.sleep(min(1.0 + attempt, 5.0))
                if not self.users or (self.client is not None and self.client.is_connected):
                    return
                try:
                    await self.ensure()
                except Exception:
                    continue
                _say(f"Bluetooth: {self.label} is back.")
                return
            _say(f"Bluetooth: couldn't reach {self.label}. Check it's on and close by, or use a USB cable.")
        finally:
            self._retrying = False

    def _queue(self, msg: list[int]) -> None:
        if self.client is None:
            return  # no link: a note sent now would only sound late
        self._pending.append(msg)
        if not self._flushing:
            self._flushing = True
            asyncio.ensure_future(self._flush())

    async def _flush(self) -> None:
        try:
            while self._pending and self.client is not None:
                batch, size = [], 1
                while self._pending and size + 1 + len(self._pending[0]) <= self.size:
                    msg = self._pending.popleft()
                    batch.append(msg)
                    size += 1 + len(msg)
                if not batch:  # longer than a packet (no use to a keyboard's notes)
                    self._pending.popleft()
                    continue
                try:
                    await self.client.write_gatt_char(MIDI_CHAR, encode(batch, int(time.perf_counter() * 1000)), response=False)
                except Exception:
                    self._pending.clear()  # the drop callback says the rest
        finally:
            self._flushing = False

    def _idle_later(self) -> None:
        if self._idle:
            self._idle.cancel()
        self._idle = _event_loop().call_later(IDLE_SEC, lambda: asyncio.ensure_future(self._close_if_idle()))

    async def _close_if_idle(self) -> None:
        if not self.users:
            await self.close()

    async def close(self) -> None:
        if self._idle:
            self._idle.cancel()
            self._idle = None
        client, self.client = self.client, None
        self._pending.clear()
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    # -- from any thread --

    def send(self, msg: list[int]) -> None:
        _event_loop().call_soon_threadsafe(self._queue, list(msg))

    def release(self) -> None:
        with _lock:
            self.users = max(0, self.users - 1)
            idle = not self.users
        if idle:
            _event_loop().call_soon_threadsafe(self._idle_later)


def _open(port: str) -> _Link:
    if not available():
        raise BluetoothError("Bluetooth MIDI needs the bleak package: pip install -r midi_coach/requirements.txt")
    with _lock:
        link = _links.get(port)
        if link is None:
            address = _remembered().get(port)
            if not address:
                raise BluetoothError(f"'{port}' hasn't been found on this PC. Turn it on, then press "
                                     "Find Bluetooth keyboards in Preferences > Connections.")
            link = _links[port] = _Link(port, address)
        link.users += 1
    if link.client is None or not link.client.is_connected:
        _say(f"Bluetooth: connecting to {link.label}…")  # the first time takes a few seconds
    try:
        _run(link.ensure(), CONNECT_SEC + 5)
    except Exception as exc:
        link.release()
        raise BluetoothError(f"Could not connect to {link.label} over Bluetooth ({exc or 'no answer'}). "
                             "Check it's on and close by, and not connected to a phone or tablet.") from exc
    return link


class Input:
    """A Bluetooth keyboard's notes, shaped like python-rtmidi's MidiIn for Recorder: the
    callback gets ((message, 0.0), None, at=<when it was played, perf_counter>)."""

    def __init__(self, port: str) -> None:
        self._link = _open(port)
        self._callback = None
        self._open = True

    def ignore_types(self, **_kinds) -> None:
        pass  # only channel messages are passed on anyway

    def set_callback(self, callback) -> None:
        self._callback = callback
        with _lock:
            if self._deliver not in self._link.listeners:
                self._link.listeners.append(self._deliver)

    def _deliver(self, at: float, msg: list[int]) -> None:
        callback = self._callback
        if callback:
            callback((msg, 0.0), None, at=at)

    def cancel_callback(self) -> None:
        self._callback = None
        with _lock:
            if self._deliver in self._link.listeners:
                self._link.listeners.remove(self._deliver)

    def close_port(self) -> None:
        self.cancel_callback()
        if self._open:
            self._open = False
            self._link.release()


class Output:
    """Sound out to a Bluetooth keyboard, shaped like python-rtmidi's MidiOut. Messages are
    packed into as few packets as the link allows and sent in order."""

    def __init__(self, port: str) -> None:
        self._link = _open(port)
        self._open = True

    def send_message(self, msg) -> None:
        if self._open:
            self._link.send(list(msg))

    def close_port(self) -> None:
        if self._open:  # what's queued (the closing note-offs) still goes: the link stays a while
            self._open = False
            self._link.release()


def release_all() -> None:
    """Let go of every idle Bluetooth link now, e.g. so the visualizer can connect to it."""
    with _lock:
        idle = [link for link in _links.values() if not link.users]
    if idle and _loop is not None:
        for link in idle:
            asyncio.run_coroutine_threadsafe(link.close(), _loop)
