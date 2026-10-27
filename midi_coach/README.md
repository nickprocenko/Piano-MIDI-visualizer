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
| Songs / Lessons (left panel) | **☰ Songs & lessons** shows or hides it. **Songs**: your song lessons by category, then the whole reference library — type to search it (every word must be in the file name); with nothing typed it lists the library songs you practised last. **Lessons**: teaching material (the *Exercises* and *AI exercises* categories), most recently practised first. Every entry shows its history from your saved takes: runs, best score, when you last played it. Click one to load it. See [Lesson categories](#lesson-categories) |
| Input | MIDI input to listen on (remembered; hidden in Listen, which doesn't use it). If the keyboard is busy — e.g. the visualizer has it open — the `Coach` loopMIDI port is used instead |
| Listen / Learn / Rehearse / Record | A line next to the buttons says what the selected mode does. **Listen** = you don't play: the keyboard plays the piece (with its sustain pedal) on the output under *Sound goes to*, at the tempo slider's speed, and the cursor follows; Bars and Loop apply, nothing is graded or saved. It plays every part that's shown (vocals only with their Sound on), so hide a hand under **Hear ▾** to hear the other alone. Learn = the cursor waits on each chord for the right notes, then flows on at the tempo slider's speed (`wait`); Rehearse = it moves at the tempo slider's speed (`rehearsal`); Record = play over the metronome and get it back as sheet music (below) |
| Play ▾ / Hear ▾ (Parts) | Per piece, remembered in the browser. For the right hand, left hand, pedals (feet) and vocals: **You play** (graded; Learn waits for it), **Show** (drawn on the sheet, or hidden) and **Sound** — a part you don't play but can see is muted until you turn it on, then the keyboard plays it along with you on the MIDI output chosen under *Sound goes to*: in time in Rehearse, and in Learn the stretch up to the next chord each time you play one (so it waits for you too). Only notes are sent — no sustain pedal or all-notes-off that would catch the notes you hold. **What each part is**: each part of the file as Right hand, Left hand, Both hands (split by register), Pedals (a bass line played with your feet), Vocals (shown and heard, never graded) or Off; **Save parts** remembers it for the file, like `set_parts` |
| Bars | Practice a bar range |
| Loop | Restart at the end of the range; each pass is saved and graded as its own take |
| Maestro decides | With Loop on, the Maestro changes the practice between passes the way a teacher would, says what it did, and the menu follows: the same problem bar in two passes → loop it with a bar either side (back to your section after three clean passes); a rough pass in Rehearse → 10% slower (not below 50%); two rough passes with both hands → right hand alone, then left, then both (two clean passes each); three clean passes in Learn → Rehearse at 70%; three clean in Rehearse → 5% faster (up to 100%). Say or type *"no"* / *"undo"* to put the last change back (handled on your PC, no API call) |
| Maestro: Warm / Strict | How the Maestro coaches, remembered between sessions (also by voice: *"be a bit gentler"*). **Warm** (default) is encouraging and says what went well before what to fix; **Strict** is dry and demanding. Either way it names the exact bar and note |
| Start / ▶ Listen / Stop | One session at a time, shared with Claude |
| Metronome | In the menu bar: **♩ Metronome** starts it, the **BPM ▾** button next to it opens its settings — BPM (type it, **Tap** it, or **Match score**), beats per bar, subdivision (quarters to sextuplets), six sounds, accent on beat 1, volume and a separate volume for the subdivisions. **M** starts/stops it. **Follow score**: Rehearse runs start with a count-in and the clicks follow the score — its tempo changes, time signatures and pickup bars, at your Tempo % — instead of waiting for your first note. Runs in the browser: no lag, no cost |
| Voice | The **Maestro**, a teacher NPC, talks to you in a dialogue box (click to skip, click again to close). When you press Start it greets you with what it knows: the piece, its key signature, your best score on it, how long you've been away. When a looped run ends it sums up: passes, your best one, your weak bar. After a pass it says at most two sentences, and only when there's something new: how it went or how it compares with the last pass, then the one thing to know. The first time a slip shows up it's named ("Bar 3: that's F sharp, not F"); the second time comes how to fix it ("Bar 3 again; take it on its own, slowly"); after that just a word ("Same spot."). Clean passes in a row stay quiet except at three and five. Wording never repeats the last half of its choices, even across sessions (`%USERPROFILE%\MidiCoach\maestro.json`). Claude's own comments (`say`) are spoken too, at the volume you set. The *Natural (Kokoro)* voices sound human; the Windows voices are the fallback. Your choice is remembered. Browsers only let a page speak after you've clicked it once |

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

**The sheet strip.** The playhead stays in the middle and the score scrolls under it on a smooth
curve through the notes, so the speed doesn't jump from note to note; small timing corrections
from the coach are blended in rather than jumped to. Once bar 1 scrolls away, the clefs, key
signature and time signature stay pinned at the left edge and change where the score changes
them. The same strip is the visualizer's sheet music, so it does this there too.

**Record mode.** Pick **Record**, set the metronome's BPM and beats per bar, press **● Record**,
and play after the count-in (one bar, two if the bar is short). Press Stop when you're done
(10 seconds of silence also stops). What you played is snapped to the beat — sixteenths, or
triplets where they fit clearly better — split between the hands as a pianist would play them (not at a fixed key; see [Splitting one part between the hands](#splitting-one-part-between-the-hands)), given a key signature,
and saved as a lesson (`Recording 2026-10-20 17-52`, under *Recordings*) that appears on the page straight away,
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

### Mock exams

Each grade of the Atlas ends in a mock exam, shaped like a graded piano exam and marked out
of 150 by the coach. It is a mock: the marking is the coach's own, not an exam board's. Open
it from the grade's exam node (**Take the mock exam**), or ask Claude (`start_exam`). An
exam card above the sheet music shows the sections, the examiner's request (spoken as
*Examiner*), and a button for the next thing to do:

| Section | What happens | Marks |
|---------|--------------|-------|
| Pieces | One from each list (A, B, C) of the grade's public-domain pieces, the ones you've worked on most first. **Begin**, play it through; it ends a few seconds after you stop | 3 × 30: pitch, time (steady, at tempo, no hesitations; less weight on steadiness in lyrical List B pieces), tone (estimated from your touch, low weight), shape (dynamics, note lengths, pedal), performance (keeping going, the whole piece). Fewer than 75% right notes caps it at 19, more than two stops of 1.5 s at 22, under 70% of the tempo at 23 |
| Scales and arpeggios | 4–8 drawn from the grade's list, asked for by name (*"B flat major, two octaves, hands together"*), played from memory with the music hidden | 21, from right notes, evenness and speed; the wrong scale scores nothing |
| Sight-reading | A piece you haven't seen: **Look at the music** gives 30 seconds, then **Play it now** | 21 |
| Aural | Each test opens its questions in the step panel; the first answer to each counts | 18 |

Pass is 100, merit 120, distinction 130. **Skip** scores a task 0, **Stop exam** abandons it
unmarked. An exam is saved after every task (`%USERPROFILE%\MidiCoach\atlas\exams`), so
reloading the page or restarting the coach picks it up where it stopped. When it's done, the
card shows the marks table and a written report, and the grade's exam node becomes Proficient
at a pass and Mastered at merit. The marking numbers are in `midi_coach/atlas/data/marking.json`.

**Find my level** (in the Atlas bar, or Claude's `start_placement`) runs full mock exams from
the grade you pick. Each pass moves up a grade until one isn't passed; if the first isn't, it
steps down a grade at a time until one is. Then every grade up to the highest one passed is
credited (its stages count as Proficient), and the first grade not passed becomes your active
goal, with that exam's weakest items first on its Path. Between exams the card offers the next
one or **Later**; stopping an exam pauses placement, and Continue sits that grade afresh. Its
progress is kept in `%USERPROFILE%\MidiCoach\atlas\placement.json`.

**Goals and Paths.** Tell the Maestro a goal (*"I want to play Piano Man"*, *"sight-read
hymns"*, *"get through Grade 3"*) or type it in the Atlas's **Path** panel (with a song file
from your library, if it's a song). It asks at most two follow-up questions, then Claude Code
plans it on your subscription in the background (a minute or two):

- **Song research** first, for a song: Hooktheory's TheoryTab (key, BPM, metre, sections,
  the chords of each section), then Wikipedia, publisher pages and lessons, every fact with
  its source. A fact two sources share, or one source and your file, is *confirmed*; a
  single source's is *reported*; where a source disagrees with your file it's a *conflict*,
  shown as such ("TheoryTab says 6/8; the file is written in 3/4"). Your file stays the
  truth for the notes. Facts are cached for 90 days in `<home>\derived\song_facts`.
- **The plan:** the requirements, families or exams the goal needs, which to bring forward,
  at most five **bridges** for skills the syllabus doesn't name (a walking bass in C, say),
  and its reasons with their sources. Unknown ids go back to be fixed before anything changes.
- **The Path:** every requirement the goal needs that you don't know yet, prerequisites first,
  grouped into families; for a song, the song itself is the last stop (learnt section by
  section like a piece). Bridges sit dashed in the margin lane at the right of their grade,
  saying *writing…* until their lessons are written (in the background, checked like the
  theory lessons below).

The **Path** panel lists the active goal's families in order with their rings; open one for
its requirements and stages. **Next** (or *"what's next?"* to the Maestro) opens the next
unfinished stage. Several goals can be open, one active; **Archive** puts one away and its
bridges leave the Atlas. Claude Desktop can do the same with `plan_goal`, or plan a goal
itself and save it with `save_goal`.

**Drills.** When the same bar trips you up (some of the same notes wrong or missed) in 2 of
a stage's last 3 graded passes, a short **drill** joins the margin lane: that bar with one
either side, from the same file and hand: listen at 70% and learn it, learn it again, then
rehearse it at 80%. On any Path that has the requirement it came from, the drill comes first,
so **Next** goes there. It retires once Proficient; if the bar starts slipping again
afterwards, it takes two fresh slips to bring a new one back. A one-off slip makes nothing,
and so does a pass that slips in more than half its bars (the stage itself works on that).
At most two drills come from one pass. The Maestro knows which drills are waiting.

**Lessons written by Claude.** The theory lessons are written in batches by Claude Code on
your subscription, checked automatically before they're saved (step shapes, quiz answers, a
named note matching the note written, every music example built, linted with all the
engraving rules and read back note for note; problems go back for up to two repair rounds):

```bat
.venv\Scripts\python -m midi_coach.atlas.generate --tiers initial,g1,g2 --dry-run
.venv\Scripts\python -m midi_coach.atlas.generate --tiers initial,g1,g2
```

It skips stages that already have a lesson and stops cleanly at the usage limit, so run it
again later to carry on (`--node <id> --force` rewrites one). Each run is logged in
`<content>\manifest.json`. These lessons show **Needs review** in the step panel until you
press **Looks right**; **Something's wrong** asks what, and notes it in
`%USERPROFILE%\MidiCoach\atlas\feedback.jsonl` for rewriting.

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
- *"Be a bit gentler."* / *"Be strict with me today."* (the Warm / Strict setting)

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

### Deeper questions and song lessons (on your Claude subscription)

Questions that need real teaching go from the Maestro to **Claude Code**, signed in with your
claude.ai account, so they use your subscription rather than API credits:

- *"Teach me this song."* / *"Next section."* / *"Why is bar twelve so hard?"*
- *"What's the story behind this piece?"* / *"Explain the chords in the bridge."*
- *"Make me a practice plan for this week."* / *"Ask Desktop."* / *"Go deeper."*

The Maestro says it'll think it over. About half a minute later the answer comes in the
Maestro's voice. A song lesson goes one section at a time: the Maestro explains the section,
plays it through the keyboard, then starts a Learn run on those bars. A follow-up within two
hours continues the same conversation, so *"next section"* picks up where you left off.

One-time setup: install Claude Code (`irm https://claude.ai/install.ps1 | iex` in PowerShell)
and sign in once by running `claude`. Each run connects back to the coach through a local MCP
endpoint (`http://127.0.0.1:8780/mcp`). The run gets the coach's tools and web search, and no
file or command access. Usage counts toward your plan's limits.

If Claude Code isn't installed, or a run fails (signed out, usage limit), the question is saved
to `~/MidiCoach/maestro_inbox.json`. In Claude Desktop, say *"check the Maestro's inbox"* and it
answers from there.

**The Maestro's notebook.** `~/MidiCoach/maestro_notes.md` holds lasting facts about you:
goals, pieces you're learning, weak spots, how you like to be taught. The voice chat, the deep
answers and Claude Desktop all read it and add to it (`remember`). Edit it freely.

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
bar-by-bar readout so Claude can check it, saves it to `%USERPROFILE%\MidiCoach\lessons\AI exercises`
(an excerpt of a real piece: `Exercises`) and publishes it. Lessons are normal references afterwards, so recording, Wait/Rehearsal
grading, heat maps and `progress` all work on them.

### Lesson categories

Each folder in `%USERPROFILE%\MidiCoach\lessons` is a heading in the page's left panel:
*Exercises* and *AI exercises* under **Lessons**, every other category under **Songs**.

| Category | What goes there |
|----------|-----------------|
| Needs review | Lessons made from a file that nobody has checked against the music yet — new song lessons land here |
| Solo piano | Piano arrangements of whole pieces (both hands, melody included) |
| Vocals & accompaniment | Songs with a vocal line (and lyrics) above the piano part you play |
| Exercises | Excerpts cut from real pieces (`create_lesson` with `from_reference`) |
| AI exercises | Lessons composed entirely by Claude or the Maestro (scales, drills, studies) |
| Recordings | Your Record-mode takes written out as sheet music |

Any other folder you make there becomes a category too; files left directly in `lessons`
show under *Unsorted*. Ask Claude to file something (*"put the Rousseau Piano Man under Solo
piano"*, *"Let It Be is checked — move it to Vocals & accompaniment"*) and `organize_lesson`
moves it — from the lessons or from the reference library — and updates your takes and saved
part choice so progress history stays with it. Moving files yourself in Explorer works for the
panel, but takes would still point at the old path.

**Where a lesson came from** is kept in the file (MusicXML `<identification><source>`): the
source file, whether the notes were converted from MIDI (lengths and rests read from how long
keys were held — the part most worth checking) or taken from a MusicXML score, and what was
changed. The panel marks MIDI conversions *from MIDI* and shows the whole note when you
hover over a lesson; the status line repeats the tag when you load one. Categories say what you
practise; the source note says how far to trust the notes.

### Song lessons

*"Make a song lesson from Let It Be"* — `make_song_lesson` writes a band file as its vocal line
over the piano part you play (`python -m midi_coach.songs "Let It Be" …` does the same from a
terminal). The tune is the part named vocal / melody / lead, else a voice or lead instrument; the
result says which (a sound effect or the highest strings is a guess — pass `melody_part`). A
karaoke MIDI file's lyrics go under the tune. Time signature changes are kept, and the key
signature changes where the song modulates (below). Every note read back is checked against the
source, and the lesson goes to *Needs review* with its source note.

### Readable sheet music: rules, checked and looked at

Every sheet the coach writes (piano sheets, transcriptions, song lessons) is held to the rules in
`midi_coach/engraving.py`, checked on what the reader sees — each one a mistake found once that
must not come back: no missing or needless accidentals (none on every E flat in E flat major; a
natural on A3 after A2 natural), no nested or odd tuplets (one grid per beat, sixteenths or
triplet eighths), nothing shorter than a sixteenth, no double dots, no short gaps inside the
sung line, no hyphen leading to a new word, at most two voices a staff, no needless ties,
ledger lines kept in check with clef changes or an 8va/8vb over a passage (never a needless or
crowded one), key changes no closer than six bars, and the title printed once. And no note of
the source may be lost: every song lesson is read back and compared note for note (an 8vb keeps
the true pitch for grading). A source played in live, whose beat can't be recovered, is refused.

```bat
.venv\Scripts\python -m midi_coach.engraving "%USERPROFILE%\MidiCoach\lessons\Needs review\X.musicxml" --png out
.venv\Scripts\python -m midi_coach.render lesson.musicxml bars.png 1 8
```

The first lists the rules a score breaks, with its worst bars, and draws bars 1–8 and those bars;
the second draws any bars, with the same library as the coach page (in a headless Chrome or
Edge), so a score can be looked at — what the rules don't cover yet shows up there. Song lessons
report their findings under `readability`; the tests hold the band sheets in
`test_sheet_conventions.py` to the rules too.

**Key signatures.** Piano sheets, transcriptions and song lessons choose a key signature bar by
bar — the one leaving the fewest accidentals — and only change it where the music stays in a new
key for a while: about six bars for a modulation that lasts (a last chorus a step up), twice that
for a passage that comes back. A borrowed chord or a short excursion gets accidentals instead, as
a printed score would.

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
| `wait` | Holds on each chord until you play every note of it (Synthesia *Melody Practice*), then flows on at `tempo_percent` through held notes and rests to the next one instead of jumping | Notes turn **green** as you hit them, the next chord is **cyan**, wrong keys flash in red. Time stuck per bar is recorded. |
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
| `inspect_reference` | Parts (track + channel) with their instrument, what each is (a hand, pedals, vocals), bars, tempo, pedal, long rests; suggests which parts to play |
| `set_parts` | Save what each part is — `right` / `left` / `both` hands, `pedals` (feet), `vocals` (shown, never graded) — remembered per file |
| `start_recording` | Record from the input; optional reference / hand (`both` / `right` / `left`, `+pedals` to add the feet, or `pedals`) / bars; `mode` = free / wait / rehearsal; `backing` = parts you don't play to sound on the MIDI output along with you |
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
| `organize_lesson` | Move a lesson or reference into a category of the page's Songs / Lessons panel (optionally renaming it); takes and part choices follow |
| `start_exam` | Start (or resume) a mock exam for a grade (`initial`, `g1`..`g8`) on the coach page; see [Mock exams](#mock-exams) |
| `exam_report` | Marks and written report of a finished mock exam (the latest, or of a grade or id), and the exam in progress |
| `atlas_overview` | Each grade's progress on the Atlas, mock exam bests, the active goal and its next stop |
| `atlas_node` / `open_node` | One Atlas node with its state, stages and lesson / open a stage's lesson on the page |
| `list_goals` | The goals, the active one's Path (families in order, requirements and stages), the planner's status, reasons and sources |
| `plan_goal` | Plan a goal (a song, skill or grade) with Claude Code on the subscription, in the background; a song is researched first |
| `save_goal` | Save a goal you planned yourself (targets, up to 5 bridges, order, reasons); checked like the planner's |
| `piece_grade` | Estimate a piece's (or passage's) grade from its measured features |
| `rebuild_progress` | Recompute the Atlas progress from the takes and the event log |
| `start_placement` | Find your level with mock exams from a grade (up until one fails, or down until one passes); credits the grades passed and sets the first grade failed as the goal. `resume=True` continues one under way |
| `make_song_lesson` | A band file as its vocal line (with karaoke lyrics) over your piano part, key and time signature changes included; saved in *Needs review* with a note on where it came from |
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
treble gets the bass line in the left hand. A bass-guitar part you play is moved up an octave,
as bass parts are written (and so a 61-key keyboard reaches it); the sheet, grading and
playback all use it there. Claude
shows you the parts and asks before going on, for example:

> 1 Track 3 — Acoustic Bass (low, E1–A2) · 4 Track 6 — Voice Oohs (melody) · 9 Drums …
> There's no piano part. I'd use the vocal melody in your right hand and the bass in your
> left. Sound right?

A part named for the pedals (*Pedal*, *Pedals*) is suggested for your feet rather than a hand,
and one named as the vocal line (*Vocals*, *Lead Vocal*, *Voice*, *Singer*) as vocals when
there's a keyboard part for the hands — the sung line of a song lesson is never graded as
piano. The piano sheet puts the vocals on a staff above the piano and the pedals on one below.

Your answer is saved with `set_parts` (in `<home>/part_choices.json`), and recording,
comparison, playback, the score and Learn Mode all use those parts from then on. Drums are
always left out unless asked for by part number. If the file changes so its parts no longer
match, the saved choice is ignored and you're asked again.

### Splitting one part between the hands

When both hands come from one track (a solo-piano file on one track, or a band's piano part),
the notes are split by a search over the whole piece that keeps each hand playable: within
reach (counting keys still held), near where it just played, a line of single notes in one
hand. When it's installed, a trained model steers the search: the hand-part network from
[PM2S](https://github.com/cheriell/PM2S) (Liu et al., ISMIR 2022, MIT licence), run with
onnxruntime, which reads the hands from the music rather than from a split key. The model
alone sometimes gives one hand a chord two octaves wide or a jump no hand makes, and now and
then has the hands the wrong way round; the search overrules it there. Measured on the 797
two-track piano files in `reference/` (`tools/hand_split_bench.py`), about 93% of notes go to
the right hand with the model and 90% without (87% for a split at middle C), and seven bars
in ten have no note in the wrong hand, against one in two.

The model is one file, `%USERPROFILE%\MidiCoach\models\pm2s_hand_part.onnx` (~41 MB). It is
built once from PM2S's published weights by `tools/export_pm2s_hand.py`, which needs PyTorch
in a separate, throwaway environment (the steps are at the top of the script); the coach itself
needs only onnxruntime. Check it with `.venv\Scripts\python -m midi_coach.hand_model`. Each
split is cached in `<home>/derived`, and sheets made before the model was installed are
rebuilt with it.

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
| `MIDI_COACH_CLAUDE` | `claude` on PATH, else `~/.local/bin/claude.exe` | Claude Code, for the Maestro's deep questions |
| `MIDI_COACH_DEEP_MODEL` | `sonnet` | Model Claude Code uses for deep questions |
| `MIDI_COACH_GENERATOR_MODEL` | `sonnet` | Model Claude Code uses to write the Atlas's lessons (`python -m midi_coach.atlas.generate`) |
| `MIDI_COACH_ATLAS_CONTENT` | `<home>/atlas/content` | Where the Atlas's syllabus, built tree and lessons live (kept out of git: the syllabus is the exam board's copyright) |
| `MIDI_COACH_MCP_PORT` | `8780` | Local MCP endpoint those runs connect to (next free port if taken) |
| `MIDI_COACH_HAND_MODEL` | `<home>/models/pm2s_hand_part.onnx` | The hand model to split parts with; `off` uses the search instead |

## Development

```bash
pip install -r midi_coach/requirements.txt pytest
python -m pytest midi_coach/tests
```

The tests use synthetic performances and a fake `rtmidi` module, so they run without hardware.
`test_sheet_conventions.py` also holds the piano sheets of a few band files from the downloaded
`reference/` library to piano-notation conventions (reach, clefs, accidentals, marks); songs that
aren't downloaded are skipped. The tests split hands with the search (`MIDI_COACH_HAND_MODEL=off`),
so they pass with or without the model; one more test checks the model when it is installed.

`tools/hand_split_bench.py` scores the hand split against every piano in `reference/` that is
already on two tracks (`--scan` finds them once; `--against HEAD` adds the committed version).
