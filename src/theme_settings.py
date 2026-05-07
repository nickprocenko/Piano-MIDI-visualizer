"""Theme manager for the active performance."""

from __future__ import annotations

import pathlib
from typing import Optional

import pygame

import src.performance_store as perf_store

BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BTN_NORMAL_BG = (35, 35, 45)
BTN_HOVER_BG = (60, 60, 80)
BTN_TEXT = (210, 210, 210)
BTN_TEXT_HOVER = (255, 255, 255)
BORDER_COLOR = (80, 80, 110)
SAVE_BG = (28, 55, 28)
SAVE_BG_HOVER = (45, 85, 45)
SAVE_TEXT = (110, 215, 110)
SAVE_TEXT_HOVER = (170, 255, 170)
UPDATE_BG = (35, 45, 65)
UPDATE_BG_HOVER = (55, 70, 105)
UPDATE_TEXT = (120, 165, 230)
UPDATE_TEXT_HOVER = (180, 210, 255)
EDITOR_BG = (24, 24, 34)
EDITOR_ACTIVE_BG = (38, 38, 58)
EDITOR_BORDER = (68, 68, 98)
EDITOR_ACTIVE_BORDER = (0, 185, 210)
ACTIVE_BORDER = (0, 200, 200)
DEL_BG = (58, 25, 25)
DEL_BG_HOVER = (95, 38, 38)
DEL_TEXT = (220, 140, 140)
DEL_TEXT_HOVER = (255, 180, 180)
PANEL_BG = (22, 22, 30)
TEXT_COLOR = (210, 210, 210)
MUTED_TEXT_COLOR = (150, 150, 150)
SLIDER_FILL = (0, 180, 180)

TITLE_FONT_SIZE = 38
BTN_FONT_SIZE = 24
ROW_FONT_SIZE = 20
BACK_W, BACK_H = 160, 50
TOP_BTN_W, TOP_BTN_H = 280, 48
NAME_W = 320
NOTES_W = 95
DEL_W = 80
ROW_H = 52
ROW_GAP = 8
COL_GAP = 8
ROW_FULL_W = NAME_W + COL_GAP + NOTES_W + COL_GAP + DEL_W
SLIDER_H = 8
SLIDER_KNOB_R = 8

THEME_MEDIA_FIELDS = [
    ("background_alpha", "Background Alpha", 0, 255, 5, ""),
    ("background_slide_duration_sec", "Slide Duration", 1, 60, 1, "s"),
    ("theme_background_transition_percent", "Theme Transition Blend", 10, 90, 5, "%"),
    ("cue_background_transition_percent", "Cue Transition Blend", 10, 90, 5, "%"),
    ("gif_speed_percent", "GIF Speed", 10, 200, 5, "%"),
]


