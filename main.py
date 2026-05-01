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


def _try_gl_display(size, base_flags, disp_idx):
    """Try to create an OpenGL display + moderngl context.

    Returns (gl_screen, gl_ctx, ui_surf) on success, or None on failure.
    ui_surf is a plain pygame.Surface used for all pygame drawing.
    """
    try:
        import moderngl
        gl_screen = pygame.display.set_mode(
            size,
            base_flags | pygame.OPENGL | pygame.DOUBLEBUF,
            display=disp_idx,
        )
        gl_ctx = moderngl.create_context()
        ui_surf = pygame.Surface(size)
        return gl_screen, gl_ctx, ui_surf
    except Exception as exc:
        print(f"[gl] OpenGL unavailable, falling back to CPU renderer: {exc}")
        return None


def main() -> None:
    app: App | None = None
    try:
        pygame.init()
        pygame.font.init()

        from src import config as cfg
        fullscreen = bool(cfg.load().get("display_style", {}).get("fullscreen", True))

        gl_ctx = None
        ui_surf = None

        if fullscreen:
            # Borderless fullscreen on the second monitor when available.
            # NOFRAME at native resolution avoids the exclusive-focus behaviour of
            # pygame.FULLSCREEN, so clicking on monitor 1 won't minimise the window.
            sizes = pygame.display.get_desktop_sizes()
            disp_idx = 1 if len(sizes) > 1 else 0
            w, h = sizes[disp_idx]
            result = _try_gl_display((w, h), pygame.NOFRAME, disp_idx)
            if result is not None:
                _, gl_ctx, ui_surf = result
            else:
                pygame.display.set_mode((w, h), pygame.NOFRAME, display=disp_idx)
        else:
            result = _try_gl_display((1280, 720), pygame.RESIZABLE, 0)
            if result is not None:
                _, gl_ctx, ui_surf = result
            else:
                pygame.display.set_mode((1280, 720), pygame.RESIZABLE)

        pygame.display.set_caption("Piano MIDI Visualizer")

        screen = ui_surf if ui_surf is not None else pygame.display.get_surface()
        app = App(screen, gl_ctx=gl_ctx)
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
