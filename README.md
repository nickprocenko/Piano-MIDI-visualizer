# Piano MIDI Visualizer

**A full-screen, real-time piano MIDI visualizer for live performances — one HTML file, no build step, no install.**

Plug in a MIDI keyboard, open the page, and play. Notes rise off the keys as glowing
trails through GPU fluid ink and custom GLSL shaders. Drop in a MIDI or MusicXML file
and it becomes a learn-along tool. Wire up an ESP32 and your LED strip lights up with
you.

[![License: MIT](https://img.shields.io/badge/License-MIT-brightgreen.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Live demo](https://img.shields.io/badge/demo-live-blue.svg)](https://nickprocenko.github.io/Piano-MIDI-visualizer/)

### ▶ [Try it live](https://nickprocenko.github.io/Piano-MIDI-visualizer/) — Chrome or Edge, no sign-up

<!--
  TODO: drop a screenshot or short GIF here — it does more than any paragraph above.
  Commit it to docs/media/ and reference it:
  ![Piano MIDI Visualizer](docs/media/demo.gif)
-->

---

## 🤝 Looking for collaborators

This started as a personal tool for live piano performances and is now open for
contributions. **There is no build tooling and no framework** — clone the repo, open
`docs/index.html` in Chrome, edit, refresh. If you have a text editor you can already
contribute.

Especially interested in help with:

- **Shaders and visual effects** — the note renderer takes Shadertoy-style GLSL, so new
  presets are self-contained and easy to prototype
- **Testing on hardware other than a Roland JUNO-DS** — genuinely useful, costs ten minutes
- **Mobile / touch support** and accessibility in the settings UI
- **A test harness of any kind** — there is currently none
- **Splitting the single-file app into ES modules** without adding a build step

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the repo layout, a walkthrough of how the
single-file app is organised, and a list of good places to start. Questions and
half-formed ideas are welcome in [issues](https://github.com/nickprocenko/Piano-MIDI-visualizer/issues).

---

## Features

- Real-time MIDI input via the **Web MIDI API** (USB MIDI devices — tested with Roland JUNO-DS)
- Rising-note highway with full visual customisation (colour, glow, sparks, smoke, halo pulse, and more)
- **Learn Mode** — drop a MIDI or MusicXML file, choose tracks and hands, and follow along at your own pace (Wait or Free-play)
- **Freeplay** — just plug in and play, no file needed
- Animated fluid ink effects (GPU-accelerated via WebGL)
- **Shader Notes** — render the falling notes with GLSL fragment shaders (built-in presets like Twisty Ribbons and Neon Glow Bars, or paste your own Shadertoy-style `mainImage`)
- Animated background image / GIF slideshow
- ESP32 LED strip synchronisation over serial or BLE
- Audience live colour control via WebSocket (Kik / Twitch channel-point integration)
- Built-in theme manager — save, rename, load, and delete colour presets
- Scenes & Profiles — store and switch full visual snapshots
- Mappable MIDI CCs for any control
- 60 fps game loop

## How to run

### Quickest: open the live site

Go to <https://nickprocenko.github.io/Piano-MIDI-visualizer/> in **Chrome** or **Edge** (Web MIDI requires a Chromium browser).

### Local file (no internet required)

```
docs/index.html   ← open this file directly in Chrome/Edge
```

No install, no server, no build step.

### Self-hosted

Copy the `docs/` folder to any static web host (Netlify, Vercel, GitHub Pages, nginx, etc.).

> **Browser requirement:** Web MIDI API is supported in Chromium-based browsers only (Chrome, Edge, Opera). Firefox and Safari do not support it.

## Settings

Open **SETTINGS** from the main menu. Tabs:

| Tab | What you configure |
|-----|-------------------|
| Notes | Colour mode, glow, sparks, smoke, trail speed |
| Effects | Halo pulse, bloom, spark physics |
| Fluid | Ink fluid simulation (curl, dissipation, pressure) |
| Shader | GPU note rendering — presets or custom Shadertoy-style GLSL (WebGL2) |
| Keyboard | Piano height, brightness, visibility |
| Display | Background slides, frame rate cap |
| Hardware | MIDI CC mappings |
| LED Output | ESP32 serial / BLE config |
| Audience | WebSocket URL for live audience colour votes |
| Themes | Save / load / delete colour presets |
| Scenes & Profiles | Full visual snapshots |

## Learn Mode

1. Select **LEARN MODE** from the menu.
2. Drop a `.mid`, `.midi`, `.xml`, or `.musicxml` file (or click **Browse**).
3. Pick which tracks to show and assign hands (Left / Right).
4. Choose **Wait** (pauses until you play the right note) or **Free-play** (plays at your set speed).
5. Click **▶ Start Learning**.

A floating transport HUD lets you pause, loop, and adjust speed without leaving the highway.

## Crash diagnostics

If the visualizer stops rendering, open the browser DevTools console (F12) for error details.

## ESP32 LED Output

The app streams note activity to an ESP32-S3 over serial or BLE.

Add an `led_output` block to `config.json` (persisted in `localStorage` when running in-browser):

```json
{
  "led_output": {
    "enabled": true,
    "transport": "serial",
    "port": "COM5",
    "baudrate": 115200,
    "ble_address": "AA:BB:CC:DD:EE:FF",
    "ble_service_uuid": "6E400001-B5A3-F393-E0A9-E50E24DCCA9E",
    "ble_char_uuid": "6E400002-B5A3-F393-E0A9-E50E24DCCA9E",
    "ble_write_with_response": false,
    "ble_chunk_size": 180,
    "led_count": 176,
    "mirror_per_key": 2,
    "fps_limit": 12,
    "active_r": 0,
    "active_g": 220,
    "active_b": 220
  }
}
```

Serial protocol (one line per frame, ASCII):
```
LEDS,<led_count>,r0,g0,b0,r1,g1,b1,...\n
```
For 88 keys × 2 LEDs: MIDI note 21 (A0) → LEDs 0–1, note 22 → LEDs 2–3, … note 108 → LEDs 174–175.

BLE transport: set `transport` to `"ble"` and fill in the address. Same frame format, chunked across BLE packets.

### FastLED Firmware

`firmware/esp32_fastled_bridge/esp32_fastled_bridge.ino` — ready to flash.

Defaults:
- `LED_COUNT 176`, `SERIAL_BAUD 115200`
- Accepts BLE writes on service `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` (characteristic `6E400002-…`)
- Install `NimBLE-Arduino` for BLE support

## Audience Color Control

The app connects to a WebSocket backend and applies live audience-voted colors.

Settings → **Audience** tab:
- WebSocket URL: `ws://localhost:8766` (or your deployed server)
- Click **Connect**

Expected incoming message:
```json
{
  "type": "color_set",
  "rgb": { "r": 41, "g": 220, "b": 255 },
  "transition_ms": 220
}
```

The visualizer smooths from the current colour to the target over `transition_ms` and updates both note colours and LED output in real time.

## Audience Vote Server (`server/`)

A Node.js server that lets your Kik audience vote on live visual changes. Polls rotate automatically; the winner is applied to the visualizer over WebSocket.

### Vote categories

| Category | Options |
|----------|---------|
| Note Theme | Rainbow, Octave Rainbow, Fire, Ice, Sunset |
| Performance | Riders on the Storm, Moonlight Sonata, Light My Fire, Claire de Lune *(full preset)* |
| Trail Colour | Ocean Blue, Sunset Red, Forest Green, Neon Purple |
| Trail Speed | Slow, Normal, Fast, Very Fast |
| Effects | Sparks On/Off, Smoke On/Off |
| Fluid Effect | Default, Smoke, Fire, Storm, Gentle, Explosion |

### Viewer commands

| Message | Bot replies |
|---------|------------|
| `1`–`N` (poll active) | Confirms vote with time remaining |
| `!suggest <name>` | Queues a poll for the matched option |
| `status` | Shows current poll or next-poll countdown |
| `!help` | Lists all categories, options, and commands |

See [`server/README.md`](server/README.md) for full setup (Kik bot registration, ngrok, OBS browser source, WebSocket wiring).

Quick start:
```bash
cd server
npm install
export KIK_USERNAME=yourbotname
export KIK_API_KEY=yourapikey
node server.js
```

### OBS Overlay (`docs/overlay.html`)

Add as a **Browser Source** in OBS (1920×1080, transparent background, local file path). The corner card slides in when a poll starts and slides out during the cooldown.

## Example Presets

`examples/` contains ready-made JSON settings files. Import any via **Settings → Themes → Import**:

| File | Description |
|------|-------------|
| `claire-de-lune.json` | Soft blue-white palette, gentle fluid ripple, no sparks |
| `moonlight-sonata.json` | Deep indigo tones, slow trails |
| `light-my-fire.json` | Warm amber/red, sparks on, fast scroll |
| `riders-on-the-storm.json` | Cool storm palette, smoke enabled |

## AI Prompt Files

`examples/prompts/` — copy-paste prompts for any external AI (Claude, ChatGPT, etc.):

- `script.md` — generates a colour script with the full API reference embedded
- `preset.md` — generates a JSON settings preset with the full schema embedded

Click **Copy AI Prompt** in the script editor to copy a prompt that includes your current script for the AI to iterate on.

## Project structure

The repo contains four independent programs that share a protocol and a look. Most
work only touches one of them.

| Path | What it is |
|------|-----------|
| `docs/index.html` | **The web app** — one self-contained file, no build step |
| `docs/notation.html` | Sheet-music strip (OpenSheetMusicDisplay, loaded in an iframe) |
| `docs/overlay.html` | OBS browser-source overlay for audience polls |
| `main.py`, `src/` | Standalone desktop version (Python + pygame), Windows-oriented |
| `server/` | Audience vote server — Kik chat bot, WebSocket out to the visualizer |
| `firmware/` | ESP32-S3 FastLED sketch for the LED strip |
| `examples/` | Importable preset JSON and AI prompt templates |
| `tools/` | Dev utilities — BLE scanner, fluid prototype, renderer stress test |

The web app and the Python app are separate implementations, not a shared core.
`docs/` is what GitHub Pages deploys on every push to `main`.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, how the
single-file app is laid out, and ideas for where to start. Bug reports, presets, and
shader submissions all count.

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

[MIT](LICENSE) © 2026 Nick Procenko — use it, fork it, perform with it, sell it.
