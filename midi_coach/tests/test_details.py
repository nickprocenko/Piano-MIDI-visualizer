"""Sheet details (details.py): chord symbols, Roman numerals, lyrics and sections over the sheet."""

import pathlib
import re
import time

import mido
import pytest

from midi_coach import details, engraving, library, sheet


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MIDI_COACH_HOME", str(tmp_path / "home"))
    folder = tmp_path / "songs"
    folder.mkdir()
    monkeypatch.setenv("MIDI_COACH_REFERENCE_DIRS", str(folder))
    monkeypatch.setenv("MIDI_COACH_CONFIG", str(tmp_path / "missing.json"))
    library._score_cache.clear()
    details.running.clear()
    return folder


# C | F | G7 | C, over and over, with a sung line on every beat ("Hel-lo there").
PROGRESSION = [(48, (0, 4, 7)), (53, (0, 4, 7)), (55, (0, 4, 7, 10)), (48, (0, 4, 7))]
WORDS = [("Hel", False), ("lo", True), ("there", True)]  # (text, ends a word)


def band_file(folder: pathlib.Path, bars: int = 8, lyrics: bool = True) -> pathlib.Path:
    mid = mido.MidiFile(ticks_per_beat=480)
    meta, piano, voice = mido.MidiTrack(), mido.MidiTrack(), mido.MidiTrack()
    mid.tracks += [meta, piano, voice]
    meta.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    piano.append(mido.MetaMessage("track_name", name="Piano", time=0))
    voice.append(mido.MetaMessage("track_name", name="Vocals", time=0))
    voice.append(mido.Message("program_change", program=53, channel=1, time=0))
    last_p = last_v = 0
    for bar in range(bars):
        bass, shape = PROGRESSION[bar % 4]
        t = bar * 4 * 480
        chord = [bass] + [bass + 12 + i for i in shape]
        for i, p in enumerate(chord):
            piano.append(mido.Message("note_on", note=p, velocity=80, time=(t - last_p) if i == 0 else 0))
        for i, p in enumerate(chord):
            piano.append(mido.Message("note_off", note=p, velocity=0, time=4 * 480 - 40 if i == 0 else 0))
        last_p = t + 4 * 480 - 40
        for beat in range(4):
            k = bar * 4 + beat
            tb = t + beat * 480
            text, _ = WORDS[k % 3]
            if lyrics:
                voice.append(mido.MetaMessage("lyrics", text=(" " if k % 3 != 1 else "") + text, time=tb - last_v))
                last_v = tb
            voice.append(mido.Message("note_on", note=bass + 24 + shape[beat % len(shape)], velocity=80, channel=1,
                                      time=tb - last_v))
            voice.append(mido.Message("note_off", note=bass + 24 + shape[beat % len(shape)], velocity=0, channel=1, time=400))
            last_v = tb + 400
    path = folder / "Band - Hello [42].mid"
    mid.save(path)
    return path


def notes_of(xml: str) -> list[str]:
    """Every <note> with its pitch, length and voice: what must never change."""
    return [re.sub(r"<lyric.*?</lyric>", "", n, flags=re.S) for n in re.findall(r"<note\b.*?</note>", xml, flags=re.S)]


def test_roman_numerals():
    assert details.roman("C", 0, False) == "I"
    assert details.roman("G7", 0, False) == "V⁷"
    assert details.roman("F/C", 0, False) == "IV⁶₄"
    assert details.roman("Am", 0, False) == "vi"
    assert details.roman("Bdim", 0, False) == "vii°"
    assert details.roman("G7/F", 0, False) == "V⁴₂"
    assert details.roman("Dm7/C", 0, False) == "ii⁴₂"
    assert details.roman("Bb", 0, False) == "♭VII"
    assert details.roman("Fm", 0, False) == "iv"  # borrowed from the minor
    assert details.roman("D/F#", 0, False) == "V⁶/V"
    assert details.roman("C7", 0, False) == "V⁷/IV"
    assert details.roman("E7", 9, True) == "V⁷"  # A minor
    assert details.roman("C", 9, True) == "III"
    assert details.roman("G#dim", 9, True) == "vii°"
    assert details.roman("Bm7b5", 9, True) == "iiø⁷"
    assert details.roman("N.C.", 0, False) is None
    # A triad over its 7th or 6th is a seventh chord: Cm/Bb in E flat is vi⁴₂, Cm/A is A half-diminished.
    assert details.roman("Cm/Bb", 3, False) == "vi⁴₂"
    assert details.roman("Cm/A", 3, False) == "♯ivø⁷"
    assert details.roman("C/Bb", 0, False) == "V⁴₂/IV"
    assert details.roman("C/B", 0, False) == "I⁴₂"
    assert details.roman("C/A", 0, False) == "vi⁷"


