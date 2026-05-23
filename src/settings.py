"""Settings hub screen — compact navigation grid + MIDI folder management."""

from __future__ import annotations

import pygame
from src import config as cfg

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
MUTED_TEXT_COLOR = (150, 150, 150)

TITLE_FONT_SIZE = 28   # smaller than before — saves space
LABEL_FONT_SIZE = 22
BTN_FONT_SIZE = 26
NAV_FONT_SIZE = 24

NAV_BTN_H = 52
NAV_BTN_GAP = 10
NAV_COLS = 2
MARGIN_X = 24
SECTION_GAP = 20
ADD_BTN_H = 48
ROW_HEIGHT = 46
ROW_GAP = 8
ROW_WIDTH = 600
REMOVE_BTN_W = 56
BACK_BTN_W = 160
BACK_BTN_H = 52

# (label, action) pairs — will be laid out as a 2-column grid
NAV_ITEMS: list[tuple[str, str]] = [
    ("NOTES SETTINGS",    "notes_settings"),
    ("KEYBOARD SETTINGS", "keyboard_settings"),
    ("LED SETTINGS",      "led_settings"),
    ("DISPLAY SETTINGS",  "display_settings"),
    ("AUDIENCE SETTINGS", "audience_settings"),
    ("THEME MANAGER",     "theme_settings"),
    ("HARDWARE SETTINGS", "hardware_settings"),
]


