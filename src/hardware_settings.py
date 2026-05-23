"""Hardware settings screen — sustain pedal and physical input behaviour."""

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
LABEL_FONT_SIZE = 24
SMALL_FONT_SIZE = 20
BTN_FONT_SIZE = 26
BACK_W = 160
BACK_H = 52
PANEL_W = 560
PANEL_MARGIN_X = 26


class HardwareSettingsScreen:
    """Settings screen for hardware input controls (sustain pedal, etc.)."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._small_font = pygame.font.SysFont("Arial", SMALL_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values: dict[str, bool] = {}
        self._hover_back = False
        self._hover_sustain = False

        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._panel_rect = pygame.Rect(0, 0, 0, 0)
        self._sustain_check_rect = pygame.Rect(0, 0, 28, 28)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)

        self._load()
        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"
            if self._sustain_check_rect.inflate(60, 12).collidepoint(event.pos):
                self._values["sustain_enabled"] = not self._values["sustain_enabled"]
                self._save()
                return "sustain_changed"

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_panel()
        self._draw_back()

    def _load(self) -> None:
        data = cfg.load().get("hardware", {})
        self._values = {
            "sustain_enabled": bool(data.get("sustain_enabled", False)),
        }

    def _save(self) -> None:
        data = cfg.load()
        data.setdefault("hardware", {})["sustain_enabled"] = self._values["sustain_enabled"]
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Hardware Settings", True, TITLE_COLOR)
        title_y = sr.height // 8
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        panel_top = title_y + title_surf.get_height() + 28
        panel_h = 180
        panel_w = min(PANEL_W, sr.width - 2 * PANEL_MARGIN_X)
        self._panel_rect = pygame.Rect(cx - panel_w // 2, panel_top, panel_w, panel_h)

        self._sustain_check_rect = pygame.Rect(
            self._panel_rect.left + 20,
            self._panel_rect.top + 28,
            28, 28,
        )

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_sustain = self._sustain_check_rect.inflate(60, 12).collidepoint(pos)

    def _draw_title(self) -> None:
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)

    def _draw_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._panel_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._panel_rect, width=1, border_radius=8)

        # Section heading
        section_surf = self._label_font.render("Sustain Pedal  (MIDI CC 64)", True, TEXT_COLOR)
        self.screen.blit(section_surf, (self._panel_rect.left + 16, self._panel_rect.top + 8 - section_surf.get_height() // 4))

        # Checkbox
        cb_bg = BUTTON_HOVER_BG if self._hover_sustain else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, cb_bg, self._sustain_check_rect, border_radius=5)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._sustain_check_rect, width=1, border_radius=5)
        if self._values["sustain_enabled"]:
            inner = self._sustain_check_rect.inflate(-8, -8)
            pygame.draw.rect(self.screen, CHECK_ON_COLOR, inner, border_radius=3)

        # Label beside checkbox
        label_surf = self._label_font.render("Enable Piano Sustain", True, TEXT_COLOR)
        self.screen.blit(
            label_surf,
            label_surf.get_rect(midleft=(self._sustain_check_rect.right + 12, self._sustain_check_rect.centery)),
        )

        # Description
        desc1 = self._small_font.render(
            "While enabled, notes held when CC 64 is pressed stay active until the pedal is released.",
            True, MUTED_TEXT_COLOR,
        )
        desc2 = self._small_font.render(
            "Triple-tap the sustain pedal to cycle themes — works regardless of this setting.",
            True, MUTED_TEXT_COLOR,
        )
        y = self._sustain_check_rect.bottom + 16
        self.screen.blit(desc1, (self._panel_rect.left + 16, y))
        self.screen.blit(desc2, (self._panel_rect.left + 16, y + desc1.get_height() + 6))

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
