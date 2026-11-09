"""Song lessons: a band file written as its vocal line over the piano part you play.

The piano is the part choice the coach already makes for the file (your confirmed choice,
else its suggestion) and the tune is the file's melody part - a part named vocal / melody /
lead, else a voice or lead instrument. Both are snapped to the beat the way the coach's piano
sheets are, and written with transcribe.grand_staff: time signature changes, key signature
changes where the song modulates, clefs and voices, and the lyrics when the MIDI file has
karaoke lyrics. The lesson records where it came from in <identification><source>, and goes to
'Needs review' until someone has checked it against the music.

    python -m midi_coach.songs "Billy Joel - Piano Man" "Let It Be"
"""

from __future__ import annotations

import pathlib
import re
import sys
import time
from fractions import Fraction

from . import analysis, lessons, library
from .notes import MIDI_SUFFIXES, Note, Part, _is_keyboard, _melody_part, effective_hands, load_score, playable_parts, select_notes
from .sheet import _beat, _end, _tempo_marks, grids_for, time_signatures
from .transcribe import grand_staff

LYRIC_REACH = 0.35  # beats: how far from a syllable's time the note it is sung on may start
MIN_KARAOKE_TEXTS = 30  # text events it takes (in a file without lyric events) to be karaoke lyrics


def melody_part(score, piano: set[int]) -> tuple[Part, str] | None:
    """The part carrying the tune, apart from the piano parts, and why."""
    candidates = [p for p in playable_parts(score) if p.index not in piano and not _is_keyboard(p)]
    return _melody_part(candidates) if candidates else None


def midi_lyrics(path: str) -> list[tuple[float, str, bool]]:
    """(seconds, syllable, starts a word) from a MIDI file's lyric events (karaoke files put
    them in text events: '/' or '\\' starts a line, '@' lines are headers)."""
    import mido

    try:
        mid = mido.MidiFile(path)
    except Exception:
        mid = mido.MidiFile(path, clip=True)
    raw: list[tuple[float, str]] = []
    t = 0.0
    lyric_events = any(m.type == "lyrics" for tr in mid.tracks for m in tr if m.is_meta)
    texts = sum(1 for tr in mid.tracks for m in tr if m.is_meta and m.type == "text" and not m.text.startswith("@"))
    if not lyric_events and texts < MIN_KARAOKE_TEXTS:
        return []  # a title or a copyright line, not lyrics
    for msg in mid:
        t += msg.time
        if msg.is_meta and msg.type == ("lyrics" if lyric_events else "text"):
            text = msg.text
            if not lyric_events and text.startswith("@"):
                continue
            raw.append((t, text))
    out: list[tuple[float, str, bool]] = []
    new_word = True
    for when, text in raw:
        starts = new_word or text[:1] in (" ", "/", "\\", "\r", "\n")
        word = text.strip(" /\\\r\n")
        if not word:
            new_word = True
            continue
        out.append((when, word, starts))
        new_word = text[-1:] in (" ", "\r", "\n")
    return out


def _whole_words(words: list[tuple[float, str, bool]], placed: set[int]) -> dict[int, tuple[str, str]]:
    """(text, syllabic) for each placed syllable. A syllable that found no note is joined onto
    a placed one of the same word ('an' + 'swer' sung on one note as 'answer'), so every word
    is printed whole and no hyphen leads to a new word."""
    out: dict[int, tuple[str, str]] = {}
    groups: list[list[int]] = []
    for i, (_, _, starts) in enumerate(words):
        if starts or not groups:
            groups.append([])
        groups[-1].append(i)
    for group in groups:
        on = [i for i in group if i in placed]
        if not on:
            continue  # the whole word found no note
        texts = {i: words[i][1] for i in on}
        owner = on[0]
        for i in group:
            if i in placed:
                owner = i
            elif i < on[0]:
                texts[on[0]] = words[i][1] + texts[on[0]]  # a missing first syllable joins the next one
            else:
                texts[owner] += words[i][1]
        for k, i in enumerate(on):
            first, last = k == 0, k == len(on) - 1
            out[i] = (texts[i], "single" if first and last else "begin" if first else "end" if last else "middle")
    return out


def place_lyrics(score, tune_notes: list[Note], words: list[tuple[float, str, bool]]) -> dict[int, tuple[str, str]]:
    """(text, syllabic) for the tune notes (by index) the file's syllables are sung on.

    Syllables go onto the tune's notes in order: each on the nearest note after the previous
    syllable's, within LYRIC_REACH beats (a tie goes to the earlier note). Singers anticipate
    the beat - 'self in times' a sixteenth early - so the nearest note isn't always on the beat."""
    lyric_on: dict[int, int] = {}
    beats = [n.beat for n in tune_notes]
    last = -1
    for i, (when, _, _) in enumerate(words):
        at = score.beat_of(when)
        best = None
        for k in range(last + 1, len(beats)):
            d = beats[k] - at
            if d > LYRIC_REACH:
                break
            if d >= -LYRIC_REACH and (best is None or abs(d) < abs(beats[best] - at) - 1e-6):
                best = k
        if best is not None:
            lyric_on[best] = i
            last = best
    sung = _whole_words(words, set(lyric_on.values()))
    return {k: sung[i] for k, i in lyric_on.items()}


def _snapped(score, n: Note, grids) -> tuple[Fraction, Fraction]:
    on = _beat(n.beat, grids)
    return on, _end(score.beat_of(n.end), on, grids)


def default_title(path: str) -> str:
    stem = re.sub(r"\s*\[[^\]]*\]\s*$", "", pathlib.Path(path).stem)  # 'Billy Joel - Piano Man [157]'
    return f"{stem} (with vocals)"


