# Piano MIDI Visualizer

A full-screen, real-time piano MIDI visualizer for live performances.  
Designed to run locally on Windows

## Features (Phase 1)
- Full-screen borderless window
- Main menu with **START**, **SETTINGS**, and **QUIT**
- Placeholder note highway screen (press **ESC** to return to menu)
- 60 fps game loop


## Planned
- Real-time MIDI input (Roland JUNO-DS and other USB MIDI devices)
- 88-key piano rendering with key highlights
- Falling-note highway with coloured bars
- Audience-controlled colours via Twitch/TikTok chat
- ESP32 LED light synchronisation

## Requirements
- Python 3.10+
- [pygame](https://www.pygame.org/)

## How to run

```bash
pip install -r requirements.txt
python main.py
```

Press **ESC** from the highway placeholder to return to the main menu.  
Click **QUIT** or close the window to exit.

## Crash Diagnostics

If the app crashes, a JSON crash report is written to `crash_logs/` with:
- Full Python traceback
- Runtime app snapshot (state, MIDI connection details, trail counts, note style)
- Python/platform/pygame version info

Share the newest file in `crash_logs/` to quickly diagnose failures.

## ESP32 LED Output (176 LEDs)

The app can stream note activity to an ESP32-S3 over serial.

1. Install dependencies:
	 - `pip install -r requirements.txt`
2. Create/edit `config.json` in the project root with an `led_output` block:

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

Serial protocol sent from app to ESP32:
- One line per frame (ASCII):
- `LEDS,<led_count>,r0,g0,b0,r1,g1,b1,...\n`
- For 88 keys with 176 LEDs, default mapping is 2 LEDs per key.
- MIDI note 21 (A0) maps to LEDs 0-1, note 22 maps to 2-3, ... note 108 maps to 174-175.

Tip:
- Keep ESP32 parser non-blocking and apply frame only after a full newline is received.
- For BLE transport, start with `fps_limit` around 10-15 and increase only if stable.

BLE transport mode:
- Set `transport` to `"ble"`
- Set `ble_address` to your ESP32 BLE MAC/address shown by your scanner tool
- Leave the UUID defaults unless you changed them in firmware
- The app writes the same `LEDS,...\n` frame, chunked across BLE packets

### In-app LED Settings

From `Settings`, open `LED SETTINGS` to configure:
- Enable/disable serial LED output
- COM port cycling + port refresh
- Baud rate cycling
- LED FPS, LEDs-per-key mapping, and active RGB color

### FastLED Firmware

A ready-to-flash FastLED bridge sketch is included at:
- `firmware/esp32_fastled_bridge/esp32_fastled_bridge.ino`

Defaults in sketch:
- `LED_COUNT 176`
- `SERIAL_BAUD 115200`
- Reads exactly the app protocol: `LEDS,<count>,r,g,b,...` per line
- Also accepts BLE writes on service `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
- Write characteristic UUID: `6E400002-B5A3-F393-E0A9-E50E24DCCA9E`

Arduino library requirement for BLE firmware:
- Install `NimBLE-Arduino`

## Audience Color Control (App Side)

The app can connect to your backend WebSocket and apply live audience colors.

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

Behavior:
- App smooths from current to target color over `transition_ms`
- Updates note colors in real time
- Updates LED active color in real time


