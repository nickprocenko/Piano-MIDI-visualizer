"""Scrolling grand-staff sheet music overlay for learn mode."""

from __future__ import annotations

import pygame

# ── Panel geometry ─────────────────────────────────────────────────────────

PANEL_W: int = 720
LINE_GAP: int = 10          # px between adjacent staff lines
HEADER_H: int = 22          # draggable title bar height
CLEF_ZONE_W: int = 60       # width reserved for clef symbol
PLAYHEAD_OFFSET: int = 80   # px from panel left edge to playhead line

_TREBLE_BOTTOM_Y: int = HEADER_H + 50   # local Y of treble bottom line (E4)
_BASS_BOTTOM_Y:   int = HEADER_H + 110  # local Y of bass bottom line (G2)
PANEL_H: int = _BASS_BOTTOM_Y + 14

_HALF_GAP: float = LINE_GAP / 2.0   # px per diatonic step
_NOTE_H:   int   = 8                 # note-bar height in px
_NOTE_R:   int   = 3                 # note-bar border radius

# ── Pitch mapping ──────────────────────────────────────────────────────────

# Chromatic semitone (0–11) → diatonic step within octave (C=0 … B=6)
_CHROM_TO_DIAT: list[int]  = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
_IS_SHARP:      list[bool] = [False, True, False, True, False,
                               False, True, False, True, False, True, False]

# Global diatonic = (midi_note//12 - 1) * 7 + diatonic_within_octave
# MIDI 60 = C4 → global_diat = 28
TREBLE_BOT_DIAT: int = 30   # E4 — bottom line of treble staff
BASS_BOT_DIAT:   int = 18   # G2 — bottom line of bass staff
SPLIT_DIAT:      int = 28   # C4 — notes >= go to treble, < go to bass

# ── Colour palette ─────────────────────────────────────────────────────────

_COL_PANEL_BG  = (18,  20,  28,  210)
_COL_HEADER_BG = (30,  33,  45,  230)
_COL_STAFF     = (155, 155, 178)
_COL_PLAYHEAD  = (255, 240,  80,  220)
_COL_NOTE_PAST = (68,  68,  90,  120)
_COL_BORDER    = (60,  65,  90,  200)
_COL_TITLE     = (165, 165, 198)
_COL_CLEF      = (185, 185, 212)


# ── Free helpers ────────────────────────────────────────────────────────────

