"""Live score display: a localhost HTTP server pushing state over Server-Sent Events.

Two front ends consume the same event stream:
  * the coach page  http://127.0.0.1:<port>/       (midi_coach/static/coach.html)
  * the web visualizer's notation strip (docs/index.html, "Coach" link)

Both render through docs/notation.html (the visualizer's OSMD strip), so this
module only sends messages that notation.html understands:
  loadScore (via GET /score), cursorBeat, marks, flash, heat, status.
The coach page also gets `practice` (its menu state), `say` (a line to speak
aloud) and `metronome` (clicks for a run or recording), and drives practice runs through POST /cmd/<name>, handled by callables
registered in hub.commands.
"""

from __future__ import annotations

import json
import os
import pathlib
import queue
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote

from . import transcript
from .notes import MUSICXML_SUFFIXES, Score

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC_FILES = {
    "/": (pathlib.Path(__file__).parent / "static" / "coach.html", "text/html; charset=utf-8"),
    "/atlas.js": (pathlib.Path(__file__).parent / "static" / "atlas.js", "application/javascript; charset=utf-8"),
    "/today.js": (pathlib.Path(__file__).parent / "static" / "today.js", "application/javascript; charset=utf-8"),
    "/profiles.js":(pathlib.Path(__file__).parent / "static" / "profiles.js", "application/javascript; charset=utf-8"),
    "/flute.js": (pathlib.Path(__file__).parent / "static" / "flute.js", "application/javascript; charset=utf-8"),
    "/video.js": (pathlib.Path(__file__).parent / "static" / "video.js", "application/javascript; charset=utf-8"),
    "/youtube.js": (pathlib.Path(__file__).parent / "static" / "youtube.js", "application/javascript; charset=utf-8"),
    "/file.js": (pathlib.Path(__file__).parent / "static" / "file.js", "application/javascript; charset=utf-8"),
    "/prefs.js": (pathlib.Path(__file__).parent / "static" / "prefs.js", "application/javascript; charset=utf-8"),
    "/roll.js": (pathlib.Path(__file__).parent / "static" / "roll.js", "application/javascript; charset=utf-8"),
    "/coach.png": (pathlib.Path(__file__).parent / "static" / "coach.png", "image/png"),
    "/favicon.ico": (pathlib.Path(__file__).parent / "static" / "coach.ico", "image/x-icon"),
    "/visualizer.html": (REPO_ROOT / "docs" / "index.html", "text/html; charset=utf-8"),  # the Visualizer card
    "/notation.html": (REPO_ROOT / "docs" / "notation.html", "text/html; charset=utf-8"),
    "/fingering.js": (REPO_ROOT / "docs" / "fingering.js", "application/javascript; charset=utf-8"),
    "/opensheetmusicdisplay.min.js": (REPO_ROOT / "src" / "static" / "opensheetmusicdisplay.min.js", "application/javascript"),
}
DEFAULT_PORT = 8765
SHEET_MAX_NOTES = 10000  # bigger MIDI files take close to a minute to convert and hang the page


def sheet_problem(score: Score) -> str | None:
    """Why a MIDI file shouldn't be drawn as sheet music, or None if it can be."""
    from . import sheet

    if pathlib.Path(score.path).suffix.lower() in MUSICXML_SUFFIXES:
        return None  # already notation
    if sheet.wanted(score):
        return None  # a piano sheet of the chosen parts only: small whatever the file
    if len(score.notes) > SHEET_MAX_NOTES:
        return (f"This file has {len(score.notes):,} notes across {len(score.parts)} parts - too much to draw as sheet "
                "music. Choose the parts you play and practice those.")
    return None


def cleanup_state(score: Score) -> str | None:
    """'off' for a MIDI file with no reliable beat (its sheet is a rough draft that Auto clean
    can redraw), 'on' once Auto clean has redrawn it, None for every other file."""
    if score.regrid and score.regrid.get("cleaned"):
        return "on"
    if score.played_live and pathlib.Path(score.path).suffix.lower() not in MUSICXML_SUFFIXES:
        return "off"
    return None


