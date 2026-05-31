"""OSMD-based sheet music bridge using a pywebview subprocess overlay.

Renders standard music notation via OpenSheetMusicDisplay (built from
nickprocenko/opensheetmusicdisplay) inside a transparent, frameless
pywebview window that overlays the main pygame display.

Accepts both:
  • MusicXML files directly (.xml / .musicxml / .mxl)
  • MIDI files — converted to MusicXML via music21

Playback position is forwarded each frame so the JS animation loop
scrolls the score in sync with MIDI.

Requires: pywebview (requirements.txt), music21 (requirements.txt).
Both are optional — the bridge falls back silently when absent.
"""

from __future__ import annotations

import json
import multiprocessing
import pathlib
from typing import Optional

_WEBVIEW_AVAILABLE = False
try:
    import webview  # type: ignore  # noqa: F401
    _WEBVIEW_AVAILABLE = True
except ImportError:
    pass

_MUSIC21_AVAILABLE = False
try:
    import music21  # type: ignore  # noqa: F401
    _MUSIC21_AVAILABLE = True
except ImportError:
    pass

_HTML_PATH = pathlib.Path(__file__).parent / "static" / "sheet_music.html"
_OSMD_JS   = pathlib.Path(__file__).parent / "static" / "opensheetmusicdisplay.min.js"

_MUSICXML_SUFFIXES = {".xml", ".musicxml", ".mxl"}


def is_musicxml(path: pathlib.Path) -> bool:
    return path.suffix.lower() in _MUSICXML_SUFFIXES


# ---------------------------------------------------------------------------
# Subprocess entry point
# ---------------------------------------------------------------------------

def _osmd_subprocess_main(
    queue: "multiprocessing.Queue[Optional[str]]",
    html_url: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    """Runs inside the webview child process."""
    try:
        import webview  # type: ignore
        import threading

        window = webview.create_window(
            title="",
            url=html_url,
            x=x,
            y=y,
            width=width,
            height=height,
            frameless=True,
            transparent=True,
            on_top=True,
            background_color="#00000000",
            easy_drag=False,
        )

        def _drain() -> None:
            while True:
                js: Optional[str] = queue.get()
                if js is None:
                    try:
                        window.destroy()
                    except Exception:
                        pass
                    return
                try:
                    window.evaluate_js(js)
                except Exception:
                    pass

        threading.Thread(target=_drain, daemon=True).start()
        webview.start()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public bridge class
# ---------------------------------------------------------------------------

class OsmdBridge:
    """Transparent pywebview overlay that renders sheet music via OSMD.

    Usage
    -----
    bridge = OsmdBridge(wx, wy, sw, sh)
    if bridge.available:
        bridge.load_file(path, enabled_tracks)   # once per file
        bridge.update_position(current_ms)       # every frame
    bridge.destroy()                             # on teardown
    """

    def __init__(
        self,
        screen_x: int,
        screen_y: int,
        screen_width: int,
        screen_height: int,
    ) -> None:
        self._enabled = False
        self._process: Optional[multiprocessing.Process] = None
        self._queue:   Optional[multiprocessing.Queue]   = None  # type: ignore[type-arg]
        self._frame_counter = 0

        if not _WEBVIEW_AVAILABLE:
            import sys
            print("[OsmdBridge] pywebview not available — sheet music disabled", file=sys.stderr)
            return
        if not _HTML_PATH.exists() or not _OSMD_JS.exists():
            import sys
            print(f"[OsmdBridge] HTML/JS assets missing at {_HTML_PATH.parent}", file=sys.stderr)
            return

        self._queue = multiprocessing.Queue(maxsize=128)
        self._process = multiprocessing.Process(
            target=_osmd_subprocess_main,
            args=(
                self._queue,
                _HTML_PATH.as_uri(),
                screen_x,
                screen_y,
                screen_width,
                screen_height,
            ),
            daemon=True,
        )
        self._process.start()
        self._enabled = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return (
            self._enabled
            and self._process is not None
            and self._process.is_alive()
        )

    def load_file(
        self,
        path: pathlib.Path,
        enabled_tracks: Optional[set[int]] = None,
    ) -> None:
        """Load a MusicXML or MIDI file and send it to the OSMD webview."""
        if not self._enabled:
            return

        if is_musicxml(path):
            xml = _read_musicxml(path)
        else:
            xml = _midi_to_musicxml(path, enabled_tracks)

        if xml:
            # Escape as a JSON string so the JS receives it safely
            self._put_js(
                f"typeof loadScore!=='undefined'&&loadScore({json.dumps(xml)})"
            )
        else:
            import sys
            print(f"[OsmdBridge] Could not produce MusicXML from {path.name}", file=sys.stderr)

    def update_position(self, current_ms: float) -> None:
        """Forward current MIDI playback position (ms) to the JS scroll loop.

        Throttled to every other frame to halve IPC overhead.
        """
        if not self._enabled:
            return
        self._frame_counter += 1
        if self._frame_counter & 1:  # send every 2nd frame (~30 Hz)
            return
        self._put_js(
            f"typeof updatePosition!=='undefined'&&updatePosition({current_ms:.1f})"
        )

    def destroy(self) -> None:
        """Shut down the webview subprocess."""
        if not self._enabled:
            return
        self._enabled = False
        if self._queue is not None:
            try:
                self._queue.put_nowait(None)
            except Exception:
                pass
        if self._process is not None:
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.kill()
            self._process = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _put_js(self, js: str) -> None:
        if self._queue is not None:
            try:
                self._queue.put_nowait(js)
            except Exception:
                pass  # queue full — drop silently


# ---------------------------------------------------------------------------
# MusicXML helpers
# ---------------------------------------------------------------------------

def _read_musicxml(path: pathlib.Path) -> Optional[str]:
    """Return the raw contents of a MusicXML file."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        import sys
        print(f"[OsmdBridge] Could not read {path}: {exc}", file=sys.stderr)
        return None


def _midi_to_musicxml(
    midi_path: pathlib.Path,
    enabled_tracks: Optional[set[int]] = None,
) -> Optional[str]:
    """Convert a MIDI file to MusicXML using music21.  Returns None on any error."""
    if not _MUSIC21_AVAILABLE:
        import sys
        print("[OsmdBridge] music21 not installed — cannot convert MIDI to MusicXML", file=sys.stderr)
        return None

    try:
        import music21  # type: ignore

        score = music21.converter.parse(str(midi_path))

        # Filter to only the requested tracks when specified.
        # music21 Parts roughly correspond to MIDI tracks with notes.
        if enabled_tracks is not None and hasattr(score, "parts") and len(score.parts) > 1:
            keep = [p for i, p in enumerate(score.parts) if i in enabled_tracks]
            if keep:
                new_score = music21.stream.Score()
                for p in keep:
                    new_score.append(p)
                score = new_score

        from music21.musicxml.m21ToXml import GeneralObjectExporter  # type: ignore
        xml_bytes: bytes = GeneralObjectExporter(score).parse()
        return xml_bytes.decode("utf-8")

    except Exception as exc:
        import sys
        print(f"[OsmdBridge] MIDI→MusicXML conversion failed: {exc}", file=sys.stderr)
        return None
