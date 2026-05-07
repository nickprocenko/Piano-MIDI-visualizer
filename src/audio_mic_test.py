"""Dedicated microphone test screen for audio input flow."""

from __future__ import annotations

import array
import threading
import time

import pygame

# Colour palette (matches menu.py)
BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)

TITLE_FONT_SIZE = 42
BODY_FONT_SIZE = 24
BUTTON_FONT_SIZE = 30
TEST_WIDTH = 360
TEST_HEIGHT = 56
SELECT_WIDTH = 420
SELECT_HEIGHT = 56
BACK_WIDTH = 160
BACK_HEIGHT = 52
BUTTON_GAP = 14
METER_WIDTH = 540
METER_HEIGHT = 72


class AudioMicTestScreen:
    """Full-screen microphone test entry screen."""

    def __init__(self, screen: pygame.Surface, selected_device: int = -1) -> None:
        self.screen = screen
        self.selected_device: int = int(selected_device)
        self._status_text: str = ""
        self._status_until: float = 0.0
        self._permission_checked: bool = False
        self._monitor_active: bool = False
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._monitor_lock = threading.Lock()
        self._level_peak: int = 0
        self._level_smooth: float = 0.0
        self._meter_rect = pygame.Rect(0, 0, METER_WIDTH, METER_HEIGHT)
        self._diag_text: str = ""

        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._body_font = pygame.font.SysFont("Arial", BODY_FONT_SIZE)
        self._button_font = pygame.font.SysFont("Arial", BUTTON_FONT_SIZE)

        self._test_rect = pygame.Rect(0, 0, TEST_WIDTH, TEST_HEIGHT)
        self._select_rect = pygame.Rect(0, 0, SELECT_WIDTH, SELECT_HEIGHT)
        self._back_rect = pygame.Rect(0, 0, BACK_WIDTH, BACK_HEIGHT)

        self._hover_test: bool = False
        self._hover_select: bool = False
        self._hover_back: bool = False

        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)

        self._build_layout()

    def refresh(self) -> None:
        if not self._permission_checked:
            self._permission_checked = True
            self._prime_microphone_access()

    def update(self, _dt: int) -> None:
        with self._monitor_lock:
            self._level_smooth *= 0.95

    def close(self) -> None:
        self._stop_monitor()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._test_rect.collidepoint(event.pos):
                if self._monitor_active:
                    self._stop_monitor()
                else:
                    self._start_monitor()
                return None
            if self._select_rect.collidepoint(event.pos):
                return "audio_device_select"
            if self._back_rect.collidepoint(event.pos):
                return "back"
        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        if self._title_surf is not None:
            self.screen.blit(self._title_surf, self._title_pos)

        self._draw_body_text()
        self._draw_meter()
        test_label = "STOP MIC MONITOR" if self._monitor_active else "START MIC MONITOR"
        self._draw_button(self._test_rect, test_label, self._hover_test)
        self._draw_button(self._select_rect, "SELECT AUDIO DEVICE", self._hover_select)
        self._draw_button(self._back_rect, "BACK", self._hover_back)

        if self._status_text and time.monotonic() <= self._status_until:
            status_surf = self._body_font.render(self._status_text, True, BUTTON_TEXT_COLOR)
            self.screen.blit(
                status_surf,
                status_surf.get_rect(midtop=(self.screen.get_rect().centerx, self._back_rect.bottom + 6)),
            )

        if self._diag_text:
            diag_color = (150, 170, 190)
            diag_line = self._fit_text(self._diag_text, self.screen.get_rect().width - 40)
            diag_surf = self._body_font.render(diag_line, True, diag_color)
            self.screen.blit(
                diag_surf,
                diag_surf.get_rect(midtop=(self.screen.get_rect().centerx, self._back_rect.bottom + 34)),
            )

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title = self._title_font.render("Mic Test", True, TITLE_COLOR)
        title_y = sr.height // 7
        self._title_surf = title
        self._title_pos = (cx - title.get_width() // 2, title_y)

        y = title_y + title.get_height() + 58
        self._meter_rect = pygame.Rect(cx - METER_WIDTH // 2, y, METER_WIDTH, METER_HEIGHT)
        y += METER_HEIGHT + 26
        self._test_rect = pygame.Rect(cx - TEST_WIDTH // 2, y, TEST_WIDTH, TEST_HEIGHT)
        y += TEST_HEIGHT + BUTTON_GAP
        self._select_rect = pygame.Rect(cx - SELECT_WIDTH // 2, y, SELECT_WIDTH, SELECT_HEIGHT)
        y += SELECT_HEIGHT + 20
        self._back_rect = pygame.Rect(cx - BACK_WIDTH // 2, y, BACK_WIDTH, BACK_HEIGHT)

    def _draw_body_text(self) -> None:
        hint = "Open the mic monitor screen here, then choose your input device if needed."
        hint_surf = self._body_font.render(hint, True, BUTTON_TEXT_COLOR)
        hint_y = self._title_pos[1] + (self._title_surf.get_height() if self._title_surf else 0) + 20
        self.screen.blit(hint_surf, hint_surf.get_rect(centerx=self.screen.get_rect().centerx, y=hint_y))

    def _draw_meter(self) -> None:
        with self._monitor_lock:
            peak = self._level_peak
            smooth = self._level_smooth

        pygame.draw.rect(self.screen, BUTTON_NORMAL_BG, self._meter_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._meter_rect, width=1, border_radius=8)

        inner = self._meter_rect.inflate(-14, -26)
        pygame.draw.rect(self.screen, (25, 25, 34), inner, border_radius=5)

        ratio = max(0.0, min(1.0, smooth / 32767.0))
        fill_w = max(1, int(inner.width * ratio))
        fill = pygame.Rect(inner.left, inner.top, fill_w, inner.height)
        color = (0, 180, 180) if ratio < 0.75 else (230, 170, 40)
        pygame.draw.rect(self.screen, color, fill, border_radius=5)

        label = f"Level: {int(smooth):5d}   Peak: {peak:5d}"
        label_surf = self._body_font.render(label, True, BUTTON_TEXT_COLOR)
        self.screen.blit(label_surf, label_surf.get_rect(midtop=(self._meter_rect.centerx, self._meter_rect.bottom - 20)))

    def _draw_button(self, rect: pygame.Rect, label: str, hovered: bool) -> None:
        bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)
        surf = self._button_font.render(label, True, fg)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _fit_text(self, text: str, max_width: int) -> str:
        if self._body_font.size(text)[0] <= max_width:
            return text
        trimmed = text
        while trimmed and self._body_font.size(trimmed + "...")[0] > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + "...") if trimmed else "..."

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_test = self._test_rect.collidepoint(pos)
        self._hover_select = self._select_rect.collidepoint(pos)
        self._hover_back = self._back_rect.collidepoint(pos)

    def _start_monitor(self) -> None:
        try:
            import pyaudio  # noqa: PLC0415
        except Exception:
            self._set_status("Mic monitor unavailable: PyAudio missing")
            return

        if self._monitor_active:
            return

        self._monitor_stop.clear()
        self._monitor_active = True
        with self._monitor_lock:
            self._level_peak = 0
            self._level_smooth = 0.0
        self._monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self._monitor_thread.start()
        self._set_status("Mic monitor started")

    def _stop_monitor(self) -> None:
        if not self._monitor_active and self._monitor_thread is None:
            return
        self._monitor_stop.set()
        thread = self._monitor_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.7)
        self._monitor_thread = None
        self._monitor_active = False
        self._set_status("Mic monitor stopped")

    def _monitor_worker(self) -> None:
        try:
            import pyaudio  # noqa: PLC0415
        except Exception:
            self._set_status("Mic monitor unavailable: PyAudio missing")
            self._monitor_active = False
            return

        chunk_frames = 512

        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream, sample_rate, _channels, _device_index = self._open_input_stream_with_fallback(pa, chunk_frames)
            while not self._monitor_stop.is_set():
                raw = stream.read(chunk_frames, exception_on_overflow=False)
                samples = array.array("h")
                samples.frombytes(raw)
                local_peak = max((abs(v) for v in samples), default=0)
                with self._monitor_lock:
                    self._level_peak = max(self._level_peak, local_peak)
                    self._level_smooth = (self._level_smooth * 0.65) + (local_peak * 0.35)
        except Exception as exc:
            reason = str(exc).strip() or "device busy or unavailable"
            hint = self._windows_privacy_hint(reason)
            display = hint if hint else reason
            self._set_status(f"Mic monitor failed: {display}")
            self._diag_text = hint if hint else reason
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            pa.terminate()
            self._monitor_active = False

    def _prime_microphone_access(self) -> None:
        """Trigger OS mic permission prompt on this screen (one-time best effort)."""
        try:
            import pyaudio  # noqa: PLC0415
        except Exception:
            return

        pa = pyaudio.PyAudio()
        stream = None
        try:
            stream, _sample_rate, _channels, _device_index = self._open_input_stream_with_fallback(pa, 256)
            self._set_status("Microphone access ready")
            self._diag_text = "Input stream opened successfully"
        except Exception as exc:
            reason = str(exc).strip() or "Allow microphone access to enable voice commands"
            hint = self._windows_privacy_hint(reason)
            if hint:
                self._set_status(f"Mic blocked: {hint}")
                self._diag_text = hint
            else:
                self._set_status(f"Mic access issue: {reason}")
                self._diag_text = reason
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            pa.terminate()

    def _resolve_input_config(self, pa: object) -> tuple[int, int, int | None]:
        sample_rate = 16_000
        channels = 1
        device_index: int | None = self.selected_device if self.selected_device >= 0 else None

        try:
            if device_index is not None:
                info = pa.get_device_info_by_index(device_index)
            else:
                info = pa.get_default_input_device_info()
                device_index = int(info.get("index", -1))
                if device_index < 0:
                    device_index = None
            sample_rate = int(float(info.get("defaultSampleRate", sample_rate)))
            channels = max(1, min(int(info.get("maxInputChannels", 1) or 1), 2))
        except Exception:
            sample_rate = 16_000
            channels = 1

        return sample_rate, channels, device_index

    def _open_input_stream_with_fallback(
        self,
        pa: object,
        frames_per_buffer: int,
    ) -> tuple[object, int, int, int | None]:
        try:
            import pyaudio  # noqa: PLC0415
        except Exception as exc:
            raise RuntimeError("PyAudio missing") from exc

        default_rate, _default_channels, preferred_index = self._resolve_input_config(pa)
        candidate_indices = self._build_candidate_input_indices(pa, preferred_index)

        last_error = ""
        for candidate_index in candidate_indices:
            try:
                info = pa.get_device_info_by_index(candidate_index)
                device_name = str(info.get("name", "Unknown device"))
                resolved_index = int(info.get("index", -1))
                if resolved_index < 0:
                    resolved_index = -1
                max_in = int(info.get("maxInputChannels", 0) or 0)
                if max_in <= 0:
                    last_error = f"{device_name}: no input channels"
                    self._diag_text = last_error
                    continue

                channel_candidates = [1]
                if max_in >= 2:
                    channel_candidates.append(2)

                rate_candidates: list[int] = []
                for rate in (int(float(info.get("defaultSampleRate", default_rate))), default_rate, 48_000, 44_100, 16_000):
                    if rate > 0 and rate not in rate_candidates:
                        rate_candidates.append(rate)

                for channels in channel_candidates:
                    for rate in rate_candidates:
                        try:
                            stream = pa.open(
                                format=pyaudio.paInt16,
                                channels=channels,
                                rate=rate,
                                input=True,
                                input_device_index=resolved_index if resolved_index >= 0 else None,
                                frames_per_buffer=frames_per_buffer,
                            )
                            self._diag_text = f"Using {device_name} @ {rate}Hz {channels}ch"
                            return stream, rate, channels, (resolved_index if resolved_index >= 0 else None)
                        except Exception as exc:
                            err = str(exc).strip() or "cannot open selected input format"
                            last_error = f"{device_name} @ {rate}Hz {channels}ch: {err}"
                            self._diag_text = last_error
            except Exception as exc:
                last_error = str(exc).strip() or "cannot inspect selected input device"
                self._diag_text = last_error

        raise RuntimeError(last_error or "device busy or unavailable")

    def _build_candidate_input_indices(self, pa: object, preferred_index: int | None) -> list[int]:
        host_priority = {
            "windows wasapi": 0,
            "windows wdm-ks": 1,
            "windows directsound": 2,
            "mme": 3,
        }
        virtual_markers = (
            "voicemeeter",
            "cable",
            "vb-audio",
            "stereo mix",
            "mapper",
            "virtual",
        )

        def _tokens(name: str) -> set[str]:
            cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in name)
            words = {w for w in cleaned.split() if len(w) >= 4}
            return words - {"input", "output", "audio", "device", "point", "windows"}

        def _name_penalty(name: str) -> int:
            n = name.lower()
            if any(k in n for k in ("microphone", "mic", "array")):
                return 0
            if "input" in n:
                return 1
            if any(k in n for k in virtual_markers):
                return 4
            return 2

        preferred_name = ""
        preferred_tokens: set[str] = set()
        preferred_is_virtual = False
        if preferred_index is not None:
            try:
                pinfo = pa.get_device_info_by_index(preferred_index)
                preferred_name = str(pinfo.get("name", "")).strip().lower()
                preferred_tokens = _tokens(preferred_name)
                preferred_is_virtual = any(m in preferred_name for m in virtual_markers)
            except Exception:
                preferred_name = ""
                preferred_tokens = set()
                preferred_is_virtual = False

        host_names: dict[int, str] = {}
        try:
            for host_idx in range(pa.get_host_api_count()):
                try:
                    host_names[host_idx] = str(pa.get_host_api_info_by_index(host_idx).get("name", ""))
                except Exception:
                    host_names[host_idx] = ""
        except Exception:
            pass

        candidates: list[tuple[int, int]] = []
        try:
            for idx in range(int(pa.get_device_count())):
                try:
                    info = pa.get_device_info_by_index(idx)
                except Exception:
                    continue
                max_in = int(info.get("maxInputChannels", 0) or 0)
                if max_in <= 0:
                    continue

                host_idx = int(info.get("hostApi", -1))
                host_name = host_names.get(host_idx, "").strip().lower()
                host_score = host_priority.get(host_name, 5)
                name = str(info.get("name", "")).strip().lower()
                tokens = _tokens(name)
                overlap = len(tokens & preferred_tokens) if preferred_tokens else 0
                pref_bonus = -1000 if preferred_index is not None and idx == preferred_index else 0
                name_family_bonus = -220 if overlap > 0 else 0
                if preferred_name and (name in preferred_name or preferred_name in name):
                    name_family_bonus -= 120
                virtual_penalty = 0
                if any(m in name for m in virtual_markers) and not preferred_is_virtual:
                    virtual_penalty = 300
                penalty = _name_penalty(str(info.get("name", "")))
                score = (host_score * 10) + penalty + pref_bonus + name_family_bonus + virtual_penalty
                candidates.append((score, idx))
        except Exception:
            pass

        candidates.sort(key=lambda item: item[0])
        ordered: list[int] = [idx for _score, idx in candidates]
        if preferred_index is not None and preferred_index not in ordered:
            ordered.insert(0, preferred_index)

        # Keep attempts bounded on systems with many virtual endpoints.
        return ordered[:20]

    def _set_status(self, text: str, duration_sec: float = 4.0) -> None:
        self._status_text = text
        self._status_until = time.monotonic() + duration_sec

    @staticmethod
    def _windows_privacy_hint(reason: str) -> str:
        """Return an actionable hint when the error looks like a Windows mic privacy block."""
        lower = reason.lower()
        if any(kw in lower for kw in ("9999", "unanticipated", "unknown", "access denied", "access is denied")):
            return "Check: Windows Settings \u2192 Privacy \u2192 Microphone \u2192 allow desktop apps"
        return ""