def playable_state(score: Score) -> dict | None:
    """Sheet → This sheet's Clean button for a MIDI file: {"on", "summary", "warning"}:
    what Clean changed, or where the hands are asked for what they can't play (a warning over
    the sheet). None for a file that is notation already."""
    from . import playable

    if pathlib.Path(score.path).suffix.lower() in MUSICXML_SUFFIXES:
        return None
    if score.clean:
        return {"on": True, "summary": score.clean["summary"], "warning": None}
    bars = playable.unplayable_bars(score)
    return {"on": False, "summary": None, "warning": (
        f"In {playable._bars_text(bars)} a hand is asked for more than it can play (a chord too wide, "
        "or a key two parts play at once). Clean makes the parts fit two hands.") if bars else None}


SHEET_WARNINGS = {
    "off": ("No steady beat in this file (it was probably played live), so the bar lines and rhythms "
            "in this sheet are rough. Auto clean follows the playing to find a beat and redraws it."),
    "on": ("Auto-cleaned: the beat was guessed from the playing, so check the rhythms by ear. "
           "The notes still play and are graded at their real times."),
}


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is still
    # listening, so requests reach whichever one Windows picks. Without it a
    # busy port raises and start() moves on to the next one.
    allow_reuse_address = os.name != "nt"


def roll_notes(score: Score) -> list[list]:
    """The notes for the coach page's falling-notes view, as [beat, length in beats, pitch, role]
    with the role the Playing menu shows and hides (right, left, pedals, vocals, a named part,
    or 'track:<index>' for a backing track: the page draws those only when shown). Drums are
    left out, as on the sheet."""
    from .analysis import side_resolver
    from .notes import HAND_ROLES, effective_roles, playable_parts, select_notes

    drums = {p.index for p in score.parts if p.drums}
    length = lambda n: round(max(0.05, score.beat_of(n.end) - n.beat), 3)  # noqa: E731
    if score.playing:  # a named part: its notes, as drawn on its sheet, and the backing
        mine = {p.index for p in score.parts if score.roles.get(p.index) == score.playing}
        return ([[round(n.beat, 3), length(n), n.pitch, score.playing] for n in select_notes(score, score.playing)[0]] +
                [[round(n.beat, 3), length(n), n.pitch, f"track:{n.part}"] for n in score.notes
                 if n.part not in mine and n.part not in drums and not is_hand(score.roles.get(n.part))])
    roles = effective_roles(score) or {p.index: "both" for p in playable_parts(score)}
    side = side_resolver(score)
    out = []
    for n in score.notes:
        role = roles.get(n.part)
        if role is None:
            if n.part in drums:
                continue
            role = f"track:{n.part}"
        elif role in HAND_ROLES:
            role = side(n)
        out.append([round(n.beat, 3), length(n), n.pitch, role])
    return out


