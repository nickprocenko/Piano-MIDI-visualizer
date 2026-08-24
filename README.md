# Piano MIDI Visualizer

A full-screen, real-time piano MIDI visualizer for live performances, built as a single-page web app.  
Open it locally or deploy to any static host — no server required for the visualizer itself.

Live deployment: <a href="https://nickprocenko.github.io/Piano-MIDI-visualizer/" target="_blank" rel="noopener noreferrer">https://nickprocenko.github.io/Piano-MIDI-visualizer/</a>

## Features

- Real-time MIDI input via the **Web MIDI API** (USB MIDI devices — tested with Roland JUNO-DS)
- Rising-note highway with full visual customisation (colour, glow, sparks, smoke, halo pulse, and more)
- **Learn Mode** — drop a MIDI or MusicXML file, choose tracks and hands, and follow along at your own pace (Wait or Free-play)
- **Freeplay** — just plug in and play, no file needed
- Animated fluid ink effects (GPU-accelerated via WebGL)
- **Shader Notes** — render the falling notes with GLSL fragment shaders (built-in presets like Twisty Ribbons and Neon Glow Bars, or paste your own Shadertoy-style `mainImage`)
- Animated background image / GIF slideshow
- ESP32 LED strip synchronisation over serial or BLE
- **Drum Kit LEDs** — an LED ring per drum on an electronic kit (Roland TD-9), each with its own effect, colour and velocity response
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
| Drum LEDs | Per-drum LED rings, pad mapping, ring effects, pad scripts |
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

## Drum Kit LED Output

Drives an LED ring around the top of each drum from an electronic kit (developed against a
**Roland TD-9** over USB MIDI). Each drum gets its own data pin, its own effect, and its own
colour, and every stroke is captured as a discrete hit with a velocity-scaled decay envelope —
so rolls and flams read as separate events rather than one smear.

This is a separate path from the piano LED output above: separate config, separate protocol,
separate firmware. Both can run at once on two boards.

### Quick start

1. Flash `firmware/esp32_drum_leds/esp32_drum_leds.ino` (needs the **FastLED** library, 3.6+).
2. Serve the app over `http://localhost` or HTTPS — Web Serial refuses `file://`:
   ```bash
   cd docs && python3 -m http.server 8000
   ```
3. **Settings → Drum LEDs** → set the LED count for each drum → **Connect**.
4. **Identify** on each pad sweeps a single pixel round that strip, so you can see which
   physical drum is on which output and fix the `Strip` numbers.
5. Hit each drum and watch the **MIDI Monitor**. Anything showing `UNMAPPED` gets a one-click
   **+ Add** chip; or use **Learn** per pad, or **Map My Kit…** to walk the whole kit at once.

**DRUM KIT** on the main menu gives a full-screen top-down view of the rings, so you can
rehearse the lighting without looking at the drums. Number keys **1**–**9** fire pads
(Shift = soft hit, Alt = rim).

### Wiring

One WS2812B ring per drum, each on its own GPIO. Slot numbers in the app map to the
`STRIP_PINS[]` table at the top of the sketch — edit that table to match your build:

| Slot | Default GPIO | Suggested drum |
|------|--------------|----------------|
| 0 | 18 | Kick |
| 1 | 19 | Snare |
| 2 | 21 | Tom 1 |
| 3 | 22 | Tom 2 |
| 4 | 23 | Floor Tom |
| 5 | 25 | Hi-Hat |
| 6 | 26 | Crash |
| 7 | 27 | Ride |

Put a 300–470 Ω resistor in series with each data line at the board, a 1000 µF capacitor
across 5V/GND at each drum, and power the strips from a dedicated 5V supply rather than the
ESP32's USB rail — with all grounds tied together.

> **Board limits — check before wiring eight drums.** FastLED drives WS2812B through the RMT
> peripheral, one channel per strip: **ESP32 (classic) has 8**, **ESP32-S3 has 4**, **ESP32-C3
> has 2**. On an S3 or C3, keep the strip count at or below that limit, or daisy-chain several
> drums onto one output.

### Roland TD-9 default note map

Loaded out of the box, and restorable any time with **Load TD-9 Map** (which leaves your
colours, effects and LED counts alone). Note maps are editable per kit, so confirm yours with
the MIDI Monitor.

