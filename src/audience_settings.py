"""Audience control settings screen."""

from __future__ import annotations

import pygame
from src import config as cfg

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

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 22
VALUE_FONT_SIZE = 20
BTN_FONT_SIZE = 26

ROW_H = 64
ROW_GAP = 10
BACK_W = 160
BACK_H = 52
PANEL_MARGIN_X = 26


class AudienceSettingsScreen:
    """Settings for app-side audience WebSocket control client."""

    TEXT_FIELDS = [
        ("ws_url", "WebSocket URL", 180),
        ("channel_id", "Channel ID", 64),
        ("app_api_key", "App API Key", 256),
    ]

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values: dict[str, str | bool | float] = {}
        self._hover_back = False
        self._hover_enable = False
        self._active_field = -1
        self._cursor: int = 0

        self._title_pos = (0, 0)
        self._panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._enable_rect = pygame.Rect(0, 0, 28, 28)
        self._field_rects: list[pygame.Rect] = []

        self._load()
        self._build_layout()
        self._apply_cursor_hover()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._active_field = -1
            return "back"

        # Navigation when not actively typing into a field.
        if event.type == pygame.KEYDOWN and self._active_field < 0:
            _nav = len(self.TEXT_FIELDS) + 2
            if event.key == pygame.K_UP:
                self._cursor = (self._cursor - 1) % _nav
                self._apply_cursor_hover()
                return None
            if event.key == pygame.K_DOWN:
                self._cursor = (self._cursor + 1) % _nav
                self._apply_cursor_hover()
                return None
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                if self._cursor == 0:
                    self._values["enabled"] = not bool(self._values["enabled"])
                    self._save()
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                result = self._cursor_confirm()
                if result is not None:
                    return result
                return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._enable_rect.collidepoint(event.pos):
                self._values["enabled"] = not bool(self._values["enabled"])
                self._save()
                return None

            self._active_field = -1
            for i, rect in enumerate(self._field_rects):
                if rect.collidepoint(event.pos):
                    self._active_field = i
                    break
            return None

        if event.type == pygame.KEYDOWN and self._active_field >= 0:
            if event.key == pygame.K_BACKSPACE:
                key, _label, _max_len = self.TEXT_FIELDS[self._active_field]
                self._values[key] = str(self._values[key])[:-1]
                self._save()
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
                self._active_field = (self._active_field + 1) % len(self.TEXT_FIELDS)
                return None

        if event.type == pygame.TEXTINPUT and self._active_field >= 0:
            key, _label, max_len = self.TEXT_FIELDS[self._active_field]
            cur = str(self._values[key])
            if len(cur) < max_len:
                self._values[key] = cur + event.text
                self._save()
            return None

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_panel()
        self._draw_back()

    def _load(self) -> None:
        data = cfg.load().get("audience_control", {})
        self._values = {
            "enabled": bool(data.get("enabled", False)),
            "ws_url": str(data.get("ws_url", "wss://example.com/ws/app")),
            "channel_id": str(data.get("channel_id", "")),
            "app_api_key": str(data.get("app_api_key", "")),
            "reconnect_sec": float(data.get("reconnect_sec", 2.0)),
        }

    def _save(self) -> None:
        data = cfg.load()
        data["audience_control"] = {
            "enabled": bool(self._values["enabled"]),
            "ws_url": str(self._values["ws_url"]),
            "channel_id": str(self._values["channel_id"]),
            "app_api_key": str(self._values["app_api_key"]),
            "reconnect_sec": float(self._values["reconnect_sec"]),
        }
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Audience Settings", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)
        self._title_surf = title_surf

        content_top = title_y + title_surf.get_height() + 20
        content_bottom = sr.height - BACK_H - 34
        self._panel = pygame.Rect(PANEL_MARGIN_X, content_top, sr.width - 2 * PANEL_MARGIN_X, max(200, content_bottom - content_top))

        y = self._panel.top + 18
        self._enable_rect = pygame.Rect(self._panel.left + 16, y, 28, 28)
        y += 44

        self._field_rects = []
        for _ in self.TEXT_FIELDS:
            rect = pygame.Rect(self._panel.left + 16, y, self._panel.width - 32, ROW_H)
            self._field_rects.append(rect)
            y += ROW_H + ROW_GAP

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_enable = self._enable_rect.collidepoint(pos)

    def _apply_cursor_hover(self) -> None:
        n = len(self.TEXT_FIELDS)
        self._hover_enable = (self._cursor == 0)
        self._hover_back = (self._cursor == n + 1)
        if 1 <= self._cursor <= n:
            self._active_field = self._cursor - 1
        else:
            self._active_field = -1

    def _cursor_confirm(self) -> str | None:
        n = len(self.TEXT_FIELDS)
        if self._cursor == 0:
            self._values["enabled"] = not bool(self._values["enabled"])
            self._save()
        elif 1 <= self._cursor <= n:
            self._active_field = self._cursor - 1
        elif self._cursor == n + 1:
            self._active_field = -1
            return "back"
        return None

    def _draw_title(self) -> None:
        self.screen.blit(self._title_surf, self._title_pos)

    def _draw_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._panel, width=1, border_radius=8)

        cb_bg = (45, 45, 60) if self._hover_enable else (35, 35, 45)
        pygame.draw.rect(self.screen, cb_bg, self._enable_rect, border_radius=5)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._enable_rect, width=1, border_radius=5)
        if bool(self._values["enabled"]):
            pygame.draw.rect(self.screen, CHECK_ON_COLOR, self._enable_rect.inflate(-8, -8), border_radius=3)

        en_label = self._label_font.render("Enable Audience Live Color Control", True, TEXT_COLOR)
        self.screen.blit(en_label, (self._enable_rect.right + 10, self._enable_rect.top + 2))

        for i, (key, label, _max_len) in enumerate(self.TEXT_FIELDS):
            rect = self._field_rects[i]
            active = i == self._active_field
            bg = BUTTON_HOVER_BG if active else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=6)

            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (rect.left + 10, rect.top + 6))

            raw = str(self._values[key])
            shown = raw if key != "app_api_key" else ("*" * len(raw) if raw else "")
            text = self._clip_text(shown, rect.width - 20)
            val_surf = self._value_font.render(text, True, MUTED_TEXT_COLOR)
            self.screen.blit(val_surf, (rect.left + 10, rect.top + 32))

        hint = self._value_font.render("Click a field and type. BACKSPACE deletes. TAB jumps field.", True, MUTED_TEXT_COLOR)
        self.screen.blit(hint, (self._panel.left + 16, self._panel.bottom - 28))

    def _clip_text(self, text: str, max_w: int) -> str:
        if self._value_font.render(text, True, (0, 0, 0)).get_width() <= max_w:
            return text
        out = text
        while len(out) > 1:
            out = out[1:]
            prefixed = "..." + out
            if self._value_font.render(prefixed, True, (0, 0, 0)).get_width() <= max_w:
                return prefixed
        return text[-1:]

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
