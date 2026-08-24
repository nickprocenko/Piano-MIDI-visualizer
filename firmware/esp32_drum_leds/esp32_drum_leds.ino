// ============================================================================
//  Drum Kit LED Bridge — one WS2812B ring per drum, driven from the browser
// ============================================================================
//
//  Companion to the "Drum LEDs" tab in docs/index.html. Independent of
//  esp32_fastled_bridge.ino (the piano strip bridge) — you can run both on two
//  boards at the same time.
//
//  WIRING
//    One data pin per drum, listed in STRIP_PINS below. Each drum's ring is a
//    plain WS2812B strip: 5V, GND, DIN. Slot 0 is the first entry in the table,
//    slot 1 the second, and so on — those slot numbers are what you type into
//    the "Strip" field for each pad in the app.
//
//    Put a 300-470 Ω resistor in series with each data line at the board end and
//    a 1000 µF capacitor across 5V/GND at each drum. Power the strips from a
//    dedicated 5V supply, not the ESP32's USB rail, and tie all grounds together.
//
//  BOARD SUPPORT — READ THIS BEFORE WIRING 8 DRUMS
//    FastLED drives WS2812B through the RMT peripheral, one channel per strip:
//      ESP32 (classic)  8 RMT channels → up to 8 strips.
//      ESP32-S3         4 RMT channels → 4 strips out of the box.
//      ESP32-C3         2 RMT channels → 2 strips.
//    On an S3 or C3, either keep the strip count at or below that limit, or
//    daisy-chain several drums onto one pin and give them adjacent slots.
//    (FastLED 3.7+ can multiplex more strips via its I2S driver, but that is not
//    enabled here — this sketch stays on the plain, predictable path.)
//
//  PROTOCOL (see docs/index.html → DrumLedEngine)
//    A5 5A <type> <len_lo> <len_hi> <payload...> <crc8>
//    len counts payload bytes only; CRC-8/ATM (poly 0x07) covers type+len+payload.
//    The parser is length-driven, so 0xA5 0x5A appearing inside pixel data is
//    just data. A failed CRC costs one frame: we drop it and rescan for the magic.
//
//      0x01 CFG    nStrips, then per strip { slot:u8, len:u16 }, then power_ma:u16
//      0x02 FRAME  seq:u8, then every configured strip's pixels concatenated,
//                  in the same order CFG listed them, r,g,b per pixel
//      0x03 PING   → replies with an ASCII banner
//      0x04 IDENT  slot:u8 — sweeps a single pixel along that strip so you can
//                  see which physical drum is on which output
//      0x05 BLANK  everything off
//
//    Until a valid CFG arrives the device prints DKNEEDCFG once a second; the app
//    watches for that and answers with a fresh CFG, so a mid-gig reset recovers
//    on its own.
//
//  FLASHING
//    Arduino IDE → install "FastLED" (3.6+). Select your ESP32 board.
//    Serial monitor at 921600 to read the banner.
// ============================================================================

#include <FastLED.h>

// ---------------- User config ----------------
#define MAX_STRIPS          8      // keep in step with DRUM_MAX_STRIPS in index.html
#define MAX_LEDS_PER_STRIP  128    // keep in step with DRUM_MAX_LEDS in index.html
#define SERIAL_BAUD         921600
#define GLOBAL_BRIGHTNESS   200    // 0-255; the app's Brightness % scales on top
#define POWER_VOLTS         5
#define MIN_SHOW_INTERVAL_MS 16    // ~60 fps ceiling on FastLED.show()
#define FRAME_TIMEOUT_MS    2000   // no frames for this long → fade out
#define FADE_OUT_MS         500

// Slot → GPIO. Slot 0 is the first entry. Edit to match your wiring; the pins
// must be output-capable and must not be strapping/flash pins for your board.
static const uint8_t STRIP_PINS[MAX_STRIPS] = { 18, 19, 21, 22, 23, 25, 26, 27 };

// ---------------- Protocol constants ----------------
static const uint8_t MAGIC0 = 0xA5, MAGIC1 = 0x5A;
enum : uint8_t { PKT_CFG = 0x01, PKT_FRAME = 0x02, PKT_PING = 0x03,
                 PKT_IDENT = 0x04, PKT_BLANK = 0x05 };
#define MAX_PAYLOAD (1 + MAX_STRIPS * MAX_LEDS_PER_STRIP * 3)

CRGB leds[MAX_STRIPS][MAX_LEDS_PER_STRIP];

// Runtime geometry, filled in by CFG.
static uint16_t stripLen[MAX_STRIPS];      // 0 = this output is not in use
static uint8_t  frameOrder[MAX_STRIPS];    // slot index of each FRAME segment
static uint8_t  frameStrips = 0;           // how many segments a FRAME carries
static uint32_t expectedFrameBytes = 0;
static bool     haveConfig = false;

