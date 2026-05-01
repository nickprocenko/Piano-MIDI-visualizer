"""Send text commands to the running Piano Visualizer to switch themes.

Usage examples:
  python tools/theme_command_bridge.py --stdin
  python tools/theme_command_bridge.py --stdin --host http://127.0.0.1:8181

This script is designed to pair with speech-to-text output. If you already have STT,
pipe or type recognized text lines into this process.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_HOST = "http://127.0.0.1:8181"


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _extract_theme_index(text: str, theme_count: int) -> int | None:
    m = re.search(r"\btheme\s*(\d{1,2})\b", text)
    if not m:
        m = re.search(r"\b(\d{1,2})\b", text)
    if not m:
        return None
    idx = int(m.group(1)) - 1
    if 0 <= idx < theme_count:
        return idx
    return None


def _find_theme_by_name(text: str, themes: list[dict]) -> int | None:
    for i, theme in enumerate(themes):
        name = _normalize(str(theme.get("name", "")))
        if name and name in text:
            return i
    return None


def _resolve_target_index(command: str, themes: list[dict], active_index: int) -> int | None:
    cmd = _normalize(command)
    if not themes:
        return None

    if "next" in cmd:
        return (active_index + 1) % len(themes)
    if "prev" in cmd or "previous" in cmd or "back" in cmd:
        return (active_index - 1) % len(themes)

    by_number = _extract_theme_index(cmd, len(themes))
    if by_number is not None:
        return by_number

    by_name = _find_theme_by_name(cmd, themes)
    if by_name is not None:
        return by_name

    return None


def _apply_theme(host: str, index: int) -> None:
    _http_post_json(f"{host}/api/patch", {"type": "theme", "index": index})


def _handle_command(host: str, command: str) -> str:
    data = _http_get_json(f"{host}/api/themes")
    themes = list(data.get("themes", []))
    active_index = int(data.get("active_index", 0))

    target = _resolve_target_index(command, themes, active_index)
    if target is None:
        return "No matching theme command. Try: next theme, previous theme, theme 2, or a theme name."

    _apply_theme(host, target)
    label = str(themes[target].get("name", f"Theme {target + 1}")) if themes else f"Theme {target + 1}"
    return f"Applied {label}"


def _run_stdin_loop(host: str) -> int:
    print("Theme command bridge ready. Type commands, Ctrl+C to quit.")
    print("Examples: 'next theme', 'theme 2', 'previous theme', 'moonlight'")
    while True:
        try:
            line = input("> ")
        except EOFError:
            return 0
        except KeyboardInterrupt:
            print("\nExiting.")
            return 0

        cmd = line.strip()
        if not cmd:
            continue
        if _normalize(cmd) in {"quit", "exit"}:
            return 0

        try:
            result = _handle_command(host, cmd)
            print(result)
        except urllib.error.URLError:
            print("Cannot reach app control server. Is the app running?")
        except Exception as exc:  # defensive: keep loop alive
            print(f"Command failed: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Theme command bridge for Piano Visualizer")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Control server host (default: http://127.0.0.1:8181)")
    parser.add_argument("--stdin", action="store_true", help="Read commands interactively from stdin")
    args = parser.parse_args()

    if not args.stdin:
        print("Pass --stdin to run command input mode.")
        return 2

    host = args.host.rstrip("/")
    return _run_stdin_loop(host)


if __name__ == "__main__":
    raise SystemExit(main())
