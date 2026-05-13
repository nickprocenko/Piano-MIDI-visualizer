"""WebGL fluid simulation bridge via a pywebview subprocess overlay.

Instead of running the fluid simulation using Python moderngl, this module
spawns a lightweight pywebview subprocess that renders the same Navier-Stokes
fluid simulation using native WebGL2 in the OS browser engine (WebView2 on
Windows, WKWebView on macOS, WebKitGTK on Linux).

The subprocess window is transparent, frameless, and always-on-top so it
naturally overlays the main pygame window without any pixel read-back.
Splat commands are forwarded to the browser via ``window.evaluate_js()``.

Architecture
------------
* ``FluidWebBridge`` (main process) puts small JS snippets into a
  ``multiprocessing.Queue``.
* ``_fluid_subprocess_main`` (child process) drains that queue on a
  background thread and calls ``window.evaluate_js()`` so the running
  WebGL simulation receives the commands.
* ``cfg.xxx = value`` assignments in JS update the live simulation
  parameters; ``addSplat(...)`` injects velocity and dye blobs.

If pywebview is not installed every public method is a silent no-op and
the rest of the app continues as if fluid is disabled.
"""

from __future__ import annotations

import multiprocessing
import pathlib
from typing import Optional

_DEPS_AVAILABLE = False
try:
    import webview  # type: ignore  # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError:
    pass

# Absolute path to the bundled fluid simulation HTML page.
_HTML_PATH = pathlib.Path(__file__).parent / "static" / "fluid.html"


# ---------------------------------------------------------------------------
# Subprocess entry point (module-level so multiprocessing can pickle it)
# ---------------------------------------------------------------------------

def _fluid_subprocess_main(
    queue: multiprocessing.Queue,  # type: ignore[type-arg]
    html_url: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    """Run inside the webview child process.

    Creates a transparent overlay window, starts a queue-drain thread that
    forwards JS snippets from the parent, then starts the blocking webview
    event loop.
    """
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
                    # Sentinel: shut down the window.
                    try:
                        window.destroy()
                    except Exception:
                        pass
                    return
                try:
                    window.evaluate_js(js)
                except Exception:
                    pass

        drain_thread = threading.Thread(target=_drain, daemon=True)
        drain_thread.start()

        webview.start()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public bridge class
# ---------------------------------------------------------------------------

class FluidWebBridge:
    """Overlay-based WebGL fluid bridge.

    Spawns a transparent, frameless, always-on-top pywebview subprocess
    positioned over the main pygame window.  The WebGL2 simulation runs
    inside the browser engine; splats are injected via ``evaluate_js()``.

    Parameters
    ----------
    screen_x / screen_y
        Top-left screen coordinates of the pygame window (used to position
        the webview overlay).  Pass ``0, 0`` when the window is fullscreen
        or the position is unknown.
    screen_width / screen_height
        Pixel dimensions of the pygame display surface.
    curl_strength
        Vorticity confinement coefficient (higher → tighter swirls).
    vel_dissipation
        Velocity decay rate (higher → fades faster).
    dye_dissipation
        Dye/colour decay rate (higher → fades faster).
    pressure
        Pressure field retention factor per step (0 = reset, 1 = full).
    """

    def __init__(
        self,
        screen_x: int,
        screen_y: int,
        screen_width: int,
        screen_height: int,
        curl_strength: float = 30.0,
        vel_dissipation: float = 0.7,
        dye_dissipation: float = 2.2,
        pressure: float = 0.8,
    ) -> None:
        self._enabled = False
        self._process: Optional[multiprocessing.Process] = None
        self._queue: Optional[multiprocessing.Queue] = None  # type: ignore[type-arg]

        if not _DEPS_AVAILABLE:
            return

        if not _HTML_PATH.exists():
            return

        # 256 slots is enough to buffer ~4 seconds of splat commands at 60 fps
        # without blocking the pygame main loop if the webview falls behind.
        self._queue = multiprocessing.Queue(maxsize=256)
        self._process = multiprocessing.Process(
            target=_fluid_subprocess_main,
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

        # Push initial simulation config once the webview is up.
        # A small initial batch is safe: the queue will buffer until the
        # webview is ready to drain.
        self.update_config(curl_strength, vel_dissipation, dye_dissipation, pressure)

    # ------------------------------------------------------------------
    # Public API (mirrors FluidRenderer so app.py callers are unchanged)
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True while the webview subprocess is alive and running."""
        return (
            self._enabled
            and self._process is not None
            and self._process.is_alive()
        )

    def update_config(
        self,
        curl_strength: Optional[float] = None,
        vel_dissipation: Optional[float] = None,
        dye_dissipation: Optional[float] = None,
        pressure: Optional[float] = None,
    ) -> None:
        """Update one or more simulation parameters at runtime."""
        if not self._enabled:
            return
        parts: list[str] = []
        if curl_strength   is not None:
            parts.append(f"cfg.curlStrength={float(curl_strength):.4f}")
        if vel_dissipation is not None:
            parts.append(f"cfg.velDissipation={float(vel_dissipation):.4f}")
        if dye_dissipation is not None:
            parts.append(f"cfg.dyeDissipation={float(dye_dissipation):.4f}")
        if pressure        is not None:
            parts.append(f"cfg.pressure={float(pressure):.4f}")
        if parts:
            self._put_js(";".join(parts) + ";")

    def add_splat(
        self,
        norm_x: float,
        norm_y: float,
        vel_x: float,
        vel_y: float,
        r: float,
        g: float,
        b: float,
        radius: float = 0.012,
    ) -> None:
        """Inject a Gaussian blob of velocity + dye at a normalised position.

        ``norm_x`` / ``norm_y`` are in [0, 1] with (0, 0) at the top-left
        (pygame convention).  ``r``, ``g``, ``b`` are in [0, 1].
        """
        if not self._enabled:
            return
        js = (
            f"typeof addSplat!=='undefined'&&"
            f"addSplat({norm_x:.5f},{norm_y:.5f},"
            f"{vel_x:.4f},{vel_y:.4f},"
            f"{r:.4f},{g:.4f},{b:.4f},{radius:.5f});"
        )
        self._put_js(js)

    def step(self, dt_sec: float) -> None:
        """No-op: the webview drives its own ``requestAnimationFrame`` loop."""

    def get_surface(self) -> None:
        """Returns ``None``: fluid is rendered directly by the overlay window."""
        return None

    def destroy(self) -> None:
        """Send quit signal to the webview subprocess and wait for it to exit."""
        if not self._enabled:
            return
        self._enabled = False
        if self._queue is not None:
            try:
                self._queue.put_nowait(None)  # sentinel → window.destroy()
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
        """Drop the snippet into the IPC queue (non-blocking; drops on full)."""
        if self._queue is not None:
            try:
                self._queue.put_nowait(js)
            except Exception:
                pass  # queue full — silently drop
