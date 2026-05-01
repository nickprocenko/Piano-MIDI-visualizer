"""Screen for tuning Freeplay note animation style with live preview."""

from __future__ import annotations

import pygame
from src import config as cfg
from src.note_fx import NoteEffectRenderer
import src.performance_store as perf_store

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
DELETE_BUTTON_BG = (58, 25, 25)
DELETE_BUTTON_HOVER_BG = (95, 38, 38)
DELETE_BUTTON_TEXT_COLOR = (220, 140, 140)
DELETE_BUTTON_HOVER_TEXT_COLOR = (255, 180, 180)
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
STYLE_ACTION_BTN_H = 44
STYLE_ACTION_BTN_GAP = 10

PANEL_MARGIN_X = 26
PANEL_GAP = 16

_PREVIEW_ON_MS = 1000
_PREVIEW_OFF_MS = 1000
_PREVIEW_PARTICLE_HEIGHT_PX = 32


def _strip_legacy_note_automation(note_style: dict[str, int | str]) -> dict[str, int | str]:
    cleaned = dict(note_style)
    cleaned["active_theme_id"] = "custom"
    cleaned["experimental_claire_script_enabled"] = 0
    return cleaned


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
    COLOR_EDGE_WIDTH_FIELD = ("outer_edge_width_px", "Outer Edge Width", 0, 8, 1)
    COLOR_GLOW_FIELD = ("glow_strength_percent", "Glow Strength", 0, 180, 5)

    EFFECT_TOGGLES = [
        ("effect_glow_enabled", "Glow"),
        ("effect_highlight_enabled", "Edge Highlight"),
        ("effect_sparks_enabled", "Sparks"),
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

    LAYERS = [
        ("motion", "MOTION"),
        ("shape", "SHAPE"),
        ("color", "COLOR"),
        ("effects", "EFFECTS"),
        ("styles", "STYLES"),
    ]

    # Slide palette for Claire De Lune: 5 moonlit colour scenes tied to slideshow slides.
    # Each entry sets note outer/interior colours and LED white/black key colours.
    CLAIRE_DE_LUNE_PALETTE: list[dict[str, int]] = [
        # 1 — Moonlight (opening)
        {"color_r": 86,  "color_g": 128, "color_b": 220,
         "interior_r": 180, "interior_g": 210, "interior_b": 255,
         "active_r": 40,  "active_g": 90,  "active_b": 200,
         "black_r": 20,  "black_g": 60,  "black_b": 180},
        # 2 — Sapphire depths (development)
        {"color_r": 30,  "color_g": 70,  "color_b": 200,
         "interior_r": 100, "interior_g": 140, "interior_b": 240,
         "active_r": 0,   "active_g": 60,  "active_b": 200,
         "black_r": 0,   "black_g": 40,  "black_b": 170},
        # 3 — Violet cascade (climax)
        {"color_r": 110, "color_g": 55,  "color_b": 195,
         "interior_r": 185, "interior_g": 140, "interior_b": 255,
         "active_r": 90,  "active_g": 40,  "active_b": 185,
         "black_r": 120, "black_g": 30,  "black_b": 200},
        # 4 — Pearl shimmer (recapitulation)
        {"color_r": 160, "color_g": 190, "color_b": 255,
         "interior_r": 215, "interior_g": 230, "interior_b": 255,
         "active_r": 120, "active_g": 155, "active_b": 220,
         "black_r": 140, "black_g": 175, "black_b": 240},
        # 5 — Dawn fade (coda)
        {"color_r": 55,  "color_g": 105, "color_b": 210,
         "interior_r": 145, "interior_g": 185, "interior_b": 255,
         "active_r": 30,  "active_g": 80,  "active_b": 200,
         "black_r": 10,  "black_g": 60,  "black_b": 175},
    ]

    CHANNEL_LABELS = [f"Channel {i}" for i in range(1, 17)]

    def __init__(
        self,
        screen: pygame.Surface,
        performance_id: str = "",
        theme_index: int = -1,
        selected_channel: int = 0,
    ) -> None:
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

        self._left_content_scroll: int = 0
        self._active_layer = "motion"
        self._hover_layer: str | None = None
        self._hover_style: int = -1
        self._hover_style_load: int = -1
        self._hover_style_delete: int = -1
        self._hover_save_style = False
        self._editing_style_index: int = -1
        self._editing_style_text: str = ""

        self._title_pos = (0, 0)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._preview_rect = pygame.Rect(0, 0, 0, 0)
        self._row_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect] = []
        self._layer_rects: dict[str, pygame.Rect] = {}
        self._style_row_rects: list[pygame.Rect] = []
        self._style_load_rects: list[pygame.Rect] = []
        self._style_delete_rects: list[pygame.Rect] = []
        self._effect_toggle_rects: list[pygame.Rect] = []
        self._save_style_rect = pygame.Rect(0, 0, 0, 0)
        self._saved_styles: list[dict[str, int | str]] = []
        self._active_saved_style_index: int = -1

        self._preview_trails: list[dict[str, float | bool]] = []
        self._preview_active_trail: dict[str, float | bool] | None = None
        self._preview_cycle_ms = 0
        self._preview_was_on = False
        # Dedicated off-screen surface for the preview panel so bloom/glow is
        # contained and never bleeds across the rest of the settings UI.
        self._preview_surf: pygame.Surface | None = None
        self._preview_fx_renderer: NoteEffectRenderer | None = None
        self._performance_id = performance_id
        self._theme_index = theme_index
        self._selected_channel = max(0, min(15, selected_channel))
        self._selected_cue = 0
        self._channel_dropdown_open = False
        self._cue_dropdown_open = False
        self._hover_cue = False
        self._hover_cue_option = -1
        self._cue_rect = pygame.Rect(0, 0, 0, 0)
        self._cue_option_rects: list[pygame.Rect] = []
        self._hover_channel = False
        self._hover_channel_option = -1
        self._channel_rect = pygame.Rect(0, 0, 0, 0)
        self._channel_option_rects: list[pygame.Rect] = []
        self._status_text = ""
        self._status_until_ms = 0
        self._channel_status_text = ""

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

        if event.type == pygame.KEYDOWN:
            if self._editing_style_index >= 0:
                return self._handle_style_edit_key(event)
            if event.key == pygame.K_ESCAPE:
                return "back"

        if event.type == pygame.MOUSEWHEEL:
            if self._left_panel.collidepoint(pygame.mouse.get_pos()):
                self._do_left_scroll(-event.y * 30)
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._editing_style_index >= 0:
                idx = self._editing_style_index
                if (
                    idx >= len(self._style_row_rects)
                    or not self._style_row_rects[idx].collidepoint(event.pos)
                ):
                    self._commit_style_edit()

            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._has_theme_channel_context():
                if self._has_style_sync_context() and self._cue_rect.collidepoint(event.pos):
                    self._cue_dropdown_open = not self._cue_dropdown_open
                    self._channel_dropdown_open = False
                    return None
                if self._cue_dropdown_open:
                    for i, rect in enumerate(self._cue_option_rects):
                        if rect.collidepoint(event.pos):
                            self._selected_cue = i
                            self._cue_dropdown_open = False
                            self._load()
                            self._build_layout()
                            self._set_status(f"Loaded {self._cue_label(i)}")
                            return None
                    self._cue_dropdown_open = False
                if self._channel_rect.collidepoint(event.pos):
                    self._channel_dropdown_open = not self._channel_dropdown_open
                    self._cue_dropdown_open = False
                    return None
                if self._channel_dropdown_open:
                    for i, rect in enumerate(self._channel_option_rects):
                        if rect.collidepoint(event.pos):
                            self._selected_channel = i
                            self._channel_dropdown_open = False
                            self._load()
                            self._build_layout()
                            self._set_status(f"Loaded {self.CHANNEL_LABELS[i]}")
                            return None
                    self._channel_dropdown_open = False

            for layer, _label in self.LAYERS:
                if self._layer_rects[layer].collidepoint(event.pos):
                    if self._active_layer != layer:
                        self._active_layer = layer
                        self._left_content_scroll = 0
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

            if self._active_layer == "styles":
                if self._save_style_rect.collidepoint(event.pos):
                    self._save_current_as_style()
                    return None
                for i, rect in enumerate(self._style_load_rects):
                    if rect.collidepoint(event.pos):
                        self._apply_saved_style(i)
                        return None
                for i, rect in enumerate(self._style_delete_rects):
                    if rect.collidepoint(event.pos):
                        self._delete_saved_style(i)
                        return None
                for i, rect in enumerate(self._style_row_rects):
                    if rect.collidepoint(event.pos):
                        self._start_style_edit(i)
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

    def _handle_style_edit_key(self, event: pygame.event.Event) -> str | None:
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_style_edit()
        elif event.key == pygame.K_ESCAPE:
            self._editing_style_index = -1
            self._editing_style_text = ""
        elif event.key == pygame.K_BACKSPACE:
            self._editing_style_text = self._editing_style_text[:-1]
        else:
            ch = event.unicode
            if ch and ch.isprintable() and len(self._editing_style_text) < 36:
                self._editing_style_text += ch
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

    def _load(self) -> None:
        global_note_style = cfg.load().get("note_style", {})
        if self._has_theme_channel_context():
            if self._has_style_sync_context():
                data = perf_store.get_theme_cue_note_style(
                    self._performance_id,
                    self._theme_index,
                    self._selected_cue,
                    self._selected_channel,
                )
                self._channel_status_text = (
                    "Cue Override"
                    if perf_store.has_theme_cue_channel_override(
                        self._performance_id,
                        self._theme_index,
                        self._selected_cue,
                        self._selected_channel,
                    )
                    else "Cue Default"
                )
            else:
                data = perf_store.get_theme_channel_note_style(
                    self._performance_id,
                    self._theme_index,
                    self._selected_channel,
                )
                self._channel_status_text = (
                    "Custom Override"
                    if perf_store.has_theme_channel_override(
                        self._performance_id,
                        self._theme_index,
                        self._selected_channel,
                    )
                    else "Theme Default"
                )
        else:
            data = global_note_style
            self._channel_status_text = ""
        self._values = {
            "speed_px_per_sec": int(global_note_style.get("speed_px_per_sec", 420)),
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
        full = cfg.load()
        raw_styles = full.get("note_styles", [])
        self._saved_styles = []
        for entry in raw_styles if isinstance(raw_styles, list) else []:
            if isinstance(entry, dict):
                self._saved_styles.append(dict(entry))
        self._active_saved_style_index = int(full.get("active_note_style_index", -1))

    def _save(self) -> None:
        data = cfg.load()
        note_style = _strip_legacy_note_automation(dict(self._values))
        data["note_style"] = note_style
        data.setdefault("slide_palette", {})["enabled"] = False
        cfg.save(data)
        if self._has_theme_channel_context():
            channel_note_style = dict(note_style)
            channel_note_style.pop("speed_px_per_sec", None)
            if self._has_style_sync_context():
                perf_store.set_theme_cue_channel_note_style(
                    self._performance_id,
                    self._theme_index,
                    self._selected_cue,
                    self._selected_channel,
                    channel_note_style,
                )
                self._channel_status_text = "Cue Override"
            else:
                perf_store.set_theme_channel_note_style(
                    self._performance_id,
                    self._theme_index,
                    self._selected_channel,
                    channel_note_style,
                )
                self._channel_status_text = "Custom Override"
        self._set_status("Saved")

    def _save_style_library(self) -> None:
        data = cfg.load()
        data["note_styles"] = [dict(entry) for entry in self._saved_styles]
        data["active_note_style_index"] = int(self._active_saved_style_index)
        cfg.save(data)

    def _start_style_edit(self, style_index: int) -> None:
        if not (0 <= style_index < len(self._saved_styles)):
            return
        self._editing_style_index = style_index
        self._editing_style_text = str(
            self._saved_styles[style_index].get("name", f"Style {style_index + 1}")
        )

    def _commit_style_edit(self) -> None:
        idx = self._editing_style_index
        if not (0 <= idx < len(self._saved_styles)):
            self._editing_style_index = -1
            self._editing_style_text = ""
            return
        new_name = self._editing_style_text.strip() or f"Style {idx + 1}"
        self._saved_styles[idx]["name"] = new_name
        self._save_style_library()
        self._editing_style_index = -1
        self._editing_style_text = ""

    def _do_left_scroll(self, delta: int) -> None:
        avail = self._left_panel.height - (12 + LAYER_BTN_H + 14) - 12
        if self._active_layer == "effects":
            toggle_total = len(self.EFFECT_TOGGLES) * (38 + 8) + 8
            content_h = toggle_total + len(self.EFFECT_FIELDS) * (ROW_H + ROW_GAP)
        elif self._active_layer == "styles":
            content_h = (
                STYLE_ACTION_BTN_H + STYLE_ACTION_BTN_GAP
                + len(self._saved_styles) * (THEME_BTN_H + THEME_BTN_GAP)
            )
        else:
            content_h = len(self._active_fields()) * (ROW_H + ROW_GAP)
        max_scroll = max(0, content_h - avail)
        self._left_content_scroll = max(0, min(max_scroll, self._left_content_scroll + delta))
        self._build_layer_rows()

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        if self._has_theme_channel_context():
            title = f"Notes / {self.CHANNEL_LABELS[self._selected_channel]}"
            if self._has_style_sync_context():
                title = f"{self._cue_label(self._selected_cue)} / {self.CHANNEL_LABELS[self._selected_channel]}"
        else:
            title = "Notes Settings"
        title_surf = self._title_font.render(title, True, TITLE_COLOR)
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
        preview_top_pad = 70 if self._has_theme_channel_context() else 16
        self._preview_rect = pygame.Rect(
            self._right_panel.left + 8,
            self._right_panel.top + preview_top_pad,
            self._right_panel.width - 16,
            self._right_panel.height - preview_top_pad - 8,
        )
        if self._has_theme_channel_context():
            cue_width = min(240, self._right_panel.width - 32)
            top_y = self._right_panel.top + 18
            if self._has_style_sync_context():
                self._cue_rect = pygame.Rect(
                    self._right_panel.left + 16,
                    top_y,
                    cue_width,
                    40,
                )
                self._cue_option_rects = []
                for i in range(self._cue_count()):
                    self._cue_option_rects.append(
                        pygame.Rect(
                            self._cue_rect.left,
                            self._cue_rect.bottom + 4 + i * 34,
                            self._cue_rect.width,
                            32,
                        )
                    )
                top_y = self._cue_rect.bottom + 12
            else:
                self._cue_option_rects = []
            self._channel_rect = pygame.Rect(
                self._right_panel.left + 16,
                top_y,
                min(250, self._right_panel.width - 32),
                40,
            )
            self._channel_option_rects = []
            for i in range(len(self.CHANNEL_LABELS)):
                self._channel_option_rects.append(
                    pygame.Rect(
                        self._channel_rect.left,
                        self._channel_rect.bottom + 4 + i * 34,
                        self._channel_rect.width,
                        32,
                    )
                )
        else:
            self._cue_option_rects = []
            self._channel_option_rects = []

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
        if self._active_layer == "styles":
            return []
        return (
            [(f"gradient_{c}", label, 0, 255, 5) for c, label in self.COLOR_CHANNELS]
            + [self.COLOR_BLEND_FIELD, self.COLOR_EDGE_WIDTH_FIELD, self.COLOR_GLOW_FIELD]
        )

    def _build_layer_rows(self) -> None:
        self._row_rects = []
        self._slider_rects = []
        self._style_row_rects = []
        self._style_load_rects = []
        self._style_delete_rects = []
        self._effect_toggle_rects = []

        fields = self._active_fields()
        y = self._left_panel.top + 12 + LAYER_BTN_H + 14 - self._left_content_scroll
        row_w = self._left_panel.width - 24

        total_gaps = ROW_GAP * max(0, len(fields) - 1)
        avail_h = self._left_panel.height - (12 + LAYER_BTN_H + 14) - 12
        if self._active_layer == "effects":
            _toggle_taken = len(self.EFFECT_TOGGLES) * (38 + 8) + 8
            _avail_sliders = max(len(fields) * 40, avail_h - _toggle_taken)
            _eff_gaps = ROW_GAP * max(0, len(fields) - 1)
            max_row_h = max(40, (_avail_sliders - _eff_gaps) // max(1, len(fields)))
        else:
            max_row_h = max(40, (avail_h - total_gaps) // max(1, len(fields)))
        row_h = max(40, min(ROW_H, max_row_h))
        slider_bottom_pad = max(10, min(16, row_h // 3))

        if self._active_layer == "styles":
            self._save_style_rect = pygame.Rect(self._left_panel.left + 12, y, row_w, STYLE_ACTION_BTN_H)
            y += STYLE_ACTION_BTN_H + STYLE_ACTION_BTN_GAP
            load_w = 90
            del_w = 80
            gap = 8
            name_w = row_w - load_w - del_w - (gap * 2)
            for _style in self._saved_styles:
                row_rect = pygame.Rect(self._left_panel.left + 12, y, row_w, THEME_BTN_H)
                load_rect = pygame.Rect(row_rect.right - del_w - gap - load_w, row_rect.top + 6, load_w, row_rect.height - 12)
                delete_rect = pygame.Rect(row_rect.right - del_w, row_rect.top + 6, del_w, row_rect.height - 12)
                name_rect = pygame.Rect(row_rect.left + 12, row_rect.top, name_w, row_rect.height)
                self._style_row_rects.append(name_rect)
                self._style_load_rects.append(load_rect)
                self._style_delete_rects.append(delete_rect)
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
        self._hover_cue = self._has_style_sync_context() and self._cue_rect.collidepoint(pos)
        self._hover_cue_option = -1
        if self._cue_dropdown_open:
            for i, rect in enumerate(self._cue_option_rects):
                if rect.collidepoint(pos):
                    self._hover_cue_option = i
                    break
        self._hover_channel = self._has_theme_channel_context() and self._channel_rect.collidepoint(pos)
        self._hover_channel_option = -1
        if self._channel_dropdown_open:
            for i, rect in enumerate(self._channel_option_rects):
                if rect.collidepoint(pos):
                    self._hover_channel_option = i
                    break
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

        self._hover_style = -1
        self._hover_style_load = -1
        self._hover_style_delete = -1
        self._hover_save_style = False
        if self._active_layer == "styles":
            self._hover_save_style = self._save_style_rect.collidepoint(pos)
            for i, rect in enumerate(self._style_row_rects):
                if rect.collidepoint(pos):
                    self._hover_style = i
                    break
            for i, rect in enumerate(self._style_load_rects):
                if rect.collidepoint(pos):
                    self._hover_style_load = i
                    break
            for i, rect in enumerate(self._style_delete_rects):
                if rect.collidepoint(pos):
                    self._hover_style_delete = i
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

        _cy = self._left_panel.top + 12 + LAYER_BTN_H + 8
        self.screen.set_clip(pygame.Rect(
            self._left_panel.left + 1, _cy,
            self._left_panel.width - 2, max(0, self._left_panel.bottom - _cy - 1),
        ))

        if self._active_layer == "styles":
            self._draw_style_buttons()
            self.screen.set_clip(None)
            return

        if self._active_layer == "effects":
            self._draw_effect_rows()
            self.screen.set_clip(None)
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

        self.screen.set_clip(None)

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

    def _draw_style_buttons(self) -> None:
        save_bg = BUTTON_HOVER_BG if self._hover_save_style else BUTTON_NORMAL_BG
        save_fg = BUTTON_HOVER_TEXT_COLOR if self._hover_save_style else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, save_bg, self._save_style_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._save_style_rect, width=1, border_radius=8)
        save_label = self._value_font.render("SAVE CURRENT AS NEW STYLE", True, save_fg)
        self.screen.blit(save_label, save_label.get_rect(center=self._save_style_rect.center))

        if not self._saved_styles:
            msg = self._label_font.render("No saved styles yet.", True, MUTED_TEXT_COLOR)
            self.screen.blit(msg, (self._left_panel.left + 24, self._save_style_rect.bottom + 20))
            return

        for i, style in enumerate(self._saved_styles):
            row_rect = pygame.Rect(
                self._left_panel.left + 12,
                self._style_row_rects[i].top,
                self._left_panel.width - 24,
                THEME_BTN_H,
            )
            is_active = i == self._active_saved_style_index
            hovered = i == self._hover_style
            is_editing = i == self._editing_style_index
            bg = BUTTON_HOVER_BG if (hovered or is_active) else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, bg, row_rect, border_radius=8)
            border = ACCENT_COLOR if (is_active or is_editing) else BUTTON_BORDER_COLOR
            pygame.draw.rect(self.screen, border, row_rect, width=2 if (is_active or is_editing) else 1, border_radius=8)

            name = self._editing_style_text + "|" if is_editing else str(style.get("name", f"Style {i + 1}"))
            title = self._value_font.render(name, True, BUTTON_TEXT_COLOR if not hovered else BUTTON_HOVER_TEXT_COLOR)
            self.screen.blit(title, (row_rect.left + 12, row_rect.top + 7))

            detail = self._label_font.render(
                f"W {int(style.get('width_px', 12))}  Speed {int(style.get('speed_px_per_sec', 420))}  Glow {int(style.get('glow_strength_percent', 80))}",
                True,
                MUTED_TEXT_COLOR,
            )
            self.screen.blit(detail, (row_rect.left + 12, row_rect.top + 28))

            self._draw_small_action_button(
                self._style_load_rects[i],
                "LOAD",
                i == self._hover_style_load,
            )
            self._draw_small_action_button(
                self._style_delete_rects[i],
                "DEL",
                i == self._hover_style_delete,
                bg=DELETE_BUTTON_BG,
                bg_hover=DELETE_BUTTON_HOVER_BG,
                fg=DELETE_BUTTON_TEXT_COLOR,
                fg_hover=DELETE_BUTTON_HOVER_TEXT_COLOR,
            )

    def _draw_small_action_button(
        self,
        rect: pygame.Rect,
        label: str,
        hovered: bool,
        bg: tuple[int, int, int] = BUTTON_NORMAL_BG,
        bg_hover: tuple[int, int, int] = BUTTON_HOVER_BG,
        fg: tuple[int, int, int] = BUTTON_TEXT_COLOR,
        fg_hover: tuple[int, int, int] = BUTTON_HOVER_TEXT_COLOR,
    ) -> None:
        pygame.draw.rect(self.screen, bg_hover if hovered else bg, rect, border_radius=6)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=6)
        surf = self._label_font.render(label, True, fg_hover if hovered else fg)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _save_current_as_style(self) -> None:
        style_name = f"Style {len(self._saved_styles) + 1}"
        style = _strip_legacy_note_automation(dict(self._values))
        style["name"] = style_name
        self._saved_styles.append(style)
        self._active_saved_style_index = len(self._saved_styles) - 1
        self._save_style_library()
        self._build_layer_rows()
        self._set_status(f"Saved {style_name}")

    def _apply_saved_style(self, style_index: int) -> None:
        if not (0 <= style_index < len(self._saved_styles)):
            return
        style = _strip_legacy_note_automation(dict(self._saved_styles[style_index]))
        style.pop("name", None)
        self._values.update(style)
        self._active_saved_style_index = style_index
        self._save()
        data = cfg.load()
        data.setdefault("slide_palette", {})["enabled"] = False
        data["active_note_style_index"] = style_index
        data.setdefault("note_style", {})["active_theme_id"] = "custom"
        data.setdefault("note_style", {})["experimental_claire_script_enabled"] = 0
        cfg.save(data)
        self._save_style_library()
        self._set_status(f"Loaded {self._saved_styles[style_index].get('name', f'Style {style_index + 1}')}")

    def _delete_saved_style(self, style_index: int) -> None:
        if not (0 <= style_index < len(self._saved_styles)):
            return
        self._saved_styles.pop(style_index)
        if self._editing_style_index == style_index:
            self._editing_style_index = -1
            self._editing_style_text = ""
        elif self._editing_style_index > style_index:
            self._editing_style_index -= 1
        if self._active_saved_style_index == style_index:
            self._active_saved_style_index = -1
        elif self._active_saved_style_index > style_index:
            self._active_saved_style_index -= 1
        self._save_style_library()
        self._build_layer_rows()
        self._set_status("Deleted style")

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
        key_w = max(14, self.screen.get_width() // 52)  # match actual white-key width
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

        if self._has_theme_channel_context():
            if self._has_style_sync_context():
                self._draw_cue_dropdown()
            self._draw_channel_dropdown()
            mode_surf = self._value_font.render(self._channel_status_text, True, MUTED_TEXT_COLOR)
            self.screen.blit(mode_surf, (self._channel_rect.right + 16, self._channel_rect.top + 8))

        now = pygame.time.get_ticks()
        if self._status_text and now <= self._status_until_ms:
            status_surf = self._value_font.render(self._status_text, True, ACCENT_COLOR)
            self.screen.blit(status_surf, (self._preview_rect.left + 12, self._preview_rect.top + 64))

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))

    def _has_theme_channel_context(self) -> bool:
        return bool(self._performance_id) and self._theme_index >= 0

    def _has_style_sync_context(self) -> bool:
        return self._has_theme_channel_context() and perf_store.is_theme_style_sync_enabled(
            self._performance_id,
            self._theme_index,
        )

    def _cue_count(self) -> int:
        if not self._has_theme_channel_context():
            return 1
        return perf_store.get_theme_style_cue_count(self._performance_id, self._theme_index)

    def _cue_label(self, cue_index: int) -> str:
        if not self._has_theme_channel_context():
            return f"Cue {cue_index + 1}"
        return perf_store.get_theme_style_cue_label(self._performance_id, self._theme_index, cue_index)

    def _draw_cue_dropdown(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_cue or self._cue_dropdown_open else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, bg, self._cue_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._cue_rect, width=1, border_radius=8)
        label = self._value_font.render(
            self._cue_label(self._selected_cue),
            True,
            BUTTON_HOVER_TEXT_COLOR if self._hover_cue else BUTTON_TEXT_COLOR,
        )
        self.screen.blit(label, (self._cue_rect.left + 12, self._cue_rect.top + 7))
        caret = self._value_font.render("v", True, BUTTON_TEXT_COLOR)
        self.screen.blit(caret, caret.get_rect(midright=(self._cue_rect.right - 12, self._cue_rect.centery)))

        if not self._cue_dropdown_open:
            return

        max_rows = min(8, len(self._cue_option_rects))
        panel_rect = pygame.Rect(
            self._cue_rect.left,
            self._cue_rect.bottom + 4,
            self._cue_rect.width,
            max_rows * 34 + 8,
        )
        pygame.draw.rect(self.screen, PANEL_BG, panel_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, panel_rect, width=1, border_radius=8)
        clip = self.screen.get_clip()
        self.screen.set_clip(panel_rect)
        for i, rect in enumerate(self._cue_option_rects):
            if rect.bottom > panel_rect.bottom - 4:
                break
            hovered = i == self._hover_cue_option
            row_bg = BUTTON_HOVER_BG if hovered or i == self._selected_cue else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, row_bg, rect, border_radius=6)
            text = self._label_font.render(
                self._cue_label(i),
                True,
                BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR,
            )
            self.screen.blit(text, (rect.left + 10, rect.top + 4))
        self.screen.set_clip(clip)

    def _draw_channel_dropdown(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_channel or self._channel_dropdown_open else BUTTON_NORMAL_BG
        pygame.draw.rect(self.screen, bg, self._channel_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._channel_rect, width=1, border_radius=8)
        label = self._value_font.render(
            self.CHANNEL_LABELS[self._selected_channel],
            True,
            BUTTON_HOVER_TEXT_COLOR if self._hover_channel else BUTTON_TEXT_COLOR,
        )
        self.screen.blit(label, (self._channel_rect.left + 12, self._channel_rect.top + 7))
        caret = self._value_font.render("v", True, BUTTON_TEXT_COLOR)
        self.screen.blit(caret, caret.get_rect(midright=(self._channel_rect.right - 12, self._channel_rect.centery)))

        if not self._channel_dropdown_open:
            return

        list_height = min(9, len(self._channel_option_rects)) * 34 + 8
        panel_rect = pygame.Rect(
            self._channel_rect.left,
            self._channel_rect.bottom + 4,
            self._channel_rect.width,
            list_height,
        )
        pygame.draw.rect(self.screen, PANEL_BG, panel_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, panel_rect, width=1, border_radius=8)
        clip = self.screen.get_clip()
        self.screen.set_clip(panel_rect)
        for i, rect in enumerate(self._channel_option_rects):
            if rect.bottom > panel_rect.bottom - 4:
                break
            hovered = i == self._hover_channel_option
            row_bg = BUTTON_HOVER_BG if hovered or i == self._selected_channel else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, row_bg, rect, border_radius=6)
            text = self._label_font.render(
                self.CHANNEL_LABELS[i],
                True,
                BUTTON_HOVER_TEXT_COLOR if hovered else BUTTON_TEXT_COLOR,
            )
            self.screen.blit(text, (rect.left + 10, rect.top + 4))
        self.screen.set_clip(clip)

    def _set_status(self, text: str, duration_ms: int = 1400) -> None:
        self._status_text = text
        self._status_until_ms = pygame.time.get_ticks() + duration_ms
