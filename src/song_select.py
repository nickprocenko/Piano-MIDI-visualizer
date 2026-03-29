"""Scrollable MIDI song selection screen."""

from __future__ import annotations

import pathlib
import pygame
from src import config as cfg
from src import file_limits

# Colour palette (matches menu.py)
BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)
NO_FILES_COLOR = (150, 150, 150)
SCROLLBAR_TRACK = (25, 25, 35)
SCROLLBAR_THUMB = (70, 70, 100)

TITLE_FONT_SIZE = 42
ITEM_FONT_SIZE = 24
BACK_FONT_SIZE = 30
ITEM_HEIGHT = 50
ITEM_GAP = 8
ITEM_WIDTH = 680
BACK_BTN_W = 160
BACK_BTN_H = 52
SCROLLBAR_W = 8
SCROLL_SPEED = 3   # items per mouse-wheel tick


def _scan_folders(folders: list[str]) -> tuple[list[pathlib.Path], int]:
    """Recursively find allowed .mid / .midi files in *folders*, deduplicated."""
    seen: set[pathlib.Path] = set()
    result: list[pathlib.Path] = []
    skipped_oversize = 0
    for folder in folders:
        p = pathlib.Path(folder)
        if not p.is_dir():
            continue
        for ext in ("*.mid", "*.midi", "*.MID", "*.MIDI"):
            for f in sorted(p.rglob(ext)):
                if f not in seen:
                    seen.add(f)
                    if not file_limits.is_allowed_midi_file(f):
                        skipped_oversize += 1
                        continue
                    result.append(f)
    return result, skipped_oversize


def _truncate(font: pygame.font.Font, text: str, max_w: int) -> str:
    if font.render(text, True, (0, 0, 0)).get_width() <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        if font.render(text + "…", True, (0, 0, 0)).get_width() <= max_w:
            return text + "…"
    return "…"


