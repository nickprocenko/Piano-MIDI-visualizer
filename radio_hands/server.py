"""The app's local web server (http://127.0.0.1:8790/).

    /                     the page (radio_hands/static/index.html)
    /radio/<file>         the page's own scripts and styles
    /roll.js, /hands3d.js, /vendor/..., /hands/...   the coach page's falling notes and 3D hands,
                          served from midi_coach/static unchanged, so both apps draw the same hands
    GET  /api/events      the state, as Server-Sent Events, twice a second
    GET  /api/pcm         the station's audio from a sample on (raw 16-bit stereo, see tuner.SR)
    GET  /api/song?id=    a song's falling notes, bars and time -> beat map
    GET  /api/stations    Radio Browser search (q, country, state, tag)
    GET  /api/states      a country's provinces/states
    GET  /api/countries
    POST /api/tune        {url, name, uuid, ...}     POST /api/stop
    POST /api/song        {query} what's playing, typed; or {path} another file for it
    POST /api/settings    {online, charts}
"""

from __future__ import annotations

import json
import logging
import pathlib
import queue
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import stations
from .tracker import Tracker
from .tuner import SR

log = logging.getLogger("radio_hands.server")

HERE = pathlib.Path(__file__).parent
OWN = HERE / "static"
COACH = HERE.parent / "midi_coach" / "static"
COACH_FILES = {"roll.js", "hands3d.js"}
COACH_DIRS = {"vendor", "hands"}
TYPES = {".js": "application/javascript", ".html": "text/html; charset=utf-8", ".json": "application/json",
         ".glb": "model/gltf-binary", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}
PCM_CHUNK = SR // 10  # samples per write: a tenth of a second


class Hub:
    """The page's event streams."""

    def __init__(self) -> None:
        self.clients: list[queue.Queue] = []
        self.lock = threading.Lock()
        self.last: bytes | None = None

    def publish(self, state: dict) -> None:
        data = json.dumps(state, separators=(",", ":")).encode()
        with self.lock:
            self.last = data
            for q in self.clients:
                if q.qsize() < 20:
                    q.put(data)

    def join(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self.lock:
            self.clients.append(q)
            if self.last:
                q.put(self.last)
        return q

    def leave(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)


def make_handler(tracker: Tracker, hub: Hub):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

        # -- helpers --------------------------------------------------------------------------

        def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200) -> None:
            self._send(code, json.dumps(data).encode(), "application/json")

        def _error(self, code: int, message: str) -> None:
            self._json({"error": message}, code)

        def _file(self, path: pathlib.Path, root: pathlib.Path) -> None:
            try:
                path = path.resolve()
                if root.resolve() not in path.parents or not path.is_file():
                    raise FileNotFoundError
                body = path.read_bytes()
            except OSError:
                self._error(404, "Not found")
                return
            self._send(200, body, TYPES.get(path.suffix.lower(), "application/octet-stream"))

        # -- GET ------------------------------------------------------------------------------

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
            path = url.path
            try:
                if path in ("/", "/index.html"):
                    return self._file(OWN / "index.html", OWN)
                if path.startswith("/radio/"):
                    return self._file(OWN / path[len("/radio/"):], OWN)
                first = path.lstrip("/").split("/")[0]
                if path.lstrip("/") in COACH_FILES or first in COACH_DIRS:
                    return self._file(COACH / path.lstrip("/"), COACH)
                if path == "/api/events":
                    return self._events()
                if path == "/api/pcm":
                    return self._pcm(q)
                if path == "/api/song":
                    prep = tracker.prep(q.get("id", ""))
                    return self._json(prep) if prep else self._error(404, "That song isn't loaded any more.")
                if path == "/api/state":
                    return self._json(tracker.state())
                if path == "/api/stations":
                    return self._json(stations.search(q.get("q", ""), q.get("country", ""), q.get("state", ""), q.get("tag", "")))
                if path == "/api/states":
                    return self._json(stations.states(q.get("country", "Canada")))
                if path == "/api/countries":
                    return self._json(stations.countries())
                if path == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon")
                self._error(404, "Not found")
            except ConnectionError as exc:
                self._error(502, str(exc))
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            q = hub.join()
            try:
                while True:
                    try:
                        data = q.get(timeout=15)
                        self.wfile.write(b"data: " + data + b"\n\n")
                    except queue.Empty:
                        self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                hub.leave(q)

        def _pcm(self, q: dict):
            tuner = tracker.tuner
            if not tuner or q.get("session") != tuner.session:
                return self._error(409, "That station isn't playing any more.")
            ring = tuner.ring
            start = max(int(float(q.get("from", 0))), ring.oldest)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-From", str(start))
            self.send_header("X-Sample-Rate", str(SR))
            self.send_header("X-Channels", "2")
            self.send_header("Access-Control-Expose-Headers", "X-From, X-Sample-Rate, X-Channels")
            self.end_headers()
            self.close_connection = True
            pos = start
            try:
                while tracker.tuner is tuner and not ring.closed:
                    got, frames = ring.read(pos, PCM_CHUNK * 5, wait=1.0)
                    if not len(frames):
                        continue
                    if got != pos:  # the page fell so far behind the ring was overwritten
                        break
                    self.wfile.write(frames.astype("<i2").tobytes())
                    pos = got + len(frames)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        # -- POST -----------------------------------------------------------------------------

        def do_POST(self):
            path = urllib.parse.urlsplit(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                return self._error(400, "Bad request")
            try:
                if path == "/api/tune":
                    return self._json(tracker.tune(body))
                if path == "/api/stop":
                    tracker.stop()
                    return self._json({"ok": True})
                if path == "/api/song":
                    tracker.choose(query=body.get("query"), path=body.get("path"))
                    return self._json({"ok": True})
                if path == "/api/settings":
                    return self._json(tracker.set_settings(online=body.get("online"), charts=body.get("charts")))
                if path == "/api/log":  # the page's ?debug=1 reports
                    log.info("page: %s", json.dumps(body)[:600])
                    return self._json({"ok": True})
                self._error(404, "Not found")
            except ValueError as exc:
                self._error(400, str(exc))

    return Handler


def serve(port: int) -> ThreadingHTTPServer:
    hub = Hub()
    tracker = Tracker(hub.publish)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(tracker, hub))
    server.daemon_threads = True
    server.tracker = tracker  # type: ignore[attr-defined]
    return server
