"""Theme management screen.

Allows the user to:
  - Save current settings as a new named theme.
  - Update the currently active theme in-place.
  - Load any saved theme (applies it to config immediately).
  - Delete any saved theme.
  - Rename a theme by clicking its name cell and typing.

``handle_event()`` returns:
  ``"back"`` — close and return to Settings.
  ``None``   — no navigational action.
"""

from __future__ import annotations

import pygame
import src.themes as themes_mod

# ── Colour palette (matches app palette) ─────────────────────────
BG_COLOR            = (15,  15,  20)
TITLE_COLOR         = (230, 230, 230)
BTN_NORMAL_BG       = (35,  35,  45)
BTN_HOVER_BG        = (60,  60,  80)
BTN_TEXT            = (210, 210, 210)
BTN_TEXT_HOVER      = (255, 255, 255)
BORDER_COLOR        = (80,  80, 110)
SAVE_BG             = (28,  55,  28)
SAVE_BG_HOVER       = (45,  85,  45)
SAVE_TEXT           = (110, 215, 110)
SAVE_TEXT_HOVER     = (170, 255, 170)
UPDATE_BG           = (35,  45,  65)
UPDATE_BG_HOVER     = (55,  70, 105)
UPDATE_TEXT         = (120, 165, 230)
UPDATE_TEXT_HOVER   = (180, 210, 255)
EDITOR_BG           = (24,  24,  34)
EDITOR_ACTIVE_BG    = (38,  38,  58)
EDITOR_BORDER       = (68,  68,  98)
EDITOR_ACTIVE_BORDER= (0,  185, 210)
ACTIVE_BORDER       = (0,  200, 200)
DEL_BG              = (58,  25,  25)
DEL_BG_HOVER        = (95,  38,  38)
DEL_TEXT            = (220, 140, 140)
DEL_TEXT_HOVER      = (255, 180, 180)
LOADED_BG           = (28,  58,  28)
LOADED_BG_HOVER     = (45,  85,  45)
LOADED_TEXT         = (110, 215, 110)
LOADED_TEXT_HOVER   = (160, 255, 160)

# ── Layout constants ──────────────────────────────────────────────
TITLE_FONT_SIZE = 40
BTN_FONT_SIZE   = 26
ROW_FONT_SIZE   = 21

BACK_W,   BACK_H   = 160,  50
TOP_BTN_W, TOP_BTN_H = 380, 50
NAME_W              = 260
SWATCH_W, SWATCH_H  = 56, 30
LOAD_W              = 90
DEL_W               = 80
ROW_H               = 50
ROW_GAP             = 8
COL_GAP             = 8

# total row width: NAME_W + gap + SWATCH_W + gap + LOAD_W + gap + DEL_W
ROW_FULL_W = NAME_W + COL_GAP + SWATCH_W + COL_GAP + LOAD_W + COL_GAP + DEL_W


