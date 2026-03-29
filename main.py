import sys
import json
import time
import traceback
import platform
import pathlib
import pygame
from src.app import App


def _write_crash_report(exc: BaseException, app: App | None) -> pathlib.Path:
    logs_dir = pathlib.Path("crash_logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report_path = logs_dir / f"crash-{stamp}.log"

    snapshot: dict[str, object] = {}
    if app is not None:
        try:
            snapshot = app.get_debug_snapshot()
        except Exception as snap_exc:
            snapshot = {"snapshot_error": repr(snap_exc)}

    payload = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version,
        "platform": platform.platform(),
        "pygame": pygame.version.ver,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "app_snapshot": snapshot,
        "traceback": traceback.format_exc(),
    }
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return report_path


def main() -> None:
    app: App | None = None
    try:
        pygame.init()
        pygame.font.init()

        from src import config as cfg
        conf = cfg.load()
        display_style = conf.get("display_style", {})
        fullscreen = bool(display_style.get("fullscreen", True))
        sizes = pygame.display.get_desktop_sizes()
        default_idx = 1 if len(sizes) > 1 else 0
        display_idx = int(display_style.get("display_index", default_idx))
        if sizes:
            display_idx = max(0, min(len(sizes) - 1, display_idx))
        else:
            display_idx = 0

        if fullscreen:
            # True fullscreen on the configured monitor. This guarantees full
            # coverage (no "almost fullscreen" gaps on some Windows setups).
            modes = pygame.display.list_modes(display=display_idx)
            if modes and modes[0] != (-1, -1):
                w, h = modes[0]
            else:
                w, h = sizes[display_idx]
            screen = pygame.display.set_mode(
                (w, h),
                pygame.FULLSCREEN,
                display=display_idx,
            )
        else:
            # Windowed mode keeps the monitor's orientation/aspect to avoid
            # rotated or misaligned layouts on portrait/rotated displays.
            base_w, base_h = sizes[display_idx] if sizes else (1280, 720)
            win_w = max(800, int(base_w * 0.75))
            win_h = max(500, int(base_h * 0.75))
            screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE, display=display_idx)
        pygame.display.set_caption("Piano MIDI Visualizer")

        app = App(screen)
        app.run()
    except Exception as exc:
        report = _write_crash_report(exc, app)
        try:
            print(f"Crash report saved: {report}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