def _pick_images() -> list[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        paths = filedialog.askopenfilenames(
            parent=root,
            title="Select theme media",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.webp;*.gif"), ("All files", "*.*")],
        )
        root.destroy()
        return list(paths) if paths else []
    except Exception:
        return []


class ThemeSettingsScreen:
    """Manage themes for the active performance."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)
        self._row_font = pygame.font.SysFont("Arial", ROW_FONT_SIZE)

        self._performance = perf_store.get_active_performance()
        self._performance_id = str((self._performance or {}).get("id", ""))
        self._performance_name = str((self._performance or {}).get("name", "Performance"))
        self._themes = perf_store.load_themes(self._performance_id) if self._performance_id else []
        self._active_index = perf_store.get_active_theme_index(self._performance_id) if self._performance_id else -1

        self._editing_index = -1
        self._editing_text = ""
        self._scroll_offset = 0
        self._scroll_area_h = 320
        self._scrollbar_rect = pygame.Rect(0, 0, 0, 0)

        self._hover_save = False
        self._hover_update = False
        self._hover_back = False
        self._hover_notes = -1
        self._hover_del = -1
        self._hover_name = -1
        self._hover_add_media = False
        self._hover_add_more = False
        self._hover_clear_media = False
        self._hover_style_sync = False
        self._hover_slider = -1
        self._drag_slider = -1

        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._add_theme_rect = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._save_all_rect = pygame.Rect(0, 0, TOP_BTN_W, TOP_BTN_H)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._rows_y = 0
        self._row_name_rects: list[pygame.Rect] = []
        self._row_notes_rects: list[pygame.Rect] = []
        self._row_del_rects: list[pygame.Rect] = []
        self._add_media_rect = pygame.Rect(0, 0, 0, 0)
        self._add_more_rect = pygame.Rect(0, 0, 0, 0)
        self._clear_media_rect = pygame.Rect(0, 0, 0, 0)
        self._style_sync_rect = pygame.Rect(0, 0, 0, 0)
        self._thumb_rect = pygame.Rect(0, 0, 0, 0)
        self._preview_slides: list[tuple[list[pygame.Surface], list[float]]] = []
        self._preview_slide_index = 0
        self._preview_slide_ms = 0.0
        self._preview_frame_index = 0
        self._preview_frame_ms = 0.0
        self._last_preview_tick = pygame.time.get_ticks()
        self._field_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect] = []

        self._build_layout()
        self._load_preview_media()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN:
            if self._editing_index >= 0:
                return self._handle_edit_key(event)
            if event.key == pygame.K_ESCAPE:
                return "back"
            theme_index = self._theme_index_from_key(event.key)
            if theme_index is not None:
                self._select_theme(theme_index)
                return None
        if event.type == pygame.MOUSEWHEEL:
            self._do_scroll(-event.y * 32)
            return None
        if event.type == pygame.MOUSEMOTION:
            if self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            self._update_hover(event.pos)
            return None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self._handle_click(event.pos)
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1
        return None

    def _theme_index_from_key(self, key: int) -> int | None:
        key_map = {
            pygame.K_1: 0,
            pygame.K_2: 1,
            pygame.K_3: 2,
            pygame.K_4: 3,
            pygame.K_5: 4,
            pygame.K_6: 5,
            pygame.K_7: 6,
            pygame.K_8: 7,
            pygame.K_9: 8,
            pygame.K_KP1: 0,
            pygame.K_KP2: 1,
            pygame.K_KP3: 2,
            pygame.K_KP4: 3,
            pygame.K_KP5: 4,
            pygame.K_KP6: 5,
            pygame.K_KP7: 6,
            pygame.K_KP8: 7,
            pygame.K_KP9: 8,
        }
        idx = key_map.get(key)
        if idx is None or not (0 <= idx < len(self._themes)):
            return None
        return idx

    def _select_theme(self, index: int) -> None:
        if not (0 <= index < len(self._themes)):
            return
        perf_store.set_active_theme(self._performance_id, index)
        perf_store.apply_theme_to_config(self._performance_id, index)
        self._active_index = index
        self._load_preview_media()

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)
        self._draw_rows()
        self._draw_media_panel()
        self._draw_back_button()

    def _refresh(self) -> None:
        self._performance = perf_store.get_active_performance()
        self._performance_id = str((self._performance or {}).get("id", ""))
        self._performance_name = str((self._performance or {}).get("name", "Performance"))
        self._themes = perf_store.load_themes(self._performance_id) if self._performance_id else []
        self._active_index = perf_store.get_active_theme_index(self._performance_id) if self._performance_id else -1
        self._build_layout()
        self._load_preview_media()

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
        if self._editing_index >= 0:
            idx = self._editing_index
            if idx >= len(self._row_name_rects) or not self._row_name_rects[idx].collidepoint(pos):
                self._commit_edit()

        if self._back_rect.collidepoint(pos):
            return "back"
        if self._add_theme_rect.collidepoint(pos):
            perf_store.create_theme(self._performance_id, f"Theme {len(self._themes) + 1}")
            self._refresh()
            return None
        if self._save_all_rect.collidepoint(pos):
            perf_store.save_active_theme_from_current(self._performance_id)
            self._refresh()
            return None
        for i, rect in enumerate(self._slider_rects):
            if rect.inflate(0, 18).collidepoint(pos):
                self._drag_slider = i
                self._set_slider_from_x(i, pos[0])
                return None

        for i, rect in enumerate(self._row_notes_rects):
            if rect.collidepoint(pos):
                perf_store.set_active_theme(self._performance_id, i)
                perf_store.apply_theme_to_config(self._performance_id, i)
                self._active_index = i
                self._load_preview_media()
                return "notes_settings"

        for i, rect in enumerate(self._row_del_rects):
            if rect.collidepoint(pos):
                perf_store.delete_theme(self._performance_id, i)
                self._refresh()
                return None

        for i, rect in enumerate(self._row_name_rects):
            if rect.collidepoint(pos):
                perf_store.set_active_theme(self._performance_id, i)
                perf_store.apply_theme_to_config(self._performance_id, i)
                self._active_index = i
                self._start_edit(i)
                self._load_preview_media()
                return None

        if self._add_media_rect.collidepoint(pos):
            self._set_media(replace=True)
        elif self._add_more_rect.collidepoint(pos):
            self._set_media(replace=False)
        elif self._clear_media_rect.collidepoint(pos):
            self._clear_media()
        elif self._style_sync_rect.collidepoint(pos):
            enabled = not perf_store.is_theme_style_sync_enabled(self._performance_id, self._active_index)
            perf_store.set_theme_style_sync_enabled(self._performance_id, self._active_index, enabled)
            self._refresh()
        return None

    def _set_media(self, replace: bool) -> None:
        if self._active_index < 0:
            return
        selected = _pick_images()
        if not selected:
            return
        current_media = dict(self._themes[self._active_index].get("media", {}))
        current_paths = list(current_media.get("background_slideshow_paths", []))
        if not replace:
            single = str(current_media.get("background_image", ""))
            if single and not current_paths:
                current_paths = [single]
            current_paths.extend(selected)
            patch = {
                "background_image": "",
                "background_slideshow_paths": current_paths,
            }
        else:
            patch = {
                "background_image": selected[0] if len(selected) == 1 else "",
                "background_slideshow_paths": selected if len(selected) > 1 else [],
            }
        perf_store.set_theme_media(self._performance_id, self._active_index, patch)
        self._refresh()

    def _clear_media(self) -> None:
        if self._active_index < 0:
            return
        perf_store.set_theme_media(
            self._performance_id,
            self._active_index,
            {"background_image": "", "background_slideshow_paths": []},
        )
        self._refresh()

    def _commit_edit(self) -> None:
        idx = self._editing_index
        if 0 <= idx < len(self._themes):
            perf_store.rename_theme(self._performance_id, idx, self._editing_text.strip() or f"Theme {idx + 1}")
        self._editing_index = -1
        self._editing_text = ""
        self._refresh()

    def _start_edit(self, index: int) -> None:
        self._editing_index = index
        self._editing_text = str(self._themes[index].get("name", f"Theme {index + 1}"))

    def _do_scroll(self, delta: int) -> None:
        total_h = len(self._themes) * (ROW_H + ROW_GAP)
        max_scroll = max(0, total_h - self._scroll_area_h)
        self._scroll_offset = max(0, min(max_scroll, self._scroll_offset + delta))
        self._build_layout()

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx
        title = self._title_font.render(f"Themes: {self._performance_name}", True, TITLE_COLOR)
        title_y = sr.height // 16
        self._title_surf = title
        self._title_pos = (cx - title.get_width() // 2, title_y)

        top = title_y + title.get_height() + 16
        content_bottom = sr.height - BACK_H - 34
        content_h = max(220, content_bottom - top)
        content_w = sr.width - 52
        left_w = int(content_w * 0.56)
        right_w = content_w - left_w - 16
        self._left_panel = pygame.Rect(26, top, left_w, content_h)
        self._right_panel = pygame.Rect(self._left_panel.right + 16, top, right_w, content_h)

        btn_gap = 10
        btn_w = max(180, (self._left_panel.width - 24 - btn_gap) // 2)
        self._add_theme_rect = pygame.Rect(self._left_panel.left + 12, self._left_panel.top + 12, btn_w, TOP_BTN_H)
        self._save_all_rect = pygame.Rect(self._add_theme_rect.right + btn_gap, self._left_panel.top + 12, btn_w, TOP_BTN_H)

        self._rows_y = self._add_theme_rect.bottom + 16
        self._scroll_area_h = max(60, self._left_panel.bottom - self._rows_y - 12)
        _SCROLLBAR_W = 8
        self._scrollbar_rect = pygame.Rect(
            self._left_panel.right - _SCROLLBAR_W - 4,
            self._rows_y,
            _SCROLLBAR_W,
            self._scroll_area_h,
        )
        rx = self._left_panel.left + 12
        row_name_w = max(120, min(NAME_W, self._left_panel.width - 12 - (NOTES_W + COL_GAP + DEL_W + COL_GAP)))
        self._row_name_rects = []
        self._row_notes_rects = []
        self._row_del_rects = []
        for i in range(len(self._themes)):
            y = self._rows_y + i * (ROW_H + ROW_GAP) - self._scroll_offset
            self._row_name_rects.append(pygame.Rect(rx, y, row_name_w, ROW_H))
            notes_x = rx + row_name_w + COL_GAP
            self._row_notes_rects.append(pygame.Rect(notes_x, y, NOTES_W, ROW_H))
            del_x = notes_x + NOTES_W + COL_GAP
            self._row_del_rects.append(pygame.Rect(del_x, y, DEL_W, ROW_H))

        rp = self._right_panel
        self._add_media_rect = pygame.Rect(rp.left + 16, rp.top + 56, rp.width - 32, 44)
        self._add_more_rect = pygame.Rect(rp.left + 16, self._add_media_rect.bottom + 10, rp.width - 32, 44)
        self._clear_media_rect = pygame.Rect(rp.left + 16, self._add_more_rect.bottom + 10, rp.width - 32, 44)
        self._style_sync_rect = pygame.Rect(rp.left + 16, self._clear_media_rect.bottom + 10, rp.width - 32, 44)
        controls_top = self._style_sync_rect.bottom + 22
        slider_height = 50
        slider_count = len(THEME_MEDIA_FIELDS)
        slider_total_h = slider_count * slider_height + max(0, slider_count - 1) * 8
        slider_top_pad = 16
        slider_bottom_margin = 14
        thumb_bottom_margin = 10
        thumb_h = max(120, rp.height - (controls_top - rp.top) - slider_top_pad - slider_total_h - slider_bottom_margin - thumb_bottom_margin)
        self._thumb_rect = pygame.Rect(rp.left + 16, controls_top, rp.width - 32, thumb_h)
        slider_top = self._thumb_rect.bottom + slider_top_pad
        self._field_rects = []
        self._slider_rects = []
        for i in range(len(THEME_MEDIA_FIELDS)):
            field_rect = pygame.Rect(rp.left + 16, slider_top + i * (slider_height + 8), rp.width - 32, slider_height)
            slider_rect = pygame.Rect(field_rect.left + 8, field_rect.bottom - 16, field_rect.width - 16, SLIDER_H)
            self._field_rects.append(field_rect)
            self._slider_rects.append(slider_rect)

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_save = self._add_theme_rect.collidepoint(pos)
        self._hover_update = self._save_all_rect.collidepoint(pos)
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_notes = next((i for i, r in enumerate(self._row_notes_rects) if r.collidepoint(pos)), -1)
        self._hover_del = next((i for i, r in enumerate(self._row_del_rects) if r.collidepoint(pos)), -1)
        self._hover_name = next((i for i, r in enumerate(self._row_name_rects) if r.collidepoint(pos)), -1)
        self._hover_add_media = self._add_media_rect.collidepoint(pos)
        self._hover_add_more = self._add_more_rect.collidepoint(pos)
        self._hover_clear_media = self._clear_media_rect.collidepoint(pos)
        self._hover_style_sync = self._style_sync_rect.collidepoint(pos)
        self._hover_slider = next((i for i, r in enumerate(self._slider_rects) if r.inflate(0, 18).collidepoint(pos)), -1)

    def _set_slider_from_x(self, index: int, mouse_x: int) -> None:
        if not (0 <= self._active_index < len(self._themes)):
            return
        rect = self._slider_rects[index]
        key, _label, min_v, max_v, step, _suffix = THEME_MEDIA_FIELDS[index]
        if rect.width <= 1:
            return
        ratio = (mouse_x - rect.left) / float(rect.width)
        ratio = max(0.0, min(1.0, ratio))
        raw_value = min_v + ratio * (max_v - min_v)
        stepped = int(round(raw_value / step) * step)
        new_value = max(min_v, min(max_v, stepped))
        if key == "theme_background_transition_percent":
            media = dict(self._themes[self._active_index].get("media", {}))
            if int(media.get("background_transition_percent", new_value)) == new_value:
                return
            perf_store.set_theme_media(
                self._performance_id,
                self._active_index,
                {"background_transition_percent": new_value},
            )
            self._refresh()
            return

        if key == "cue_background_transition_percent":
            cue_count = perf_store.get_theme_style_cue_count(self._performance_id, self._active_index)
            cue_index = max(0, min(cue_count - 1, self._preview_slide_index))
            current = perf_store.get_theme_cue_transition_percent(
                self._performance_id,
                self._active_index,
                cue_index,
            )
            if current == new_value:
                return
            perf_store.set_theme_cue_transition_percent(
                self._performance_id,
                self._active_index,
                cue_index,
                new_value,
            )
            self._refresh()
            return
        media = dict(self._themes[self._active_index].get("media", {}))
        if int(media.get(key, new_value)) == new_value:
            return
        perf_store.set_theme_media(self._performance_id, self._active_index, {key: new_value})
        self._refresh()

    @staticmethod
    def _load_image_frames(path: pathlib.Path) -> tuple[list[pygame.Surface], list[float]]:
        if path.suffix.lower() == ".gif":
            try:
                from PIL import Image as _PILImage  # type: ignore

                pil = _PILImage.open(str(path))
                frames: list[pygame.Surface] = []
                durations: list[float] = []
                try:
                    while True:
                        rgba = pil.convert("RGBA")
                        surf = pygame.image.fromstring(rgba.tobytes(), rgba.size, "RGBA").convert_alpha()
                        frames.append(surf)
                        durations.append(max(16.0, float(pil.info.get("duration", 100))))
                        pil.seek(pil.tell() + 1)
                except EOFError:
                    pass
                if frames:
                    return frames, durations
            except ImportError:
                pass
            except Exception:
                return [], []

        try:
            image = pygame.image.load(str(path))
            surf = image.convert_alpha() if image.get_alpha() is not None else image.convert()
            return [surf], [1_000_000.0]
        except Exception:
            return [], []

    def _load_preview_media(self) -> None:
        self._preview_slides = []
        self._preview_slide_index = 0
        self._preview_slide_ms = 0.0
        self._preview_frame_index = 0
        self._preview_frame_ms = 0.0
        self._last_preview_tick = pygame.time.get_ticks()
        if not (0 <= self._active_index < len(self._themes)):
            return
        media = dict(self._themes[self._active_index].get("media", {}))
        slideshow = list(media.get("background_slideshow_paths", []))
        single = str(media.get("background_image", ""))
        paths_to_use = slideshow if slideshow else ([single] if single else [])
        for path_str in paths_to_use:
            path = pathlib.Path(path_str)
            if not path.exists():
                continue
            frames, durations = self._load_image_frames(path)
            if frames:
                self._preview_slides.append((frames, durations))

    def _advance_preview(self, dt_ms: float) -> tuple[Optional[pygame.Surface], Optional[pygame.Surface], float]:
        if not self._preview_slides:
            return None, None, 0.0

        media = dict(self._themes[self._active_index].get("media", {})) if 0 <= self._active_index < len(self._themes) else {}
        slide_dur_ms = max(500.0, float(media.get("background_slide_duration_sec", 5)) * 1000.0)
        transition_pct = int(media.get("background_transition_percent", 35))
        style_sync_enabled = perf_store.is_theme_style_sync_enabled(self._performance_id, self._active_index)
        if style_sync_enabled:
            cue_count = perf_store.get_theme_style_cue_count(self._performance_id, self._active_index)
            cue_index = max(0, min(cue_count - 1, self._preview_slide_index))
            transition_pct = perf_store.get_theme_cue_transition_percent(
                self._performance_id,
                self._active_index,
                cue_index,
            )
        transition_ratio = transition_pct / 100.0
        transition_ratio = max(0.10, min(0.90, transition_ratio))
        transition_ms = max(500.0, min(3000.0, slide_dur_ms * transition_ratio))

        if len(self._preview_slides) > 1:
            self._preview_slide_ms += dt_ms
            while self._preview_slide_ms >= slide_dur_ms:
                self._preview_slide_ms -= slide_dur_ms
                self._preview_slide_index = (self._preview_slide_index + 1) % len(self._preview_slides)
                self._preview_frame_index = 0
                self._preview_frame_ms = 0.0

        frames, durations = self._preview_slides[self._preview_slide_index % len(self._preview_slides)]
        if not frames:
            return None, None, 0.0

        if len(frames) > 1:
            speed_pct = int(media.get("gif_speed_percent", 100))
            speed_pct = max(10, min(200, speed_pct))
            self._preview_frame_ms += dt_ms * (speed_pct / 100.0)
            while durations and self._preview_frame_ms >= durations[self._preview_frame_index % len(durations)]:
                self._preview_frame_ms -= durations[self._preview_frame_index % len(durations)]
                self._preview_frame_index = (self._preview_frame_index + 1) % len(frames)

        current_frame = frames[self._preview_frame_index % len(frames)]
        next_frame: Optional[pygame.Surface] = None
        blend = 0.0

        if len(self._preview_slides) > 1:
            blend_start_ms = slide_dur_ms - transition_ms
            if self._preview_slide_ms >= blend_start_ms:
                t = (self._preview_slide_ms - blend_start_ms) / max(1.0, transition_ms)
                t = max(0.0, min(1.0, t))
                blend = t * t * (3.0 - 2.0 * t)
                next_idx = (self._preview_slide_index + 1) % len(self._preview_slides)
                next_frames, _next_durations = self._preview_slides[next_idx]
                if next_frames:
                    next_frame = next_frames[0]

        return current_frame, next_frame, blend

    def _draw_btn(self, rect: pygame.Rect, label: str, hover: bool, bg: tuple, bg_h: tuple, fg: tuple, fg_h: tuple) -> None:
        pygame.draw.rect(self.screen, bg_h if hover else bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, BORDER_COLOR, rect, width=1, border_radius=8)
        surf = self._btn_font.render(label, True, fg_h if hover else fg)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_top_buttons(self) -> None:
        self._draw_btn(self._add_theme_rect, "ADD THEME", self._hover_save, SAVE_BG, SAVE_BG_HOVER, SAVE_TEXT, SAVE_TEXT_HOVER)
        self._draw_btn(self._save_all_rect, "SAVE ALL CHANGES", self._hover_update, UPDATE_BG, UPDATE_BG_HOVER, UPDATE_TEXT, UPDATE_TEXT_HOVER)

    def _draw_back_button(self) -> None:
        self._draw_btn(self._back_rect, "BACK", self._hover_back, BTN_NORMAL_BG, BTN_HOVER_BG, BTN_TEXT, BTN_TEXT_HOVER)

    def _draw_rows(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._left_panel, border_radius=8)
        pygame.draw.rect(self.screen, BORDER_COLOR, self._left_panel, width=1, border_radius=8)
        self._draw_top_buttons()
        if not self._themes:
            msg = self._row_font.render("No themes yet. Press ADD THEME to create one.", True, MUTED_TEXT_COLOR)
            self.screen.blit(msg, (self._left_panel.left + 18, self._rows_y + 8))
            return

        clip = pygame.Rect(self._left_panel.left, self._rows_y, self._left_panel.width, self._scroll_area_h)
        self.screen.set_clip(clip)
        for i, theme in enumerate(self._themes):
            name_rect = self._row_name_rects[i]
            if name_rect.bottom < self._rows_y or name_rect.top > self._rows_y + self._scroll_area_h:
                continue
            notes_rect = self._row_notes_rects[i]
            del_rect = self._row_del_rects[i]
            is_active = i == self._active_index
            is_editing = i == self._editing_index

            name_bg = EDITOR_ACTIVE_BG if is_editing else EDITOR_BG
            name_border = EDITOR_ACTIVE_BORDER if is_editing else ACTIVE_BORDER if is_active else EDITOR_BORDER
            pygame.draw.rect(self.screen, name_bg, name_rect, border_radius=6)
            pygame.draw.rect(self.screen, name_border, name_rect, width=2 if (is_active or is_editing) else 1, border_radius=6)
            display_text = (self._editing_text + "|") if is_editing else str(theme.get("name", f"Theme {i + 1}"))
            surf = self._row_font.render(display_text, True, TITLE_COLOR if is_active else BTN_TEXT)
            self.screen.blit(surf, (name_rect.x + 6, name_rect.centery - surf.get_height() // 2))

            if is_active:
                active_tag = self._row_font.render("ACTIVE", True, SAVE_TEXT)
                self.screen.blit(active_tag, active_tag.get_rect(midleft=(name_rect.right - 80, name_rect.centery)))
            self._draw_btn(notes_rect, "NOTES", self._hover_notes == i, UPDATE_BG, UPDATE_BG_HOVER, UPDATE_TEXT, UPDATE_TEXT_HOVER)
            self._draw_btn(del_rect, "DEL", self._hover_del == i, DEL_BG, DEL_BG_HOVER, DEL_TEXT, DEL_TEXT_HOVER)
        self.screen.set_clip(None)
        total_h = len(self._themes) * (ROW_H + ROW_GAP)
        if total_h > self._scroll_area_h:
            track = self._scrollbar_rect
            pygame.draw.rect(self.screen, (40, 40, 55), track, border_radius=4)
            visible_ratio = self._scroll_area_h / max(1, total_h)
            thumb_h = max(24, int(track.height * visible_ratio))
            max_scroll = max(1, total_h - self._scroll_area_h)
            thumb_y = track.top + int((track.height - thumb_h) * self._scroll_offset / max_scroll)
            thumb_rect = pygame.Rect(track.left, thumb_y, track.width, thumb_h)
            pygame.draw.rect(self.screen, (90, 90, 130), thumb_rect, border_radius=4)

    def _draw_media_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._right_panel, border_radius=8)
        pygame.draw.rect(self.screen, BORDER_COLOR, self._right_panel, width=1, border_radius=8)
        self.screen.set_clip(self._right_panel)

        title = self._row_font.render("Theme Media", True, TEXT_COLOR)
        self.screen.blit(title, (self._right_panel.left + 16, self._right_panel.top + 16))

        if 0 <= self._active_index < len(self._themes):
            active_name = str(self._themes[self._active_index].get("name", f"Theme {self._active_index + 1}"))
            active_surf = self._row_font.render(active_name, True, MUTED_TEXT_COLOR)
            self.screen.blit(active_surf, (self._right_panel.left + 16, self._right_panel.top + 34))

        self._draw_btn(self._add_media_rect, "ADD MEDIA", self._hover_add_media, BTN_NORMAL_BG, BTN_HOVER_BG, BTN_TEXT, BTN_TEXT_HOVER)
        self._draw_btn(self._add_more_rect, "ADD MORE MEDIA", self._hover_add_more, BTN_NORMAL_BG, BTN_HOVER_BG, BTN_TEXT, BTN_TEXT_HOVER)
        self._draw_btn(self._clear_media_rect, "CLEAR MEDIA", self._hover_clear_media, DEL_BG, DEL_BG_HOVER, DEL_TEXT, DEL_TEXT_HOVER)
        style_sync_enabled = (
            perf_store.is_theme_style_sync_enabled(self._performance_id, self._active_index)
            if 0 <= self._active_index < len(self._themes)
            else False
        )
        sync_label = "STYLE SYNC ON" if style_sync_enabled else "STYLE SYNC OFF"
        sync_bg = SAVE_BG if style_sync_enabled else BTN_NORMAL_BG
        sync_bg_hover = SAVE_BG_HOVER if style_sync_enabled else BTN_HOVER_BG
        sync_fg = SAVE_TEXT if style_sync_enabled else BTN_TEXT
        sync_fg_hover = SAVE_TEXT_HOVER if style_sync_enabled else BTN_TEXT_HOVER
        self._draw_btn(self._style_sync_rect, sync_label, self._hover_style_sync, sync_bg, sync_bg_hover, sync_fg, sync_fg_hover)

        pygame.draw.rect(self.screen, BG_COLOR, self._thumb_rect, border_radius=8)
        pygame.draw.rect(self.screen, BORDER_COLOR, self._thumb_rect, width=1, border_radius=8)
        preview_now = pygame.time.get_ticks()
        dt_ms = max(0.0, min(250.0, float(preview_now - self._last_preview_tick)))
        self._last_preview_tick = preview_now
        current_frame, next_frame, blend = self._advance_preview(dt_ms)
        media = dict(self._themes[self._active_index].get("media", {})) if 0 <= self._active_index < len(self._themes) else {}
        alpha = int(media.get("background_alpha", 120))

        if current_frame is not None:
            fit = pygame.transform.smoothscale(current_frame, (self._thumb_rect.width - 8, self._thumb_rect.height - 8))
            fit.set_alpha(alpha)
            self.screen.blit(fit, (self._thumb_rect.left + 4, self._thumb_rect.top + 4))
            if next_frame is not None and blend > 0.0:
                fit_next = pygame.transform.smoothscale(next_frame, (self._thumb_rect.width - 8, self._thumb_rect.height - 8))
                fit_next.set_alpha(max(0, min(255, int(alpha * blend))))
                self.screen.blit(fit_next, (self._thumb_rect.left + 4, self._thumb_rect.top + 4))
        else:
            hint = self._row_font.render("No media thumbnail yet", True, MUTED_TEXT_COLOR)
            self.screen.blit(hint, hint.get_rect(center=self._thumb_rect.center))

        if 0 <= self._active_index < len(self._themes):
            media = dict(self._themes[self._active_index].get("media", {}))
            slideshow = list(media.get("background_slideshow_paths", []))
            if slideshow:
                status = f"{len(slideshow)} media files"
            else:
                single = str(media.get("background_image", ""))
                status = pathlib.Path(single).name if single else "No media selected"
            status_surf = self._row_font.render(status, True, MUTED_TEXT_COLOR)
            self.screen.blit(status_surf, (self._thumb_rect.left + 4, self._thumb_rect.bottom + 6))
            if style_sync_enabled:
                cue_count = perf_store.get_theme_style_cue_count(self._performance_id, self._active_index)
                cue_surf = self._row_font.render(f"{cue_count} synced style cues", True, MUTED_TEXT_COLOR)
                self.screen.blit(cue_surf, (self._thumb_rect.left + 4, self._thumb_rect.bottom + 28))

        self._draw_theme_media_fields()
        self.screen.set_clip(None)

    def _draw_theme_media_fields(self) -> None:
        if not (0 <= self._active_index < len(self._themes)):
            return
        media = dict(self._themes[self._active_index].get("media", {}))
        cue_count = perf_store.get_theme_style_cue_count(self._performance_id, self._active_index)
        cue_index = max(0, min(cue_count - 1, self._preview_slide_index))
        for i, (key, label, min_v, max_v, _step, suffix) in enumerate(THEME_MEDIA_FIELDS):
            field_rect = self._field_rects[i]
            slider_rect = self._slider_rects[i]
            pygame.draw.rect(self.screen, BG_COLOR, field_rect, border_radius=6)
            pygame.draw.rect(self.screen, BORDER_COLOR, field_rect, width=1, border_radius=6)

            draw_label = label
            if key == "cue_background_transition_percent":
                draw_label = f"Cue {cue_index + 1} Transition Blend"
            self.screen.blit(self._row_font.render(draw_label, True, TEXT_COLOR), (field_rect.left + 8, field_rect.top + 6))

            if key == "theme_background_transition_percent":
                value = int(media.get("background_transition_percent", min_v))
            elif key == "cue_background_transition_percent":
                value = perf_store.get_theme_cue_transition_percent(
                    self._performance_id,
                    self._active_index,
                    cue_index,
                )
            else:
                value = int(media.get(key, min_v))
            value_surf = self._row_font.render(f"{value}{suffix}", True, MUTED_TEXT_COLOR)
            self.screen.blit(value_surf, value_surf.get_rect(topright=(field_rect.right - 8, field_rect.top + 6)))

            slider_bg = BTN_HOVER_BG if self._hover_slider == i or self._drag_slider == i else BTN_NORMAL_BG
            pygame.draw.rect(self.screen, slider_bg, slider_rect, border_radius=4)
            pygame.draw.rect(self.screen, BORDER_COLOR, slider_rect, width=1, border_radius=4)

            ratio = (value - min_v) / float(max(1, max_v - min_v))
            fill_rect = pygame.Rect(slider_rect.left, slider_rect.top, max(1, int(slider_rect.width * ratio)), slider_rect.height)
            pygame.draw.rect(self.screen, SLIDER_FILL, fill_rect, border_radius=4)

            knob_x = int(slider_rect.left + ratio * slider_rect.width)
            knob_center = (knob_x, slider_rect.centery)
            pygame.draw.circle(self.screen, (210, 210, 210), knob_center, SLIDER_KNOB_R)
            pygame.draw.circle(self.screen, BORDER_COLOR, knob_center, SLIDER_KNOB_R, width=1)