def test_chord_names():
    assert details.chord_name(details.parse_chord("Bbmaj7")) == "Bbmaj7"
    assert details.chord_name(details.parse_chord("F#min7")) == "F#m7"
    assert details.chord_name(details.parse_chord("CΔ7")) == "Cmaj7"
    assert details.chord_name(details.parse_chord("D/F#")) == "D/F#"
    assert details.parse_chord("Gadd9").added == (9,)
    assert details.parse_chord("Cm/Bb").tones == {0, 3, 7, 10}  # the bass counts: Cm/Bb isn't contradicted by a B flat
    assert details.parse_chord("H7") is None and details.parse_chord("") is None
    names = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    # Eb in the bass under Eb-G-Bb with a passing C: a lead sheet says Eb, not Cm7/Eb.
    w = [0.0] * 12
    w[3], w[7], w[10], w[0] = 2.0, 1.5, 1.5, 0.6
    assert details.lead_sheet_name(w, 3, names)[0] == "Eb"
    assert details.title_and_artist("Adele - Skyfall [bitmidi 3932].mid") == ("Skyfall", "Adele")
    assert details.title_and_artist("Elton John - Your Song (with vocals).musicxml") == ("Your Song", "Elton John")


def test_local_details_are_written_without_touching_a_note(home):
    score = library.get_score(str(band_file(home)))
    data = details.local(score)
    assert [c["chord"] for c in data["chords"][:4]] == ["C", "F", "G7", "C"]
    assert data["lyrics_on"] == "vocals" and data["lyrics"][:3] == [
        {"beat": 0.0, "pitch": 72, "text": "Hel", "syllabic": "begin"},
        {"beat": 1.0, "pitch": 76, "text": "lo", "syllabic": "end"},
        {"beat": 2.0, "pitch": 79, "text": "there", "syllabic": "single"}]
    data["sections"] = [{"beat": 0.0, "name": "Verse 1"}, {"beat": 16.0, "name": "Chorus"}]
    xml = sheet.piano_xml(score)
    staves = sheet.staves(score)
    assert staves == ["vocals", "right", "left"]
    out = details.apply(xml, data, staves, score)

    assert notes_of(out) == notes_of(xml)  # the notes are exactly as they were
    parts = re.findall(r"<part id=.*?</part>", out, flags=re.S)
    vocals, right, left = parts
    assert vocals.count("<lyric") == 32 and "<text>Hel</text>" in vocals and "<lyric" not in right + left
    assert right.count('id="details-chord-') == len(data["chords"]) and "details-chord" not in vocals + left
    assert left.count("<numeral>") == len(data["chords"])
    assert re.findall(r'numeral-root text="([^"]+)"', left)[:4] == ["I", "IV", "V⁷", "I"]
    assert re.findall(r'details-section-\d+" placement="above"><direction-type><words[^>]*>([^<]+)', vocals) == ["Verse 1", "Chorus"]
    assert '<harmony id="details-chord-1" placement="above"><root><root-step>F</root-step></root><kind>major</kind>' in right
    readability = engraving.lint(out)
    assert not any(readability["counts"].values()), readability["findings"][:5]
    assert details.apply(xml, None, staves, score) == xml


