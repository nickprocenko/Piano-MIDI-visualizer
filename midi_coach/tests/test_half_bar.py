"""The middle of a 4/4 bar shows and its eighths are beamed by the half bar, as printed music
does. Found comparing the coach's sheet of Debussy's Reverie with the published engraving: the
left hand's arpeggio held its G as a quarter over beat 3 and was beamed in pairs or flagged,
where the engraving writes two tied eighths under beams of four."""

import re
from fractions import Fraction as F

from midi_coach import engraving
from midi_coach.notes import load_score
from midi_coach.transcribe import _pieces, grand_staff

# Reverie, bar 1, left hand: Bb C D G~G D C Bb in eighths (the G held over the middle of the
# bar), a Bb held under it all.
ARPEGGIO = [(0, 1, 58), (1, 2, 60), (2, 3, 62), (3, 5, 67), (5, 6, 62), (6, 7, 60), (7, 8, 58)]


def _events(bars=2):
    out = []
    for b in range(bars):
        out += [("left", F(on, 2) + 4 * b, F(end, 2) + 4 * b, p) for on, end, p in ARPEGGIO]
        out.append(("left", F(4 * b), F(4 * b + 4), 46))
        out.append(("right", F(4 * b), F(4 * b + 2), 79))
        out.append(("right", F(4 * b + 2), F(4 * b + 4), 74))
    return out


def test_held_note_is_tied_at_the_half_bar_and_eighths_beamed_in_fours(tmp_path):
    events = _events()
    xml = grand_staff(events, "t", "4/4", legato_gap=F(0))["xml"]
    found = engraving.lint(xml)["counts"]
    assert found["hidden-half-bar"] == 0 and found["pair-beams"] == 0
    assert re.findall(r'<beam number="1">(\w+)', xml)[:8] == ["begin", "continue", "continue", "end"] * 2
    assert xml.count('<tied type="start"') >= 2  # the G, in each bar
    path = tmp_path / "arpeggio.musicxml"
    path.write_text(xml, encoding="utf-8")
    got = sorted((round(n.beat, 3), n.pitch) for n in load_score(path).notes)
    assert got == sorted((float(on), p) for _, on, _, p in events)  # no note lost or added


def test_the_lint_catches_the_old_way():
    from music21 import meter, note, stream

    part = stream.Part()
    part.partName = "Left Hand"
    m = stream.Measure(number=1)
    m.append(meter.TimeSignature("4/4"))
    for p, ql in (("B-3", .5), ("C4", .5), ("D4", .5), ("G4", 1), ("D4", .5), ("C4", .5), ("B-3", .5)):
        m.append(note.Note(p, quarterLength=ql))  # the G a quarter from beat 2.5 over beat 3
    m2 = stream.Measure(number=2)
    for p in "B-3 C4 D4 G4 G4 D4 C4 B-3".split():
        m2.append(note.Note(p, quarterLength=.5))
    part.append([m, m2])
    part.makeBeams(inPlace=True)  # music21's pairs
    counts = engraving.lint(stream.Score([part]))["counts"]
    assert counts["hidden-half-bar"] == 1
    assert counts["pair-beams"] == 2  # both halves of bar 2


def test_where_notes_and_rests_are_cut():
    middles = [F(2)]
    assert _pieces(F(3, 2), F(1), [F(0), F(4)], middles) == [(F(3, 2), F(1, 2)), (F(2), F(1, 2))]
    assert _pieces(F(1), F(2), [F(0), F(4)], middles) == [(F(1), F(2))]  # a half on beat 2 may cross
    assert _pieces(F(0), F(3), [F(0), F(4)], middles, rest=True) == [(F(0), F(2)), (F(2), F(1))]  # not a dotted-half rest
    assert _pieces(F(0), F(4), [F(0), F(4)], middles, rest=True) == [(F(0), F(4))]  # a whole-bar rest
