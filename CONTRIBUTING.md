# Contributing

Thanks for taking a look. This project started as a personal tool for live piano
performances and is now open for collaboration — PRs, bug reports, presets, and
shader submissions are all welcome.

**No build step, no toolchain, no framework.** If you have Chrome and a text
editor, you can already contribute.

---

## Quick start (60 seconds)

```bash
git clone https://github.com/nickprocenko/Piano-MIDI-visualizer.git
cd Piano-MIDI-visualizer
```

Open `docs/index.html` directly in **Chrome or Edge**. That's it — edit the file,
hit refresh, see the change.

> **Why Chromium only?** The app depends on the [Web MIDI API](https://developer.mozilla.org/en-US/docs/Web/API/Web_MIDI_API),
> which Firefox and Safari do not implement. Nothing else in the stack is
> Chromium-specific.

**No MIDI keyboard?** You don't need one to work on most of the project. Use
**Learn Mode** with any `.mid` file to drive the visualizer, or click the on-screen
piano keys with the mouse. Only hardware-input work genuinely requires a device.

Some browsers restrict `localStorage` and file access on `file://` URLs. If you
hit that, serve the folder instead:

```bash
python -m http.server 8000 --directory docs
# then open http://localhost:8000
```

---

## Repository layout

The repo holds **four separate programs** that share a protocol and a look. Most
contributions only touch one of them.

| Path | What it is | Language | Needs |
|------|-----------|----------|-------|
| `docs/index.html` | **The main web app.** Single self-contained file — the primary target for contributions. | HTML/CSS/JS | Chrome |
| `docs/notation.html` | Sheet-music strip, rendered by OpenSheetMusicDisplay in an iframe | HTML/JS | Chrome |
| `docs/overlay.html` | OBS browser-source overlay for audience polls | HTML/JS | Chrome |
| `main.py`, `src/` | Standalone desktop version (pygame). Predates the web app, still maintained, Windows-oriented. | Python 3.10+ | `pip install -r requirements.txt` |
| `server/` | Audience vote server — Kik chat bot, WebSocket out to the visualizer | Node.js | `npm install` |
| `firmware/esp32_fastled_bridge/` | ESP32-S3 sketch driving a WS2812 strip | Arduino C++ | Arduino IDE, FastLED, NimBLE-Arduino |
| `examples/` | Importable preset JSON + AI prompt templates | JSON/Markdown | — |
| `tools/` | Dev scratch utilities (BLE scanner, fluid prototype, renderer stress test) | Python | — |

The web app (`docs/`) and the Python app (`src/`) are **independent
implementations**, not a shared core. A fix in one does not automatically apply to
the other. If you fix a behaviour bug that exists in both, fixing just one is
completely fine — say so in the PR and we'll track the other separately.

`docs/` is what GitHub Pages deploys, via `.github/workflows/deploy-pages.yml` on
every push to `main` that touches `docs/**`.

---

## Working in `docs/index.html`

It's one ~5,700-line file. That is a deliberate trade-off — zero build tooling and
a single file you can email to someone — but it does mean you need to know how to
navigate it.

**Every major subsystem has a banner comment.** Search for these to jump around:

```
// ═══════════════════════════════════════════════════════
// FLUID CONTROLLER
// ═══════════════════════════════════════════════════════
```

Current sections, in file order: `CONFIG`, `PIANO LAYOUT`, `PIANO RENDERER`,
`FX RENDERER`, `MIDI HANDLER`, `SCENE IMAGE DB`, `SCENE MANAGER`,
`MIDI FILE PLAYER`, `FLUID CONTROLLER`, `LED OUTPUT`, `AUDIENCE COLOR CLIENT`,
`THEME MANAGER`, `NOTE COLOR SYSTEM`, `SETTINGS CONTENT BUILDER`,
`MIDI CC MAPPABLE PARAMETERS`, `SETTINGS WIRING`, `MIDI CC PARAM APPLY`,
`SCENE WIRING`, `MIDI CC MAPPING WIRING`.

### Configuration and persistence

All state lives in the `Config` object. `Config._d` holds the defaults; anything a
user changes is deep-merged over the defaults and persisted to `localStorage`
under the key `pianoVisCfg`.

Shorthand accessors you'll see everywhere: `Config.ns` (note style), `Config.ks`
(keyboard), `Config.ds` (display), `Config.lo` (LED output), `Config.ac`
(audience), `Config.lrn` (learn mode).

**Adding a new setting is usually three small edits:**

1. Add the key with its default to the right group in `Config._d`.
2. Add a control to the settings markup with the `data-cfg` / `data-cfk`
   attributes — the generic wiring in `wireSettings()` picks it up automatically:
   ```html
   <input type="range" data-cfg="ns" data-cfk="my_new_thing" min="0" max="100">
   ```
   Toggles use `data-ns-tog="my_new_flag"` instead.
3. Read `Config.ns.my_new_thing` wherever it's used in the render loop.

Never call `Config.save()` directly from an input handler — use `schedSave()`,
which debounces writes by 300 ms.

To make a value controllable from a MIDI knob, add one row to the `MIDI_PARAMS`
table (`{g:'Effects', label:'…', target:'ns.my_new_thing', min:0, max:100}`) and
it becomes mappable in **Settings → Hardware** with no other changes.

### Backwards compatibility

Saved configs, themes, scenes, and preset files from earlier versions must keep
loading. `Config.load()` contains migration code for exactly this reason. If you
rename or restructure a config key, add a migration next to the existing ones
rather than breaking old saves — people have hand-tuned presets they care about.

### Code style

Match the surrounding code. It is deliberately compact: 2-space indent, tight
spacing around operators, `"use strict"` at the top of the script block. Don't
reformat regions you aren't otherwise changing — whitespace-only churn in a
single-file project makes diffs unreviewable for everyone else.

No dependencies get added to the web app without discussion. Everything except
VexFlow and OSMD is hand-rolled on purpose, and staying dependency-free is what
keeps "just open the file" true.

---

## Working on the other pieces

**Python desktop app** — `pip install -r requirements.txt`, then
`python main.py` (or the `.bat` launcher on Windows, which sets up a venv for
you). Crashes write a JSON report to `crash_logs/`; attach one to bug reports.
Copy `config.example.json` to `config.json` for local settings — `config.json` is
gitignored because it holds personal paths and hardware addresses.

**Vote server** — `cd server && npm install && node server.js`. Requires
`KIK_USERNAME` and `KIK_API_KEY` in the environment. See `server/README.md`.

**ESP32 firmware** — flash `firmware/esp32_fastled_bridge/esp32_fastled_bridge.ino`.
The wire protocol is documented in the main README; if you change the frame format,
update both the firmware and the `LED OUTPUT` section of `docs/index.html` in the
same PR, and note the compatibility break.

---

## Testing your change

There is no automated test suite yet. **Adding one is a genuinely welcome
contribution** — see the ideas below. For now, verify by hand and tell us what you
checked.

Before opening a PR, run through whatever's relevant:

- [ ] App loads in Chrome with no console errors (F12)
- [ ] Notes render and animate when you play or run a MIDI file
- [ ] Settings you touched persist across a page reload
- [ ] An existing preset from `examples/` still imports cleanly
- [ ] Frame rate holds up during a dense passage (glissando, sustained chords)
- [ ] If you touched LED output: frames still reach the strip, or the serial
      output still matches the documented format

Note the browser and OS you tested on in the PR description.

---

## Submitting a pull request

1. Fork and branch off `main` — `git checkout -b fix/spark-decay`.
2. Keep the PR focused on one thing. A 40-line behaviour fix and a 400-line
   refactor in one PR is very hard to review in a single-file codebase.
3. Fill in the PR template: what changed, why, and how you tested it.
4. Attach a screenshot or short clip for anything visual. This project is
   entirely about what it looks like — a 5-second capture communicates more than
   three paragraphs.

For anything large — a rewrite, a new subsystem, a build step, a new dependency —
**open an issue first** so we can agree on the approach before you spend a weekend
on it.

---

## Good places to start

Ideas that are self-contained and don't require deep familiarity with the codebase:

**Beginner**
- New preset JSON files in `examples/` for well-known pieces
- New GLSL shader presets for the shader-note renderer (Shadertoy-style
  `mainImage`, so they're easy to prototype outside the app)
- New built-in colour themes in the `NOTE COLOR SYSTEM` section
- Documentation and README fixes — including anything in this file that turned
  out to be wrong or unclear

**Intermediate**
- Keyboard shortcuts for transport and settings toggles
- Touch/mobile-friendly settings UI (currently mouse-oriented)
- MIDI file playback edge cases — tempo changes, pickup bars, odd time signatures
- Accessibility: focus states, ARIA labels, reduced-motion support
- Preset import validation with a readable error instead of a silent failure

**Ambitious**
- A test harness of any kind — even a headless Chrome smoke test that loads the
  page, fires synthetic MIDI events, and asserts no console errors would be a
  real improvement
- Splitting `docs/index.html` into modules **without introducing a build step**
  (native ES modules, so `file://` still works) — needs discussion first, but
  it's the single biggest thing standing between this project and easy
  contribution
- Audio output — soft synth for playback without hardware
- Recording/export of a performance to video

**Hardware**
- Testing against MIDI keyboards other than the Roland JUNO-DS and reporting what
  works. This is genuinely useful and costs you ten minutes.
- Alternative LED strip layouts and key mappings

---

## Reporting bugs

Open an issue with the bug report template. The things that actually make a
report actionable:

- Browser and version, OS
- Your MIDI device, if the bug involves input
- The **browser console output** (F12 → Console) — for the web app this is
  usually the whole answer
- A `crash_logs/*.log` file, for the Python app
- Your exported settings JSON if the bug is preset- or config-related

---

## Licence

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE), the same as the rest of the project.
