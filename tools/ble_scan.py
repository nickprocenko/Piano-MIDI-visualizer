"""Quick BLE scanner — run to find Piano-LED-Bridge address after flashing."""
import asyncio
from bleak import BleakScanner, BleakClient

SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
CHAR_UUID    = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TARGET_NAME  = "Piano-LED-Bridge"

TEST_FRAME   = b"LEDS,3,255,0,0,0,255,0,0,0,255\n"  # 3 LEDs: red, green, blue


FALLBACK_ADDRESS = "84:FC:E6:50:A6:F9"  # known address from initial scan
                   

async def scan() -> str | None:
    print("Scanning 6 s...")
    devices = await BleakScanner.discover(timeout=6.0, return_adv=True)
    found = None
    for address, (d, adv) in devices.items():
        name = d.name if d.name else "(unnamed)"
        # Match by name OR by service UUID in advertisement (more reliable on Windows)
        adv_uuids = [str(u).lower() for u in (adv.service_uuids or [])]
        by_name = TARGET_NAME in name
        by_uuid = SERVICE_UUID.lower() in adv_uuids
        marker = " <-- TARGET (name)" if by_name else (" <-- TARGET (uuid)" if by_uuid else "")
        print(f"  {name:40s}  {address}{marker}")
        if by_name or by_uuid:
            found = address

    if not found and FALLBACK_ADDRESS.upper() in {a.upper() for a in devices}:
        print(f"  (falling back to known address {FALLBACK_ADDRESS})")
        found = FALLBACK_ADDRESS

    return found


async def test_connection(address: str) -> None:
    print(f"\nConnecting to {address} ...")
    try:
        async with BleakClient(address, timeout=10.0) as client:
            if not client.is_connected:
                print("Failed to connect.")
                return
            print("Connected!")

            svcs = client.services
            has_service = any(SERVICE_UUID.lower() in str(s.uuid).lower() for s in svcs)
            has_char    = any(CHAR_UUID.lower() in str(c.uuid).lower()
                              for s in svcs for c in s.characteristics)

            print(f"  LED service present : {has_service}")
            print(f"  Write char present  : {has_char}")

            if has_char:
                print(f"  Sending test frame  : {TEST_FRAME}")
                await client.write_gatt_char(CHAR_UUID, TEST_FRAME, response=False)
                print("  Sent OK — first 3 LEDs should show red / green / blue")
            else:
                print("  Write characteristic not found — check firmware UUID config")
    except Exception as e:
        print(f"Connection error: {e}")


async def main() -> None:
    address = await scan()
    if address:
        await test_connection(address)
    else:
        print(f"\n'{TARGET_NAME}' not found. Make sure the ESP32 is powered and flashed.")


asyncio.run(main())
