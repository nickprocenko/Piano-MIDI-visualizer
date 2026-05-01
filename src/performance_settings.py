"""Performance list screen."""

from __future__ import annotations

import pygame

import src.performance_store as perf_store

BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BTN_NORMAL_BG = (35, 35, 45)
BTN_HOVER_BG = (60, 60, 80)
BTN_TEXT = (210, 210, 210)
BTN_TEXT_HOVER = (255, 255, 255)
BORDER_COLOR = (80, 80, 110)
EDITOR_BG = (24, 24, 34)
EDITOR_ACTIVE_BG = (38, 38, 58)
EDITOR_BORDER = (68, 68, 98)
EDITOR_ACTIVE_BORDER = (0, 185, 210)
ACTIVE_BORDER = (0, 200, 200)
DEL_BG = (58, 25, 25)
DEL_BG_HOVER = (95, 38, 38)
DEL_TEXT = (220, 140, 140)
DEL_TEXT_HOVER = (255, 180, 180)
SAVE_BG = (28, 55, 28)
SAVE_BG_HOVER = (45, 85, 45)
SAVE_TEXT = (110, 215, 110)
SAVE_TEXT_HOVER = (170, 255, 170)
UPDATE_BG = (35, 45, 65)
UPDATE_BG_HOVER = (55, 70, 105)
UPDATE_TEXT = (120, 165, 230)
UPDATE_TEXT_HOVER = (180, 210, 255)

TITLE_FONT_SIZE = 40
BTN_FONT_SIZE = 26
ROW_FONT_SIZE = 21
BACK_W, BACK_H = 160, 50
TOP_BTN_W, TOP_BTN_H = 380, 50
NAME_W = 340
THEMES_W = 120
DEL_W = 80
ROW_H = 54
ROW_GAP = 8
COL_GAP = 8
ROW_FULL_W = NAME_W + COL_GAP + THEMES_W + COL_GAP + DEL_W


