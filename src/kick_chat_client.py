"""Kick.com chat client for audience LED color control.

Connects to Kick's Pusher-based chat WebSocket and parses !color commands
from viewers into AudienceColorEvent objects, which app.py consumes the
same way it consumes events from AudienceColorClient.

Supported command formats (case-insensitive):
    !color red              <- CSS / common color name
    !color #FF0080          <- 6-digit hex
    !color #F08             <- 3-digit hex shorthand
    !color 255 0 128        <- RGB integers, space-separated
    !color 255,0,128        <- RGB integers, comma-separated

Pusher protocol
---------------
Kick uses Pusher with app-key 32cbd69e4b950bf97679 on us2.
Public chatroom channels need no auth token.
Heartbeat: respond to pusher:ping with pusher:pong.

Chatroom ID lookup
------------------
Fetched once on connect from the public Kick REST API:
    GET https://kick.com/api/v1/channels/{slug}
    -> .chatroom.id
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from src import config as cfg
from src.audience_color_client import AudienceColorEvent

try:
    import websocket  # type: ignore
    _WS_AVAILABLE = True
except Exception:
    websocket = None  # type: ignore
    _WS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pusher constants
# ---------------------------------------------------------------------------

_PUSHER_URL = (
    "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679"
    "?protocol=7&client=py-piano-viz&version=1.0.0&flash=false"
)
_KICK_API = "https://kick.com/api/v1/channels/{slug}"
_API_TIMEOUT = 8  # seconds


# ---------------------------------------------------------------------------
# Color name table  (CSS4 names + popular aliases, all lowercase)
# ---------------------------------------------------------------------------

_NAMED: dict[str, tuple[int, int, int]] = {
    # basics
    "red": (255, 0, 0),
    "green": (0, 200, 0),
    "blue": (0, 0, 255),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "yellow": (255, 255, 0),
    "orange": (255, 140, 0),
    "purple": (128, 0, 128),
    "pink": (255, 105, 180),
    "cyan": (0, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "fuchsia": (255, 0, 255),
    # extended CSS
    "lime": (0, 255, 0),
    "teal": (0, 128, 128),
    "navy": (0, 0, 128),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "silver": (192, 192, 192),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "coral": (255, 127, 80),
    "salmon": (250, 128, 114),
    "tomato": (255, 99, 71),
    "gold": (255, 215, 0),
    "khaki": (240, 230, 140),
    "turquoise": (64, 224, 208),
    "violet": (238, 130, 238),
    "indigo": (75, 0, 130),
    "crimson": (220, 20, 60),
    "chocolate": (210, 105, 30),
    "peru": (205, 133, 63),
    "tan": (210, 180, 140),
    "beige": (245, 245, 220),
    "ivory": (255, 255, 240),
    "lavender": (230, 230, 250),
    "orchid": (218, 112, 214),
    "plum": (221, 160, 221),
    "thistle": (216, 191, 216),
    "hotpink": (255, 105, 180),
    "deeppink": (255, 20, 147),
    "lightblue": (173, 216, 230),
    "skyblue": (135, 206, 235),
    "steelblue": (70, 130, 180),
    "royalblue": (65, 105, 225),
    "dodgerblue": (30, 144, 255),
    "cornflowerblue": (100, 149, 237),
    "mediumblue": (0, 0, 205),
    "darkblue": (0, 0, 139),
    "lightgreen": (144, 238, 144),
    "limegreen": (50, 205, 50),
    "forestgreen": (34, 139, 34),
    "darkgreen": (0, 100, 0),
    "seagreen": (46, 139, 87),
    "springgreen": (0, 255, 127),
    "yellowgreen": (154, 205, 50),
    "chartreuse": (127, 255, 0),
    "lightyellow": (255, 255, 224),
    "lemonchiffon": (255, 250, 205),
    "wheat": (245, 222, 179),
    "moccasin": (255, 228, 181),
    "peachpuff": (255, 218, 185),
    "mistyrose": (255, 228, 225),
    "snow": (255, 250, 250),
    "mintcream": (245, 255, 250),
    "honeydew": (240, 255, 240),
    "azure": (240, 255, 255),
    "aliceblue": (240, 248, 255),
    "ghostwhite": (248, 248, 255),
    "whitesmoke": (245, 245, 245),
    "gainsboro": (220, 220, 220),
    "lightgray": (211, 211, 211),
    "lightgrey": (211, 211, 211),
    "darkgray": (169, 169, 169),
    "darkgrey": (169, 169, 169),
    "dimgray": (105, 105, 105),
    "dimgrey": (105, 105, 105),
    "slategray": (112, 128, 144),
    "slategrey": (112, 128, 144),
    "darkslategray": (47, 79, 79),
    "darkslategrey": (47, 79, 79),
    # fun aliases
    "rainbow": (255, 0, 255),  # mapped to magenta — cycle via multiple commands
    "neon": (57, 255, 20),
    "mint": (62, 255, 186),
    "rose": (255, 0, 127),
    "amber": (255, 191, 0),
    "electric": (0, 255, 255),
    "fire": (255, 69, 0),
    "ice": (160, 220, 255),
    "sunset": (255, 100, 50),
}

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#([0-9a-f]{6}|[0-9a-f]{3})$", re.IGNORECASE)
_RGB_RE = re.compile(r"^(\d{1,3})[,\s]+(\d{1,3})[,\s]+(\d{1,3})$")
_CMD_RE = re.compile(r"^!(?:color|colour|lights?|led)\s+(.+)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Color parser
# ---------------------------------------------------------------------------

def _clamp(v: int) -> int:
    return max(0, min(255, v))


def parse_color(text: str) -> Optional[tuple[int, int, int]]:
    """Parse a color string into (r, g, b) or return None if unrecognised."""
    text = text.strip()

    # Hex  #RRGGBB or #RGB
    m = _HEX_RE.match(text)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = h[0] * 2 + h[1] * 2 + h[2] * 2
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    # RGB integers
    m = _RGB_RE.match(text)
    if m:
        return (_clamp(int(m.group(1))), _clamp(int(m.group(2))), _clamp(int(m.group(3))))

    # Named color (strip internal spaces, e.g. "light blue" -> "lightblue")
    key = text.lower().replace(" ", "")
    if key in _NAMED:
        return _NAMED[key]

    return None


def parse_command(message: str) -> Optional[tuple[int, int, int]]:
    """Return (r, g, b) if message is a valid !color command, else None."""
    m = _CMD_RE.match(message.strip())
    if not m:
        return None
    return parse_color(m.group(1).strip())


# ---------------------------------------------------------------------------
# KickChatClient
# ---------------------------------------------------------------------------

class KickChatClient:
    """Background thread that reads Kick chat and emits AudienceColorEvents."""

    def __init__(self, channel_slug: str, transition_ms: int = 600) -> None:
        self._slug = channel_slug.strip().lower()
        self._transition_ms = transition_ms
        self._events: queue.SimpleQueue[AudienceColorEvent] = queue.SimpleQueue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._status = "idle"   # "idle" | "connecting" | "connected" | "error:<msg>"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @staticmethod
    def from_config() -> "KickChatClient":
        data = cfg.load().get("kick_chat", {})
        return KickChatClient(
            channel_slug=str(data.get("channel_slug", "")),
            transition_ms=int(data.get("transition_ms", 600)),
        )

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def status(self) -> str:
        return self._status

    def start(self) -> bool:
        data = cfg.load().get("kick_chat", {})
        if not bool(data.get("enabled", False)):
            return False
        if not _WS_AVAILABLE or not self._slug:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._connected = False
        self._status = "idle"

    def drain_events(self) -> list[AudienceColorEvent]:
        out: list[AudienceColorEvent] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except Exception:
                break
        return out

    # ------------------------------------------------------------------
    # Private: background thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        reconnect_delay = 3.0
        while not self._stop.is_set():
            try:
                self._status = "connecting"
                chatroom_id = self._fetch_chatroom_id()
                if chatroom_id is None:
                    self._status = "error:channel not found"
                    time.sleep(reconnect_delay)
                    continue

                self._connect_and_listen(chatroom_id)
            except Exception as exc:
                self._status = f"error:{exc}"
            finally:
                self._connected = False

            if self._stop.is_set():
                break
            time.sleep(reconnect_delay)

    def _fetch_chatroom_id(self) -> Optional[int]:
        url = _KICK_API.format(slug=self._slug)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PianoViz/1.0)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
                return int(data["chatroom"]["id"])
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, ValueError):
            return None

    def _connect_and_listen(self, chatroom_id: int) -> None:
        if websocket is None:
            return

        ws = websocket.create_connection(_PUSHER_URL, timeout=10)
        try:
            self._connected = True
            self._status = "connected"

            channel = f"chatrooms.{chatroom_id}.v2"
            ws.send(json.dumps({
                "event": "pusher:subscribe",
                "data": {"auth": "", "channel": channel},
            }))

            last_ping = time.monotonic()

            while not self._stop.is_set():
                ws.settimeout(30)
                try:
                    raw = ws.recv()
                except Exception:
                    break
                if raw is None:
                    break

                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                event = msg.get("event", "")

                if event == "pusher:ping":
                    ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                    last_ping = time.monotonic()
                    continue

                if event in ("App\\Events\\ChatMessageEvent",
                             "App\\Events\\ChatMessageSentEvent"):
                    data_raw = msg.get("data", "{}")
                    if isinstance(data_raw, str):
                        try:
                            data_raw = json.loads(data_raw)
                        except Exception:
                            continue
                    content = str(data_raw.get("content", ""))
                    self._handle_content(content)

                # Send a keepalive ping if the server hasn't pinged us in a while
                if time.monotonic() - last_ping > 100:
                    ws.send(json.dumps({"event": "pusher:ping", "data": {}}))
                    last_ping = time.monotonic()

        finally:
            try:
                ws.close()
            except Exception:
                pass
            self._connected = False

    def _handle_content(self, content: str) -> None:
        rgb = parse_command(content)
        if rgb is None:
            return
        self._events.put(AudienceColorEvent(
            r=rgb[0], g=rgb[1], b=rgb[2],
            transition_ms=self._transition_ms,
        ))
