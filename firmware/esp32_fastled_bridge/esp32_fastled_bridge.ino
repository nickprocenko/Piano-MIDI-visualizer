#include <FastLED.h>
#include <string.h>

// Fix for arduino-esp32 >= 3.3.7: core now calls btInUse() before startup
// to decide whether to reserve BT controller memory. NimBLE-Arduino doesn't
// register with this check, so memory gets freed before NimBLE::init() runs
// → TLSF assert / Guru Meditation crash. This one line prevents that.
extern "C" bool btInUse(void) { return true; }

#include <NimBLEDevice.h>
#define HAS_NIMBLE 1

// ---------------- User Config ----------------
#define DATA_PIN    33
#define CLOCK_PIN   21
#define LED_TYPE    SK9822
#define COLOR_ORDER BGR
#define LED_COUNT   177
#define BRIGHTNESS  128

// WS2812B second strip (mirrored). FastLED uses RMT on ESP32-S3 for WS2812B
// so BLE radio interrupts cannot corrupt its output.
#define DATA_PIN_2   18
#define LED_COUNT_2  144         // 1m 144-pixel WS2812B strip

#define SERIAL_BAUD 115200
#define MAX_LINE_LEN 4096
#define ENABLE_BLE 1

// BLE UART-style write characteristic (Nordic UART UUIDs)
static const char* BLE_DEVICE_NAME = "Piano-LED-Bridge";
static const char* BLE_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
static const char* BLE_WRITE_UUID   = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E";

CRGB leds[LED_COUNT];
CRGB leds2[LED_COUNT_2];
char lineBuf[MAX_LINE_LEN];
size_t lineLen = 0;

// Ring buffer for bytes arriving from the BLE callback (NimBLE FreeRTOS task,
// Core 0). loop() (Core 1) drains it — FastLED.show() only ever runs in loop().
static char           blePipe[MAX_LINE_LEN * 2];
static volatile size_t bpHead = 0;
static size_t          bpTail = 0;  // only written by loop()
static portMUX_TYPE    bleMux = portMUX_INITIALIZER_UNLOCKED;

#if ENABLE_BLE && HAS_NIMBLE
NimBLEServer* bleServer = nullptr;
#endif

void clearAll() {
  fill_solid(leds,  LED_COUNT,  CRGB::Black);
  fill_solid(leds2, LED_COUNT_2, CRGB::Black);
  FastLED.show();
}

// Parse: LEDS,<led_count>,r0,g0,b0,r1,g1,b1,...
bool applyFrame(char* line) {
  char* tok = strtok(line, ",");
  if (tok == nullptr || strcmp(tok, "LEDS") != 0) {
    return false;
  }

  tok = strtok(nullptr, ",");
  if (tok == nullptr) {
    return false;
  }

  int incomingCount = atoi(tok);
  int count = incomingCount < LED_COUNT ? incomingCount : LED_COUNT;
  if (count <= 0) {
    return false;
  }

  for (int i = 0; i < count; ++i) {
    char* rs = strtok(nullptr, ",");
    char* gs = strtok(nullptr, ",");
    char* bs = strtok(nullptr, ",");
    if (rs == nullptr || gs == nullptr || bs == nullptr) {
      return false;
    }

    int r = atoi(rs);
    int g = atoi(gs);
    int b = atoi(bs);

    if (r < 0) r = 0; if (r > 255) r = 255;
    if (g < 0) g = 0; if (g > 255) g = 255;
    if (b < 0) b = 0; if (b > 255) b = 255;

    leds[i] = CRGB((uint8_t)r, (uint8_t)g, (uint8_t)b);
  }

  // If sender count is smaller, clear remainder.
  for (int i = count; i < LED_COUNT; ++i) {
    leds[i] = CRGB::Black;
  }

  // Mirror to WS2812B strip (FastLED handles BGR vs GRB per-strip at show time).
  int mirrorCount = min((int)LED_COUNT, (int)LED_COUNT_2);
  memcpy(leds2, leds, sizeof(CRGB) * mirrorCount);
  for (int i = mirrorCount; i < LED_COUNT_2; ++i) {
    leds2[i] = CRGB::Black;
  }

  FastLED.show();
  return true;
}