class PerformanceSettingsScreen:
    """Manage named performances (songs) and enter their theme pages."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)
        self._row_font = pygame.font.SysFont("Arial", ROW_FONT_SIZE)

        self._performances = perf_store.load_performances()
        self._active_id = perf_store.get_active_performance_id()
        self._editing_index = -1
        self._editing_text = ""

        self._hover_add = False
        self._hover_save_all = False
        self._hover_back = False
        self._hover_themes = -1
        self._hover_del = -1
        self._hover_name = -1

        self._scroll_offset = 0
        self._scroll_area_h = 400

        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._add_rect = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._save_all_rect = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._rows_y = 0
        self._row_name_rects: list[pygame.Rect] = []
        self._row_themes_rects: list[pygame.Rect] = []
        self._row_del_rects: list[pygame.Rect] = []

        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN:
            if self._editing_index >= 0:
                return self._handle_edit_key(event)
            if event.key == pygame.K_ESCAPE:
                return "back"

        if event.type == pygame.MOUSEWHEEL:
            self._do_scroll(-event.y * 32)
            return None

        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_click(event.pos)

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)
        self._draw_top_buttons()
        self._draw_rows()
        self._draw_back_button()

    def _refresh(self) -> None:
        self._performances = perf_store.load_performances()
        self._active_id = perf_store.get_active_performance_id()
        self._build_layout()

    def _handle_edit_key(self, event: pygame.event.Event) -> str | None:
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_edit()
        elif event.key == pygame.K_ESCAPE:
            self._editing_index = -1
            self._editing_text = ""
        elif event.key == pygame.K_BACKSPACE:
            self._editing_text = self._editing_text[:-1]
        else:
            ch = event.unicode
            if ch and ch.isprintable() and len(self._editing_text) < 50:
                self._editing_text += ch
        return None

    def _handle_click(self, pos: tuple[int, int]) -> str | None:
        if self._editing_index >= 0:
            idx = self._editing_index
            if idx >= len(self._row_name_rects) or not self._row_name_rects[idx].collidepoint(pos):
                self._commit_edit()

        if self._back_rect.collidepoint(pos):
            return "back"
        if self._add_rect.collidepoint(pos):
            name = f"Performance {len(self._performances) + 1}"
            perf_store.create_performance(name)
            self._refresh()
            return None
        if self._save_all_rect.collidepoint(pos):
            if self._active_id:
                perf_store.save_active_theme_from_current(self._active_id)
                self._refresh()
            return None

        for i, rect in enumerate(self._row_themes_rects):
            if rect.collidepoint(pos):
                performance_id = str(self._performances[i].get("id", ""))
                perf_store.set_active_performance(performance_id)
                self._active_id = performance_id
                return "theme_settings"

        for i, rect in enumerate(self._row_del_rects):
            if rect.collidepoint(pos):
                perf_store.delete_performance(str(self._performances[i].get("id", "")))
                self._refresh()
                return None

        for i, rect in enumerate(self._row_name_rects):
            if rect.collidepoint(pos):
                performance_id = str(self._performances[i].get("id", ""))
                perf_store.set_active_performance(performance_id)
                self._active_id = performance_id
                self._start_edit(i)
                return None

        return None

    def _commit_edit(self) -> None:
        idx = self._editing_index
        if 0 <= idx < len(self._performances):
            performance_id = str(self._performances[idx].get("id", ""))
            name = self._editing_text.strip() or f"Performance {idx + 1}"
            perf_store.rename_performance(performance_id, name)
        self._editing_index = -1
        self._editing_text = ""
        self._refresh()

    def _start_edit(self, index: int) -> None:
        self._editing_index = index
        self._editing_text = str(self._performances[index].get("name", f"Performance {index + 1}"))

    def _do_scroll(self, delta: int) -> None:
        total_h = len(self._performances) * (ROW_H + ROW_GAP)
        max_scroll = max(0, total_h - self._scroll_area_h)
        self._scroll_offset = max(0, min(max_scroll, self._scroll_offset + delta))
        self._build_layout()

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx
        title_surf = self._title_font.render("Performances", True, TITLE_COLOR)
        title_y = sr.height // 10
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        btn_y = title_y + title_surf.get_height() + 20
        self._add_rect = pygame.Rect(cx - TOP_BTN_W - 6, btn_y, TOP_BTN_W, TOP_BTN_H)
        self._save_all_rect = pygame.Rect(cx + 6, btn_y, TOP_BTN_W, TOP_BTN_H)
        self._rows_y = btn_y + TOP_BTN_H + 20
        self._scroll_area_h = max(60, sr.height - self._rows_y - BACK_H - 36)
        rx = cx - ROW_FULL_W // 2

        self._row_name_rects = []
        self._row_themes_rects = []
        self._row_del_rects = []
        for i in range(len(self._performances)):
            y = self._rows_y + i * (ROW_H + ROW_GAP) - self._scroll_offset
            self._row_name_rects.append(pygame.Rect(rx, y, NAME_W, ROW_H))
            themes_x = rx + NAME_W + COL_GAP
            self._row_themes_rects.append(pygame.Rect(themes_x, y, THEMES_W, ROW_H))
            del_x = themes_x + THEMES_W + COL_GAP
            self._row_del_rects.append(pygame.Rect(del_x, y, DEL_W, ROW_H))

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_add = self._add_rect.collidepoint(pos)
        self._hover_save_all = self._save_all_rect.collidepoint(pos)
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_themes = next((i for i, r in enumerate(self._row_themes_rects) if r.collidepoint(pos)), -1)
        self._hover_del = next((i for i, r in enumerate(self._row_del_rects) if r.collidepoint(pos)), -1)
        self._hover_name = next((i for i, r in enumerate(self._row_name_rects) if r.collidepoint(pos)), -1)

    def _draw_btn(
        self,
        rect: pygame.Rect,
        label: str,
        hover: bool,
        bg: tuple[int, int, int],
        bg_h: tuple[int, int, int],
        fg: tuple[int, int, int],
        fg_h: tuple[int, int, int],
    ) -> None:
        pygame.draw.rect(self.screen, bg_h if hover else bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, BORDER_COLOR, rect, width=1, border_radius=8)
        surf = self._btn_font.render(label, True, fg_h if hover else fg)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_top_buttons(self) -> None:
        self._draw_btn(
            self._add_rect,
            "ADD PERFORMANCE",
            self._hover_add,
            SAVE_BG,
            SAVE_BG_HOVER,
            SAVE_TEXT,
            SAVE_TEXT_HOVER,
        )
        self._draw_btn(
            self._save_all_rect,
            "SAVE ALL CHANGES",
            self._hover_save_all,
            UPDATE_BG,
            UPDATE_BG_HOVER,
            UPDATE_TEXT,
            UPDATE_TEXT_HOVER,
        )

    def _draw_back_button(self) -> None:
        self._draw_btn(
            self._back_rect,
            "BACK",
            self._hover_back,
            BTN_NORMAL_BG,
            BTN_HOVER_BG,
            BTN_TEXT,
            BTN_TEXT_HOVER,
        )

    def _draw_rows(self) -> None:
        sr = self.screen.get_rect()
        if not self._performances:
            msg = self._row_font.render("No performances yet. Press ADD PERFORMANCE to create one.", True, (130, 130, 140))
            self.screen.blit(msg, msg.get_rect(centerx=sr.centerx, top=self._rows_y + 16))
            return

        clip = pygame.Rect(0, self._rows_y, sr.width, self._scroll_area_h)
        self.screen.set_clip(clip)
        for i, performance in enumerate(self._performances):
            name_rect = self._row_name_rects[i]
            themes_rect = self._row_themes_rects[i]
            del_rect = self._row_del_rects[i]
            if name_rect.bottom < self._rows_y or name_rect.top > self._rows_y + self._scroll_area_h:
                continue

            is_active = str(performance.get("id", "")) == self._active_id
            is_editing = i == self._editing_index
            name_bg = EDITOR_ACTIVE_BG if is_editing else EDITOR_BG
            name_border = EDITOR_ACTIVE_BORDER if is_editing else ACTIVE_BORDER if is_active else EDITOR_BORDER
            pygame.draw.rect(self.screen, name_bg, name_rect, border_radius=6)
            pygame.draw.rect(self.screen, name_border, name_rect, width=2 if (is_active or is_editing) else 1, border_radius=6)
            display_text = (self._editing_text + "|") if is_editing else str(performance.get("name", f"Performance {i + 1}"))
            surf = self._row_font.render(display_text, True, TITLE_COLOR if is_active else BTN_TEXT)
            self.screen.blit(surf, (name_rect.x + 6, name_rect.centery - surf.get_height() // 2))

            self._draw_btn(themes_rect, "THEMES", self._hover_themes == i, BTN_NORMAL_BG, BTN_HOVER_BG, BTN_TEXT, BTN_TEXT_HOVER)
            self._draw_btn(del_rect, "DEL", self._hover_del == i, DEL_BG, DEL_BG_HOVER, DEL_TEXT, DEL_TEXT_HOVER)

        self.screen.set_clip(None)