static uint8_t  payload[MAX_PAYLOAD];
static uint32_t lastShowMs = 0, lastFrameMs = 0, lastNagMs = 0;
static bool     dirty = false, fadedOut = false;

// IDENT sweep state — runs locally so you can identify strips with nothing
// streaming from the browser.
static int8_t   identStrip = -1;
static uint16_t identPos = 0;
static uint32_t identMs = 0;

// ---------------- CRC-8/ATM, poly 0x07 ----------------
static uint8_t crc8(const uint8_t* d, size_t n) {
  uint8_t c = 0;
  while (n--) {
    c ^= *d++;
    for (uint8_t b = 0; b < 8; b++) c = (c & 0x80) ? (uint8_t)((c << 1) ^ 0x07) : (uint8_t)(c << 1);
  }
  return c;
}

// ---------------- FastLED strip registration ----------------
// addLeds() takes the data pin as a *template* parameter, so it must be a
// compile-time constant. That is why STRIP_PINS is a fixed table and the app
// addresses outputs by slot number rather than sending GPIO numbers: this switch
// is the only place a runtime index becomes a compile-time pin.
template <uint8_t PIN>
static void addStripT(CRGB* arr) {
  FastLED.addLeds<WS2812B, PIN, GRB>(arr, MAX_LEDS_PER_STRIP);
}

static void addStripByPin(uint8_t pin, CRGB* arr) {
  switch (pin) {
    case  2: addStripT< 2>(arr); break;
    case  4: addStripT< 4>(arr); break;
    case  5: addStripT< 5>(arr); break;
    case 12: addStripT<12>(arr); break;
    case 13: addStripT<13>(arr); break;
    case 14: addStripT<14>(arr); break;
    case 15: addStripT<15>(arr); break;
    case 16: addStripT<16>(arr); break;
    case 17: addStripT<17>(arr); break;
    case 18: addStripT<18>(arr); break;
    case 19: addStripT<19>(arr); break;
    case 21: addStripT<21>(arr); break;
    case 22: addStripT<22>(arr); break;
    case 23: addStripT<23>(arr); break;
    case 25: addStripT<25>(arr); break;
    case 26: addStripT<26>(arr); break;
    case 27: addStripT<27>(arr); break;
    case 32: addStripT<32>(arr); break;
    case 33: addStripT<33>(arr); break;
    default:
      // Pin not in the list above. Add a `case N: addStripT<N>(arr); break;`
      // line for it — the template has to be instantiated for every pin used.
      Serial.print(F("DKERR unsupported pin ")); Serial.println(pin);
      break;
  }
}

static void clearAll() {
  for (uint8_t s = 0; s < MAX_STRIPS; s++) fill_solid(leds[s], MAX_LEDS_PER_STRIP, CRGB::Black);
  dirty = true;
}

// ---------------- Packet handling ----------------
static void handleConfig(const uint8_t* p, uint16_t n) {
  if (n < 1) { Serial.println(F("DKCFG ERR empty")); return; }
  uint8_t count = p[0];
  if (count > MAX_STRIPS) {
    Serial.print(F("DKCFG ERR ")); Serial.print(count);
    Serial.print(F(" strips, this build supports ")); Serial.println(MAX_STRIPS);
    return;
  }
  if (n != (uint16_t)(1 + count * 3 + 2)) {
    Serial.print(F("DKCFG ERR payload ")); Serial.println(n);
    return;
  }

  // Validate everything before touching live state, so a bad CFG cannot leave
  // the kit half-configured and streaming garbage.
  uint16_t lens[MAX_STRIPS];
  uint8_t  slots[MAX_STRIPS];
  uint32_t total = 0;
  for (uint8_t i = 0; i < count; i++) {
    slots[i] = p[1 + i * 3];
    lens[i]  = (uint16_t)p[2 + i * 3] | ((uint16_t)p[3 + i * 3] << 8);
    if (slots[i] >= MAX_STRIPS) {
      Serial.print(F("DKCFG ERR slot ")); Serial.println(slots[i]);
      return;
    }
    if (lens[i] == 0 || lens[i] > MAX_LEDS_PER_STRIP) {
      Serial.print(F("DKCFG ERR len ")); Serial.print(lens[i]);
      Serial.print(F(" on slot ")); Serial.println(slots[i]);
      return;
    }
    total += lens[i];
  }

  for (uint8_t s = 0; s < MAX_STRIPS; s++) stripLen[s] = 0;
  for (uint8_t i = 0; i < count; i++) {
    stripLen[slots[i]] = lens[i];
    frameOrder[i] = slots[i];
  }
  frameStrips = count;
  expectedFrameBytes = 1 + total * 3;   // seq byte + rgb
  haveConfig = true;

  uint16_t ma = (uint16_t)p[1 + count * 3] | ((uint16_t)p[2 + count * 3] << 8);
  FastLED.setMaxPowerInVoltsAndMilliamps(POWER_VOLTS, ma);

  clearAll();
  Serial.print(F("DKCFG OK ")); Serial.print(count);
  Serial.print(' '); Serial.print(total);
  Serial.print(F(" px ")); Serial.print(ma); Serial.println(F(" mA"));
}

