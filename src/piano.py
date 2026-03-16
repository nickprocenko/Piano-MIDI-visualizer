"""88-key piano keyboard renderer for Pygame."""

from __future__ import annotations

import pygame

# MIDI note range for a standard 88-key piano
PIANO_FIRST_NOTE = 21   # A0
PIANO_LAST_NOTE = 108   # C8
PIANO_NUM_NOTES = PIANO_LAST_NOTE - PIANO_FIRST_NOTE + 1  # 88

# Palette tuned for a cleaner, stage-style keyboard look.
PIANO_BG_TOP = (20, 23, 30)
PIANO_BG_BOTTOM = (10, 12, 18)
WHITE_KEY_TOP = (248, 248, 244)
WHITE_KEY_BOTTOM = (224, 224, 220)
WHITE_KEY_PRESSED_TOP = (194, 236, 244)
WHITE_KEY_PRESSED_BOTTOM = (156, 206, 220)
WHITE_KEY_BORDER = (92, 98, 108)
BLACK_KEY_TOP = (58, 62, 72)
BLACK_KEY_BOTTOM = (16, 18, 24)
BLACK_KEY_PRESSED_TOP = (96, 170, 188)
BLACK_KEY_PRESSED_BOTTOM = (30, 84, 108)
BLACK_KEY_BORDER = (10, 12, 16)
ACCENT_LINE = (142, 206, 221)
C_NOTE_LABEL = (112, 118, 128)

# Which semitone offsets within an octave are black keys
# (C=0, C#=1, D=2, D#=3, E=4, F=5, F#=6, G=7, G#=8, A=9, A#=10, B=11)
_BLACK_SEMITONES = {1, 3, 6, 8, 10}

# Proportions for black key dimensions relative to white key size
BLACK_KEY_WIDTH_RATIO = 0.60
BLACK_KEY_HEIGHT_RATIO = 0.62

def _is_black(note: int) -> bool:
    return (note % 12) in _BLACK_SEMITONES


def _count_white_keys(first: int, last: int) -> int:
    return sum(1 for n in range(first, last + 1) if not _is_black(n))


