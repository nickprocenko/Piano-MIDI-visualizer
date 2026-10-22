# midi-coach — an MCP server that lets Claude hear your playing

`midi-coach` is a local [MCP](https://modelcontextprotocol.io) server for Claude Desktop.
It records what you play on the JUNO-DS, analyzes it, compares it note-by-note with a
reference MIDI / MusicXML file, keeps a practice history, and plays passages back
through the keyboard.

Ask Claude things like:

- *"Record me playing the right hand of Clair de Lune, bars 1–8, and tell me what to fix."*
- *"Play bars 9–16 of the left hand at 70% so I can practice the right hand over it."*
- *"Let me hear my take of the worst bar, then how it should sound."*
- *"Am I getting better at the Moonlight Sonata?"*
- *"Wait mode on bars 1–8, right hand — I'm learning the notes."*
- *"Rehearsal at 80%, whole piece."*

## Practice from the sheet-music page

The coach page (**http://127.0.0.1:8765/**) has its own menu, so you can practice without
asking Claude to start each run:

| Control | What it does |
|---------|--------------|
| Lesson | Any lesson in `%USERPROFILE%\MidiCoach\lessons` (newest first), or the score Claude just showed |
| Input | MIDI input to listen on (remembered). If the keyboard is busy — e.g. the visualizer has it open — the `Coach` loopMIDI port is used instead |
| Learn / Rehearse / Record | Learn = the cursor waits for the right notes (`wait`); Rehearse = it moves at the tempo slider's speed (`rehearsal`); Record = play over the metronome and get it back as sheet music (below) |
| Hand, Bars | Practice one hand (the other is ignored) or a bar range |
| Loop | Restart at the end of the range; each pass is saved and graded as its own take |
| Start / Stop | One session at a time, shared with Claude |
| Metronome | BPM (type it, **Tap** it, or **Match score**), beats per bar, subdivision (quarters to sextuplets), six sounds, accent on beat 1, volume and a separate volume for the subdivisions. **M** starts/stops it. **Follow score**: Rehearse runs start with a count-in and the clicks follow the score — its tempo changes, time signatures and pickup bars, at your Tempo % — instead of waiting for your first note. Runs in the browser: no lag, no cost |
| Voice | The **Maestro**, a strict-teacher NPC, talks to you in a dialogue box (click to skip, click again to close). When you press Start it greets you with what it knows: the piece, its key signature, your best score on it, how long you've been away. When a looped run ends it sums up: passes, your best one, your weak bar. After each pass it speaks: a verdict, the exact slip ("Bar 3: that's F sharp, not F"), where you froze, rushed or dragged, how it compares with the last pass, and one instruction ("Isolate bar 3, five clean times in a row"). The wording changes every pass. Claude's own comments (`say`) are spoken too, at the volume you set. The *Natural (Kokoro)* voices sound human; the Windows voices are the fallback. Your choice is remembered. Browsers only let a page speak after you've clicked it once |

**Natural voice (Kokoro).** [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) is a small open
speech model that runs on your PC — free, offline, nothing leaves the machine. After installing
the requirements, download the model once (~340 MB, into `%USERPROFILE%\MidiCoach\kokoro`) and
hear a test line:

```bat
.venv\Scripts\python -m midi_coach.tts
.venv\Scripts\python -m midi_coach.tts "Keep the thumb under." bm_george
```

Restart Claude Desktop (or the practice page) afterwards. Each line takes about a second to
generate, so the coach speaks just after a pass ends, not mid-pass.

**Record mode.** Pick **Record**, set the metronome's BPM and beats per bar, press **● Record**,
and play after the count-in (one bar, two if the bar is short). Press Stop when you're done
(10 seconds of silence also stops). What you played is snapped to the beat — sixteenths, or
triplets where they fit clearly better — split between the hands by where they are on the keyboard (not at a fixed key), given a key signature,
and saved as a lesson (`Recording 2026-10-20 17-52`) that appears on the page straight away,
ready to practise in Learn or Rehearse. It's a readable sketch, not an engraving: notes held
under a moving line in the same hand are shortened. Claude's `transcribe_take` does the same for
any take, e.g. free play recorded without a click (it estimates the tempo; tell it the BPM if it
gets it wrong).

After each pass the page shows a one-line summary (e.g. *Pass 3 · Learn: 29/30 notes, 2 wrong,
bar 3 slowest, score 93*) and the bar heat map. Runs you start there are the same session as
Claude's `start_recording`, so with Claude Desktop open you can say *"give me feedback on
that"* and it picks up the pass with `wait_for_recording` / `compare_take`.

Without Claude Desktop: `.venv\Scripts\python -m midi_coach.practice` opens the page with
your newest lesson. Every pass is still saved, so Claude can review them later (`progress`).
Don't run it while Claude Desktop's midi-coach is running — they'd compete for the keyboard.

## Talk to the Maestro (voice chat, optional)

Tap **🎤 Talk** on the coach page, speak, tap again (or hold it, or hold **Space**, and let go
when you're done), or type in the box next to it. A level meter shows whether the microphone
hears you; pick the microphone in the menu next to it. The JUNO-DS's USB audio input is
not a microphone, so plug in a headset or USB mic. The Maestro
answers out loud in character and can run the practice for you:

- *"Hello. How did that go?"* / *"What's my best on this?"*
- *"Loop bars five to eight in Rehearse at seventy percent."* / *"Left hand only."* / *"Stop."*
- *"Play bars one to four for me."* (through the keyboard)
- *"Write me a G major arpeggio exercise."* / *"Switch to the C major scale."*

Your speech is transcribed **on your PC** (Whisper `base.en`, downloaded once, ~145 MB, to
`%USERPROFILE%\MidiCoach\whisper`). Only the text, plus a short summary of your practice,
goes to Claude: **Haiku 5.5** for the conversation and commands, **Sonnet 5.5** when it
writes a lesson (with server-side fallback enabled, so a declined request is retried on
another model).

This uses the **Claude API** (pay as you go), not your Claude subscription:

1. Create a key at console.anthropic.com and add credit.
2. Save it as `%USERPROFILE%\MidiCoach\anthropic_api_key.txt` (just the key), or set
   `ANTHROPIC_API_KEY` in the midi-coach `env` block of Claude Desktop's config.
3. Reload the coach page. The button switches on and shows today's spend.

Every request's cost is added up in `%USERPROFILE%\MidiCoach\ai_spend.json`. After
`MIDI_COACH_DAILY_CAP` dollars in a day (default **$0.50**) the Maestro stops calling the API
until tomorrow. A typical exchange on Haiku costs well under a cent; a new lesson from Sonnet,
a few cents.

## Custom lessons, pushed live

Ask Claude for an exercise and it appears on the coach page **immediately** — no file to
save or load. Ask for it "in the visualizer" too and it is also pushed into the visualizer's
Learn Mode (falling notes plus sheet music). For example:

- *"Write me a 4-bar left-hand exercise for the jump in bar 12."*
- *"Make a lesson out of my three worst bars from that take, right hand only."*
- *"Give me a G major contrary-motion scale, Wait mode."*

Claude writes each hand in music21 *tinyNotation* (`g4 a b c' d'2 r4 d'8 c' b1`,
chords as `chord{GG2 BB D}`), full MusicXML, or cuts an excerpt from a reference. The
server validates it (a typo is rejected instead of silently dropped), returns a
bar-by-bar readout so Claude can check it, saves it to `%USERPROFILE%\MidiCoach\lessons`
and publishes it. Lessons are normal references afterwards, so recording, Wait/Rehearsal
grading, heat maps and `progress` all work on them.

For the visualizer push (`to_visualizer=True`) the visualizer must be connected (Settings →
Hardware → *Practice Coach* → Connect; it
reconnects automatically after a reload). A lesson that arrives while you're in the middle
of something replaces the current Learn Mode song; a page that connects later receives the
latest lesson without auto-starting it.

## Live sheet music

midi-coach reuses the visualizer's OSMD sheet-music strip (`docs/notation.html`) as a
live score. Claude opens it at **http://127.0.0.1:8765/** (the coach page) when you
start a session; you can also show it inside the visualizer (below).

| Mode | Cursor | Grading |
|------|--------|---------|
| `wait` | Holds on each chord until you play every note of it (Synthesia *Melody Practice*) | Notes turn **green** as you hit them, the next chord is **cyan**, wrong keys flash in red. Time stuck per bar is recorded. |
| `rehearsal` | Starts on your first note and moves at `tempo_percent` (Synthesia *Song Recital*) | Notes turn **green** when hit within ±200 ms, **red** when they pass unplayed. |
| `free` | Score shown, no live grading | Analyzed after you stop (the original behavior). |

After every take the score shows a **bar heat map**: green = clean bar, through yellow to
red = most problems, with a label such as "2 wrong, 1 missed". `show_heatmap(take)` redraws
it for any earlier take. Wait-mode takes are scored on notes only, since the cursor waited.

**In the web visualizer:** Settings → Hardware → *Practice Coach (Claude)* → Connect. The
sheet-music strip then mirrors the coach (it takes over the strip from Learn Mode while
connected). When the visualizer runs from GitHub Pages, Chrome may ask to allow access to
devices on your local network — allow it, since the coach runs on `127.0.0.1`.

## Setup (Windows)

**Quick way:** from the repo root run `python midi_coach\setup_claude_desktop.py`. It
creates `.venv`, installs everything, lists your MIDI ports and adds midi-coach to Claude
Desktop's config (with a backup; other settings are kept). Add `--input Coach` if you use
a loopMIDI port. Then quit Claude Desktop from the tray and reopen it. The manual steps
below do the same thing.

1. **Install dependencies** (from the repo root, ideally in the same venv as the visualizer):

   ```bat
   python -m venv .venv
   .venv\Scripts\pip install -r midi_coach\requirements.txt
   ```

2. **Add the server to Claude Desktop.** Edit `%APPDATA%\Claude\claude_desktop_config.json`
   (Claude Desktop → Settings → Developer → Edit Config) and adjust the paths:

   ```json
   {
     "mcpServers": {
       "midi-coach": {
         "command": "C:\\path\\to\\Piano-MIDI-visualizer\\.venv\\Scripts\\python.exe",
         "args": ["-m", "midi_coach"],
         "env": {
           "PYTHONPATH": "C:\\path\\to\\Piano-MIDI-visualizer",
           "MIDI_COACH_INPUT": "Coach",
           "MIDI_COACH_OUTPUT": "JUNO"
         }
       }
     }
   }
   ```

   Restart Claude Desktop. A "midi-coach" entry should appear under the tools (🔨) menu.

3. **Reference files** are found in the visualizer's `config.json` → `search_folders`,
   plus any folders in `MIDI_COACH_REFERENCE_DIRS` (separate with `;`), plus
   `%USERPROFILE%\MidiCoach\references`. `.mid`, `.midi`, `.xml`, `.musicxml` and `.mxl` all work.

### Sharing the keyboard with the visualizer (virtual MIDI port)

Windows lets only **one** program open a MIDI *input* at a time, so the visualizer and
midi-coach can't both open the JUNO directly. Split it through virtual ports:

1. Install [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) and create two ports,
   e.g. **`Visualizer`** and **`Coach`**.
2. Install [MIDI-OX](http://www.midiox.com/). In *Options → MIDI Devices*, select the JUNO-DS as
   the input and both loopMIDI ports as outputs. MIDI-OX forwards the keyboard to both. Keep
   it running while you practice.
3. Point the visualizer at `Visualizer`, and set `MIDI_COACH_INPUT=Coach` (as in the config above).

Playback is unaffected: the visualizer only opens inputs, so midi-coach can send to the
JUNO's output directly (`MIDI_COACH_OUTPUT=JUNO`). If you won't run both at once, skip all
this and leave `MIDI_COACH_INPUT` unset — the JUNO is picked automatically.

## Tools

| Tool | What it does |
|------|--------------|
| `list_midi_ports` | Show MIDI inputs/outputs |
| `find_reference` | Fuzzy search the reference library by title |
| `inspect_reference` | Parts (track + channel) with their instrument, which hand each is, bars, tempo, pedal, long rests; suggests which parts to play |
| `set_parts` | Save which parts you play with which hand (remembered per file) |
| `start_recording` | Record from the input; optional reference / hand / bars; `mode` = free / wait / rehearsal |
| `wait_for_recording` | Block until the take ends; returns the comparison (or standalone analysis) |
| `stop_recording` | End the take now |
| `status` | Recording + playback status |
| `analyze_take` | Standalone analysis: pulse & evenness, pauses, dynamics, hands, articulation, pedal |
| `compare_take` | Take vs reference (see below); saved to history |
| `list_takes` / `progress` | Practice history, score trend, improved / persistent problem bars |
| `play` | Play a reference or take: bar range, single hand, tempo %, loops |
| `play_comparison` | A/B: your take of a passage, then the reference (at your tempo by default) |
| `stop_playback` | Stop, release notes and pedal |
| `show_score` | Show a reference on the live sheet-music page |
| `show_heatmap` | Draw a take's bar heat map on the live score |
| `say` | Speak a short comment aloud on the coach page (browser voice; mute with the page's Voice switch) |
| `transcribe_take` | Write a take out as sheet music (a two-staff lesson): Record-mode takes use their metronome grid, others get an estimated tempo or the `bpm` you give |
| `create_lesson` | Write a lesson (tinyNotation / MusicXML / excerpt) and show it on the coach page (`to_visualizer` also pushes it into Learn Mode) |
| `send_lesson` | Show an existing lesson or reference on the coach page (`to_visualizer`: Learn Mode too) |
| `search_chord_charts` | Search Ultimate Guitar (chords, tabs, bass, ukulele, drums, Guitar Pro), plus sheet-music search links |
| `get_chord_chart` | A chart's key, capo, chords, per-section progression and text; transpose; with `reference`, suggests the transpose that matches the score |
| `chords_in_score` | Names the chord in each bar (or half bar, or beat) of a reference from its notes, plus the estimated key |
| `search_youtube` | Recordings, performances and tutorials for a piece |

## Band arrangements

MIDI files downloaded from sites like freemidi.org or midiworld.com are usually full-band
arrangements rather than piano scores. `inspect_reference` names each part's instrument from
its General MIDI program (channel 10 is drums) and suggests what to play: the main keyboard
part (piano or organ) if there is one, otherwise the melody in your right hand and the bass
line in your left. Tracks that only double another (note for note or an octave apart) are
ignored; two tracks that are clearly one player's two hands are given a hand each; a
separate bass-register piano track joins the left hand; and a keyboard part that stays in the
treble gets the bass line in the left hand. Claude
shows you the parts and asks before going on, for example:

> 1 Track 3 — Acoustic Bass (low, E1–A2) · 4 Track 6 — Voice Oohs (melody) · 9 Drums …
> There's no piano part. I'd use the vocal melody in your right hand and the bass in your
> left. Sound right?

Your answer is saved with `set_parts` (in `<home>/part_choices.json`), and recording,
comparison, playback, the score and Learn Mode all use those parts from then on. Drums are
always left out unless asked for by part number. If the file changes so its parts no longer
match, the saved choice is ignored and you're asked again.

## Cross-referencing charts and recordings

The Ultimate Guitar and YouTube lookups are ported from the Music Practice app, so you can ask
things like:

- *"Pull up the chords for Let It Be and check them against my reference."*
- *"Which bars of my score don't match the chart's chorus?"*
- *"Find a slow piano tutorial for bars 9–16 on YouTube."*

`chords_in_score` works the harmony out from the notes, so it does best on accompaniment-style
writing. Busy melodies and passing notes lower each bar's `fit`. Charts are written by fans, so
when a chart and the score disagree, Claude is told to trust the score. These tools need an
internet connection; everything else stays local.

## How it works

**When does a recording stop?** After `silence_sec` (default 4 s) with no keys held.
If a reference is attached, the timeout is stretched to cover the longest *written* rest
still ahead in the piece, scaled to your current tempo — so a two-bar rest won't cut the
take short. Once you've played about all of the notes, the short timeout applies again.
A held sustain pedal keeps it alive for at least 12 s (let the last chord ring). There is
a hard cap (`max_minutes`, default 10), and it gives up after 2 minutes with no first note.

**Comparison.** Notes are grouped into chords and aligned to the reference with dynamic
programming, so a wrong or skipped note doesn't throw off everything after it, and rolled
chords still match. If you don't give a bar range, the section you played is detected
automatically. The report includes:

- **Notes** — correct / wrong (with expected vs played) / missed / extra, with bar & beat and hand.
- **Timing** — error relative to *your own local tempo* (playing slower than the score is
  not penalized), per hand, hands-together offset, and hesitations.
- **Tempo** — your BPM vs the score, bar-to-bar variation, rushing / dragging, and trend.
- **Dynamics** — velocity by hand, melody voicing, and how well you follow the score's dynamic
  shape (only when the reference has varied velocities).
- **Articulation** — key-down time vs written length, clipped / over-held notes, legato gaps.
- **Pedal** — blurred pedal changes, missing pedal, pedal where the score has none (when the
  reference contains CC64; otherwise it flags pedals held across several bars).
- **Scores** — overall = 50% note F1 + 30% timing + 20% tempo stability.

Takes are saved as `.mid` plus `.json` in `%USERPROFILE%\MidiCoach\takes` (override with
`MIDI_COACH_HOME`). Each comparison is appended to the take's JSON, which `progress` reads.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MIDI_COACH_INPUT` | JUNO, else the only port | Input port name substring |
| `MIDI_COACH_OUTPUT` | JUNO | Output port name substring |
| `MIDI_COACH_HOME` | `~/MidiCoach` | Takes and extra references |
| `MIDI_COACH_REFERENCE_DIRS` | — | Extra reference folders (`;`-separated) |
| `MIDI_COACH_CONFIG` | `<repo>/config.json` | Where to read `search_folders` |
| `MIDI_COACH_DISPLAY_PORT` | `8765` | Live score server port (next free port if taken) |
| `MIDI_COACH_NO_BROWSER` | — | Set to stop Claude opening the browser automatically |
| `ANTHROPIC_API_KEY` | `~/MidiCoach/anthropic_api_key.txt` | API key for talking to the Maestro |
| `MIDI_COACH_DAILY_CAP` | `0.50` | Daily voice-chat spending limit in dollars |

## Development

```bash
pip install -r midi_coach/requirements.txt pytest
python -m pytest midi_coach/tests
```

The tests use synthetic performances and a fake `rtmidi` module, so they run without hardware.