static void handleFrame(const uint8_t* p, uint16_t n) {
  if (!haveConfig) { Serial.println(F("DKNEEDCFG")); return; }
  if (n != expectedFrameBytes) {
    Serial.print(F("DKFRAME ERR ")); Serial.print(n);
    Serial.print(F(" expected ")); Serial.println(expectedFrameBytes);
    // Our idea of the geometry disagrees with the sender's. Asking for a fresh
    // CFG is the only way back in sync.
    haveConfig = false;
    Serial.println(F("DKNEEDCFG"));
    return;
  }
  identStrip = -1;               // a real frame ends any identify sweep
  uint32_t o = 1;                // skip seq
  for (uint8_t i = 0; i < frameStrips; i++) {
    uint8_t s = frameOrder[i];
    uint16_t len = stripLen[s];
    for (uint16_t j = 0; j < len; j++) {
      leds[s][j] = CRGB(p[o], p[o + 1], p[o + 2]);
      o += 3;
    }
    for (uint16_t j = len; j < MAX_LEDS_PER_STRIP; j++) leds[s][j] = CRGB::Black;
  }
  lastFrameMs = millis();
  fadedOut = false;
  dirty = true;
}

static void handlePacket(uint8_t type, const uint8_t* p, uint16_t n) {
  switch (type) {
    case PKT_CFG:   handleConfig(p, n); break;
    case PKT_FRAME: handleFrame(p, n);  break;
    case PKT_BLANK: clearAll();         break;
    case PKT_IDENT:
      if (n >= 1 && p[0] < MAX_STRIPS) {
        identStrip = (int8_t)p[0];
        identPos = 0;
        identMs = millis();
        Serial.print(F("DKIDENT slot ")); Serial.print(p[0]);
        Serial.print(F(" pin ")); Serial.println(STRIP_PINS[p[0]]);
      }
      break;
    case PKT_PING:
      Serial.print(F("DKPONG v1 strips=")); Serial.print(MAX_STRIPS);
      Serial.print(F(" maxleds=")); Serial.print(MAX_LEDS_PER_STRIP);
      Serial.print(F(" cfg=")); Serial.print(haveConfig ? 1 : 0);
      Serial.print(F(" heap=")); Serial.println(ESP.getFreeHeap());
      break;
    default:
      Serial.print(F("DKERR unknown packet 0x")); Serial.println(type, HEX);
      break;
  }
}

// ---------------- Byte-wise frame parser ----------------
// Length-driven: once the header is in, we consume exactly len bytes and check
// the CRC. Only a CRC failure sends us back to hunting for the magic pair, so
// pixel data that happens to contain A5 5A is never mistaken for a header.
enum ParseState { WAIT_M0, WAIT_M1, GET_TYPE, GET_LEN_LO, GET_LEN_HI, GET_PAYLOAD, GET_CRC };
static ParseState pstate = WAIT_M0;
static uint8_t  pType = 0;
static uint16_t pLen = 0, pGot = 0;

static void parseByte(uint8_t c) {
  switch (pstate) {
    case WAIT_M0:
      if (c == MAGIC0) pstate = WAIT_M1;
      break;
    case WAIT_M1:
      // A5 A5 5A is a valid start: stay armed rather than dropping the second A5.
      if (c == MAGIC1) pstate = GET_TYPE;
      else if (c != MAGIC0) pstate = WAIT_M0;
      break;
    case GET_TYPE:   pType = c; pstate = GET_LEN_LO; break;
    case GET_LEN_LO: pLen = c;  pstate = GET_LEN_HI; break;
    case GET_LEN_HI:
      pLen |= ((uint16_t)c << 8);
      if (pLen > MAX_PAYLOAD) {
        Serial.print(F("DKERR oversize payload ")); Serial.println(pLen);
        pstate = WAIT_M0;
      } else {
        pGot = 0;
        pstate = pLen ? GET_PAYLOAD : GET_CRC;
      }
      break;
    case GET_PAYLOAD:
      payload[pGot++] = c;
      if (pGot >= pLen) pstate = GET_CRC;
      break;
    case GET_CRC: {
      uint8_t hdr[3] = { pType, (uint8_t)(pLen & 0xFF), (uint8_t)(pLen >> 8) };
      uint8_t want = crc8(hdr, 3);
      // Continue the CRC across the payload without copying: recompute from the
      // running value by feeding the payload bytes in.
      for (uint16_t i = 0; i < pLen; i++) {
        want ^= payload[i];
        for (uint8_t b = 0; b < 8; b++) want = (want & 0x80) ? (uint8_t)((want << 1) ^ 0x07) : (uint8_t)(want << 1);
      }
      if (want == c) handlePacket(pType, payload, pLen);
      else Serial.println(F("DKERR crc"));
      pstate = WAIT_M0;
      break;
    }
  }
}

