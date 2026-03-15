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
        fullscreen = bool(cfg.load().get("display_style", {}).get("fullscreen", True))
        info = pygame.display.Info()
        if fullscreen:
            screen = pygame.display.set_mode(
                (info.current_w, info.current_h),
                pygame.NOFRAME | pygame.FULLSCREEN,
            )
        else:
            screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
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
