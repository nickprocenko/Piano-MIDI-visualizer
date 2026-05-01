"""Display settings screen for global projector sizing and fullscreen mode."""

from __future__ import annotations

import pygame

from src import config as cfg
from src.piano import Piano


BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
TEXT_COLOR = (210, 210, 210)
MUTED_TEXT_COLOR = (150, 150, 150)
PANEL_BG = (22, 22, 30)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 24
VALUE_FONT_SIZE = 22
BTN_FONT_SIZE = 26

ROW_H = 64
BACK_W = 160
BACK_H = 52
SLIDER_H = 8
KNOB_R = 9

PANEL_MARGIN_X = 26
PANEL_GAP = 16


class DisplaySettingsScreen:
    """Settings UI for global display layout only."""

    _PREVIEW_ACTIVE_NOTES = {48, 52, 55, 60, 64, 67, 72}
    FIELD = ("width_scale_percent", "Highway Width Scale", 60, 80, 1, "%")

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values: dict[str, int | bool] = {}
        self._preview_keyboard_height: int = 18
        self._preview_keyboard_brightness: int = 100
        self._preview_highway_surf: pygame.Surface | None = None
        self._preview_piano: Piano | None = None
        self._preview_hw_size: tuple[int, int] = (0, 0)

        self._hover_back = False
        self._hover_slider = False
        self._drag_slider = False
        self._hover_fullscreen = False

        self._title_pos = (0, 0)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._row_rect = pygame.Rect(0, 0, 0, 0)
        self._slider_rect = pygame.Rect(0, 0, 0, 0)
        self._fullscreen_rect = pygame.Rect(0, 0, 0, 0)
        self._preview_rect = pygame.Rect(0, 0, 0, 0)

        self._load()
        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            if self._drag_slider:
                self._set_slider_from_x(event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"
            if self._fullscreen_rect.collidepoint(event.pos):
                return "toggle_fullscreen"
            if self._slider_rect.inflate(0, 18).collidepoint(event.pos):
                self._drag_slider = True
                self._set_slider_from_x(event.pos[0])
                return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = False

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_left_panel()
        self._draw_right_panel()
        self._draw_back()

    def _load(self) -> None:
        conf = cfg.load()
        data = conf.get("display_style", {})
        keyboard = conf.get("keyboard_style", {})
        width_scale = int(data.get("width_scale_percent", 66))
        width_scale = max(60, min(80, width_scale))
        self._values = {
            "width_scale_percent": width_scale,
            "fullscreen": bool(data.get("fullscreen", True)),
        }
        self._preview_keyboard_height = int(keyboard.get("height_percent", 18))
        self._preview_keyboard_brightness = int(keyboard.get("brightness", 100))

    def _save(self) -> None:
        data = cfg.load()
        display_style = data.setdefault("display_style", {})
        display_style["width_scale_percent"] = int(self._values["width_scale_percent"])
        display_style["fullscreen"] = bool(self._values["fullscreen"])
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Display Settings", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)
        self._title_surf = title_surf

        content_top = title_y + title_surf.get_height() + 20
        content_bottom = sr.height - BACK_H - 34
        content_h = max(200, content_bottom - content_top)

        content_w = sr.width - 2 * PANEL_MARGIN_X
        half_w = (content_w - PANEL_GAP) // 2

        self._left_panel = pygame.Rect(PANEL_MARGIN_X, content_top, half_w, content_h)
        self._right_panel = pygame.Rect(
            self._left_panel.right + PANEL_GAP, content_top, half_w, content_h
        )

        self._row_rect = pygame.Rect(
            self._left_panel.left + 12,
            self._left_panel.top + 14,
            self._left_panel.width - 24,
            ROW_H,
        )
        self._slider_rect = pygame.Rect(
            self._row_rect.left + 6,
            self._row_rect.bottom - 18,
            self._row_rect.width - 12,
            SLIDER_H,
        )
        self._fullscreen_rect = pygame.Rect(
            self._left_panel.left + 12,
            self._row_rect.bottom + 18,
            self._left_panel.width - 24,
            44,
        )
        self._preview_rect = pygame.Rect(
            self._right_panel.left + 12,
            self._right_panel.top + 12,
            self._right_panel.width - 24,
            self._right_panel.height - 24,
        )
        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_slider = self._slider_rect.inflate(0, 18).collidepoint(pos)
        self._hover_fullscreen = self._fullscreen_rect.collidepoint(pos)

    def _set_slider_from_x(self, mouse_x: int) -> None:
        rect = self._slider_rect
        key, _label, min_v, max_v, step, _suffix = self.FIELD
        if rect.width <= 1:
            return
        ratio = (mouse_x - rect.left) / float(rect.width)
        ratio = max(0.0, min(1.0, ratio))
        raw_value = min_v + ratio * (max_v - min_v)
        stepped = int(round(raw_value / step) * step)
        new_v = max(min_v, min(max_v, stepped))
        if new_v == self._values[key]:
            return
        self._values[key] = new_v
        self._save()

    def _draw_title(self) -> None:
        self.screen.blit(self._title_surf, self._title_pos)

    def _draw_left_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._left_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._left_panel, width=1, border_radius=8)

        key, label, min_v, max_v, _step, suffix = self.FIELD
        row = self._row_rect
        slider = self._slider_rect

        pygame.draw.rect(self.screen, BG_COLOR, row, border_radius=6)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row, width=1, border_radius=6)

        label_surf = self._label_font.render(label, True, TEXT_COLOR)
        self.screen.blit(label_surf, (row.left + 10, row.top + 7))

        value_surf = self._value_font.render(f"{self._values[key]}{suffix}", True, MUTED_TEXT_COLOR)
        self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

        track_color = BUTTON_HOVER_BG if self._hover_slider or self._drag_slider else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, track_color, slider, border_radius=4)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

        ratio = (int(self._values[key]) - min_v) / float(max(1, max_v - min_v))
        fill_rect = pygame.Rect(slider.left, slider.top, max(1, int(slider.width * ratio)), slider.height)
        pygame.draw.rect(self.screen, (0, 180, 180), fill_rect, border_radius=4)

        knob_x = int(slider.left + ratio * slider.width)
        knob_center = (knob_x, slider.centery)
        pygame.draw.circle(self.screen, (210, 210, 210), knob_center, KNOB_R)
        pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, knob_center, KNOB_R, width=1)

        fs = bool(self._values.get("fullscreen", True))
        fs_label = "WINDOWED MODE" if fs else "FULLSCREEN MODE"
        fs_active_bg = (0, 80, 80) if not self._hover_fullscreen else (0, 110, 110)
        fs_inactive_bg = BUTTON_HOVER_BG if self._hover_fullscreen else BUTTON_NORMAL_BG
        fs_bg = fs_active_bg if not fs else fs_inactive_bg
        pygame.draw.rect(self.screen, fs_bg, self._fullscreen_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._fullscreen_rect, width=1, border_radius=8)
        fs_surf = self._value_font.render(
            fs_label,
            True,
            BUTTON_HOVER_TEXT_COLOR if self._hover_fullscreen else BUTTON_TEXT_COLOR,
        )
        self.screen.blit(fs_surf, fs_surf.get_rect(center=self._fullscreen_rect.center))

        note = self._value_font.render("Theme media and timing now live under Themes.", True, MUTED_TEXT_COLOR)
        self.screen.blit(note, (self._left_panel.left + 14, self._fullscreen_rect.bottom + 14))

    def _draw_right_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._right_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._right_panel, width=1, border_radius=8)

        pr = self._preview_rect
        pygame.draw.rect(self.screen, (10, 10, 14), pr, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, pr, width=1, border_radius=8)

        scale = int(self._values["width_scale_percent"])
        kb_full_w = pr.width
        kb_scaled_w = max(1, int(kb_full_w * (scale / 100.0)))
        highway_rect = pygame.Rect(
            pr.left + (kb_full_w - kb_scaled_w) // 2,
            pr.top,
            kb_scaled_w,
            pr.height,
        )

        prev_clip = self.screen.get_clip()
        self.screen.set_clip(pr)
        pygame.draw.rect(self.screen, (14, 16, 22), highway_rect)
        pygame.draw.rect(self.screen, (82, 88, 104), highway_rect, width=1)

        self._ensure_preview_highway(highway_rect.width, highway_rect.height)
        if self._preview_highway_surf is not None:
            self._preview_highway_surf.fill((0, 0, 0, 0))
            lane = pygame.Surface((highway_rect.width, highway_rect.height), pygame.SRCALPHA)
            band_h = max(2, highway_rect.height // 14)
            for i in range(14):
                y = i * band_h
                h = highway_rect.height - y if i == 13 else band_h
                alpha = 26 + i * 4
                pygame.draw.rect(lane, (10, 12, 18, min(110, alpha)), pygame.Rect(0, y, highway_rect.width, h))
            self._preview_highway_surf.blit(lane, (0, 0))
            if self._preview_piano is not None:
                self._preview_piano.draw(set(self._PREVIEW_ACTIVE_NOTES))
            self.screen.blit(self._preview_highway_surf, highway_rect.topleft)
        self.screen.set_clip(prev_clip)

        title = self._value_font.render("Preview", True, TEXT_COLOR)
        self.screen.blit(title, (pr.left + 10, pr.top + 8))
        cap = self._label_font.render(f"Highway width: {scale}%", True, MUTED_TEXT_COLOR)
        self.screen.blit(cap, (pr.left + 10, pr.top + 36))

    def _ensure_preview_highway(self, width: int, height: int) -> None:
        size = (max(1, width), max(1, height))
        if self._preview_highway_surf is not None and self._preview_hw_size == size:
            return
        self._preview_hw_size = size
        self._preview_highway_surf = pygame.Surface(size, pygame.SRCALPHA)
        self._preview_piano = Piano(
            self._preview_highway_surf,
            height_percent=max(5, min(50, self._preview_keyboard_height)),
            brightness_percent=max(10, min(150, self._preview_keyboard_brightness)),
            visible=True,
        )

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
