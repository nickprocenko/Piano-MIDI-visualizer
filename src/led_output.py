"""ESP32 LED output for piano note activity via serial.

Protocol
--------
Each frame is sent as one ASCII line:

    LEDS,<led_count>,r0,g0,b0,r1,g1,b1,...\n
Example for 4 LEDs:

    LEDS,4,0,0,0,0,220,220,0,220,220,0,0,0\n
Default mapping for an 88-key keyboard and 176 LEDs is 2 LEDs per key.
A pressed note lights both mapped LEDs with the configured active color.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import threading
from typing import Optional

from src import config as cfg

try:
    import serial  # type: ignore
    _SERIAL_AVAILABLE = True
except Exception:
    serial = None  # type: ignore
    _SERIAL_AVAILABLE = False

try:
    from bleak import BleakClient, BleakScanner  # type: ignore
    _BLE_AVAILABLE = True
except Exception:
    BleakClient = None  # type: ignore
    BleakScanner = None  # type: ignore
    _BLE_AVAILABLE = False

PIANO_FIRST_NOTE = 21
PIANO_LAST_NOTE = 108


@dataclass
class LedOutputConfig:
    enabled: bool
    transport: str
    port: str
    baudrate: int
    ble_address: str
    ble_device_name: str
    ble_service_uuid: str
    ble_char_uuid: str
    ble_write_with_response: bool
    ble_chunk_size: int
    led_count: int
    mirror_per_key: int
    fps_limit: int
    active_r: int
    active_g: int
    active_b: int


class _BleLedSender:
    """Minimal BLE writer for newline-terminated LED frames."""

    def __init__(
        self,
        address: str,
        device_name: str,
        service_uuid: str,
        char_uuid: str,
        write_with_response: bool,
        chunk_size: int,
        reconnect_sec: float = 2.0,
    ) -> None:
        self._address = address
        self._device_name = (device_name or "").strip()
        self._service_uuid = (service_uuid or "").strip()
        self._char_uuid = char_uuid
        self._write_with_response = write_with_response
        self._chunk_size = max(20, min(512, int(chunk_size)))
        self._reconnect_sec = max(0.2, float(reconnect_sec))

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected_event = threading.Event()
        self._connected = False
        self._client: Optional[object] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self, timeout_sec: float = 8.0) -> bool:
        if not _BLE_AVAILABLE or BleakClient is None or not self._char_uuid:
            return False

        resolved = self._resolve_address(timeout_sec=min(6.0, timeout_sec))
        if not resolved:
            return False
        self._address = resolved

        if self._thread is not None and self._thread.is_alive():
            return self._connected

        self._stop.clear()
        self._connected_event.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        return self._connected_event.wait(timeout=max(0.5, timeout_sec))

    def _resolve_address(self, timeout_sec: float) -> str:
        # Prefer live discovery by service UUID / device name so stale saved
        # addresses in config do not block BLE connection.
        discovered = self._discover_address(timeout_sec)
        if discovered:
            return discovered
        return (self._address or "").strip()

    def _discover_address(self, timeout_sec: float) -> str:
        if BleakScanner is None:
            return ""

        async def _scan() -> str:
            try:
                devices = await BleakScanner.discover(timeout=max(2.0, float(timeout_sec)), return_adv=True)
            except Exception:
                return ""

            wanted_name = self._device_name.lower()
            wanted_service = self._service_uuid.lower()

            for address, (dev, adv) in devices.items():
                name = (getattr(dev, "name", "") or "").lower()
                adv_uuids = [str(u).lower() for u in (getattr(adv, "service_uuids", None) or [])]
                by_name = bool(wanted_name) and wanted_name in name
                by_service = bool(wanted_service) and wanted_service in adv_uuids
                if by_name or by_service:
                    return str(address)
            return ""

        try:
            return str(asyncio.run(_scan()) or "")
        except RuntimeError:
            # If an event loop is already active in this thread, run scan in a
            # private loop to avoid breaking the caller.
            loop = asyncio.new_event_loop()
            try:
                return str(loop.run_until_complete(_scan()) or "")
            except Exception:
                return ""
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
        except Exception:
            return ""

    def close(self) -> None:
        self._stop.set()
        self._connected = False
        self._connected_event.clear()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._loop = None
        self._client = None

    def send(self, data: bytes, timeout_sec: float = 2.5) -> bool:
        loop = self._loop
        if not self._connected or loop is None:
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(self._send_chunks(data), loop)
            return bool(future.result(timeout=max(0.2, timeout_sec)))
        except Exception:
            return False

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        finally:
            try:
                loop.stop()
            except Exception:
                pass
            loop.close()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                assert BleakClient is not None
                async with BleakClient(self._address, timeout=10.0) as client:
                    self._client = client
                    self._connected = bool(client.is_connected)
                    if self._connected:
                        self._connected_event.set()

                    while not self._stop.is_set() and client.is_connected:
                        await asyncio.sleep(0.15)
            except Exception:
                pass
            finally:
                self._client = None
                self._connected = False

            if self._stop.is_set():
                break
            await asyncio.sleep(self._reconnect_sec)

    async def _send_chunks(self, data: bytes) -> bool:
        client = self._client
        if client is None or not self._connected:
            return False

        try:
            for i in range(0, len(data), self._chunk_size):
                chunk = data[i:i + self._chunk_size]
                await client.write_gatt_char(
                    self._char_uuid,
                    chunk,
                    response=self._write_with_response,
                )
            return True
        except Exception:
            self._connected = False
            return False


class LedOutput:
    """Serial LED sender that mirrors active piano notes to an LED strip."""

    def __init__(self, config: LedOutputConfig) -> None:
        self._cfg = config
        self._ser: Optional[object] = None
        self._ble: Optional[_BleLedSender] = None
        self._connected = False
        self._send_accum_ms = 0
        self._last_frame: bytes = b""

    @property
    def connected(self) -> bool:
        if self._cfg.transport == "ble":
            return self._ble is not None and bool(self._ble.connected)
        return self._connected

    def send_raw(self, data: bytes) -> bool:
        """Send a pre-built raw frame, bypassing the FPS rate limiter."""
        if not self.connected:
            return False
        return self._send_frame(data)

    def set_active_color(self, r: int, g: int, b: int) -> None:
        self._cfg.active_r = max(0, min(255, int(r)))
        self._cfg.active_g = max(0, min(255, int(g)))
        self._cfg.active_b = max(0, min(255, int(b)))
        self._last_frame = b""

        self._last_frame = b""

    @staticmethod
    def from_config() -> "LedOutput":
        full = cfg.load()
        data = full.get("led_output", {})
        note_style = full.get("note_style", {})
        # Config may be either legacy flat note_style or per-channel note_style.
        if isinstance(note_style, dict) and "1" in note_style and isinstance(note_style.get("1"), dict):
            note_style_default = note_style.get("1", {})
        else:
            note_style_default = note_style if isinstance(note_style, dict) else {}
        transport = str(data.get("transport", "serial")).strip().lower()
        if transport not in {"serial", "ble"}:
            transport = "serial"

        conf = LedOutputConfig(
            enabled=bool(data.get("enabled", False)),
            transport=transport,
            port=str(data.get("port", "COM5")),
            baudrate=int(data.get("baudrate", 115200)),
            ble_address=str(data.get("ble_address", "")).strip(),
            ble_device_name=str(data.get("ble_device_name", "Piano-LED-Bridge")).strip(),
            ble_service_uuid=str(data.get("ble_service_uuid", "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")).strip(),
            ble_char_uuid=str(data.get("ble_char_uuid", "6E400002-B5A3-F393-E0A9-E50E24DCCA9E")).strip(),
            ble_write_with_response=bool(data.get("ble_write_with_response", False)),
            ble_chunk_size=max(20, min(512, int(data.get("ble_chunk_size", 180)))),
            led_count=max(1, int(data.get("led_count", 176))),
            mirror_per_key=max(1, int(data.get("mirror_per_key", 2))),
            fps_limit=max(1, int(data.get("fps_limit", 30))),
            # Active colour is driven by note colour — read from note_style, not led_output
            active_r=max(0, min(255, int(note_style_default.get("color_r", 0)))),
            active_g=max(0, min(255, int(note_style_default.get("color_g", 230)))),
            active_b=max(0, min(255, int(note_style_default.get("color_b", 230)))),
        )
        return LedOutput(conf)

    def connect(self) -> bool:
        if not self._cfg.enabled:
            self._connected = False
            return False

        if self._cfg.transport == "ble":
            self._ble = _BleLedSender(
                address=self._cfg.ble_address,
                device_name=self._cfg.ble_device_name,
                service_uuid=self._cfg.ble_service_uuid,
                char_uuid=self._cfg.ble_char_uuid,
                write_with_response=self._cfg.ble_write_with_response,
                chunk_size=self._cfg.ble_chunk_size,
            )
            self._connected = self._ble.start(timeout_sec=8.0)
            # Keep the BLE sender alive even if initial wait times out.
            # Its internal reconnect loop can still recover shortly after.
            return self._connected

        if not _SERIAL_AVAILABLE or serial is None:
            self._connected = False
            return False

        try:
            self._ser = serial.Serial(self._cfg.port, self._cfg.baudrate, timeout=0)
            self._connected = True
            return True
        except Exception:
            self._ser = None
            self._connected = False
            return False

    def close(self) -> None:
        if self._ble is not None:
            try:
                self._ble.close()
            except Exception:
                pass
        self._ble = None

        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None
        self._connected = False
        self._last_frame = b""
        self._send_accum_ms = 0

    def update(
        self,
        active_notes: set[int],
        dt_ms: int,
        note_channels: dict[int, int] | None = None,
        channel_colors: dict[str, dict[str, int]] | None = None,
        note_color_overrides: dict[int, dict[str, int]] | None = None,
    ) -> None:
        """Rate-limited update; sends only when frame content changes."""
        if self._cfg.transport == "ble":
            # BLE sender owns reconnect loop internally; avoid forcing hard-close
            # on transient drops so it can recover in the background.
            if self._ble is None or not self._ble.connected:
                return
        elif not self._connected:
            return
        elif self._ser is None:
            self._connected = False
            return

        self._send_accum_ms += dt_ms
        interval_ms = max(1, int(1000 / self._cfg.fps_limit))
        if self._send_accum_ms < interval_ms:
            return
        self._send_accum_ms = 0

        frame = self._build_frame(
            active_notes,
            note_channels=note_channels,
            channel_colors=channel_colors,
            note_color_overrides=note_color_overrides,
        )
        if frame == self._last_frame:
            return

        if self._send_frame(frame):
            self._last_frame = frame
        else:
            if self._cfg.transport == "ble":
                # Keep BLE worker alive; it will reconnect on its own.
                self._last_frame = b""
            else:
                self.close()

    def _send_frame(self, frame: bytes) -> bool:
        if self._cfg.transport == "ble":
            if self._ble is None:
                return False
            return self._ble.send(frame)

        if self._ser is None:
            return False
        try:
            self._ser.write(frame)
            return True
        except Exception:
            return False

    def _build_frame(
        self,
        active_notes: set[int],
        note_channels: dict[int, int] | None = None,
        channel_colors: dict[str, dict[str, int]] | None = None,
        note_color_overrides: dict[int, dict[str, int]] | None = None,
    ) -> bytes:
        led_count = self._cfg.led_count
        leds = [(0, 0, 0)] * led_count

        for note in active_notes:
            if note < PIANO_FIRST_NOTE or note > PIANO_LAST_NOTE:
                continue
            key_index = note - PIANO_FIRST_NOTE
            base = key_index * self._cfg.mirror_per_key
            color = self._resolve_note_color(
                note,
                note_channels=note_channels,
                channel_colors=channel_colors,
                note_color_overrides=note_color_overrides,
            )
            for i in range(self._cfg.mirror_per_key):
                led_idx = base + i
                if 0 <= led_idx < led_count:
                    leds[led_idx] = color

        flat = [str(led_count)]
        for r, g, b in leds:
            flat.append(str(r))
            flat.append(str(g))
            flat.append(str(b))
        return ("LEDS," + ",".join(flat) + "\n").encode("ascii")

    def _resolve_note_color(
        self,
        note: int,
        note_channels: dict[int, int] | None,
        channel_colors: dict[str, dict[str, int]] | None,
        note_color_overrides: dict[int, dict[str, int]] | None,
    ) -> tuple[int, int, int]:
        if note_color_overrides is not None:
            override = note_color_overrides.get(note)
            if isinstance(override, dict):
                return (
                    max(0, min(255, int(override.get("color_r", self._cfg.active_r)))),
                    max(0, min(255, int(override.get("color_g", self._cfg.active_g)))),
                    max(0, min(255, int(override.get("color_b", self._cfg.active_b)))),
                )

        if note_channels is None or channel_colors is None:
            return (self._cfg.active_r, self._cfg.active_g, self._cfg.active_b)

        channel = int(note_channels.get(note, 1))
        ch_key = str(max(1, min(16, channel)))
        colour = channel_colors.get(ch_key)
        if not isinstance(colour, dict):
            return (self._cfg.active_r, self._cfg.active_g, self._cfg.active_b)

        return (
            max(0, min(255, int(colour.get("color_r", self._cfg.active_r)))),
            max(0, min(255, int(colour.get("color_g", self._cfg.active_g)))),
            max(0, min(255, int(colour.get("color_b", self._cfg.active_b)))),
        )
