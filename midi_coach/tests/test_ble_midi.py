"""Bluetooth MIDI keyboards (ble_midi): the BLE-MIDI packet format, and how a "Bluetooth: …"
port reaches the recorder, Sound out and the page, with no Bluetooth radio needed."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import types

import pytest

from midi_coach import ble_midi, library, midi_io


# ---------------------------------------------------------------------------
# Packets
# ---------------------------------------------------------------------------


def test_parse_one_note():
    assert ble_midi.parse_packet(bytes([0x80, 0x80, 0x90, 60, 100])) == [(0, [0x90, 60, 100])]


def test_parse_several_messages_with_their_timestamps():
    packet = bytes([0x81, 0x85, 0x90, 60, 100, 0x8A, 0x80, 60, 0, 0x8C, 0xB0, 64, 127])
    assert ble_midi.parse_packet(packet) == [
        ((1 << 7) | 5, [0x90, 60, 100]),
        ((1 << 7) | 10, [0x80, 60, 0]),
        ((1 << 7) | 12, [0xB0, 64, 127]),
    ]


def test_parse_running_status_with_and_without_a_timestamp():
    # a chord: one status, then data bytes alone, then a new timestamp with data bytes alone
    packet = bytes([0x80, 0x81, 0x90, 60, 100, 64, 90, 0x83, 67, 80])
    assert [m for _, m in ble_midi.parse_packet(packet)] == [[0x90, 60, 100], [0x90, 64, 90], [0x90, 67, 80]]
    assert [t for t, _ in ble_midi.parse_packet(packet)] == [1, 1, 3]


def test_parse_skips_sysex_and_real_time_but_keeps_running_status():
    packet = bytes([0x80, 0x81, 0x90, 60, 100,
                    0x82, 0xF8,                       # clock: real-time, running status survives
                    0x82, 62, 90,                     # running status note-on
                    0x83, 0xF0, 0x41, 0x10, 0x84, 0xF7,  # sysex, skipped
                    0x85, 0xC0, 5])                   # program change: one data byte
    assert [m for _, m in ble_midi.parse_packet(packet)] == [[0x90, 60, 100], [0x90, 62, 90], [0xC0, 5]]


def test_parse_keeps_what_came_before_a_cut_off_message():
    assert ble_midi.parse_packet(bytes([0x80, 0x80, 0x90, 60, 100, 0x81, 0x90, 62])) == [(0, [0x90, 60, 100])]
    assert ble_midi.parse_packet(bytes([0x80])) == []
    assert ble_midi.parse_packet(bytes([0x10, 0x80, 0x90, 60, 100])) == []  # no header


def test_parse_timestamp_wrapping_inside_a_packet():
    packet = bytes([0x85, 0xFE, 0x90, 60, 100, 0x81, 0x80, 60, 0])  # low bits 126 then 1: the high bits step
    assert [t for t, _ in ble_midi.parse_packet(packet)] == [(5 << 7) | 126, (6 << 7) | 1]


def test_encode_round_trips():
    messages = [[0x90, 60, 100], [0x90, 64, 90], [0xB0, 64, 127], [0xC0, 3]]
    packet = ble_midi.encode(messages, 9000)  # past 13 bits: wraps
    assert len(packet) == 1 + sum(1 + len(m) for m in messages)
    assert ble_midi.parse_packet(packet) == [(9000 & 0x1FFF, m) for m in messages]


def test_arrival_times_put_notes_back_where_they_were_played():
    now = 100.0
    messages = [(8190, [0x90, 60, 100]), (2, [0x90, 64, 100]), (2, [0x90, 67, 100])]  # across the wrap
    assert ble_midi.arrival_times(messages, now) == pytest.approx([now - 0.004, now, now])
    # a stale timestamp is never taken as more than 0.1 s back
    assert ble_midi.arrival_times([(0, [0x90, 1, 1]), (4000, [0x90, 2, 1])], now)[0] == pytest.approx(now - 0.1)


# ---------------------------------------------------------------------------
# The link, without a radio
# ---------------------------------------------------------------------------


class FakeClient:
    def __init__(self):
        self.packets: list[bytes] = []
        self.is_connected = True

    async def write_gatt_char(self, char, data, response=None):
        assert char == ble_midi.MIDI_CHAR and response is False
        self.packets.append(bytes(data))
        await asyncio.sleep(0)


def test_sound_out_is_packed_into_packets_in_order():
    async def go():
        link = ble_midi._Link("Bluetooth: Piano", "AA:BB")
        link.client = FakeClient()
        link.size = 13  # header + three 4-byte messages
        messages = [[0x90, 60 + k, 80] for k in range(7)] + [[0xC0, 1]]
        for msg in messages:
            link._queue(msg)
        while link._flushing:
            await asyncio.sleep(0)
        return link.client.packets, messages

    packets, messages = asyncio.run(go())
    assert all(len(p) <= 13 for p in packets) and len(packets) == 3
    assert [m for p in packets for _, m in ble_midi.parse_packet(p)] == messages


def test_a_dropped_link_drops_queued_notes_and_says_so(monkeypatch):
    said = []
    monkeypatch.setattr(ble_midi, "on_status", said.append)

    async def go():
        link = ble_midi._Link("Bluetooth: Piano", "AA:BB")
        client = link.client = FakeClient()
        link._pending.extend([[0x90, 60, 80]])
        link.users = 1
        monkeypatch.setattr(link, "_retry", lambda: asyncio.sleep(0))
        link._dropped(object())  # some other client: ignored
        assert link.client is client
        link._dropped(client)
        await asyncio.sleep(0)
        return link

    link = asyncio.run(go())
    assert link.client is None and not link._pending
    assert said == ["Bluetooth: lost Piano. Reconnecting…"]
    link._queue([0x90, 60, 80])  # nothing is queued while it's down: it would only sound late
    assert not link._pending


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------


class FakeLink:
    def __init__(self, name):
        self.name, self.label = name, name[len(ble_midi.PREFIX):]
        self.listeners, self.sent, self.users = [], [], 1

    def send(self, msg):
        self.sent.append(list(msg))

    def release(self):
        self.users -= 1


@pytest.fixture()
def bluetooth(monkeypatch):
    """bleak "installed", one remembered keyboard, and links that never touch a radio."""
    monkeypatch.setattr(ble_midi, "available", lambda: True)
    path = library.home() / "bluetooth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"Bluetooth: FP-30X": "AA:BB:CC:DD:EE:FF"}), encoding="utf-8")
    links: dict[str, FakeLink] = {}

    def fake_open(port):
        if port not in ble_midi._remembered():
            raise ble_midi.BluetoothError(f"'{port}' hasn't been found on this PC.")
        return links.setdefault(port, FakeLink(port))

    monkeypatch.setattr(ble_midi, "_open", fake_open)
    return links


@pytest.fixture()
def usb(monkeypatch):
    class In:
        def get_ports(self):
            return ["JUNO-DS 0"]

    mod = types.SimpleNamespace(MidiIn=In, MidiOut=In)
    monkeypatch.setitem(sys.modules, "rtmidi", mod)


def test_remembered_keyboards_join_both_lists(bluetooth, usb):
    assert midi_io.list_ports() == {"inputs": ["JUNO-DS 0", "Bluetooth: FP-30X"], "outputs": ["JUNO-DS 0", "Bluetooth: FP-30X"]}


def test_no_bleak_no_bluetooth_ports(monkeypatch, usb):
    monkeypatch.setattr(ble_midi, "available", lambda: False)
    assert midi_io.list_ports() == {"inputs": ["JUNO-DS 0"], "outputs": ["JUNO-DS 0"]}


def test_recorder_takes_notes_from_a_bluetooth_keyboard_at_their_own_times(bluetooth):
    rec = midi_io.Recorder()
    assert rec.start("Bluetooth: FP-30X", silence_sec=5, max_sec=30, lead_in_sec=5) == "Bluetooth: FP-30X"
    (deliver,) = bluetooth["Bluetooth: FP-30X"].listeners
    played = time.perf_counter()
    deliver(played - 0.010, [0x90, 60, 90])  # a chord in one packet, put back in order
    deliver(played, [0x90, 64, 90])
    deliver(played + 0.2, [0x80, 60, 0])
    assert rec.status()["notes_so_far"] == 2
    events = rec._state.events
    assert [t for t, _ in events] == [played - 0.010, played, played + 0.2]
    rec.stop()
    assert not bluetooth["Bluetooth: FP-30X"].listeners and bluetooth["Bluetooth: FP-30X"].users == 0


def test_sound_out_to_a_bluetooth_keyboard(bluetooth):
    acc = midi_io.Accompanist("Bluetooth: FP-30X")
    assert acc.port == "Bluetooth: FP-30X"
    acc.schedule([(0.0, [0x90, 60, 80]), (0.05, [0x80, 60, 0])], time.perf_counter())
    deadline = time.time() + 3
    while len(bluetooth["Bluetooth: FP-30X"].sent) < 2 and time.time() < deadline:
        time.sleep(0.01)
    acc.close()
    assert bluetooth["Bluetooth: FP-30X"].sent == [[0x90, 60, 80], [0x80, 60, 0]]
    assert bluetooth["Bluetooth: FP-30X"].users == 0


def test_an_unknown_bluetooth_keyboard_is_a_port_error(bluetooth):
    with pytest.raises(midi_io.PortError, match="hasn't been found"):
        midi_io.Recorder().start("Bluetooth: Somebody else's", silence_sec=1)


def test_page_finds_bluetooth_keyboards_and_never_swaps_one_for_coach(bluetooth, usb, monkeypatch):
    from midi_coach import server
    monkeypatch.setattr(ble_midi, "scan", lambda: ["Bluetooth: FP-30X"])
    out = server._cmd_ports({"bluetooth": True})
    assert out["bluetooth"]["found"] == ["Bluetooth: FP-30X"]
    assert "Bluetooth: FP-30X" in out["inputs"] and "Bluetooth: FP-30X" in out["outputs"]
    assert "less reliable" in out["bluetooth"]["warning"]
    assert "found" not in server._cmd_ports({})["bluetooth"]  # only a Find looks

    def no_radio():
        raise ble_midi.BluetoothError("Bluetooth isn't available on this PC")
    monkeypatch.setattr(ble_midi, "scan", no_radio)
    assert server._cmd_ports({"bluetooth": True})["bluetooth"]["error"].startswith("Bluetooth isn't available")

    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    with pytest.raises(midi_io.PortError, match="hasn't been found"):  # not quietly the Coach port
        server._start_input("Bluetooth: Gone", 4.0, 60.0, 5.0, None)


def test_scan_names_two_of_the_same_keyboard_apart(monkeypatch):
    monkeypatch.setattr(ble_midi, "available", lambda: True)
    hits = {"AA:AA:AA:AA:00:01": "FP-30X", "AA:AA:AA:AA:00:02": "FP-30X"}
    monkeypatch.setattr(ble_midi, "_run", lambda coro, timeout: (coro.close(), hits)[1])
    assert ble_midi.scan() == ["Bluetooth: FP-30X", "Bluetooth: FP-30X (00:02)"]
    assert ble_midi._remembered() == {"Bluetooth: FP-30X": "AA:AA:AA:AA:00:01", "Bluetooth: FP-30X (00:02)": "AA:AA:AA:AA:00:02"}
