"""Voice recognition settings screen."""

from __future__ import annotations

import pygame
from src import config as cfg

# ── Colour palette ────────────────────────────────────────────────────────────
BG_COLOR        = (15, 15, 20)
TITLE_COLOR     = (230, 230, 230)
TEXT_COLOR      = (210, 210, 210)
MUTED_COLOR     = (130, 130, 140)
DIM_COLOR       = (80, 80, 95)
PANEL_BG        = (22, 22, 30)
BTN_NORMAL_BG   = (35, 35, 45)
BTN_HOVER_BG    = (60, 60, 80)
BTN_ON_BG       = (0, 90, 90)
BTN_ON_HOVER_BG = (0, 120, 120)
BTN_TEXT        = (210, 210, 210)
BTN_TEXT_HOVER  = (255, 255, 255)
BTN_ON_TEXT     = (180, 255, 255)
BORDER_COLOR    = (80, 80, 110)
FILL_COLOR      = (0, 180, 180)
FILL_DIM_COLOR  = (40, 70, 70)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 22
VALUE_FONT_SIZE = 20
BTN_FONT_SIZE   = 22

PANEL_W      = 600
ROW_H        = 62
TOGGLE_H     = 46
ROW_GAP      = 8
ROW_PAD      = 14
SLIDER_H     = 8
KNOB_R       = 9
BACK_W       = 160
BACK_H       = 52
TOGGLE_BTN_W = 100
BACKEND_BTN_W = 110

# (key, label, min_v, max_v, step, suffix)
_SLIDERS: list[tuple[str, str, float, float, float, str]] = [
    ("push_to_talk_record_secs", "Push-to-Talk Duration",  1.0,  15.0, 0.5, "s"),
    ("continuous_record_secs",   "Continuous Window",      0.5,   4.0, 0.1, "s"),
    ("continuous_gap_ms",        "Continuous Gap",        80.0, 2000.0, 20.0, "ms"),
    ("word_buffer_size",         "Word Buffer Size",       2.0,  24.0,  1.0, ""),
]

_DEFAULTS: dict[str, float] = {
    "push_to_talk_record_secs": 6.0,
    "continuous_record_secs": 1.2,
    "continuous_gap_ms": 220.0,
    "word_buffer_size": 6.0,
}