| Pad | Head / bow | Rim / edge | Enabled by default |
|---|---|---|---|
| Kick | 36 | — | ✅ |
| Snare | 38 | 37 cross-stick, 40 rimshot | ✅ |
| Tom 1 | 48 | 50 | ✅ |
| Tom 2 | 45 | 47 | ✅ |
| Floor Tom | 43 | 58 | ✅ |
| Hi-Hat | 46, 42 | 22, 26, 44 pedal | — |
| Crash 1 | 49 | 55 | — |
| Ride | 51 | 59, 53 bell | — |

The cymbals ship disabled since the strips are on the drums; enable them in the Pads list, or
use **+ Add Pad** for anything else (a second crash, an aux pad).

### Ring effects

Each pad picks one, with its own colour, accent colour, decay, velocity response, speed and
arc width. Rim/edge hits use the accent colour and a shorter decay so they read differently
from the head.

| Effect | On a ring |
|---|---|
| Flash | Whole ring lights, exponential decay — the reliable default |
| Radial Burst | Two arcs leave the top, meet at the bottom, fade |
| Comet Spin | An arc whips round the ring with a fading tail |
| Sparkle | Random pixels pop, count scaled by velocity |
| Ripple | A wavefront expands both ways with a damped wake |
| VU Ring | Fills in proportion to velocity, then drains |
| Strobe | Rapid on/off pulses inside the decay window |
| Rainbow Spin | Hue rotates round the ring; hits boost it |
| Hue Step | Each stroke advances the hue — rolls paint a gradient |
| Ember | Ring-wrapped fire flicker fed by hits |
| Alternating Halves | Successive hits light opposite halves |
| Theater Chase | Every Nth pixel lit, marching round |

Plus a per-pad idle layer (off / solid / breathe / drift) so the kit glows between strokes.

### Custom lighting per drum

**Settings → Drum LEDs → Pad Script** takes a JavaScript script that replaces the built-in
effect for one pad:

```js
api.onFrame(function(now, dt, hits){
  api.fill(0,0,0);
  for (const h of hits) {
    const a = Math.exp(-h.age / 0.3) * h.vel;
    const c = api.hsvToRgb((h.index * 0.13) % 1, 0.95, 1);   // new hue each stroke
    for (let i = 0; i < api.len; i++) api.add(i, c.r*a, c.g*a, c.b*a);
  }
});
```

**Copy AI Prompt** puts a full API reference — plus that pad's name, LED count and current
script — on the clipboard, ready to hand to any assistant. The same text lives in
[`examples/prompts/drum-script.md`](examples/prompts/drum-script.md).

Whole-kit setups save as named presets and export to JSON;
[`examples/drum-kit-td9.json`](examples/drum-kit-td9.json) is the factory map.

### Protocol

USB serial at 921600 baud. Binary rather than the piano path's ASCII CSV, because a drum
flash has to land within a few milliseconds of the stick:

```
A5 5A <type> <len_lo> <len_hi> <payload…> <crc8>
```

`len` counts payload bytes only; CRC-8/ATM (poly 0x07) covers type + length + payload. The
parser is length-driven, so `A5 5A` occurring inside pixel data is just data; a failed CRC
costs one frame.

| Type | Name | Payload |
|---|---|---|
| `0x01` | CFG | `nStrips`, then `{slot:u8, len:u16}` per strip, then `power_ma:u16` |
| `0x02` | FRAME | `seq:u8`, then every configured strip's pixels concatenated, `r,g,b` each |
| `0x03` | PING | — (device replies with an ASCII banner) |
| `0x04` | IDENT | `slot:u8` — sweeps one strip so you can identify it |
| `0x05` | BLANK | — all strips off |

A five-drum kit of 120 pixels is 367 bytes a frame, about 24 % of the link at 60 fps. The
tab shows live bandwidth and turns red past 85 %; **Protocol Self-Test** checks the framing
and flags configuration mistakes (two drums on one output, a strip longer than the firmware
allows) without any hardware attached.

Until it has a valid CFG the device prints `DKNEEDCFG` once a second, and the app answers
automatically — so resetting or reflashing the ESP32 mid-session recovers on its own. If
frames stop for two seconds the firmware fades the kit out rather than freezing it lit.

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
- `drum-script.md` — generates a per-drum ring lighting script

Click **Copy AI Prompt** in the script editor to copy a prompt that includes your current script for the AI to iterate on.
