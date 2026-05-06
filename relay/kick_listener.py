"""Kick.com chat listener — parses commands and forwards them to the relay.

Run alongside relay/main.py:
    python -m relay.kick_listener

Commands available in chat:
    !color  #rrggbb | r,g,b   set note colour
    !bright 0-100             LED brightness
    !speed  100-1200          note fall speed (px/sec)
    !glow   0-100             glow strength
    !sparks on|off            toggle sparks
    !smoke  on|off            toggle smoke

Credentials are read from config.json under "kick_chat" (same key as
tools/kick_chat.py so you only need one config block).
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
RELAY_URL = "http://localhost:8000"
CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.json"

_COMMANDS: dict[str, str] = {
    "!color":  "color",
    "!bright": "brightness",
    "!speed":  "speed",
    "!glow":   "glow",
    "!sparks": "sparks",
    "!smoke":  "smoke",
    "!drip":   "drip",
}
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f).get("kick_chat", {})
    except Exception:
        return {}


async def _send(param: str, value: str, user: str) -> None:
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{RELAY_URL}/control",
                json={"param": param, "value": value, "source": "kick", "user": user},
                timeout=3,
            )
            print(f"[Kick] {user} → {param}={value}")
        except Exception as exc:
            print(f"[Kick] relay error: {exc}")


async def message_handler(message: dict) -> None:
    username: str = message.get("sender_username", "viewer")
    content: str = message.get("content", "").strip()
    lower = content.lower()

    for cmd, param in _COMMANDS.items():
        if lower.startswith(cmd + " ") or lower == cmd:
            value = content[len(cmd):].strip()
            if value:
                await _send(param, value, username)
            return


async def main() -> None:
    conf = _load_config()
    client_id = conf.get("client_id", "")
    client_secret = conf.get("client_secret", "")
    redirect_uri = conf.get("redirect_uri", "http://localhost:8080/callback")
    channel = conf.get("channel", "")

    if not client_id or not client_secret or not channel:
        sys.exit(
            "kick_chat config missing in config.json.\n"
            "Add: {\"kick_chat\": {\"client_id\": \"...\", \"client_secret\": \"...\","
            " \"redirect_uri\": \"http://localhost:8080/callback\", \"channel\": \"...\"}}"
        )

    api = KickAPI(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    api.add_message_handler(message_handler)
    await api.connect_to_chatroom(channel)

    print(f"[Kick] Connected to #{channel} — forwarding commands to {RELAY_URL}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
