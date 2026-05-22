"""Display settings screen for projector scaling and background image."""

from __future__ import annotations

import pathlib
import pygame
from src import config as cfg


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
TEAL = (0, 180, 180)
GIF_BADGE_COLOR = (0, 150, 150)
REMOVE_BTN_COLOR = (120, 40, 40)
REMOVE_BTN_HOVER = (180, 60, 60)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 24
VALUE_FONT_SIZE = 22
ITEM_LABEL_SIZE = 18
ITEM_VALUE_SIZE = 16
BTN_FONT_SIZE = 26

ROW_H = 64
ROW_GAP = 12
BACK_W = 160
BACK_H = 52
SLIDER_H = 8
KNOB_R = 9
ITEM_ROW_H = 90
ITEM_ROW_GAP = 6

PANEL_MARGIN_X = 26
PANEL_GAP = 16

_ITEM_DEFAULTS: dict = {"slide_sec": 5, "transition_pct": 35, "gif_speed_pct": 100}
_ITEM_RANGES: dict = {
    "slide_sec":      (1, 60, 1,  "s"),
    "transition_pct": (10, 90, 5, "%"),
    "gif_speed_pct":  (10, 200, 5, "%"),
}
_ITEM_LABELS: dict = {
    "slide_sec":      "Slide",
    "transition_pct": "Fade",
    "gif_speed_pct":  "Speed",
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _migrate_items(data: dict) -> list[dict]:
    """Convert old path-list + global scalars to per-item dicts."""
    paths = list(data.get("background_slideshow_paths", []))
    single = str(data.get("background_image", ""))
    slide_sec     = int(data.get("background_slide_duration_sec", 5))
    trans_pct     = int(data.get("background_transition_percent", 35))
    gif_speed_pct = int(data.get("gif_speed_percent", 100))
    all_paths = paths if paths else ([single] if single else [])
    return [
        {"path": p, "slide_sec": slide_sec, "transition_pct": trans_pct, "gif_speed_pct": gif_speed_pct}
        for p in all_paths
    ]


def _paths_to_items(paths: list[str]) -> list[dict]:
    return [{**_ITEM_DEFAULTS, "path": p} for p in paths]


def _pick_images() -> list[str]:
    """Open a file picker; returns a list of selected paths (may be 1 or many)."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        paths = filedialog.askopenfilenames(
            parent=root,
            title="Select background image(s) / GIF",
            filetypes=[
                ("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return list(paths) if paths else []
    except Exception:
        return []


def _is_gif(path: str) -> bool:
    return pathlib.Path(path).suffix.lower() == ".gif"


class DisplaySettingsScreen:
    """Settings UI for display scale, background images, and per-item slideshow controls."""

    FIELDS = [
        ("width_scale_percent", "Highway Width Scale", 60, 80, 1, "%"),
        ("background_alpha",    "Background Alpha",    0, 255, 5, ""),
    ]

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font      = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font      = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font      = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font        = pygame.font.SysFont("Arial", BTN_FONT_SIZE)
        self._item_label_font = pygame.font.SysFont("Arial", ITEM_LABEL_SIZE)
        self._item_value_font = pygame.font.SysFont("Arial", ITEM_VALUE_SIZE)

        self._values: dict = {}
        self._items: list[dict] = []

        self._hover_back       = False
        self._hover_slider     = -1
        self._drag_slider      = -1
        self._hover_pick       = False
        self._hover_clear      = False
        self._hover_add        = False
        self._hover_fullscreen = False

        self._item_scroll: int = 0
        self._item_drag: tuple[int, str] | None = None   # (item_idx, field_key)
        self._item_hover_remove: int = -1                # item index under × button
        self._item_slider_rects: list[dict[str, pygame.Rect]] = []

        self._title_pos  = (0, 0)
        self._title_surf: pygame.Surface | None = None
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect  = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._row_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect] = []
        self._pick_rect      = pygame.Rect(0, 0, 0, 0)
        self._clear_rect     = pygame.Rect(0, 0, 0, 0)
        self._add_rect       = pygame.Rect(0, 0, 0, 0)
        self._fullscreen_rect = pygame.Rect(0, 0, 0, 0)

        self._load()
        self._build_layout()

    # ── Public interface ──────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        mouse_pos = pygame.mouse.get_pos()

        if event.type == pygame.MOUSEMOTION:
            if self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            if self._item_drag is not None:
                idx, field = self._item_drag
                self._set_item_slider(idx, field, event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        # Mouse wheel — scroll item list
        if event.type == pygame.MOUSEWHEEL:
            if self._right_panel.collidepoint(mouse_pos):
                total_h = len(self._items) * (ITEM_ROW_H + ITEM_ROW_GAP)
                max_scroll = max(0, total_h - self._right_panel.height + 16)
                self._item_scroll = int(_clamp(self._item_scroll - event.y * 30, 0, max_scroll))
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._pick_rect.collidepoint(event.pos):
                selected = _pick_images()
                if selected:
                    self._items = _paths_to_items(selected)
                    self._item_scroll = 0
                    self._save()
                return None

            if self._add_rect.collidepoint(event.pos):
                extra = _pick_images()
                if extra:
                    self._items.extend(_paths_to_items(extra))
                    self._save()
                return None

            if self._clear_rect.collidepoint(event.pos):
                self._items = []
                self._item_scroll = 0
                self._save()
                return None

            if self._fullscreen_rect.collidepoint(event.pos):
                return "toggle_fullscreen"

            # Global sliders
            for i, rect in enumerate(self._slider_rects):
                if rect.inflate(0, 18).collidepoint(event.pos):
                    self._drag_slider = i
                    self._set_slider_from_x(i, event.pos[0])
                    return None

            # Item list interactions (right panel)
            if self._right_panel.collidepoint(event.pos):
                hit = self._item_hit_test(event.pos)
                if hit == "remove":
                    # Handled on mouseup to avoid accidental clicks — actually remove immediately
                    pass
                elif hit is not None:
                    idx, field = hit
                    self._item_drag = (idx, field)
                    self._set_item_slider(idx, field, event.pos[0])
                return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1

            if self._item_drag is not None:
                self._item_drag = None
                return None

            # Remove button release
            if self._right_panel.collidepoint(event.pos):
                hit = self._item_hit_test(event.pos)
                if hit == "remove":
                    idx = self._item_hover_remove
                    if 0 <= idx < len(self._items):
                        self._items.pop(idx)
                        total_h = len(self._items) * (ITEM_ROW_H + ITEM_ROW_GAP)
                        max_scroll = max(0, total_h - self._right_panel.height + 16)
                        self._item_scroll = int(_clamp(self._item_scroll, 0, max_scroll))
                        self._save()

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        if self._title_surf is not None:
            self.screen.blit(self._title_surf, self._title_pos)
        self._draw_rows()
        self._draw_item_list()
        self._draw_back()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Display Settings", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)
        self._title_surf = title_surf

        content_top    = title_y + title_surf.get_height() + 20
        content_bottom = sr.height - BACK_H - 34
        content_h      = max(200, content_bottom - content_top)
        content_w      = sr.width - 2 * PANEL_MARGIN_X
        half_w         = (content_w - PANEL_GAP) // 2

        self._left_panel  = pygame.Rect(PANEL_MARGIN_X, content_top, half_w, content_h)
        self._right_panel = pygame.Rect(self._left_panel.right + PANEL_GAP, content_top, half_w, content_h)

        self._row_rects   = []
        self._slider_rects = []
        y     = self._left_panel.top + 12
        row_w = self._left_panel.width - 24
        _btn_reserve    = 4 * 30 + 3 * 6 + 16
        available       = self._left_panel.height - 24 - _btn_reserve
        row_h = max(40, min(ROW_H, (available - ROW_GAP * (len(self.FIELDS) - 1)) // max(1, len(self.FIELDS))))
        for _ in self.FIELDS:
            row    = pygame.Rect(self._left_panel.left + 12, y, row_w, row_h)
            slider = pygame.Rect(row.left + 6, row.bottom - 18, row.width - 12, SLIDER_H)
            self._row_rects.append(row)
            self._slider_rects.append(slider)
            y += row_h + ROW_GAP

        btn_area_top    = y + 8
        btn_area_bottom = self._left_panel.bottom - 8
        btn_h   = min(44, max(28, (btn_area_bottom - btn_area_top - 3 * 8) // 4))
        btn_gap = max(4, (btn_area_bottom - btn_area_top - 4 * btn_h) // 3)

        def _btn(n: int) -> pygame.Rect:
            by = btn_area_top + n * (btn_h + btn_gap)
            return pygame.Rect(self._left_panel.left + 12, by, row_w, btn_h)

        self._pick_rect       = _btn(0)
        self._add_rect        = _btn(1)
        self._clear_rect      = _btn(2)
        self._fullscreen_rect = _btn(3)

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    # ── Hit testing ───────────────────────────────────────────────────────────

    def _item_hit_test(self, pos: tuple[int, int]) -> tuple[int, str] | str | None:
        """Return (item_idx, field_key), 'remove', or None."""
        for i, sliders in enumerate(self._item_slider_rects):
            for field, rect in sliders.items():
                if field == "_remove":
                    if rect.collidepoint(pos):
                        self._item_hover_remove = i
                        return "remove"
                else:
                    if rect.inflate(0, 16).collidepoint(pos):
                        return (i, field)
        return None

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back       = self._back_rect.collidepoint(pos)
        self._hover_pick       = self._pick_rect.collidepoint(pos)
        self._hover_add        = self._add_rect.collidepoint(pos)
        self._hover_clear      = self._clear_rect.collidepoint(pos)
        self._hover_fullscreen = self._fullscreen_rect.collidepoint(pos)
        self._hover_slider     = -1
        for i, rect in enumerate(self._slider_rects):
            if rect.inflate(0, 18).collidepoint(pos):
                self._hover_slider = i
                break
        self._item_hover_remove = -1
        if self._right_panel.collidepoint(pos):
            hit = self._item_hit_test(pos)
            if hit == "remove":
                pass  # already set in _item_hit_test

    # ── Slider helpers ────────────────────────────────────────────────────────

    def _set_slider_from_x(self, index: int, mouse_x: int) -> None:
        rect = self._slider_rects[index]
        key, _label, min_v, max_v, step, _suffix = self.FIELDS[index]
        if rect.width <= 1:
            return
        ratio   = _clamp((mouse_x - rect.left) / float(rect.width), 0.0, 1.0)
        raw     = min_v + ratio * (max_v - min_v)
        stepped = int(round(raw / step) * step)
        new_v   = int(_clamp(stepped, min_v, max_v))
        if new_v == self._values[key]:
            return
        self._values[key] = new_v
        self._save()

    def _set_item_slider(self, item_idx: int, field: str, mouse_x: int) -> None:
        if item_idx >= len(self._items):
            return
        sliders = self._item_slider_rects[item_idx] if item_idx < len(self._item_slider_rects) else {}
        rect = sliders.get(field)
        if rect is None or rect.width <= 1:
            return
        min_v, max_v, step, _suffix = _ITEM_RANGES[field]
        ratio   = _clamp((mouse_x - rect.left) / float(rect.width), 0.0, 1.0)
        raw     = min_v + ratio * (max_v - min_v)
        stepped = int(round(raw / step) * step)
        new_v   = int(_clamp(stepped, min_v, max_v))
        if self._items[item_idx].get(field) == new_v:
            return
        self._items[item_idx][field] = new_v
        self._save()

    def _value_ratio(self, index: int) -> float:
        key, _label, min_v, max_v, _step, _suffix = self.FIELDS[index]
        span = max(1, max_v - min_v)
        return (int(self._values[key]) - min_v) / float(span)

    def _item_field_ratio(self, item: dict, field: str) -> float:
        min_v, max_v, _step, _suffix = _ITEM_RANGES[field]
        val = int(item.get(field, _ITEM_DEFAULTS[field]))
        return _clamp((val - min_v) / float(max(1, max_v - min_v)), 0.0, 1.0)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        conf = cfg.load()
        data = conf.get("display_style", {})
        keyboard = conf.get("keyboard_style", {})

        width_scale = int(_clamp(int(data.get("width_scale_percent", 66)), 60, 80))
        self._values = {
            "width_scale_percent": width_scale,
            "background_alpha": int(data.get("background_alpha", 120)),
            "background_image": str(data.get("background_image", "")),
            "fullscreen": bool(data.get("fullscreen", True)),
        }

        items = list(data.get("background_slideshow_items", []))
        if not items:
            items = _migrate_items(data)
        self._items = items

        _ = keyboard  # reserved for future preview use

    def _save(self) -> None:
        data = cfg.load()
        data["display_style"] = {
            "width_scale_percent": int(self._values["width_scale_percent"]),
            "background_alpha":    int(self._values["background_alpha"]),
            "background_image":    str(self._values.get("background_image", "")),
            "background_slideshow_items": self._items,
            "fullscreen": bool(self._values.get("fullscreen", True)),
        }
        cfg.save(data)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_rows(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._left_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._left_panel, width=1, border_radius=8)

        for i, (key, label, _min_v, _max_v, _step, suffix) in enumerate(self.FIELDS):
            row    = self._row_rects[i]
            slider = self._slider_rects[i]

            pygame.draw.rect(self.screen, BG_COLOR, row, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row, width=1, border_radius=6)

            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (row.left + 10, row.top + 7))

            val_text  = f"{self._values[key]}{suffix}"
            value_surf = self._value_font.render(val_text, True, MUTED_TEXT_COLOR)
            self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

            track_color = BUTTON_HOVER_BG if i in (self._hover_slider, self._drag_slider) else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, track_color, slider, border_radius=4)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

            fill_ratio = self._value_ratio(i)
            fill_w     = max(1, int(slider.width * fill_ratio))
            pygame.draw.rect(self.screen, TEAL, pygame.Rect(slider.left, slider.top, fill_w, slider.height), border_radius=4)

            knob_x = int(slider.left + fill_ratio * slider.width)
            pygame.draw.circle(self.screen, (210, 210, 210), (knob_x, slider.centery), KNOB_R)
            pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, (knob_x, slider.centery), KNOB_R, width=1)

        self._draw_action_button(self._pick_rect, self._hover_pick, "SELECT BACKGROUND(S) / GIF")
        self._draw_action_button(self._add_rect,  self._hover_add,  "ADD MORE TO SLIDESHOW")
        self._draw_action_button(self._clear_rect, self._hover_clear, "CLEAR BACKGROUND")

        fs        = bool(self._values.get("fullscreen", True))
        fs_label  = "WINDOWED MODE" if fs else "FULLSCREEN MODE"
        fs_active = (0, 80, 80) if not self._hover_fullscreen else (0, 110, 110)
        fs_inact  = BUTTON_HOVER_BG if self._hover_fullscreen else BUTTON_NORMAL_BG
        fs_bg     = fs_active if not fs else fs_inact
        pygame.draw.rect(self.screen, fs_bg, self._fullscreen_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._fullscreen_rect, width=1, border_radius=8)
        fs_surf = self._value_font.render(fs_label, True, BUTTON_HOVER_TEXT_COLOR if self._hover_fullscreen else BUTTON_TEXT_COLOR)
        self.screen.blit(fs_surf, fs_surf.get_rect(center=self._fullscreen_rect.center))

    def _draw_action_button(self, rect: pygame.Rect, hover: bool, text: str) -> None:
        bg = BUTTON_HOVER_BG if hover else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if hover else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)
        surf = self._value_font.render(text, True, fg)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_item_list(self) -> None:
        rp = self._right_panel
        pygame.draw.rect(self.screen, PANEL_BG, rp, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rp, width=1, border_radius=8)

        # Heading
        head = self._label_font.render(
            f"Slideshow  ({len(self._items)} item{'s' if len(self._items) != 1 else ''})",
            True, TEXT_COLOR,
        )
        head_y = rp.top + 10
        self.screen.blit(head, (rp.left + 14, head_y))

        if not self._items:
            hint = self._value_font.render(
                "No media loaded — use SELECT BACKGROUND(S) / GIF",
                True, MUTED_TEXT_COLOR,
            )
            self.screen.blit(hint, hint.get_rect(center=(rp.centerx, rp.centery)))
            self._item_slider_rects = []
            return

        list_top  = head_y + head.get_height() + 8
        list_rect = pygame.Rect(rp.left + 8, list_top, rp.width - 16, rp.bottom - list_top - 8)

        # Clip to list viewport
        prev_clip = self.screen.get_clip()
        self.screen.set_clip(list_rect)

        self._item_slider_rects = []
        item_x = list_rect.left
        item_w = list_rect.width
        y0     = list_rect.top - self._item_scroll

        REMOVE_SZ = 22
        SLIDER_MINI_H = 6
        KNOB_MINI_R   = 7
        PAD = 8

        for idx, item in enumerate(self._items):
            row_top = y0 + idx * (ITEM_ROW_H + ITEM_ROW_GAP)
            row_rect = pygame.Rect(item_x, row_top, item_w, ITEM_ROW_H)

            # Skip fully off-screen rows
            if row_rect.bottom < list_rect.top or row_rect.top > list_rect.bottom:
                self._item_slider_rects.append({})
                continue

            # Row background
            pygame.draw.rect(self.screen, BG_COLOR, row_rect, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row_rect, width=1, border_radius=6)

            # ── Top row: filename, GIF badge, × button ────────────────────
            name      = pathlib.Path(item["path"]).name
            is_gif    = _is_gif(item["path"])
            name_x    = row_rect.left + PAD
            name_y    = row_rect.top + 7
            remove_rect = pygame.Rect(
                row_rect.right - REMOVE_SZ - PAD,
                row_rect.top + 5,
                REMOVE_SZ, REMOVE_SZ,
            )

            # Truncate filename if too long
            max_name_w = remove_rect.left - name_x - 4
            name_surf  = self._item_label_font.render(name, True, TEXT_COLOR)
            while name_surf.get_width() > max_name_w and len(name) > 6:
                name   = name[:-4] + "…"
                name_surf = self._item_label_font.render(name, True, TEXT_COLOR)
            self.screen.blit(name_surf, (name_x, name_y))

            if is_gif:
                badge_surf = self._item_value_font.render("GIF", True, GIF_BADGE_COLOR)
                self.screen.blit(badge_surf, (name_x + name_surf.get_width() + 6, name_y + 2))

            # × remove button
            is_hov_remove = self._item_hover_remove == idx
            rb_color = REMOVE_BTN_HOVER if is_hov_remove else REMOVE_BTN_COLOR
            pygame.draw.rect(self.screen, rb_color, remove_rect, border_radius=4)
            x_surf = self._item_value_font.render("×", True, (230, 230, 230))
            self.screen.blit(x_surf, x_surf.get_rect(center=remove_rect.center))

            # ── Bottom row: per-item sliders ──────────────────────────────
            fields = ["slide_sec", "transition_pct"]
            if is_gif:
                fields.append("gif_speed_pct")

            slider_area_top  = row_rect.top + 42
            slider_area_h    = row_rect.bottom - slider_area_top - PAD
            n_fields         = len(fields)
            slot_w           = (item_w - PAD * 2) // n_fields
            rects_for_item: dict[str, pygame.Rect] = {"_remove": remove_rect}

            for fi, field in enumerate(fields):
                sx   = item_x + PAD + fi * slot_w
                lbl  = _ITEM_LABELS[field]
                min_v, max_v, _step, suffix = _ITEM_RANGES[field]
                val  = int(item.get(field, _ITEM_DEFAULTS[field]))

                # Label
                lbl_surf = self._item_value_font.render(lbl, True, MUTED_TEXT_COLOR)
                self.screen.blit(lbl_surf, (sx, slider_area_top))

                # Value
                val_text  = f"{val}{suffix}"
                val_surf  = self._item_value_font.render(val_text, True, TEXT_COLOR)
                self.screen.blit(val_surf, (sx + lbl_surf.get_width() + 4, slider_area_top))

                # Track
                track_y  = slider_area_top + lbl_surf.get_height() + 4
                track_w  = slot_w - PAD
                track_rect = pygame.Rect(sx, track_y, track_w, SLIDER_MINI_H)

                is_dragging = self._item_drag is not None and self._item_drag == (idx, field)
                track_bg = BUTTON_HOVER_BG if is_dragging else BUTTON_NORMAL_BG
                pygame.draw.rect(self.screen, track_bg, track_rect, border_radius=3)
                pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, track_rect, width=1, border_radius=3)

                ratio  = _clamp((val - min_v) / float(max(1, max_v - min_v)), 0.0, 1.0)
                fill_w = max(1, int(track_rect.width * ratio))
                pygame.draw.rect(self.screen, TEAL,
                                 pygame.Rect(track_rect.left, track_rect.top, fill_w, SLIDER_MINI_H),
                                 border_radius=3)

                knob_x = int(track_rect.left + ratio * track_rect.width)
                pygame.draw.circle(self.screen, (200, 200, 200), (knob_x, track_rect.centery), KNOB_MINI_R)
                pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, (knob_x, track_rect.centery), KNOB_MINI_R, width=1)

                rects_for_item[field] = track_rect

            self._item_slider_rects.append(rects_for_item)

        self.screen.set_clip(prev_clip)

        # Scroll indicator (thin bar on right edge)
        total_h = len(self._items) * (ITEM_ROW_H + ITEM_ROW_GAP)
        if total_h > list_rect.height:
            bar_h  = max(20, int(list_rect.height * list_rect.height / total_h))
            bar_y  = list_rect.top + int(self._item_scroll / total_h * list_rect.height)
            bar_rect = pygame.Rect(rp.right - 6, bar_y, 4, bar_h)
            pygame.draw.rect(self.screen, (80, 80, 110), bar_rect, border_radius=2)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
