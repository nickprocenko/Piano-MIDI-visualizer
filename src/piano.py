"""88-key piano keyboard renderer for Pygame."""

from __future__ import annotations

import pygame

# MIDI note range for a standard 88-key piano
PIANO_FIRST_NOTE = 21   # A0
PIANO_LAST_NOTE = 108   # C8
PIANO_NUM_NOTES = PIANO_LAST_NOTE - PIANO_FIRST_NOTE + 1  # 88

# Colours
WHITE_KEY_COLOR = (220, 220, 220)
WHITE_KEY_ACTIVE_COLOR = (0, 210, 210)    # cyan highlight
WHITE_KEY_BORDER_COLOR = (60, 60, 60)
BLACK_KEY_COLOR = (20, 20, 20)
BLACK_KEY_ACTIVE_COLOR = (0, 160, 160)    # darker cyan highlight
PIANO_BG_COLOR = (30, 30, 30)

# Which semitone offsets within an octave are black keys
# (C=0, C#=1, D=2, D#=3, E=4, F=5, F#=6, G=7, G#=8, A=9, A#=10, B=11)
_BLACK_SEMITONES = {1, 3, 6, 8, 10}

# Proportions for black key dimensions relative to white key size
BLACK_KEY_WIDTH_RATIO = 0.60
BLACK_KEY_HEIGHT_RATIO = 0.62

# Black-key horizontal offset (as a fraction of white key width) per semitone
# These centre the black keys over the correct position between white keys.
_BLACK_OFFSET_FRAC: dict[int, float] = {
    1:  0.60,   # C#  — after C
    3:  1.65,   # D#  — after D
    6:  3.60,   # F#  — after F
    8:  4.65,   # G#  — after G
    10: 5.70,   # A#  — after A
}


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

    def __init__(self, screen: pygame.Surface) -> None:
        self._screen = screen
        self._rect: pygame.Rect | None = None
        self._white_rects: dict[int, pygame.Rect] = {}   # note → Rect
        self._black_rects: dict[int, pygame.Rect] = {}   # note → Rect
        self._build_layout()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draw(self, active_notes: set[int]) -> None:
        """Draw the full keyboard; highlight keys present in *active_notes*."""
        surface = self._screen
        if self._rect is None:
            return

        # Background
        pygame.draw.rect(surface, PIANO_BG_COLOR, self._rect)

        # White keys first
        for note, rect in self._white_rects.items():
            color = WHITE_KEY_ACTIVE_COLOR if note in active_notes else WHITE_KEY_COLOR
            pygame.draw.rect(surface, color, rect)
            pygame.draw.rect(surface, WHITE_KEY_BORDER_COLOR, rect, width=1)

        # Black keys on top
        for note, rect in self._black_rects.items():
            color = BLACK_KEY_ACTIVE_COLOR if note in active_notes else BLACK_KEY_COLOR
            pygame.draw.rect(surface, color, rect)

    def on_resize(self) -> None:
        """Call when the screen size changes to recompute key geometry."""
        self._build_layout()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        sw, sh = self._screen.get_size()
        piano_h = int(sh * self.HEIGHT_FRACTION)
        piano_y = sh - piano_h

        self._rect = pygame.Rect(0, piano_y, sw, piano_h)

        num_white = _count_white_keys(PIANO_FIRST_NOTE, PIANO_LAST_NOTE)
        white_w = sw / num_white
        white_h = piano_h

        black_w = white_w * BLACK_KEY_WIDTH_RATIO
        black_h = white_h * BLACK_KEY_HEIGHT_RATIO

        self._white_rects = {}
        self._black_rects = {}

        white_index = 0  # running index of white keys drawn so far

        for note in range(PIANO_FIRST_NOTE, PIANO_LAST_NOTE + 1):
            semitone = note % 12
            if not _is_black(note):
                x = white_index * white_w
                rect = pygame.Rect(int(x), piano_y, max(1, int(white_w) - 1), white_h)
                self._white_rects[note] = rect
                white_index += 1
            else:
                # Find the octave-start white-key index for this note.
                # C of this octave sits at the start of the octave block.
                octave = note // 12
                c_note = octave * 12  # MIDI number of this octave's C

                # Count how many white keys came before this octave's C
                whites_before_c = sum(
                    1 for n in range(PIANO_FIRST_NOTE, c_note) if not _is_black(n)
                )

                # Black key x is relative to the octave's C position
                offset_frac = _BLACK_OFFSET_FRAC.get(semitone, 0.0)
                x = (whites_before_c + offset_frac) * white_w - black_w / 2
                rect = pygame.Rect(int(x), piano_y, max(1, int(black_w)), black_h)
                self._black_rects[note] = rect
