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

The coach page (**http://127.0.0.1:8765/**) opens to a Home hub, where you choose a mode:
**Session** for the score and its Learn / Rehearse / Listen controls (play anything you like;
nothing there pushes an exam), **Explore music** to search songs and lessons (full screen from
Home; in a Session, **Change piece** opens it beside the sheet, and **⇤** / **⤢** switch between
them), **Record a new idea** to play over the metronome and get your take back as sheet music,
the **Roadmap** for the learning map, goals, and where to start, and **Play along on YouTube**. **Today** at the top of Home
plans your practice for the day ([Today](#today-one-button-practice)). The bar at the top only
has **Home** and the name of the mode you're in: to change modes you go back to Home (the Roadmap's
**← Home** and Esc do the same). If leaving would stop a run or a recording, it asks first,
whether you clicked or the Maestro asked: **Stop and go** or **Cancel** (a recording stopped
this way is kept, as Stop always does). Asked to start a run from elsewhere, the Maestro brings
the Session up for it. In a Session, the piece's title and status sit above one row of
controls; the Maestro has its own floating panel ([below](#talk-to-the-maestro-voice-chat-optional))
and the colour key is in the bar along the bottom:

| Control | What it does |
|---------|--------------|
| Home / Practice / Explore / Roadmap | Start with a clear task, then use the top navigation to return to the score, search for music, or view your learning map and goals |
| YouTube | Play along with a song's video on youtube.com: whether the extension is connected (or needs a reload), the song open now with its video, the extension's setup steps, and every song you've synced to a video. See [Videos that only play on YouTube](#videos-that-only-play-on-youtube) |
| File | The menu left of Home. **Open file…** (Ctrl+O): a MIDI or MusicXML file from your computer; a copy is kept in your lessons (*Unsorted*) and shown, and opening the same file again reuses it. **Save as…** (Ctrl+Shift+S): a copy of the sheet on the page under a new name, in any category (or a new one); it keeps the sheet's parts, starts with no practice history, and becomes the sheet you're on. **Download sheet file**: the file the sheet comes from, to your Downloads. **Switch profile…** opens the profile menu **Song folders…**: where songs are found (the same dialog as Preferences → Song folders → Change folders…). New songs are noticed by themselves: a MIDI or MusicXML file added to a song folder, or (with **Pick up new songs from Downloads**, on by default) saved into Downloads, shows up in the Songs search within a few seconds, a download copied into `references/downloads`, and the status line offers **Open it**. **Rescan now** looks through every folder again at once. |
| Preferences | Beside File (Ctrl+,). Its settings are remembered in this browser. **Connections**: whether the page is connected to the coach, and the MIDI input and output (the same choices as under **Playing**: MIDI input and *Sound goes to*), with **Refresh** after plugging a keyboard in. **Microphone & speakers**: the microphone everything that listens uses (talking to the Maestro, singing and spoken answers in lessons, the flute, sax or voice), with a level bar to check it hears you. A USB microphone or headset plugged in later is added to the list straight away, and the header says so. **Allow the microphone** appears until Windows has let the page use one, since device names stay hidden until then. **Speakers** picks where the page's own sounds go (the Kokoro voice, the metronome, lesson tones), with **Test**. **Audio to MIDI**: how the microphone turns the flute, sax or voice into notes (buffer size, noise gate, pitch clarity, note timings, input latency), with a live graph of what it hears and a list of the notes it sends (see [Flute: the flute Roadmap and the microphone](#flute-the-flute-roadmap-and-the-microphone)). Windows voices always use the default speakers, and the keyboard's sound follows Sound out. **Maestro**: coaching style, when it speaks in a run (the same three as the **Maestro** menu), read replies aloud, voice and volume. **Sheet**: sheet / falling notes / both, layout, zoom, dynamics (the same as the **Maestro** and **Sheet** menus). **Song folders**: the folders the Songs search looks in (and every folder inside them). **Change folders…**: paste a path or press **Browse…** for Windows' folder picker, then **Add**; **Remove** stops searching a folder without touching its files. Saved in `config.json` → `search_folders`, so the desktop visualizer uses the same list. The tick box below turns the bitmidi.com search on or off. **Shortcuts**: the page's keyboard shortcuts |
| Explore | Opens the search as a panel to the left of the sheet, so the piece you're practicing stays where it is; choosing an entry loads it and the panel stays open. **✕** closes it. **Songs** lists your song lessons and the reference library; search matches every word in the file name. With an empty search it shows songs you practiced recently. Under the results, **Search bitmidi.com for “…”** looks for the song online (only when pressed). Rarer words count most, so *halloween theme* puts the Halloween files ahead of every other "… Theme". Clicking a result downloads it into `%USERPROFILE%\MidiCoach\references\bitmidi` and opens it; next time the library search finds it. A file's name there is only what its uploader called it, so check what you get. **Lessons** lists teaching material (the *Exercises* and *AI exercises* categories), most recently practiced first. Entries include take history. See [Lesson categories](#lesson-categories) |
| Playing / Sheet / Maestro / Playback / Settings / Actions | Drop-downs in the same row as the mode buttons, one kind of setting each (one open at a time; a click elsewhere or Escape closes it). **Playing**: MIDI input, what you play and the file's tracks (below); its label says what you're set to (*Playing: Both hands*, *Listening: 3 of 20*), with 🔊 when tracks play along. **Sheet**: show the sheet music, the falling notes (the visualizer's view; scroll on it to change how fast they fall) or both, plus labels, dynamics and layout, and, under *This sheet*, Analysis (Add chords & lyrics), Two hands (Clean) and Cleanup (Auto clean) when the open sheet offers them. **Maestro**: coaching style, when it speaks in a run (**Hello at Start**, **After a pass**: every pass / when something's new / nothing, **Sum up at the end**), Maestro decides, reading replies aloud (voice and volume). **Playback**: the bar timeline, with previous/next bar, restart, Loop and bookmarks; then **Bars** (from–to), **Tempo**, and the **Lead-in** (bars of backing before your first bar, and whether every loop pass gets one) when tracks play along. **Settings** and **Actions** hold what works in every mode. **Settings**: Sound out (the same as Playing's *Sound goes to*), **Keep the screen on** (stops the screen dimming or locking while the page is open; remembered in the browser), and shortcuts to Preferences' Connections, Mic & speakers and Shortcuts. **Actions**: back to the start, bookmark this bar, metronome on/off, play along with a video, change piece, ask the Maestro, save a copy, download the sheet file, full screen; an item is greyed out when it can't run (no sheet, no Maestro). The metronome sits beside them |
| Learn / Rehearse / Listen | Hover over a mode button (or Start) to see what it does. **Listen** = you don't play: the keyboard plays the piece (with its sustain pedal) on the output under *Sound goes to*, at the tempo slider's speed, and the cursor follows; Bars and Loop apply, nothing is graded or saved. It plays every track that isn't muted under **Playing** (Listen has its own Mute and Volume, every track on at first), shown on the sheet or not, each at its own volume, and the cursor follows what sounds; mute a track there to hear the rest without it. Learn = the cursor waits on each chord for the right notes, then flows on at the tempo slider's speed (`wait`); Rehearse = it moves at the tempo slider's speed (`rehearsal`). Recording is its own mode, **Record a new idea** on Home: play over the metronome and get it back as sheet music (below) |
| ▶ Video | Play along with a recording: a YouTube video of the song plays above the sheet and the sheet's cursor follows it. See [Play along with a video](#play-along-with-a-video) |
| Tracks | Under **Playing**, one row per track of the file (its instruments: name, instrument, notes, range), the ones you play first. **Part**: what the track is for you: Right hand, Left hand, Both hands (split by register), Pedals (a bass line played with your feet), Vocals (sung: shown and heard, never graded), an instrument part (*An instrument part…*: name what you play it on, like flute), or **Backing**. **Show**: drawn on the sheet and the falling notes; a backing track you show gets its own staff, named for it, above yours, and falls faint (drums aren't drawn). Backing tracks start hidden. **Mute** and **Volume**: how a track you don't play sounds on the MIDI output under *Sound goes to*. **You play** (above the table) picks which of your parts you play this run (graded; Learn waits for it): both hands, one hand, with the pedals, or an instrument part. Every track you don't play is the backing and plays along unless muted: in time in Rehearse, and in Learn the stretch up to the next chord each time you play one (so it waits for you too). Listen has its own Mute and Volume. Everything is saved for the file the moment you change it (no Save button); a file whose parts were only suggested says so, with **OK** to keep them. During a run Mute and Volume are heard from the next note; Part, Show and You play wait for Stop. Only notes are sent — no sustain pedal or all-notes-off that would catch the notes you hold. A file whose parts were chosen before tracks had their own mix keeps its unused tracks hidden and muted. **Band songs**: set a track's Part to *An instrument part…*, or tell the Maestro *"the flute solo, Learn, loop, just the flute, the rest as backing"* (it finds the track by name, then by instrument, and asks if it can't tell). Then only that part is drawn, on its own staff and in the falling notes, and every other track sounds as its own instrument (*"drums down"*, *"mute the choir"* work on any track you don't play). Learn waits for each of your notes, and the band plays in time up to your next one, then goes quiet until you play it. With no bars set, the run takes the bars your part plays (the Maestro asks which if it plays in sections far apart). A **Lead-in** of backing bars (2 at first, 0-8, *"give me four bars before"*) brings you in when some backing sounds and the bars start after bar 1, on every loop pass or the first only. On a flute, sax or voice profile, naming a part clears the hand choices, and the part becomes one line: notes starting together keep the top one, and notes overlapping the next are cut where it starts |
| Bars | Practice a bar range. Each piece remembers how you last had it: its **Bars**, **Tempo**, **Loop** and Learn / Rehearse / Listen come back whenever you open it again, from Explore, Today, the Roadmap, a playlist or the Maestro (saved with the file in `part_choices.json`, so they survive a different browser too). A piece you haven't set up opens on the whole piece and keeps the tempo, loop and mode you had. Zoom, layout, labels and the rest of the Sheet menu stay the same for every piece. Bars the Roadmap marks on a song (*See in the song*) aren't kept |
| Labels | Under **Sheet**: note names and counting drawn on the sheet, at a level like a game's difficulty. **Easy**: on every bar, and when you press the same wrong key twice on one chord, the red flash also names the key to play. **Coached** (the default): only on the bars you slip on. Two wrong keys in a bar, or a long hunt for a chord in Learn, puts note names on it; two right keys played off the beat in Rehearse, or a bar whose timing comes out loose, puts counting under it. They appear mid-pass, and come off once you finish two passes without that slip in the bar; the Maestro says when it adds or removes them (unless After a pass is Nothing). **Hard**: none. **Note names** puts the letter on each notehead (filled or hollow like the note; a sharp or flat beside it, the key signature's included). **Counting** puts the beats between the hands' staves (under a single staff): 1 2 3 4, with & e a or trip let where notes start between beats, and a held or rested beat fainter. Coached labels belong to the piece you're on and reset when you open another. A mock exam shows none |
| Dynamics | Under **Sheet**: show or hide dynamics (pp to ff, hairpins) on the sheet. Off by default, remembered in the browser. A MIDI file played with changing dynamics gets them marked from how hard each passage was played (a new mark only where the level changes for two bars or more, so one accented bar isn't a new dynamic); a file at one velocity throughout gets none. MusicXML lessons show their own |
| Add chords & lyrics | Under **Sheet → This sheet → Analysis**: adds **chord names** over the right hand, **Roman numerals** under the left hand, **lyrics** under the tune and **section names** (Verse, Chorus…). See [Chords, lyrics and sections](#chords-lyrics-and-sections). The boxes under it show and hide each kind (remembered in the browser); **Look again** looks the song up afresh |
| Clean | Under **Sheet → This sheet → Two hands**, for MIDI files: makes the parts you play fit two hands and checks the sheet for anything hard to read. See [Parts no two hands can play](#parts-no-two-hands-can-play). **Show original** undoes it |
| Sheet | Under **Sheet → Layout**: **Scrolls sideways** (one long line moving past a fixed cursor, the default) or **Two rows, scrolls down** (the sheet as rows across the page: the row you're playing on top, the next one under it, and the sheet scrolls down a row as the cursor reaches it). Remembered in the browser. In two rows, drag or scroll up and down to look around |
| ⤢ Maximize | The button at the sheet's top-right corner: the sheet fills the window, with only the Start row left above it (the title bar, the search, the video and the colour key fold away). **⤡** or **Esc** restores it |
| Zoom | Under **Sheet → Zoom** (50–200%, remembered in the browser): how big the sheet is drawn on top of its fit to the strip. Smaller shows more bars along the line, or more rows in two-row layout; larger makes the strip taller where there's room, and past that crops the top and bottom of the line (or shows less of the next row) |
| Bar timeline / Loop / Bookmarks | **Playback** shows the whole piece on one slider. Drag it or use ◀ / ▶ to jump, ↺ to go back to the start of the selected bars; while Learn, Rehearse or Listen is running, the coach restarts at that bar (Learn waits at its first chord). When **Bars** are chosen they show as a band on the slider (in the accent colour with **Loop** on), and the slider stays inside them. With **Loop** on, the selected bars repeat; jumping within them doesn't change their endpoints. Each completed pass is saved and graded as its own take. The sheet flags where the bars start and end (*Loop start* / *Loop end* while repeating). **🔖** bookmarks the bar you're on (again to remove it): each bookmark is a tick on the slider and a chip under it that jumps there (✕ removes it). Bookmarks are per piece, remembered in the browser. **Double-click a bar on the sheet** to jump to it. A bookmark or double-click outside the selected bars clears them first when nothing is running; during a run it says the bar is outside them |
| Maestro decides | With **Loop** on, the Maestro changes the practice between passes the way a teacher would, says what it did, and the menu follows: the same problem bar in two passes → loop it with a bar either side (back to your section after three clean passes); a rough pass in Rehearse → 10% slower (not below 50%); two rough passes with both hands → right hand alone, then left, then both (two clean passes each); three clean passes in Learn → Rehearse at 70%; three clean in Rehearse → 5% faster (up to 100%). Say or type *"no"* / *"undo"* to put the last change back (handled on your PC, no API call) |
| Maestro: Friend / Strict | How the Maestro coaches, remembered between sessions (also by voice: *"be a bit gentler"*). **Friend** (default) is a cheerful practice buddy, more Duolingo than examiner: it celebrates effort and streaks, treats slips as part of learning, and says what went well before the one thing to try next; **Strict** is dry and demanding. Either way it names the exact bar and note |
| Start / ▶ Listen / Stop | One session at a time, shared with Claude. Stop freezes the sheet cursor at its current position |
| Metronome | In the control row, **♩ Metronome** starts it and the **BPM ▾** button opens its settings — BPM (type it, **Tap** it, or **Match score**), beats per bar, subdivision (quarters to sextuplets), six sounds, accent on beat 1, volume and a separate volume for the subdivisions. **M** starts/stops it. **Follow score**: Rehearse runs start with a count-in and the clicks follow the score — its tempo changes, time signatures and pickup bars, at your Tempo % — instead of waiting for your first note. Runs in the browser: no lag, no cost |
| Maestro | Ask by text or microphone in the dedicated Maestro panel. The Maestro also speaks coaching feedback in a dialogue box (click to skip, click again to close). While it speaks, **■ Stop** in its panel and in the dialogue box cuts it off mid-sentence (talking to it does too). When you press Start it greets you with what it knows: the piece, its key signature, your best score on it, how long you've been away. When a looped run ends it sums up passes, your best one, and your weak bar. After a pass it says at most two sentences, and only when there's something new: how it went or how it compares with the last pass, then the one thing to know. The first time a slip shows up it's named ("Bar 3: that's F sharp, not F"); the second time comes how to fix it ("Bar 3 again; take it on its own, slowly"); after that just a word ("Same spot."). Clean passes in a row stay quiet except at three and five. Wording never repeats the last half of its choices, even across sessions (`%USERPROFILE%\MidiCoach\maestro.json`). Claude's comments (`say`) are spoken too. Each of these can be switched off under **Maestro** (or by asking it, *"don't greet me"*, *"only talk when something changes"*): **Hello at Start**, **After a pass** (*Every pass* always says something, *When something's new* is the behaviour above, *Nothing* stays quiet and leaves just the pass line), and **Sum up at the end**. With **Maestro decides** on, it still says what it changed. These and the Friend / Strict style are kept per profile in `maestro.json`; the voice and volume are remembered in this browser. Browsers only let a page speak after you've clicked it once |

Learn-mode note scores use the live cursor's hits, unfinished notes, and wrong presses; they do not infer accuracy from performance timing because the cursor waits for each note.

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
ready to practice in Learn or Rehearse. It's a readable sketch, not an engraving: notes held
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

**Shortcut.** `.venv\Scripts\python -m midi_coach.shortcut` puts *Music Coach* (with the
coach logo) in the Start menu, so Windows search finds it, and on the Desktop. Both run
`Launch Music Coach.bat`, which goes through `midi_coach.launch`: if a coach is already
running and current it just opens the page; if that copy started before the code changed, a
practice copy is restarted, and for Claude Desktop's midi-coach it tells you to restart
Claude Desktop.

**Updates while it's open.** When the code changes (say, after a fix in Claude Code), a bar at
the top of the coach page tells you, once the files have stopped changing for 15 seconds:
*This page was updated* → **Reload**, or *The coach was updated* → **Restart coach**. Restart
is off while a run is going. It takes a few seconds: the coach comes back in the same window
with the same piece, and the page reloads by itself. A coach started by the shortcut or by
`python -m midi_coach.launch` can restart this way. For Claude Desktop's midi-coach the bar says
to quit Claude Desktop and open it again. The logo is drawn by `python -m midi_coach.icon` (`static/coach.ico`,
`coach.png`; it's also the page's tab icon).

## Today: one-button practice

The **Today** card at the top of Home plans a session from your goal's Path, the way a teacher
plans a lesson, so you don't have to pick from the map. It's sized to how long you said you
practice on most days (*Getting to know you*; 15 minutes if you didn't say). A new profile
with no goal yet sees **Find where I start ▸** here instead, which opens *Where to start*:

| Part | What it is |
|------|------------|
| Warm-up | A scale or pattern you already know, the one longest since you played it (~3 min) |
| Review | A skill you've passed before that has gone longest without practice, at least two days ago (~4 min) |
| New | The next stop on your Path, what **Next ▸** opens (~6 min); with time to spare, the stop after it too |
| For fun | The piece you played most recently in a Session, opened there (~5 min) |

Five minutes is just the new part; ten adds the warm-up; fifteen the review; twenty the piece
for fun (before the review if you're learning for songs you love). **Start** opens the first
part not done yet, and so does **Continue** after that. The plan is made once a day, so it stays put while you work
through it; **Plan again** makes it fresh from where your Path is now. A part ticks off once
you've tried every graded step of its lesson since the plan was made, passed or not (the Roadmap
keeps the levels); the piece for fun, once you've played it for 20 seconds. While you're in a
lesson the same list sits under its exercises, and when the part you're on is done,
**Next: …** takes you on. When everything is done, **Keep going** adds the next stop on the Path.

The bar shows minutes practiced today: your takes and lesson activity, with gaps of up to five
minutes between them counted as practice. The plan is kept in the profile's
`atlas/today.json`, and the Maestro knows it.

## The Roadmap

The **Roadmap** (from Home) is a map of everything a graded piano exam asks for, built on the ABRSM
Piano syllabus: Initial, then Grades 1 to 8, top to bottom. Each grade has five strands, left to
right: **Pieces**, **Scales & arpeggios**, **Sight-reading**, **Aural** and **Theory** (theory
practiced at the keyboard). A strand holds **families** (*Grade 3 · arpeggios*). A family holds
**requirements**, each one exam item (*B flat major, 2 octaves, hands separately*). A
requirement holds **stages**, the steps of learning it (right hand, left hand, hands together
slowly, then at speed). The last stage is the requirement itself. Each grade ends in a
**Review** (a mixed recheck of what you know, weakest first) and an **Exam** (the mock exam,
below). Nothing is ever locked.

| On the map | What it does |
|------------|--------------|
| Scroll / pinch | Zoom in and out. Each zoom level shows one level of the tree: grades, strands, families, requirements, then stages. Every node keeps its place, so zooming in reveals what was inside |
| Drag | Move around |
| Hover | Lights a node and its links and fades the rest |
| Click | Opens a node in the panel on the right (its level, stages and lesson) and zooms in to it |
| Search | *Search skills* at the top finds any node (*E flat major*, *echoes*) and zooms to it |
| ⤢ Whole map (Home) | Zoom back out to the whole Roadmap |
| ← Practice (Esc) | Back to the sheet |

The map is drawn like a graph of notes: every node is a dot in its strand's colour, with its
name underneath and no boxes. Busier families get bigger dots. Grades stack top to bottom and
each strand keeps its column, and within a grade a family always sits below everything it
builds on, so links run downward. At stage zoom a lesson's exercises hang below it on a stem.
Review is a gold hexagon and Exam a gold shield. The fill shows how far along a node is.
**Not started** is hollow. **Practiced** is half-filled: you've started on it. **Proficient**
is solid: every graded step has passed since the last slip. **Mastered** adds a gold ring: every
step passed again on a later day. Passing a later stage credits the earlier ones as Proficient.
A Mastered node is rechecked only when a Path needs it more than 30 days after its last pass,
and a failed recheck takes it back to Proficient. The grey count after a grade, strand or family
(*3/10*) is how many of its requirements are at Proficient or better. **★** marks its weakest part (the
lowest level, then the longest since practiced). Dashed outlines are a goal's own temporary nodes:
bridges and drills (below).

**Building it.** ABRSM keeps the copyright on its syllabus, so the Roadmap's facts aren't in git.
`syllabus.json` is drafted from your own copy of the syllabus into
`%USERPROFILE%\MidiCoach\atlas\content` (or `MIDI_COACH_ATLAS_CONTENT`), in the format of the
made-up `midi_coach/atlas/sample/syllabus.json`. The tree and its lessons are built there too:

```bat
.venv\Scripts\python -m midi_coach.atlas.build
```

That writes `atlas.json`, more than 2,000 nodes. Your progress is kept per profile in its
`atlas` folder: the event log, goals, temporary nodes and exam results. Claude's
`rebuild_progress` works it out again from your takes and the log.

### First steps and Ready to read

Above Initial, the Roadmap has two tiers of its own for complete beginners from about age 4. They
assume no music knowledge, not even where the black keys are. They're made of many small
skills, each one idea, linked to the ones they need:

- **First steps** (no reading yet): sitting and bubble hands, finger numbers, high and low, the
  black-key groups, finding every letter, middle C, the music alphabet, the C five-finger
  position in each hand, steps, skips, hands taking turns, a held note under a tune, hands
  together; rhythm read on one key (*ta*, *ta-a*, *ta-a-a-a*); listening games (high or low, loud
  or quiet, fast or slow, up or down, smooth or bouncy, same or different, happy or sad), tapping
  the beat, copying a rhythm, singing back two or three notes; and tunes learnt by ear (Hot Cross
  Buns and Mary on the black keys, then Hot Cross Buns, Mary, Au clair de la lune, Ode to Joy,
  Lightly Row, Jingle Bells and Twinkle, left hand and both hands too). Every score in this tier
  has finger numbers above the notes and letter names under them.
- **Ready to read:** the stave, the clefs and each note on them; reading pools that add one note
  at a time (C and D, then C D E, up to five fingers, then the left hand, rests, quavers, both
  staves); the G, D and middle C positions, mirror hands, staccato, f and p, the C and D minor
  chords, thumb under and finger over; more ear games; tunes in G position and hands together.
  Finger numbers stay; letter names go, since reading the notes is the point.

The lesson text speaks to the child, with an occasional *Grown-ups:* tip. Learn passes need 80%
of the notes and Rehearse passes 60 overall, gentler than the grades above. These tiers have no
mock exam. Initial's starting points need the end of Ready to read, so a beginner's Path to
Initial starts at *Sitting at the piano*. A skill you already know (Proficient) brings none of
its prerequisites onto a Path, so these tiers stay off it for anyone who knows Initial's skills,
and starting at Initial or above in **Where to start** credits them too. **Next** only offers a requirement
whose prerequisites on the Path are done.

**Young learner profiles.** Tick **Young learner** when you add a profile on the *Who is
practicing?* screen, or switch it with **Edit → ☺**. For that profile:

- the Maestro talks to the child: short sentences and everyday words, praise first, no
  percentages, and a game or a wiggle break after two hard tries. It still answers a grown-up
  normally. Its style is set to Friend, and the lessons it writes stay in one five-finger position
  with simple rhythms;
- the step panel reads each step aloud as it comes up (what to do on play, tap and sing steps;
  a quiz's question and its choices), says whether a quiz answer was right, and shows big
  print and big buttons. Every profile gets a 🔊 button on reading and quiz steps;
- a piano profile with no goal starts with the goal *Ready to read*, so **Next** opens *Sitting
  at the piano*.

They're the coach's own (public-domain tunes in `midi_coach/atlas/data/first_tunes.json`), so
they're in git and come with every build of the Roadmap. Rebuild the Roadmap and write their lessons
(every score linted and read back note for note) with:

```bat
.venv\Scripts\python -m midi_coach.atlas.first_steps
```

### Familiar tunes

Beside a grade's List A, B and C pieces, a **Familiar tunes** family holds songs everyone knows,
following no syllabus. Grade 1 has Hot Cross Buns (hands in octaves), Twinkle in G, London
Bridge, Old MacDonald, Row Your Boat, Frère Jacques, Yankee Doodle, Happy Birthday, Aura Lee,
Amazing Grace, We Wish You a Merry Christmas, Silent Night and the Drunken Sailor. The right hand
plays each public-domain melody note for note (an upbeat is written as rests at the start of
the first bar), over the coach's own simple left hand on the song's usual chords. They're learnt
in stages like any piece, with the same pass marks. They're on the grade's Path and in its review, but
a mock exam only asks for List A, B and C pieces. The tunes are in
`midi_coach/atlas/data/familiar_tunes.json` (add one there, with its grade as `tier`). The
`first_steps` command above also writes their lessons; to write only theirs:

```bat
.venv\Scripts\python -m midi_coach.atlas.familiar
```

### Mock exams

Each grade of the Roadmap ends in a mock exam, shaped like a graded piano exam and marked out
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

**Where to start** (a tab at the top of the Roadmap side panel, beside Planner) is *Getting to know
you*: a few questions, one at a time, with a progress bar. First about you (have you played,
can you read music, any piano exam passed, why you're learning, how long you can practice a
day), then light music checks: two notes to compare (higher or lower, played by the page),
notes on the treble and bass staves, beats in a minim, *p*, 3/4 time, the key of one sharp.
A check you miss just shows the answer, and *I'm not sure* is always fine. The answers pick a
starting tier: the grade after an exam you've passed, otherwise reading plus the checks (First
steps up to Grade 2). The tiers below are credited and the starting tier becomes a goal (the
active one if you have none). **Start today's practice ▸** on the last screen opens the first
part of Today. Answers are kept in `%USERPROFILE%\MidiCoach\atlas\welcome.json`, and the
Maestro hears why you're learning and how long you practice. A flute or saxophone profile is
asked about its instrument, reads a treble G instead of the bass-clef note, and checks the
microphone before the end; a singer reads middle C and sings a note for the check; a fiddler
reads the open A, a guitarist the open top E and a bassist the open A in the bass clef (see
[Flute: the flute Roadmap and the microphone](#flute-the-flute-roadmap-and-the-microphone),
[Alto saxophone and vocals](#alto-saxophone-and-vocals) and
[Fiddle, electric guitar and bass guitar](#fiddle-electric-guitar-and-bass-guitar)).

**Mock exams** (the link under Where to start, or Claude's `start_placement`) runs full mock exams from
the grade you pick. Each pass moves up a grade until one isn't passed; if the first isn't, it
steps down a grade at a time until one is. Then every grade up to the highest one passed is
credited (its stages count as Proficient), and the first grade not passed becomes your active
goal, with that exam's weakest items first on its Path. Right after each exam its card offers the next
one or **Later**; between exams a Session shows nothing about it; stopping an exam pauses placement, and Continue sits that grade afresh. Its
progress is kept in `%USERPROFILE%\MidiCoach\atlas\placement.json`.

**Goals and Paths.** Tell the Maestro a goal (*"I want to play Piano Man"*, *"sight-read
hymns"*, *"get through Grade 3"*) or type it in the Roadmap's **Planner** tab (with a song file
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

The **Route** panel, on the left of the map, inspects one route: the active goal's Path, or,
while you have a lesson off it selected, the route to that lesson (everything it needs that you
don't know yet, prerequisites first, marked *not saved*; *← goal* goes back). It lists the
route's families in order with their rings. Each family holds its lessons (requirements), and
each lesson opens and closes like a folder to show its exercises (stages); folders you close
stay closed. Click a family or lesson to show it on the map and open it on the right. The
route's dots are outlined on the map. The map shows a lesson among the rest of its family and
doesn't zoom inside it; scroll in yourself to see its exercises as circles. Clicking a lesson
on the map brings its route up here and opens its folder.
Lessons are started only from the Route panel: click an exercise (**▶ Start**). It opens the
lesson view, still under the Roadmap tab: the lesson's
exercises down the left (its stages, each with its progress dot; click one to switch), the
step panel with just the lesson's name, and the sheet. **← Roadmap**, the Roadmap tab or the
browser's Back goes up to the map; finished steps are already saved, and if a step is still
running it asks first, since a step stopped halfway isn't graded. Leaving the lesson view
puts back the sheet the Session had before. On a song goal, **See in the song** (under the
lesson's name, or ask the Maestro) shows the song itself in the lesson view, scrolled to this
lesson's bars and marked with Start/End: a section's own bars, a bridge's bars as the planner
placed it in the song, or the start when it didn't. Nothing played there is graded against the
lesson. **← Back to exercise** puts the lesson's music back; **Practise the whole song in the
Session** takes the song there (the marked bars stay chosen) and the Roadmap reselects this
lesson when you come back. A step's **Start** / **▶ Listen** turns into **■ Stop**
while it runs (Listen steps play like a Session's Listen, with the cursor following); a play
step says its pass mark in words (*play to the end and get 80% of the notes right*), and every
run ends with a line under the step, also when it wasn't graded and why. Everything
else is on the right. A selected lesson's details end with **★ Quick save**, which keeps the
route on the left as a goal straight away (no planning wait), or say *On your route* when the
lesson is already on the active one. The **Planner** tab holds the goal box and **Saved
routes**: click one to make it active, show it in the Route panel and outline it on the map;
the active one has **Next** (or *"what's next?"* to the Maestro), which opens the next
unfinished stage, *Why this Path* and **Archive**. Drag the strip between
either side panel and the map to resize it; « / », or a double-click on the strip, folds
it down to a thin rail, and a click on the rail brings it back. Several goals can be open, one active; **Archive** puts one away and its
bridges leave the Roadmap. Claude Desktop can do the same with `plan_goal`, or plan a goal
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

## Flute: the flute Roadmap and the microphone

**Getting started on the flute:**

1. On the *Who is practicing?* screen, add a profile and pick **Flute**, or on Home press
   **+ Learn flute** under the heading to add the flute to the profile you're on.
2. Plug in a headset or USB microphone and choose it under **Preferences → Microphone &
   speakers** (the JUNO-DS's audio input is not a microphone).
3. On Home, press **Find where I start ▸** on the Today card and answer the questions (about
   two minutes). At the end, play a long note: the page shows the note it hears, so you know
   the coach can hear the flute. Can't make a sound yet? Press **Skip for now**.
4. Press **Start today's practice ▸**. Someone brand new starts with *Making a sound*, then
   the notes B, A and G. After that, the **Today** card on Home plans each day's practice.

A profile can learn **piano**, **flute**, **alto sax** and **vocals**, one or more, like courses:
pick the first when you add a profile on the *Who is practicing?* screen. The buttons under
Home's heading show the instrument you're on (**🎹 Piano** / **🎶 Flute** / **🎷 Alto sax** /
**🎤 Vocals**); press another to switch, or **+ Learn …** to add one. Each instrument keeps its own Roadmap progress, goals and exams (the first in the
profile's `atlas` folder, one added later in `atlas-<instrument>`), while takes, lessons and the
Maestro's notes stay the person's. Switching to the flute changes four things:

- **Input.** *Playing → MIDI input* defaults to **Microphone (flute)**. While a run is going
  the page tracks the flute's pitch (YIN, in the browser) and sends each note to the coach as
  if a key had been pressed, so Learn, Rehearse and Record a new idea work as on the keyboard.
  A tongued repeat of the same note counts as a new note; a slur to another note too. A tuner
  under the status line shows the note it hears and how many cents sharp or flat (green
  within 15). Listening pauses while the Maestro speaks or you hold Talk. Use a headset or
  USB mic, not the JUNO-DS audio input; Listen mode still plays through the keyboard's output.
- **Examples** (a lesson's Listen step, a quiz's ▶, "Maestro, play it") come from the coach
  page on a soft flute tone, not the keyboard, and the microphone ignores them while they
  sound. An example stops when you go to another step, start a run, or the Maestro speaks
  (except when you asked the Maestro to play it). With no coach page open they play on the
  MIDI output.
- **The Maestro** teaches the flute (breath, tonguing, slurs, octaves; one line, no hands),
  and **write me…** requests come back as single-line flute exercises in the beginner range.
  Whisper is primed with flute words.
- **The Roadmap is the flute's own** (the same Roadmap tab, map and controls): *First
  notes* (the coach's own, since ABRSM has no woodwind Initial grade: making a sound, B A G, C and D, low E
  and F, F♯ and B♭, the upper octave; long tones, tonguing, two-note slurs; four first tunes;
  first theory), then **ABRSM Flute Grades 1 and 2**: the grade's scales and arpeggios (each
  learnt slowly, then tongued, then slurred, then at exam speed from memory, once each way),
  sight-reading in the grade's keys, times and range, the aural tests, theory, and three
  public-domain pieces per grade filed as Lists A, B and C (ABRSM's own flute pieces are
  copyrighted arrangements). Grade 2's new top notes have their own step. Mock exams work as
  on the piano Roadmap, from Grade 1.

The flute Roadmap is built locally, like the piano one: the ABRSM facts are drafted into
`%USERPROFILE%\MidiCoach\atlas\pan\syllabus.json` from the woodwind syllabus (copy in
`atlas\pan-source`), never into git. Rebuild after changing it:

```bat
.venv\Scripts\python -m midi_coach.atlas.pan
```

It writes `atlas\pan\atlas.json`, a lesson for every stage and the music (single-staff flute
parts, each checked against the engraving rules and read back note for note); the tunes are
in `midi_coach/atlas/data/pan_tunes.json`.

**Fingering.** For the flute and the alto sax, a fingering chart is a column of keys: the left
hand at the top in blue, the right hand under it in red, a key that's down filled (the sax's in
written pitch, as its music is printed). Each **Find the notes** lesson opens with the charts of
its new notes, then asks *Which note is this?* about each chart (practice only: the stage is still
passed by playing). **Sheet ▸ Fingering** puts a small chart under the notes of any score: *Where
it changes* (a run of the same note gets one) or *First time on each line* (each note once per
row; on the sideways line, once per four bars). It's off by default, since it makes the sheet
taller and spreads the notes out; it goes under a lesson's line or, in a band song, the parts
named for the instrument. **Monitor** (beside it, on by default) shows two charts in the corner
while you play: the note the music is waiting for, and the note the microphone hears, green when
they match and red when not. A note with no chart (the flute above E♭6, the sax above F6) gets
none. The Maestro can set both.

**Audio to MIDI** (Preferences, Ctrl+,) tunes how the microphone turns the flute into notes.
While the pane is open the microphone listens: a graph shows the last four seconds (level, the
noise gate, the pitch heard, the note being held), a line under it the live level, pitch,
cents and pitch clarity, and a list every note-on and note-off it produces (velocity, how late
it was heard, how long it was held). They're marked *test*, and only reach the coach (*→ coach*)
while a run is listening. The settings, saved in the browser and used from then on:

| Setting | Default | What it changes |
|---|---|---|
| Buffer size | 1024 samples | The window each pitch is read from: longer hears low notes more steadily, shorter reacts sooner |
| Look again | every half buffer | How often a new window is read (more often = quicker notes, more CPU) |
| Noise gate | −38 dB | Sounds quieter than this are ignored. **Measure room noise** listens for 2 s and sets it just above the room |
| Pitch clarity needed | 88% | Higher ignores breathy or noisy sound; lower catches soft notes |
| A note starts once its pitch holds for | 30 ms | Longer skips the scoop at the start of a note; shorter is quicker |
| A note ends after this much silence | 45 ms | Longer bridges a gap in the tone; shorter separates fast tonguing |
| Extra input latency | 0 ms | A USB audio interface or Bluetooth headset's delay, taken off each note's time so it's graded on time |

Below the list the pane says what the window can hear (sample rate, lowest pitch) and the
latency Windows reports. **Reset to defaults** puts them all back.

**Hands-free.** Tick **Hands-free** beside the Talk button and the microphone stays open: say
*"Maestro, start Learn mode at sixty percent"*, *"Maestro, write me a G major long-tone
exercise"* or just *"Maestro"* (it answers *Yes?* and takes the next thing you say). Speech is
transcribed on your PC; only what follows "Maestro" goes to Claude, and sounds that are mostly
a steady flute pitch are ignored.

## Alto saxophone and vocals

The alto saxophone and the voice work like the flute: the microphone is the input, examples
come from the coach page, the Maestro teaches that instrument (a sax teacher's words: reed,
embouchure, octave key, tonguing with "tah"; a singing teacher's: breath, support, legato,
sol-fa, and rest when the voice is tired), **write me…** gives one-line exercises, and the
welcome checks the microphone hears you. Each has its own Roadmap.

**Alto sax** music is in **written pitch**, as sax books print it: the alto sounds a major sixth
lower, so the page moves every note it hears up 9 semitones (the tuner, the notes it sends and
the welcome's check all name written notes) and plays its examples 9 lower, at the pitch an alto
really sounds. The scores say they are for an E♭ instrument, so other music programs play them
at concert pitch too. The Roadmap: *First notes* (the coach's own: making a sound on the
mouthpiece, B A G, C and D, low D E F, F♯ and B♭, the octave key; long tones, tonguing, slurs;
first tunes), then **ABRSM Saxophone Grades 1 and 2** (scales and arpeggios tongued and
slurred, sight-reading, aural tests, theory including written and sounding pitch, and
public-domain pieces). Its syllabus is drafted locally into
`%USERPROFILE%\MidiCoach\atlas\sax\syllabus.json` from the Saxophone pages of the woodwind
syllabus, never into git. Build it with:

```bat
.venv\Scripts\python -m midi_coach.atlas.sax
```

**Vocals** is the coach's own course (no exam board's): *First notes* (finding your voice, then
matching pitches a few at a time from do re mi up to the top E, long notes, legato, leaps, first
songs), then Grades 1 and 2 (scales and arpeggios learnt on "la", then in sol-fa, then legato,
then at tempo from memory; sight-singing; theory; public-domain songs in
`midi_coach/atlas/data/voice_songs.json`). Its aural tests come from the flute's local syllabus
when there is one. A singer has a **high voice** (soprano, alto: the treble clef) or a **low
voice** (tenor, baritone, bass: the same Roadmap an octave down, in the treble clef with an 8
below). Pick it when you add the profile, or press **High voice** / **Low voice** beside the
instrument buttons on Home; progress is shared between the two. Build both with:

```bat
.venv\Scripts\python -m midi_coach.atlas.voice
```

The microphone listens over each instrument's range (a low voice's from about 70 Hz) and is a
little more forgiving of a voice's slides and vibrato; **Audio to MIDI** in Preferences still
tunes it.

## Fiddle, electric guitar and bass guitar

These three work like the flute too (the microphone, examples from the page, a Maestro who
teaches that instrument, **write me…**, the welcome's microphone check), and each is the coach's
own course (no exam board's): *First notes* in first position, then Grades 1 and 2 with scales
and arpeggios, sight-reading, aural tests (from the flute's local syllabus when there is one),
theory and public-domain tunes. The syllabi and tunes are in `midi_coach/atlas/data`
(`fiddle_*`, `guitar_*`, `bass_*`).

**Fiddle** reads the treble clef at the pitch it sounds. *First notes*: holding the fiddle and
bow, the open strings, the fingers on the A, D, E and G strings, the low second finger; whole
bows, string crossing, two notes to a bow. Scales are learnt with separate bows, then slurred,
then at tempo from memory; the keys start with D, G and A major.

**Electric guitar** and **bass guitar** music is written an octave above how it sounds, as
guitar and bass books print it: the sheet shows an 8 under the treble (guitar) or bass clef
(bass), and the coach hears and grades the pitch that sounds, so nothing needs moving. The
microphone hears one note at a time, so everything graded is single notes (melodies, riffs,
scales, arpeggios); chords, strumming and power chords are taught in the guitar's *Theory &
chords* strand, not graded: pick a chord's strings one at a time to hear each note. Plug in and
keep the amp low; a bass's low E (41 Hz) needs an amp, and the page analyses longer windows for
these two (2048 samples for the guitar, 4096 for the bass) whatever **Audio to MIDI** is set to.

**Tab.** For the guitar and the bass, **Sheet ▸ Tab** (on by default) adds a tab staff under the
notes: a line per string, the number the fret to press, 0 the open string. It is worked out on
the page from the notes, lowest fret first (so first position), for a lesson's line or, in a
band song, the parts named for the instrument; it shows and hides with that part, and is never
marked or graded. The Maestro can turn it on or off too.

Build the three Roadmaps with:

```bat
.venv\Scripts\python -m midi_coach.atlas.fiddle
.venv\Scripts\python -m midi_coach.atlas.guitar
.venv\Scripts\python -m midi_coach.atlas.bass
```

## Talk to the Maestro (voice chat, optional)

The **Maestro panel** floats over every part of the coach page. Drag it by its top bar; the
arrow opens it on today's conversation or folds it to the bar. Open, it keeps everything said
today — what you asked, each answer, and what the Maestro, Claude or the Examiner said unasked
(marked *unasked*) — and a reload shows the same day (`~/MidiCoach/maestro_log/<date>.jsonl`).
Folded, a new line shows in the dialogue box as before and lights a dot on the bar. 🔊 beside
a line says it again (even with the voice off); **Clear** empties the panel for the rest of
the day without touching the log; a dashed line marks where the Maestro started a fresh
conversation and forgot what's above it. Resize it from its top-right corner. **Ask
Maestro** (top bar, Home, Actions) opens it where you are, without leaving what you're doing.

Under the bar, folded or open, are **quick-action tiles** for the part of the app you're on.
Session: Play/Stop, Start, Loop, Metronome, Tempo − / +, Record. Roadmap: Today, Next stop,
Planner, Mock exam. Home: Today, Continue. Record and YouTube: Play/Stop, Metronome. A tile that
can't act right now is greyed, and its hover says why (*Open a piece first*). **✎** edits this
part's set: × takes a tile off, the tray below adds one, drag to reorder, **Done** to finish. Any
tile can go on any part; one that belongs elsewhere has a dashed edge and goes there first
(asking first if that would stop a run). Or ask: *"Put the metronome on my Roadmap tiles."* Each
profile keeps its own sets (`tiles.json` in the profile's folder).

Tap **🎤 Talk** on the panel, speak, tap again (or hold it, or hold **Space**, and let go
when you're done), or open the panel and type. A level meter shows whether the microphone
hears you; pick the microphone in the menu next to it. The JUNO-DS's USB audio input is
not a microphone, so plug in a headset or USB mic. The Maestro
answers out loud in character and can run the practice for you:

- *"Hello. How did that go?"* / *"What's my best on this?"*
- *"Loop bars five to eight in Rehearse at seventy percent."* / *"Left hand only."* / *"Stop."*
- *"Play bars one to four for me."* (through the keyboard)
- *"Write me a G major arpeggio exercise."* / *"Switch to the C major scale."*
- *"Be a bit gentler."* / *"Be strict with me today."* (the Friend / Strict setting)
- *"Show the falling notes."* / *"Note names on."* / *"Zoom in."* / *"Metronome on at sixty."* /
  *"Open the Roadmap."* / *"Set bars nine to twelve and loop them."* (the page's own controls,
  set as if you'd clicked them, without starting a run)
- With a flute in your hands, tick **Hands-free** and start with *"Maestro, …"* instead (see
  [Flute: the flute Roadmap and the microphone](#flute-the-flute-roadmap-and-the-microphone)).

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

**Bug reports.** When something in the app goes wrong, say *"Bug: the cursor jumped to bar
five"* (or *"that's a bug, …"*, *"report a bug"*) and keep playing. Starting with "bug" is
handled on your PC with no API call; describing a problem in other words (*"the play button
does nothing"*) also works, through the Maestro. Each report is saved to
`~/MidiCoach/bug_reports/open/<date_time>/`: what you said, the practice on screen, the coach's
recent log, a screenshot of the window in front, and up to five from the 15 seconds before
(the problem has usually just happened by the time you report it). *"Another screenshot"*
adds one more to the latest report, with anything you say after it. The screenshots are of
whatever window is in front and stay on your PC; the last few seconds are kept in memory only
while a coach page is open, and only written when you report a bug. Later, in Claude Code, say
*"fix the bug reports"*; each fixed one waits in `bug_reports/check/` until you try it.

**Typing instead (F9).** On the coach page, **F9** opens a small box: pick 🐞 Bug or 💡 Idea,
type what's wrong, press Enter. The box closes before the screenshot is taken, and the report
is saved exactly like a spoken one (screenshots from the seconds before, the practice on
screen, the page's errors). F9 again or Escape closes it without saving.

**Trying the fixes.** When something you reported has been fixed, a **👀 N fixes to try** button
appears at the top of the coach page. It lists each fix with your screenshot, what you said and
where you were (page, song, bar, mode), and a line on what changed. Try it, then press
**✅ Works** (it moves to `fixed/`, or `requests/done/`) or **↩️ Still wrong** and say what's
still off (it goes back to `open/` with your words, to be fixed again). Each fix is its own git
commit on this PC (never pushed by the coach). A fix made by a background worker waits on its own
side branch, so it has a **🧪 Try it** button: that adds it to your code so you can see it (press
Restart or Reload when the bar at the top asks), then Works keeps it and Still wrong takes it out
again. Pressing Works without trying adds it too, and Still wrong without trying just drops it.
Neither Try it nor Works adds a fix while you have unsaved changes in a file it changes: it says
which, and you press it again once they're committed or undone. A fix made in your folder (or
tried) is undone by Still wrong, which says so if it can't be undone cleanly. **↗ Go there** opens
the piece you reported it on and sets the page up as it was: the view, the mode, the bars, the
tempo, the loop and the cursor's bar (this becomes that piece's saved practice settings, as if
you'd set them). It's off while a run is going. Opening
`http://127.0.0.1:8765/#checks` opens the list straight away.

**The backlog in Obsidian.** If your Obsidian vault has a `Projects/MidiCoach` folder (the vault
is `~/Vault` unless `MIDI_COACH_VAULT` says otherwise), every report, fix and check rewrites
`Projects/MidiCoach/Backlog.md`: what's ready to try, what's open, and what was done in the last
two weeks, each with its screenshot (copied to the vault's `attachments/backlog/`). It's written
by the coach, so edit the reports, not the note.

**Requests for the app.** Want something changed or added? Say *"Idea: a bigger metronome
button"* (or *"feature: …"*, *"feature request …"*, *"wish list: …"*, *"suggestion: …"*).
It's saved like a bug report, with screenshots, to `~/MidiCoach/requests/open/<date_time>/`, free
and with no API call; asking in other words (*"could the sheet have finger numbers?"*) also works,
through the Maestro. *"Another screenshot"* adds to whichever report or request you made last.
In Claude Code, say *"do the requests"*; built ones wait in `requests/check/` for you to try, like fixes.

**The backlog runner.** `python -m midi_coach.runner` works the backlog by itself: whenever there's
something queued, it starts up to two Claude Code workers (on your claude.ai account), any time of
day. One triages new reports first; then each takes a batch (one area of the app), never two that
change the same file. Each works in its own copy of the code in `~/MidiCoach/workers/`, so your
folder isn't touched, and may only read, edit its own copy, run the project's Python and use
read-only git: no pushing, no other programs. Its fixes appear under 👀 like any other. One it
can't finish is set aside as 🧱 Stuck in the backlog (`python -m midi_coach.bugs unstick <id>` puts
it back). When your usage runs out it gives the work back and tries again 30 minutes later.
`--install` starts it at every Windows login (`--uninstall` stops that), `--once` fills the free
slots once and waits for those workers. What it did: `~/MidiCoach/runner/<date>.log`.

**Questions for you (❓).** When building a report would mean guessing what you meant, it isn't
built: it waits under ❓ Needs you with one question and two to four answers. Triage asks these,
and so does a worker that finds two fair ways to read a report halfway through. The 👀 button then
also says *"1 question"*. Its box lists the questions above the fixes: press an answer, or write
your own and press **Use this**. Or ask the Maestro *"any questions?"*. It reads the first one out,
with its answers numbered. Say *"answer two"* (or *"the first one"*, *"option 3"*), *"my answer
is …"* in your own words, or *"skip"*, and it goes on to the next. That's free, with no API call.
An answered item goes back in the queue, in its area's batch, and the worker building it reads
your answer. From a terminal: `python -m midi_coach.bugs answer <id> 2` (or your own words).

**Conversation log.** Everything you say or type to the Maestro, and its answer, is added to
`~/MidiCoach/maestro_log/<date>.md`, so a wish said in passing isn't lost. It stays on your PC.

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
practice; the source note says how far to trust the notes.

### Song lessons

*"Make a song lesson from Let It Be"* — `make_song_lesson` writes a band file as its vocal line
over the piano part you play (`python -m midi_coach.songs "Let It Be" …` does the same from a
terminal). The tune is the part named vocal / melody / lead, else a voice or lead instrument; the
result says which (a sound effect or the highest strings is a guess — pass `melody_part`). A
karaoke MIDI file's lyrics go under the tune. Time signature changes are kept, and the key
signature changes where the song modulates (below). Every note read back is checked against the
source, and the lesson goes to *Needs review* with its source note.

### Playlists: an album's keyboard parts, in order

*"Make a playlist of every keyboard part on Dark Side of the Moon"*: `make_playlist` takes song
titles in order (`python -m midi_coach.playlist "Dark Side of the Moon" --artist "Pink Floyd"
Breathe "On the Run" Time …` does the same from a terminal). It looks for each song in the
reference library. When there's more than one version, it uses the one with the most keyboard
notes, or the file you name with `"Title=path"`. Every keyboard part of every song then gets its
own entry: piano, electric piano, organ and synths, from the track names first and then the
instruments. It leaves out drums, voices, bass and parts that only double another.

- **One part per entry:** an entry is an unchanged copy of the song's file with that part chosen
  for your hands, so the rest of the band plays along.
- **Hands:** a line that stays above middle C goes to the right hand and one below it to the
  left; a part with chords across the keyboard is split between the hands.
- **Order:** the files are numbered `01 Breathe – Elec Piano.mid`, `02 Breathe – Organ.mid` and
  so on in the category's folder. The folder's `playlist.json` lists them in order.
- **On the page:** the Songs panel lists a playlist in that order and marks it *playlist*. Beside
  the title, **◀ 3 of 19 ▶** steps to the previous or next piece. Nothing moves on by itself, and
  the arrows wait while a run is going.
- **Missing songs:** a song with no file, or no keyboard part in its file, is listed as missing.

Pass `replace` (`--replace`) to rebuild a playlist. `organize_lesson` moving an entry out of the
folder takes it off the list; renaming it keeps its place.

To fill gaps in the library, `tools/fetch_songs.py "<Artist>" "<Title>" …` downloads named songs
from bitmidi.com the same polite way `tools/fetch_alternates.py` does. Some files hold a whole
album side as one medley. `tools/split_midi.py <file>` lists its markers by bar, and
`tools/split_midi.py <file> "Breathe@19" "On the Run@63" …` cuts it into one file per song. Every
note keeps its pitch, length and place in the bar, and each file starts with the tempo, key and
instruments in force at its cut.

### Readable sheet music: rules, checked and looked at

Every sheet the coach writes (piano sheets, transcriptions, song lessons) is held to the rules in
`midi_coach/engraving.py`, checked on what the reader sees — each one a mistake found once that
must not come back: no missing or needless accidentals (none on every E flat in E flat major; a
natural on A3 after A2 natural), no nested or odd tuplets (one grid per beat, sixteenths or
triplet eighths), nothing shorter than a sixteenth, no double dots, no short gaps inside the
sung line, no hyphen leading to a new word, at most two voices a staff, no needless ties,
ledger lines kept in check with clef changes or an 8va/8vb over a passage (15ma/15mb for a long note
one octave doesn't bring back; never a needless or crowded mark, and a note held over a barline
counts once), key changes no closer than six bars, and the title printed once. And no note of
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

**Files with no steady beat.** Some MIDI files were played in without a click, so their
notes don't line up with the file's bar lines. When the coach can't recover the beat by
itself, the sheet is still drawn on the file's own grid, with a yellow warning above it
that the bar lines and rhythms are rough. Press **Auto clean** (under **Sheet → This sheet**;
the warning has a button that opens it) to have the coach
follow the playing, find a beat and redraw the sheet. It tries starting tempos from 50 to
200 BPM; when a few different beats fit about equally well, it writes the sheet for each and
keeps the one that reads best (fewest engraving problems, then the plainest rhythms). The
first time on a long file this can take up to a minute; after that it's remembered. It changes the notation only: the notes still play
and are graded at their real times. **Show original** turns it off again. The choice is
saved per file, alongside the part choice.

### Parts no two hands can play

A band arrangement often asks the hands for more than they can do: an organ doubles the bass
line an octave up while it plays the riff, so the right hand would need B2 and D5 at once
(Ghostbusters' chorus); two parts play the same key at the same moment; a file has a note
written twice. The sheet of such a part is hard to read too, full of clef changes and 8va / 8vb
marks. When the coach finds this in the parts you play, a yellow warning above the sheet says
in which bars. Press **Clean** (under **Sheet → This sheet**; the warning has a button that
opens it), or **✕** to ignore the warning for that sheet (remembered in this browser; Clean
stays under *This sheet*). Chord by chord, it:

1. plays a key sounded twice at once only once, in the hand it sits best in;
2. hands notes one hand can't reach (more than a ninth from its top note in the right hand,
   its bottom note in the left) to the other hand, when that hand can take them;
3. leaves out what still doesn't fit in a tenth: first notes that double another note of the
   chord an octave away, then the ones furthest from the tune on top or the bass underneath;
4. leaves out octave doublings in a hand with more than five notes at once.

Then it redraws the sheet, checks it against the coach's readability rules and says what it
changed and what, if anything, is still hard to read. The sheet, the falling notes, Learn and
Rehearse and the grading all use the cleaned parts; the file itself isn't touched, and the
sheet notes what was changed. **Show original** turns it off. The choice is saved per file,
alongside the part choice. A part both hands can already play is left as it is.

### Chords, lyrics and sections

**Add chords & lyrics** (under **Sheet → This sheet**) writes extra information onto the song that is
open. It never changes a note, and it doesn't change the lesson file: only the drawn sheet.
It isn't offered on the Roadmap's own music (scales, arpeggios, exercises, exam pieces,
sight-reading), which has no chart or lyrics to look up.

1. **Straight away, from the file.** The coach works out each bar's chord from the notes (one
   a bar, two when the harmony clearly changes halfway, and named the way a lead sheet names
   them: *Eb*, not *Cm7/Eb*). The Roman numerals come from those chords and the key signature,
   with inversions (*V⁶*, *I⁶₄*, *ii⁴₂*) and secondary dominants (*V⁷/IV*). A karaoke MIDI
   file's own lyrics go under the vocal line.
2. **Then the song is looked up, on your Claude subscription.** This takes a few minutes
   and uses no API credits. The coach fetches the best-rated chord chart (Ultimate Guitar)
   and the lyrics (LRCLIB, an open lyrics database). Claude Code then lays them onto this
   file's bars and tune, checks Hooktheory TheoryTab for the sections, and the sheet is
   redrawn when it's done (after the current run, if you're playing). What comes back is
   checked against the file. A published chord the notes contradict is left out and the
   file's own chord is kept: hover over the note beside the button to see where that
   happened, and the sources. A word is kept only if it's in the fetched lyrics.

Lyrics go on the vocal staff when the file has one, otherwise on the right hand's top notes.
A lesson that already has lyrics or chord symbols keeps its own. If Claude Code isn't
installed, or your subscription's usage limit is reached, the sheet keeps what the file shows
and the button offers **Try again**. Results are saved per file in
`%USERPROFILE%\MidiCoach\derived\details\` (safe to delete).

### Play along with a video

**▶ Video** (next to the Session's modes) opens a YouTube player above the sheet. Paste the
song's link and press **Use**, or press **Find on YouTube** and pick one. While the video
plays, the sheet's cursor follows it, and so does the web visualizer's strip if it's
connected. Pause or skip around in the video and the cursor goes with it. **Speed** slows the
video down, and the cursor slows with it. Each speed shows the recording's tempo at that speed.

The page can't hear the video, so you line it up once:

1. Press **Tap to sync**. The video starts.
2. On the first beat of bar 1, press **T** (or the button). Then tap the first beat of every
   bar after it. Four to eight bars is enough. A missed bar or an accidental double tap is
   worked out and skipped.
3. Press **Done**, or just stop tapping for a few seconds. The taps are saved.

Then the note says which bars you tapped and the recording's tempo. If the recording speeds
up or slows down later and the cursor drifts, press **T** on the first beat of any bar while
it plays. That bar line is moved to that moment. To tap a later stretch again, set **from
bar** first. **Forget taps** starts over. Choosing a different video also forgets the taps,
because they belong to the old video.

**Loop bars** repeats a stretch: tick it and set the first and last bar. When the video
reaches the end of the last bar it jumps back to a second before the first, so you get a
run-up. If the video is before the loop when you press play, it jumps ahead to it.

The sync and the loop are saved per song and video in `%USERPROFILE%\MidiCoach\synced.json`,
shared by all profiles. They're only used while the panel is open and no practice run is
going: Learn, Rehearse and Listen still drive the cursor themselves. Chord names and lyrics
come from **Add chords & lyrics** as usual, so they move along with the video too.

#### Videos that only play on YouTube

Some videos refuse to play anywhere but youtube.com; the panel says so. For those, install
the **Piano Coach for YouTube** extension (Chrome or Edge, once):

1. Open `chrome://extensions` (Edge: `edge://extensions`) and turn on **Developer mode**.
2. Press **Load unpacked** and choose the folder `midi_coach\youtube_extension` in this repo.

The coach page's **YouTube** mode walks through these steps (with the folder's
path to copy and **Show in Explorer**), and its light shows whether the extension is talking to
the coach: green while a YouTube tab is open, *Installed* when it has been seen before, and
*Reload the extension* when the copy in the browser is older than the one in the repo. It also
lists every song synced to a video: **Play along ↗** opens that song in the coach and its video
on YouTube; **Play here** opens it in a Session with the video above the sheet.

Then press **Open on YouTube** in the panel (or open the song's video yourself). A small
*Piano Coach* box appears in the top-right corner of the video's page, showing the song open in the coach.
On a video the song isn't synced to yet, press **Use this video for this song**. After that
the box works like the panel: the sheet follows the video, **Tap to sync**, **T** to tap or
to fix drift, and **Loop bars**. It uses the same taps and loop as the panel, so a video
synced in one is synced in the other. The **–** button shrinks the box.

Good to know:
- On a song's video, **T** taps for the coach instead of switching YouTube's theater mode.
- While an ad plays, the cursor waits; it carries on when the song comes back.
- The box finds the coach by itself (ports 8765–8774). If the coach isn't running it says so,
  and connects when you start it.
- After you change the extension's files, press its reload button on the extensions page and
  reload the YouTube tab (the YouTube tab in the coach says when that's needed).

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

3. **Reference files** are found in the visualizer's `config.json` → `search_folders`
   (set them on the coach page with **File → Song folders…**), plus any folders in `MIDI_COACH_REFERENCE_DIRS` (separate with `;`), plus
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
| `set_parts` | Save what each part is — `right` / `left` / `both` hands, `pedals` (feet), `vocals` (shown, never graded), and `named` parts (`{"flute": [4]}`: played on their own, `hand="flute"`, over the rest of the file as backing) — remembered per file |
| `start_recording` | Record from the input; optional reference / hand (`both` / `right` / `left`, `+pedals` to add the feet, or `pedals`) / bars; `mode` = free / wait / rehearsal; in wait / rehearsal every track you don't play sounds on the MIDI output as the Playing menu mixes it (mute / volume per track) |
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
| `pianist_notes` / `remember` | Read the Maestro's notebook on you (goals, pieces, weak spots, how you like to be taught) / add one lasting fact to it |
| `maestro_inbox` | Questions you asked the Maestro at the keyboard that couldn't be answered then (Claude Code missing, signed out, usage limit), each with what you were practicing; empties the inbox once read |
| `say` | Speak a short comment aloud on the coach page (browser voice; mute with the page's Voice switch) |
| `transcribe_take` | Write a take out as sheet music (a two-staff lesson): Record-mode takes use their metronome grid, others get an estimated tempo or the `bpm` you give |
| `create_lesson` | Write a lesson (tinyNotation / MusicXML / excerpt) and show it on the coach page (`to_visualizer` also pushes it into Learn Mode) |
| `send_lesson` | Show an existing lesson or reference on the coach page (`to_visualizer`: Learn Mode too) |
| `organize_lesson` | Move a lesson or reference into a category of the page's Songs / Lessons panel (optionally renaming it); takes and part choices follow |
| `start_exam` | Start (or resume) a mock exam for a grade (`initial`, `g1`..`g8`) on the coach page; see [Mock exams](#mock-exams) |
| `exam_report` | Marks and written report of a finished mock exam (the latest, or of a grade or id), and the exam in progress |
| `atlas_overview` | Each grade's progress on the Roadmap, mock exam bests, the active goal and its next stop |
| `atlas_node` / `open_node` | One Roadmap node with its state, stages and lesson / open a stage's lesson on the page |
| `list_goals` | The goals, the active one's Path (families in order, requirements and stages), the planner's status, reasons and sources |
| `plan_goal` | Plan a goal (a song, skill or grade) with Claude Code on the subscription, in the background; a song is researched first |
| `save_goal` | Save a goal you planned yourself (targets, up to 5 bridges, order, reasons); checked like the planner's |
| `piece_grade` | Estimate a piece's (or passage's) grade from its measured features |
| `rebuild_progress` | Recompute the Roadmap progress from the takes and the event log |
| `start_placement` | Find your level with mock exams from a grade (up until one fails, or down until one passes); credits the grades passed and sets the first grade failed as the goal. `resume=True` continues one under way |
| `make_song_lesson` | A band file as its vocal line (with karaoke lyrics) over your piano part, key and time signature changes included; saved in *Needs review* with a note on where it came from |
| `make_playlist` | Every keyboard part of the songs given, in order, as a category the page steps through with ◀ ▶: one entry per part (a copy of the song with that part chosen), the band playing the rest; songs not found are listed as missing |
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
| `MIDI_COACH_CONFIG` | `<repo>/config.json` | Where `search_folders`, `online_search` (the bitmidi.com search; on unless `false`) and `watch_downloads` (pick up new songs from Downloads; on unless `false`) are kept |
| `MIDI_COACH_DOWNLOADS` | `~/Downloads` | The Downloads folder the Maestro's open_song and the new-song watcher look in |
| `MIDI_COACH_VAULT` | `~/Vault` | Obsidian vault for `Projects/MidiCoach/Backlog.md` (used only if that folder exists); `off` for none |
| `MIDI_COACH_SONG_WATCH` | on | `off` stops the coach watching the song folders and Downloads for new songs |
| `MIDI_COACH_DISPLAY_PORT` | `8765` | Live score server port (next free port if taken) |
| `MIDI_COACH_NO_BROWSER` | — | Set to stop Claude opening the browser automatically |
| `ANTHROPIC_API_KEY` | `~/MidiCoach/anthropic_api_key.txt` | API key for talking to the Maestro |
| `MIDI_COACH_DAILY_CAP` | `0.50` | Daily voice-chat spending limit in dollars |
| `MIDI_COACH_CLAUDE` | `claude` on PATH, else `~/.local/bin/claude.exe` | Claude Code, for the Maestro's deep questions |
| `MIDI_COACH_DEEP_MODEL` | `sonnet` | Model Claude Code uses for deep questions |
| `MIDI_COACH_GENERATOR_MODEL` | `sonnet` | Model Claude Code uses to write the Roadmap's lessons (`python -m midi_coach.atlas.generate`) |
| `MIDI_COACH_ATLAS_CONTENT` | `<home>/atlas/content` | Where the Roadmap's syllabus, built tree and lessons live (kept out of git: the syllabus is the exam board's copyright) |
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
