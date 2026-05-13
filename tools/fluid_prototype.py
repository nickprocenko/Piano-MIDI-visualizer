from __future__ import annotations

import argparse
import functools
import math
from pathlib import Path
import sys
import threading
import time
from typing import Any

try:
    import webview
except ImportError as exc:  # pragma: no cover - import guard for local tool
    raise SystemExit(
        "pywebview is required for tools/fluid_prototype.py.\n"
        "Install dependencies with: pip install -r requirements.txt"
    ) from exc


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FLUID_HTML_PATH = PROJECT_ROOT / "src" / "static" / "fluid.html"


class FluidPrototypeRuntime:
    def __init__(self, duration_sec: float, splat_interval_sec: float) -> None:
        self.duration_sec = duration_sec
        self.splat_interval_sec = splat_interval_sec
        self.window: Any = None
        self.api = FluidPrototypeApi(self)
        self._stop = threading.Event()
        self._eval_lock = threading.Lock()
        self._launch_time = time.perf_counter()
        self._synthetic_index = 0
        self._capabilities_reported = False

    def bind_window(self, window: Any) -> None:
        self.window = window

    def start(self) -> None:
        print(f"Loading fluid prototype from {FLUID_HTML_PATH}")
        print("Interactive controls: click in the window, or press Space / Enter for a center splat.")
        print(
            f"Window will auto-close after {self.duration_sec:.0f} seconds; "
            f"synthetic splats fire every {self.splat_interval_sec:.1f} seconds."
        )
        self.inject_splat(
            norm_x=0.50,
            norm_y=0.50,
            vel_x=0.0,
            vel_y=-1200.0,
            color=(0.20, 0.75, 1.00),
            radius=0.032,
            source="startup",
        )
        threading.Thread(target=self._synthetic_loop, daemon=True).start()
        threading.Thread(target=self._auto_close_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def destroy_window(self) -> None:
        if self.window is None:
            return
        try:
            self.window.destroy()
        except Exception as exc:
            print(f"[prototype] window destroy failed: {exc}")

    def inject_splat(
        self,
        norm_x: float,
        norm_y: float,
        vel_x: float,
        vel_y: float,
        color: tuple[float, float, float] | None = None,
        radius: float = 0.020,
        source: str = "synthetic",
    ) -> None:
        if self.window is None or self._stop.is_set():
            return

        if color is None:
            color = self._color_for_index(self._synthetic_index)

        start = time.perf_counter()
        js = (
            f"typeof addSplat!=='undefined'&&"
            f"addSplat({float(norm_x):.5f},{float(norm_y):.5f},"
            f"{float(vel_x):.4f},{float(vel_y):.4f},"
            f"{float(color[0]):.4f},{float(color[1]):.4f},{float(color[2]):.4f},"
            f"{float(radius):.5f});"
        )
        try:
            with self._eval_lock:
                self.window.evaluate_js(js)
        except Exception as exc:
            print(f"[prototype] failed to inject {source} splat: {exc}")
            return

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        print(
            f"[prototype] {source:>10s} splat "
            f"at ({norm_x:.3f}, {norm_y:.3f}) "
            f"velocity=({vel_x:.0f}, {vel_y:.0f}) "
            f"eval_js={elapsed_ms:.2f} ms"
        )

    def report_capabilities(self, payload: dict[str, Any]) -> None:
        if self._capabilities_reported:
            return
        self._capabilities_reported = True
        startup_ms = (time.perf_counter() - self._launch_time) * 1000.0
        print("[prototype] renderer capabilities")
        print(f"  startup_ms            : {startup_ms:.1f}")
        print(f"  webgl2                : {payload.get('webgl2')}")
        print(f"  ext_color_buffer_float: {payload.get('extColorBufferFloat')}")
        print(f"  canvas                : {payload.get('width')}x{payload.get('height')}")
        print(f"  user_agent            : {payload.get('userAgent')}")

    def report_frame(self, now_ms: float, dt_ms: float, frame_count: int) -> None:
        fps = 1000.0 / max(dt_ms, 0.001)
        print(
            f"[prototype] frame #{frame_count:05d} "
            f"js_now={now_ms:9.2f} ms dt={dt_ms:6.2f} ms fps={fps:5.1f}"
        )

    def handle_input_splat(
        self,
        norm_x: float,
        norm_y: float,
        source: str,
        key_name: str,
        event_time_ms: float,
    ) -> dict[str, Any]:
        vx = 0.0
        vy = -1400.0 if source == "keyboard" else 0.0
        color = (1.00, 0.55, 0.18) if source == "keyboard" else (0.95, 0.30, 1.00)
        label = key_name or source
        print(
            f"[prototype] host input source={label} "
            f"norm=({norm_x:.3f}, {norm_y:.3f}) js_event_ms={event_time_ms:.2f}"
        )
        self.inject_splat(
            norm_x=norm_x,
            norm_y=norm_y,
            vel_x=vx,
            vel_y=vy,
            color=color,
            radius=0.025,
            source=f"input:{label}",
        )
        return {"ok": True, "source": label}

    def _synthetic_loop(self) -> None:
        if self._stop.wait(0.75):
            return
        while not self._stop.wait(self.splat_interval_sec):
            angle = self._synthetic_index * 0.85
            norm_x = 0.50 + 0.26 * math.cos(angle)
            norm_y = 0.50 + 0.18 * math.sin(angle * 1.35)
            vel_x = -math.sin(angle) * 1200.0
            vel_y = math.cos(angle * 1.35) * 900.0
            color = self._color_for_index(self._synthetic_index)
            self.inject_splat(
                norm_x=norm_x,
                norm_y=norm_y,
                vel_x=vel_x,
                vel_y=vel_y,
                color=color,
                radius=0.020,
                source="synthetic",
            )
            self._synthetic_index += 1

    def _auto_close_loop(self) -> None:
        if self._stop.wait(self.duration_sec):
            return
        print("[prototype] duration reached; closing window")
        self.destroy_window()

    @staticmethod
    def _color_for_index(index: int) -> tuple[float, float, float]:
        palette = (
            (0.20, 0.75, 1.00),
            (0.45, 1.00, 0.55),
            (1.00, 0.50, 0.22),
            (0.92, 0.30, 1.00),
            (1.00, 0.90, 0.25),
        )
        return palette[index % len(palette)]


class FluidPrototypeApi:
    def __init__(self, runtime: FluidPrototypeRuntime) -> None:
        self._runtime = runtime

    def report_capabilities(self, payload: dict[str, Any]) -> None:
        self._runtime.report_capabilities(payload)

    def report_frame(self, now_ms: float, dt_ms: float, frame_count: int) -> None:
        self._runtime.report_frame(now_ms, dt_ms, frame_count)

    def trigger_input_splat(
        self,
        norm_x: float,
        norm_y: float,
        source: str,
        key_name: str,
        event_time_ms: float,
    ) -> dict[str, Any]:
        return self._runtime.handle_input_splat(norm_x, norm_y, source, key_name, event_time_ms)


def _start_runtime(runtime: FluidPrototypeRuntime) -> None:
    runtime.start()


def _on_window_closed(runtime: FluidPrototypeRuntime) -> None:
    runtime.stop()
    print("[prototype] window closed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone pywebview fluid prototype.")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--duration", type=float, default=30.0, help="Seconds before auto-close.")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between synthetic splats.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable pywebview debug mode.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not FLUID_HTML_PATH.exists():
        raise SystemExit(f"Missing fluid page: {FLUID_HTML_PATH}")

    runtime = FluidPrototypeRuntime(
        duration_sec=max(1.0, args.duration),
        splat_interval_sec=max(0.1, args.interval),
    )

    window = webview.create_window(
        "Fluid Prototype",
        FLUID_HTML_PATH.resolve().as_uri(),
        width=max(320, args.width),
        height=max(240, args.height),
        resizable=False,
        transparent=False,
        background_color="#101014",
        js_api=runtime.api,
    )
    runtime.bind_window(window)

    try:
        window.events.closed += functools.partial(_on_window_closed, runtime)
    except Exception:
        pass

    webview.start(functools.partial(_start_runtime, runtime), debug=args.debug)


if __name__ == "__main__":
    main()
