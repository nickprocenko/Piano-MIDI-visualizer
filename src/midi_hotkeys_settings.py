"""Read-only MIDI hotkey overview screen."""

from __future__ import annotations

import pygame

from src.midi_actions import get_actions_grouped
from src.midi_hotkeys import format_mapping_label, load_hotkeys

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
ACCENT_COLOR = (0, 180, 180)

TITLE_FONT_SIZE = 42
SECTION_FONT_SIZE = 24
ROW_FONT_SIZE = 22
BACK_FONT_SIZE = 26
BACK_WIDTH = 160
BACK_HEIGHT = 52
ROW_HEIGHT = 42
ROW_GAP = 8


class MidiHotkeysSettingsScreen:
    """Shows the current hotkey map until full MIDI learn UI lands."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._section_font = pygame.font.SysFont("Arial", SECTION_FONT_SIZE, bold=True)
        self._row_font = pygame.font.SysFont("Arial", ROW_FONT_SIZE)
        self._back_font = pygame.font.SysFont("Arial", BACK_FONT_SIZE)

        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._panel_rect = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_WIDTH, BACK_HEIGHT)
        self._hover_back = False
        self._scroll_offset = 0
        self._content_height = 0

        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._hover_back = self._back_rect.collidepoint(event.pos)
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"
        if event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, self._content_height - self._panel_rect.height + 20)
            self._scroll_offset = max(0, min(max_scroll, self._scroll_offset - (event.y * 28)))
            return None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self._back_rect.collidepoint(event.pos):
            return "back"
        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        if self._title_surf is not None:
            self.screen.blit(self._title_surf, self._title_pos)
        pygame.draw.rect(self.screen, PANEL_BG, self._panel_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._panel_rect, width=1, border_radius=8)
        self._draw_rows()
        self._draw_back()

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx
        title = self._title_font.render("MIDI Hotkeys", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_surf = title
        self._title_pos = (cx - title.get_width() // 2, title_y)
        top = title_y + title.get_height() + 22
        bottom = sr.height - BACK_HEIGHT - 34
        self._panel_rect = pygame.Rect(26, top, sr.width - 52, max(180, bottom - top))
        self._back_rect = pygame.Rect(cx - BACK_WIDTH // 2, sr.height - BACK_HEIGHT - 24, BACK_WIDTH, BACK_HEIGHT)

    def _draw_rows(self) -> None:
        grouped = get_actions_grouped()
        mappings_by_action = {
            str(mapping.get("action_id", "")): mapping
            for mapping in load_hotkeys()
        }

        clip = self._panel_rect.inflate(-12, -12)
        self.screen.set_clip(clip)
        y = self._panel_rect.top + 14 - self._scroll_offset
        for category, actions in grouped.items():
            header = self._section_font.render(category, True, ACCENT_COLOR)
            self.screen.blit(header, (self._panel_rect.left + 16, y))
            y += header.get_height() + 10
            for action in actions:
                row_rect = pygame.Rect(self._panel_rect.left + 14, y, self._panel_rect.width - 28, ROW_HEIGHT)
                pygame.draw.rect(self.screen, BG_COLOR, row_rect, border_radius=6)
                pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row_rect, width=1, border_radius=6)

                label = self._row_font.render(str(action["label"]), True, TEXT_COLOR)
                self.screen.blit(label, (row_rect.left + 12, row_rect.top + 8))

                mapping_label = format_mapping_label(mappings_by_action.get(str(action["id"])))
                mapping_surf = self._row_font.render(mapping_label, True, MUTED_TEXT_COLOR)
                self.screen.blit(mapping_surf, mapping_surf.get_rect(midright=(row_rect.right - 12, row_rect.centery)))
                y += ROW_HEIGHT + ROW_GAP
            y += 8

        self._content_height = max(0, y - self._panel_rect.top)
        self.screen.set_clip(None)

        hint = self._row_font.render("Learn-mode editing UI is next. Current mappings are shown here.", True, MUTED_TEXT_COLOR)
        hint_rect = hint.get_rect()
        hint_rect.midbottom = (self._panel_rect.centerx, self._panel_rect.bottom - 10)
        self.screen.blit(hint, hint_rect)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        label = self._back_font.render("BACK", True, fg)
        self.screen.blit(label, label.get_rect(center=self._back_rect.center))
