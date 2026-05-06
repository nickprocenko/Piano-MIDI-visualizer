"""Kick.com chat bot — forwards chat commands to the local control server.

Run this alongside the main visualizer:
    python tools/kick_chat.py

Commands (usable by anyone in chat):
    !color <hex|r,g,b>   — set note colour  e.g. !color #ff00ff  or  !color 255,0,128
    !bright <0-100>      — set LED brightness
    !speed <100-1200>    — set note fall speed (px/sec)
    !glow <0-100>        — set glow strength
    !sparks <on|off>     — toggle sparks effect
    !smoke <on|off>      — toggle smoke effect

Credentials are read from config.json under "kick_chat":
    {
      "kick_chat": {
        "client_id":     "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
        "redirect_uri":  "http://localhost:8080/callback",
        "channel":       "YOUR_KICK_USERNAME"
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

try:
    import httpx
except ImportError:
    sys.exit("Missing dependency: pip install httpx")

try:
    from kickpython import KickAPI  # type: ignore
except ImportError:
    sys.exit("Missing dependency: pip install kickpython")

# ---------------------------------------------------------------------------
CONTROL_URL = "http://localhost:8181/api/patch"
CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.json"

COMMAND_HELP = (
    "Commands: !color #rrggbb | !bright 0-100 | !speed 100-1200 "
    "| !glow 0-100 | !sparks on/off | !smoke on/off"
)
# ---------------------------------------------------------------------------


def _load_kick_config() -> dict:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f).get("kick_chat", {})
    except Exception:
        return {}


def _parse_color(value: str) -> tuple[int, int, int] | None:
    value = value.strip().lstrip("#")
    if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value):
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
        return r, g, b
    parts = value.split(",")
    if len(parts) == 3:
        try:
            r, g, b = (max(0, min(255, int(p.strip()))) for p in parts)
            return r, g, b
        except ValueError:
            pass
    return None


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


async def _patch(client: httpx.AsyncClient, payload: dict) -> None:
    try:
        await client.post(CONTROL_URL, json=payload, timeout=3)
    except Exception as exc:
        print(f"[Kick] relay error: {exc}")


async def message_handler(message: dict) -> None:
    username = message.get("sender_username", "?")
    content = message.get("content", "").strip()
    lower = content.lower()

    async with httpx.AsyncClient() as client:
        if lower.startswith("!color "):
            rgb = _parse_color(content[7:])
            if rgb:
                r, g, b = rgb
                await _patch(client, {
                    "type": "note_style",
                    "patch": {"color_r": r, "color_g": g, "color_b": b},
                })
                print(f"[Kick] {username} → color ({r},{g},{b})")
            return

        if lower.startswith("!bright "):
            try:
                v = _clamp(int(content[8:].strip()), 0, 100)
                await _patch(client, {"type": "keyboard_style", "patch": {"brightness": v}})
                print(f"[Kick] {username} → brightness {v}")
            except ValueError:
                pass
            return

        if lower.startswith("!speed "):
            try:
                v = _clamp(int(content[7:].strip()), 100, 1200)
                await _patch(client, {"type": "note_style", "patch": {"speed_px_per_sec": v}})
                print(f"[Kick] {username} → speed {v}")
            except ValueError:
                pass
            return

        if lower.startswith("!glow "):
            try:
                v = _clamp(int(content[6:].strip()), 0, 100)
                await _patch(client, {
                    "type": "note_style",
                    "patch": {"glow_strength_percent": v},
                })
                print(f"[Kick] {username} → glow {v}")
            except ValueError:
                pass
            return

        if lower.startswith("!sparks "):
            arg = content[8:].strip().lower()
            if arg in ("on", "off"):
                enabled = 1 if arg == "on" else 0
                await _patch(client, {
                    "type": "note_style",
                    "patch": {"effect_sparks_enabled": enabled},
                })
                print(f"[Kick] {username} → sparks {arg}")
            return

        if lower.startswith("!smoke "):
            arg = content[7:].strip().lower()
            if arg in ("on", "off"):
                enabled = 1 if arg == "on" else 0
                await _patch(client, {
                    "type": "note_style",
                    "patch": {"effect_smoke_enabled": enabled},
                })
                print(f"[Kick] {username} → smoke {arg}")
            return

        if lower.startswith("!drip "):
            arg = content[6:].strip().lower()
            if arg in ("on", "off"):
                enabled = 1 if arg == "on" else 0
                await _patch(client, {
                    "type": "note_style",
                    "patch": {"effect_liquid_drip_enabled": enabled},
                })
                print(f"[Kick] {username} → drip {arg}")
            return


async def main() -> None:
    conf = _load_kick_config()
    client_id = conf.get("client_id", "")
    client_secret = conf.get("client_secret", "")
    redirect_uri = conf.get("redirect_uri", "http://localhost:8080/callback")
    channel = conf.get("channel", "")

    if not client_id or not client_secret or not channel:
        sys.exit(
            "kick_chat config missing. Add to config.json:\n"
            '  "kick_chat": {\n'
            '    "client_id": "...",\n'
            '    "client_secret": "...",\n'
            '    "redirect_uri": "http://localhost:8080/callback",\n'
            '    "channel": "your_kick_username"\n'
            "  }"
        )

    api = KickAPI(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    api.add_message_handler(message_handler)
    await api.connect_to_chatroom(channel)

    print(f"[Kick] Connected to #{channel}. {COMMAND_HELP}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
