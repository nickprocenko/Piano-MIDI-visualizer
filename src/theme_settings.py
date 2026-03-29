"""Theme hierarchy settings screen — Banks, Themes, and Channels.

Allows hierarchical navigation through:
    - Level 1: Banks (song folders, renameable)
        - Level 2: Themes (sections within a bank, renameable)
        - Level 3: Channel editor
        - Level 4: Channel note settings

When a theme is loaded, both note styles and background image are applied.

``handle_event()`` returns:
  ``"back"`` — close and return to Settings.
    ``"menu"`` — close and return to Main Menu.
  ``None`` — no navigational action.
"""

from __future__ import annotations

import pathlib

import pygame
import src.themes as themes_mod
from src import file_limits


def _pick_image() -> str | None:
    """Open a file picker; returns a single selected path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        path = filedialog.askopenfilename(
            parent=root,
            title="Select background image, GIF, or video",
            filetypes=[
                ("Media files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif;*.mp4;*.mov;*.avi;*.mkv;*.webm;*.m4v"),
                ("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif"),
                ("Video files", "*.mp4;*.mov;*.avi;*.mkv;*.webm;*.m4v"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        if not path:
            return None
        selected = pathlib.Path(path)
        if not file_limits.is_allowed_media_file(selected):
            print(
                "Skipping selected background media over size limit: "
                f"{selected} (limit {file_limits.format_limit_mb(file_limits.MAX_MEDIA_FILE_BYTES)})"
            )
            return None
        return path
    except Exception:
        return None

# ── Colour palette ───────────────────────────────────────────────
BG_COLOR            = (15,  15,  20)
TITLE_COLOR         = (230, 230, 230)
TEXT_COLOR          = (210, 210, 210)
BREADCRUMB_COLOR    = (150, 150, 150)
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

# ── Layout constants ──────────────────────────────────────────────
TITLE_FONT_SIZE     = 40
BREADCRUMB_FONT_SIZE = 18
BTN_FONT_SIZE       = 26
ROW_FONT_SIZE       = 21

BACK_W,   BACK_H    = 160,  50
MENU_W             = 220
TOP_BTN_W, TOP_BTN_H = 380, 50
NAME_W              = 260
THUMB_W, THUMB_H    = 60, 36  # background image thumbnail
SLIDER_W, SLIDER_H  = 80, 8   # transition softness slider
LOAD_W              = 90
DEL_W               = 80
STYLES_W             = 80
RENAME_W            = 100
ROW_H               = 50
ROW_GAP             = 8
COL_GAP             = 8


class ThemeSettingsScreen:
    """Hierarchical theme browser and manager."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._breadcrumb_font = pygame.font.SysFont("Arial", BREADCRUMB_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)
        self._row_font = pygame.font.SysFont("Arial", ROW_FONT_SIZE)

        self._banks: list[dict] = themes_mod.load_banks()

        # Navigation state
        self._level: int = 1  # 1=banks, 2=themes, 3=channels, 4=channel note settings
        self._bank_index: int = themes_mod.get_active_bank_index()
        self._theme_index: int = themes_mod.get_active_theme_index()

        # Inline name editing state
        self._editing_index: int = -1
        self._editing_text: str = ""

        # Hover state
        self._hover_back: bool = False
        self._hover_menu: bool = False
        self._hover_open: int = -1
        self._hover_save: bool = False
        self._hover_update: bool = False
        self._hover_load: int = -1
        self._hover_del: int = -1
        self._hover_name: int = -1
        self._hover_rename: int = -1
        self._hover_slider: int = -1
        self._hover_media: int = -1
        self._hover_styles: int = -1
        self._drag_slider: int = -1

        # Scroll state
        self._scroll_offset: int = 0
        self._scroll_area_h: int = 400

        # Layout rects
        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._breadcrumb_surf: pygame.Surface | None = None
        self._breadcrumb_pos = (0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._menu_rect = pygame.Rect(0, 0, MENU_W, BACK_H)
        self._save_rect = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._update_rect = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._open_rects: list[pygame.Rect] = []
        self._row_name_rects: list[pygame.Rect] = []
        self._row_thumb_rects: list[pygame.Rect] = []
        self._row_media_rects: list[pygame.Rect] = []
        self._row_load_rects: list[pygame.Rect] = []
        self._row_del_rects: list[pygame.Rect] = []
        self._row_rename_rects: list[pygame.Rect] = []
        self._row_slider_rects: list[pygame.Rect] = []
        self._row_styles_rects: list[pygame.Rect] = []
        self._rows_y: int = 0

        self._build_layout()

        # Level 4 channel view (no embedded Notes Settings screen)
        self._selected_channel: int = 1
        self._channel_rects: list[pygame.Rect] = []
        self._hover_channel: int = -1
        self._channel_notes_screen = None
        self._channel_parent_level: int = 2

        # Keyboard / MIDI navigation cursor (row index within the current level)
        self._cursor: int = 0

        # Cache scaled media previews so the theme list stays responsive.
        self._thumbnail_cache: dict[str, pygame.Surface | None] = {}

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if self._level == 4 and self._channel_notes_screen is not None:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._channel_notes_screen = None
                self._level = 3
                self._build_layout()
                return None
            result = self._channel_notes_screen.handle_event(event)
            if result == "back":
                self._channel_notes_screen = None
                self._level = 3
                self._build_layout()
            elif result == "save_theme":
                self._update_active_theme()
            return None

        if event.type == pygame.KEYDOWN:
            if self._editing_index >= 0:
                return self._handle_edit_key(event)
            if event.key == pygame.K_ESCAPE:
                if self._go_up_one():
                    return None
                return "back"
            if event.key == pygame.K_UP:
                self._move_cursor(-1)
                return None
            if event.key == pygame.K_DOWN:
                self._move_cursor(1)
                return None
            if event.key == pygame.K_LEFT:
                return self._cursor_left()
            if event.key == pygame.K_RIGHT:
                self._cursor_right()
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._confirm_cursor()
                return None

        if event.type == pygame.MOUSEWHEEL:
            self._do_scroll(-event.y * ROW_GAP * 4)
            return None

        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            if self._drag_slider >= 0 and self._level == 2:
                if self._drag_slider < len(self._row_slider_rects):
                    rect = self._row_slider_rects[self._drag_slider]
                    self._update_theme_slider_value(self._drag_slider, event.pos[0] - rect.x)
            return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_click(event.pos)

        return None

    def update(self, dt: int) -> None:
        if self._level == 4 and self._channel_notes_screen is not None:
            self._channel_notes_screen.update(dt)
            return
        _ = dt

    def draw(self) -> None:
        if self._level == 4 and self._channel_notes_screen is not None:
            self._channel_notes_screen.draw()
            return
        self.screen.fill(BG_COLOR)
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)
        if self._breadcrumb_surf:
            self.screen.blit(self._breadcrumb_surf, self._breadcrumb_pos)
        self._draw_rows()
        self._draw_back_button()

    # ─────────────────────────────────────────────────────────────
    # Private – input handling
    # ─────────────────────────────────────────────────────────────

    def _go_up_one(self) -> bool:
        if self._level <= 1:
            return False
        if self._level == 4:
            self._channel_notes_screen = None
            self._level = 3
            self._cursor = self._selected_channel - 1
        elif self._level == 3:
            self._level = self._channel_parent_level
            self._cursor = self._theme_index
        else:
            self._level -= 1
            self._cursor = self._bank_index
        self._build_layout()
        return True

    def _move_cursor(self, delta: int) -> None:
        """Move keyboard/MIDI navigation cursor within the current level."""
        if self._level == 1:
            n = len(self._banks)
            if n:
                self._cursor = (self._cursor + delta) % n
        elif self._level == 2:
            bank = self._banks[self._bank_index] if self._bank_index < len(self._banks) else {}
            n = len(bank.get("themes", []))
            if n:
                self._cursor = (self._cursor + delta) % n
        elif self._level == 3:
            # 4-column grid; up/down jumps a full row (4 cells)
            if delta < 0:
                self._cursor = max(0, self._cursor - 4)
            else:
                self._cursor = min(15, self._cursor + 4)
            self._selected_channel = self._cursor + 1

    def _cursor_left(self) -> str | None:
        """Left arrow: back at L1, slider -5% at L2, col-left at L3."""
        if self._level == 1:
            if self._go_up_one():
                return None
            return "back"
        elif self._level == 2:
            self._nudge_slider(-5)
        elif self._level == 3:
            row, col = divmod(self._cursor, 4)
            if col > 0:
                self._cursor = row * 4 + col - 1
                self._selected_channel = self._cursor + 1
        return None

    def _cursor_right(self) -> None:
        """Right arrow: open bank at L1, slider +5% at L2, col-right at L3."""
        if self._level == 1:
            self._open_bank_at_cursor()
        elif self._level == 2:
            self._nudge_slider(5)
        elif self._level == 3:
            row, col = divmod(self._cursor, 4)
            if col < 3:
                self._cursor = row * 4 + col + 1
                self._selected_channel = self._cursor + 1

    def _confirm_cursor(self) -> None:
        """Enter/confirm at the cursor row."""
        if self._level == 1:
            self._open_bank_at_cursor()
        elif self._level == 2:
            self._enter_channels(self._cursor)
        elif self._level == 3:
            self._open_channel_note_settings(self._selected_channel)

    def _open_bank_at_cursor(self) -> None:
        """Descend into the bank currently under _cursor."""
        if 0 <= self._cursor < len(self._banks):
            self._bank_index = self._cursor
            themes_mod.set_active_bank_index(self._cursor)
            self._level = 2
            self._cursor = 0
            self._build_layout()

    def _nudge_slider(self, delta: int) -> None:
        """Adjust transition softness for the cursor theme by delta percent."""
        if self._bank_index >= len(self._banks):
            return
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        if 0 <= self._cursor < len(themes):
            theme = themes[self._cursor]
            current = theme.get("background_transition_percent", 50)
            theme["background_transition_percent"] = max(10, min(90, current + delta))
            themes_mod.save_banks(self._banks)

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
            if ch and ch.isprintable() and len(self._editing_text) < 40:
                self._editing_text += ch
        return None

    def _handle_click(self, pos: tuple[int, int]) -> str | None:
        # Commit any active edit when clicking elsewhere
        if self._editing_index >= 0:
            idx = self._editing_index
            if idx >= len(self._row_name_rects) or not self._row_name_rects[idx].collidepoint(pos):
                self._commit_edit()

        if self._back_rect.collidepoint(pos):
            if self._go_up_one():
                return None
            return "back"

        if self._menu_rect.collidepoint(pos):
            return "menu"

        # Level-specific click handling
        if self._level == 1:
            return self._handle_click_banks(pos)
        elif self._level == 2:
            return self._handle_click_themes(pos)
        elif self._level == 3:
            return self._handle_click_channels(pos)

        return None

    def _handle_click_banks(self, pos: tuple[int, int]) -> str | None:
        for i, rect in enumerate(self._open_rects):
            if rect.collidepoint(pos):
                self._level = 2
                self._bank_index = i
                themes_mod.set_active_bank_index(i)
                self._build_layout()
                return None

        for i, rect in enumerate(self._row_del_rects):
            if rect.collidepoint(pos):
                self._delete_bank(i)
                return None

        for i, rect in enumerate(self._row_name_rects):
            if rect.collidepoint(pos):
                self._start_edit(i)
                return None

        if self._save_rect.collidepoint(pos):
            self._create_new_bank()
            return None

        return None

    def _handle_click_themes(self, pos: tuple[int, int]) -> str | None:
        for i, rect in enumerate(self._row_media_rects):
            if rect.collidepoint(pos):
                self._theme_index = i
                themes_mod.set_active_theme_index(i)
                self._pick_theme_image(i)
                return None

        for i, rect in enumerate(self._row_slider_rects):
            if rect.collidepoint(pos):
                self._theme_index = i
                themes_mod.set_active_theme_index(i)
                self._drag_slider = i
                self._update_theme_slider_value(i, pos[0] - rect.x)
                return None

        for i, rect in enumerate(self._row_styles_rects):
            if rect.collidepoint(pos):
                self._enter_channels(i)
                return None

        for i, rect in enumerate(self._row_del_rects):
            if rect.collidepoint(pos):
                self._delete_theme(i)
                return None

        for i, rect in enumerate(self._row_name_rects):
            if rect.collidepoint(pos):
                self._theme_index = i
                themes_mod.set_active_theme_index(i)
                self._start_edit(i)
                return None

        if self._save_rect.collidepoint(pos):
            self._save_as_new_theme()
            return None

        if self._update_rect.collidepoint(pos):
            self._update_active_theme()
            return None

        return None

    def _handle_click_channels(self, pos: tuple[int, int]) -> str | None:
        for i, rect in enumerate(self._channel_rects):
            if rect.collidepoint(pos):
                self._selected_channel = i + 1
                self._open_channel_note_settings(self._selected_channel)
                return None

        if self._save_rect.collidepoint(pos):
            self._update_active_theme()
            return None

        return None

    def _open_channel_note_settings(self, channel_num: int) -> None:
        from src.notes_settings import NotesSettingsScreen

        self._selected_channel = max(1, min(16, int(channel_num)))
        self._channel_notes_screen = NotesSettingsScreen(self.screen)
        self._channel_notes_screen._selected_channel = str(self._selected_channel)
        self._channel_notes_screen._show_theme_save_button = True
        self._channel_notes_screen._load()
        self._channel_notes_screen._build_layout()
        self._level = 4

    def _commit_edit(self) -> None:
        idx = self._editing_index
        if self._level == 1 and 0 <= idx < len(self._banks):
            name = self._editing_text.strip() or f"Bank {idx + 1}"
            self._banks[idx]["name"] = name
        elif self._level == 2:
            bank = self._banks[self._bank_index]
            themes = bank.get("themes", [])
            if 0 <= idx < len(themes):
                name = self._editing_text.strip() or f"Theme {idx + 1}"
                themes[idx]["name"] = name

        themes_mod.save_banks(self._banks)
        self._editing_index = -1
        self._editing_text = ""
        self._build_layout()

    def _start_edit(self, index: int) -> None:
        self._editing_index = index
        if self._level == 1:
            self._editing_text = self._banks[index].get("name", f"Bank {index + 1}")
        elif self._level == 2:
            themes = self._banks[self._bank_index].get("themes", [])
            self._editing_text = themes[index].get("name", f"Theme {index + 1}")

    # ─────────────────────────────────────────────────────────────
    # Private – operations
    # ─────────────────────────────────────────────────────────────

    def _get_current_display_media(self) -> tuple[str, int]:
        """Return current display media from config (with legacy fallbacks)."""
        import src.config as cfg

        data = cfg.load()
        display = data.get("display_style", {}) if isinstance(data.get("display_style", {}), dict) else {}

        bg_image = str(display.get("background_image", data.get("background_image", "")) or "")
        transition = int(display.get("background_transition_percent", data.get("background_transition_percent", 50)))
        transition = max(10, min(90, transition))
        return bg_image, transition

    def _create_new_bank(self) -> None:
        name = f"Bank {len(self._banks) + 1}"
        bank = themes_mod.create_bank(name)
        self._banks.append(bank)
        themes_mod.save_banks(self._banks)
        self._build_layout()

    def _delete_bank(self, index: int) -> None:
        if 0 <= index < len(self._banks):
            self._banks.pop(index)
            if self._bank_index >= len(self._banks):
                self._bank_index = max(0, len(self._banks) - 1)
            themes_mod.save_banks(self._banks)
            themes_mod.set_active_bank_index(self._bank_index)
            self._build_layout()



    def _save_as_new_theme(self) -> None:
        bank = self._banks[self._bank_index]
        themes = bank.setdefault("themes", [])
        name = f"Theme {len(themes) + 1}"
        bg_image, transition_percent = self._get_current_display_media()
        theme = themes_mod.snapshot_theme(name, bg_image if bg_image else None)
        theme["background_transition_percent"] = transition_percent
        themes.append(theme)
        self._theme_index = len(themes) - 1
        themes_mod.save_banks(self._banks)
        themes_mod.set_active_theme_index(self._theme_index)
        self._build_layout()

    def _update_active_theme(self) -> None:
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        if 0 <= self._theme_index < len(themes):
            # Capture current state and update the theme without wiping existing media.
            existing = themes[self._theme_index]
            bg_image, transition_percent = self._get_current_display_media()
            if not bg_image:
                bg_image = str(existing.get("background_image", "") or "")
            updated = themes_mod.snapshot_theme(existing.get("name", f"Theme {self._theme_index + 1}"), bg_image if bg_image else None)
            updated["background_transition_percent"] = transition_percent
            themes[self._theme_index] = updated
            themes_mod.save_banks(self._banks)



    def _delete_theme(self, index: int) -> None:
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        if 0 <= index < len(themes):
            themes.pop(index)
            if self._theme_index >= len(themes):
                self._theme_index = max(0, len(themes) - 1)
            themes_mod.save_banks(self._banks)
            themes_mod.set_active_theme_index(self._theme_index)
            self._build_layout()

    def _update_theme_slider_value(self, theme_index: int, x_offset: int) -> None:
        """Update theme transition percent based on slider position (10-90%)."""
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        if 0 <= theme_index < len(themes):
            theme = themes[theme_index]
            percent_value = int((x_offset / SLIDER_W) * 80 + 10)
            percent_value = max(10, min(90, percent_value))
            theme["background_transition_percent"] = percent_value
            themes_mod.save_banks(self._banks)

    def _pick_theme_image(self, theme_index: int) -> None:
        """Open image picker for a theme."""
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        if 0 <= theme_index < len(themes):
            image_path = _pick_image()
            if image_path:
                self._theme_index = theme_index
                themes_mod.set_active_theme_index(theme_index)
                themes[theme_index]["background_image"] = image_path
                themes_mod.save_banks(self._banks)

    def _get_theme_thumbnail(self, image_path: str) -> pygame.Surface | None:
        """Return a cached thumbnail surface for the given image path."""
        image_path = str(image_path or "").strip()
        if not image_path:
            return None
        if image_path in self._thumbnail_cache:
            return self._thumbnail_cache[image_path]

        thumbnail = self._load_theme_thumbnail(image_path)
        self._thumbnail_cache[image_path] = thumbnail
        return thumbnail

    def _load_theme_thumbnail(self, image_path: str) -> pygame.Surface | None:
        """Load and scale a saved theme background image for list preview."""
        path = pathlib.Path(image_path)
        if not path.exists():
            return None
        if not file_limits.is_allowed_media_file(path):
            return None

        try:
            image = self._load_thumbnail_surface(path)
            if image is None:
                return None

            fitted = pygame.transform.smoothscale(image, (THUMB_W - 2, THUMB_H - 2))
            return fitted.convert_alpha() if fitted.get_alpha() is not None else fitted.convert()
        except Exception:
            return None

    def _load_thumbnail_surface(self, path: pathlib.Path) -> pygame.Surface | None:
        """Load a preview surface, using the first frame for GIFs when possible."""
        if path.suffix.lower() == ".gif":
            try:
                from PIL import Image as _PILImage  # type: ignore

                pil = _PILImage.open(str(path))
                rgba = pil.convert("RGBA")
                return pygame.image.fromstring(rgba.tobytes(), rgba.size, "RGBA").convert_alpha()
            except Exception:
                pass

        image = pygame.image.load(str(path))
        return image.convert_alpha() if image.get_alpha() is not None else image.convert()

    def _enter_channels(self, theme_index: int) -> None:
        """Enter Level 3 channel grid for the given theme."""
        self._theme_index = theme_index
        self._level = 3
        self._channel_parent_level = 2
        self._selected_channel = 1
        self._build_layout()

    def _do_scroll(self, delta: int) -> None:
        num_rows = self._get_num_rows()
        total_h = num_rows * (ROW_H + ROW_GAP)
        max_scroll = max(0, total_h - self._scroll_area_h)
        self._scroll_offset = max(0, min(max_scroll, self._scroll_offset + delta))
        self._build_layout()

    # ─────────────────────────────────────────────────────────────
    # Private – layout
    # ─────────────────────────────────────────────────────────────

    def _get_num_rows(self) -> int:
        if self._level == 1:
            return len(self._banks)
        elif self._level == 2:
            if self._bank_index < len(self._banks):
                return len(self._banks[self._bank_index].get("themes", []))
        return 0

    def _get_title(self) -> str:
        if self._level == 1:
            return "Banks"
        elif self._level == 2:
            return "Themes"
        elif self._level == 3:
            return "Channels"
        elif self._level == 4:
            return "Note Settings"
        return "Manager"

    def _get_breadcrumb(self) -> str:
        parts = ["Banks"]
        if self._level >= 2 and self._bank_index < len(self._banks):
            parts.append(self._banks[self._bank_index]["name"])
        if self._level >= 3:
            bank = self._banks[self._bank_index]
            themes = bank.get("themes", [])
            if self._theme_index < len(themes):
                parts.append(themes[self._theme_index].get("name", f"Theme {self._theme_index + 1}"))
        if self._level >= 3:
            parts.append("Channels")
        if self._level >= 4:
            parts.append(f"Channel {self._selected_channel}")
        return " / ".join(parts)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        # Title
        title_text = self._get_title()
        title_surf = self._title_font.render(title_text, True, TITLE_COLOR)
        title_y = sr.height // 10
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        # Breadcrumb
        breadcrumb_text = self._get_breadcrumb()
        breadcrumb_surf = self._breadcrumb_font.render(breadcrumb_text, True, BREADCRUMB_COLOR)
        breadcrumb_y = title_y + title_surf.get_height() + 8
        self._breadcrumb_surf = breadcrumb_surf
        self._breadcrumb_pos = (cx - breadcrumb_surf.get_width() // 2, breadcrumb_y)

        # Buttons
        btn_y = breadcrumb_y + breadcrumb_surf.get_height() + 16
        self._save_rect = pygame.Rect(cx - TOP_BTN_W - 6, btn_y, TOP_BTN_W, TOP_BTN_H)
        self._update_rect = pygame.Rect(cx + 6, btn_y, TOP_BTN_W, TOP_BTN_H)

        # Rows
        self._rows_y = btn_y + TOP_BTN_H + 20
        self._scroll_area_h = max(60, sr.height - self._rows_y - BACK_H - 36)
        nav_y = sr.height - BACK_H - 18
        self._back_rect = pygame.Rect(20, nav_y, BACK_W, BACK_H)
        self._menu_rect = pygame.Rect(sr.width - MENU_W - 20, nav_y, MENU_W, BACK_H)

        self._build_rows(cx)

    def _build_rows(self, cx: int) -> None:
        self._open_rects = []
        self._row_name_rects = []
        self._row_thumb_rects = []
        self._row_media_rects = []
        self._row_load_rects = []
        self._row_del_rects = []
        self._row_rename_rects = []
        self._row_slider_rects = []
        self._row_styles_rects = []
        self._channel_rects = []

        if self._level == 1:
            self._build_bank_rows(cx)
        elif self._level == 2:
            self._build_theme_rows(cx)
        elif self._level == 3:
            self._build_channel_rows()

    def _build_channel_rows(self) -> None:
        sr = self.screen.get_rect()
        cols = 4
        gap = 12
        card_w = max(180, (sr.width - 80 - gap * (cols - 1)) // cols)
        card_h = 74
        start_x = (sr.width - (cols * card_w + (cols - 1) * gap)) // 2
        start_y = self._rows_y
        for idx in range(16):
            row = idx // cols
            col = idx % cols
            x = start_x + col * (card_w + gap)
            y = start_y + row * (card_h + gap)
            self._channel_rects.append(pygame.Rect(x, y, card_w, card_h))

    def _build_bank_rows(self, cx: int) -> None:
        rx = cx - (NAME_W + COL_GAP + 80 + COL_GAP + DEL_W) // 2
        for i, bank in enumerate(self._banks):
            y = self._rows_y + i * (ROW_H + ROW_GAP) - self._scroll_offset
            self._row_name_rects.append(pygame.Rect(rx, y, NAME_W, ROW_H))
            self._open_rects.append(pygame.Rect(rx + NAME_W + COL_GAP, y, 80, ROW_H))
            del_x = rx + NAME_W + COL_GAP + 80 + COL_GAP
            self._row_del_rects.append(pygame.Rect(del_x, y, DEL_W, ROW_H))



    def _build_theme_rows(self, cx: int) -> None:
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        # Layout for media, slider, channels button, delete
        rx = cx - (NAME_W + COL_GAP + THUMB_W + COL_GAP + 50 + COL_GAP + SLIDER_W + COL_GAP + STYLES_W + COL_GAP + DEL_W) // 2
        for i, theme in enumerate(themes):
            y = self._rows_y + i * (ROW_H + ROW_GAP) - self._scroll_offset
            self._row_name_rects.append(pygame.Rect(rx, y, NAME_W, ROW_H))
            thumb_x = rx + NAME_W + COL_GAP
            self._row_thumb_rects.append(pygame.Rect(thumb_x, y + (ROW_H - THUMB_H) // 2, THUMB_W, THUMB_H))
            media_x = thumb_x + THUMB_W + COL_GAP
            self._row_media_rects.append(pygame.Rect(media_x, y, 50, ROW_H))
            slider_x = media_x + 50 + COL_GAP
            self._row_slider_rects.append(pygame.Rect(slider_x, y + (ROW_H - SLIDER_H) // 2, SLIDER_W, SLIDER_H))
            styles_x = slider_x + SLIDER_W + COL_GAP
            self._row_styles_rects.append(pygame.Rect(styles_x, y, STYLES_W, ROW_H))
            del_x = styles_x + STYLES_W + COL_GAP
            self._row_del_rects.append(pygame.Rect(del_x, y, DEL_W, ROW_H))

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_menu = self._menu_rect.collidepoint(pos)
        self._hover_save = self._save_rect.collidepoint(pos)
        self._hover_update = self._update_rect.collidepoint(pos)
        self._hover_open = next((i for i, r in enumerate(self._open_rects) if r.collidepoint(pos)), -1)
        self._hover_load = next((i for i, r in enumerate(self._row_load_rects) if r.collidepoint(pos)), -1)
        self._hover_del = next((i for i, r in enumerate(self._row_del_rects) if r.collidepoint(pos)), -1)
        self._hover_name = next((i for i, r in enumerate(self._row_name_rects) if r.collidepoint(pos)), -1)
        self._hover_slider = next((i for i, r in enumerate(self._row_slider_rects) if r.collidepoint(pos)), -1)
        self._hover_media = next((i for i, r in enumerate(self._row_media_rects) if r.collidepoint(pos)), -1)
        self._hover_styles = next((i for i, r in enumerate(self._row_styles_rects) if r.collidepoint(pos)), -1)
        self._hover_channel = next((i for i, r in enumerate(self._channel_rects) if r.collidepoint(pos)), -1)

    def _draw_rows(self) -> None:
        if self._level == 1:
            self._draw_bank_rows()
        elif self._level == 2:
            self._draw_theme_rows()
        elif self._level == 3:
            self._draw_channel_rows()

    def _draw_bank_rows(self) -> None:
        for i, bank in enumerate(self._banks):
            if i >= len(self._row_name_rects):
                break
            rect = self._row_name_rects[i]
            is_active = i == self._bank_index
            is_cursor = i == self._cursor

            # Keyboard cursor: highlight box spanning name + open button with hint
            if is_cursor and i < len(self._open_rects):
                open_r = self._open_rects[i]
                cursor_box = pygame.Rect(
                    rect.x - 4, rect.y - 4,
                    open_r.right - rect.x + 8, rect.h + 8,
                )
                pygame.draw.rect(self.screen, EDITOR_BG, cursor_box)
                pygame.draw.rect(self.screen, ACTIVE_BORDER, cursor_box, 2, border_radius=4)
                hint = self._breadcrumb_font.render(
                    "Enter / → : Open   ·   ESC: Back", True, ACTIVE_BORDER
                )
                self.screen.blit(
                    hint,
                    (open_r.right - hint.get_width() - 2,
                     cursor_box.centery - hint.get_height() // 2),
                )

            # Name
            bg_color = ACTIVE_BORDER if is_active else EDITOR_BG
            pygame.draw.rect(self.screen, bg_color, rect)
            pygame.draw.rect(self.screen, EDITOR_BORDER, rect, 1)

            if self._editing_index == i:
                self._draw_text_input(rect, self._editing_text)
            else:
                text = bank.get("name", f"Bank {i + 1}")
                surf = self._row_font.render(text, True, TEXT_COLOR)
                self.screen.blit(surf, (rect.x + 8, rect.y + (rect.h - surf.get_height()) // 2))

            # Open button
            open_rect = self._open_rects[i]
            open_hover = i == self._hover_open
            open_color = BTN_HOVER_BG if open_hover else BTN_NORMAL_BG
            pygame.draw.rect(self.screen, open_color, open_rect)
            pygame.draw.rect(self.screen, BORDER_COLOR, open_rect, 1)
            open_surf = self._btn_font.render("→", True, BTN_TEXT_HOVER if open_hover else BTN_TEXT)
            self.screen.blit(open_surf, (open_rect.centerx - open_surf.get_width() // 2, open_rect.centery - open_surf.get_height() // 2))

            # Delete button
            del_rect = self._row_del_rects[i]
            del_hover = i == self._hover_del
            del_color = DEL_BG_HOVER if del_hover else DEL_BG
            pygame.draw.rect(self.screen, del_color, del_rect)
            pygame.draw.rect(self.screen, BORDER_COLOR, del_rect, 1)
            del_surf = self._btn_font.render("Del", True, DEL_TEXT_HOVER if del_hover else DEL_TEXT)
            self.screen.blit(del_surf, (del_rect.centerx - del_surf.get_width() // 2, del_rect.centery - del_surf.get_height() // 2))

        # New bank button
        self._draw_button(self._save_rect, "New Bank", self._hover_save, is_save=True)

    def _draw_theme_rows(self) -> None:
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        for i, theme in enumerate(themes):
            if i >= len(self._row_name_rects):
                break
            rect = self._row_name_rects[i]
            is_active = i == self._theme_index
            is_cursor = i == self._cursor

            # Keyboard cursor: highlight box spanning name through styles button
            if is_cursor and i < len(self._row_styles_rects):
                styles_r = self._row_styles_rects[i]
                cursor_box = pygame.Rect(
                    rect.x - 4, rect.y - 4,
                    styles_r.right - rect.x + 8, rect.h + 8,
                )
                pygame.draw.rect(self.screen, EDITOR_BG, cursor_box)
                pygame.draw.rect(self.screen, ACTIVE_BORDER, cursor_box, 2, border_radius=4)
                hint = self._breadcrumb_font.render(
                    "← → Softness   ·   Enter: Channels", True, ACTIVE_BORDER
                )
                self.screen.blit(
                    hint,
                    (styles_r.right - hint.get_width() - 2,
                     cursor_box.centery - hint.get_height() // 2),
                )

            # Name
            bg_color = ACTIVE_BORDER if is_active else EDITOR_BG
            pygame.draw.rect(self.screen, bg_color, rect)
            pygame.draw.rect(self.screen, EDITOR_BORDER, rect, 1)

            if self._editing_index == i:
                self._draw_text_input(rect, self._editing_text)
            else:
                text = theme.get("name", f"Theme {i + 1}")
                surf = self._row_font.render(text, True, TEXT_COLOR)
                self.screen.blit(surf, (rect.x + 8, rect.y + (rect.h - surf.get_height()) // 2))

            # Background thumbnail preview
            thumb_rect = self._row_thumb_rects[i]
            pygame.draw.rect(self.screen, EDITOR_BG, thumb_rect)
            pygame.draw.rect(self.screen, BORDER_COLOR, thumb_rect, 1)
            image_path = str(theme.get("background_image", "") or "")
            thumbnail = self._get_theme_thumbnail(image_path)
            if thumbnail is not None:
                self.screen.blit(thumbnail, (thumb_rect.x + 1, thumb_rect.y + 1))
            elif image_path:
                missing_surf = self._breadcrumb_font.render("N/A", True, DEL_TEXT)
                self.screen.blit(
                    missing_surf,
                    (
                        thumb_rect.centerx - missing_surf.get_width() // 2,
                        thumb_rect.centery - missing_surf.get_height() // 2,
                    ),
                )

            # Media picker button
            media_rect = self._row_media_rects[i]
            media_hover = i == self._hover_media
            media_bg = BTN_HOVER_BG if media_hover else BTN_NORMAL_BG
            pygame.draw.rect(self.screen, media_bg, media_rect)
            pygame.draw.rect(self.screen, BORDER_COLOR, media_rect, 1)
            media_text_color = BTN_TEXT_HOVER if media_hover else BTN_TEXT
            media_surf = self._btn_font.render("+", True, media_text_color)
            self.screen.blit(media_surf, (media_rect.centerx - media_surf.get_width() // 2, media_rect.centery - media_surf.get_height() // 2))

            # Transition softness slider
            slider_rect = self._row_slider_rects[i]
            transition_percent = theme.get("background_transition_percent", 50)
            self._draw_slider(slider_rect, transition_percent, "Transition", i == self._hover_slider, is_cursor=is_cursor)

            # Channels button
            if i < len(self._row_styles_rects):
                styles_rect = self._row_styles_rects[i]
                styles_hover = i == self._hover_styles
                styles_bg = BTN_HOVER_BG if styles_hover else BTN_NORMAL_BG
                pygame.draw.rect(self.screen, styles_bg, styles_rect)
                pygame.draw.rect(self.screen, BORDER_COLOR, styles_rect, 1)
                styles_surf = self._btn_font.render("Channels →", True, BTN_TEXT_HOVER if styles_hover else BTN_TEXT)
                self.screen.blit(styles_surf, (styles_rect.centerx - styles_surf.get_width() // 2, styles_rect.centery - styles_surf.get_height() // 2))

            # Delete button
            del_rect = self._row_del_rects[i]
            del_hover = i == self._hover_del
            del_color = DEL_BG_HOVER if del_hover else DEL_BG
            pygame.draw.rect(self.screen, del_color, del_rect)
            pygame.draw.rect(self.screen, BORDER_COLOR, del_rect, 1)
            del_surf = self._btn_font.render("Del", True, DEL_TEXT_HOVER if del_hover else DEL_TEXT)
            self.screen.blit(del_surf, (del_rect.centerx - del_surf.get_width() // 2, del_rect.centery - del_surf.get_height() // 2))

        # Save and update buttons
        self._draw_button(self._save_rect, "New Theme", self._hover_save, is_save=True)
        self._draw_button(self._update_rect, "Update Theme", self._hover_update, is_update=True)

    def _draw_channel_rows(self) -> None:
        bank = self._banks[self._bank_index]
        themes = bank.get("themes", [])
        theme = themes[self._theme_index] if 0 <= self._theme_index < len(themes) else None
        channels = theme.get("channels", {}) if isinstance(theme, dict) else {}

        for i, rect in enumerate(self._channel_rects):
            ch_num = i + 1
            ch_key = str(ch_num)
            ch_data = channels.get(ch_key, {})
            is_selected = ch_num == self._selected_channel
            is_hover = i == self._hover_channel

            card_bg = EDITOR_ACTIVE_BG if is_selected else (BTN_HOVER_BG if is_hover else EDITOR_BG)
            pygame.draw.rect(self.screen, card_bg, rect)
            pygame.draw.rect(self.screen, ACTIVE_BORDER if is_selected else BORDER_COLOR, rect, 2 if is_selected else 1)

            title = self._row_font.render(f"Ch {ch_num}", True, TITLE_COLOR)
            self.screen.blit(title, (rect.x + 10, rect.y + 8))

            r = int(ch_data.get("note_color_r", ch_data.get("color_r", 80)))
            g = int(ch_data.get("note_color_g", ch_data.get("color_g", 180)))
            b = int(ch_data.get("note_color_b", ch_data.get("color_b", 255)))
            swatch = pygame.Rect(rect.right - 40, rect.y + 10, 24, 24)
            pygame.draw.rect(self.screen, (r, g, b), swatch)
            pygame.draw.rect(self.screen, BORDER_COLOR, swatch, 1)

            info = self._breadcrumb_font.render(
                f"W:{int(ch_data.get('note_width_px', ch_data.get('width_px', 18)))}  S:{int(ch_data.get('note_speed_px_per_sec', ch_data.get('speed_px_per_sec', 430)))}",
                True,
                TEXT_COLOR,
            )
            self.screen.blit(info, (rect.x + 10, rect.y + rect.h - info.get_height() - 8))

        # Detail panel for selected channel
        selected = channels.get(str(self._selected_channel), {})
        sr = self.screen.get_rect()
        panel_y = self._rows_y + 4 * (74 + 12) + 8
        panel_h = max(90, sr.height - panel_y - BACK_H - 34)
        panel = pygame.Rect(40, panel_y, sr.width - 80, panel_h)
        pygame.draw.rect(self.screen, EDITOR_BG, panel)
        pygame.draw.rect(self.screen, BORDER_COLOR, panel, 1)

        head = self._btn_font.render(f"Channel {self._selected_channel} Info", True, TITLE_COLOR)
        self.screen.blit(head, (panel.x + 12, panel.y + 8))

        keys = [
            ("speed", selected.get("note_speed_px_per_sec", selected.get("speed_px_per_sec", "-"))),
            ("width", selected.get("note_width_px", selected.get("width_px", "-"))),
            ("round", selected.get("note_roundness_px", selected.get("edge_roundness_px", "-"))),
            ("decay", selected.get("note_decay_speed", selected.get("decay_speed", "-"))),
            ("inner", selected.get("note_inner_blend_percent", selected.get("inner_blend_percent", "-"))),
            ("glow", selected.get("note_glow_strength_percent", selected.get("glow_strength_percent", "-"))),
            ("highlight", selected.get("note_highlight_strength_percent", selected.get("highlight_strength_percent", "-"))),
            ("sparks", selected.get("note_spark_amount_percent", selected.get("spark_amount_percent", "-"))),
        ]
        line_y = panel.y + 48
        for k, v in keys:
            txt = self._breadcrumb_font.render(f"{k}: {v}", True, TEXT_COLOR)
            self.screen.blit(txt, (panel.x + 14, line_y))
            line_y += txt.get_height() + 4

        self._draw_button(self._save_rect, "Save Theme", self._hover_save, is_save=True)

    def _draw_button(self, rect: pygame.Rect, text: str, is_hover: bool, is_save: bool = False, is_update: bool = False) -> None:
        if is_save:
            bg_color = SAVE_BG_HOVER if is_hover else SAVE_BG
            text_color = SAVE_TEXT_HOVER if is_hover else SAVE_TEXT
        elif is_update:
            bg_color = UPDATE_BG_HOVER if is_hover else UPDATE_BG
            text_color = UPDATE_TEXT_HOVER if is_hover else UPDATE_TEXT
        else:
            bg_color = BTN_HOVER_BG if is_hover else BTN_NORMAL_BG
            text_color = BTN_TEXT_HOVER if is_hover else BTN_TEXT

        pygame.draw.rect(self.screen, bg_color, rect)
        pygame.draw.rect(self.screen, BORDER_COLOR, rect, 1)
        surf = self._btn_font.render(text, True, text_color)
        self.screen.blit(surf, (rect.centerx - surf.get_width() // 2, rect.centery - surf.get_height() // 2))

    def _draw_back_button(self) -> None:
        bg_color = BTN_HOVER_BG if self._hover_back else BTN_NORMAL_BG
        text_color = BTN_TEXT_HOVER if self._hover_back else BTN_TEXT
        pygame.draw.rect(self.screen, bg_color, self._back_rect)
        pygame.draw.rect(self.screen, BORDER_COLOR, self._back_rect, 1)
        label = "Back" if self._level <= 1 else "Up One"
        surf = self._btn_font.render(label, True, text_color)
        self.screen.blit(surf, (self._back_rect.centerx - surf.get_width() // 2, self._back_rect.centery - surf.get_height() // 2))

        menu_bg = BTN_HOVER_BG if self._hover_menu else BTN_NORMAL_BG
        menu_text = BTN_TEXT_HOVER if self._hover_menu else BTN_TEXT
        pygame.draw.rect(self.screen, menu_bg, self._menu_rect)
        pygame.draw.rect(self.screen, BORDER_COLOR, self._menu_rect, 1)
        menu_surf = self._btn_font.render("Main Menu", True, menu_text)
        self.screen.blit(menu_surf, (self._menu_rect.centerx - menu_surf.get_width() // 2, self._menu_rect.centery - menu_surf.get_height() // 2))

    def _draw_text_input(self, rect: pygame.Rect, text: str) -> None:
        pygame.draw.rect(self.screen, EDITOR_ACTIVE_BG, rect)
        pygame.draw.rect(self.screen, EDITOR_ACTIVE_BORDER, rect, 2)
        surf = self._row_font.render(text + "|", True, TEXT_COLOR)
        self.screen.blit(surf, (rect.x + 8, rect.y + (rect.h - surf.get_height()) // 2))

    def _draw_slider(self, rect: pygame.Rect, value: int, label: str, is_hover: bool, is_cursor: bool = False) -> None:
        """Draw a horizontal slider for transition softness (10-90%)."""
        # When cursor is on this row, expand the slider into a taller fill bar
        if is_cursor:
            draw_r = pygame.Rect(rect.x - 2, rect.y - 5, rect.w + 4, rect.h + 10)
        else:
            draw_r = rect

        pygame.draw.rect(self.screen, EDITOR_BG, draw_r)

        # Fill bar proportional to value
        normalized = max(0.0, min(1.0, (value - 10) / 80.0))
        fill_w = int(normalized * draw_r.w)
        if fill_w > 0:
            fill_color = (0, 140, 190) if is_cursor else (0, 85, 130)
            pygame.draw.rect(self.screen, fill_color,
                             pygame.Rect(draw_r.x, draw_r.y, fill_w, draw_r.h))

        border_color = ACTIVE_BORDER if is_cursor else (BORDER_COLOR if is_hover else (60, 60, 80))
        pygame.draw.rect(self.screen, border_color, draw_r, 1)

        if is_cursor:
            # Show numeric value centred in the bar
            val_surf = self._breadcrumb_font.render(f"{value}%", True, (220, 245, 255))
            self.screen.blit(val_surf, val_surf.get_rect(center=draw_r.center))
        else:
            # Original knob dot
            knob_x = int(rect.x + normalized * rect.w)
            pygame.draw.circle(self.screen,
                               (100, 200, 255) if is_hover else (80, 160, 200),
                               (knob_x, rect.centery), 5)
