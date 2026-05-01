"""Audio input device selection screen."""

from __future__ import annotations

import pygame

# Colour palette (matches menu.py)
BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)
NO_DEVICE_COLOR = (150, 150, 150)

TITLE_FONT_SIZE = 42
ITEM_FONT_SIZE = 26
BACK_FONT_SIZE = 30
ITEM_WIDTH = 600
ITEM_HEIGHT = 52
ITEM_GAP = 14
BACK_WIDTH = 160
BACK_HEIGHT = 52
SCROLL_STEP = 48


class AudioDeviceSelect:
    """Full-screen audio input device selection screen."""

    def __init__(self, screen: pygame.Surface, selected_device: int = -1) -> None:
        self.screen = screen
        self.selected_device: int = int(selected_device)
        self._scan_error: str = ""

        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._item_font = pygame.font.SysFont("Arial", ITEM_FONT_SIZE)
        self._back_font = pygame.font.SysFont("Arial", BACK_FONT_SIZE)

        self._devices: list[tuple[int, str]] = []
        self._item_rects: list[pygame.Rect] = []
        self._back_rect = pygame.Rect(0, 0, BACK_WIDTH, BACK_HEIGHT)
        self._list_view_rect = pygame.Rect(0, 0, 0, 0)
        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._list_top_y: int = 0
        self._scroll_offset: int = 0
        self._max_scroll: int = 0

        self._hover_item: int = -1
        self._hover_back: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-scan available audio input devices and rebuild the layout."""
        self._devices = self._list_input_devices()
        self._scroll_offset = 0
        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "back"
            if event.key == pygame.K_UP:
                self._set_scroll(self._scroll_offset - SCROLL_STEP)
                return None
            if event.key == pygame.K_DOWN:
                self._set_scroll(self._scroll_offset + SCROLL_STEP)
                return None

        if event.type == pygame.MOUSEWHEEL:
            self._set_scroll(self._scroll_offset - (event.y * SCROLL_STEP))
            self._update_hover(pygame.mouse.get_pos())
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"
            for i, rect in enumerate(self._item_rects):
                if rect.collidepoint(event.pos):
                    self.selected_device = self._devices[i][0]
                    return "select"

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_devices()
        self._draw_back()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _list_input_devices(self) -> list[tuple[int, str]]:
        devices: list[tuple[int, str]] = [(-1, "System Default Input Device")]
        self._scan_error = ""
        try:
            import pyaudio  # noqa: PLC0415

            pa = pyaudio.PyAudio()
            try:
                default_input_idx = -1
                try:
                    default_info = pa.get_default_input_device_info()
                    default_input_idx = int(default_info.get("index", -1))
                except Exception:
                    default_input_idx = -1

                host_api_names: dict[int, str] = {}
                try:
                    for host_idx in range(pa.get_host_api_count()):
                        try:
                            host_api_names[host_idx] = str(
                                pa.get_host_api_info_by_index(host_idx).get("name", "Unknown API")
                            )
                        except Exception:
                            host_api_names[host_idx] = "Unknown API"
                except Exception:
                    pass

                device_count = int(pa.get_device_count())
                for idx in range(device_count):
                    try:
                        info = pa.get_device_info_by_index(idx)
                    except Exception:
                        continue

                    if int(info.get("maxInputChannels", 0) or 0) <= 0:
                        continue

                    host_api_idx = int(info.get("hostApi", -1))
                    host_api_name = host_api_names.get(host_api_idx, "Unknown API")
                    name = str(info.get("name", f"Input Device {idx}"))
                    default_tag = " (default)" if idx == default_input_idx else ""
                    devices.append((idx, f"{name}{default_tag}  [{host_api_name}]"))
            finally:
                pa.terminate()
        except Exception:
            self._scan_error = "PyAudio could not enumerate input devices."
        return devices

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Select Audio Input", True, TITLE_COLOR)
        title_y = sr.height // 8
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        start_y = title_y + title_surf.get_height() + 40
        self._list_top_y = start_y
        back_y = sr.height - BACK_HEIGHT - 24
        list_bottom = back_y - 24
        list_height = max(ITEM_HEIGHT, list_bottom - start_y)
        self._list_view_rect = pygame.Rect(
            cx - ITEM_WIDTH // 2,
            start_y,
            ITEM_WIDTH,
            list_height,
        )

        total_content_h = max(0, len(self._devices) * (ITEM_HEIGHT + ITEM_GAP) - ITEM_GAP)
        self._max_scroll = max(0, total_content_h - self._list_view_rect.height)
        self._scroll_offset = max(0, min(self._max_scroll, self._scroll_offset))

        y = start_y - self._scroll_offset
        self._item_rects = []
        for _ in self._devices:
            rect = pygame.Rect(cx - ITEM_WIDTH // 2, y, ITEM_WIDTH, ITEM_HEIGHT)
            self._item_rects.append(rect)
            y += ITEM_HEIGHT + ITEM_GAP

        self._back_rect = pygame.Rect(
            cx - BACK_WIDTH // 2, back_y, BACK_WIDTH, BACK_HEIGHT
        )

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_item = -1
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(pos):
                self._hover_item = i
                break

    def _draw_title(self) -> None:
        if self._title_surf is not None:
            self.screen.blit(self._title_surf, self._title_pos)

    def _draw_devices(self) -> None:
        if not self._devices:
            sr = self.screen.get_rect()
            msg = self._item_font.render(
                "No audio input devices found.",
                True,
                NO_DEVICE_COLOR,
            )
            title_bottom = self._title_pos[1] + (self._title_surf.get_height() if self._title_surf else 0)
            self.screen.blit(msg, (sr.centerx - msg.get_width() // 2, title_bottom + 50))
            return

        if len(self._devices) == 1:
            sr = self.screen.get_rect()
            info_text = self._scan_error or "Only default device is available from current audio drivers."
            info_surf = self._item_font.render(info_text, True, NO_DEVICE_COLOR)
            title_bottom = self._title_pos[1] + (self._title_surf.get_height() if self._title_surf else 0)
            self.screen.blit(info_surf, (sr.centerx - info_surf.get_width() // 2, title_bottom + 8))

        clip_prev = self.screen.get_clip()
        self.screen.set_clip(self._list_view_rect)
        for i, rect in enumerate(self._item_rects):
            if rect.bottom < self._list_view_rect.top or rect.top > self._list_view_rect.bottom:
                continue
            hovered = i == self._hover_item
            bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
            fg = BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR
            pygame.draw.rect(self.screen, bg, rect, border_radius=8)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)
            prefix = "* " if self._devices[i][0] == self.selected_device else ""
            label_text = self._fit_label(prefix + self._devices[i][1], rect.width - 20)
            label = self._item_font.render(label_text, True, fg)
            self.screen.blit(label, label.get_rect(center=rect.center))
        self.screen.set_clip(clip_prev)

    def _set_scroll(self, new_offset: int) -> None:
        self._scroll_offset = max(0, min(self._max_scroll, int(new_offset)))
        self._build_layout()

    def _fit_label(self, text: str, max_width: int) -> str:
        if self._item_font.size(text)[0] <= max_width:
            return text
        trimmed = text
        while trimmed and self._item_font.size(trimmed + "...")[0] > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + "...") if trimmed else "..."

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        label = self._back_font.render("BACK", True, fg)
        self.screen.blit(label, label.get_rect(center=self._back_rect.center))
