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
// Strip 1: SK9822 (SPI — data + clock)
#define DATA_PIN    33
#define CLOCK_PIN   21
#define LED_TYPE    SK9822
#define COLOR_ORDER BGR

// Strip 2: WS2812B (single-wire via RMT)
// Change DATA_PIN_2 to whichever GPIO you wire the WS2812B data line to.
#define DATA_PIN_2  18
#define LED_TYPE_2  WS2812B
#define COLOR_ORDER_2 GRB

#define LED_COUNT   177
#define BRIGHTNESS  128

#define SERIAL_BAUD 115200
#define MAX_LINE_LEN 4096
#define ENABLE_BLE 1

// BLE UART-style write characteristic (Nordic UART UUIDs)
static const char* BLE_DEVICE_NAME = "Piano-LED-Bridge";
static const char* BLE_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
static const char* BLE_WRITE_UUID   = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E";

CRGB leds[LED_COUNT];   // SK9822 strip
CRGB leds2[LED_COUNT];  // WS2812B strip (mirrors strip 1)
char lineBuf[MAX_LINE_LEN];
size_t lineLen = 0;

#if ENABLE_BLE && HAS_NIMBLE
NimBLEServer* bleServer = nullptr;
#endif

void clearAll() {
  fill_solid(leds,  LED_COUNT, CRGB::Black);
  fill_solid(leds2, LED_COUNT, CRGB::Black);
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

    leds[i]  = CRGB((uint8_t)r, (uint8_t)g, (uint8_t)b);
    leds2[i] = leds[i];  // mirror to WS2812B strip
  }

  // If sender count is smaller, clear remainder.
  for (int i = count; i < LED_COUNT; ++i) {
    leds[i]  = CRGB::Black;
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
    clearAll();
    NimBLEDevice::getAdvertising()->start();
  }
};

ServerCallbacks serverCallbacks;

class RxCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
    (void)connInfo;
    std::string value = pCharacteristic->getValue();
    for (size_t i = 0; i < value.size(); ++i) {
      processIncomingByte(value[i]);
    }
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
  FastLED.addLeds<LED_TYPE,   DATA_PIN,  CLOCK_PIN, COLOR_ORDER >(leds,  LED_COUNT);
  FastLED.addLeds<LED_TYPE_2, DATA_PIN_2, COLOR_ORDER_2          >(leds2, LED_COUNT);
  FastLED.setBrightness(BRIGHTNESS);
  clearAll();

  delay(500);
  Serial.begin(SERIAL_BAUD);
  Serial.println("=== Piano-LED-Bridge booting ===");
  Serial.print("HAS_NIMBLE = "); Serial.println(HAS_NIMBLE);
  Serial.println("FastLED ready");

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
  while (Serial.available() > 0) {
    processIncomingByte((char)Serial.read());
  }
}
