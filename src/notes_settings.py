"""Screen for tuning Freeplay note animation style with live preview."""

from __future__ import annotations

import colorsys
import pygame
from typing import Callable
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
        ("h", "Hue", 0, 360, 5),
        ("s", "Saturation", 0, 100, 5),
        ("v", "Value", 0, 100, 5),
    ]

    COLOR_BLEND_FIELD = ("inner_blend_percent", "Inner/Outer Blend", 0, 100, 5)
    COLOR_EDGE_WIDTH_FIELD = ("outer_edge_width_px", "Outer Edge Width", 1, 8, 1)
    COLOR_GLOW_FIELD = ("glow_strength_percent", "Glow Strength", 0, 180, 5)

    EFFECT_TOGGLES = [
        ("effect_glow_enabled", "Glow"),
        ("effect_highlight_enabled", "Edge Highlight"),
        ("effect_sparks_enabled", "Sparks"),
        ("effect_embers_enabled", "Embers"),
        ("effect_smoke_enabled", "Smoke"),
        ("effect_press_smoke_enabled", "Start Mist"),
        ("effect_moon_dust_enabled", "Moon Dust"),
        ("effect_steam_smoke_enabled", "Steam Wisps"),
        ("effect_halo_pulse_enabled", "Halo Pulse"),
    ]

    EFFECT_FIELDS = [
        ("highlight_strength_percent", "Highlight Strength", 0, 170, 5),
        ("spark_amount_percent", "Spark Amount", 0, 300, 5),
        ("smoke_amount_percent", "Smoke Amount", 0, 300, 5),
        ("press_smoke_amount_percent", "Start Mist Amount", 0, 250, 5),
    ]

    EFFECT_COLOR_SOURCES = {
        "glow_color": "color",
        "highlight_color": "color",
        "spark_color": "color",
        "ember_color": "color",
        "smoke_color": "color",
        "mist_color": "interior",
        "dust_color": "interior",
        "steam_color": "color",
    }

    # Each entry: (toggle_key, display_label, [(slider_key, label, min, max, step), ...])
    EFFECT_SECTIONS: list[tuple[str, str, list]] = [
        ("effect_glow_enabled", "Glow", [
            ("glow_strength_percent", "Glow Strength", 0, 180, 5),
            ("glow_color_h", "Hue", 0, 360, 5),
            ("glow_color_s", "Saturation", 0, 100, 5),
            ("glow_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_highlight_enabled", "Edge Highlight", [
            ("highlight_strength_percent", "Highlight Strength", 0, 170, 5),
            ("highlight_color_h", "Hue", 0, 360, 5),
            ("highlight_color_s", "Saturation", 0, 100, 5),
            ("highlight_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_sparks_enabled", "Sparks", [
            ("spark_amount_percent", "Spark Amount", 0, 300, 5),
            ("spark_color_h", "Hue", 0, 360, 5),
            ("spark_color_s", "Saturation", 0, 100, 5),
            ("spark_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_embers_enabled", "Embers", [
            ("spark_amount_percent", "Spark Amount", 0, 300, 5),
            ("ember_color_h", "Hue", 0, 360, 5),
            ("ember_color_s", "Saturation", 0, 100, 5),
            ("ember_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_smoke_enabled", "Smoke", [
            ("smoke_amount_percent", "Smoke Amount", 0, 300, 5),
            ("smoke_color_h", "Hue", 0, 360, 5),
            ("smoke_color_s", "Saturation", 0, 100, 5),
            ("smoke_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_press_smoke_enabled", "Start Mist", [
            ("press_smoke_amount_percent", "Mist Amount", 0, 250, 5),
            ("mist_color_h", "Hue", 0, 360, 5),
            ("mist_color_s", "Saturation", 0, 100, 5),
            ("mist_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_moon_dust_enabled", "Moon Dust", [
            ("dust_color_h", "Hue", 0, 360, 5),
            ("dust_color_s", "Saturation", 0, 100, 5),
            ("dust_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_steam_smoke_enabled", "Steam Wisps", [
            ("steam_color_h", "Hue", 0, 360, 5),
            ("steam_color_s", "Saturation", 0, 100, 5),
            ("steam_color_v", "Value", 0, 100, 5),
        ]),
        ("effect_halo_pulse_enabled", "Halo Pulse", []),
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
                "effect_embers_enabled": 0,
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
                "effect_embers_enabled": 0,
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
                "effect_embers_enabled": 0,
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
        (
            "ember_storm",
            "Ember Storm",
            {
                "speed_px_per_sec": 420,
                "width_px": 18,
                "edge_roundness_px": 9,
                "outer_edge_width_px": 2,
                "glow_strength_percent": 88,
                "decay_speed": 90,
                "decay_value": 24,
                "inner_blend_percent": 30,
                "effect_glow_enabled": 1,
                "effect_highlight_enabled": 1,
                "effect_sparks_enabled": 1,
                "effect_embers_enabled": 1,
                "effect_smoke_enabled": 0,
                "effect_press_smoke_enabled": 0,
                "effect_moon_dust_enabled": 0,
                "effect_steam_smoke_enabled": 0,
                "effect_halo_pulse_enabled": 0,
                "highlight_strength_percent": 62,
                "spark_amount_percent": 260,
                "smoke_amount_percent": 0,
                "press_smoke_amount_percent": 0,
                "color_r": 246,
                "color_g": 74,
                "color_b": 28,
                "interior_r": 255,
                "interior_g": 178,
                "interior_b": 102,
                "active_theme_id": "ember_storm",
                "experimental_claire_script_enabled": 0,
            },
        ),
    ]

    def __init__(
        self,
        screen: pygame.Surface,
        on_change: Callable[[str, dict[str, int | str]], None] | None = None,
    ) -> None:
        self.screen = screen
        self._on_change = on_change
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values = {}
        self._hover_back = False
        self._hover_slider = -1
        self._drag_slider = -1
        self._drag_color = None  # (channel, outer|inner)

        self._active_layer = "motion"
        self._hover_layer = None
        self._hover_theme = -1
        self._cursor: int = 0

        self._title_pos = (0, 0)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._preview_rect = pygame.Rect(0, 0, 0, 0)
        self._row_rects = []
        self._slider_rects = []
        self._layer_rects = {}
        self._theme_rects = []
        self._effect_toggle_rects = []

        # Per-section accordion state (effects layer)
        self._effect_expanded: dict[str, bool] = {}
        self._effect_section_header_rects: list[pygame.Rect] = []
        self._effect_section_checkbox_rects: list[pygame.Rect] = []
        self._eff_row_rects: list[pygame.Rect] = []
        self._eff_slider_rects: list[pygame.Rect] = []
        # (section_index, key, min_v, max_v, step)
        self._eff_slider_meta: list[tuple[int, str, int, int, int]] = []
        self._eff_hover_header: int = -1
        self._eff_hover_slider: int = -1
        self._eff_drag_slider: int = -1

        self._preview_trails = []
        self._preview_active_trail = None
        self._preview_cycle_ms = 0
        self._preview_was_on = False
        # Dedicated off-screen surface for the preview panel so bloom/glow is
        # contained and never bleeds across the rest of the settings UI.
        self._preview_surf = None
        self._preview_fx_renderer = None

        # Channel selector state
        self._channels = [str(i) for i in range(1, 17)]
        self._selected_channel = "1"
        self._dropdown_open = False
        self._dropdown_rect = None
        self._dropdown_item_rects = []
        self._show_theme_save_button: bool = False
        self._theme_save_rect = pygame.Rect(0, 0, 120, 38)
        self._hover_theme_save: bool = False

        self._load()
        self._build_layout()
        self._sync_cursor_hover()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        # Dropdown channel selector events
        if event.type == pygame.MOUSEMOTION and self._show_theme_save_button:
            self._hover_theme_save = self._theme_save_rect.collidepoint(event.pos)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._show_theme_save_button and self._theme_save_rect.collidepoint(event.pos):
                return "save_theme"
            if self._dropdown_rect and self._dropdown_rect.collidepoint(event.pos):
                self._dropdown_open = not self._dropdown_open
                return None
            if self._dropdown_open:
                for i, rect in enumerate(self._dropdown_item_rects):
                    if rect.collidepoint(event.pos):
                        self._selected_channel = self._channels[i]
                        self._dropdown_open = False
                        self._load()
                        self._build_layout()
                        return None
                self._dropdown_open = False
        if event.type == pygame.MOUSEMOTION:
            if self._drag_color is not None:
                channel, role = self._drag_color
                self._set_color_knob_from_x(channel, role, event.pos[0])
            elif self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            elif self._eff_drag_slider >= 0:
                self._set_eff_slider_from_x(self._eff_drag_slider, event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "back"
            n = self._nav_row_count()
            if event.key == pygame.K_UP:
                self._cursor = (self._cursor - 1) % (n + 2)
                self._sync_cursor_hover()
                return None
            if event.key == pygame.K_DOWN:
                self._cursor = (self._cursor + 1) % (n + 2)
                self._sync_cursor_hover()
                return None
            if event.key == pygame.K_LEFT:
                self._step_cursor(delta=-1)
                return None
            if event.key == pygame.K_RIGHT:
                self._step_cursor(delta=1)
                return None
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                result = self._confirm_cursor()
                if result is not None:
                    return result
                return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            for layer, _label in self.LAYERS:
                if self._layer_rects[layer].collidepoint(event.pos):
                    if self._active_layer != layer:
                        self._active_layer = layer
                        self._build_layer_rows()
                        self._cursor = 0
                        self._sync_cursor_hover()
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
                # Check effect slider drags first
                for i, srect in enumerate(self._eff_slider_rects):
                    if srect.inflate(0, 18).collidepoint(event.pos):
                        self._eff_drag_slider = i
                        self._set_eff_slider_from_x(i, event.pos[0])
                        return None
                # Check section headers: checkbox toggles, rest of header expands/collapses
                for i, hrect in enumerate(self._effect_section_header_rects):
                    if hrect.collidepoint(event.pos):
                        key, _label, fields = self.EFFECT_SECTIONS[i]
                        if self._effect_section_checkbox_rects[i].collidepoint(event.pos):
                            self._values[key] = 0 if int(self._values[key]) else 1
                            self._save()
                        elif fields:
                            self._effect_expanded[key] = not self._effect_expanded.get(key, False)
                            self._build_layer_rows()
                        return None

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1
            self._drag_color = None
            self._eff_drag_slider = -1

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
            if float(trail["bottom_y"]) > 0:  # surface-relative: 0 is top of preview
                survivors.append(trail)
        self._preview_trails = survivors

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_rows()
        self._draw_preview()
        self._draw_back()
        # Draw dropdown last so it renders on top of all other UI
        self._draw_channel_dropdown()

    def _draw_channel_dropdown(self) -> None:
        """Draws the channel selector dropdown at the top-right of the screen."""
        sr = self.screen.get_rect()
        w, h = 160, 38
        x = sr.right - w - 16
        y = 16
        rect = pygame.Rect(x, y, w, h)
        self._dropdown_rect = rect
        pygame.draw.rect(self.screen, BUTTON_NORMAL_BG, rect, border_radius=7)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=7)
        label = f"Channel: {self._selected_channel}"
        surf = self._btn_font.render(label, True, BUTTON_TEXT_COLOR)
        self.screen.blit(surf, surf.get_rect(center=rect.center))
        # Draw dropdown arrow
        arrow_x = rect.right - 22
        arrow_y = rect.centery
        pygame.draw.polygon(
            self.screen,
            BUTTON_TEXT_COLOR,
            [(arrow_x - 8, arrow_y - 4), (arrow_x + 8, arrow_y - 4), (arrow_x, arrow_y + 6)]
        )

        if self._show_theme_save_button:
            save_w = 120
            save_x = x - save_w - 12
            self._theme_save_rect = pygame.Rect(save_x, y, save_w, h)
            save_bg = BUTTON_HOVER_BG if self._hover_theme_save else BUTTON_NORMAL_BG
            save_fg = BUTTON_HOVER_TEXT_COLOR if self._hover_theme_save else BUTTON_TEXT_COLOR
            pygame.draw.rect(self.screen, save_bg, self._theme_save_rect, border_radius=7)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._theme_save_rect, width=1, border_radius=7)
            save_surf = self._btn_font.render("Save Theme", True, save_fg)
            self.screen.blit(save_surf, save_surf.get_rect(center=self._theme_save_rect.center))

        # Draw dropdown items if open
        self._dropdown_item_rects = []
        if self._dropdown_open:
            item_h = h
            for i, ch in enumerate(self._channels):
                item_rect = pygame.Rect(x, y + h + i * item_h, w, item_h)
                self._dropdown_item_rects.append(item_rect)
                bg = ACCENT_COLOR if ch == self._selected_channel else BUTTON_NORMAL_BG
                fg = (255, 255, 255) if ch == self._selected_channel else BUTTON_TEXT_COLOR
                pygame.draw.rect(self.screen, bg, item_rect, border_radius=7)
                pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, item_rect, width=1, border_radius=7)
                ch_surf = self._btn_font.render(f"Channel: {ch}", True, fg)
                self.screen.blit(ch_surf, ch_surf.get_rect(center=item_rect.center))

    def _load(self) -> None:
        all_styles = cfg.load().get("note_style", {})
        data = all_styles.get(self._selected_channel, {})
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
            "effect_embers_enabled": int(bool(data.get("effect_embers_enabled", 0))),
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
        self._ensure_color_models(data)

    def _save(self) -> None:
        self._sync_hsv_to_rgb_values()
        data = cfg.load()
        all_styles = data.setdefault("note_style", {})
        all_styles[self._selected_channel] = dict(self._values)
        data["note_style"] = all_styles
        cfg.save(data)
        if self._on_change is not None:
            self._on_change(self._selected_channel, dict(self._values))

    @staticmethod
    def _rgb_to_hsv_int(r: int, g: int, b: int) -> tuple[int, int, int]:
        hue, sat, val = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        return (
            max(0, min(360, int(round(hue * 360.0)))),
            max(0, min(100, int(round(sat * 100.0)))),
            max(0, min(100, int(round(val * 100.0)))),
        )

    @staticmethod
    def _hsv_to_rgb_int(h: int, s: int, v: int) -> tuple[int, int, int]:
        rgb = colorsys.hsv_to_rgb((h % 360) / 360.0, s / 100.0, v / 100.0)
        return tuple(max(0, min(255, int(round(channel * 255.0)))) for channel in rgb)

    @classmethod
    def _color_axis_spec(cls, channel: str) -> tuple[str, int, int, int]:
        for key, label, min_v, max_v, step in cls.COLOR_CHANNELS:
            if key == channel:
                return label, min_v, max_v, step
        raise KeyError(channel)

    def _color_prefix_defaults(self) -> list[tuple[str, tuple[int, int, int]]]:
        outer_rgb = (
            int(self._values.get("color_r", 0)),
            int(self._values.get("color_g", 230)),
            int(self._values.get("color_b", 230)),
        )
        inner_rgb = (
            int(self._values.get("interior_r", 120)),
            int(self._values.get("interior_g", 255)),
            int(self._values.get("interior_b", 255)),
        )
        color_defaults = [("color", outer_rgb), ("interior", inner_rgb)]
        for prefix, source in self.EFFECT_COLOR_SOURCES.items():
            color_defaults.append((prefix, inner_rgb if source == "interior" else outer_rgb))
        return color_defaults

    def _ensure_color_models(self, source: dict) -> None:
        for prefix, default_rgb in self._color_prefix_defaults():
            rgb_keys = [f"{prefix}_r", f"{prefix}_g", f"{prefix}_b"]
            hsv_keys = [f"{prefix}_h", f"{prefix}_s", f"{prefix}_v"]
            rgb = tuple(int(source.get(key, self._values.get(key, default_rgb[idx]))) for idx, key in enumerate(rgb_keys))
            if any(key in source for key in hsv_keys):
                derived_hsv = self._rgb_to_hsv_int(*rgb)
                hsv = tuple(int(source.get(key, derived_hsv[idx])) for idx, key in enumerate(hsv_keys))
                rgb = self._hsv_to_rgb_int(*hsv)
            else:
                hsv = self._rgb_to_hsv_int(*rgb)

            for idx, key in enumerate(rgb_keys):
                self._values[key] = rgb[idx]
            for idx, key in enumerate(hsv_keys):
                self._values[key] = hsv[idx]

    def _sync_hsv_to_rgb_values(self) -> None:
        for prefix, default_rgb in self._color_prefix_defaults():
            fallback_hsv = self._rgb_to_hsv_int(*default_rgb)
            hsv = (
                int(self._values.get(f"{prefix}_h", fallback_hsv[0])),
                int(self._values.get(f"{prefix}_s", fallback_hsv[1])),
                int(self._values.get(f"{prefix}_v", fallback_hsv[2])),
            )
            rgb = self._hsv_to_rgb_int(*hsv)
            self._values[f"{prefix}_r"] = rgb[0]
            self._values[f"{prefix}_g"] = rgb[1]
            self._values[f"{prefix}_b"] = rgb[2]

    @staticmethod
    def _is_hsv_key(key: str) -> bool:
        return key.endswith(("_h", "_s", "_v")) and (key.startswith(("color_", "interior_")) or "_color_" in key)

    def _format_color_value(self, key: str, value: int) -> str:
        if not self._is_hsv_key(key):
            return str(value)
        if key.endswith("_h"):
            return f"{value}deg"
        return f"{value}%"

    def _draw_hsv_axis_track(self, rect: pygame.Rect, axis: str, reference_hsv: tuple[int, int, int], hovered: bool) -> None:
        track_bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, track_bg, rect, border_radius=4)
        strips = max(18, rect.width // 5)
        hue, sat, val = reference_hsv
        for strip_idx in range(strips):
            t0 = strip_idx / float(strips)
            t1 = (strip_idx + 1) / float(strips)
            sample = (t0 + t1) * 0.5
            if axis == "h":
                sample_rgb = self._hsv_to_rgb_int(int(round(sample * 360.0)), 100, 100)
            elif axis == "s":
                sample_rgb = self._hsv_to_rgb_int(hue, int(round(sample * 100.0)), max(12, val))
            else:
                sample_rgb = self._hsv_to_rgb_int(hue, sat, int(round(sample * 100.0)))
            x0 = rect.left + int(t0 * rect.width)
            x1 = rect.left + int(t1 * rect.width)
            pygame.draw.rect(self.screen, sample_rgb, pygame.Rect(x0, rect.top, max(1, x1 - x0), rect.height))
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=4)

    def _build_preview_note_style(self) -> dict[str, int]:
        self._sync_hsv_to_rgb_values()
        return {
            "color_r": self._values["color_r"],
            "color_g": self._values["color_g"],
            "color_b": self._values["color_b"],
            "interior_r": self._values["interior_r"],
            "interior_g": self._values["interior_g"],
            "interior_b": self._values["interior_b"],
            "glow_color_r": self._values["glow_color_r"],
            "glow_color_g": self._values["glow_color_g"],
            "glow_color_b": self._values["glow_color_b"],
            "highlight_color_r": self._values["highlight_color_r"],
            "highlight_color_g": self._values["highlight_color_g"],
            "highlight_color_b": self._values["highlight_color_b"],
            "spark_color_r": self._values["spark_color_r"],
            "spark_color_g": self._values["spark_color_g"],
            "spark_color_b": self._values["spark_color_b"],
            "ember_color_r": self._values["ember_color_r"],
            "ember_color_g": self._values["ember_color_g"],
            "ember_color_b": self._values["ember_color_b"],
            "smoke_color_r": self._values["smoke_color_r"],
            "smoke_color_g": self._values["smoke_color_g"],
            "smoke_color_b": self._values["smoke_color_b"],
            "mist_color_r": self._values["mist_color_r"],
            "mist_color_g": self._values["mist_color_g"],
            "mist_color_b": self._values["mist_color_b"],
            "dust_color_r": self._values["dust_color_r"],
            "dust_color_g": self._values["dust_color_g"],
            "dust_color_b": self._values["dust_color_b"],
            "steam_color_r": self._values["steam_color_r"],
            "steam_color_g": self._values["steam_color_g"],
            "steam_color_b": self._values["steam_color_b"],
            "outer_edge_width_px": self._values["outer_edge_width_px"],
            "inner_blend_percent": self._values["inner_blend_percent"],
            "glow_strength_percent": self._values["glow_strength_percent"],
            "effect_glow_enabled": self._values["effect_glow_enabled"],
            "effect_highlight_enabled": self._values["effect_highlight_enabled"],
            "effect_sparks_enabled": self._values["effect_sparks_enabled"],
            "effect_embers_enabled": self._values["effect_embers_enabled"],
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

        # Create/resize the off-screen preview surface so bloom stays inside it.
        pw, ph = self._preview_rect.width, self._preview_rect.height
        if pw > 0 and ph > 0:
            self._preview_surf = pygame.Surface((pw, ph))
            # bloom_downscale=0 disables the full-surface bloom pass in the preview;
            # the glow rings in _fx_surf look correct without it on a small surface.
            self._preview_fx_renderer = NoteEffectRenderer(self._preview_surf, bloom_downscale=0)

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
            [(f"color_{c}", label, min_v, max_v, step) for c, label, min_v, max_v, step in self.COLOR_CHANNELS]
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
            _HEADER_H = 40
            _SLIDER_ROW_H = 46
            _GAP = 6
            _INDENT = 20
            self._effect_section_header_rects = []
            self._effect_section_checkbox_rects = []
            self._eff_row_rects = []
            self._eff_slider_rects = []
            self._eff_slider_meta = []
            for idx, (key, _label, fields) in enumerate(self.EFFECT_SECTIONS):
                header = pygame.Rect(self._left_panel.left + 12, y, row_w, _HEADER_H)
                self._effect_section_header_rects.append(header)
                cb = pygame.Rect(header.left + 10, header.centery - 9, 18, 18)
                self._effect_section_checkbox_rects.append(cb)
                y += _HEADER_H + _GAP
                if self._effect_expanded.get(key, False):
                    for fkey, _flabel, fmin, fmax, fstep in fields:
                        rx = self._left_panel.left + 12 + _INDENT
                        rw = row_w - _INDENT
                        row_rect = pygame.Rect(rx, y, rw, _SLIDER_ROW_H)
                        slider_rect = pygame.Rect(
                            row_rect.left + 4,
                            row_rect.bottom - 14,
                            row_rect.width - 8,
                            SLIDER_H,
                        )
                        self._eff_row_rects.append(row_rect)
                        self._eff_slider_rects.append(slider_rect)
                        self._eff_slider_meta.append((idx, fkey, fmin, fmax, fstep))
                        y += _SLIDER_ROW_H + 4
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
            self._eff_hover_header = -1
            self._eff_hover_slider = -1
            for i, rect in enumerate(self._effect_section_header_rects):
                if rect.collidepoint(pos):
                    self._eff_hover_header = i
                    break
            for i, rect in enumerate(self._eff_slider_rects):
                if rect.inflate(0, 18).collidepoint(pos):
                    self._eff_hover_slider = i
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
        _label, min_v, max_v, _step = self._color_axis_spec(channel)
        span = max(1, max_v - min_v)
        outer_x = rect.left + int(((outer_v - min_v) / float(span)) * rect.width)
        inner_x = rect.left + int(((inner_v - min_v) / float(span)) * rect.width)
        return outer_x, inner_x

    def _set_color_knob_from_x(self, channel: str, role: str, mouse_x: int) -> None:
        rect = self._slider_rects[[c for c, *_ in self.COLOR_CHANNELS].index(channel)]
        if rect.width <= 1:
            return

        _label, min_v, max_v, step = self._color_axis_spec(channel)
        ratio = (mouse_x - rect.left) / float(rect.width)
        ratio = max(0.0, min(1.0, ratio))
        raw_value = min_v + ratio * (max_v - min_v)
        new_v = int(round(raw_value / step) * step)
        new_v = max(min_v, min(max_v, new_v))

        key = f"color_{channel}" if role == "outer" else f"interior_{channel}"
        if new_v == self._values[key]:
            return
        self._values[key] = new_v
        self._save()

    def _nav_row_count(self) -> int:
        if self._active_layer == "motion":
            return len(self.MOTION_FIELDS)
        if self._active_layer == "shape":
            return len(self.SHAPE_FIELDS)
        if self._active_layer == "color":
            return len(self._active_fields())
        if self._active_layer == "effects":
            return len(self.EFFECT_SECTIONS)
        if self._active_layer == "themes":
            return len(self.THEMES)
        return 0

    def _sync_cursor_hover(self) -> None:
        self._hover_back = False
        self._hover_slider = -1
        self._hover_theme = -1
        self._eff_hover_header = -1
        n = self._nav_row_count()
        if self._cursor == n + 1:
            self._hover_back = True
        elif 1 <= self._cursor <= n:
            row_idx = self._cursor - 1
            if self._active_layer == "themes":
                self._hover_theme = row_idx
            elif self._active_layer == "effects":
                self._eff_hover_header = row_idx
            else:
                self._hover_slider = row_idx

    def _step_cursor(self, delta: int) -> None:
        if self._cursor == 0:
            layers = [la for la, _ in self.LAYERS]
            idx = layers.index(self._active_layer) if self._active_layer in layers else 0
            idx = (idx + delta) % len(layers)
            self._active_layer = layers[idx]
            self._build_layer_rows()
            self._cursor = 0
            self._sync_cursor_hover()
        else:
            self._step_cursor_row(self._cursor - 1, delta)

    def _step_cursor_row(self, row_idx: int, delta: int) -> None:
        if self._active_layer == "effects":
            if row_idx < len(self.EFFECT_SECTIONS):
                key, _label, fields = self.EFFECT_SECTIONS[row_idx]
                if fields:
                    # Step the first slider of the section when left/right pressed
                    if self._effect_expanded.get(key, False):
                        fkey, _fl, fmin, fmax, fstep = fields[0]
                        cur_v = int(self._values.get(fkey, fmin))
                        new_v = max(fmin, min(fmax, cur_v + delta * fstep))
                        if new_v != cur_v:
                            self._values[fkey] = new_v
                            self._save()
                else:
                    cur = int(self._values.get(key, 0))
                    self._values[key] = 0 if cur else 1
                    self._save()
        elif self._active_layer == "color":
            fields = self._active_fields()
            if row_idx < len(fields):
                key, _lbl, min_v, max_v, step = fields[row_idx]
                cur_v = int(self._values.get(key, min_v))
                new_v = max(min_v, min(max_v, cur_v + delta * step))
                if new_v != cur_v:
                    self._values[key] = new_v
                    self._save()
        elif self._active_layer != "themes":
            fields = self._active_fields()
            if row_idx < len(fields):
                key, _lbl, min_v, max_v, step = fields[row_idx]
                cur_v = int(self._values.get(key, min_v))
                new_v = max(min_v, min(max_v, cur_v + delta * step))
                if new_v != cur_v:
                    self._values[key] = new_v
                    self._save()

    def _confirm_cursor(self) -> str | None:
        n = self._nav_row_count()
        if self._cursor == n + 1:
            return "back"
        if 1 <= self._cursor <= n:
            row_idx = self._cursor - 1
            if self._active_layer == "themes":
                self._apply_theme(row_idx)
            elif self._active_layer == "effects" and row_idx < len(self.EFFECT_SECTIONS):
                key, _label, fields = self.EFFECT_SECTIONS[row_idx]
                if fields:
                    self._effect_expanded[key] = not self._effect_expanded.get(key, False)
                    self._build_layer_rows()
                else:
                    self._values[key] = 0 if int(self._values[key]) else 1
                    self._save()
        return None

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
                    outer_rgb = (
                        self._values["color_r"],
                        self._values["color_g"],
                        self._values["color_b"],
                    )
                    inner_rgb = (
                        self._values["interior_r"],
                        self._values["interior_g"],
                        self._values["interior_b"],
                    )
                    outer_hsv = (
                        self._values["color_h"],
                        self._values["color_s"],
                        self._values["color_v"],
                    )
                    inner_hsv = (
                        self._values["interior_h"],
                        self._values["interior_s"],
                        self._values["interior_v"],
                    )
                    ref_hsv = (
                        int((outer_hsv[0] + inner_hsv[0]) * 0.5),
                        int((outer_hsv[1] + inner_hsv[1]) * 0.5),
                        int((outer_hsv[2] + inner_hsv[2]) * 0.5),
                    )

                    label_surf = self._label_font.render(f"{label}  (Outer / Inner)", True, TEXT_COLOR)
                    self.screen.blit(label_surf, (row.left + 10, row.top + 6))

                    value_surf = self._value_font.render(
                        f"{self._format_color_value(f'color_{channel}', outer_v)} / {self._format_color_value(f'interior_{channel}', inner_v)}",
                        True,
                        MUTED_TEXT_COLOR,
                    )
                    self.screen.blit(value_surf, value_surf.get_rect(topright=(row.right - 10, row.top + 8)))

                    self._draw_hsv_axis_track(slider, channel, ref_hsv, i == self._hover_slider or i == self._drag_slider)

                    outer_x, inner_x = self._color_knob_positions(channel, slider)
                    outer_center = (outer_x, slider.centery)
                    inner_center = (inner_x, slider.centery)

                    pygame.draw.circle(self.screen, outer_rgb, outer_center, KNOB_R)
                    pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, outer_center, KNOB_R, width=1)
                    pygame.draw.circle(self.screen, inner_rgb, inner_center, KNOB_R)
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

    def _set_eff_slider_from_x(self, index: int, mouse_x: int) -> None:
        """Adjust the value of an effects-accordion slider from a mouse x position."""
        if index >= len(self._eff_slider_rects) or index >= len(self._eff_slider_meta):
            return
        rect = self._eff_slider_rects[index]
        _sec_idx, key, min_v, max_v, step = self._eff_slider_meta[index]
        if rect.width <= 1:
            return
        ratio = max(0.0, min(1.0, (mouse_x - rect.left) / float(rect.width)))
        raw = min_v + ratio * (max_v - min_v)
        new_v = max(min_v, min(max_v, int(round(raw / step) * step)))
        if new_v == self._values.get(key, min_v):
            return
        self._values[key] = new_v
        self._save()

    def _draw_effect_rows(self) -> None:
        # Clipping region — stop drawing below the left-panel bottom edge.
        clip_bottom = self._left_panel.bottom - 6

        for i, (key, label, fields) in enumerate(self.EFFECT_SECTIONS):
            if i >= len(self._effect_section_header_rects):
                break
            header = self._effect_section_header_rects[i]
            if header.top > clip_bottom:
                break

            expanded = self._effect_expanded.get(key, False)
            hovered = i == self._eff_hover_header
            enabled = bool(int(self._values.get(key, 0)))

            # ── Header background ──────────────────────────────────────────
            if hovered:
                header_bg = BUTTON_HOVER_BG
            elif expanded:
                header_bg = (28, 28, 42)
            else:
                header_bg = BG_COLOR
            pygame.draw.rect(self.screen, header_bg, header, border_radius=6)
            left_edge_color = ACCENT_COLOR if enabled else BUTTON_BORDER_COLOR
            pygame.draw.rect(self.screen, left_edge_color, header, width=1, border_radius=6)

            # ── Checkbox ───────────────────────────────────────────────────
            cb = self._effect_section_checkbox_rects[i]
            pygame.draw.rect(self.screen, (35, 35, 45), cb, border_radius=4)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, cb, width=1, border_radius=4)
            if enabled:
                pygame.draw.rect(self.screen, ACCENT_COLOR, cb.inflate(-6, -6), border_radius=2)

            # ── Label ──────────────────────────────────────────────────────
            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (cb.right + 10, header.top + (header.height - label_surf.get_height()) // 2))

            # ── ON/OFF tag ─────────────────────────────────────────────────
            state_color = ACCENT_COLOR if enabled else MUTED_TEXT_COLOR
            state_surf = self._value_font.render("ON" if enabled else "OFF", True, state_color)
            state_x = header.right - state_surf.get_width() - (36 if fields else 14)
            self.screen.blit(state_surf, (state_x, header.top + (header.height - state_surf.get_height()) // 2))

            # ── Expand arrow (only for sections that have sliders) ─────────
            if fields:
                arrow_cx = header.right - 16
                arrow_cy = header.centery
                if expanded:
                    pts = [(arrow_cx - 6, arrow_cy + 3), (arrow_cx + 6, arrow_cy + 3), (arrow_cx, arrow_cy - 4)]
                else:
                    pts = [(arrow_cx - 4, arrow_cy - 6), (arrow_cx - 4, arrow_cy + 6), (arrow_cx + 4, arrow_cy)]
                pygame.draw.polygon(self.screen, MUTED_TEXT_COLOR, pts)

        # ── Expanded slider rows ───────────────────────────────────────────
        for i, (row_rect, slider_rect) in enumerate(zip(self._eff_row_rects, self._eff_slider_rects)):
            if row_rect.top > clip_bottom:
                break
            _sec_idx, key, min_v, max_v, _step = self._eff_slider_meta[i]
            val = int(self._values.get(key, min_v))
            span = max(1, max_v - min_v)
            ratio = max(0.0, min(1.0, (val - min_v) / float(span)))

            hovered = i == self._eff_hover_slider or i == self._eff_drag_slider

            # Find label from section fields
            sec_key, _sec_label, fields = self.EFFECT_SECTIONS[_sec_idx]
            field_label = key
            for fkey, flabel, *_ in fields:
                if fkey == key:
                    field_label = flabel
                    break

            pygame.draw.rect(self.screen, (20, 20, 30), row_rect, border_radius=5)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row_rect, width=1, border_radius=5)

            lbl_surf = self._label_font.render(field_label, True, MUTED_TEXT_COLOR)
            self.screen.blit(lbl_surf, (row_rect.left + 10, row_rect.top + 6))

            if self._is_hsv_key(key):
                val_text = self._format_color_value(key, val)
            else:
                val_text = f"{val}%"
            val_surf = self._value_font.render(val_text, True, TEXT_COLOR)
            self.screen.blit(val_surf, val_surf.get_rect(topright=(row_rect.right - 10, row_rect.top + 8)))

            if self._is_hsv_key(key):
                prefix = key[:-2]
                ref_hsv = (
                    int(self._values.get(f"{prefix}_h", 0)),
                    int(self._values.get(f"{prefix}_s", 100)),
                    int(self._values.get(f"{prefix}_v", 100)),
                )
                swatch_rect = pygame.Rect(row_rect.right - 42, row_rect.top + 8, 18, 18)
                self._draw_hsv_axis_track(slider_rect, key[-1], ref_hsv, hovered)
                pygame.draw.rect(self.screen, self._hsv_to_rgb_int(*ref_hsv), swatch_rect, border_radius=4)
                pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, swatch_rect, width=1, border_radius=4)
            else:
                track_col = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
                pygame.draw.rect(self.screen, track_col, slider_rect, border_radius=4)
                pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, slider_rect, width=1, border_radius=4)
                fill_w = max(1, int(slider_rect.width * ratio))
                pygame.draw.rect(self.screen, ACCENT_COLOR, pygame.Rect(slider_rect.left, slider_rect.top, fill_w, slider_rect.height), border_radius=4)
            knob_x = int(slider_rect.left + ratio * slider_rect.width)
            pygame.draw.circle(self.screen, (210, 210, 210), (knob_x, slider_rect.centery), KNOB_R)
            pygame.draw.circle(self.screen, BUTTON_BORDER_COLOR, (knob_x, slider_rect.centery), KNOB_R, width=1)

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
        self._ensure_color_models(vals)
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
        """Return key rect in preview-surface–relative coordinates."""
        key_w = 42
        key_h = 88
        pw = self._preview_rect.width
        ph = self._preview_rect.height
        return pygame.Rect(
            pw // 2 - key_w // 2,
            ph - key_h - 14,
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

        if self._preview_surf is None or self._preview_fx_renderer is None:
            return

        # Clear the off-screen surface and draw the key into it.
        self._preview_surf.fill(PANEL_BG)
        key_rect = self._preview_key_rect()  # surface-relative
        pygame.draw.rect(self._preview_surf, KEY_COLOR, key_rect, border_radius=4)
        pygame.draw.rect(self._preview_surf, KEY_BORDER, key_rect, width=1, border_radius=4)

        note_style = self._build_preview_note_style()
        self._preview_fx_renderer.begin_frame()
        for trail in self._preview_trails:
            # No clip_rect needed — the surface is already the preview size.
            self._preview_fx_renderer.draw_trail(trail, note_style)
        self._preview_fx_renderer.end_frame()

        # Blit the fully-composited preview surface onto the screen.
        self.screen.blit(self._preview_surf, self._preview_rect.topleft)

        # Re-draw borders so they sit on top of any glow bleed.
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._right_panel, width=1, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._preview_rect, width=1, border_radius=8)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
