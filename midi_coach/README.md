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

## Custom lessons, pushed live

Ask Claude for an exercise and it appears in the visualizer's Learn Mode (falling notes plus
sheet music) and on the coach page **immediately** — no file to save or load. For example:

- *"Write me a 4-bar left-hand exercise for the jump in bar 12."*
- *"Make a lesson out of my three worst bars from that take, right hand only."*
- *"Give me a G major contrary-motion scale, Wait mode."*

Claude writes each hand in music21 *tinyNotation* (`g4 a b c' d'2 r4 d'8 c' b1`,
chords as `chord{GG2 BB D}`), full MusicXML, or cuts an excerpt from a reference. The
server validates it (a typo is rejected instead of silently dropped), returns a
bar-by-bar readout so Claude can check it, saves it to `%USERPROFILE%\MidiCoach\lessons`
and publishes it. Lessons are normal references afterwards, so recording, Wait/Rehearsal
grading, heat maps and `progress` all work on them.

The visualizer must be connected (Settings → Hardware → *Practice Coach* → Connect; it
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
| `inspect_reference` | Parts (track + channel), which hand each is, bars, tempo, pedal, long rests |
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
| `create_lesson` | Write a lesson (tinyNotation / MusicXML / excerpt) and push it into Learn Mode |
| `send_lesson` | Push an existing lesson or reference into Learn Mode |
| `search_chord_charts` | Search Ultimate Guitar (chords, tabs, bass, ukulele, drums, Guitar Pro), plus sheet-music search links |
| `get_chord_chart` | A chart's key, capo, chords, per-section progression and text; transpose; with `reference`, suggests the transpose that matches the score |
| `chords_in_score` | Names the chord in each bar (or half bar, or beat) of a reference from its notes, plus the estimated key |
| `search_youtube` | Recordings, performances and tutorials for a piece |

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

## Development

```bash
pip install -r midi_coach/requirements.txt pytest
python -m pytest midi_coach/tests
```

The tests use synthetic performances and a fake `rtmidi` module, so they run without hardware.
