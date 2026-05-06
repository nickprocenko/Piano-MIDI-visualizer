# Piano MIDI Visualizer

A full-screen, real-time piano MIDI visualizer for live performances.  
Designed to run locally on Windows with a dual-monitor setup (projector + PC).

## Features

- Borderless fullscreen on a second monitor — clicking your PC monitor won't minimise the window
- Real-time MIDI input (USB MIDI devices — tested with Roland JUNO-DS)
- 88-key piano rendering with brightness and height controls
- Falling-note highway with full visual customisation (colour, glow, sparks, smoke, halo pulse, and more)
- Animated background image / GIF slideshow
- ESP32 LED strip synchronisation over serial or BLE
- Audience live colour control via WebSocket
- **Kick.com chat bot** — viewers control colours and effects live via chat commands
- Triple sustain-pedal tap to cycle through saved themes
- Built-in theme manager — save, rename, load, and delete colour presets
- **Live web control panel** at `http://localhost:8181` — change notes, effects, keyboard, and themes from your browser while a song is playing
- 60 fps game loop with crash diagnostics

## Requirements

- Python 3.10+
- Internet connection on first launch (to download packages)

## How to Run

### Double-click (recommended)

Just double-click **`Launch Piano MIDI Visualizer.bat`**.  
On first launch it automatically creates a virtual environment and installs all Python dependencies from `requirements.txt`. Subsequent launches start immediately.

### Command line

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Press **ESC** during a song to return to the main menu.  
Click **QUIT** or close the window to exit.

## Visual Effects

All effects are togglable and tunable from the in-app **Notes Settings** screen or via the web control panel.

| Effect | Config key | Description |
|---|---|---|
| Glow | `effect_glow_enabled` | Soft bloom around each note |
| Highlight | `effect_highlight_enabled` | Bright streak at the top of each note |
| Sparks | `effect_sparks_enabled` | Spark particles flying off notes |
| Smoke | `effect_smoke_enabled` | Rising smoke trail above notes |
| Press Smoke | `effect_press_smoke_enabled` | Smoke burst on key press |
| Moon Dust | `effect_moon_dust_enabled` | Floating ambient dust particles |
| Steam Smoke | `effect_steam_smoke_enabled` | Denser upward steam mode for smoke |
| Halo Pulse | `effect_halo_pulse_enabled` | Expanding halo ring on key press |

Strength sliders: `glow_strength_percent`, `highlight_strength_percent`, `spark_amount_percent`, `smoke_amount_percent`, `press_smoke_amount_percent`.  
Decay controls: `decay_speed`, `decay_value` — tune how quickly notes fade as they rise.

## Crash Diagnostics

If the app crashes, a JSON crash report is written to `crash_logs/` with:
- Full Python traceback
- Runtime app snapshot (state, MIDI connection details, trail counts, note style)
- Python / platform / pygame version info

Share the newest file in `crash_logs/` to quickly diagnose failures.

## ESP32 LED Output

The app can stream note activity to an ESP32-S3 over serial or BLE.

Add an `led_output` block to `config.json` (see `config.example.json` for all fields):

```json
{
  "led_output": {
    "enabled": true,
    "transport": "serial",
    "port": "COM5",
    "baudrate": 115200,
    "led_count": 176,
    "mirror_per_key": 2,
    "fps_limit": 12,
    "active_r": 0,
    "active_g": 220,
    "active_b": 220
  }
}
```

**Serial protocol** (one ASCII line per frame):
```
LEDS,<led_count>,r0,g0,b0,r1,g1,b1,...\n
```
For 88 keys with 176 LEDs, default mapping is 2 LEDs per key.  
MIDI note 21 (A0) → LEDs 0–1, note 108 (C8) → LEDs 174–175.

**BLE transport:** set `transport` to `"ble"`, provide your ESP32 MAC in `ble_address`, and leave UUID defaults unless you changed them in firmware. Start with `fps_limit` around 10–15.

### In-app LED Settings

From `Settings → LED SETTINGS`:
- Enable/disable output
- COM port cycling and refresh
- Baud rate cycling
- FPS limit, LEDs-per-key, and active RGB colour

### FastLED Firmware

A ready-to-flash sketch is at `firmware/esp32_fastled_bridge/esp32_fastled_bridge.ino`.

Defaults:
- `LED_COUNT 176`, `SERIAL_BAUD 115200`
- Parses the `LEDS,<count>,r,g,b,...` protocol
- BLE service UUID: `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
- BLE write characteristic: `6E400002-B5A3-F393-E0A9-E50E24DCCA9E`
- Arduino library required: **NimBLE-Arduino**

## Audience Color Control (WebSocket)

The app can connect to a backend WebSocket and apply live audience-controlled colours.

Add to `config.json`:

```json
{
  "audience_control": {
    "enabled": true,
    "ws_url": "wss://your-domain/ws/app",
    "channel_id": "12345678",
    "app_api_key": "your-app-secret",
    "reconnect_sec": 2.0
  }
}
```

Expected incoming WebSocket message:

```json
{
  "type": "color_set",
  "rgb": {"r": 41, "g": 220, "b": 255},
  "transition_ms": 220
}
```

The app smooths from the current to the target colour over `transition_ms` milliseconds, updating note colours and LED active colour in real time.

## Kick.com Chat Bot

Run `tools/kick_chat.py` alongside the visualizer to let viewers control the visuals from Kick chat. Commands are forwarded to the local control server — no extra relay needed.

Add credentials to `config.json`:

```json
{
  "kick_chat": {
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uri": "http://localhost:8080/callback",
    "channel": "YOUR_KICK_USERNAME"
  }
}
```

Start the bot:

```bash
python tools/kick_chat.py
```

**Available chat commands:**

| Command | Example | Effect |
|---|---|---|
| `!color` | `!color #ff00ff` or `!color 255,0,128` | Set note colour |
| `!bright` | `!bright 80` | Set keyboard brightness (0–100) |
| `!speed` | `!speed 500` | Set note fall speed (100–1200 px/sec) |
| `!glow` | `!glow 60` | Set glow strength (0–100) |
| `!sparks` | `!sparks on` / `!sparks off` | Toggle sparks effect |
| `!smoke` | `!smoke on` / `!smoke off` | Toggle smoke effect |

## Tools

| Script | Description |
|---|---|
| `tools/kick_chat.py` | Kick.com chat bot — forwards chat commands to the visualizer |
| `tools/ble_scan.py` | Scan for nearby BLE devices to find your ESP32 address |
| `tools/stress_test_renderer.py` | Benchmark the note renderer with synthetic load |

## Web Control Panel

While the visualizer is running, open `http://localhost:8181` in any browser on the same machine to:
- Change note colour and interior colour
- Adjust glow, highlight, sparks, smoke, and all effect strengths
- Toggle individual effects on/off
- Set keyboard brightness and height
- Load, save, rename, and delete themes

All changes apply instantly without restarting.
