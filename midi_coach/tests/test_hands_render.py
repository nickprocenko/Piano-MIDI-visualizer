"""hands_render: the moments it draws and what it hands the page (no browser here)."""

import mido

from midi_coach import hands_render, library


def _two_hands(path, bpm=100):
    """Two bars of C major: the right hand a note a beat from C4, the left hand half notes
    from C3."""
    mid = mido.MidiFile(ticks_per_beat=480)
    for name, notes, beats in (("Right Hand", (60, 62, 64, 65, 67, 65, 64, 62), 1),
                               ("Left Hand", (48, 53, 55, 48), 2)):
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        if beats == 1:
            tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
            tr.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
        for p in notes:
            tr.append(mido.Message("note_on", note=p, velocity=80, time=0))
            tr.append(mido.Message("note_off", note=p, velocity=0, time=480 * beats - 10))
            tr.append(mido.Message("note_on", note=p, velocity=0, time=10))
    mid.save(path)
    return path


def test_beats_and_bars_become_seconds_at_the_pieces_tempo(tmp_path):
    score = library.get_score(str(_two_hands(tmp_path / "scale.mid")))
    assert abs(hands_render.seconds_of_beat(score, 3) - 1.8) < 1e-3  # 100 bpm: 0.6 s a beat
    every = hands_render.moments_of(score, None, None, [1, 1], 1.0)
    assert [round(t, 3) for t in every] == [0.0, 0.6, 1.2, 1.8]
    assert hands_render.moments_of(score, "2.5, 1", None, None, 1.0) == [2.5, 1.0]


def test_the_job_has_fingered_notes_a_time_map_and_ordered_moments(tmp_path):
    score = library.get_score(str(_two_hands(tmp_path / "scale.mid")))
    job = hands_render.build_job(score, [1.2, 0.3, 1.2], (21, 108), 2.0)
    hands = {n[3] for n in job["notes"] if len(n) > 4}
    assert hands == {"right", "left"}  # every hand's note carries its finger
    assert [m["t"] for m in job["moments"]] == [0.3, 1.2]  # sorted, each once
    assert job["moments"][0]["name"] == "0000_300s"
    assert job["keys"] == [21, 108]
    t, beat = job["timeline"][30]
    assert abs(beat - score.beat_of(t)) < 1e-4
