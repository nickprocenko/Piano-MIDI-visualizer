"""Keyboard visual settings screen."""

from __future__ import annotations

import pygame
from src import config as cfg

# Shared look
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
CHECK_ON_COLOR = (0, 180, 180)
PREVIEW_BG = (12, 12, 18)
PREVIEW_LINE = (70, 70, 90)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 24
VALUE_FONT_SIZE = 22
BTN_FONT_SIZE = 26

ROW_H = 64
ROW_GAP = 12
BACK_W = 160
BACK_H = 52
SLIDER_H = 8
KNOB_R = 9

PANEL_MARGIN_X = 26
PANEL_GAP = 16


class KeyboardSettingsScreen:
    """Settings UI for keyboard height/brightness and visibility."""

    FIELDS = [
        ("height_percent", "Keyboard Height", 8, 45, 1, "%"),
        ("brightness", "Keyboard Brightness", 15, 150, 5, "%"),
    ]

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values: dict[str, int | bool] = {}
        self._hover_back = False
        self._hover_slider: int = -1
        self._drag_slider: int = -1
        self._hover_checkbox = False
        self._hover_sustain = False

        self._title_pos = (0, 0)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._row_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect] = []
        self._checkbox_rect = pygame.Rect(0, 0, 28, 28)
        self._sustain_rect = pygame.Rect(0, 0, 28, 28)
        self._preview_rect = pygame.Rect(0, 0, 0, 0)

        self._load()
        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            if self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._checkbox_rect.collidepoint(event.pos):
                self._values["visible"] = not bool(self._values["visible"])
                self._save()
                return None

            if self._sustain_rect.collidepoint(event.pos):
                self._values["sustain_latch"] = not bool(self._values["sustain_latch"])
                self._save()
                return None

            for i, rect in enumerate(self._slider_rects):
                if rect.inflate(0, 18).collidepoint(event.pos):
                    self._drag_slider = i
                    self._set_slider_from_x(i, event.pos[0])
                    return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_rows()
        self._draw_checkbox_panel()
        self._draw_back()

    def _load(self) -> None:
        data = cfg.load().get("keyboard_style", {})
        self._values = {
            "height_percent": int(data.get("height_percent", 18)),
            "brightness": int(data.get("brightness", 100)),
            "visible": bool(data.get("visible", True)),
            "sustain_latch": bool(data.get("sustain_latch", False)),
        }

    def _save(self) -> None:
        data = cfg.load()
        data["keyboard_style"] = {
            "height_percent": int(self._values["height_percent"]),
            "brightness": int(self._values["brightness"]),
            "visible": bool(self._values["visible"]),
            "sustain_latch": bool(self._values["sustain_latch"]),
        }
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Keyboard Settings", True, TITLE_COLOR)
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

        self._row_rects = []
        self._slider_rects = []
        y = self._left_panel.top + 16
        row_w = self._left_panel.width - 24
        for _ in self.FIELDS:
            row = pygame.Rect(self._left_panel.left + 12, y, row_w, ROW_H)
            slider = pygame.Rect(row.left + 6, row.bottom - 18, row.width - 12, SLIDER_H)
            self._row_rects.append(row)
            self._slider_rects.append(slider)
            y += ROW_H + ROW_GAP

        cb_row = pygame.Rect(self._right_panel.left + 16, self._right_panel.top + 22, self._right_panel.width - 32, 56)
        self._checkbox_rect = pygame.Rect(cb_row.left + 8, cb_row.centery - 14, 28, 28)

        sustain_row = pygame.Rect(self._right_panel.left + 16, cb_row.bottom + 10, self._right_panel.width - 32, 56)
        self._sustain_rect = pygame.Rect(sustain_row.left + 8, sustain_row.centery - 14, 28, 28)

        self._preview_rect = pygame.Rect(
            self._right_panel.left + 16,
            sustain_row.bottom + 14,
            self._right_panel.width - 32,
            max(80, self._right_panel.height - (sustain_row.bottom - self._right_panel.top) - 30),
        )

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_checkbox = self._checkbox_rect.collidepoint(pos)
        self._hover_sustain = self._sustain_rect.collidepoint(pos)
        self._hover_slider = -1
        for i, rect in enumerate(self._slider_rects):
            if rect.inflate(0, 18).collidepoint(pos):
                self._hover_slider = i
                break

    def _set_slider_from_x(self, index: int, mouse_x: int) -> None:
        rect = self._slider_rects[index]
        key, _label, min_v, max_v, step, _suffix = self.FIELDS[index]
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

    def _draw_rows(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._left_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._left_panel, width=1, border_radius=8)

        for i, (key, label, _min_v, _max_v, _step, suffix) in enumerate(self.FIELDS):
            row = self._row_rects[i]
            slider = self._slider_rects[i]

            pygame.draw.rect(self.screen, BG_COLOR, row, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row, width=1, border_radius=6)

            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (row.left + 10, row.top + 7))

            val = f"{self._values[key]}{suffix}"
            value_surf = self._value_font.render(val, True, MUTED_TEXT_COLOR)
            self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

            track_color = BUTTON_HOVER_BG if i == self._hover_slider or i == self._drag_slider else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, track_color, slider, border_radius=4)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

            fill_ratio = self._value_ratio(i)
            fill_w = max(1, int(slider.width * fill_ratio))
            fill_rect = pygame.Rect(slider.left, slider.top, fill_w, slider.height)
            pygame.draw.rect(self.screen, (0, 180, 180), fill_rect, border_radius=4)

            knob_x = int(slider.left + fill_ratio * slider.width)
            knob_center = (knob_x, slider.centery)
            pygame.draw.circle(self.screen, (210, 210, 210), knob_center, KNOB_R)
            pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, knob_center, KNOB_R, width=1)

    def _draw_checkbox_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._right_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._right_panel, width=1, border_radius=8)

        title = self._label_font.render("Keyboard Options", True, TEXT_COLOR)
        self.screen.blit(title, (self._right_panel.left + 16, self._right_panel.top + 16))

        cb_bg = (45, 45, 60) if self._hover_checkbox else (35, 35, 45)
        pygame.draw.rect(self.screen, cb_bg, self._checkbox_rect, border_radius=5)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._checkbox_rect, width=1, border_radius=5)

        if bool(self._values["visible"]):
            inner = self._checkbox_rect.inflate(-8, -8)
            pygame.draw.rect(self.screen, CHECK_ON_COLOR, inner, border_radius=3)

        vis_text = "Show keyboard" if bool(self._values["visible"]) else "Hide keyboard (notes start at bottom)"
        label = self._value_font.render(vis_text, True, MUTED_TEXT_COLOR)
        self.screen.blit(label, (self._checkbox_rect.right + 12, self._checkbox_rect.top + 2))

        sus_bg = (45, 45, 60) if self._hover_sustain else (35, 35, 45)
        pygame.draw.rect(self.screen, sus_bg, self._sustain_rect, border_radius=5)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._sustain_rect, width=1, border_radius=5)
        if bool(self._values["sustain_latch"]):
            inner2 = self._sustain_rect.inflate(-8, -8)
            pygame.draw.rect(self.screen, CHECK_ON_COLOR, inner2, border_radius=3)
        sus_label = self._value_font.render("Sustain pedal latch", True, MUTED_TEXT_COLOR)
        self.screen.blit(sus_label, (self._sustain_rect.right + 12, self._sustain_rect.top + 2))

        self._draw_live_preview()

    def _draw_live_preview(self) -> None:
        pygame.draw.rect(self.screen, PREVIEW_BG, self._preview_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._preview_rect, width=1, border_radius=8)

        title = self._value_font.render("Live Preview", True, TEXT_COLOR)
        self.screen.blit(title, (self._preview_rect.left + 10, self._preview_rect.top + 8))

        visible = bool(self._values["visible"])
        height_percent = int(self._values["height_percent"])
        brightness_percent = int(self._values["brightness"])
        brightness = max(0.1, min(1.5, brightness_percent / 100.0))

        scene = self._preview_rect.inflate(-12, -38)
        scene.y += 24

        start_y = scene.bottom if not visible else scene.bottom - int(scene.height * (height_percent / 100.0))
        start_y = max(scene.top + 8, min(scene.bottom - 2, start_y))

        line_color = (
            max(0, min(255, int(PREVIEW_LINE[0] * brightness))),
            max(0, min(255, int(PREVIEW_LINE[1] * brightness))),
            max(0, min(255, int(PREVIEW_LINE[2] * brightness))),
        )
        pygame.draw.line(self.screen, line_color, (scene.left + 4, start_y), (scene.right - 4, start_y), width=2)

        note_rect = pygame.Rect(scene.centerx - 10, max(scene.top + 4, start_y - 72), 20, max(16, start_y - max(scene.top + 4, start_y - 72)))
        note_color = (0, int(190 * brightness), int(190 * brightness))
        pygame.draw.rect(self.screen, note_color, note_rect, border_radius=5)

        if visible:
            key_h = max(20, int(scene.height * (height_percent / 100.0)))
            kb_rect = pygame.Rect(scene.left + 4, scene.bottom - key_h, scene.width - 8, key_h)
            kb_bg = (
                max(0, min(255, int(40 * brightness))),
                max(0, min(255, int(40 * brightness))),
                max(0, min(255, int(50 * brightness))),
            )
            white = (
                max(0, min(255, int(220 * brightness))),
                max(0, min(255, int(220 * brightness))),
                max(0, min(255, int(220 * brightness))),
            )
            border = (
                max(0, min(255, int(70 * brightness))),
                max(0, min(255, int(70 * brightness))),
                max(0, min(255, int(70 * brightness))),
            )
            pygame.draw.rect(self.screen, kb_bg, kb_rect, border_radius=4)
            pygame.draw.rect(self.screen, border, kb_rect, width=1, border_radius=4)

            key_w = max(10, kb_rect.width // 10)
            for i in range(10):
                k = pygame.Rect(kb_rect.left + i * key_w, kb_rect.top, key_w - 1, kb_rect.height)
                pygame.draw.rect(self.screen, white, k)
                pygame.draw.rect(self.screen, border, k, width=1)

        mode = "Keyboard visible" if visible else "Keyboard hidden"
        mode_surf = self._value_font.render(mode, True, MUTED_TEXT_COLOR)
        self.screen.blit(mode_surf, (scene.left + 2, scene.top + 4))

    def _value_ratio(self, index: int) -> float:
        key, _label, min_v, max_v, _step, _suffix = self.FIELDS[index]
        span = max(1, max_v - min_v)
        return (int(self._values[key]) - min_v) / float(span)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
