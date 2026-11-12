# Radio Hands

Pick an internet radio station, and a pair of hands plays what's on, on the same falling notes
and 3D hands as the coach page's *Hands on the keys*.

- **The song is in the library** (the coach's song folders, `~/MidiCoach/references`, or found
  on bitmidi.com): the hands play the song's own MIDI, lined up with the radio by ear.
- **It isn't**: the hands play the chords heard on the radio. They choose from the song file's
  chords or its chord chart when there is one, else from the 24 major and minor chords.

```bat
Launch Radio Hands.bat                          :: or:
.venv\Scripts\python -m radio_hands             :: http://127.0.0.1:8790/ (--port, --no-browser)
.venv\Scripts\python -m pytest radio_hands/tests
```

It runs alongside the coach (different port) and doesn't use a MIDI keyboard.

## Using it

- **Station** (top left): search [radio-browser.info](https://www.radio-browser.info)'s directory
  by name, country, province/state and genre; star favourites; or paste a stream link (MP3/AAC,
  `.pls`, `.m3u`, `.m3u8`). Classic rock, oldies and 80s stations find the most songs in the
  library; current hits are rarely there, so those get chords.
- **Delay**: how far behind live the radio plays (default 15 s). The app needs about 8 seconds of
  a song to find its place in the MIDI file, so with the delay the hands are ready on the
  song's first note, and the next chord is known before you hear it. *Live* plays at once; the
  hands then join a few seconds into each song. A radio in the room won't match: listen
  through the app.
- **On air** shows what the station says is playing, and whether the hands play the song's
  **♪ Notes** or its **Chords**. When the station names the song wrongly or not at all, type it
  in *Not right? Type the song…*. When the library has more than one file for the song, the
  menu beside it picks another (fan-made MIDIs differ, and one may fit the radio better).
- **Views** (top right, or keys **1–4**): **🎹 Piano** (falling notes and 3D hands), **🎸 Guitar** (the chords as a note highway: six string lanes, the fret on each string, × = not played, struck at the bright line, with chord boxes for now and next; shapes are open chords and movable barres in `static/guitar.js`, slash chords show the plain chord), **🥁 Drums** (hits fall to pads: crash, hi-hat, snare, tom, and the kick as a bar), and **⊞ All**, the piano across the top with guitar and drums below. Guitar and drums look ahead as far as the delay allows.
- **Drums come from** the song's own MIDI drum track when its file is lined up with the radio, else from the audio (`drums.py`: kick, snare and hi-hat told apart by frequency band; toms and crashes aren't). Measured on live radio against songs' MIDI drums (a noisy answer key: fan MIDIs simplify the real pattern) it finds about 60% of kicks and hi-hats and 40% of snares in the right place, so heard drums follow the main beat but are not exact.
- **Played ▾** lists the songs so far and whether each was in the library.
- **⚙**: look on bitmidi.com for songs the library lacks (on by default: a match is downloaded
  into `~/MidiCoach/references/bitmidi`); use chord charts; finger numbers and note names.
  Scroll over the keys to change how fast the notes fall.

- **Shortcuts**: Space listen/stop, S stations, H played songs, M mute, ↑/↓ volume, F fullscreen.
  A splash shows until the app and the 3D hands are ready, the page says when it loses the app,
  and a *Resume* button on the start screen tunes back to the last station.

## How it works

| File | What it does |
|------|--------------|
| `tuner.py` | Reads the station (ICY titles cut out of the stream; HLS through PyAV), decodes it into a 7-minute ring of 44.1 kHz stereo. A sample's index since tuning in is the app's clock. |
| `songs.py` | Reads a station title both ways round (`Artist - Title`, `TITLE - ARTIST`, `Title by Artist`) and finds it in the library (by title words, then artist), or on bitmidi.com. Prepares the falling notes with `midi_coach`'s fingering and Clean. |
| `chroma.py` | The 12 pitch classes ten times a second, from the radio and from the MIDI's notes, compared as correlations. `align` finds where in the file (and at what speed, 0.80–1.20×: fan MIDIs are often 10% or more off the record's tempo) the last stretch of radio is. |
| `chords.py` | Names the chords heard (chroma plus the bass line against chord templates, smoothed with Viterbi) and voices them for two hands. |
| `tracker.py` | Ties it together: a title starts a song, its file is looked up and lined up with the radio; each good fit adds an anchor (stream second → MIDI second). Publishes the state twice a second. |
| `server.py` | Local web server: the page, the coach's `roll.js` / `hands3d.js` / hand models from `midi_coach/static` (unchanged), events, and the audio as raw PCM. |
| `drums.py` | Kick / snare / hi-hat onsets from the audio (spectral flux per band), and General MIDI drum notes to lanes. |
| `static/guitar.js`, `static/drums.js` | The guitar and drum highways. |
| `static/` | The page. Plays the PCM with Web Audio, so it knows which stream second is coming out of the speakers, and draws the hands at that moment. |

Lining up, measured on real radio: the right file scores about 0.63–0.76 (correlation), and 40
wrong files at most 0.50, so a fit counts from 0.52 (`chroma.SURE_SCORE`). A chorus heard twice
fits two places equally; either shows the right hands, and the time since the title changed
breaks the tie.

## Known limits

- **Coverage**: about 6,900 files, mostly older pop and rock. Current hits mostly get chords.
- **Titles**: some stations send none (CBC, some Bell streams) or send ads as titles. Type the
  song, or the chords are heard anyway.
- **Chord charts**: the coach's Ultimate Guitar client (`midi_coach/web.py`) currently gets
  `426 Upgrade Required` from UG's API, so charts are skipped and the chords come from the song
  file or the 24 triads.
- **Edits**: a radio edit that cuts a verse from the album version loses its place at the cut,
  then finds it again within a few seconds.
- **One-chord songs**: lining up goes by the harmony, so a song that sits on one chord for
  minutes (Superstition's funk riff) has little to line up by; it gets chords instead.

Tried on live stations (Nov 2026): Valerie, Alive and Kicking, Samba Pa Ti, Eternal Flame and
Allentown lined up within 10–15 s of music; Superstition didn't. About one classic-rock, oldies
or 80s station in five was playing a song from the library at any moment.