def _pick_folder() -> str | None:
    """Open a native folder-picker dialog and return the chosen path."""
    try:
        import tkinter as tk
        from tkinter import filedialog

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
    Settings hub with a compact 2-column navigation grid.

    ``handle_event()`` returns one of:
      ``"back"``              — user pressed BACK or ESC
      ``"notes_settings"``    — open note visual customisation screen
      ``"keyboard_settings"`` — open keyboard settings screen
      ``"led_settings"``      — open ESP32 LED output settings screen
      ``"display_settings"``  — open projector/display settings screen
      ``"audience_settings"`` — open audience WebSocket settings screen
      ``"theme_settings"``    — open theme manager screen
      ``"hardware_settings"`` — open hardware settings screen
      ``None``                — nothing actionable
    """

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._nav_font = pygame.font.SysFont("Arial", NAV_FONT_SIZE, bold=True)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._folders: list[str] = []
        self._nav_rects: list[pygame.Rect] = []
        self._hover_nav: int = -1
        self._add_rect = pygame.Rect(0, 0, 0, ADD_BTN_H)
        self._back_rect = pygame.Rect(0, 0, BACK_BTN_W, BACK_BTN_H)
        self._row_rects: list[pygame.Rect] = []
        self._remove_rects: list[pygame.Rect] = []
        self._hover_add = False
        self._hover_back = False
        self._hover_remove: int = -1
        self._list_start_y = 0
        self._title_pos = (0, 0)

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

            for i, rect in enumerate(self._nav_rects):
                if rect.collidepoint(event.pos):
                    return NAV_ITEMS[i][1]

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
        self._draw_nav_grid()
        self._draw_folder_section()
        self._draw_back_button()

    def _load(self) -> None:
        self._folders = list(cfg.load().get("search_folders", []))

    def _save(self) -> None:
        data = cfg.load()
        data["search_folders"] = self._folders
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        # Compact title at top
        title_surf = self._title_font.render("Settings", True, TITLE_COLOR)
        title_y = 12
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        # Navigation grid — 2 columns
        grid_top = title_y + title_surf.get_height() + 14
        available_w = sr.width - 2 * MARGIN_X
        col_w = (available_w - NAV_BTN_GAP) // 2
        self._nav_rects = []
        for i, _ in enumerate(NAV_ITEMS):
            col = i % NAV_COLS
            row = i // NAV_COLS
            x = MARGIN_X + col * (col_w + NAV_BTN_GAP)
            y = grid_top + row * (NAV_BTN_H + NAV_BTN_GAP)
            self._nav_rects.append(pygame.Rect(x, y, col_w, NAV_BTN_H))

        # If odd number of items the last button spans both columns
        if len(NAV_ITEMS) % NAV_COLS == 1:
            last = self._nav_rects[-1]
            self._nav_rects[-1] = pygame.Rect(MARGIN_X, last.y, available_w, NAV_BTN_H)

        grid_bottom = self._nav_rects[-1].bottom if self._nav_rects else grid_top

        # MIDI Search Folders section
        section_top = grid_bottom + SECTION_GAP
        self._folder_label_pos = (MARGIN_X, section_top)
        label_h = self._label_font.get_height()

        add_y = section_top + label_h + 6
        add_w = min(360, available_w)
        self._add_rect = pygame.Rect(cx - add_w // 2, add_y, add_w, ADD_BTN_H)

        list_y = add_y + ADD_BTN_H + 12
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

        back_y = max(y + 12, sr.height - BACK_BTN_H - 14)
        self._back_rect = pygame.Rect(cx - BACK_BTN_W // 2, back_y, BACK_BTN_W, BACK_BTN_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_nav = -1
        for i, rect in enumerate(self._nav_rects):
            if rect.collidepoint(pos):
                self._hover_nav = i
                break
        self._hover_add = self._add_rect.collidepoint(pos)
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_remove = -1
        for i, rect in enumerate(self._remove_rects):
            if rect.collidepoint(pos):
                self._hover_remove = i
                break

    def _draw_title(self) -> None:
        self.screen.blit(self._title_surf, self._title_pos)

    def _draw_nav_grid(self) -> None:
        for i, (label, _action) in enumerate(NAV_ITEMS):
            rect = self._nav_rects[i]
            is_hover = self._hover_nav == i
            bg = BUTTON_HOVER_BG if is_hover else BUTTON_NORMAL_BG
            fg = BUTTON_HOVER_TEXT_COLOR if is_hover else BUTTON_TEXT_COLOR
            pygame.draw.rect(self.screen, bg, rect, border_radius=8)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)
            surf = self._nav_font.render(label, True, fg)
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_folder_section(self) -> None:
        lx, ly = self._folder_label_pos
        label_surf = self._label_font.render("MIDI Search Folders", True, MUTED_TEXT_COLOR)
        self.screen.blit(label_surf, (lx, ly))

        # Add button
        bg = BUTTON_HOVER_BG if self._hover_add else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_add else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._add_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._add_rect, width=1, border_radius=8)
        add_surf = self._btn_font.render("+ ADD SEARCH FOLDER", True, fg)
        self.screen.blit(add_surf, add_surf.get_rect(center=self._add_rect.center))

        # Folder list
        if not self._folders:
            sr = self.screen.get_rect()
            msg = self._label_font.render("No search folders added yet.", True, NO_FOLDERS_COLOR)
            self.screen.blit(msg, (sr.centerx - msg.get_width() // 2, self._list_start_y + 8))
            return

        for i, folder in enumerate(self._folders):
            row_rect = self._row_rects[i]
            rem_rect = self._remove_rects[i]

            pygame.draw.rect(self.screen, BUTTON_NORMAL_BG, row_rect, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row_rect, width=1, border_radius=6)
            label_text = _truncate(self._label_font, folder, row_rect.width - 16)
            label_s = self._label_font.render(label_text, True, BUTTON_TEXT_COLOR)
            self.screen.blit(label_s, label_s.get_rect(midleft=(row_rect.left + 8, row_rect.centery)))

            r_bg = REMOVE_HOVER_BG if i == self._hover_remove else REMOVE_NORMAL_BG
            pygame.draw.rect(self.screen, r_bg, rem_rect, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rem_rect, width=1, border_radius=6)
            x_s = self._label_font.render("✕", True, REMOVE_TEXT_COLOR)
            self.screen.blit(x_s, x_s.get_rect(center=rem_rect.center))

    def _draw_back_button(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
