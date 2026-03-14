"""Audience color control client for receiving live color events over WebSocket."""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from src import config as cfg

try:
    import websocket  # type: ignore
    _WS_AVAILABLE = True
except Exception:
    websocket = None  # type: ignore
    _WS_AVAILABLE = False


@dataclass
class AudienceColorEvent:
    r: int
    g: int
    b: int
    transition_ms: int


@dataclass
class AudienceClientConfig:
    enabled: bool
    ws_url: str
    channel_id: str
    app_api_key: str
    reconnect_sec: float


class AudienceColorClient:
    """Background WebSocket client that receives color_set events."""

    def __init__(self, conf: AudienceClientConfig) -> None:
        self._cfg = conf
        self._events: queue.SimpleQueue[AudienceColorEvent] = queue.SimpleQueue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @staticmethod
    def from_config() -> "AudienceColorClient":
        data = cfg.load().get("audience_control", {})
        conf = AudienceClientConfig(
            enabled=bool(data.get("enabled", False)),
            ws_url=str(data.get("ws_url", "wss://example.com/ws/app")),
            channel_id=str(data.get("channel_id", "")),
            app_api_key=str(data.get("app_api_key", "")),
            reconnect_sec=max(0.2, float(data.get("reconnect_sec", 2.0))),
        )
        return AudienceColorClient(conf)

    def start(self) -> bool:
        if not self._cfg.enabled or not _WS_AVAILABLE or websocket is None:
            return False
        if not self._cfg.ws_url or not self._cfg.channel_id or not self._cfg.app_api_key:
            return False

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._connected = False

    def drain_events(self) -> list[AudienceColorEvent]:
        out: list[AudienceColorEvent] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except Exception:
                break
        return out

    def _run(self) -> None:
        while not self._stop.is_set():
            ws = None
            try:
                ws = websocket.create_connection(self._cfg.ws_url, timeout=5)
                self._connected = True

                auth = {
                    "type": "app_auth",
                    "channel_id": self._cfg.channel_id,
                    "api_key": self._cfg.app_api_key,
                }
                ws.send(json.dumps(auth))

                while not self._stop.is_set():
                    raw = ws.recv()
                    if raw is None:
                        break
                    self._handle_message(raw)
            except Exception:
                pass
            finally:
                self._connected = False
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass

            if self._stop.is_set():
                break
            time.sleep(self._cfg.reconnect_sec)

    def _handle_message(self, raw: Any) -> None:
        if not isinstance(raw, str):
            return
        try:
            msg = json.loads(raw)
        except Exception:
            return

        if msg.get("type") == "ping":
            return
        if msg.get("type") != "color_set":
            return

        rgb = msg.get("rgb", {})
        r = max(0, min(255, int(rgb.get("r", 0))))
        g = max(0, min(255, int(rgb.get("g", 0))))
        b = max(0, min(255, int(rgb.get("b", 0))))
        transition_ms = max(20, min(3000, int(msg.get("transition_ms", 220))))
        self._events.put(AudienceColorEvent(r=r, g=g, b=b, transition_ms=transition_ms))