class ThemeSettingsScreen:
    """Theme creation, selection and deletion screen."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._btn_font   = pygame.font.SysFont("Arial", BTN_FONT_SIZE)
        self._row_font   = pygame.font.SysFont("Arial", ROW_FONT_SIZE)

        self._themes: list[dict]  = themes_mod.load_user_themes()
        self._active_index: int   = themes_mod.get_active_index()

        # Inline name editing state
        self._editing_index: int  = -1
        self._editing_text: str   = ""

        # Hover state
        self._hover_save:   bool  = False
        self._hover_update: bool  = False
        self._hover_back:   bool  = False
        self._hover_load:   int   = -1
        self._hover_del:    int   = -1
        self._hover_name:   int   = -1

        # Scroll state
        self._scroll_offset: int  = 0
        self._scroll_area_h: int  = 400

        # Layout rects (rebuilt by _build_layout)
        self._title_surf: pygame.Surface | None = None
        self._title_pos  = (0, 0)
        self._save_rect   = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._update_rect = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._back_rect   = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._rows_y: int = 0
        self._row_name_rects:   list[pygame.Rect] = []
        self._row_swatch_rects: list[pygame.Rect] = []
        self._row_load_rects:   list[pygame.Rect] = []
        self._row_del_rects:    list[pygame.Rect] = []

        self._build_layout()

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────
    # Private – input handling
    # ─────────────────────────────────────────────────────────────

    def _handle_edit_key(self, event: pygame.event.Event) -> str | None:
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_edit()
        elif event.key == pygame.K_ESCAPE:
            self._editing_index = -1
            self._editing_text  = ""
        elif event.key == pygame.K_BACKSPACE:
            self._editing_text = self._editing_text[:-1]
        else:
            ch = event.unicode
            if ch and ch.isprintable() and len(self._editing_text) < 40:
                self._editing_text += ch
        return None

    def _handle_click(self, pos: tuple[int, int]) -> str | None:
        # Commit any active name edit when clicking elsewhere
        if self._editing_index >= 0:
            idx = self._editing_index
            if idx >= len(self._row_name_rects) or not self._row_name_rects[idx].collidepoint(pos):
                self._commit_edit()

        if self._back_rect.collidepoint(pos):
            return "back"

        if self._save_rect.collidepoint(pos):
            self._save_as_new()
            return None

        if self._update_rect.collidepoint(pos):
            self._update_active()
            return None

        for i, rect in enumerate(self._row_load_rects):
            if rect.collidepoint(pos):
                self._load_theme(i)
                return None

        for i, rect in enumerate(self._row_del_rects):
            if rect.collidepoint(pos):
                self._delete_theme(i)
                return None

        for i, rect in enumerate(self._row_name_rects):
            if rect.collidepoint(pos):
                self._start_edit(i)
                return None

        return None

    def _commit_edit(self) -> None:
        idx = self._editing_index
        if 0 <= idx < len(self._themes):
            name = self._editing_text.strip() or f"Theme {idx + 1}"
            self._themes[idx]["name"] = name
            themes_mod.save_user_themes(self._themes)
        self._editing_index = -1
        self._editing_text  = ""

    def _start_edit(self, index: int) -> None:
        self._editing_index = index
        self._editing_text  = self._themes[index].get("name", f"Theme {index + 1}")

    # ─────────────────────────────────────────────────────────────
    # Private – theme operations
    # ─────────────────────────────────────────────────────────────

    def _save_as_new(self) -> None:
        name  = f"Theme {len(self._themes) + 1}"
        theme = themes_mod.snapshot_current(name)
        self._themes.append(theme)
        self._active_index = len(self._themes) - 1
        themes_mod.save_user_themes(self._themes)
        themes_mod.set_active_index(self._active_index)
        self._build_layout()

    def _update_active(self) -> None:
        if not self._themes:
            return
        idx = self._active_index
        if idx >= len(self._themes):
            idx = len(self._themes) - 1
        name = self._themes[idx].get("name", f"Theme {idx + 1}")
        updated = themes_mod.snapshot_current(name)
        self._themes[idx] = updated
        themes_mod.save_user_themes(self._themes)
        themes_mod.set_active_index(idx)

    def _load_theme(self, index: int) -> None:
        if 0 <= index < len(self._themes):
            self._active_index = index
            themes_mod.set_active_index(index)
            themes_mod.apply_theme_to_config(self._themes[index])

    def _delete_theme(self, index: int) -> None:
        if 0 <= index < len(self._themes):
            self._themes.pop(index)
            if self._active_index >= len(self._themes):
                self._active_index = max(0, len(self._themes) - 1)
            themes_mod.save_user_themes(self._themes)
            themes_mod.set_active_index(self._active_index)
            self._build_layout()

    def _do_scroll(self, delta: int) -> None:
        total_h   = len(self._themes) * (ROW_H + ROW_GAP)
        max_scroll = max(0, total_h - self._scroll_area_h)
        self._scroll_offset = max(0, min(max_scroll, self._scroll_offset + delta))
        self._build_layout()

    # ─────────────────────────────────────────────────────────────
    # Private – layout
    # ─────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        sr  = self.screen.get_rect()
        cx  = sr.centerx

        title_surf = self._title_font.render("Theme Manager", True, TITLE_COLOR)
        title_y    = sr.height // 10
        self._title_surf = title_surf
        self._title_pos  = (cx - title_surf.get_width() // 2, title_y)

        btn_y = title_y + title_surf.get_height() + 20
        self._save_rect   = pygame.Rect(cx - TOP_BTN_W - 6, btn_y, TOP_BTN_W, TOP_BTN_H)
        self._update_rect = pygame.Rect(cx + 6,              btn_y, TOP_BTN_W, TOP_BTN_H)

        self._rows_y       = btn_y + TOP_BTN_H + 20
        self._scroll_area_h = max(60, sr.height - self._rows_y - BACK_H - 36)

        rx = cx - ROW_FULL_W // 2

        self._row_name_rects   = []
        self._row_swatch_rects = []
        self._row_load_rects   = []
        self._row_del_rects    = []

        for i in range(len(self._themes)):
            y = self._rows_y + i * (ROW_H + ROW_GAP) - self._scroll_offset

            self._row_name_rects.append(
                pygame.Rect(rx, y, NAME_W, ROW_H)
            )
            swatch_x = rx + NAME_W + COL_GAP
            self._row_swatch_rects.append(
                pygame.Rect(swatch_x, y + (ROW_H - SWATCH_H) // 2, SWATCH_W, SWATCH_H)
            )
            load_x = swatch_x + SWATCH_W + COL_GAP
            self._row_load_rects.append(
                pygame.Rect(load_x, y, LOAD_W, ROW_H)
            )
            del_x = load_x + LOAD_W + COL_GAP
            self._row_del_rects.append(
                pygame.Rect(del_x, y, DEL_W, ROW_H)
            )

        back_y = sr.height - BACK_H - 24
        self._back_rect = pygame.Rect(cx - BACK_W // 2, back_y, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_save   = self._save_rect.collidepoint(pos)
        self._hover_update = self._update_rect.collidepoint(pos)
        self._hover_back   = self._back_rect.collidepoint(pos)
        self._hover_load   = next((i for i, r in enumerate(self._row_load_rects) if r.collidepoint(pos)), -1)
        self._hover_del    = next((i for i, r in enumerate(self._row_del_rects)  if r.collidepoint(pos)), -1)
        self._hover_name   = next((i for i, r in enumerate(self._row_name_rects) if r.collidepoint(pos)), -1)

    # ─────────────────────────────────────────────────────────────
    # Private – drawing
    # ─────────────────────────────────────────────────────────────

    def _draw_btn(
        self,
        rect: pygame.Rect,
        label: str,
        hover: bool,
        bg: tuple,
        bg_h: tuple,
        fg: tuple,
        fg_h: tuple,
    ) -> None:
        bg_c  = bg_h if hover else bg
        fg_c  = fg_h if hover else fg
        pygame.draw.rect(self.screen, bg_c,       rect, border_radius=8)
        pygame.draw.rect(self.screen, BORDER_COLOR, rect, width=1, border_radius=8)
        surf = self._btn_font.render(label, True, fg_c)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_top_buttons(self) -> None:
        self._draw_btn(
            self._save_rect, "SAVE CURRENT AS NEW",
            self._hover_save,
            SAVE_BG, SAVE_BG_HOVER, SAVE_TEXT, SAVE_TEXT_HOVER,
        )
        self._draw_btn(
            self._update_rect, "UPDATE ACTIVE THEME",
            self._hover_update,
            UPDATE_BG, UPDATE_BG_HOVER, UPDATE_TEXT, UPDATE_TEXT_HOVER,
        )

    def _draw_back_button(self) -> None:
        self._draw_btn(
            self._back_rect, "BACK",
            self._hover_back,
            BTN_NORMAL_BG, BTN_HOVER_BG, BTN_TEXT, BTN_TEXT_HOVER,
        )

    def _draw_rows(self) -> None:
        sr = self.screen.get_rect()
        if not self._themes:
            msg = self._row_font.render(
                "No themes saved yet.  Press  SAVE CURRENT AS NEW  to create one.",
                True, (130, 130, 140),
            )
            self.screen.blit(msg, msg.get_rect(centerx=sr.centerx, top=self._rows_y + 16))
            return

        clip = pygame.Rect(0, self._rows_y, sr.width, self._scroll_area_h)
        self.screen.set_clip(clip)

        for i, theme in enumerate(self._themes):
            name_rect   = self._row_name_rects[i]
            swatch_rect = self._row_swatch_rects[i]
            load_rect   = self._row_load_rects[i]
            del_rect    = self._row_del_rects[i]

            # Cull rows outside the visible scroll area
            if name_rect.bottom < self._rows_y or name_rect.top > self._rows_y + self._scroll_area_h:
                continue

            is_active  = (i == self._active_index)
            is_editing = (i == self._editing_index)

            # ── Name cell ────────────────────────────────────────
            name_bg     = EDITOR_ACTIVE_BG if is_editing else EDITOR_BG
            name_border = (
                EDITOR_ACTIVE_BORDER if is_editing
                else ACTIVE_BORDER   if is_active
                else EDITOR_BORDER
            )
            border_w    = 2 if is_active or is_editing else 1
            pygame.draw.rect(self.screen, name_bg,     name_rect, border_radius=6)
            pygame.draw.rect(self.screen, name_border, name_rect, width=border_w, border_radius=6)

            display_text = (self._editing_text + "|") if is_editing else theme.get("name", f"Theme {i+1}")
            name_surf    = self._row_font.render(display_text, True, TITLE_COLOR if is_active else BTN_TEXT)
            # Clip to name cell width
            max_w = NAME_W - 12
            if name_surf.get_width() > max_w:
                name_surf = name_surf.subsurface((name_surf.get_width() - max_w, 0, max_w, name_surf.get_height()))
            self.screen.blit(name_surf, (name_rect.x + 6, name_rect.centery - name_surf.get_height() // 2))

            # ── Color swatch (note color | LED active color) ──────
            note_r = theme.get("note_color_r", 0)
            note_g = theme.get("note_color_g", 230)
            note_b = theme.get("note_color_b", 230)
            led_r  = theme.get("led_active_r",  0)
            led_g  = theme.get("led_active_g",  220)
            led_b  = theme.get("led_active_b",  220)
            hw     = swatch_rect.width // 2
            pygame.draw.rect(
                self.screen, (note_r, note_g, note_b),
                pygame.Rect(swatch_rect.x, swatch_rect.y, hw, swatch_rect.height),
                border_radius=4,
            )
            pygame.draw.rect(
                self.screen, (led_r, led_g, led_b),
                pygame.Rect(swatch_rect.x + hw, swatch_rect.y, hw, swatch_rect.height),
                border_radius=4,
            )
            pygame.draw.rect(self.screen, BORDER_COLOR, swatch_rect, width=1, border_radius=4)

            # ── Load button ───────────────────────────────────────
            self._draw_btn(
                load_rect,
                "LOADED" if is_active else "LOAD",
                self._hover_load == i,
                LOADED_BG    if is_active else BTN_NORMAL_BG,
                LOADED_BG_HOVER if is_active else BTN_HOVER_BG,
                LOADED_TEXT  if is_active else BTN_TEXT,
                LOADED_TEXT_HOVER if is_active else BTN_TEXT_HOVER,
            )

            # ── Delete button ─────────────────────────────────────
            self._draw_btn(
                del_rect, "DEL",
                self._hover_del == i,
                DEL_BG, DEL_BG_HOVER, DEL_TEXT, DEL_TEXT_HOVER,
            )

        self.screen.set_clip(None)
