"""Audience control settings screen — WebSocket + Kick.com chat."""

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
KICK_COLOR = (83, 252, 31)          # Kick brand green
SECTION_COLOR = (160, 160, 180)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 22
VALUE_FONT_SIZE = 20
BTN_FONT_SIZE = 26
SECTION_FONT_SIZE = 18

ROW_H = 64
ROW_GAP = 10
BACK_W = 160
BACK_H = 52
PANEL_MARGIN_X = 26
PANEL_GAP = 16


class AudienceSettingsScreen:
    """Settings for WebSocket audience control and Kick.com chat LED control."""

    WS_FIELDS = [
        ("ws_url", "WebSocket URL", 180),
        ("channel_id", "Channel ID", 64),
        ("app_api_key", "App API Key", 256),
    ]

    # Total interactive field count: 3 WS fields + 1 Kick slug field
    _WS_FIELD_COUNT = 3
    _KICK_FIELD_INDEX = 3   # slug is the 4th field (index 3) for TAB cycling

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font  = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font  = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font  = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font    = pygame.font.SysFont("Arial", BTN_FONT_SIZE)
        self._section_font = pygame.font.SysFont("Arial", SECTION_FONT_SIZE, bold=True)

        self._ws_values: dict[str, str | bool | float] = {}
        self._kick_values: dict[str, str | bool | int] = {}

        self._hover_back    = False
        self._hover_ws_en   = False
        self._hover_kick_en = False
        self._active_field  = -1   # 0-2 → WS fields, 3 → Kick slug

        self._title_pos = (0, 0)
        self._title_surf: pygame.Surface | None = None
        self._ws_panel   = pygame.Rect(0, 0, 0, 0)
        self._kick_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect  = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._ws_enable_rect   = pygame.Rect(0, 0, 28, 28)
        self._kick_enable_rect = pygame.Rect(0, 0, 28, 28)
        self._ws_field_rects: list[pygame.Rect] = []
        self._kick_slug_rect = pygame.Rect(0, 0, 0, ROW_H)

        self._load()
        self._build_layout()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._ws_enable_rect.collidepoint(event.pos):
                self._ws_values["enabled"] = not bool(self._ws_values["enabled"])
                self._save()
                return None

            if self._kick_enable_rect.collidepoint(event.pos):
                self._kick_values["enabled"] = not bool(self._kick_values["enabled"])
                self._save()
                return None

            self._active_field = -1
            for i, rect in enumerate(self._ws_field_rects):
                if rect.collidepoint(event.pos):
                    self._active_field = i
                    return None
            if self._kick_slug_rect.collidepoint(event.pos):
                self._active_field = self._KICK_FIELD_INDEX
            return None

        if event.type == pygame.KEYDOWN and self._active_field >= 0:
            if event.key == pygame.K_BACKSPACE:
                self._delete_char()
                self._save()
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_TAB):
                total = self._WS_FIELD_COUNT + 1   # +1 for kick slug
                self._active_field = (self._active_field + 1) % total
                return None

        if event.type == pygame.TEXTINPUT and self._active_field >= 0:
            self._append_char(event.text)
            self._save()
            return None

        return None

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_ws_panel()
        self._draw_kick_panel()
        self._draw_back()

    # ------------------------------------------------------------------
    # Private: load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        data = cfg.load()
        wd = data.get("audience_control", {})
        self._ws_values = {
            "enabled":      bool(wd.get("enabled", False)),
            "ws_url":       str(wd.get("ws_url", "wss://example.com/ws/app")),
            "channel_id":   str(wd.get("channel_id", "")),
            "app_api_key":  str(wd.get("app_api_key", "")),
            "reconnect_sec": float(wd.get("reconnect_sec", 2.0)),
        }
        kd = data.get("kick_chat", {})
        self._kick_values = {
            "enabled":       bool(kd.get("enabled", False)),
            "channel_slug":  str(kd.get("channel_slug", "")),
            "transition_ms": int(kd.get("transition_ms", 600)),
        }

    def _save(self) -> None:
        data = cfg.load()
        data["audience_control"] = {
            "enabled":       bool(self._ws_values["enabled"]),
            "ws_url":        str(self._ws_values["ws_url"]),
            "channel_id":    str(self._ws_values["channel_id"]),
            "app_api_key":   str(self._ws_values["app_api_key"]),
            "reconnect_sec": float(self._ws_values["reconnect_sec"]),
        }
        data["kick_chat"] = {
            "enabled":       bool(self._kick_values["enabled"]),
            "channel_slug":  str(self._kick_values["channel_slug"]),
            "transition_ms": int(self._kick_values["transition_ms"]),
        }
        cfg.save(data)

    # ------------------------------------------------------------------
    # Private: layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Audience Settings", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)
        self._title_surf = title_surf

        content_top    = title_y + title_surf.get_height() + 20
        content_bottom = sr.height - BACK_H - 34
        total_h        = max(200, content_bottom - content_top)
        half_h         = (total_h - PANEL_GAP) // 2
        panel_w        = sr.width - 2 * PANEL_MARGIN_X

        # WebSocket panel (top half)
        self._ws_panel = pygame.Rect(PANEL_MARGIN_X, content_top, panel_w, half_h)
        y = self._ws_panel.top + 14
        self._ws_enable_rect = pygame.Rect(self._ws_panel.left + 16, y + 2, 28, 28)
        y += 44
        self._ws_field_rects = []
        for _ in self.WS_FIELDS:
            rect = pygame.Rect(self._ws_panel.left + 16, y, panel_w - 32, ROW_H)
            self._ws_field_rects.append(rect)
            y += ROW_H + ROW_GAP

        # Kick panel (bottom half)
        kick_top = self._ws_panel.bottom + PANEL_GAP
        self._kick_panel = pygame.Rect(PANEL_MARGIN_X, kick_top, panel_w,
                                        content_bottom - kick_top)
        y = self._kick_panel.top + 14
        self._kick_enable_rect = pygame.Rect(self._kick_panel.left + 16, y + 2, 28, 28)
        y += 44
        self._kick_slug_rect = pygame.Rect(
            self._kick_panel.left + 16, y, panel_w - 32, ROW_H
        )

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    # ------------------------------------------------------------------
    # Private: text editing helpers
    # ------------------------------------------------------------------

    def _delete_char(self) -> None:
        fi = self._active_field
        if fi < self._WS_FIELD_COUNT:
            key = self.WS_FIELDS[fi][0]
            self._ws_values[key] = str(self._ws_values[key])[:-1]
        elif fi == self._KICK_FIELD_INDEX:
            self._kick_values["channel_slug"] = str(self._kick_values["channel_slug"])[:-1]

    def _append_char(self, ch: str) -> None:
        fi = self._active_field
        if fi < self._WS_FIELD_COUNT:
            key, _label, max_len = self.WS_FIELDS[fi]
            cur = str(self._ws_values[key])
            if len(cur) < max_len:
                self._ws_values[key] = cur + ch
        elif fi == self._KICK_FIELD_INDEX:
            cur = str(self._kick_values["channel_slug"])
            if len(cur) < 64:
                self._kick_values["channel_slug"] = cur + ch

    # ------------------------------------------------------------------
    # Private: hover
    # ------------------------------------------------------------------

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back    = self._back_rect.collidepoint(pos)
        self._hover_ws_en   = self._ws_enable_rect.collidepoint(pos)
        self._hover_kick_en = self._kick_enable_rect.collidepoint(pos)

    # ------------------------------------------------------------------
    # Private: draw helpers
    # ------------------------------------------------------------------

    def _draw_title(self) -> None:
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)

    def _draw_ws_panel(self) -> None:
        panel = self._ws_panel
        pygame.draw.rect(self.screen, PANEL_BG, panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, panel, width=1, border_radius=8)

        # Section label
        sec = self._section_font.render("WEBSOCKET (custom server)", True, SECTION_COLOR)
        self.screen.blit(sec, (panel.left + 16, panel.top + 6))

        # Enable checkbox
        cb_bg = BUTTON_HOVER_BG if self._hover_ws_en else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, cb_bg, self._ws_enable_rect, border_radius=5)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._ws_enable_rect, width=1, border_radius=5)
        if bool(self._ws_values["enabled"]):
            pygame.draw.rect(self.screen, CHECK_ON_COLOR,
                             self._ws_enable_rect.inflate(-8, -8), border_radius=3)
        en_label = self._label_font.render("Enable WebSocket Color Control", True, TEXT_COLOR)
        self.screen.blit(en_label, (self._ws_enable_rect.right + 10, self._ws_enable_rect.top + 2))

        # Text fields
        for i, (key, label, _) in enumerate(self.WS_FIELDS):
            rect = self._ws_field_rects[i]
            active = i == self._active_field
            bg = BUTTON_HOVER_BG if active else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=6)
            self.screen.blit(self._label_font.render(label, True, TEXT_COLOR),
                             (rect.left + 10, rect.top + 6))
            raw = str(self._ws_values[key])
            shown = raw if key != "app_api_key" else ("*" * len(raw) if raw else "")
            val_surf = self._value_font.render(self._clip(shown, rect.width - 20), True, MUTED_TEXT_COLOR)
            self.screen.blit(val_surf, (rect.left + 10, rect.top + 32))

        hint = self._value_font.render(
            "Click a field and type. BACKSPACE deletes. TAB cycles.", True, MUTED_TEXT_COLOR
        )
        self.screen.blit(hint, (panel.left + 16, panel.bottom - 26))

    def _draw_kick_panel(self) -> None:
        panel = self._kick_panel
        pygame.draw.rect(self.screen, PANEL_BG, panel, border_radius=8)
        pygame.draw.rect(self.screen, KICK_COLOR, panel, width=1, border_radius=8)

        # Section label with Kick branding
        sec = self._section_font.render("KICK.COM CHAT  —  chat !color <name/hex/r g b>", True, KICK_COLOR)
        self.screen.blit(sec, (panel.left + 16, panel.top + 6))

        # Enable checkbox
        cb_bg = BUTTON_HOVER_BG if self._hover_kick_en else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, cb_bg, self._kick_enable_rect, border_radius=5)
        pygame.draw.rect(self.screen, KICK_COLOR, self._kick_enable_rect, width=1, border_radius=5)
        if bool(self._kick_values["enabled"]):
            pygame.draw.rect(self.screen, KICK_COLOR,
                             self._kick_enable_rect.inflate(-8, -8), border_radius=3)
        en_label = self._label_font.render("Enable Kick Chat Light Control", True, TEXT_COLOR)
        self.screen.blit(en_label, (self._kick_enable_rect.right + 10, self._kick_enable_rect.top + 2))

        # Channel slug field
        rect = self._kick_slug_rect
        active = self._active_field == self._KICK_FIELD_INDEX
        bg = BUTTON_HOVER_BG if active else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, bg, rect, border_radius=6)
        pygame.draw.rect(self.screen, KICK_COLOR if active else BUTTON_BORDER_COLOR,
                         rect, width=1, border_radius=6)
        self.screen.blit(self._label_font.render("Kick Channel Name (your username/slug)", True, TEXT_COLOR),
                         (rect.left + 10, rect.top + 6))
        slug = str(self._kick_values["channel_slug"]) or ""
        val_surf = self._value_font.render(self._clip(slug, rect.width - 20), True, MUTED_TEXT_COLOR)
        self.screen.blit(val_surf, (rect.left + 10, rect.top + 32))

        # Color command hint
        hint = self._value_font.render(
            "Commands: !color red  |  !color #FF0080  |  !color 255 0 128",
            True, MUTED_TEXT_COLOR,
        )
        self.screen.blit(hint, (panel.left + 16, panel.bottom - 26))

    def _clip(self, text: str, max_w: int) -> str:
        if self._value_font.render(text, True, (0, 0, 0)).get_width() <= max_w:
            return text
        out = text
        while len(out) > 1:
            out = out[1:]
            if self._value_font.render("..." + out, True, (0, 0, 0)).get_width() <= max_w:
                return "..." + out
        return text[-1:]

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
