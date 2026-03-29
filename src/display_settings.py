"""Display settings screen for projector scaling and playback options.

Note: Background image selection is now handled in Theme Settings.
"""

from __future__ import annotations

import pathlib
import pygame
from src import config as cfg
from src import file_limits
from src.piano import Piano


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

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 24
VALUE_FONT_SIZE = 22
BTN_FONT_SIZE = 26

ROW_H = 64
ROW_GAP = 12
BACK_W = 160
BACK_H = 52
SLIDER_H = 8
KNOB_R = 9

PANEL_MARGIN_X = 26
PANEL_GAP = 16


class DisplaySettingsScreen:
    """Settings UI for display scale and background image transparency."""

    _PREVIEW_ACTIVE_NOTES = {48, 52, 55, 60, 64, 67, 72}

    FIELDS = [
        ("width_scale_percent", "Highway Width Scale", 60, 80, 1, "%"),
        ("background_alpha", "Background Alpha", 0, 255, 5, ""),
        ("background_slide_duration_sec", "Slide Duration", 1, 60, 1, "s"),
        ("background_transition_percent", "Transition Blend", 10, 90, 5, "%"),
        ("gif_speed_percent", "GIF Speed", 10, 200, 5, "%"),
    ]

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values: dict[str, int | str | list[str]] = {}
        self._bg_image: pygame.Surface | None = None
        self._bg_first_frame: pygame.Surface | None = None  # first frame of slideshow for preview
        self._preview_keyboard_height: int = 18
        self._preview_keyboard_brightness: int = 100
        self._preview_highway_surf: pygame.Surface | None = None
        self._preview_piano: Piano | None = None
        self._preview_hw_size: tuple[int, int] = (0, 0)

        self._hover_back = False
        self._hover_slider: int = -1
        self._drag_slider: int = -1
        self._hover_fullscreen = False
        self._hover_blend_channels = False
        self._cursor: int = 0

        self._title_pos = (0, 0)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._row_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect] = []
        self._fullscreen_rect = pygame.Rect(0, 0, 0, 0)
        self._blend_channels_rect = pygame.Rect(0, 0, 0, 0)
        self._preview_rect = pygame.Rect(0, 0, 0, 0)

        self._load()
        self._load_background_image()
        self._build_layout()
        self._apply_cursor_hover()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            if self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "back"
            _nav = len(self.FIELDS) + 3
            if event.key == pygame.K_UP:
                self._cursor = (self._cursor - 1) % _nav
                self._apply_cursor_hover()
                return None
            if event.key == pygame.K_DOWN:
                self._cursor = (self._cursor + 1) % _nav
                self._apply_cursor_hover()
                return None
            if event.key == pygame.K_LEFT:
                self._cursor_adjust(-1)
                return None
            if event.key == pygame.K_RIGHT:
                self._cursor_adjust(1)
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                result = self._cursor_confirm()
                if result is not None:
                    return result
                return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._blend_channels_rect.collidepoint(event.pos):
                self._values["blend_same_pitch_channels"] = not bool(self._values.get("blend_same_pitch_channels", False))
                self._save()
                return None

            if self._fullscreen_rect.collidepoint(event.pos):
                return "toggle_fullscreen"

            for i, rect in enumerate(self._slider_rects):
                if rect.inflate(0, 18).collidepoint(event.pos):
                    self._drag_slider = i
                    self._set_slider_from_x(i, event.pos[0])
                    return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_rows()
        self._draw_right_panel()
        self._draw_back()

    def _load(self) -> None:
        conf = cfg.load()
        data = conf.get("display_style", {})
        keyboard = conf.get("keyboard_style", {})
        width_scale = int(data.get("width_scale_percent", 66))
        width_scale = max(60, min(80, width_scale))
        self._values = {
            "width_scale_percent": width_scale,
            "background_alpha": int(data.get("background_alpha", 120)),
            "background_image": str(data.get("background_image", "")),
            "background_slideshow_paths": list(data.get("background_slideshow_paths", [])),
            "background_slide_duration_sec": int(data.get("background_slide_duration_sec", 5)),
            "background_transition_percent": int(data.get("background_transition_percent", 35)),
            "gif_speed_percent": int(data.get("gif_speed_percent", 100)),
            "fullscreen": bool(data.get("fullscreen", True)),
            "blend_same_pitch_channels": bool(conf.get("blend_same_pitch_channels", False)),
        }
        self._preview_keyboard_height = int(keyboard.get("height_percent", 18))
        self._preview_keyboard_brightness = int(keyboard.get("brightness", 100))

    def _save(self) -> None:
        data = cfg.load()
        data["display_style"] = {
            "width_scale_percent": int(self._values["width_scale_percent"]),
            "background_alpha": int(self._values["background_alpha"]),
            "background_image": str(self._values["background_image"]),
            "background_slideshow_paths": list(self._values["background_slideshow_paths"]),
            "background_slide_duration_sec": int(self._values["background_slide_duration_sec"]),
            "background_transition_percent": int(self._values["background_transition_percent"]),
            "gif_speed_percent": int(self._values["gif_speed_percent"]),
            "fullscreen": bool(self._values["fullscreen"]),
        }
        data["blend_same_pitch_channels"] = bool(self._values.get("blend_same_pitch_channels", False))
        cfg.save(data)

    def _load_background_image(self) -> None:
        self._bg_image = None
        self._bg_first_frame = None
        slideshow: list[str] = list(self._values.get("background_slideshow_paths", []))
        single: str = str(self._values.get("background_image", ""))
        # Pick the first available path for preview
        preview_path_str = ""
        if slideshow:
            preview_path_str = next((p for p in slideshow if pathlib.Path(p).exists()), "")
        elif single:
            preview_path_str = single
        if not preview_path_str:
            return
        p = pathlib.Path(preview_path_str)
        if not p.exists():
            return
        if not file_limits.is_allowed_media_file(p):
            return
        _VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
        try:
            if p.suffix.lower() in _VIDEO_EXTS:
                # Extract first frame via OpenCV for the preview thumbnail
                try:
                    import cv2  # type: ignore
                    cap = cv2.VideoCapture(str(p))
                    ret, bgr = cap.read()
                    cap.release()
                    if ret:
                        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                        h, w = rgb.shape[:2]
                        surf = pygame.image.fromstring(rgb.tobytes(), (w, h), "RGB").convert()
                        self._bg_image = surf
                        self._bg_first_frame = surf
                        return
                except Exception:
                    pass
            if p.suffix.lower() == ".gif":
                # Try to load first GIF frame via Pillow for preview
                try:
                    from PIL import Image as _PILImage  # type: ignore
                    pil = _PILImage.open(str(p))
                    rgba = pil.convert("RGBA")
                    import pygame as _pg
                    surf = _pg.image.fromstring(rgba.tobytes(), rgba.size, "RGBA").convert_alpha()
                    self._bg_image = surf
                    self._bg_first_frame = surf
                    return
                except Exception:
                    pass
            img = pygame.image.load(str(p))
            self._bg_image = img.convert_alpha() if img.get_alpha() is not None else img.convert()
            self._bg_first_frame = self._bg_image
        except Exception:
            self._bg_image = None
            self._bg_first_frame = None

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Display Settings", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)
        self._title_surf = title_surf

        content_top = title_y + title_surf.get_height() + 20
        content_bottom = sr.height - BACK_H - 34
        content_h = max(200, content_bottom - content_top)

        content_w = sr.width - 2 * PANEL_MARGIN_X
        half_w = (content_w - PANEL_GAP) // 2

        self._left_panel = pygame.Rect(PANEL_MARGIN_X, content_top, half_w, content_h)
        self._right_panel = pygame.Rect(
            self._left_panel.right + PANEL_GAP, content_top, half_w, content_h
        )

        self._row_rects = []
        self._slider_rects = []
        y = self._left_panel.top + 12
        row_w = self._left_panel.width - 24
        # Reserve room for blend toggle + fullscreen toggle buttons under sliders.
        btn_h = 42
        btn_gap = 8
        available_for_rows = self._left_panel.height - 24 - (btn_h * 2) - btn_gap - 12
        row_h = max(40, min(ROW_H, (available_for_rows - ROW_GAP * (len(self.FIELDS) - 1)) // max(1, len(self.FIELDS))))
        for _ in self.FIELDS:
            row = pygame.Rect(self._left_panel.left + 12, y, row_w, row_h)
            slider = pygame.Rect(row.left + 6, row.bottom - 18, row.width - 12, SLIDER_H)
            self._row_rects.append(row)
            self._slider_rects.append(slider)
            y += row_h + ROW_GAP

        self._fullscreen_rect = pygame.Rect(self._left_panel.left + 12, self._left_panel.bottom - btn_h - 10, row_w, btn_h)
        self._blend_channels_rect = pygame.Rect(
            self._left_panel.left + 12,
            self._fullscreen_rect.top - btn_gap - btn_h,
            row_w,
            btn_h,
        )

        rp = self._right_panel
        self._preview_rect = pygame.Rect(rp.left + 12, rp.top + 12, rp.width - 24, rp.height - 24)

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_blend_channels = self._blend_channels_rect.collidepoint(pos)
        self._hover_fullscreen = self._fullscreen_rect.collidepoint(pos)
        self._hover_slider = -1
        for i, rect in enumerate(self._slider_rects):
            if rect.inflate(0, 18).collidepoint(pos):
                self._hover_slider = i
                break

    def _set_slider_from_x(self, index: int, mouse_x: int) -> None:
        rect = self._slider_rects[index]
        key, _label, min_v, max_v, step, _suffix = self.FIELDS[index]
        if rect.width <= 1:
            return

        ratio = (mouse_x - rect.left) / float(rect.width)
        ratio = max(0.0, min(1.0, ratio))
        raw_value = min_v + ratio * (max_v - min_v)
        stepped = int(round(raw_value / step) * step)
        new_v = max(min_v, min(max_v, stepped))
        if new_v == self._values[key]:
            return

        self._values[key] = new_v
        self._save()

    def _apply_cursor_hover(self) -> None:
        n = len(self.FIELDS)
        self._hover_slider = self._cursor if self._cursor < n else -1
        self._hover_blend_channels = (self._cursor == n)
        self._hover_fullscreen = (self._cursor == n + 1)
        self._hover_back = (self._cursor == n + 2)

    def _cursor_adjust(self, delta: int) -> None:
        n = len(self.FIELDS)
        if self._cursor < n:
            key, _lbl, min_v, max_v, step, _sfx = self.FIELDS[self._cursor]
            new_v = max(min_v, min(max_v, int(self._values[key]) + delta * step))
            if new_v != self._values[key]:
                self._values[key] = new_v
                self._save()
        elif self._cursor == n:
            self._values["blend_same_pitch_channels"] = not bool(self._values.get("blend_same_pitch_channels", False))
            self._save()

    def _cursor_confirm(self) -> str | None:
        n = len(self.FIELDS)
        if self._cursor == n + 2:
            return "back"
        if self._cursor == n:
            self._values["blend_same_pitch_channels"] = not bool(self._values.get("blend_same_pitch_channels", False))
            self._save()
            return None
        if self._cursor == n + 1:
            return "toggle_fullscreen"
        return None

    def _draw_title(self) -> None:
        self.screen.blit(self._title_surf, self._title_pos)

    def _draw_rows(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._left_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._left_panel, width=1, border_radius=8)

        for i, (key, label, _min_v, _max_v, _step, suffix) in enumerate(self.FIELDS):
            row = self._row_rects[i]
            slider = self._slider_rects[i]

            pygame.draw.rect(self.screen, BG_COLOR, row, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row, width=1, border_radius=6)

            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (row.left + 10, row.top + 7))

            val = f"{self._values[key]}{suffix}"
            value_surf = self._value_font.render(val, True, MUTED_TEXT_COLOR)
            self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

            track_color = BUTTON_HOVER_BG if i == self._hover_slider or i == self._drag_slider else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, track_color, slider, border_radius=4)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

            fill_ratio = self._value_ratio(i)
            fill_w = max(1, int(slider.width * fill_ratio))
            fill_rect = pygame.Rect(slider.left, slider.top, fill_w, slider.height)
            pygame.draw.rect(self.screen, (0, 180, 180), fill_rect, border_radius=4)

            knob_x = int(slider.left + fill_ratio * slider.width)
            knob_center = (knob_x, slider.centery)
            pygame.draw.circle(self.screen, (210, 210, 210), knob_center, KNOB_R)
            pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, knob_center, KNOB_R, width=1)

        # Fullscreen/window mode toggle button
        blend_enabled = bool(self._values.get("blend_same_pitch_channels", False))
        blend_bg = BUTTON_HOVER_BG if self._hover_blend_channels else BUTTON_NORMAL_BG
        blend_fg = BUTTON_HOVER_TEXT_COLOR if self._hover_blend_channels else BUTTON_TEXT_COLOR
        blend_label = "SAME-PITCH BLEND: ON" if blend_enabled else "SAME-PITCH BLEND: OFF"
        if blend_enabled and not self._hover_blend_channels:
            blend_bg = (0, 90, 90)
        pygame.draw.rect(self.screen, blend_bg, self._blend_channels_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._blend_channels_rect, width=1, border_radius=8)
        blend_txt = self._value_font.render(blend_label, True, blend_fg)
        self.screen.blit(blend_txt, blend_txt.get_rect(center=self._blend_channels_rect.center))

        fs = bool(self._values.get("fullscreen", True))
        label = "SWITCH TO WINDOWED MODE" if fs else "SWITCH TO FULLSCREEN"
        bg = BUTTON_HOVER_BG if self._hover_fullscreen else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_fullscreen else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._fullscreen_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._fullscreen_rect, width=1, border_radius=8)
        txt = self._value_font.render(label, True, fg)
        self.screen.blit(txt, txt.get_rect(center=self._fullscreen_rect.center))

    def _draw_right_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._right_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._right_panel, width=1, border_radius=8)

        pr = self._preview_rect
        pygame.draw.rect(self.screen, (10, 10, 14), pr, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, pr, width=1, border_radius=8)

        # Background always full preview width so you can align the keyboard.
        if self._bg_image is not None:
            bg = pygame.transform.smoothscale(self._bg_image, (pr.width, pr.height))
            bg.set_alpha(int(self._values["background_alpha"]))
            self.screen.blit(bg, pr.topleft)
        else:
            hint = self._value_font.render("No background image selected", True, MUTED_TEXT_COLOR)
            self.screen.blit(hint, hint.get_rect(center=(pr.centerx, pr.centery - 40)))

        # Highway preview area — scaled to width setting, centred like gameplay.
        scale = int(self._values["width_scale_percent"])
        kb_full_w = pr.width
        kb_scaled_w = max(1, int(kb_full_w * (scale / 100.0)))
        highway_rect = pygame.Rect(
            pr.left + (kb_full_w - kb_scaled_w) // 2,
            pr.top,
            kb_scaled_w,
            pr.height,
        )

        # Clip drawing inside the preview panel.
        prev_clip = self.screen.get_clip()
        self.screen.set_clip(pr)

        pygame.draw.rect(self.screen, (14, 16, 22), highway_rect)
        pygame.draw.rect(self.screen, (82, 88, 104), highway_rect, width=1)

        self._ensure_preview_highway(highway_rect.width, highway_rect.height)
        if self._preview_highway_surf is not None:
            self._preview_highway_surf.fill((0, 0, 0, 0))

            # Subtle top-to-bottom lane fade for a closer in-song feel.
            lane = pygame.Surface((highway_rect.width, highway_rect.height), pygame.SRCALPHA)
            band_h = max(2, highway_rect.height // 14)
            for i in range(14):
                y = i * band_h
                h = highway_rect.height - y if i == 13 else band_h
                alpha = 26 + i * 4
                pygame.draw.rect(lane, (10, 12, 18, min(110, alpha)), pygame.Rect(0, y, highway_rect.width, h))
            self._preview_highway_surf.blit(lane, (0, 0))

            if self._preview_piano is not None:
                self._preview_piano.draw(set(self._PREVIEW_ACTIVE_NOTES))

            self.screen.blit(self._preview_highway_surf, highway_rect.topleft)

        self.screen.set_clip(prev_clip)

        # Labels
        title = self._value_font.render("Preview  (matches in-song bottom keyboard placement)", True, TEXT_COLOR)
        self.screen.blit(title, (pr.left + 10, pr.top + 8))
        cap = self._label_font.render(f"Highway width: {scale}%", True, MUTED_TEXT_COLOR)
        self.screen.blit(cap, (pr.left + 10, pr.top + 36))

    def _ensure_preview_highway(self, width: int, height: int) -> None:
        size = (max(1, width), max(1, height))
        if self._preview_highway_surf is not None and self._preview_hw_size == size:
            return
        self._preview_hw_size = size
        self._preview_highway_surf = pygame.Surface(size, pygame.SRCALPHA)
        self._preview_piano = Piano(
            self._preview_highway_surf,
            height_percent=max(5, min(50, self._preview_keyboard_height)),
            brightness_percent=max(10, min(150, self._preview_keyboard_brightness)),
            visible=True,
        )

    def _value_ratio(self, index: int) -> float:
        key, _label, min_v, max_v, _step, _suffix = self.FIELDS[index]
        span = max(1, max_v - min_v)
        return (int(self._values[key]) - min_v) / float(span)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
