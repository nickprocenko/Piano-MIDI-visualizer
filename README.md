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
- Audience live colour control via WebSocket (Twitch channel-point integration)
- Triple sustain-pedal tap to cycle through saved themes
- Built-in theme manager — save, rename, load, and delete colour presets
- **Live web control panel** at `http://localhost:8181` — change notes, effects, keyboard, and themes from your browser while a song is playing
- 60 fps game loop with crash diagnostics

## Requirements
- Python 3.10+
- Internet connection on first launch (to download packages)

## How to run

### Double-click (recommended)
Just double-click **`Launch Piano MIDI Visualizer.bat`**.
On first launch it will automatically create a virtual environment and install all Python dependencies from `requirements.txt`. Subsequent launches start immediately.

### Command line

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Press **ESC** during a song to return to the main menu.  
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

## Future UX Ideas (Piano MIDI Visualizer)

These are quick wins to revisit when the core app is stable:

- **"Please wait" indicator** — show a loading/transition overlay whenever the app switches screens (e.g., menu → highway, settings open/close). A simple spinner or animated bar prevents the feeling that the app has frozen.
- **QWERTYUIOP virtual keyboard** — map the top keyboard row (`Q W E R T Y U I O P`) to ten piano notes so users can play without a MIDI device. Lay them out left-to-right as a single octave (10 notes). This is useful for demos, testing, and casual play on a laptop.

---

## Brainstorming: Future App — Music Festival Calendar/Planner

> *Notes captured 2026-04-04. Come back here to resume planning.*

### What it is

A personal planning tool that helps you discover music festivals near Toronto (≤ 50 km), filter them by month/genre/size, lock chosen festivals into a persistent plan, and instantly see scheduling conflicts — with a path to circle/group planning later.

---

### MVP Scope (single user, seeded database first)

**Goal:** filters produce a relevant suggestion list → user locks festivals → conflicts are highlighted.

#### Data model (minimal)

| Table | Key fields |
|---|---|
| `FestivalOccurrence` | `id`, `name`, `start_date`, `end_date`, `lat`, `lng`, `genre_tags` (JSON list), `attendance_estimate` (int, nullable) |
| `Plan` | `id`, `name`, `created_at` |
| `PlanFestival` | `plan` (FK), `festival` (FK), `locked` (bool, default `true`), `status` (`going`/`maybe`/`no`) |

Derived in code: `is_major = attendance_estimate is not None and attendance_estimate >= 10_000`

#### Filter pipeline

| Filter | Rule |
|---|---|
| Radius | Haversine distance from Toronto ≤ 50 km (requires `lat`/`lng` on every record) |
| Month range | `start_date` month falls within selected range |
| Genre | `genre_tags` intersects selected genres |
| Major / Minor / Any | `is_major` threshold = 10,000 attendees |

#### Locked-festival rule

- Filters only affect the **suggestions list** — never auto-remove from the plan.
- If a locked festival no longer matches filters, mark it `out_of_scope = True` (badge: "Outside filters") but keep it in the plan.

#### Conflict detection (MVP)

- Flag any two `PlanFestival` rows whose date ranges overlap (`festivalA.start_date <= festivalB.end_date and festivalA.end_date >= festivalB.start_date`).
- Show a conflict badge on both; list all conflicts in a sidebar panel.
- Only flag when both festivals have a valid `end_date`.

---

### Recommended stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python | Familiar, great ecosystem |
| Framework | Django | Free admin UI for seeding/editing festivals; migrations included |
| Database | PostgreSQL | Future-proof (PostGIS for radius later); works with Django ORM |
| API | Django REST Framework (add later) | Same models, adds JSON endpoints when needed |

---

### 7-day solo dev plan

| Day | Task |
|---|---|
| 1 | Create Django project, Postgres DB, three models (`FestivalOccurrence`, `Plan`, `PlanFestival`) |
| 2 | Use Django Admin to enter 20–30 seed festivals (realistic Toronto-area spread across months) |
| 3 | Build `/api/festivals/` with filter params (radius, month, genre, major/minor) |
| 4 | Build `/api/plan/` endpoints (add / lock / remove) |
| 5 | Basic UI: filter inputs + suggestions list + "Add to plan" button |
| 6 | Calendar view of the plan (month grid, locked items persist) |
| 7 | Conflict detection + highlighting |

---

### Seed data notes

- Use a **controlled genre list**: EDM, Hip-hop, Rock/Indie, Pop, Jazz, Classical, Folk/Country, Mixed, Other — avoid free-text.
- Every festival **must** have `start_date`, `end_date`, `lat`, `lng` (even if `end_date = start_date`).
- Use a unique slug (`veld-music-festival-2026`) to avoid duplicates.
- Label the dataset clearly: *"Seed dataset — Toronto MVP, manually curated."*

---

### What to add after MVP works

- Circle/group planning (shared plan, per-person `going/maybe/no` status)
- "Review out-of-scope" view for locked festivals that drifted outside filters
- Real external data source (API or scrape) behind the same filter interface
- Travel conflict detection (same weekend, distance > 200 km)
- PostGIS for true geospatial radius queries

---

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


