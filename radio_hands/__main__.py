"""Radio Hands: listen to an internet radio station and watch a pair of hands play what's on.

    python -m radio_hands [--port 8790] [--no-browser]

Opens http://127.0.0.1:8790/ in the browser. Close the window (or Ctrl+C) to quit.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import webbrowser

os.environ.setdefault("MIDI_COACH_SONG_WATCH", "off")  # the coach's folder watcher isn't needed here
os.environ.setdefault("MIDI_COACH_VAULT", "off")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="radio_hands", description="Hands playing what's on the radio.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("RADIO_HANDS_PORT", 8790)))
    ap.add_argument("--no-browser", action="store_true", help="don't open the page")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    url = f"http://127.0.0.1:{args.port}/"
    with socket.socket() as s:
        taken = s.connect_ex(("127.0.0.1", args.port)) == 0
    if taken:
        if _is_radio_hands(url):  # already running: just show it
            print(f"Radio Hands is already running: {url}")
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        print(f"Port {args.port} is used by another program. Try: python -m radio_hands --port {args.port + 10}")
        return 1
    from .server import serve

    server = serve(args.port)
    print(f"Radio Hands: {url}  (Ctrl+C to quit)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _is_radio_hands(url: str) -> bool:
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(url + "api/state", timeout=3) as res:
            return "tuner" in json.loads(res.read())
    except Exception:  # noqa: BLE001 - anything else on the port
        return False


if __name__ == "__main__":
    sys.exit(main())
