"""Piano fingering (fingering.py): textbook fingerings for scales, five-finger patterns and
triads in both hands; the falling notes carry each hand's finger; the coach names the finger
after the same wrong key twice, aloud only when the page asks."""

from __future__ import annotations

from midi_coach import display, fingering, live
from midi_coach.notes import Note, Score, select_notes

C_MAJOR = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81, 83, 84]


def melody(pitches, step=0.25):
    return [(i * step, p) for i, p in enumerate(pitches)]


def test_right_hand_c_major_scale_two_octaves():
    assert fingering.finger_hand(melody(C_MAJOR)) == [1, 2, 3, 1, 2, 3, 4, 1, 2, 3, 1, 2, 3, 4, 5]
    assert fingering.finger_hand(melody(C_MAJOR[::-1])) == [5, 4, 3, 2, 1, 3, 2, 1, 4, 3, 2, 1, 3, 2, 1]


def test_left_hand_scale_crosses_at_the_thumb_and_ends_on_it():
    down = fingering.finger_hand(melody([p - 24 for p in C_MAJOR[::-1]]), mirrored=True)
    up = fingering.finger_hand(melody([p - 24 for p in C_MAJOR]), mirrored=True)
    assert down[0] == 1 and up[-1] == 1  # from and to middle C on the thumb
    for fingers in (down, up):
        steps = list(zip(fingers, fingers[1:]))
        assert all(a != b for a, b in steps)
        crossings = [(a, b) for a, b in steps if (a - b) * (1 if fingers is down else -1) > 0]
        assert len(crossings) == 3 and all(1 in c and 5 not in c for c in crossings)  # at the thumb, three times


def test_five_finger_position_and_triads():
    assert fingering.finger_hand(melody([60, 62, 64, 65, 67, 65, 64, 62, 60])) == [1, 2, 3, 4, 5, 4, 3, 2, 1]
    assert fingering.finger_hand([(0, 60), (0, 64), (0, 67)]) == [1, 3, 5]
    assert fingering.finger_hand([(0, 48), (0, 52), (0, 55)], mirrored=True) == [5, 3, 1]
    assert fingering.finger_hand([(0, 60), (0, 72)]) == [1, 5]  # an octave


def test_every_note_gets_a_finger_even_in_a_big_chord_with_a_doubled_key():
    seq = [(0, p) for p in (48, 52, 55, 60, 64, 67, 72)] + [(0, 60)]
    fingers = fingering.finger_hand(seq)
    picked = [f for f in fingers if f]
    assert len(picked) >= 5 and sorted(set(picked)) == [1, 2, 3, 4, 5]
    assert fingers[3] == fingers[-1]  # the doubled C takes its twin's finger
    assert fingering.finger_hand([]) == []


def test_thumb_avoids_black_keys_in_a_flat_scale():
    b_flat = [70, 72, 74, 75, 77, 79, 81, 82]
    fingers = fingering.finger_hand(melody(b_flat))
    assert all(f != 1 for p, f in zip(b_flat, fingers) if p % 12 in fingering.BLACK)


def _two_hands() -> Score:
    rh = [Note(p, i * 0.5, i * 0.5 + 0.45, 80, part=0, beat=i * 1.0) for i, p in enumerate([60, 62, 64, 65, 67])]
    lh = [Note(p, 0.0, 2.0, 70, part=1, beat=0.0) for p in (48, 52, 55)]
    return _score(rh + lh)


def _score(notes):
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    for name, part in (("Right", 0), ("Left", 1)):
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=name))
        track.append(mido.MetaMessage("set_tempo", tempo=500000))
        events = []
        for n in notes:
            if n.part == part:
                events.append((round(n.start * 960), mido.Message("note_on", note=n.pitch, velocity=n.velocity, channel=part)))
                events.append((round(n.end * 960), mido.Message("note_off", note=n.pitch, velocity=0, channel=part)))
        events.sort(key=lambda e: (e[0], e[1].type == "note_on"))
        last = 0
        for t, m in events:
            track.append(m.copy(time=t - last))
            last = t
        mid.tracks.append(track)
    return mid


def test_falling_notes_carry_each_hands_finger(tmp_path):
    from midi_coach.notes import load_score

    path = tmp_path / "two.mid"
    _two_hands().save(path)
    score = load_score(str(path))
    roll = display.roll_notes(score)
    right = [r for r in roll if r[3] == "right"]
    left = sorted((r for r in roll if r[3] == "left"), key=lambda r: r[2])
    assert [r[4] for r in sorted(right)] == [1, 2, 3, 4, 5]
    assert [r[4] for r in left] == [5, 3, 1]


class Hub:
    def __init__(self, speak):
        self.events, self.speak_fingers = [], speak

    def flash(self, text, hint=None):
        self.events.append(("flash", text, hint))

    def say(self, text, interrupt=False, speaker="Claude"):
        self.events.append(("say", text))

    def __getattr__(self, name):  # marks, cursor, session, status...
        return lambda *a, **k: None


def test_the_coach_names_the_finger_and_says_it_when_asked(tmp_path):
    from midi_coach.notes import load_score

    path = tmp_path / "two.mid"
    _two_hands().save(path)
    score = load_score(str(path))
    notes, _ = select_notes(score, "right")
    for speak in (True, False):
        hub = Hub(speak)
        sess = live.LiveSession("wait", score, notes, hub)
        sess.start()
        for t in (0.0, 0.1, 0.2):
            sess.on_message(t, [0x90, 61, 80])
        sess.stop()
        assert ("flash", "C#4", "C4 (1)") in hub.events
        said = [e for e in hub.events if e[0] == "say"]
        assert said == ([("say", "Right hand, finger 1 on C4.")] if speak else [])  # once per chord


def test_the_page_turns_spoken_fingering_on_and_off():
    hub = display.DisplayHub()
    assert hub.speak_fingers is False
    assert hub.commands["speak_fingers"]({"on": True}) == {"ok": True, "on": True}
    assert hub.speak_fingers is True