def song_lesson(reference: str, title: str | None = None, melody: int | None = None, category: str = lessons.NEEDS_REVIEW) -> dict:
    """Write a reference as a vocal + piano lesson and save it in `category`. melody: the
    tune's part index (default: found from the part names and instruments)."""
    score = library.get_score(reference)
    if score.played_live:
        raise ValueError("This file was played in live and its beat couldn't be recovered, so its rhythms "
                         "can't be written down reliably (they come out as nested tuplets). Use a sequenced "
                         "file, or one whose beat the coach can follow.")
    hands = effective_hands(score)
    if not hands:
        raise ValueError("A plain piano file has no separate tune to put above the piano.")
    if melody is None:
        found = melody_part(score, set(hands))
        if not found:
            raise ValueError("No vocal or melody part apart from the piano. Parts: "
                             + ", ".join(f"{p.index} {p.name} ({p.instrument})" for p in score.parts if p.note_count))
        tune_part, why = found
    else:
        tune_part, why = score.parts[melody], "chosen"
    if tune_part.index in hands:
        raise ValueError(f"Part {tune_part.index} '{tune_part.name}' is what the piano plays here (the file has no piano part).")

    notes, info = select_notes(score, "both")
    side = analysis.side_resolver(score)
    # One rhythmic grid per beat for the piano, and one for the tune: a sung triplet over
    # straight piano reads right, and no staff mixes grids inside a beat.
    piano_grids = grids_for([n.beat for n in notes])
    events = [(side(n), *_snapped(score, n, piano_grids), n.pitch) for n in notes]
    tune_notes = sorted((n for n in score.notes if n.part == tune_part.index), key=lambda n: (n.start, -n.pitch))
    tune_grids = grids_for([n.beat for n in tune_notes])
    words = midi_lyrics(score.path) if pathlib.Path(score.path).suffix.lower() in MIDI_SUFFIXES else []
    sung = place_lyrics(score, tune_notes, words)
    tune = [(*_snapped(score, n, tune_grids), n.pitch, sung.get(k)) for k, n in enumerate(tune_notes)]

    made = "converted from MIDI: note lengths and rests read from how long keys were held" \
        if pathlib.Path(score.path).suffix.lower() in MIDI_SUFFIXES else "from MusicXML"
    source = (f"{pathlib.Path(score.path).name}, {made}. Piano: {info.get('method')}. Vocal line: part {tune_part.index} "
              f"'{tune_part.name}' ({tune_part.instrument}, {why}). Made by midi-coach {time.strftime('%Y-%m-%d')}; "
              "not yet checked against a printed score.")
    title = title or default_title(score.path)
    artist = pathlib.Path(score.path).stem.split(" - ")[0].strip() if " - " in pathlib.Path(score.path).stem else None
    if artist and artist.islower():
        artist = artist.title()  # 'adele - someone like you [4271].mid'
    out = grand_staff(events, title, time_signatures(score), _tempo_marks(score), melody=tune, source=source, composer=artist)

    folder = lessons.lessons_dir(category)
    name = re.sub(r'[<>:"/\\|?*]+', "", title).strip(" .") or "Song"
    path, k = folder / f"{name}.musicxml", 2
    while path.exists():
        path, k = folder / f"{name} ({k}).musicxml", k + 1
    path.write_text(out["xml"], encoding="utf-8")

    # Check: what the coach reads back is the snapped source, note for note (onset and pitch).
    # (Sets: two parts doubling a key at the same moment is one key on the sheet.)
    loaded = load_score(path)
    got = {i: {(round(n.beat, 3), n.pitch) for n in loaded.notes if n.part == i} for i in range(3)}
    want = {0: {(round(float(on), 3), p) for on, _, p, _ in tune},
            1: {(round(float(on), 3), p) for h, on, _, p in events if h == "right"},
            2: {(round(float(on), 3), p) for h, on, _, p in events if h == "left"}}
    check = {name_: (len(want[i]), got[i] == want[i], sorted(want[i] - got[i])[:5], sorted(got[i] - want[i])[:5])
             for i, name_ in enumerate(("vocal", "right", "left"))}
    from . import engraving

    readability = engraving.lint(out["xml"])
    return {"path": str(path), "title": title, "category": category, "bars": out["bars"], "key": out["key"],
            "key_changes": out["keys"], "lyrics": f"{len(sung)} of {len(words)} syllables placed" if words else "none in the file",
            "piano": info.get("method"), "vocal": f"part {tune_part.index} {tune_part.name} ({tune_part.instrument}), {why}",
            "check": {k_: {"notes": n, "same as source": ok, **({"missing": miss, "extra": extra} if not ok else {})}
                      for k_, (n, ok, miss, extra) in check.items()},
            # Readability rules broken (engraving.RULES), with examples: should be empty.
            "readability": {r: [f"{p} bar {b}: {d}" for r_, p, b, d in readability["findings"] if r_ == r][:3]
                            for r, n in readability["counts"].items() if n}}


def main(argv: list[str]) -> None:
    for ref in argv:
        try:
            out = song_lesson(ref)
        except Exception as exc:  # noqa: BLE001 - report and go on to the next song
            print(f"{ref}: {exc}")
            continue
        print(f"{out['title']}: {out['bars']} bars, key {out['key']} {out['key_changes']}, lyrics {out['lyrics']}\n"
              f"    piano: {out['piano']}\n    vocal: {out['vocal']}\n    check: {out['check']}\n    -> {out['path']}")


if __name__ == "__main__":
    main(sys.argv[1:])
