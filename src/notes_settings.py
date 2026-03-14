"""Screen for tuning Freeplay note animation style with live preview."""

from __future__ import annotations

import pygame
from src import config as cfg
from src.note_fx import NoteEffectRenderer

# Shared look
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
ACCENT_COLOR = (0, 180, 180)
KEY_COLOR = (220, 220, 220)
KEY_BORDER = (60, 60, 60)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 24
VALUE_FONT_SIZE = 22
BTN_FONT_SIZE = 26

ROW_H = 58
ROW_GAP = 10
BACK_W = 160
BACK_H = 52
SLIDER_H = 8
KNOB_R = 9
LAYER_BTN_H = 36
LAYER_BTN_GAP = 10
THEME_BTN_H = 52
THEME_BTN_GAP = 12

PANEL_MARGIN_X = 26
PANEL_GAP = 16

_PREVIEW_ON_MS = 1000
_PREVIEW_OFF_MS = 1000
_PREVIEW_PARTICLE_HEIGHT_PX = 32


class NotesSettingsScreen:
    """Settings UI for note particle style and rising-note preview."""

    MOTION_FIELDS = [
        ("speed_px_per_sec", "Rise Speed", 80, 1200, 20),
        ("decay_speed", "Decay Speed", 0, 240, 5),
        ("decay_value", "Decay Value", 0, 100, 5),
    ]

    SHAPE_FIELDS = [
        ("width_px", "Note Width", 4, 40, 1),
        ("edge_roundness_px", "Edge Roundness", 0, 20, 1),
    ]

    COLOR_CHANNELS = [
        ("r", "Red"),
        ("g", "Green"),
        ("b", "Blue"),
    ]

    COLOR_BLEND_FIELD = ("inner_blend_percent", "Inner/Outer Blend", 0, 100, 5)
    COLOR_EDGE_WIDTH_FIELD = ("outer_edge_width_px", "Outer Edge Width", 1, 8, 1)
    COLOR_GLOW_FIELD = ("glow_strength_percent", "Glow Strength", 0, 180, 5)

    EFFECT_TOGGLES = [
        ("effect_glow_enabled", "Glow"),
        ("effect_highlight_enabled", "Edge Highlight"),
        ("effect_sparks_enabled", "Sparks"),
        ("effect_smoke_enabled", "Smoke"),
        ("effect_press_smoke_enabled", "Start Mist"),
    ]

    EFFECT_FIELDS = [
        ("highlight_strength_percent", "Highlight Strength", 0, 170, 5),
        ("spark_amount_percent", "Spark Amount", 0, 300, 5),
        ("smoke_amount_percent", "Smoke Amount", 0, 300, 5),
        ("press_smoke_amount_percent", "Start Mist Amount", 0, 250, 5),
    ]

    LAYERS = [
        ("motion", "MOTION"),
        ("shape", "SHAPE"),
        ("color", "COLOR"),
        ("effects", "EFFECTS"),
        ("themes", "THEMES"),
    ]

    THEMES: list[tuple[str, str, dict[str, int | str]]] = [
        (
            "claire_de_lune",
            "Claire De Lune",
            {
                "speed_px_per_sec": 300,
                "width_px": 14,
                "edge_roundness_px": 12,
                "outer_edge_width_px": 2,
                "glow_strength_percent": 62,
                "decay_speed": 70,
                "decay_value": 26,
                "inner_blend_percent": 58,
                "effect_glow_enabled": 1,
                "effect_highlight_enabled": 1,
                "effect_sparks_enabled": 1,
                "effect_smoke_enabled": 1,
                "effect_press_smoke_enabled": 1,
                "effect_moon_dust_enabled": 1,
                "effect_steam_smoke_enabled": 1,
                "effect_halo_pulse_enabled": 1,
                "highlight_strength_percent": 42,
                "spark_amount_percent": 110,
                "smoke_amount_percent": 170,
                "press_smoke_amount_percent": 120,
                "color_r": 86,
                "color_g": 128,
                "color_b": 220,
                "interior_r": 205,
                "interior_g": 223,
                "interior_b": 255,
                "active_theme_id": "claire_de_lune",
                "experimental_claire_script_enabled": 1,
            },
        ),
        (
            "concert_cyan",
            "Concert Cyan",
            {
                "speed_px_per_sec": 430,
                "width_px": 18,
                "edge_roundness_px": 9,
                "outer_edge_width_px": 2,
                "glow_strength_percent": 82,
                "decay_speed": 95,
                "decay_value": 22,
                "inner_blend_percent": 32,
                "effect_glow_enabled": 1,
                "effect_highlight_enabled": 1,
                "effect_sparks_enabled": 1,
                "effect_smoke_enabled": 1,
                "effect_press_smoke_enabled": 0,
                "effect_moon_dust_enabled": 0,
                "effect_steam_smoke_enabled": 0,
                "effect_halo_pulse_enabled": 0,
                "highlight_strength_percent": 70,
                "spark_amount_percent": 100,
                "smoke_amount_percent": 95,
                "press_smoke_amount_percent": 90,
                "color_r": 22,
                "color_g": 180,
                "color_b": 255,
                "interior_r": 160,
                "interior_g": 245,
                "interior_b": 255,
                "active_theme_id": "concert_cyan",
                "experimental_claire_script_enabled": 0,
            },
        ),
        (
            "amber_stage",
            "Amber Stage",
            {
                "speed_px_per_sec": 380,
                "width_px": 17,
                "edge_roundness_px": 8,
                "outer_edge_width_px": 2,
                "glow_strength_percent": 68,
                "decay_speed": 105,
                "decay_value": 20,
                "inner_blend_percent": 28,
                "effect_glow_enabled": 1,
                "effect_highlight_enabled": 1,
                "effect_sparks_enabled": 1,
                "effect_smoke_enabled": 1,
                "effect_press_smoke_enabled": 0,
                "effect_moon_dust_enabled": 0,
                "effect_steam_smoke_enabled": 0,
                "effect_halo_pulse_enabled": 0,
                "highlight_strength_percent": 62,
                "spark_amount_percent": 90,
                "smoke_amount_percent": 90,
                "press_smoke_amount_percent": 80,
                "color_r": 255,
                "color_g": 135,
                "color_b": 62,
                "interior_r": 255,
                "interior_g": 225,
                "interior_b": 170,
                "active_theme_id": "amber_stage",
                "experimental_claire_script_enabled": 0,
            },
        ),
    ]

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values: dict[str, int | str] = {}
        self._hover_back = False
        self._hover_slider: int = -1
        self._drag_slider: int = -1
        self._drag_color: tuple[str, str] | None = None  # (channel, outer|inner)

        self._active_layer = "motion"
        self._hover_layer: str | None = None
        self._hover_theme: int = -1

        self._title_pos = (0, 0)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._preview_rect = pygame.Rect(0, 0, 0, 0)
        self._row_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect] = []
        self._layer_rects: dict[str, pygame.Rect] = {}
        self._theme_rects: list[pygame.Rect] = []
        self._effect_toggle_rects: list[pygame.Rect] = []

        self._preview_trails: list[dict[str, float | bool]] = []
        self._preview_active_trail: dict[str, float | bool] | None = None
        self._preview_cycle_ms = 0
        self._preview_was_on = False
        self._fx_renderer = NoteEffectRenderer(screen)

        self._load()
        self._build_layout()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            if self._drag_color is not None:
                channel, role = self._drag_color
                self._set_color_knob_from_x(channel, role, event.pos[0])
            elif self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            for layer, _label in self.LAYERS:
                if self._layer_rects[layer].collidepoint(event.pos):
                    if self._active_layer != layer:
                        self._active_layer = layer
                        self._build_layer_rows()
                    return None

            for i, rect in enumerate(self._slider_rects):
                hit = rect.inflate(0, 18).collidepoint(event.pos)
                if not hit:
                    continue

                if self._active_layer == "color":
                    if i < len(self.COLOR_CHANNELS):
                        channel = self.COLOR_CHANNELS[i][0]
                        outer_x, inner_x = self._color_knob_positions(channel, rect)
                        if abs(event.pos[0] - outer_x) <= abs(event.pos[0] - inner_x):
                            role = "outer"
                        else:
                            role = "inner"
                        self._drag_color = (channel, role)
                        self._set_color_knob_from_x(channel, role, event.pos[0])
                    else:
                        self._drag_slider = i
                        self._set_slider_from_x(i, event.pos[0])
                else:
                    self._drag_slider = i
                    self._set_slider_from_x(i, event.pos[0])
                return None

            if self._active_layer == "themes":
                for i, rect in enumerate(self._theme_rects):
                    if rect.collidepoint(event.pos):
                        self._apply_theme(i)
                        return None

            if self._active_layer == "effects":
                for i, rect in enumerate(self._effect_toggle_rects):
                    if rect.collidepoint(event.pos):
                        key, _label = self.EFFECT_TOGGLES[i]
                        self._values[key] = 0 if int(self._values[key]) else 1
                        self._save()
                        return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1
            self._drag_color = None

        return None

    def update(self, dt: int) -> None:
        cycle_len = _PREVIEW_ON_MS + _PREVIEW_OFF_MS
        self._preview_cycle_ms = (self._preview_cycle_ms + dt) % cycle_len
        preview_on = self._preview_cycle_ms < _PREVIEW_ON_MS

        if preview_on and not self._preview_was_on:
            self._start_preview_trail()
        elif not preview_on and self._preview_was_on:
            self._release_preview_trail()

        self._preview_was_on = preview_on

        if preview_on:
            self._anchor_preview_trail()

        NoteEffectRenderer.update_particles(self._preview_trails, dt)

        speed = float(max(1, self._values["speed_px_per_sec"]))
        dy = speed * (dt / 1000.0)
        survivors: list[dict[str, float | bool]] = []
        for trail in self._preview_trails:
            trail["age_ms"] = float(trail.get("age_ms", 0.0)) + dt
            trail["top_y"] = float(trail["top_y"]) - dy
            if bool(trail["released"]):
                trail["bottom_y"] = float(trail["bottom_y"]) - dy
            if float(trail["bottom_y"]) > self._preview_rect.top:
                survivors.append(trail)
        self._preview_trails = survivors

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_rows()
        self._draw_preview()
        self._draw_back()

    def _load(self) -> None:
        data = cfg.load().get("note_style", {})
        self._values = {
            "speed_px_per_sec": int(data.get("speed_px_per_sec", 420)),
            "width_px": int(data.get("width_px", 12)),
            "edge_roundness_px": int(data.get("edge_roundness_px", 4)),
            "outer_edge_width_px": int(data.get("outer_edge_width_px", 2)),
            "decay_speed": int(data.get("decay_speed", 80)),
            "decay_value": int(data.get("decay_value", 20)),
            "inner_blend_percent": int(data.get("inner_blend_percent", 35)),
            "glow_strength_percent": int(data.get("glow_strength_percent", 80)),
            "effect_glow_enabled": int(bool(data.get("effect_glow_enabled", 1))),
            "effect_highlight_enabled": int(bool(data.get("effect_highlight_enabled", 1))),
            "effect_sparks_enabled": int(bool(data.get("effect_sparks_enabled", 1))),
            "effect_smoke_enabled": int(bool(data.get("effect_smoke_enabled", 1))),
            "effect_press_smoke_enabled": int(bool(data.get("effect_press_smoke_enabled", 0))),
            "effect_moon_dust_enabled": int(bool(data.get("effect_moon_dust_enabled", 0))),
            "effect_steam_smoke_enabled": int(bool(data.get("effect_steam_smoke_enabled", 0))),
            "effect_halo_pulse_enabled": int(bool(data.get("effect_halo_pulse_enabled", 0))),
            "highlight_strength_percent": int(data.get("highlight_strength_percent", 70)),
            "spark_amount_percent": int(data.get("spark_amount_percent", 100)),
            "smoke_amount_percent": int(data.get("smoke_amount_percent", 100)),
            "press_smoke_amount_percent": int(data.get("press_smoke_amount_percent", 100)),
            "color_r": int(data.get("color_r", 0)),
            "color_g": int(data.get("color_g", 230)),
            "color_b": int(data.get("color_b", 230)),
            "interior_r": int(data.get("interior_r", 120)),
            "interior_g": int(data.get("interior_g", 255)),
            "interior_b": int(data.get("interior_b", 255)),
            "active_theme_id": str(data.get("active_theme_id", "custom")),
            "experimental_claire_script_enabled": int(bool(data.get("experimental_claire_script_enabled", 0))),
        }

    def _save(self) -> None:
        data = cfg.load()
        data["note_style"] = dict(self._values)
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Notes Settings", True, TITLE_COLOR)
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
        self._preview_rect = self._right_panel.inflate(-16, -16)

        # Layer buttons
        layers_count = len(self.LAYERS)
        total_gap = LAYER_BTN_GAP * (layers_count - 1)
        btn_w = (self._left_panel.width - 24 - total_gap) // layers_count
        y = self._left_panel.top + 12
        x = self._left_panel.left + 12
        self._layer_rects = {}
        for layer, _label in self.LAYERS:
            self._layer_rects[layer] = pygame.Rect(x, y, btn_w, LAYER_BTN_H)
            x += btn_w + LAYER_BTN_GAP

        self._build_layer_rows()

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

    def _active_fields(self) -> list[tuple[str, str, int, int, int]]:
        if self._active_layer == "motion":
            return list(self.MOTION_FIELDS)
        if self._active_layer == "shape":
            return list(self.SHAPE_FIELDS)
        if self._active_layer == "effects":
            return list(self.EFFECT_FIELDS)
        if self._active_layer == "themes":
            return []
        return (
            [(f"gradient_{c}", label, 0, 255, 5) for c, label in self.COLOR_CHANNELS]
            + [self.COLOR_BLEND_FIELD, self.COLOR_EDGE_WIDTH_FIELD, self.COLOR_GLOW_FIELD]
        )

    def _build_layer_rows(self) -> None:
        self._row_rects = []
        self._slider_rects = []
        self._theme_rects = []
        self._effect_toggle_rects = []

        fields = self._active_fields()
        y = self._left_panel.top + 12 + LAYER_BTN_H + 14
        row_w = self._left_panel.width - 24

        total_gaps = ROW_GAP * max(0, len(fields) - 1)
        avail_h = self._left_panel.height - (12 + LAYER_BTN_H + 14) - 12
        max_row_h = max(40, (avail_h - total_gaps) // max(1, len(fields)))
        row_h = max(40, min(ROW_H, max_row_h))
        slider_bottom_pad = max(10, min(16, row_h // 3))

        if self._active_layer == "themes":
            for _id, _label, _values in self.THEMES:
                rect = pygame.Rect(self._left_panel.left + 12, y, row_w, THEME_BTN_H)
                self._theme_rects.append(rect)
                y += THEME_BTN_H + THEME_BTN_GAP
        elif self._active_layer == "effects":
            toggle_h = 38
            for _key, _label in self.EFFECT_TOGGLES:
                rect = pygame.Rect(self._left_panel.left + 12, y, row_w, toggle_h)
                self._effect_toggle_rects.append(rect)
                y += toggle_h + 8

            y += 8
            for _ in fields:
                row_rect = pygame.Rect(self._left_panel.left + 12, y, row_w, row_h)
                slider_rect = pygame.Rect(
                    row_rect.left + 4,
                    row_rect.bottom - slider_bottom_pad,
                    row_rect.width - 8,
                    SLIDER_H,
                )
                self._row_rects.append(row_rect)
                self._slider_rects.append(slider_rect)
                y += row_h + ROW_GAP
        else:
            for _ in fields:
                row_rect = pygame.Rect(self._left_panel.left + 12, y, row_w, row_h)
                slider_rect = pygame.Rect(
                    row_rect.left + 4,
                    row_rect.bottom - slider_bottom_pad,
                    row_rect.width - 8,
                    SLIDER_H,
                )
                self._row_rects.append(row_rect)
                self._slider_rects.append(slider_rect)
                y += row_h + ROW_GAP

        self._drag_slider = -1
        self._drag_color = None

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_slider = -1
        for i, rect in enumerate(self._slider_rects):
            if rect.inflate(0, 18).collidepoint(pos):
                self._hover_slider = i
                break

        self._hover_layer = None
        for layer, _label in self.LAYERS:
            if self._layer_rects[layer].collidepoint(pos):
                self._hover_layer = layer
                break

        self._hover_theme = -1
        if self._active_layer == "themes":
            for i, rect in enumerate(self._theme_rects):
                if rect.collidepoint(pos):
                    self._hover_theme = i
                    break

        if self._active_layer == "effects":
            for i, rect in enumerate(self._effect_toggle_rects):
                if rect.collidepoint(pos):
                    self._hover_slider = i + 1000
                    break

    def _set_slider_from_x(self, index: int, mouse_x: int) -> None:
        rect = self._slider_rects[index]
        key, _label, min_v, max_v, step = self._active_fields()[index]
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

    def _color_knob_positions(self, channel: str, rect: pygame.Rect) -> tuple[int, int]:
        outer_v = int(self._values[f"color_{channel}"])
        inner_v = int(self._values[f"interior_{channel}"])
        outer_x = rect.left + int((outer_v / 255.0) * rect.width)
        inner_x = rect.left + int((inner_v / 255.0) * rect.width)
        return outer_x, inner_x

    def _set_color_knob_from_x(self, channel: str, role: str, mouse_x: int) -> None:
        rect = self._slider_rects[[c for c, _ in self.COLOR_CHANNELS].index(channel)]
        if rect.width <= 1:
            return

        ratio = (mouse_x - rect.left) / float(rect.width)
        ratio = max(0.0, min(1.0, ratio))
        raw_value = ratio * 255.0
        new_v = int(round(raw_value / 5.0) * 5)
        new_v = max(0, min(255, new_v))

        key = f"color_{channel}" if role == "outer" else f"interior_{channel}"
        if new_v == self._values[key]:
            return
        self._values[key] = new_v
        self._save()

    def _draw_title(self) -> None:
        self.screen.blit(self._title_surf, self._title_pos)

    def _draw_layer_buttons(self) -> None:
        for layer, label in self.LAYERS:
            rect = self._layer_rects[layer]
            active = layer == self._active_layer
            hovered = layer == self._hover_layer
            bg = BUTTON_HOVER_BG if (active or hovered) else BUTTON_NORMAL_BG
            fg = BUTTON_HOVER_TEXT_COLOR if (active or hovered) else BUTTON_TEXT_COLOR
            pygame.draw.rect(self.screen, bg, rect, border_radius=7)
            border = ACCENT_COLOR if active else BUTTON_BORDER_COLOR
            pygame.draw.rect(self.screen, border, rect, width=1, border_radius=7)
            surf = self._value_font.render(label, True, fg)
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_rows(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._left_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._left_panel, width=1, border_radius=8)

        self._draw_layer_buttons()

        if self._active_layer == "themes":
            self._draw_theme_buttons()
            return

        if self._active_layer == "effects":
            self._draw_effect_rows()
            return

        fields = self._active_fields()
        for i, (key, label, _min_v, _max_v, _step) in enumerate(fields):
            row = self._row_rects[i]
            slider = self._slider_rects[i]

            pygame.draw.rect(self.screen, BG_COLOR, row, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row, width=1, border_radius=6)

            if self._active_layer == "color":
                if i < len(self.COLOR_CHANNELS):
                    channel = self.COLOR_CHANNELS[i][0]
                    outer_v = int(self._values[f"color_{channel}"])
                    inner_v = int(self._values[f"interior_{channel}"])

                    label_surf = self._label_font.render(f"{label}  (Outer / Inner)", True, TEXT_COLOR)
                    self.screen.blit(label_surf, (row.left + 10, row.top + 6))

                    value_surf = self._value_font.render(f"{outer_v} / {inner_v}", True, MUTED_TEXT_COLOR)
                    self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

                    # Gradient track between outer and inner values for this channel.
                    pygame.draw.rect(self.screen, BUTTON_NORMAL_BG, slider, border_radius=4)
                    strips = max(12, slider.width // 4)
                    for s in range(strips):
                        t0 = s / float(strips)
                        t1 = (s + 1) / float(strips)
                        val = int(outer_v + (inner_v - outer_v) * ((t0 + t1) * 0.5))
                        if channel == "r":
                            col = (val, 28, 28)
                        elif channel == "g":
                            col = (28, val, 28)
                        else:
                            col = (28, 28, val)
                        x0 = slider.left + int(t0 * slider.width)
                        x1 = slider.left + int(t1 * slider.width)
                        pygame.draw.rect(self.screen, col, pygame.Rect(x0, slider.top, max(1, x1 - x0), slider.height))

                    pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

                    outer_x, inner_x = self._color_knob_positions(channel, slider)
                    outer_center = (outer_x, slider.centery)
                    inner_center = (inner_x, slider.centery)

                    pygame.draw.circle(self.screen, (150, 240, 240), outer_center, KNOB_R)
                    pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, outer_center, KNOB_R, width=1)
                    pygame.draw.circle(self.screen, (255, 255, 255), inner_center, KNOB_R)
                    pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, inner_center, KNOB_R, width=1)

                    o_tag = self._label_font.render("O", True, (30, 40, 40))
                    i_tag = self._label_font.render("I", True, (30, 30, 30))
                    self.screen.blit(o_tag, o_tag.get_rect(center=outer_center))
                    self.screen.blit(i_tag, i_tag.get_rect(center=inner_center))
                else:
                    val = int(self._values[key])
                    label_surf = self._label_font.render(label, True, TEXT_COLOR)
                    self.screen.blit(label_surf, (row.left + 10, row.top + 6))

                    suffix = "%" if key in ("inner_blend_percent", "glow_strength_percent") else ""
                    value_surf = self._value_font.render(f"{val}{suffix}", True, MUTED_TEXT_COLOR)
                    self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

                    track_color = BUTTON_HOVER_BG if i == self._hover_slider or i == self._drag_slider else BUTTON_NORMAL_BG
                    pygame.draw.rect(self.screen, track_color, slider, border_radius=4)
                    pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

                    fill_ratio = self._value_ratio(i)
                    fill_w = max(1, int(slider.width * fill_ratio))
                    fill_rect = pygame.Rect(slider.left, slider.top, fill_w, slider.height)
                    pygame.draw.rect(self.screen, ACCENT_COLOR, fill_rect, border_radius=4)

                    knob_x = int(slider.left + fill_ratio * slider.width)
                    knob_center = (knob_x, slider.centery)
                    pygame.draw.circle(self.screen, (210, 210, 210), knob_center, KNOB_R)
                    pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, knob_center, KNOB_R, width=1)
            else:
                label_surf = self._label_font.render(label, True, TEXT_COLOR)
                self.screen.blit(label_surf, (row.left + 10, row.top + 6))

                value_surf = self._value_font.render(str(self._values[key]), True, MUTED_TEXT_COLOR)
                self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

                track_color = BUTTON_HOVER_BG if i == self._hover_slider or i == self._drag_slider else BUTTON_NORMAL_BG
                pygame.draw.rect(self.screen, track_color, slider, border_radius=4)
                pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

                fill_ratio = self._value_ratio(i)
                fill_w = max(1, int(slider.width * fill_ratio))
                fill_rect = pygame.Rect(slider.left, slider.top, fill_w, slider.height)
                pygame.draw.rect(self.screen, ACCENT_COLOR, fill_rect, border_radius=4)

                knob_x = int(slider.left + fill_ratio * slider.width)
                knob_center = (knob_x, slider.centery)
                pygame.draw.circle(self.screen, (210, 210, 210), knob_center, KNOB_R)
                pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, knob_center, KNOB_R, width=1)

    def _draw_effect_rows(self) -> None:
        # Toggle rows
        for i, (key, label) in enumerate(self.EFFECT_TOGGLES):
            rect = self._effect_toggle_rects[i]
            hovered = self._hover_slider == i + 1000
            bg = BUTTON_HOVER_BG if hovered else BG_COLOR
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=6)

            enabled = bool(int(self._values[key]))
            cb = pygame.Rect(rect.left + 10, rect.centery - 9, 18, 18)
            pygame.draw.rect(self.screen, (35, 35, 45), cb, border_radius=4)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, cb, width=1, border_radius=4)
            if enabled:
                pygame.draw.rect(self.screen, ACCENT_COLOR, cb.inflate(-6, -6), border_radius=2)

            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (cb.right + 10, rect.top + 6))

            state_surf = self._value_font.render("ON" if enabled else "OFF", True, MUTED_TEXT_COLOR)
            self.screen.blit(state_surf, state_surf.get_rect(topright=(rect.right - 10, rect.top + 7)))

        # Slider rows
        for i, (key, label, _min_v, _max_v, _step) in enumerate(self.EFFECT_FIELDS):
            row = self._row_rects[i]
            slider = self._slider_rects[i]

            pygame.draw.rect(self.screen, BG_COLOR, row, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row, width=1, border_radius=6)

            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (row.left + 10, row.top + 6))

            val = int(self._values[key])
            value_surf = self._value_font.render(f"{val}%", True, MUTED_TEXT_COLOR)
            self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

            track_color = BUTTON_HOVER_BG if i == self._hover_slider or i == self._drag_slider else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, track_color, slider, border_radius=4)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider, width=1, border_radius=4)

            fill_ratio = self._value_ratio(i)
            fill_w = max(1, int(slider.width * fill_ratio))
            fill_rect = pygame.Rect(slider.left, slider.top, fill_w, slider.height)
            pygame.draw.rect(self.screen, ACCENT_COLOR, fill_rect, border_radius=4)

            knob_x = int(slider.left + fill_ratio * slider.width)
            knob_center = (knob_x, slider.centery)
            pygame.draw.circle(self.screen, (210, 210, 210), knob_center, KNOB_R)
            pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, knob_center, KNOB_R, width=1)

    def _draw_theme_buttons(self) -> None:
        for i, (_theme_id, label, values) in enumerate(self.THEMES):
            rect = self._theme_rects[i]
            hovered = i == self._hover_theme
            bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
            fg = BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR

            pygame.draw.rect(self.screen, bg, rect, border_radius=8)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)

            title = self._value_font.render(label, True, fg)
            self.screen.blit(title, (rect.left + 12, rect.top + 7))

            detail = self._label_font.render(
                f"W {values['width_px']}  Speed {values['speed_px_per_sec']}  Decay {values['decay_speed']}/{values['decay_value']}",
                True,
                MUTED_TEXT_COLOR,
            )
            self.screen.blit(detail, (rect.left + 12, rect.top + 28))

    def _apply_theme(self, theme_index: int) -> None:
        _theme_id, _label, vals = self.THEMES[theme_index]
        self._values.update(vals)
        self._save()

    def _value_ratio(self, index: int) -> float:
        key, _label, min_v, max_v, _step = self._active_fields()[index]
        span = max(1, max_v - min_v)
        return (self._values[key] - min_v) / float(span)

    def _start_preview_trail(self) -> None:
        key_rect = self._preview_key_rect()
        trail = {
            "x": float(key_rect.centerx),
            "top_y": float(key_rect.top),
            "bottom_y": float(key_rect.top),
            "width": float(self._values["width_px"]),
            "released": False,
            "age_ms": 0.0,
        }
        self._preview_active_trail = trail
        self._preview_trails.append(trail)
        NoteEffectRenderer.spawn_sparks(trail, self._values)
        NoteEffectRenderer.spawn_press_smoke(trail, self._values)

    def _release_preview_trail(self) -> None:
        if self._preview_active_trail is not None:
            self._preview_active_trail["released"] = True
            NoteEffectRenderer.spawn_smoke(self._preview_active_trail, self._values)
            self._preview_active_trail = None

    def _anchor_preview_trail(self) -> None:
        if self._preview_active_trail is None:
            return
        key_rect = self._preview_key_rect()
        self._preview_active_trail["x"] = float(key_rect.centerx)
        self._preview_active_trail["bottom_y"] = float(key_rect.top)
        self._preview_active_trail["width"] = float(self._values["width_px"])

    def _preview_key_rect(self) -> pygame.Rect:
        key_w = 42
        key_h = 88
        return pygame.Rect(
            self._preview_rect.centerx - key_w // 2,
            self._preview_rect.bottom - key_h - 14,
            key_w,
            key_h,
        )

    def _draw_preview(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._right_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._right_panel, width=1, border_radius=8)

        pygame.draw.rect(self.screen, PANEL_BG, self._preview_rect, border_radius=8)

        label = self._label_font.render("Live Preview", True, TEXT_COLOR)
        self.screen.blit(label, (self._preview_rect.left + 12, self._preview_rect.top + 10))

        hint = self._value_font.render("1s on, 1s off preview loop", True, MUTED_TEXT_COLOR)
        self.screen.blit(hint, (self._preview_rect.left + 12, self._preview_rect.top + 38))

        key_rect = self._preview_key_rect()
        pygame.draw.rect(self.screen, KEY_COLOR, key_rect, border_radius=4)
        pygame.draw.rect(self.screen, KEY_BORDER, key_rect, width=1, border_radius=4)

        note_style = {
            "color_r": self._values["color_r"],
            "color_g": self._values["color_g"],
            "color_b": self._values["color_b"],
            "interior_r": self._values["interior_r"],
            "interior_g": self._values["interior_g"],
            "interior_b": self._values["interior_b"],
            "outer_edge_width_px": self._values["outer_edge_width_px"],
            "inner_blend_percent": self._values["inner_blend_percent"],
            "glow_strength_percent": self._values["glow_strength_percent"],
            "effect_glow_enabled": self._values["effect_glow_enabled"],
            "effect_highlight_enabled": self._values["effect_highlight_enabled"],
            "effect_sparks_enabled": self._values["effect_sparks_enabled"],
            "effect_smoke_enabled": self._values["effect_smoke_enabled"],
            "effect_press_smoke_enabled": self._values["effect_press_smoke_enabled"],
            "effect_moon_dust_enabled": self._values["effect_moon_dust_enabled"],
            "effect_steam_smoke_enabled": self._values["effect_steam_smoke_enabled"],
            "effect_halo_pulse_enabled": self._values["effect_halo_pulse_enabled"],
            "highlight_strength_percent": self._values["highlight_strength_percent"],
            "spark_amount_percent": self._values["spark_amount_percent"],
            "smoke_amount_percent": self._values["smoke_amount_percent"],
            "press_smoke_amount_percent": self._values["press_smoke_amount_percent"],
            "edge_roundness_px": self._values["edge_roundness_px"],
            "decay_speed": self._values["decay_speed"],
            "decay_value": self._values["decay_value"],
        }
        self._fx_renderer.begin_frame()
        for trail in self._preview_trails:
            self._fx_renderer.draw_trail(trail, note_style, clip_rect=self._preview_rect)
        self._fx_renderer.end_frame()

        # Re-draw borders so they sit on top of any glow bleed
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._right_panel, width=1, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._preview_rect, width=1, border_radius=8)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
