"""Two keyboards at once (keyboards.py): an organ's upper manual for the right hand, the lower
for the left. Each keyboard's notes are kept apart and written with its hand."""

import sys
import time
import types

import pytest

from midi_coach import keyboards, library, midi_io, transcribe
from midi_coach.keyboards import Keyboard
from midi_coach.notes import Note, notes_from_events, played_hands


class FakeIn:
    """rtmidi.MidiIn over named fake ports; FakeIn.opened[name] sends on that port."""
    ports = ["Upper Manual 0", "Lower Manual 1", "Organ 2"]
    opened: dict = {}

    def get_ports(self):
        return list(self.ports)

    def open_port(self, idx):
        self.name = self.ports[idx]
        FakeIn.opened[self.name] = self

    def ignore_types(self, **_):
        pass

    def set_callback(self, cb):
        self.cb = cb

    def cancel_callback(self):
        self.cb = None

    def close_port(self):
        FakeIn.opened.pop(self.name, None)

    def send(self, msg):
        if self.cb:
            self.cb((msg, 0.0), None)


@pytest.fixture
def fake_midi(monkeypatch):
    FakeIn.opened = {}
    monkeypatch.setitem(sys.modules, "rtmidi", types.SimpleNamespace(MidiIn=FakeIn, MidiOut=FakeIn))
    return FakeIn


ORGAN = [Keyboard("Upper Manual 0", "upper"), Keyboard("Lower Manual 1", "lower")]


def test_saved_keyboards_are_cleaned():
    kbs = keyboards.save([{"port": "A", "role": "upper"}, {"port": "B", "role": "nonsense", "channel": 40},
                          {"port": "A", "role": "lower"}, {"port": ""}, {"port": "C", "role": "off", "channel": "2"}])
    assert [(k.port, k.role, k.channel) for k in kbs] == [("A", "upper", None), ("B", "both", None), ("C", "off", 2)]
    assert keyboards.load() == kbs
    assert keyboards.several()  # A and B are on; C is off
    keyboards.save([{"port": "A"}, {"port": "C", "role": "off"}])
    assert not keyboards.several()


def test_each_keyboard_plays_its_roles_hand_unless_a_track_is_routed_to_it():
    kbs = ORGAN + [Keyboard("Pedals", "pedals"), Keyboard("Piano", "both")]
    assert keyboards.hands_for(kbs) == ["right", "left", "left", None]
    # The melody routed to the lower manual: the lower plays the right hand for this song.
    assert keyboards.hands_for(kbs, {"Lower Manual 1": "right"})[:2] == ["right", "right"]
    assert keyboards.default_keyboard(kbs, "right").port == "Upper Manual 0"
    assert keyboards.default_keyboard(kbs, "pedals").port == "Pedals"
    assert keyboards.default_keyboard(kbs, "both").port == "Piano"
    assert keyboards.default_keyboard(ORGAN, "both") is None  # no one keyboard plays both hands


def test_recorder_keeps_each_keyboards_notes_apart(fake_midi):
    rec = midi_io.Recorder()
    name = rec.start(None, 30, 60, 60, None, keyboards=ORGAN)
    assert name == "Upper Manual 0 + Lower Manual 1"
    upper, lower = fake_midi.opened["Upper Manual 0"], fake_midi.opened["Lower Manual 1"]
    lower.send([0x90, 60, 70])   # both manuals hold middle C
    upper.send([0x90, 60, 90])
    lower.send([0x80, 60, 0])    # letting go below doesn't end the C above
    time.sleep(0.01)
    upper.send([0x80, 60, 0])
    rec.stop()
    events = rec._state.events
    assert [m[0] for _, m in events] == [0x91, 0x90, 0x81, 0x80]  # stamped with the keyboard's slot
    notes, _ = notes_from_events(events, ["right", "left"])
    by_hand = {n.hand: n for n in notes}
    assert by_hand["right"].velocity == 90 and by_hand["left"].velocity == 70
    assert by_hand["right"].duration > by_hand["left"].duration
    assert not fake_midi.opened  # every port closed


def test_one_port_split_by_channel(fake_midi):
    """An organ sending both manuals down one cable, each on its own channel."""
    kbs = [Keyboard("Organ 2", "upper", channel=0), Keyboard("Organ 2", "lower", channel=1)]
    rec = midi_io.Recorder()
    rec.start(None, 30, 60, 60, None, keyboards=kbs)
    organ = fake_midi.opened["Organ 2"]
    organ.send([0x91, 48, 80])  # lower manual
    organ.send([0x90, 72, 80])  # upper manual
    organ.send([0x95, 50, 80])  # a channel nobody listens to
    rec.stop()
    assert [m[:2] for _, m in rec._state.events] == [[0x91, 48], [0x90, 72]]


def test_a_take_is_written_with_the_hand_each_note_was_played_with():
    """Crossed hands: the left plays above the right. By pitch they'd swap; by keyboard they don't."""
    notes = []
    for beat in range(8):
        notes.append(Note(55 + beat % 3, beat * 0.5, beat * 0.5 + 0.45, 80, hand="right"))  # upper manual, low
        notes.append(Note(76 + beat % 2, beat * 0.5, beat * 0.5 + 0.45, 80, hand="left"))   # lower manual, high
    sides = played_hands(notes)
    assert all(sides[(round(n.start, 4), n.pitch)] == n.hand for n in notes)
    xml = transcribe.transcribe(notes, 120, 4, 0.0)["xml"]
    right, left = xml.split("<part id=")[1:3]  # Right Hand's part, then Left Hand's
    assert "<octave>3" in right and "<octave>5" not in right
    assert "<octave>5" in left and "<octave>3" not in left
    # Without keyboards the same notes go by register: the high ones to the right hand.
    plain = [Note(n.pitch, n.start, n.end, n.velocity) for n in notes]
    assert played_hands(plain)[(0.0, 76)] == "right"


def test_saved_take_remembers_its_keyboards():
    events = [(0.0, [0x90, 60, 80]), (0.0, [0x91, 62, 80]), (0.5, [0x80, 60, 0]), (0.5, [0x81, 62, 0])]
    meta = library.save_take(events, {"inputs": [{"port": "Upper Manual 0", "role": "upper", "hand": "right"},
                                                 {"port": "Lower Manual 1", "role": "lower", "hand": "left"}]})
    library._score_cache.clear()
    notes, _ = library.take_notes(meta)
    assert {n.pitch: n.hand for n in notes} == {60: "right", 62: "left"}


def test_a_run_listens_to_every_keyboard_and_notes_their_hands(fake_midi, monkeypatch):
    from midi_coach import server
    monkeypatch.setattr(server, "recorder", midi_io.Recorder())
    keyboards.save([{"port": "Upper Manual 0", "role": "upper"}, {"port": "Lower Manual 1", "role": "lower"},
                    {"port": "Organ 2", "role": "off"}])
    meta = {}
    port, fell_back = server._start_input(None, 30, 60, 60, None, meta=meta)
    try:
        assert (port, fell_back) == ("Upper Manual 0 + Lower Manual 1", False)
        assert set(fake_midi.opened) == {"Upper Manual 0", "Lower Manual 1"}  # not the one that's off
        assert [k["hand"] for k in meta["inputs"]] == ["right", "left"]
    finally:
        server.recorder.stop()
    # A port named for the run (the Playing menu's) is just that one keyboard, as before.
    meta = {}
    port, _ = server._start_input("Organ 2", 30, 60, 60, None, meta=meta)
    server.recorder.stop()
    assert port == "Organ 2" and "inputs" not in meta
