"""A compressed MusicXML file (.mxl) is drawn as written, not round-tripped through music21."""

import zipfile

from midi_coach.display import score_to_musicxml
from midi_coach.notes import read_musicxml

SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise><work><work-title>Reverie</work-title></work>
<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
<notations><slur type="start" placement="above"/></notations></note></measure></part></score-partwise>"""


def _mxl(path, container=True, name="score/lg-1.xml"):
    with zipfile.ZipFile(path, "w") as z:
        if container:
            z.writestr("META-INF/container.xml", f'<container><rootfiles><rootfile full-path="{name}"/></rootfiles></container>')
        z.writestr(name, SCORE)
    return path


def test_mxl_is_read_as_written(tmp_path):
    path = _mxl(tmp_path / "reverie.mxl")
    assert read_musicxml(path) == SCORE
    xml = score_to_musicxml(str(path))
    assert xml == SCORE  # title and slur placement kept
    assert 'placement="above"' in xml


def test_mxl_without_a_container(tmp_path):
    assert read_musicxml(_mxl(tmp_path / "bare.mxl", container=False, name="bare.musicxml")) == SCORE


def test_plain_musicxml_unchanged(tmp_path):
    path = tmp_path / "plain.musicxml"
    path.write_text(SCORE, encoding="utf-8")
    assert read_musicxml(path) == SCORE


NATURALS_KEY = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise><part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>1</divisions><key><fifths>4</fifths></key>
<time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note></measure>
<measure number="2"><attributes><key><key-step>F</key-step><key-alter>0</key-alter><key-accidental>natural</key-accidental>
<key-step>C</key-step><key-alter>0</key-alter><key-accidental>natural</key-accidental></key></attributes>
<note><pitch><step>F</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note></measure></part></score-partwise>"""


def test_a_key_change_written_as_naturals_loads(tmp_path):
    """MuseScore writes a return to fewer sharps as <key-step> naturals; music21 can't put that
    in a MIDI file, so the loader drops it (the notes keep their spelled pitches)."""
    from midi_coach.notes import load_score

    path = tmp_path / "naturals.musicxml"
    path.write_text(NATURALS_KEY, encoding="utf-8")
    assert [n.pitch for n in load_score(path).notes] == [64, 65]