class Piano:
    """
    Draws an 88-key piano keyboard that occupies the bottom portion of
    the given surface.  Active (held) notes are highlighted.

    Call ``draw(surface, active_notes)`` each frame.
    """

    # Fraction of the screen height the piano occupies
    HEIGHT_FRACTION = 0.18

    def __init__(
        self,
        screen: pygame.Surface,
        height_percent: int = 18,
        brightness_percent: int = 100,
        visible: bool = True,
    ) -> None:
        self._screen = screen
        self._height_fraction = max(0.05, min(0.5, height_percent / 100.0))
        self._brightness = max(0.1, min(1.5, brightness_percent / 100.0))
        self._visible = visible
        self._rect: pygame.Rect | None = None
        self._white_rects: dict[int, pygame.Rect] = {}   # note → Rect
        self._black_rects: dict[int, pygame.Rect] = {}   # note → Rect
        self._c_note_labels: dict[int, pygame.Surface] = {}
        self._label_font: pygame.font.Font | None = None
        self._build_layout()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_resize(self) -> None:
        """Call when the screen size changes to recompute key geometry."""
        self._build_layout()

    def set_target(self, screen: pygame.Surface) -> None:
        """Retarget drawing to *screen*, rebuilding layout if size changed."""
        if self._screen is screen:
            return
        if self._screen.get_size() != screen.get_size():
            self._screen = screen
            self._build_layout()
            return
        self._screen = screen

    def get_note_rect(self, note: int) -> pygame.Rect | None:
        """Return the key rectangle for *note*, or None if note is out of range."""
        rect = self._black_rects.get(note)
        if rect is not None:
            return rect.copy()
        rect = self._white_rects.get(note)
        if rect is not None:
            return rect.copy()
        return None

    def set_height_percent(self, percent: int) -> None:
        self._height_fraction = max(0.05, min(0.5, percent / 100.0))
        self._build_layout()

    def set_brightness(self, percent: int) -> None:
        self._brightness = max(0.1, min(1.5, percent / 100.0))

    def set_visible(self, visible: bool) -> None:
        self._visible = visible

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _scale_color(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
        return (
            max(0, min(255, int(color[0] * factor))),
            max(0, min(255, int(color[1] * factor))),
            max(0, min(255, int(color[2] * factor))),
        )

    @staticmethod
    def _lerp_color(
        a: tuple[int, int, int],
        b: tuple[int, int, int],
        t: float,
    ) -> tuple[int, int, int]:
        return (
            int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t),
        )

    def _draw_vertical_gradient(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        top_color: tuple[int, int, int],
        bottom_color: tuple[int, int, int],
        steps: int,
        border_radius: int = 0,
    ) -> None:
        if rect.width <= 0 or rect.height <= 0:
            return

        grad = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        bands = max(1, steps)
        band_h = max(1, rect.height // bands)
        for i in range(bands):
            y = i * band_h
            h = rect.height - y if i == bands - 1 else band_h
            t = i / float(max(1, bands - 1))
            color = self._lerp_color(top_color, bottom_color, t)
            pygame.draw.rect(grad, (*color, 255), pygame.Rect(0, y, rect.width, h))

        if border_radius > 0:
            mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=border_radius)
            grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        surface.blit(grad, rect.topleft)

    def _build_layout(self) -> None:
        sw, sh = self._screen.get_size()
        piano_h = int(sh * self._height_fraction)
        piano_y = sh - piano_h

        self._rect = pygame.Rect(0, piano_y, sw, piano_h)

        num_white = _count_white_keys(PIANO_FIRST_NOTE, PIANO_LAST_NOTE)
        white_w = sw / float(num_white)
        white_h = piano_h

        black_w = white_w * BLACK_KEY_WIDTH_RATIO
        black_h = white_h * BLACK_KEY_HEIGHT_RATIO

        self._white_rects = {}
        self._black_rects = {}
        self._c_note_labels = {}
        white_centers: dict[int, float] = {}

        label_size = max(10, int(piano_h * 0.095))
        self._label_font = pygame.font.SysFont("Segoe UI", label_size, bold=True)

        white_index = 0  # running index of white keys drawn so far

        for note in range(PIANO_FIRST_NOTE, PIANO_LAST_NOTE + 1):
            semitone = note % 12
            if not _is_black(note):
                left = int(round(white_index * white_w))
                right = int(round((white_index + 1) * white_w))
                rect = pygame.Rect(left, piano_y, max(1, right - left), white_h)
                self._white_rects[note] = rect
                white_centers[note] = rect.centerx
                if semitone == 0 and self._label_font is not None:
                    octave = (note // 12) - 1
                    label = self._label_font.render(f"C{octave}", True, C_NOTE_LABEL)
                    self._c_note_labels[note] = label
                white_index += 1

        # Build black keys from true center-to-center spacing:
        # each black key is centered exactly between its neighboring white-key centers.
        for note in range(PIANO_FIRST_NOTE, PIANO_LAST_NOTE + 1):
            if not _is_black(note):
                continue

            left_white = note - 1
            while left_white >= PIANO_FIRST_NOTE and _is_black(left_white):
                left_white -= 1

            right_white = note + 1
            while right_white <= PIANO_LAST_NOTE and _is_black(right_white):
                right_white += 1

            left_center = white_centers.get(left_white)
            right_center = white_centers.get(right_white)
            if left_center is None or right_center is None:
                continue

            center_x = (left_center + right_center) * 0.5
            x = int(round(center_x - (black_w * 0.5)))
            rect = pygame.Rect(x, piano_y, max(1, int(round(black_w))), black_h)
            self._black_rects[note] = rect

    def draw(self, active_notes: set[int]) -> None:
        """Draw the full keyboard; highlight keys present in *active_notes*."""
        if self._rect is None or not self._visible:
            return

        surface = self._screen
        rect = self._rect

        bg_top = self._scale_color(PIANO_BG_TOP, self._brightness)
        bg_bottom = self._scale_color(PIANO_BG_BOTTOM, self._brightness)
        self._draw_vertical_gradient(surface, rect, bg_top, bg_bottom, steps=10)

        lip_h = max(2, int(rect.height * 0.05))
        pygame.draw.rect(
            surface,
            self._scale_color((54, 60, 72), self._brightness),
            pygame.Rect(rect.left, rect.top, rect.width, lip_h),
        )

        # White keys first so black keys can sit on top.
        for note, key_rect in self._white_rects.items():
            pressed = note in active_notes
            draw_rect = key_rect.copy()
            if pressed:
                draw_rect.y += 1
                draw_rect.height = max(2, draw_rect.height - 1)

            top = WHITE_KEY_PRESSED_TOP if pressed else WHITE_KEY_TOP
            bottom = WHITE_KEY_PRESSED_BOTTOM if pressed else WHITE_KEY_BOTTOM
            self._draw_vertical_gradient(
                surface,
                draw_rect,
                self._scale_color(top, self._brightness),
                self._scale_color(bottom, self._brightness),
                steps=8,
            )

            pygame.draw.line(
                surface,
                self._scale_color((255, 255, 252), self._brightness),
                (draw_rect.left + 1, draw_rect.top + 1),
                (draw_rect.right - 2, draw_rect.top + 1),
                1,
            )
            pygame.draw.rect(surface, self._scale_color(WHITE_KEY_BORDER, self._brightness), draw_rect, width=1)

            label = self._c_note_labels.get(note)
            if label is not None:
                label_rect = label.get_rect()
                label_rect.centerx = draw_rect.centerx
                label_rect.bottom = draw_rect.bottom - max(3, int(draw_rect.height * 0.06))
                surface.blit(label, label_rect)

        # Black keys on top with rounded corners and stronger contrast.
        radius = max(3, int(rect.height * 0.035))
        for note, key_rect in self._black_rects.items():
            pressed = note in active_notes
            draw_rect = key_rect.copy()
            if pressed:
                draw_rect.y += 1
                draw_rect.height = max(2, draw_rect.height - 1)

            top = BLACK_KEY_PRESSED_TOP if pressed else BLACK_KEY_TOP
            bottom = BLACK_KEY_PRESSED_BOTTOM if pressed else BLACK_KEY_BOTTOM
            self._draw_vertical_gradient(
                surface,
                draw_rect,
                self._scale_color(top, self._brightness),
                self._scale_color(bottom, self._brightness),
                steps=9,
                border_radius=radius,
            )

            highlight_h = max(2, int(draw_rect.height * 0.08))
            pygame.draw.rect(
                surface,
                self._scale_color((120, 130, 148), self._brightness),
                pygame.Rect(draw_rect.left + 2, draw_rect.top + 2, max(1, draw_rect.width - 4), highlight_h),
                border_radius=max(1, radius - 1),
            )

            if pressed:
                pygame.draw.line(
                    surface,
                    self._scale_color(ACCENT_LINE, self._brightness),
                    (draw_rect.left + 2, draw_rect.bottom - 3),
                    (draw_rect.right - 3, draw_rect.bottom - 3),
                    2,
                )

            pygame.draw.rect(
                surface,
                self._scale_color(BLACK_KEY_BORDER, self._brightness),
                draw_rect,
                width=1,
                border_radius=radius,
            )
