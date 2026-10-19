"""Live score display: a localhost HTTP server pushing state over Server-Sent Events.

Two front ends consume the same event stream:
  * the coach page  http://127.0.0.1:<port>/       (midi_coach/static/coach.html)
  * the web visualizer's notation strip (docs/index.html, "Coach" link)

Both render through docs/notation.html (the visualizer's OSMD strip), so this
module only sends messages that notation.html understands:
  loadScore (via GET /score), cursorBeat, marks, flash, heat, status.
"""

from __future__ import annotations

import json
import os
import pathlib
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .notes import MUSICXML_SUFFIXES, Score

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC_FILES = {
    "/": (pathlib.Path(__file__).parent / "static" / "coach.html", "text/html; charset=utf-8"),
    "/notation.html": (REPO_ROOT / "docs" / "notation.html", "text/html; charset=utf-8"),
    "/opensheetmusicdisplay.min.js": (REPO_ROOT / "src" / "static" / "opensheetmusicdisplay.min.js", "application/javascript"),
}
DEFAULT_PORT = 8765


def score_to_musicxml(path: str) -> str:
    """MusicXML text for OSMD: raw file for .xml/.musicxml, music21 export otherwise."""
    p = pathlib.Path(path)
    if p.suffix.lower() in MUSICXML_SUFFIXES - {".mxl"}:
        return p.read_text(encoding="utf-8", errors="replace")
    from music21 import converter
    from music21.musicxml.m21ToXml import GeneralObjectExporter

    return GeneralObjectExporter(converter.parse(str(p))).parse().decode("utf-8")


class DisplayHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[queue.Queue] = []
        self._server: ThreadingHTTPServer | None = None
        self.url: str | None = None
        self.score_path: str | None = None
        self._xml_cache: dict[str, str] = {}
        self._score_payload: dict | None = None
        self._version = 0
        self._marks: dict[tuple[float, int], str] = {}
        self._heat: list[dict] | None = None
        self._status = ""
        self._cursor: dict | None = None
        self._lesson: dict | None = None
        self._lesson_version = 0
        self._session: dict = {"type": "session", "active": False}

    # -- server ------------------------------------------------------------

    def start(self) -> str:
        if self._server:
            return self.url
        hub = self
        base = int(os.environ.get("MIDI_COACH_DISPLAY_PORT") or DEFAULT_PORT)
        last_exc: Exception | None = None
        for port in range(base, base + 10):
            try:
                self._server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(hub))
                break
            except OSError as exc:
                last_exc = exc
        else:
            raise RuntimeError(f"Could not open display server port ({last_exc})")
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/"
        return self.url

    def shutdown(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._clients)

    def open_browser(self) -> None:
        webbrowser.open(self.start())

    # -- state -------------------------------------------------------------

    def load_score(self, score: Score) -> None:
        if score.path == self.score_path and self._score_payload:
            return
        xml = self.xml_for(score.path)
        with self._lock:
            self._version += 1
            self.score_path = score.path
            self._score_payload = {"version": self._version, "title": pathlib.Path(score.path).stem, "xml": xml}
            self._marks.clear()
            self._heat = None
            self._cursor = None
            self._status = ""
        self._broadcast({"type": "score", "version": self._version, "title": pathlib.Path(score.path).stem})

    def xml_for(self, path: str) -> str:
        xml = self._xml_cache.get(path)
        if xml is None:
            xml = self._xml_cache[path] = score_to_musicxml(path)
        return xml

    def marks(self, updates: list[tuple[float, int, str]], reset: bool = False) -> None:
        with self._lock:
            if reset:
                self._marks.clear()
            for beat, pitch, status in updates:
                self._marks[(round(beat, 3), pitch)] = status
        self._broadcast({"type": "marks", "reset": reset, "marks": [{"beat": b, "pitch": p, "status": s} for b, p, s in updates]})

    def heat(self, bars: list[dict] | None) -> None:
        with self._lock:
            self._heat = bars
        self._broadcast({"type": "heat", "bars": bars or []})

    def cursor(self, beat: float, beats_per_sec: float = 0.0, live: bool = False) -> None:
        """live=True: a practice session drives the cursor (the visualizer then lets it
        override Learn Mode's own scrolling); otherwise it's just positioning."""
        msg = {"type": "cursorBeat", "beat": round(beat, 4), "bps": round(beats_per_sec, 4), "live": live}
        with self._lock:
            self._cursor = msg
        self._broadcast(msg)

    def lesson(self, payload: dict) -> int:
        """Publish a lesson for the visualizer's Learn Mode (title, xml, events, mode...)."""
        with self._lock:
            self._lesson_version += 1
            self._lesson = {**payload, "version": self._lesson_version}
        self._broadcast({"type": "lesson", "version": self._lesson_version, "title": payload.get("title"), "autostart": payload.get("autostart", False)})
        return self._lesson_version

    def lesson_payload(self) -> dict | None:
        with self._lock:
            return self._lesson

    def session(self, active: bool, mode: str | None = None) -> None:
        msg = {"type": "session", "active": active, "mode": mode}
        with self._lock:
            self._session = msg
        self._broadcast(msg)

    def flash(self, text: str) -> None:
        self._broadcast({"type": "flash", "text": text})

    def status(self, text: str) -> None:
        with self._lock:
            self._status = text
        self._broadcast({"type": "status", "text": text})

    def snapshot(self) -> list[dict]:
        with self._lock:
            # A page that connects late gets the latest lesson, but never auto-started.
            lesson = [{"type": "lesson", "version": self._lesson_version, "title": self._lesson.get("title"), "autostart": False}] if self._lesson else []
            if not self._score_payload:
                return lesson + [{"type": "status", "text": "Waiting for a score from Claude…"}]
            out = [{"type": "score", "version": self._version, "title": self._score_payload["title"]}] + lesson + [self._session]
            if self._marks:
                out.append({"type": "marks", "reset": True, "marks": [{"beat": b, "pitch": p, "status": s} for (b, p), s in self._marks.items()]})
            if self._heat:
                out.append({"type": "heat", "bars": self._heat})
            if self._cursor:
                out.append({**self._cursor, "bps": 0.0})
            if self._status:
                out.append({"type": "status", "text": self._status})
            return out

    def score_payload(self) -> dict | None:
        with self._lock:
            return self._score_payload

    def _broadcast(self, msg: dict) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def _subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        for msg in self.snapshot():
            q.put_nowait(msg)
        with self._lock:
            self._clients.append(q)
        return q

    def _unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)


def _make_handler(hub: DisplayHub):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # stdout belongs to MCP
            pass

        def _cors(self) -> None:
            # The visualizer may run from GitHub Pages or file://; allow it to read localhost.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Allow-Headers", "*")

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/events":
                return self._events()
            if path == "/lesson":
                payload = hub.lesson_payload()
                if not payload:
                    return self._send(404, b'{"error":"no lesson"}', "application/json")
                return self._send(200, json.dumps(payload).encode(), "application/json")
            if path == "/score":
                payload = hub.score_payload()
                if not payload:
                    return self._send(404, b'{"error":"no score loaded"}', "application/json")
                return self._send(200, json.dumps(payload).encode(), "application/json")
            if path in STATIC_FILES:
                file, ctype = STATIC_FILES[path]
                try:
                    return self._send(200, file.read_bytes(), ctype)
                except OSError:
                    pass
            self._send(404, b"not found", "text/plain")

        def _events(self) -> None:
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = hub._subscribe()
            try:
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                        data = f"data: {json.dumps(msg)}\n\n".encode()
                    except queue.Empty:
                        data = b": ping\n\n"
                    self.wfile.write(data)
                    self.wfile.flush()
            except (OSError, ValueError):
                pass
            finally:
                hub._unsubscribe(q)

    return Handler