def test_lyrics_already_in_the_sheet_are_not_doubled(home):
    from midi_coach import songs

    path = band_file(home)
    lesson = songs.song_lesson(str(path))["path"]  # a song lesson has the karaoke lyrics written in
    score = library.get_score(lesson)
    data = details.local(library.get_score(str(path)))
    xml = pathlib.Path(lesson).read_text(encoding="utf-8")
    out = details.apply(xml, data, sheet.staves(score), score)
    assert out.count("<lyric") == xml.count("<lyric") and "details-lyric" not in out
    assert "details-chord-0" in out


def test_research_keeps_what_checks_out(home):
    score = library.get_score(str(band_file(home, lyrics=False)))
    data = details.local(score)
    assert data["lyrics"] == []
    asked = {}

    def run(prompt, model, schema=None, system=None, tools="", timeout=0):
        asked["prompt"], asked["tools"] = prompt, tools
        return {"structured": {
            "chords": [{"bar": 1, "beat": 1, "chord": "C"}, {"bar": 2, "beat": 1, "chord": "F"},
                       {"bar": 3, "beat": 1, "chord": "Ebm"},  # the notes play G7
                       {"bar": 4, "beat": 1, "chord": "C"}, {"bar": 99, "beat": 1, "chord": "D"}],
            "sections": [{"bar": 1, "name": "Verse"}, {"bar": 5, "name": "Chorus"}, {"bar": 400, "name": "Coda"}],
            "lyrics": [{"note": 0, "text": "Hel", "syllabic": "begin"}, {"note": 1, "text": "lo", "syllabic": "end"},
                       {"note": 2, "text": "there", "syllabic": "single"},
                       {"note": 3, "text": "made-up", "syllabic": "single"},  # not in the lyrics: dropped
                       {"note": 2, "text": "again", "syllabic": "single"}],  # out of order: dropped
            "sources": ["https://www.hooktheory.com/theorytab/view/band/hello", "not a url"]}}

    lyrics = lambda song, artist: {"text": "Hello there, hello there", "url": "https://lrclib.net/api/get/1"}  # noqa: E731
    chart = lambda song, artist, chords: {"text": "[Verse]\nC  F\nHello there", "url": "https://tabs.example/hello",  # noqa: E731
                                          "key": "C", "capo": 0, "transpose": 0}
    new = details.research(score, data, run, lyrics, chart)

    assert data["song"] == "Hello" and data["artist"] == "Band" and "Song: Hello by Band" in asked["prompt"]
    assert "bar 3 (4/4): G7@1 (1.00) | tune: #8 1 G5" in asked["prompt"] and "WebFetch" in asked["tools"]
    assert new["state"] == "done"
    assert [c["chord"] for c in new["chords"]] == ["C", "F", "G7", "C"]
    assert new["chords"][2]["from"] == "notes" and new["conflicts"] == ["Bar 3: the chart has Ebm, the notes play G7."]
    assert [s["name"] for s in new["sections"]] == ["Verse", "Chorus"] and new["sections"][1]["beat"] == 16.0
    assert [(s["text"], s["syllabic"]) for s in new["lyrics"]] == [("Hel", "begin"), ("lo", "end"), ("there", "single")]
    assert new["lyrics_from"] == "https://lrclib.net/api/get/1"
    assert new["sources"] == ["https://tabs.example/hello", "https://lrclib.net/api/get/1",
                              "https://www.hooktheory.com/theorytab/view/band/hello"]
    assert "3 chords from the published chart, 1 kept from the notes" in new["note"]

    failed = details.research(score, data, lambda *a, **k: {"error": "limit", "usage_limit": True}, lyrics, chart)
    assert failed["state"] == "failed" and "usage limit" in failed["note"] and failed["chords"] == data["chords"]


