# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What's here

Several loosely coupled programs share one repo:

| Part | What it is | Entry point |
|------|-----------|-------------|
| `docs/` | The visualizer as a single-file web app (Web MIDI, Chromium only). Deployed to GitHub Pages on push to `main` when `docs/**` changes. No build step. | `docs/index.html` |
| `midi_coach/` | Python MCP server for Claude Desktop: records the keyboard, grades takes against a reference, writes sheet music, runs the coach page and the voice "Maestro". All active development is here. | `python -m midi_coach` |
| `src/` + `main.py` | Older pygame desktop version of the visualizer (pywebview overlays for OSMD sheet music and WebGL fluid, HTTP control panel on :8181). | `Launch Piano MIDI Visualizer.bat` |
| `server/` | Node audience-vote server (Kik webhook, WebSocket to the visualizer and `docs/overlay.html`). | `node server/server.js` |
| `firmware/` | ESP32 FastLED bridge for the LED strip (serial/BLE frame protocol is in the README). | Arduino sketch |

`reference/` (downloaded band MIDI library) and `config.json` are gitignored; `config.example.json` is the template.

## Commands

Windows, from the repo root, using the repo's `.venv`:

```bat
.venv\Scripts\python -m pytest midi_coach/tests                    :: full suite, ~50 s, no hardware needed
.venv\Scripts\python -m pytest midi_coach/tests -k <name>          :: one test
.venv\Scripts\python -m pytest midi_coach/tests/test_sheet_conventions.py

.venv\Scripts\python -m midi_coach.practice [piece]                :: coach page without Claude Desktop (http://127.0.0.1:8765/)
.venv\Scripts\python -m midi_coach.engraving <score.musicxml> --png <out_dir>   :: lint a score + render worst bars
.venv\Scripts\python -m midi_coach.render <score.musicxml> <out.png> [first last] :: render bars with OSMD in headless Chrome/Edge
.venv\Scripts\python -m midi_coach.songs "<song title>" ...        :: build song lessons from the reference library
```

There is no linter or formatter configured. Tests use a fake `rtmidi` and synthetic performances; `conftest.py` fails any test that tries to open a browser. `test_sheet_conventions.py` skips songs that aren't in the local `reference/` folder.

## midi_coach architecture

**Note model (`notes.py`).** Everything loads into a flat, seconds-based `Score` of `Note`s, with parts split by MIDI track + channel (matching the web visualizer's Learn Mode track list) and bars derived from the file's time-signature and tempo maps. Part/hand selection (`playable_parts`, `select_notes`, `suggest_hands`, `effective_hands`) lives here too; the user's confirmed choice is saved per file in `<home>/part_choices.json` via `library.py` and every downstream feature (grading, playback, sheet, Learn Mode) reads it.

**Grading.** `analysis.py` groups onsets into chords and aligns take vs reference with dynamic programming, then scores notes/timing/tempo/dynamics/articulation/pedal. `live.py` runs the Synthesia-style `wait` and `rehearsal` modes in real time and pushes cursor/marks to the display. `remarks.py` turns a graded pass into the Maestro's spoken feedback.

**Sheet-music writers.** `transcribe.grand_staff` is the shared MusicXML writer. Callers: `transcribe.py` (takes → lessons), `sheet.py` (piano sheet for a band MIDI, cached in `<home>/derived`), `songs.py` (vocal line over the piano part), `lessons.py` (tinyNotation / MusicXML / excerpts). `regrid.py` recovers a beat grid for MIDI files whose notes drift off their own bar lines; it changes notation only, never note times. `engraving.py` holds `RULES`, readability checks run on what the reader sees.

**Display (`display.py`).** A localhost HTTP server (port 8765) pushes state over Server-Sent Events. Two front ends consume the same stream, and both render through `docs/notation.html` (the visualizer's OSMD strip): the coach page `midi_coach/static/coach.html`, and the web visualizer's notation strip when connected via Settings → Hardware → Practice Coach. So changes to `docs/notation.html` affect both the coach and the deployed site. The coach page drives runs with `POST /cmd/<name>`, handled by callables registered on `DisplayHub.commands`.

**MCP server (`server.py`).** Defines every tool (listed in `midi_coach/README.md`) and wires the modules above together. `practice.py` reuses it without Claude Desktop. Only one process can own the MIDI input and display port, so `practice` and Claude Desktop's midi-coach must not run together.

**Maestro (voice).** `chat.py` uses the Claude API (Haiku for conversation/commands, Sonnet for writing lessons) with spend metered to `~/MidiCoach/ai_spend.json` against `MIDI_COACH_DAILY_CAP`. `deep.py` hands teaching questions to headless `claude -p` on the user's subscription, which connects back through a local MCP endpoint (port 8780). `stt.py` (faster-whisper) and `tts.py` (Kokoro) run locally.

**User data** lives in `MIDI_COACH_HOME` (default `~/MidiCoach`): `takes/`, `lessons/<category>/`, `derived/`, part choices, notes. Lesson categories are folders; `organize_lesson` moves a file and rewrites the takes and part choices that point to it, so don't move lessons with plain file operations.

## Conventions for sheet music

- A messy score is a bug. Before showing any MusicXML the coach wrote, run `midi_coach.engraving` on it (no rule broken, no source note lost) and render the opening and the worst bars to PNG with `midi_coach.render`, then look at them.
- When a new kind of mess turns up, add it to `engraving.RULES` with a regression test and fix the writer, not just the one file.
- Lessons built from a source file keep its pitches, rhythms and parts exactly. Only notation-level cleanup is allowed (grid snapping, clefs, 8va/8vb that keeps the true pitch for grading), and the change is recorded in the MusicXML `<identification><source>`. New song lessons go to the *Needs review* category.

## Docs

`midi_coach/README.md` is the user-facing manual (tools table, env vars, setup, practice page). Update it when you add or change a tool, env var or page control.