// ---------------- Identify sweep ----------------
static void tickIdent() {
  if (identStrip < 0) return;
  uint32_t now = millis();
  if (now - identMs < 25) return;
  identMs = now;
  uint16_t len = stripLen[identStrip] ? stripLen[identStrip] : MAX_LEDS_PER_STRIP;
  fill_solid(leds[identStrip], MAX_LEDS_PER_STRIP, CRGB::Black);
  leds[identStrip][identPos % len] = CRGB::White;
  if (identPos) leds[identStrip][(identPos - 1) % len] = CRGB(60, 60, 60);
  identPos++;
  if (identPos > len * 2) {                       // two laps, then stop
    fill_solid(leds[identStrip], MAX_LEDS_PER_STRIP, CRGB::Black);
    identStrip = -1;
  }
  dirty = true;
}

// ---------------- Watchdog ----------------
// If the browser tab closes or USB is unplugged mid-song the last frame would
// otherwise stay lit forever. Fade out instead of cutting to black, so a brief
// stall does not read as a glitch.
static void tickWatchdog() {
  if (!haveConfig || fadedOut || identStrip >= 0) return;
  uint32_t now = millis();
  if (!lastFrameMs || now - lastFrameMs < FRAME_TIMEOUT_MS) return;
  uint32_t into = now - lastFrameMs - FRAME_TIMEOUT_MS;
  if (into >= FADE_OUT_MS) {
    clearAll();
    fadedOut = true;
    Serial.println(F("DKIDLE faded out"));
    return;
  }
  // ~30 steps across the fade window
  static uint32_t lastFade = 0;
  if (now - lastFade < FADE_OUT_MS / 30) return;
  lastFade = now;
  for (uint8_t s = 0; s < MAX_STRIPS; s++)
    if (stripLen[s]) fadeToBlackBy(leds[s], stripLen[s], 24);
  dirty = true;
}

void setup() {
  // Must come before begin(): at 921600 the default 256-byte RX buffer overruns
  // inside a single frame and you get a stream of CRC errors.
  Serial.setRxBufferSize(4096);
  Serial.begin(SERIAL_BAUD);

  for (uint8_t s = 0; s < MAX_STRIPS; s++) addStripByPin(STRIP_PINS[s], leds[s]);
  FastLED.setBrightness(GLOBAL_BRIGHTNESS);
  FastLED.setMaxPowerInVoltsAndMilliamps(POWER_VOLTS, 2000);
  // Temporal dithering fights us at high frame rates — it modulates brightness
  // between show() calls, which reads as flicker on a fast-decaying drum hit.
  FastLED.setDither(0);
  clearAll();
  FastLED.show();

  delay(300);
  Serial.println();
  Serial.println(F("=== Drum-LED-Bridge v1 ==="));
  Serial.print(F("strips=")); Serial.print(MAX_STRIPS);
  Serial.print(F(" maxleds=")); Serial.print(MAX_LEDS_PER_STRIP);
  Serial.print(F(" baud=")); Serial.println(SERIAL_BAUD);
  Serial.print(F("pins="));
  for (uint8_t s = 0; s < MAX_STRIPS; s++) { Serial.print(STRIP_PINS[s]); Serial.print(s + 1 < MAX_STRIPS ? ',' : '\n'); }
  Serial.println(F("DKNEEDCFG"));
}

void loop() {
  while (Serial.available() > 0) parseByte((uint8_t)Serial.read());

  tickIdent();
  tickWatchdog();

  // Nag for a config so the app can answer without the user doing anything.
  uint32_t now = millis();
  if (!haveConfig && now - lastNagMs > 1000) {
    lastNagMs = now;
    Serial.println(F("DKNEEDCFG"));
  }

  if (dirty && now - lastShowMs >= MIN_SHOW_INTERVAL_MS) {
    lastShowMs = now;
    dirty = false;
    FastLED.show();
  }
}
