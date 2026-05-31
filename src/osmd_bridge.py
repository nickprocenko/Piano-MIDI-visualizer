"""OSMD-based sheet music bridge using a pywebview subprocess overlay.

Converts a MIDI file to MusicXML via music21 and renders it with
OpenSheetMusicDisplay (OSMD) inside a transparent, frameless pywebview
window that sits on top of the main pygame display.

Playback position is forwarded each frame via evaluate_js so the JS
animation loop scrolls the score in sync with MIDI.

Requires: pywebview (already in requirements.txt), music21 (new dep).
Falls back silently if either library is absent.
"""

from __future__ import annotations

import json
import multiprocessing
import pathlib
from typing import Optional

_DEPS_AVAILABLE = False
try:
    import webview  # type: ignore  # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError:
    pass

_HTML_PATH  = pathlib.Path(__file__).parent / "static" / "sheet_music.html"
_OSMD_JS    = pathlib.Path(__file__).parent / "static" / "opensheetmusicdisplay.min.js"


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
    """Run inside the webview child process."""
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

    Usage:
        bridge = OsmdBridge(wx, wy, sw, sh)
        bridge.load_midi(path, enabled_tracks)      # once per file
        bridge.update_position(current_ms)          # each frame
        bridge.destroy()                            # on teardown
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
        self._queue:   Optional[multiprocessing.Queue] = None  # type: ignore[type-arg]

        if not _DEPS_AVAILABLE:
            return
        if not _HTML_PATH.exists() or not _OSMD_JS.exists():
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

    def load_midi(
        self,
        midi_path: pathlib.Path,
        enabled_tracks: Optional[set[int]] = None,
    ) -> None:
        """Convert *midi_path* to MusicXML and send it to the OSMD webview."""
        if not self._enabled:
            return
        xml = _midi_to_musicxml(midi_path, enabled_tracks)
        if xml:
            self._put_js(f"typeof loadScore!=='undefined'&&loadScore({json.dumps(xml)})")

    def update_position(self, current_ms: float) -> None:
        """Forward the MIDI playback position (ms) to the scrolling overlay."""
        if not self._enabled:
            return
        self._put_js(f"typeof updatePosition!=='undefined'&&updatePosition({current_ms:.1f})")

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
# MIDI → MusicXML conversion
# ---------------------------------------------------------------------------

def _midi_to_musicxml(
    midi_path: pathlib.Path,
    enabled_tracks: Optional[set[int]] = None,
) -> Optional[str]:
    """Convert a MIDI file to a MusicXML string using music21.

    Returns None on any error (import failure, parse error, etc.).
    """
    try:
        import music21  # type: ignore

        score = music21.converter.parse(str(midi_path))

        # Filter to only the requested tracks (music21 Parts correspond to
        # MIDI tracks; indices may not match exactly for Type-0 files, but
        # the best-effort selection is still useful).
        if enabled_tracks is not None and hasattr(score, "parts") and len(score.parts) > 1:
            parts_to_keep = [
                part for i, part in enumerate(score.parts)
                if i in enabled_tracks
            ]
            if parts_to_keep:
                new_score = music21.stream.Score()
                for part in parts_to_keep:
                    new_score.append(part)
                score = new_score

        from music21.musicxml.m21ToXml import GeneralObjectExporter  # type: ignore
        xml_bytes: bytes = GeneralObjectExporter(score).parse()
        return xml_bytes.decode("utf-8")

    except Exception as exc:
        import sys
        print(f"[OsmdBridge] MusicXML conversion failed: {exc}", file=sys.stderr)
        return None