class VoiceSettingsScreen:
    """Settings UI for voice recognition / push-to-talk configuration."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font   = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        # Config values
        self._continuous_listen: bool = False
        self._allow_google_fallback: bool = True
        self._backend: str = "vosk"
        self._slider_values: dict[str, float] = {}

        # Rects
        self._panel_rect          = pygame.Rect(0, 0, 0, 0)
        self._back_rect           = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._title_surf: pygame.Surface | None = None
        self._title_pos           = (0, 0)
        self._continuous_rect     = pygame.Rect(0, 0, 0, TOGGLE_H)
        self._continuous_btn_rect = pygame.Rect(0, 0, TOGGLE_BTN_W, 34)
        self._slider_row_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect]     = []
        self._backend_rect        = pygame.Rect(0, 0, 0, TOGGLE_H)
        self._vosk_btn_rect       = pygame.Rect(0, 0, BACKEND_BTN_W, 34)
        self._google_btn_rect     = pygame.Rect(0, 0, BACKEND_BTN_W, 34)
        self._fallback_rect       = pygame.Rect(0, 0, 0, TOGGLE_H)
        self._fallback_btn_rect   = pygame.Rect(0, 0, TOGGLE_BTN_W, 34)

        # Hover / drag state
        self._hover_back       = False
        self._hover_continuous = False
        self._hover_fallback   = False
        self._hover_vosk       = False
        self._hover_google     = False
        self._hover_slider: int = -1
        self._drag_slider: int  = -1

        self._load()
        self._build_layout()

    # ── Public API ────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            if self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._drag_slider = -1

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._continuous_btn_rect.collidepoint(event.pos):
                self._continuous_listen = not self._continuous_listen
                self._save()
                return None

            if self._fallback_btn_rect.collidepoint(event.pos) and self._backend == "vosk":
                self._allow_google_fallback = not self._allow_google_fallback
                self._save()
                return None

            if self._vosk_btn_rect.collidepoint(event.pos):
                self._backend = "vosk"
                self._save()
                return None

            if self._google_btn_rect.collidepoint(event.pos):
                self._backend = "google"
                self._save()
                return None

            for i, sr in enumerate(self._slider_rects):
                if sr.inflate(0, 20).collidepoint(event.pos):
                    self._drag_slider = i
                    self._set_slider_from_x(i, event.pos[0])
                    return None

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)
        self._draw_panel()
        self._draw_back_btn()

    # ── Private ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        vc = cfg.load().get("voice_settings", {})
        self._continuous_listen     = bool(vc.get("continuous_listen", False))
        self._allow_google_fallback = bool(vc.get("allow_google_fallback", True))
        self._backend               = str(vc.get("backend", "vosk"))
        for key, _label, min_v, max_v, _step, _suf in _SLIDERS:
            raw = vc.get(key, _DEFAULTS.get(key, min_v))
            self._slider_values[key] = max(min_v, min(max_v, float(raw)))

    def _save(self) -> None:
        data = cfg.load()
        vc = data.setdefault("voice_settings", {})
        vc["continuous_listen"]     = self._continuous_listen
        vc["allow_google_fallback"] = self._allow_google_fallback
        vc["backend"]               = self._backend
        for key, _label, _min, _max, step, _suf in _SLIDERS:
            v = self._slider_values[key]
            vc[key] = int(round(v)) if step >= 1.0 else round(v, 2)
        cfg.save(data)

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Voice Settings", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        panel_x = cx - PANEL_W // 2
        panel_top = title_y + title_surf.get_height() + 20

        y = panel_top + 16

        # Continuous mode toggle
        self._continuous_rect = pygame.Rect(panel_x, y, PANEL_W, TOGGLE_H)
        btn_x = panel_x + PANEL_W - ROW_PAD - TOGGLE_BTN_W
        self._continuous_btn_rect = pygame.Rect(btn_x, y + (TOGGLE_H - 34) // 2, TOGGLE_BTN_W, 34)
        y += TOGGLE_H + ROW_GAP

        # Slider rows
        self._slider_row_rects = []
        self._slider_rects = []
        for _key, _label, _min, _max, _step, _suf in _SLIDERS:
            row = pygame.Rect(panel_x, y, PANEL_W, ROW_H)
            slider = pygame.Rect(
                panel_x + ROW_PAD,
                y + ROW_H - SLIDER_H - 12,
                PANEL_W - ROW_PAD * 2,
                SLIDER_H,
            )
            self._slider_row_rects.append(row)
            self._slider_rects.append(slider)
            y += ROW_H + ROW_GAP

        y += 6  # extra separator gap

        # Backend selector
        self._backend_rect = pygame.Rect(panel_x, y, PANEL_W, TOGGLE_H)
        g_x = panel_x + PANEL_W - ROW_PAD - BACKEND_BTN_W
        v_x = g_x - BACKEND_BTN_W - 6
        btn_y = y + (TOGGLE_H - 34) // 2
        self._vosk_btn_rect   = pygame.Rect(v_x, btn_y, BACKEND_BTN_W, 34)
        self._google_btn_rect = pygame.Rect(g_x, btn_y, BACKEND_BTN_W, 34)
        y += TOGGLE_H + ROW_GAP

        # Allow Google Fallback toggle
        self._fallback_rect = pygame.Rect(panel_x, y, PANEL_W, TOGGLE_H)
        fb_x = panel_x + PANEL_W - ROW_PAD - TOGGLE_BTN_W
        self._fallback_btn_rect = pygame.Rect(fb_x, y + (TOGGLE_H - 34) // 2, TOGGLE_BTN_W, 34)
        y += TOGGLE_H + 16

        panel_h = y - panel_top
        self._panel_rect = pygame.Rect(panel_x, panel_top, PANEL_W, panel_h)

        back_y = sr.height - BACK_H - 24
        self._back_rect = pygame.Rect(cx - BACK_W // 2, back_y, BACK_W, BACK_H)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back       = self._back_rect.collidepoint(pos)
        self._hover_continuous = self._continuous_btn_rect.collidepoint(pos)
        self._hover_fallback   = self._fallback_btn_rect.collidepoint(pos) and self._backend == "vosk"
        self._hover_vosk       = self._vosk_btn_rect.collidepoint(pos)
        self._hover_google     = self._google_btn_rect.collidepoint(pos)
        self._hover_slider = -1
        for i, sr in enumerate(self._slider_rects):
            if sr.inflate(0, 20).collidepoint(pos):
                self._hover_slider = i
                break

    def _set_slider_from_x(self, index: int, mouse_x: int) -> None:
        sr = self._slider_rects[index]
        key, _label, min_v, max_v, step, _suf = _SLIDERS[index]
        if sr.width <= 1:
            return
        ratio = max(0.0, min(1.0, (mouse_x - sr.left) / sr.width))
        raw = min_v + ratio * (max_v - min_v)
        snapped = round(raw / step) * step
        new_v = round(max(min_v, min(max_v, snapped)), 4)
        if new_v == self._slider_values[key]:
            return
        self._slider_values[key] = new_v
        self._save()

    # ── Draw helpers ──────────────────────────────────────────────────────────

    def _draw_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, BORDER_COLOR, self._panel_rect, width=1, border_radius=10)
        self._draw_continuous_row()
        for i in range(len(_SLIDERS)):
            self._draw_slider_row(i)
        self._draw_backend_row()
        self._draw_fallback_row()

    def _draw_row_bg(self, rect: pygame.Rect, dimmed: bool = False) -> None:
        bg = (18, 18, 24) if dimmed else (28, 28, 38)
        border = (50, 50, 65) if dimmed else BORDER_COLOR
        pygame.draw.rect(self.screen, bg, rect, border_radius=6)
        pygame.draw.rect(self.screen, border, rect, width=1, border_radius=6)

    def _draw_toggle_btn(self, rect: pygame.Rect, active: bool, hovered: bool, dimmed: bool = False) -> None:
        if dimmed:
            bg = (28, 28, 36)
            fg = DIM_COLOR
            border = (50, 50, 65)
        elif active:
            bg = BTN_ON_HOVER_BG if hovered else BTN_ON_BG
            fg = BTN_ON_TEXT
            border = BORDER_COLOR
        else:
            bg = BTN_HOVER_BG if hovered else BTN_NORMAL_BG
            fg = BTN_TEXT_HOVER if hovered else BTN_TEXT
            border = BORDER_COLOR
        pygame.draw.rect(self.screen, bg, rect, border_radius=6)
        pygame.draw.rect(self.screen, border, rect, width=1, border_radius=6)
        label = "ON" if active else "OFF"
        surf = self._btn_font.render(label, True, fg)
        self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_label(self, row: pygame.Rect, text: str, dimmed: bool = False) -> None:
        color = DIM_COLOR if dimmed else TEXT_COLOR
        surf = self._label_font.render(text, True, color)
        self.screen.blit(surf, (row.left + ROW_PAD, row.centery - surf.get_height() // 2))

    def _draw_continuous_row(self) -> None:
        self._draw_row_bg(self._continuous_rect)
        self._draw_label(self._continuous_rect, "Continuous Mode")
        self._draw_toggle_btn(self._continuous_btn_rect, self._continuous_listen, self._hover_continuous)

    def _draw_slider_row(self, index: int) -> None:
        key, label, min_v, max_v, step, suffix = _SLIDERS[index]
        row = self._slider_row_rects[index]
        sr  = self._slider_rects[index]
        val = self._slider_values[key]

        # Push-to-talk duration is irrelevant in continuous mode; others irrelevant in PTT mode.
        dimmed = self._continuous_listen if key == "push_to_talk_record_secs" else not self._continuous_listen

        self._draw_row_bg(row, dimmed=dimmed)

        label_fg = DIM_COLOR if dimmed else TEXT_COLOR
        label_surf = self._label_font.render(label, True, label_fg)
        self.screen.blit(label_surf, (row.left + ROW_PAD, row.top + 8))

        val_text = f"{int(round(val))}{suffix}" if step >= 1.0 else f"{val:.1f}{suffix}"
        val_fg = DIM_COLOR if dimmed else MUTED_COLOR
        val_surf = self._value_font.render(val_text, True, val_fg)
        self.screen.blit(val_surf, val_surf.get_rect(topright=(row.right - ROW_PAD, row.top + 9)))

        is_hot = (self._hover_slider == index or self._drag_slider == index) and not dimmed
        track_bg = (25, 25, 32) if dimmed else (BTN_HOVER_BG if is_hot else BTN_NORMAL_BG)
        border = (50, 50, 65) if dimmed else BORDER_COLOR
        pygame.draw.rect(self.screen, track_bg, sr, border_radius=4)
        pygame.draw.rect(self.screen, border, sr, width=1, border_radius=4)

        ratio = (val - min_v) / max(1e-6, max_v - min_v)
        fill_w = max(1, int(sr.width * ratio))
        fill_color = FILL_DIM_COLOR if dimmed else FILL_COLOR
        pygame.draw.rect(self.screen, fill_color, pygame.Rect(sr.left, sr.top, fill_w, sr.height), border_radius=4)

        if not dimmed:
            knob_x = int(sr.left + ratio * sr.width)
            pygame.draw.circle(self.screen, (210, 210, 210), (knob_x, sr.centery), KNOB_R)
            pygame.draw.circle(self.screen, BORDER_COLOR, (knob_x, sr.centery), KNOB_R, width=1)

    def _draw_backend_row(self) -> None:
        self._draw_row_bg(self._backend_rect)
        self._draw_label(self._backend_rect, "STT Backend")

        is_vosk = self._backend == "vosk"
        for rect, active, hovered, label in (
            (self._vosk_btn_rect,   is_vosk,      self._hover_vosk,   "VOSK"),
            (self._google_btn_rect, not is_vosk,  self._hover_google, "GOOGLE"),
        ):
            if active:
                bg = BTN_ON_HOVER_BG if hovered else BTN_ON_BG
                fg = BTN_ON_TEXT
            else:
                bg = BTN_HOVER_BG if hovered else BTN_NORMAL_BG
                fg = BTN_TEXT_HOVER if hovered else BTN_TEXT
            pygame.draw.rect(self.screen, bg, rect, border_radius=6)
            pygame.draw.rect(self.screen, BORDER_COLOR, rect, width=1, border_radius=6)
            surf = self._btn_font.render(label, True, fg)
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_fallback_row(self) -> None:
        dimmed = self._backend != "vosk"
        self._draw_row_bg(self._fallback_rect, dimmed=dimmed)
        self._draw_label(self._fallback_rect, "Allow Google Fallback", dimmed=dimmed)
        self._draw_toggle_btn(self._fallback_btn_rect, self._allow_google_fallback, self._hover_fallback, dimmed=dimmed)

    def _draw_back_btn(self) -> None:
        bg = BTN_HOVER_BG if self._hover_back else BTN_NORMAL_BG
        fg = BTN_TEXT_HOVER if self._hover_back else BTN_TEXT
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