def _global_diatonic(midi_note: int) -> int:
    """Return the global diatonic position (C4 = 28)."""
    return (midi_note // 12 - 1) * 7 + _CHROM_TO_DIAT[midi_note % 12]


# ── Main class ──────────────────────────────────────────────────────────────

class SheetMusicOverlay:
    """Scrolling grand-staff panel drawn on top of the highway in learn mode.

    Notes scroll right-to-left; the playhead is fixed at PLAYHEAD_OFFSET px
    from the left edge of the panel.  Drag the header bar to reposition.
    Press S (handled by app.py) to toggle visibility.
    """

    def __init__(
        self,
        screen: pygame.Surface,
        x: int = 30,
        y: int = 30,
        visible: bool = True,
        px_per_ms: float = 0.15,
    ) -> None:
        self._screen = screen
        self._x = x
        self._y = y
        self._visible = visible
        self.px_per_ms = px_per_ms

        self._dragging   = False
        self._drag_off_x = 0
        self._drag_off_y = 0

        self._surf = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
        self._font_small: pygame.font.Font | None = None
        self._font_clef:  pygame.font.Font | None = None
        self._font_acc:   pygame.font.Font | None = None
        self._init_fonts()

    # ── Public geometry properties (read by app.py) ─────────────────────────

    @property
    def PANEL_W(self) -> int:           # noqa: N802
        return PANEL_W

    @property
    def PLAYHEAD_OFFSET(self) -> int:   # noqa: N802
        return PLAYHEAD_OFFSET

    @property
    def CLEF_ZONE_W(self) -> int:       # noqa: N802
        return CLEF_ZONE_W

    # ── Configuration / lifecycle ────────────────────────────────────────────

    def toggle(self) -> None:
        self._visible = not self._visible

    def get_config(self) -> dict:
        return {
            "x":        self._x,
            "y":        self._y,
            "visible":  self._visible,
            "px_per_ms": self.px_per_ms,
        }

    # ── Event handling ───────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> None:
        if not self._visible:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos
            if pygame.Rect(self._x, self._y, PANEL_W, HEADER_H).collidepoint(mx, my):
                self._dragging   = True
                self._drag_off_x = mx - self._x
                self._drag_off_y = my - self._y
        elif event.type == pygame.MOUSEMOTION:
            if self._dragging:
                mx, my = event.pos
                self._x = mx - self._drag_off_x
                self._y = my - self._drag_off_y
                self._clamp_to_screen()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False

    # ── Drawing ──────────────────────────────────────────────────────────────

    def draw(
        self,
        target: pygame.Surface,
        current_ms: float,
        notes: list[tuple[int, float, float]],
        note_rgb: tuple[int, int, int],
    ) -> None:
        """Render the overlay onto *target* (the main screen surface)."""
        if not self._visible:
            return

        self._screen = target  # stay in sync with screen surface after resize

        surf = self._surf
        surf.fill((0, 0, 0, 0))

        # ── Panel chrome ───────────────────────────────────────────────────
        pygame.draw.rect(surf, _COL_PANEL_BG,  (0, 0, PANEL_W, PANEL_H), border_radius=6)
        pygame.draw.rect(surf, _COL_HEADER_BG, (0, 0, PANEL_W, HEADER_H),
                         border_top_left_radius=6, border_top_right_radius=6)
        if self._font_small:
            lbl = self._font_small.render(
                "Sheet Music  •  S to toggle  •  drag to move",
                True, _COL_TITLE,
            )
            surf.blit(lbl, (8, (HEADER_H - lbl.get_height()) // 2))

        # ── Staff lines ────────────────────────────────────────────────────
        self._draw_staff(surf, _TREBLE_BOTTOM_Y)
        self._draw_staff(surf, _BASS_BOTTOM_Y)

        # ── Clef labels ────────────────────────────────────────────────────
        self._draw_clef(surf)

        # ── Note bars ──────────────────────────────────────────────────────
        for note_num, start_ms, end_ms in notes:
            self._draw_note_bar(surf, note_num, start_ms, end_ms, current_ms, note_rgb)

        # ── Playhead line ──────────────────────────────────────────────────
        pygame.draw.line(
            surf, _COL_PLAYHEAD,
            (PLAYHEAD_OFFSET, HEADER_H + 2),
            (PLAYHEAD_OFFSET, PANEL_H - 4),
            2,
        )

        # ── Border ─────────────────────────────────────────────────────────
        pygame.draw.rect(surf, _COL_BORDER, (0, 0, PANEL_W, PANEL_H), width=1, border_radius=6)

        target.blit(surf, (self._x, self._y))

    # ── Private helpers ──────────────────────────────────────────────────────

    def _init_fonts(self) -> None:
        self._font_small = pygame.font.SysFont("Segoe UI,Arial,DejaVu Sans", 11)
        self._font_clef  = pygame.font.SysFont("Segoe UI,Arial,DejaVu Sans", 24)
        self._font_acc   = pygame.font.SysFont("Segoe UI,Arial,DejaVu Sans", 10)

    def _clamp_to_screen(self) -> None:
        sw, sh = self._screen.get_size()
        self._x = max(0, min(self._x, sw - PANEL_W))
        self._y = max(0, min(self._y, sh - PANEL_H))

    def _draw_staff(self, surf: pygame.Surface, bottom_y: int) -> None:
        """Draw the five horizontal lines of one staff."""
        for i in range(5):
            y = bottom_y - i * LINE_GAP
            pygame.draw.line(surf, _COL_STAFF, (CLEF_ZONE_W, y), (PANEL_W - 4, y), 1)

    def _draw_clef(self, surf: pygame.Surface) -> None:
        if self._font_clef is None:
            return
        cx = CLEF_ZONE_W // 2
        for cy, sym_unicode, fallback_char in [
            (_TREBLE_BOTTOM_Y - LINE_GAP * 2, "\U0001d11e", "G"),  # 𝄞 treble G-clef
            (_BASS_BOTTOM_Y   - LINE_GAP * 2, "\U0001d122", "F"),  # 𝄢 bass F-clef
        ]:
            rendered = self._font_clef.render(sym_unicode, True, _COL_CLEF)
            if rendered.get_width() <= 2:
                # Font doesn't include the SMP glyph; use clef-letter fallback
                rendered = self._font_clef.render(fallback_char, True, _COL_CLEF)
            surf.blit(rendered, rendered.get_rect(center=(cx, cy)))

    def _draw_note_bar(
        self,
        surf: pygame.Surface,
        midi_note: int,
        start_ms: float,
        end_ms: float,
        current_ms: float,
        note_rgb: tuple[int, int, int],
    ) -> None:
        gd        = _global_diatonic(midi_note)
        in_treble = gd >= SPLIT_DIAT

        if in_treble:
            step = gd - TREBLE_BOT_DIAT
            cy   = int(_TREBLE_BOTTOM_Y - step * _HALF_GAP)
        else:
            step = gd - BASS_BOT_DIAT
            cy   = int(_BASS_BOTTOM_Y   - step * _HALF_GAP)

        x0 = PLAYHEAD_OFFSET + (start_ms - current_ms) * self.px_per_ms
        x1 = PLAYHEAD_OFFSET + (end_ms   - current_ms) * self.px_per_ms

        if x1 < CLEF_ZONE_W or x0 > PANEL_W - 4:
            return  # fully outside visible area

        cx0 = max(CLEF_ZONE_W, x0)
        cx1 = min(PANEL_W - 4, x1)
        bw  = max(4, int(cx1 - cx0))

        is_active = start_ms <= current_ms < end_ms
        is_past   = end_ms <= current_ms

        if is_past:
            col: tuple = _COL_NOTE_PAST
        elif is_active:
            col = (
                min(255, note_rgb[0] + 60),
                min(255, note_rgb[1] + 60),
                min(255, note_rgb[2] + 60),
                240,
            )
        else:
            col = (*note_rgb, 200)

        bar = pygame.Rect(int(cx0), cy - _NOTE_H // 2, bw, _NOTE_H)
        pygame.draw.rect(surf, col, bar, border_radius=_NOTE_R)

        # Ledger lines for notes outside the 5-line staff
        bottom_y = _TREBLE_BOTTOM_Y if in_treble else _BASS_BOTTOM_Y
        self._draw_ledger_lines(surf, step, bottom_y, int(cx0), bw)

        # Accidental (#) symbol
        if _IS_SHARP[midi_note % 12] and self._font_acc:
            ax = int(cx0) - 8
            if ax >= CLEF_ZONE_W:
                acc_s = self._font_acc.render("#", True, _COL_STAFF)
                surf.blit(acc_s, acc_s.get_rect(center=(ax, cy)))

    def _draw_ledger_lines(
        self,
        surf: pygame.Surface,
        step: int,
        bottom_y: int,
        bar_x: int,
        bar_w: int,
    ) -> None:
        """Draw ledger lines for notes above or below the 5-line staff."""
        lx = max(CLEF_ZONE_W, bar_x - 4)
        rx = min(PANEL_W - 4, bar_x + bar_w + 4)

        if step < 0:
            # Below bottom line — ledger lines at even negative steps
            s = -2
            while s >= step:
                y = int(bottom_y - s * _HALF_GAP)
                pygame.draw.line(surf, _COL_STAFF, (lx, y), (rx, y), 1)
                s -= 2
        elif step > 8:
            # Above top line (top line is at step=8)
            s = 10
            while s <= step:
                y = int(bottom_y - s * _HALF_GAP)
                pygame.draw.line(surf, _COL_STAFF, (lx, y), (rx, y), 1)
                s += 2
