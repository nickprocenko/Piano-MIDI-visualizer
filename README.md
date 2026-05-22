# Piano MIDI Visualizer

A real-time piano MIDI visualizer for live performances. Two editions share the same project:

| Edition | Entry point | Use case |
|---------|------------|----------|
| **Desktop app** | `main.py` / `Launch Piano MIDI Visualizer.bat` | Fullscreen local performance with LED output |
| **Web visualizer** | `docs/index.html` | Browser-based, zero-install, OBS-streamable |

Live site: <a href="https://nickprocenko.github.io/Piano-MIDI-visualizer/" target="_blank" rel="noopener noreferrer">https://nickprocenko.github.io/Piano-MIDI-visualizer/</a>

---

## Desktop App

### Features

- Borderless fullscreen on a second monitor — clicking your PC monitor won't minimise the window
- Real-time MIDI input (USB MIDI devices — tested with Roland JUNO-DS)
- 88-key piano rendering with animated rising-note highway
- Full visual customisation: colour, glow, sparks, smoke, halo pulse, fluid ripple, and more
- **Per-item slideshow**: each background image or GIF has its own Slide duration, Fade blend, and (for GIFs) Speed slider
- ESP32 LED strip synchronisation over serial or BLE
- Audience live colour control via WebSocket
- Mappable MIDI CCs for live controls
- Built-in theme manager — save, rename, load, and delete colour presets
- **Live web control panel** at `http://localhost:8181` — adjust notes, effects, keyboard, and themes from a browser while a song plays
- 60 fps game loop with crash diagnostics

### Requirements

- Python 3.10+
- Internet connection on first launch (packages are installed automatically)

### Running

**Double-click (recommended):** `Launch Piano MIDI Visualizer.bat`  
On first launch it creates a virtual environment and installs all dependencies. Subsequent launches start immediately.

**Command line:**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Press **ESC** during a song to return to the main menu. Click **QUIT** or close the window to exit.

### Display Settings — Per-Item Slideshow

Open **Settings → Display Settings**. The right panel shows your loaded slideshow items. Each row has:

- **Slide** slider (1–60 s) — how long that image stays on screen
- **Fade** slider (10–90%) — what fraction of the dwell time is used for the crossfade blend
- **Speed** slider (10–200%, GIFs only) — playback rate relative to the embedded frame timings
- **×** button — remove that item from the slideshow

Use **SELECT BACKGROUND(S) / GIF** to load one or more files at once. Use **ADD MORE TO SLIDESHOW** to append additional files. Mouse-wheel scrolls the list when it overflows.

### Live Web Control Panel

1. Start the app.
2. Open `http://localhost:8181` in a browser on the same machine.
3. Adjust **Notes**, **Effects**, **Fluid**, **Keyboard**, and **Themes** tabs — changes apply live and are saved to `config.json`.

The panel is local-only and not exposed to the network.

### ESP32 LED Output

Configure in **Settings → LED Settings** or directly in `config.json`:

```json
{
  "led_output": {
    "enabled": true,
    "transport": "serial",
    "port": "COM5",
    "baudrate": 115200,
    "led_count": 176,
    "mirror_per_key": 2,
    "fps_limit": 12
  }
}
```

For BLE: set `"transport": "ble"` and provide `ble_address`. The same `LEDS,<count>,r,g,b,...\n` protocol is used over both transports.

A ready-to-flash FastLED firmware sketch is at `firmware/esp32_fastled_bridge/esp32_fastled_bridge.ino`.

### Crash Diagnostics

If the app crashes a JSON report is written to `crash_logs/` with the full traceback, runtime snapshot, and version info. Share the newest file to diagnose failures.

---

## Web Visualizer (`docs/index.html`)

A fully self-contained browser visualizer — no server required for basic use. Open the file locally or serve it from GitHub Pages.

### Features

- All note-style and effect settings from the desktop app
- **Script editor** — write JavaScript that runs against a live API to colour notes dynamically
- **Script callbacks**: `api.onNoteOn(fn)`, `api.onNoteOff(fn)`, `api.onFrame(fn)` for reactive, time-based effects
- **Re-attack trail gap** — when a note is re-struck while the sustain pedal is held, a small visual gap appears in the trail at the strike point, distinguishing new attacks from sustained resonance
- **Canvas drag-and-drop** — drop a `.mid` file onto the running visualiser to swap the song without interrupting the stream
- **Tracks panel** (HUD side panel) — mute, recolour, and mark "you play" per MIDI channel while streaming
- Audience vote integration via WebSocket (see Audience Vote Server below)