def test_details_button_round_trip(home, monkeypatch):
    from midi_coach import display, server

    monkeypatch.setattr(server, "hub", display.DisplayHub())
    path = str(band_file(home))
    server.hub.load_score(library.get_score(path))
    assert server.hub.score_payload()["details"]["state"] == "none"
    assert "<harmony" not in server.hub.score_payload()["xml"]

    def research(score, data, run=None):
        time.sleep(0.2)
        return {**data, "state": "done", "sections": [{"beat": 0.0, "name": "Intro"}], "note": "Added 4 chords."}

    monkeypatch.setattr(details, "research", research)
    out = server._cmd_details({})
    assert out["state"] == "researching"
    payload = server.hub.score_payload()
    assert payload["details"]["state"] == "researching" and "details-chord-0" in payload["xml"]  # the file's own, now
    deadline = time.time() + 10
    while details.running and time.time() < deadline:
        time.sleep(0.05)
    deadline = time.time() + 5
    while server.hub.score_payload()["details"]["state"] != "done" and time.time() < deadline:
        time.sleep(0.05)
    payload = server.hub.score_payload()
    assert payload["details"]["state"] == "done" and payload["details"]["has"]["sections"]
    assert "details-section-0" in payload["xml"]
    assert server._cmd_details({})["state"] == "done"  # done: no second lookup unless asked
    assert not details.running


def test_atlas_exercises_get_no_details(home, monkeypatch):
    """A scale or other Atlas lesson isn't a song: no Add chords & lyrics, and none drawn from an
    old cache (a C major scale once came out as 'Bm' and 'i')."""
    from midi_coach import display, server
    from midi_coach.atlas import content_dir

    monkeypatch.setenv("MIDI_COACH_ATLAS_CONTENT", str(home.parent / "atlas" / "content"))
    music = content_dir() / "lessons" / "music"
    music.mkdir(parents=True)
    path = str(band_file(music, lyrics=False))
    assert not details.offered(path) and details.offered(str(band_file(home)))
    details.save(path, {**details.local(library.get_score(path)), "state": "done"})
    monkeypatch.setattr(server, "hub", display.DisplayHub())
    server.hub.load_score(library.get_score(path))
    payload = server.hub.score_payload()
    assert payload["details"] is None and "<harmony" not in payload["xml"]
    assert "error" in server._cmd_details({}) and not details.running


def test_a_syllable_on_a_sung_chord_goes_on_its_first_note():
    """A two-note chord in the vocal line: a syllable sung on its upper note goes on the
    chord's first <note> (one written on the second one is lost, leaving 'ex-' hyphenated
    to the next word)."""
    from types import SimpleNamespace

    def note(step, octave, chord=False):
        return (f"<note>{'<chord/>' if chord else ''}<pitch><step>{step}</step><octave>{octave}</octave></pitch>"
                "<duration>1</duration><voice>1</voice><type>quarter</type></note>")

    xml = ('<?xml version="1.0" encoding="utf-8"?><score-partwise version="4.0"><part-list><score-part id="P1">'
           '<part-name>Vocals</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes>'
           '<divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time>'
           '<clef><sign>G</sign><line>2</line></clef></attributes>'
           + note("C", 4) + note("E", 4, chord=True) + note("D", 4) + note("E", 4) + note("F", 4) + "</measure></part></score-partwise>")
    data = {"lyrics_on": "vocals", "lyrics": [
        {"beat": 0.0, "pitch": 64, "text": "ex", "syllabic": "begin"}, {"beat": 1.0, "pitch": 62, "text": "cuse", "syllabic": "end"},
        {"beat": 2.0, "pitch": 64, "text": "me", "syllabic": "single"}]}
    out = details.apply(xml, data, ["vocals"], SimpleNamespace(notes=[], parts=[], roles={}))
    notes = re.findall(r"<note>.*?</note>", out)
    assert "<text>ex</text>" in notes[0] and "<lyric" not in notes[1] and "<text>cuse</text>" in notes[2]
    assert not engraving.lint(out)["counts"].get("dangling-hyphen")
    # 'cuse' with no note of its own joins 'ex': the word is printed whole, no hyphen to 'me'.
    data["lyrics"][1]["beat"] = 0.5
    out = details.apply(xml, data, ["vocals"], SimpleNamespace(notes=[], parts=[], roles={}))
    assert re.findall(r"<syllabic>(\w+)</syllabic><text>(\w+)</text>", out) == [("single", "excuse"), ("single", "me")]
