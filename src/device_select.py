"""MIDI device selection screen."""

from __future__ import annotations

import pygame
from src.midi_input import MidiInput

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
ITEM_WIDTH = 520
ITEM_HEIGHT = 52
ITEM_GAP = 14
BACK_WIDTH = 160
BACK_HEIGHT = 52


class DeviceSelect:
    """
    Full-screen MIDI device selection screen.

    After construction, call ``refresh()`` to scan for ports before the first
    draw.  ``handle_event()`` returns:

    * ``"select"`` — user chose a device (port index stored in
      ``self.selected_port``).
    * ``"back"``   — user pressed BACK or ESC.
    * ``None``     — nothing actionable yet.
    """

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.selected_port: int = 0

        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._item_font = pygame.font.SysFont("Arial", ITEM_FONT_SIZE)
        self._back_font = pygame.font.SysFont("Arial", BACK_FONT_SIZE)

        self._ports: list[str] = []
        self._item_rects: list[pygame.Rect] = []   # one per port
        self._back_rect = pygame.Rect(0, 0, BACK_WIDTH, BACK_HEIGHT)
        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)

        self._hover_item: int = -1   # index of hovered port button, or -1
        self._hover_back: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-scan available MIDI ports and rebuild the layout."""
        self._ports = MidiInput().list_ports()
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
            for i, rect in enumerate(self._item_rects):
                if rect.collidepoint(event.pos):
                    self.selected_port = i
                    return "select"

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_ports()
        self._draw_back()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Select MIDI Device", True, TITLE_COLOR)
        title_y = sr.height // 8
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        start_y = title_y + title_surf.get_height() + 40
        y = start_y
        self._item_rects = []
        for _ in self._ports:
            rect = pygame.Rect(cx - ITEM_WIDTH // 2, y, ITEM_WIDTH, ITEM_HEIGHT)
            self._item_rects.append(rect)
            y += ITEM_HEIGHT + ITEM_GAP

        back_y = y + 24
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

    def _draw_ports(self) -> None:
        if not self._ports:
            sr = self.screen.get_rect()
            msg = self._item_font.render(
                "No MIDI devices found.  Connect a device and press BACK to retry.",
                True,
                NO_DEVICE_COLOR,
            )
            title_bottom = self._title_pos[1] + (self._title_surf.get_height() if self._title_surf else 0)
            self.screen.blit(msg, (sr.centerx - msg.get_width() // 2, title_bottom + 50))
            return

        for i, rect in enumerate(self._item_rects):
            hovered = i == self._hover_item
            bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
            fg = BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR
            pygame.draw.rect(self.screen, bg, rect, border_radius=8)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)
            label = self._item_font.render(self._ports[i], True, fg)
            self.screen.blit(label, label.get_rect(center=rect.center))

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        label = self._back_font.render("BACK", True, fg)
        self.screen.blit(label, label.get_rect(center=self._back_rect.center))