def is_hand(role: str | None) -> bool:
    """A hand's or the feet's or the singer's part (not drawn beside a named part's sheet)."""
    from .notes import ROLES

    return role in ROLES


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
        self.started: float | None = None  # when the server opened its port; the launcher compares it with the code
        self.score_path: str | None = None
        self._score_key: tuple | None = None
        self._xml_cache: dict[str, str] = {}
        self._score_payload: dict | None = None
        self._version = 0
        self._marks: dict[tuple[float, int], str] = {}
        self._heat: list[dict] | None = None
        self._aids: dict | None = None  # labels the coach put on bars (aids.py)
        self._status = ""
        self._cursor: dict | None = None
        self._cursor_at = 0.0  # time.monotonic() of the last cursor message
        self._lesson: dict | None = None
        self._lesson_version = 0
        self._session: dict = {"type": "session", "active": False}
        self._practice: dict | None = None
        self._atlas: dict | None = None
        # name -> callable(body: dict) -> dict, for the coach page's POST /cmd/<name>
        self.commands: dict = {}
        # callable(audio: bytes) -> dict, for POST /voice (push-to-talk recordings)
        self.voice_handler = None
        # callable(audio: bytes) -> {heard}, for POST /voice/transcribe (an answer said aloud, no chat)
        self.transcribe_handler = None
        # The YouTube extension's last command: {seen: time.time(), version} (version None before 1.1)
        self.extension: dict | None = None
        # callable(version) run on each of its commands, to remember it across restarts
        self.extension_hook = None

    # -- server ------------------------------------------------------------

    def start(self) -> str:
        if self._server:
            return self.url
        hub = self
        base = int(os.environ.get("MIDI_COACH_DISPLAY_PORT") or DEFAULT_PORT)
        last_exc: Exception | None = None
        for port in range(base, base + 10):
            try:
                self._server = _Server(("127.0.0.1", port), _make_handler(hub))
                break
            except OSError as exc:
                last_exc = exc
        else:
            raise RuntimeError(f"Could not open display server port ({last_exc})")
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/"
        self.started = time.time()
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
        from . import details, lessons, sheet

        # A new part choice, a backing track shown or hidden, turning Auto clean or Clean on or off,
        # or new details redraws the sheet.
        key = (score.path, tuple(sorted(score.roles.items())), score.playing, score.regrid is not None, details.stamp(score.path),
               score.clean is not None, tuple(sheet.shown_backing(score)))
        if key == self._score_key and self._score_payload:
            return
        notice = sheet_problem(score)
        xml = None if notice else self.sheet_xml(score)
        staves = sheet.staves(score) if xml else []
        offered = bool(xml) and details.offered(score.path)
        if offered:
            xml = details.apply(xml, details.load(score.path), staves, score)
        first = score.bars[0] if score.bars else None
        bars = [{"number": bar.number, "start_beat": round(bar.start_beat, 4), "end_beat": round(bar.end_beat, 4)}
                for bar in score.bars]
        # The metronome's Match score / Follow score need a real beat grid.
        tempo = None if score.played_live or not first else {
            "bpm": round(score.bpm_at(first.start), 2), "beats": first.numerator, "type": first.denominator}
        cleanup = cleanup_state(score) if xml else None
        playable = playable_state(score) if xml else None
        notes = roll_notes(score)
        with self._lock:
            self._version += 1
            new_piece = score.path != self.score_path
            if new_piece:
                self._aids = None
            self.score_path = score.path
            self._score_key = key
            self._score_payload = {"version": self._version, "title": pathlib.Path(score.path).stem, "path": score.path, "xml": xml,
                                   "notice": notice, "warning": SHEET_WARNINGS.get(cleanup), "cleanup": cleanup, "playable": playable,
                                   "details": details.status(score.path) if offered else None,
                                   "grid": not score.played_live, "tempo": tempo, "staves": staves, "bars": bars,
                                   "notes": notes, "playlist": lessons.playlist_position(score.path)}
            self._marks.clear()
            self._heat = None
            self._cursor = None
            self._status = ""
        self._broadcast(self._score_message(score.path))
        if new_piece:  # the labels were for the last piece's bars
            self._broadcast({"type": "aids", "bars": [], "off": False})

    def _score_message(self, path: str) -> dict:
        """The page's "score" event: a new sheet, with how its Session was last set up
        (library.practice_settings), which the page puts back when the piece changes."""
        from . import library
        return {"type": "score", "version": self._version, "title": pathlib.Path(path).stem, "path": path,
                "practice": library.practice_settings(path)}

    def sheet_xml(self, score: Score) -> str | None:
        """What to draw for a score: a piano sheet of the chosen parts for band arrangements and
        re-gridded files, the file itself (converted if MIDI) otherwise; None if it can't be drawn."""
        from . import sheet

        if sheet_problem(score):
            return None
        return sheet.piano_xml(score) if sheet.wanted(score) else self.xml_for(score.path)

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

    def aids(self, bars: list[dict], off: bool = False) -> None:
        """The bars the coach labels for this player, [{bar, start, end, kinds}] with kinds from
        "names" (note names) and "counts" (counting); the page shows them at its Labels level.
        off: no labels at all, whatever that level is (a mock exam)."""
        msg = {"type": "aids", "bars": list(bars), "off": off}
        with self._lock:
            self._aids = msg
        self._broadcast(msg)

    def cursor(self, beat: float, beats_per_sec: float = 0.0, live: bool = False, until: float | None = None) -> None:
        """live=True: a practice session drives the cursor (the visualizer then lets it
        override Learn Mode's own scrolling); otherwise it's just positioning.
        until: the cursor moves at beats_per_sec from beat and parks there (Learn mode
        flowing through a rest to the chord it waits for)."""
        msg = {"type": "cursorBeat", "beat": round(beat, 4), "bps": round(beats_per_sec, 4), "live": live}
        if until is not None:
            msg["until"] = round(until, 4)
        with self._lock:
            self._cursor = msg
            self._cursor_at = time.monotonic()
        self._broadcast(msg)

    def cursor_beat(self) -> float | None:
        """Where the cursor is now: its last position carried on at its speed, for at most two
        seconds so a cursor nobody updates any more doesn't run off. None before any cursor."""
        with self._lock:
            cur, at = self._cursor, self._cursor_at
        if not cur:
            return None
        beat = cur["beat"] + cur["bps"] * min(time.monotonic() - at, 2.0)
        return min(beat, cur["until"]) if "until" in cur else beat

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

    def practice(self, state: dict) -> None:
        """Coach page menu state: running, settings, port, pass number, last pass summary."""
        msg = {"type": "practice", **state}
        with self._lock:
            self._practice = msg
        self._broadcast(msg)

    def atlas(self, state: dict) -> None:
        """The Atlas's state for the coach page: the step being practised, the last verdict,
        the active Path (replayed to pages that connect later)."""
        msg = {"type": "atlas", **state}
        with self._lock:
            self._atlas = msg
        self._broadcast(msg)

    def metronome(self, grid: dict | None) -> None:
        """Have the coach page's metronome click a run: {start_in, bars: [{t, len, beats, accent}]}
        for a score, or {start_in, bpm, beats, count_in_beats} for an open-ended recording.
        None stops it. Not replayed to pages that connect later."""
        self._broadcast({"type": "metronome", **(grid or {"stop": True})})

    def keys(self, held: list[int]) -> None:
        """The keys held down on the keyboard now, while a run listens to it (the falling-notes
        view lights them). Not replayed to pages that connect later."""
        self._broadcast({"type": "keys", "on": sorted(held)})

    def sound(self, notes: list | None) -> None:
        """Have the coach page play notes itself ([[start sec, length sec, pitch, velocity], ...],
        a flute profile's examples), or stop them (None). Not replayed to pages that connect later."""
        self._broadcast({"type": "sound", "notes": notes} if notes is not None else {"type": "sound", "stop": True})

    def page(self, changes: dict) -> int:
        """Have the coach page change its own controls ({view, show, labels, zoom_percent, ...}, the
        Maestro's page_control), as if clicked. Not replayed to pages that connect later. Returns
        how many pages were connected to do it."""
        self._broadcast({"type": "page", **changes})
        return self.clients

    def songs_added(self, songs: list[dict]) -> None:
        """New songs turned up in the song folders or Downloads (songwatch.py): [{title, path,
        folder}]. The page refreshes its Songs list and offers to open them. Not replayed."""
        self._broadcast({"type": "songs_added", "songs": songs})

    def flash(self, text: str, hint: str | None = None) -> None:
        """A short message over the sheet (a wrong key's name). hint: the key(s) to play instead,
        shown only at Sheet ▸ Labels ▸ Easy."""
        msg = {"type": "flash", "text": text}
        if hint:
            msg["hint"] = hint
        self._broadcast(msg)

    def say(self, text: str, interrupt: bool = False, speaker: str = "Claude") -> int:
        """Have the coach page speak a line (and show it in its dialogue box, under the
        speaker's name). Not replayed to pages that connect later. Returns how many pages
        were connected to hear it. The line also goes in today's transcript (the Maestro panel)."""
        self.line(speaker, text)
        self._broadcast({"type": "say", "text": text, "interrupt": interrupt, "speaker": speaker})
        return self.clients

    def line(self, who: str, text: str, kind: str = "", link: str = "") -> None:
        """Add a line to today's transcript and show it in every page's Maestro panel (with a
        link under it, opened in the browser, when given)."""
        entry = transcript.add(who, text, kind, link)
        if entry:
            self._broadcast({"type": "line", **entry})

    def status(self, text: str) -> None:
        with self._lock:
            self._status = text
        self._broadcast({"type": "status", "text": text})

    def snapshot(self) -> list[dict]:
        with self._lock:
            # A page that connects late gets the latest lesson, but never auto-started.
            lesson = [{"type": "lesson", "version": self._lesson_version, "title": self._lesson.get("title"), "autostart": False}] if self._lesson else []
            practice = [self._practice] if self._practice else []
            practice += [self._atlas] if self._atlas else []
            if not self._score_payload:
                return lesson + practice + [{"type": "status", "text": "Pick a lesson, or ask the Maestro for one."}]
            out = [self._score_message(self._score_payload["path"])] + lesson + practice + [self._session]
            if self._marks:
                out.append({"type": "marks", "reset": True, "marks": [{"beat": b, "pitch": p, "status": s} for (b, p), s in self._marks.items()]})
            if self._heat:
                out.append({"type": "heat", "bars": self._heat})
            if self._aids:
                out.append(self._aids)
            if self._cursor:
                cur = {**self._cursor, "bps": 0.0}
                if "until" in cur:  # mid-glide: a late page parks at the waiting chord
                    cur["beat"] = cur.pop("until")
                out.append(cur)
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

        def _from_extension(self) -> None:
            """Note a command from the YouTube extension (its worker's requests carry its origin)."""
            version = self.headers.get("X-Piano-Coach-Extension")
            if not version and not (self.headers.get("Origin") or "").startswith(("chrome-extension://", "extension://")):
                return
            hub.extension = {"seen": time.time(), "version": version}
            if hub.extension_hook:
                try:
                    hub.extension_hook(version)
                except OSError:
                    pass

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            voice = {"/voice": hub.voice_handler, "/voice/transcribe": hub.transcribe_handler}.get(path)
            if voice:
                length = min(int(self.headers.get("Content-Length") or 0), 20_000_000)
                try:
                    result = voice(self.rfile.read(length))
                except Exception as exc:
                    result = {"error": str(exc)}
                return self._send(400 if "error" in result else 200, json.dumps(result).encode(), "application/json")
            handler = hub.commands.get(path[len("/cmd/"):]) if path.startswith("/cmd/") else None
            self._from_extension()
            if handler is None:
                return self._send(404, b'{"error":"unknown command"}', "application/json")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                result = handler(body)
            except Exception as exc:  # report to the page instead of dropping the connection
                result = {"error": str(exc)}
            code = 400 if isinstance(result, dict) and "error" in result else 200
            self._send(code, json.dumps(result).encode(), "application/json")

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/events":
                return self._events()
            if path in ("/tts", "/tts/voices"):
                return self._tts(path)
            if path == "/version":  # for midi_coach.launch: is this copy older than the code on disk?
                return self._send(200, json.dumps({"started": hub.started, "pid": os.getpid()}).encode(), "application/json")
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
            if path == "/file":  # File → Download: the sheet on the page, as the file it was loaded from
                return self._download()
            if path in STATIC_FILES:
                file, ctype = STATIC_FILES[path]
                try:
                    return self._send(200, file.read_bytes(), ctype)
                except OSError:
                    pass
            self._send(404, b"not found", "text/plain")

        def _download(self) -> None:
            file = pathlib.Path(hub.score_path) if hub.score_path else None
            try:
                data = file.read_bytes() if file else None
            except OSError:
                data = None
            if data is None:
                return self._send(404, b'{"error":"no score loaded"}', "application/json")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file.name)}")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _tts(self, path: str) -> None:
            """Kokoro speech for the coach page; 404 tells the page to use the browser's voices."""
            from . import tts

            if path == "/tts/voices":
                found = tts.voices()
                if found:
                    tts.warm_up()
                return self._send(200 if found else 404, json.dumps({"voices": found}).encode(), "application/json")
            query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            try:
                wav = tts.speak_wav(
                    query.get("text", [""])[0],
                    query.get("voice", [tts.DEFAULT_VOICE])[0],
                    float(query.get("speed", ["1"])[0]),
                )
            except tts.Unavailable as exc:
                return self._send(404, json.dumps({"error": str(exc)}).encode(), "application/json")
            except Exception as exc:
                return self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            self._send(200, wav, "audio/wav")

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
