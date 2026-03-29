"""Global hotkeys screen with remappable MIDI navigation bindings."""

from __future__ import annotations

from typing import Callable

import pygame

BG_COLOR = (15, 15, 20)
PANEL_BG = (28, 28, 38)
PANEL_BORDER = (80, 80, 110)
TITLE_COLOR = (235, 235, 245)
TEXT_COLOR = (210, 210, 225)
KEY_COLOR = (155, 215, 255)
MIDI_COLOR = (165, 255, 185)
MUTED_COLOR = (150, 150, 165)
ACCENT_COLOR = (0, 190, 220)
BTN_BG = (34, 42, 56)
BTN_HOVER = (52, 66, 92)
ROW_BG = (30, 38, 52)
ROW_ACTIVE_BG = (44, 60, 84)


class HotkeysScreen:
    """Remappable hotkeys editor; returns 'back' on close intent."""

    _KEYBOARD_ROWS: list[tuple[str, str]] = [
        ("UP", "Navigate up through menu and settings items"),
        ("DOWN", "Navigate down through menu and settings items"),
        ("LEFT", "Move highlighted slider or value left"),
        ("RIGHT", "Move highlighted slider or value right"),
        ("ENTER", "Confirm highlighted item"),
        ("ESC", "Go back or close current screen"),
        ("F1", "Toggle this hotkeys screen"),
    ]

    _MIDI_ROWS: list[tuple[str, str]] = [
        ("nav_up", "Navigate Up"),
        ("nav_down", "Navigate Down"),
        ("nav_left", "Navigate Left"),
        ("nav_right", "Navigate Right"),
        ("confirm", "Confirm / Enter"),
        ("back", "Back / Escape"),
        ("cycle_theme", "Next Theme"),
        ("cycle_bank", "Next Bank"),
        ("cycle_theme_prev", "Previous Theme"),
        ("cycle_bank_prev", "Previous Bank"),
        ("toggle_keyboard", "Toggle Keyboard"),
        ("toggle_fullscreen", "Toggle Fullscreen"),
    ]

    def __init__(
        self,
        screen: pygame.Surface,
        cc_action_to_num: dict[str, int],
        get_cc_map: Callable[[], dict[str, int]],
        on_set_cc: Callable[[str, int], None],
        on_reset_defaults: Callable[[], None],
    ) -> None:
        self.screen = screen
        self._cc = dict(cc_action_to_num)
        self._get_cc_map = get_cc_map
        self._on_set_cc = on_set_cc
        self._on_reset_defaults = on_reset_defaults

        self._title_font = pygame.font.SysFont("Arial", 44, bold=True)
        self._head_font = pygame.font.SysFont("Arial", 30, bold=True)
        self._row_font = pygame.font.SysFont("Arial", 22)
        self._hint_font = pygame.font.SysFont("Arial", 19)

        self._midi_cursor = 0
        self._midi_row_rects: list[pygame.Rect] = []
        self._reset_rect = pygame.Rect(0, 0, 0, 0)
        self._hover_reset = False

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                return "back"
            if event.key == pygame.K_UP:
                self._midi_cursor = (self._midi_cursor - 1) % len(self._MIDI_ROWS)
                return None
            if event.key == pygame.K_DOWN:
                self._midi_cursor = (self._midi_cursor + 1) % len(self._MIDI_ROWS)
                return None
            if event.key == pygame.K_LEFT:
                self._nudge_selected_cc(-1)
                return None
            if event.key == pygame.K_RIGHT:
                self._nudge_selected_cc(1)
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self._hover_reset:
                    self._reset_defaults()
                return None
            if event.key == pygame.K_r:
                self._reset_defaults()
                return None

        if event.type == pygame.MOUSEMOTION:
            self._hover_reset = self._reset_rect.collidepoint(event.pos)
            for i, rect in enumerate(self._midi_row_rects):
                if rect.collidepoint(event.pos):
                    self._midi_cursor = i
                    break
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._reset_rect.collidepoint(event.pos):
                self._reset_defaults()
                return None
            for i, rect in enumerate(self._midi_row_rects):
                if rect.collidepoint(event.pos):
                    self._midi_cursor = i
                    return None

        return None

    def _reset_defaults(self) -> None:
        self._on_reset_defaults()
        self._sync_cc_map()

    def _nudge_selected_cc(self, delta: int) -> None:
        action, _label = self._MIDI_ROWS[self._midi_cursor]
        current = int(self._cc.get(action, 0))
        new_cc = max(0, min(127, current + int(delta)))
        if new_cc == current:
            return
        self._on_set_cc(action, new_cc)
        self._sync_cc_map()

    def _sync_cc_map(self) -> None:
        current = self._get_cc_map()
        self._cc = {
            action: int(current.get(action, 0))
            for action, _label in self._MIDI_ROWS
        }

    def draw(self) -> None:
        self._sync_cc_map()
        self.screen.fill(BG_COLOR)
        screen_rect = self.screen.get_rect()
        panel = screen_rect.inflate(-120, -100)

        pygame.draw.rect(self.screen, PANEL_BG, panel, border_radius=12)
        pygame.draw.rect(self.screen, PANEL_BORDER, panel, width=1, border_radius=12)

        title = self._title_font.render("Hotkeys", True, TITLE_COLOR)
        self.screen.blit(title, (panel.left + 24, panel.top + 20))

        close_hint = self._hint_font.render("F1 or ESC closes this screen", True, MUTED_COLOR)
        self.screen.blit(
            close_hint,
            (panel.right - close_hint.get_width() - 24, panel.top + 34),
        )

        gutter = 32
        content_top = panel.top + 92
        col_width = (panel.width - 48 - gutter) // 2
        left_x = panel.left + 24
        right_x = left_x + col_width + gutter

        self._draw_keyboard_column(left_x, content_top, col_width)
        self._draw_midi_column(right_x, content_top, col_width)

        self._reset_rect = pygame.Rect(right_x, panel.bottom - 72, col_width, 40)
        reset_bg = BTN_HOVER if self._hover_reset else BTN_BG
        pygame.draw.rect(self.screen, reset_bg, self._reset_rect, border_radius=8)
        pygame.draw.rect(self.screen, PANEL_BORDER, self._reset_rect, width=1, border_radius=8)
        reset_text = self._row_font.render("Reset MIDI Defaults", True, TEXT_COLOR)
        self.screen.blit(reset_text, reset_text.get_rect(center=self._reset_rect.center))

        footer = self._hint_font.render(
            "UP/DOWN select MIDI action, LEFT/RIGHT adjust CC, R resets defaults",
            True,
            MUTED_COLOR,
        )
        self.screen.blit(footer, (panel.left + 24, panel.bottom - footer.get_height() - 14))

    def _draw_keyboard_column(self, x: int, y: int, width: int) -> None:
        header = self._head_font.render("Keyboard", True, KEY_COLOR)
        self.screen.blit(header, (x, y))

        row_y = y + 46
        for key_name, desc in self._KEYBOARD_ROWS:
            rect = pygame.Rect(x, row_y, width, 38)
            pygame.draw.rect(self.screen, ROW_BG, rect, border_radius=7)
            pygame.draw.rect(self.screen, PANEL_BORDER, rect, width=1, border_radius=7)

            key_surf = self._row_font.render(key_name, True, KEY_COLOR)
            desc_surf = self._row_font.render(desc, True, TEXT_COLOR)
            self.screen.blit(key_surf, (rect.x + 10, rect.y + 7))
            self.screen.blit(desc_surf, (rect.x + 110, rect.y + 7))
            row_y += 42

    def _draw_midi_column(self, x: int, y: int, width: int) -> None:
        header = self._head_font.render("MIDI (Remappable)", True, MIDI_COLOR)
        self.screen.blit(header, (x, y))

        row_y = y + 46
        self._midi_row_rects = []
        for i, (action, label) in enumerate(self._MIDI_ROWS):
            rect = pygame.Rect(x, row_y, width, 38)
            self._midi_row_rects.append(rect)

            active = i == self._midi_cursor
            row_bg = ROW_ACTIVE_BG if active else ROW_BG
            row_border = ACCENT_COLOR if active else PANEL_BORDER
            pygame.draw.rect(self.screen, row_bg, rect, border_radius=7)
            pygame.draw.rect(self.screen, row_border, rect, width=2 if active else 1, border_radius=7)

            cc_num = int(self._cc.get(action, 0))
            cc_surf = self._row_font.render(f"CC {cc_num:02d}", True, MIDI_COLOR)
            label_surf = self._row_font.render(label, True, TEXT_COLOR)
            self.screen.blit(cc_surf, (rect.x + 10, rect.y + 7))
            self.screen.blit(label_surf, (rect.x + 118, rect.y + 7))

            if active:
                hint_surf = self._hint_font.render("<  >", True, ACCENT_COLOR)
                self.screen.blit(
                    hint_surf,
                    (rect.right - hint_surf.get_width() - 10, rect.y + 9),
                )

            row_y += 42