void processIncomingByte(char c) {
  if (c == '\n') {
    lineBuf[lineLen] = '\0';
    if (lineLen > 0) {
      applyFrame(lineBuf);
    }
    lineLen = 0;
    return;
  }

  if (c == '\r') {
    return;
  }

  if (lineLen < (MAX_LINE_LEN - 1)) {
    lineBuf[lineLen++] = c;
  } else {
    // Overflow: drop this line and wait for next newline.
    lineLen = 0;
  }
}

#if ENABLE_BLE && HAS_NIMBLE
class ServerCallbacks : public NimBLEServerCallbacks {
  void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
    (void)connInfo; (void)reason;
    // Do NOT clear LEDs — a brief signal dropout would flash the strip black.
    // Instead, flush parse state so the first frame after reconnect starts clean.
    portENTER_CRITICAL(&bleMux);
    bpHead = bpTail = 0;  // discard any partial BLE frame in the ring buffer
    portEXIT_CRITICAL(&bleMux);
    lineLen = 0;           // discard partial line buffer
    NimBLEDevice::getAdvertising()->start();
  }
};

ServerCallbacks serverCallbacks;

// onWrite only pushes bytes into the ring buffer — it never touches leds[] or
// calls FastLED.show(). This avoids the race where the NimBLE task (Core 0)
// and the Arduino loop task (Core 1) both write to shared globals simultaneously.
class RxCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
    (void)connInfo;
    std::string value = pCharacteristic->getValue();
    portENTER_CRITICAL(&bleMux);
    for (size_t i = 0; i < value.size(); ++i) {
      char c = value[i];
      size_t next = (bpHead + 1) % sizeof(blePipe);
      if (next != bpTail) {
        blePipe[bpHead] = c;
        bpHead = next;
      }
      // silently drop on overflow — safer than corrupting shared parse state
    }
    portEXIT_CRITICAL(&bleMux);
  }
};

RxCallbacks rxCallbacks;

void setupBleReceiver() {
  NimBLEDevice::init(BLE_DEVICE_NAME);
  bleServer = NimBLEDevice::createServer();
  bleServer->setCallbacks(&serverCallbacks);

  NimBLEService* service = bleServer->createService(BLE_SERVICE_UUID);
  NimBLECharacteristic* rx = service->createCharacteristic(
    BLE_WRITE_UUID,
    NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR
  );
  rx->setCallbacks(&rxCallbacks);

  service->start();

  NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
  advertising->addServiceUUID(BLE_SERVICE_UUID);
  advertising->setName(BLE_DEVICE_NAME);
  advertising->enableScanResponse(true);    // Name in scan response so Windows sees it
  advertising->start();
}
#endif

void setup() {
  // Clear LEDs immediately on boot — before any delay — so a reset wipes
  // whatever noise/state the strip was showing.
  FastLED.addLeds<LED_TYPE, DATA_PIN, CLOCK_PIN, COLOR_ORDER>(leds, LED_COUNT);
  FastLED.addLeds<WS2812B, DATA_PIN_2, GRB>(leds2, LED_COUNT_2);
  FastLED.setBrightness(BRIGHTNESS);
  // Clamp total current draw so the 5V rail doesn't sag and corrupt WS2812B data.
  // Raise the milliamps limit if your PSU can supply more cleanly.
  FastLED.setMaxPowerInVoltsAndMilliamps(5, 2000);
  clearAll();

  delay(500);
  Serial.begin(SERIAL_BAUD);
  Serial.println("=== Piano-LED-Bridge booting ===");
  Serial.print("HAS_NIMBLE = "); Serial.println(HAS_NIMBLE);
  Serial.println("FastLED ready (SK9822 + WS2812B)");

#if ENABLE_BLE
#if HAS_NIMBLE
  setupBleReceiver();
  Serial.println("BLE receiver enabled");
#else
  Serial.println("BLE disabled: install NimBLE-Arduino library");
#endif
#endif
}

void loop() {
  // Drain BLE ring buffer. bpHead is written under bleMux by the NimBLE task;
  // snapshot it once so we don't race on the comparison inside the loop.
  size_t h;
  portENTER_CRITICAL(&bleMux);
  h = bpHead;
  portEXIT_CRITICAL(&bleMux);
  while (bpTail != h) {
    processIncomingByte(blePipe[bpTail]);
    bpTail = (bpTail + 1) % sizeof(blePipe);
  }

  // Drain serial
  while (Serial.available() > 0) {
    processIncomingByte((char)Serial.read());
  }
}