### Script API

```js
// Static setup runs once:
api.setAll(0, 100, 200);

// Reactive callbacks:
api.onNoteOn(function(note, velocity, channel) {
  api.setNote(note, velocity * 2, velocity * 2, 255);
});
api.onNoteOff(function(note, channel) {
  api.setNote(note, null);   // revert to base colour
});
api.onFrame(function(activeNotes, now, dt) {
  // now = ms, dt = seconds since last frame
  for (const n of activeNotes) {
    const [r, g, b] = api.hsvToRgb((now / 2000 + n / 12) % 1, 1, 1);
    api.setNote(n, r, g, b);
  }
});
```

Full API reference: `examples/prompts/script.md`

### Example Presets

`examples/` contains ready-made JSON settings files. Import any of them via **Settings → Import**:

| File | Description |
|------|-------------|
| `claire-de-lune.json` | Soft blue-white palette, gentle fluid ripple, no sparks |
| `moonlight-sonata.json` | Deep indigo tones, slow trails |
| `light-my-fire.json` | Warm amber/red, sparks on, fast scroll |
| `riders-on-the-storm.json` | Cool storm palette, smoke enabled |

### AI Prompt Files

`examples/prompts/` contains copy-paste prompts for any external AI (Claude, ChatGPT, etc.):

- `script.md` — generates a colour script with the full API reference embedded
- `preset.md` — generates a JSON settings preset with the full schema embedded

Click **Copy AI Prompt** in the script editor to copy a prompt that already includes your current script for the AI to iterate on.

---

## Audience Vote Server (`server/`)

A Node.js server that lets your Kik audience vote on live visual changes. Polls run automatically; winners are applied to the web visualizer instantly via WebSocket.

### Vote categories (random rotation, never repeats back-to-back)

| Category | Options |
|----------|---------|
| Note Theme | Rainbow, Riders on the Storm, Moonlight Sonata, Light My Fire |
| Trail Colour | Ocean Blue, Sunset Red, Forest Green, Neon Purple |
| Trail Speed | Slow, Normal, Fast, Very Fast |
| Effects | Sparks On/Off, Smoke On/Off |
| Fluid Effect | Default, Smoke, Fire, Storm, Gentle, Explosion |

### Viewer commands

| Message | Bot replies |
|---------|------------|
| `1` – `4` (poll active) | Confirms vote with time remaining |
| `!suggest <name>` | Queues a poll for the matched option; if ambiguous, lists candidates numbered for clarification |
| `status` | Shows current poll or next-poll countdown |

**`!suggest` details:** fuzzy-matches against all option names across all categories (exact → starts-with → substring). When multiple options match, the bot asks the viewer to pick from a numbered list before queuing. One suggestion per viewer in the queue at a time; queue capped at 5. When the poll goes live, the overlay shows *"Suggested by @username"* and the suggester gets a personal Kik ping.

**Proactive notifications:** every viewer who has previously messaged the bot receives a Kik notification when a new poll starts, including the numbered option list.

### Setup

See [`server/README.md`](server/README.md) for the complete setup guide (Kik bot registration, ngrok, OBS browser source, WebSocket connection).

Quick start:
```bash
cd server
npm install
export KIK_USERNAME=yourbotname
export KIK_API_KEY=yourapikey
node server.js
```

### OBS Overlay (`docs/overlay.html`)

Add as a **Browser Source** in OBS (1920×1080, transparent background, local file path). The corner card slides in when a poll starts and slides out during the cooldown. Shows live vote bars, countdown, and the "Suggested by" attribution when applicable.

---

## Project Layout

```
main.py                          Desktop app entry point
Launch Piano MIDI Visualizer.bat Windows launcher
src/                             Desktop app source
  app.py                         Main game loop
  display_settings.py            Per-item slideshow UI
  control_server.py              Local web control panel (port 8181)
  led_output.py                  ESP32 serial/BLE output
  ...
docs/
  index.html                     Web visualizer (self-contained)
  overlay.html                   OBS audience-vote overlay
server/
  server.js                      Audience vote server (Node.js)
  adapters/kik.js                Kik Bot API adapter
  README.md                      Server setup guide
examples/
  *.json                         Importable settings presets
  prompts/
    script.md                    AI prompt for generating colour scripts
    preset.md                    AI prompt for generating JSON presets
firmware/
  esp32_fastled_bridge/          FastLED sketch for ESP32 LED output
tools/
  fluid_prototype.py             Standalone fluid-effect prototype
```
