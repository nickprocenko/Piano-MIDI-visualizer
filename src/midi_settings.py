"""MIDI settings navigation screen."""

from __future__ import annotations

import pygame

BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)

TITLE_FONT_SIZE = 42
BUTTON_FONT_SIZE = 28
BUTTON_WIDTH = 360
BUTTON_HEIGHT = 56
BUTTON_GAP = 16
BACK_WIDTH = 160
BACK_HEIGHT = 52


class MidiSettingsScreen:
    """Navigation hub for MIDI and audio input settings."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._button_font = pygame.font.SysFont("Arial", BUTTON_FONT_SIZE)

        self._device_rect = pygame.Rect(0, 0, BUTTON_WIDTH, BUTTON_HEIGHT)
        self._audio_rect = pygame.Rect(0, 0, BUTTON_WIDTH, BUTTON_HEIGHT)
        self._hotkeys_rect = pygame.Rect(0, 0, BUTTON_WIDTH, BUTTON_HEIGHT)
        self._back_rect = pygame.Rect(0, 0, BACK_WIDTH, BACK_HEIGHT)

        self._hover_device = False
        self._hover_audio = False
        self._hover_hotkeys = False
        self._hover_back = False
        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)

        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._device_rect.collidepoint(event.pos):
                return "device_select"
            if self._audio_rect.collidepoint(event.pos):
                return "audio_device_select"
            if self._hotkeys_rect.collidepoint(event.pos):
                return "midi_hotkeys"
            if self._back_rect.collidepoint(event.pos):
                return "back"
        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        if self._title_surf is not None:
            self.screen.blit(self._title_surf, self._title_pos)
        self._draw_button(self._device_rect, "MIDI DEVICE", self._hover_device)
        self._draw_button(self._audio_rect, "AUDIO INPUT", self._hover_audio)
        self._draw_button(self._hotkeys_rect, "MIDI HOTKEYS", self._hover_hotkeys)
        self._draw_button(self._back_rect, "BACK", self._hover_back)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx
        title = self._title_font.render("Input Settings", True, TITLE_COLOR)
        title_y = sr.height // 8
        self._title_surf = title
        self._title_pos = (cx - title.get_width() // 2, title_y)

        y = title_y + title.get_height() + 36
        self._device_rect = pygame.Rect(cx - BUTTON_WIDTH // 2, y, BUTTON_WIDTH, BUTTON_HEIGHT)
        y += BUTTON_HEIGHT + BUTTON_GAP
        self._audio_rect = pygame.Rect(cx - BUTTON_WIDTH // 2, y, BUTTON_WIDTH, BUTTON_HEIGHT)
        y += BUTTON_HEIGHT + BUTTON_GAP
        self._hotkeys_rect = pygame.Rect(cx - BUTTON_WIDTH // 2, y, BUTTON_WIDTH, BUTTON_HEIGHT)
        y += BUTTON_HEIGHT + 26
        self._back_rect = pygame.Rect(cx - BACK_WIDTH // 2, y, BACK_WIDTH, BACK_HEIGHT)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_device = self._device_rect.collidepoint(pos)
        self._hover_audio = self._audio_rect.collidepoint(pos)
        self._hover_hotkeys = self._hotkeys_rect.collidepoint(pos)
        self._hover_back = self._back_rect.collidepoint(pos)

    def _draw_button(self, rect: pygame.Rect, label: str, hovered: bool) -> None:
        bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)
        surf = self._button_font.render(label, True, fg)
        self.screen.blit(surf, surf.get_rect(center=rect.center))
