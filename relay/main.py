"""FastAPI relay server — bridges Kick chat commands to the visualizer and
broadcasts live state to WebSocket subscribers (OBS overlay, web UIs).

Run with:
    uvicorn relay.main:app --host 0.0.0.0 --port 8000

Endpoints:
    POST /control          — receive commands from kick_listener
    POST /vote             — direct REST color vote
    WS   /ws/state         — subscribe to live state broadcasts (overlay)
    WS   /ws/vote          — submit a color vote over WebSocket
    GET  /state            — current state snapshot (REST)
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
VISUALIZER_URL = "http://localhost:8181/api/patch"
MAX_RECENT = 8
# ---------------------------------------------------------------------------

app = FastAPI(title="Piano MIDI Relay")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- shared state ----------------------------------------------------------
_state: dict[str, Any] = {
    "color": {"r": 0, "g": 220, "b": 255},
    "last_user": None,
    "last_command": None,
    "recent_picks": [],
    "brightness": 100,
    "speed": 420,
    "glow": 80,
    "sparks": True,
    "smoke": True,
    "drip": False,
}

_ws_clients: set[WebSocket] = set()

# ---- helpers ---------------------------------------------------------------

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _parse_color(value: str) -> tuple[int, int, int] | None:
    value = value.strip().lstrip("#")
    if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    parts = value.split(",")
    if len(parts) == 3:
        try:
            r, g, b = (_clamp(int(p.strip()), 0, 255) for p in parts)
            return r, g, b
        except ValueError:
            pass
    return None


def _record_color_pick(user: str, r: int, g: int, b: int) -> None:
    _state["color"] = {"r": r, "g": g, "b": b}
    _state["last_user"] = user
    picks: list = _state["recent_picks"]
    picks.insert(0, {
        "user": user,
        "color": {"r": r, "g": g, "b": b},
        "ts": int(time.time()),
    })
    _state["recent_picks"] = picks[:MAX_RECENT]


async def _broadcast() -> None:
    dead: set[WebSocket] = set()
    msg = json.dumps({"type": "state_update", **_state})
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead


async def _forward(patch: dict) -> None:
    try:
        async with httpx.AsyncClient() as client:
            await client.post(VISUALIZER_URL, json=patch, timeout=2)
    except Exception as exc:
        print(f"[relay] visualizer unreachable: {exc}")


# ---- request models --------------------------------------------------------

class ControlRequest(BaseModel):
    param: str
    value: str
    source: str = "kick"
    user: str = "viewer"


class VoteRequest(BaseModel):
    color: str
    user: str = "viewer"


# ---- REST endpoints --------------------------------------------------------

@app.get("/state")
async def get_state() -> dict:
    return {"type": "state_update", **_state}


@app.post("/control")
async def control(req: ControlRequest) -> dict:
    patch: dict | None = None
    _state["last_user"] = req.user
    _state["last_command"] = req.param

    if req.param == "color":
        rgb = _parse_color(req.value)
        if rgb:
            r, g, b = rgb
            _record_color_pick(req.user, r, g, b)
            patch = {"type": "note_style", "patch": {"color_r": r, "color_g": g, "color_b": b}}

    elif req.param == "brightness":
        try:
            v = _clamp(int(req.value), 0, 100)
            _state["brightness"] = v
            patch = {"type": "keyboard_style", "patch": {"brightness": v}}
        except ValueError:
            pass

    elif req.param == "speed":
        try:
            v = _clamp(int(req.value), 100, 1200)
            _state["speed"] = v
            patch = {"type": "note_style", "patch": {"speed_px_per_sec": v}}
        except ValueError:
            pass

    elif req.param == "glow":
        try:
            v = _clamp(int(req.value), 0, 100)
            _state["glow"] = v
            patch = {"type": "note_style", "patch": {"glow_strength_percent": v}}
        except ValueError:
            pass

    elif req.param == "sparks":
        enabled = req.value.lower() == "on"
        _state["sparks"] = enabled
        patch = {"type": "note_style", "patch": {"effect_sparks_enabled": int(enabled)}}

    elif req.param == "smoke":
        enabled = req.value.lower() == "on"
        _state["smoke"] = enabled
        patch = {"type": "note_style", "patch": {"effect_smoke_enabled": int(enabled)}}

    elif req.param == "drip":
        enabled = req.value.lower() == "on"
        _state["drip"] = enabled
        patch = {"type": "note_style", "patch": {"effect_liquid_drip_enabled": int(enabled)}}

    if patch:
        await _forward(patch)
        await _broadcast()

    return {"ok": bool(patch)}


@app.post("/vote")
async def vote(req: VoteRequest) -> dict:
    rgb = _parse_color(req.color)
    if not rgb:
        return {"ok": False, "error": "invalid color"}
    r, g, b = rgb
    _record_color_pick(req.user, r, g, b)
    _state["last_command"] = "vote"
    await _forward({"type": "note_style", "patch": {"color_r": r, "color_g": g, "color_b": b}})
    await _broadcast()
    return {"ok": True}


# ---- WebSocket endpoints ---------------------------------------------------

@app.websocket("/ws/state")
async def ws_state(ws: WebSocket) -> None:
    """Overlay connects here to receive live state pushes."""
    await ws.accept()
    _ws_clients.add(ws)
    try:
        # Send current state immediately on connect.
        await ws.send_text(json.dumps({"type": "state_update", **_state}))
        while True:
            # Keep the connection alive; ignore any client messages.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


@app.websocket("/ws/vote")
async def ws_vote(ws: WebSocket) -> None:
    """Web UI connects here to submit color votes.
    Send: {"color": "#rrggbb", "user": "nick"}
    Receive: {"ok": true} or {"ok": false, "error": "..."}
    """
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"ok": False, "error": "invalid json"}))
                continue

            color = data.get("color", "")
            user = str(data.get("user", "viewer"))
            rgb = _parse_color(color)
            if not rgb:
                await ws.send_text(json.dumps({"ok": False, "error": "invalid color"}))
                continue

            r, g, b = rgb
            _record_color_pick(user, r, g, b)
            _state["last_command"] = "vote"
            await _forward({"type": "note_style", "patch": {"color_r": r, "color_g": g, "color_b": b}})
            await _broadcast()
            await ws.send_text(json.dumps({"ok": True}))

    except WebSocketDisconnect:
        pass
