"""Settings screen — manage MIDI file search folders."""

from __future__ import annotations

import pygame
from src import config as cfg

# Colour palette (matches menu.py)
BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)
REMOVE_NORMAL_BG = (60, 30, 30)
REMOVE_HOVER_BG = (100, 40, 40)
REMOVE_TEXT_COLOR = (220, 150, 150)
NO_FOLDERS_COLOR = (150, 150, 150)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 22
BTN_FONT_SIZE = 28
ROW_HEIGHT = 48
ROW_GAP = 10
ROW_WIDTH = 600
REMOVE_BTN_W = 60
ADD_BTN_W = 340
ADD_BTN_H = 52
NOTES_BTN_W = 340
NOTES_BTN_H = 52
KEYBOARD_BTN_W = 340
KEYBOARD_BTN_H = 52
LED_BTN_W = 340
LED_BTN_H = 52
DISPLAY_BTN_W = 340
DISPLAY_BTN_H = 52
AUDIENCE_BTN_W = 340
AUDIENCE_BTN_H = 52
BACK_BTN_W = 160
BACK_BTN_H = 52


def _pick_folder() -> str | None:
    """Open a native folder-picker dialog and return the chosen path."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        # -topmost ensures the dialog floats above the pygame window.
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        folder = filedialog.askdirectory(
            parent=root, title="Select MIDI search folder"
        )
        root.destroy()
        return folder if folder else None
    except Exception:
        return None


def _truncate(font: pygame.font.Font, text: str, max_w: int) -> str:
    """Shorten *text* with a trailing '…' so it fits within *max_w* pixels."""
    if font.render(text, True, (0, 0, 0)).get_width() <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        if font.render(text + "…", True, (0, 0, 0)).get_width() <= max_w:
            return text + "…"
    return "…"


class SettingsScreen:
    """
    Settings screen for managing MIDI file search folders.

    ``handle_event()`` returns:
      ``"back"``  — user pressed BACK or ESC (changes are auto-saved).
        ``"notes_settings"`` — open the note visual customization screen.
        ``"keyboard_settings"`` — open keyboard settings screen.
                ``"led_settings"`` — open ESP32 LED output settings screen.
        ``"display_settings"`` — open projector/display settings screen.
                ``"audience_settings"`` — open audience WebSocket settings screen.
      ``None``    — nothing actionable.
    """

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._folders: list[str] = []
        self._add_rect = pygame.Rect(0, 0, ADD_BTN_W, ADD_BTN_H)
        self._notes_rect = pygame.Rect(0, 0, NOTES_BTN_W, NOTES_BTN_H)
        self._keyboard_rect = pygame.Rect(0, 0, KEYBOARD_BTN_W, KEYBOARD_BTN_H)
        self._led_rect = pygame.Rect(0, 0, LED_BTN_W, LED_BTN_H)
        self._display_rect = pygame.Rect(0, 0, DISPLAY_BTN_W, DISPLAY_BTN_H)
        self._audience_rect = pygame.Rect(0, 0, AUDIENCE_BTN_W, AUDIENCE_BTN_H)
        self._back_rect = pygame.Rect(0, 0, BACK_BTN_W, BACK_BTN_H)
        self._row_rects: list[pygame.Rect] = []
        self._remove_rects: list[pygame.Rect] = []

        self._hover_add = False
        self._hover_notes = False
        self._hover_keyboard = False
        self._hover_led = False
        self._hover_display = False
        self._hover_audience = False
        self._hover_back = False
        self._hover_remove: int = -1

        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._list_start_y = 0

        self._load()
        self._build_layout()

    # ------------------------------------------------------------------
    # Public API
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

            if self._notes_rect.collidepoint(event.pos):
                return "notes_settings"

            if self._keyboard_rect.collidepoint(event.pos):
                return "keyboard_settings"

            if self._led_rect.collidepoint(event.pos):
                return "led_settings"

            if self._display_rect.collidepoint(event.pos):
                return "display_settings"

            if self._audience_rect.collidepoint(event.pos):
                return "audience_settings"

            if self._add_rect.collidepoint(event.pos):
                folder = _pick_folder()
                if folder and folder not in self._folders:
                    self._folders.append(folder)
                    self._save()
                    self._build_layout()
                return None

            for i, rect in enumerate(self._remove_rects):
                if rect.collidepoint(event.pos):
                    self._folders.pop(i)
                    self._save()
                    self._build_layout()
                    return None

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_notes_button()
        self._draw_keyboard_button()
        self._draw_led_button()
        self._draw_display_button()
        self._draw_audience_button()
        self._draw_add_button()
        self._draw_folders()
        self._draw_back_button()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._folders = list(cfg.load().get("search_folders", []))

    def _save(self) -> None:
        data = cfg.load()
        data["search_folders"] = self._folders
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Settings", True, TITLE_COLOR)
        title_y = sr.height // 8
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        notes_y = title_y + title_surf.get_height() + 24
        self._notes_rect = pygame.Rect(
            cx - NOTES_BTN_W // 2, notes_y, NOTES_BTN_W, NOTES_BTN_H
        )

        keyboard_y = notes_y + NOTES_BTN_H + 12
        self._keyboard_rect = pygame.Rect(
            cx - KEYBOARD_BTN_W // 2, keyboard_y, KEYBOARD_BTN_W, KEYBOARD_BTN_H
        )

        led_y = keyboard_y + KEYBOARD_BTN_H + 12
        self._led_rect = pygame.Rect(
            cx - LED_BTN_W // 2, led_y, LED_BTN_W, LED_BTN_H
        )

        display_y = led_y + LED_BTN_H + 12
        self._display_rect = pygame.Rect(
            cx - DISPLAY_BTN_W // 2, display_y, DISPLAY_BTN_W, DISPLAY_BTN_H
        )

        audience_y = display_y + DISPLAY_BTN_H + 12
        self._audience_rect = pygame.Rect(
            cx - AUDIENCE_BTN_W // 2, audience_y, AUDIENCE_BTN_W, AUDIENCE_BTN_H
        )

        add_y = audience_y + AUDIENCE_BTN_H + 12
        self._add_rect = pygame.Rect(cx - ADD_BTN_W // 2, add_y, ADD_BTN_W, ADD_BTN_H)

        list_y = add_y + ADD_BTN_H + 28
        self._list_start_y = list_y

        self._row_rects = []
        self._remove_rects = []
        y = list_y
        for _ in self._folders:
            path_rect = pygame.Rect(
                cx - ROW_WIDTH // 2, y, ROW_WIDTH - REMOVE_BTN_W - 8, ROW_HEIGHT
            )
            rem_rect = pygame.Rect(
                cx + ROW_WIDTH // 2 - REMOVE_BTN_W, y, REMOVE_BTN_W, ROW_HEIGHT
            )
            self._row_rects.append(path_rect)
            self._remove_rects.append(rem_rect)
            y += ROW_HEIGHT + ROW_GAP

        back_y = max(y + 24, sr.height - BACK_BTN_H - 24)
        self._back_rect = pygame.Rect(
            cx - BACK_BTN_W // 2, back_y, BACK_BTN_W, BACK_BTN_H
        )

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_add = self._add_rect.collidepoint(pos)
        self._hover_notes = self._notes_rect.collidepoint(pos)
        self._hover_keyboard = self._keyboard_rect.collidepoint(pos)
        self._hover_led = self._led_rect.collidepoint(pos)
        self._hover_display = self._display_rect.collidepoint(pos)
        self._hover_audience = self._audience_rect.collidepoint(pos)
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_remove = -1
        for i, rect in enumerate(self._remove_rects):
            if rect.collidepoint(pos):
                self._hover_remove = i
                break

    def _draw_title(self) -> None:
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)

    def _draw_add_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_add else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_add else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._add_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._add_rect, width=1, border_radius=8
        )
        label = self._btn_font.render("+ ADD SEARCH FOLDER", True, fg)
        self.screen.blit(label, label.get_rect(center=self._add_rect.center))

    def _draw_notes_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_notes else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_notes else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._notes_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._notes_rect, width=1, border_radius=8
        )
        label = self._btn_font.render("NOTES SETTINGS", True, fg)
        self.screen.blit(label, label.get_rect(center=self._notes_rect.center))

    def _draw_keyboard_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_keyboard else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_keyboard else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._keyboard_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._keyboard_rect, width=1, border_radius=8
        )
        label = self._btn_font.render("KEYBOARD SETTINGS", True, fg)
        self.screen.blit(label, label.get_rect(center=self._keyboard_rect.center))

    def _draw_led_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_led else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_led else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._led_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._led_rect, width=1, border_radius=8
        )
        label = self._btn_font.render("LED SETTINGS", True, fg)
        self.screen.blit(label, label.get_rect(center=self._led_rect.center))

    def _draw_display_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_display else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_display else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._display_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._display_rect, width=1, border_radius=8
        )
        label = self._btn_font.render("DISPLAY SETTINGS", True, fg)
        self.screen.blit(label, label.get_rect(center=self._display_rect.center))

    def _draw_audience_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_audience else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_audience else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._audience_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._audience_rect, width=1, border_radius=8
        )
        label = self._btn_font.render("AUDIENCE SETTINGS", True, fg)
        self.screen.blit(label, label.get_rect(center=self._audience_rect.center))

    def _draw_folders(self) -> None:
        if not self._folders:
            sr = self.screen.get_rect()
            msg = self._label_font.render(
                "No search folders added yet.", True, NO_FOLDERS_COLOR
            )
            self.screen.blit(
                msg, (sr.centerx - msg.get_width() // 2, self._list_start_y + 10)
            )
            return

        for i, folder in enumerate(self._folders):
            row_rect = self._row_rects[i]
            rem_rect = self._remove_rects[i]

            # Path row
            pygame.draw.rect(self.screen, BUTTON_NORMAL_BG, row_rect, border_radius=6)
            pygame.draw.rect(
                self.screen, BUTTON_BORDER_COLOR, row_rect, width=1, border_radius=6
            )
            label_text = _truncate(self._label_font, folder, row_rect.width - 16)
            label_surf = self._label_font.render(label_text, True, BUTTON_TEXT_COLOR)
            self.screen.blit(
                label_surf,
                label_surf.get_rect(midleft=(row_rect.left + 8, row_rect.centery)),
            )

            # Remove [✕] button
            r_bg = REMOVE_HOVER_BG if i == self._hover_remove else REMOVE_NORMAL_BG
            pygame.draw.rect(self.screen, r_bg, rem_rect, border_radius=6)
            pygame.draw.rect(
                self.screen, BUTTON_BORDER_COLOR, rem_rect, width=1, border_radius=6
            )
            x_surf = self._label_font.render("✕", True, REMOVE_TEXT_COLOR)
            self.screen.blit(x_surf, x_surf.get_rect(center=rem_rect.center))

    def _draw_back_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8
        )
        label = self._btn_font.render("BACK", True, fg)
        self.screen.blit(label, label.get_rect(center=self._back_rect.center))