class SongSelect:
    """
    Scrollable list of MIDI files found in the configured search folders.

    ``handle_event()`` returns:
      ``"select"``  — user chose a file; path is in ``self.selected_file``.
      ``"back"``    — user pressed BACK or ESC.
      ``None``      — nothing actionable.
    """

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.selected_file: pathlib.Path | None = None

        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._item_font = pygame.font.SysFont("Arial", ITEM_FONT_SIZE)
        self._back_font = pygame.font.SysFont("Arial", BACK_FONT_SIZE)

        self._files: list[pathlib.Path] = []
        self._skipped_oversize_files: int = 0
        self._scroll: int = 0          # index of the topmost visible item
        self._visible_count: int = 1

        self._hover_item: int = -1
        self._hover_back: bool = False
        self._cursor: int = 0  # keyboard / MIDI nav cursor

        self._list_rect = pygame.Rect(0, 0, 0, 0)
        self._item_rects: list[pygame.Rect] = []
        self._back_rect = pygame.Rect(0, 0, BACK_BTN_W, BACK_BTN_H)

        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)

        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-scan configured folders and rebuild the layout."""
        folders = cfg.load().get("search_folders", [])
        self._files, self._skipped_oversize_files = _scan_folders(folders)
        self._scroll = 0
        self._cursor = 0
        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "back"
            elif event.key == pygame.K_UP:
                if self._cursor > 0:
                    self._cursor -= 1
                    if self._cursor < self._scroll:
                        self._scroll = self._cursor
                        self._rebuild_item_rects()
                return None
            elif event.key == pygame.K_DOWN:
                if self._cursor < len(self._files) - 1:
                    self._cursor += 1
                    if self._cursor >= self._scroll + self._visible_count:
                        self._scroll = self._cursor - self._visible_count + 1
                        self._rebuild_item_rects()
                return None
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if 0 <= self._cursor < len(self._files):
                    self.selected_file = self._files[self._cursor]
                    return "select"

        if event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, len(self._files) - self._visible_count)
            self._scroll = max(0, min(self._scroll - event.y * SCROLL_SPEED, max_scroll))
            self._rebuild_item_rects()
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            for screen_idx, rect in enumerate(self._item_rects):
                if rect.collidepoint(event.pos):
                    file_idx = self._scroll + screen_idx
                    if file_idx < len(self._files):
                        self.selected_file = self._files[file_idx]
                        return "select"

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_files()
        self._draw_scrollbar()
        self._draw_back()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Select Song", True, TITLE_COLOR)
        title_y = sr.height // 8
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        list_top = title_y + title_surf.get_height() + 32
        back_y = sr.height - BACK_BTN_H - 24
        list_bottom = back_y - 20

        self._list_rect = pygame.Rect(
            cx - ITEM_WIDTH // 2, list_top, ITEM_WIDTH, list_bottom - list_top
        )
        self._visible_count = max(
            1, self._list_rect.height // (ITEM_HEIGHT + ITEM_GAP)
        )

        self._back_rect = pygame.Rect(
            cx - BACK_BTN_W // 2, back_y, BACK_BTN_W, BACK_BTN_H
        )
        self._rebuild_item_rects()

    def _rebuild_item_rects(self) -> None:
        self._item_rects = []
        y = self._list_rect.top
        for i in range(self._visible_count):
            if self._scroll + i >= len(self._files):
                break
            rect = pygame.Rect(
                self._list_rect.left, y, self._list_rect.width, ITEM_HEIGHT
            )
            self._item_rects.append(rect)
            y += ITEM_HEIGHT + ITEM_GAP

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_item = -1
        for i, rect in enumerate(self._item_rects):
            if rect.collidepoint(pos):
                self._hover_item = i
                break

    def _draw_title(self) -> None:
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)

    def _draw_files(self) -> None:
        if not self._files:
            sr = self.screen.get_rect()
            lines = ["No MIDI files found.", "Add search folders in Settings."]
            if self._skipped_oversize_files > 0:
                lines.append(
                    f"{self._skipped_oversize_files} oversized MIDI file(s) were skipped "
                    f"(limit: {file_limits.format_limit_mb(file_limits.MAX_MIDI_FILE_BYTES)})."
                )
            y = self._list_rect.centery - len(lines) * 18
            for line in lines:
                surf = self._item_font.render(line, True, NO_FILES_COLOR)
                self.screen.blit(surf, (sr.centerx - surf.get_width() // 2, y))
                y += 38
            return

        prev_clip = self.screen.get_clip()
        self.screen.set_clip(self._list_rect)

        for screen_idx, rect in enumerate(self._item_rects):
            file_idx_this = self._scroll + screen_idx
            hovered = screen_idx == self._hover_item or file_idx_this == self._cursor
            bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
            fg = BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(
                self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=6
            )

            file_idx = self._scroll + screen_idx
            name = _truncate(self._item_font, self._files[file_idx].name, rect.width - 20)
            surf = self._item_font.render(name, True, fg)
            self.screen.blit(surf, surf.get_rect(midleft=(rect.left + 10, rect.centery)))

        if self._skipped_oversize_files > 0:
            note = self._item_font.render(
                f"Skipped {self._skipped_oversize_files} oversized MIDI file(s) "
                f"over {file_limits.format_limit_mb(file_limits.MAX_MIDI_FILE_BYTES)}.",
                True,
                NO_FILES_COLOR,
            )
            note_rect = note.get_rect(bottomleft=(self._list_rect.left + 4, self._list_rect.bottom - 4))
            self.screen.blit(note, note_rect)

        self.screen.set_clip(prev_clip)

    def _draw_scrollbar(self) -> None:
        total = len(self._files)
        if total <= self._visible_count:
            return

        bar_rect = pygame.Rect(
            self._list_rect.right + 6,
            self._list_rect.top,
            SCROLLBAR_W,
            self._list_rect.height,
        )
        bar_h = self._list_rect.height
        thumb_h = max(20, int(bar_h * self._visible_count / total))
        thumb_y = self._list_rect.top + int(
            (bar_h - thumb_h) * self._scroll / max(1, total - self._visible_count)
        )
        thumb_rect = pygame.Rect(bar_rect.left, thumb_y, SCROLLBAR_W, thumb_h)

        pygame.draw.rect(self.screen, SCROLLBAR_TRACK, bar_rect, border_radius=4)
        pygame.draw.rect(self.screen, SCROLLBAR_THUMB, thumb_rect, border_radius=4)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8
        )
        label = self._back_font.render("BACK", True, fg)
        self.screen.blit(label, label.get_rect(center=self._back_rect.center))
