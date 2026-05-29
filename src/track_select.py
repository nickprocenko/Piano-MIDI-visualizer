"""Track / channel selection screen for Learn Mode."""

from __future__ import annotations

import pathlib
import pygame
from src.midi_player import MidiFilePlayer

BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
SUBTITLE_COLOR = (150, 150, 160)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)
CHECK_ON_COLOR = (0, 180, 180)
MUTED_COLOR = (120, 120, 140)
PLAY_NORMAL_BG = (18, 90, 70)
PLAY_HOVER_BG = (28, 130, 100)
PLAY_BORDER_COLOR = (0, 160, 120)
PLAY_TEXT_COLOR = (160, 255, 210)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 24
SMALL_FONT_SIZE = 20
BTN_FONT_SIZE = 28
ROW_HEIGHT = 54
ROW_GAP = 8
ROW_WIDTH = 660
BACK_BTN_W = 160
BACK_BTN_H = 52
PLAY_BTN_W = 190
PLAY_BTN_H = 52
CHECK_SIZE = 26
BTN_GAP = 20


def _truncate(font: pygame.font.Font, text: str, max_w: int) -> str:
    if font.size(text)[0] <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        if font.size(text + "…")[0] <= max_w:
            return text + "…"
    return "…"


class TrackSelect:
    """
    Shows note-bearing tracks from a MIDI file with enable/disable checkboxes.

    ``handle_event()`` returns:
      ``"play"``  — user confirmed; ``self.enabled_tracks`` contains selected indices.
      ``"back"``  — user pressed BACK or ESC.
      ``None``    — nothing actionable.
    """

    def __init__(self, screen: pygame.Surface, midi_path: pathlib.Path) -> None:
        self.screen = screen
        self.midi_path = midi_path
        self.enabled_tracks: set[int] = set()

        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._small_font = pygame.font.SysFont("Arial", SMALL_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._tracks: list[dict] = []
        self._hover_row: int = -1
        self._hover_back: bool = False
        self._hover_play: bool = False

        self._row_rects: list[pygame.Rect] = []
        self._check_rects: list[pygame.Rect] = []
        self._back_rect = pygame.Rect(0, 0, BACK_BTN_W, BACK_BTN_H)
        self._play_rect = pygame.Rect(0, 0, PLAY_BTN_W, PLAY_BTN_H)
        self._title_surf: pygame.Surface | None = None
        self._title_pos = (0, 0)
        self._subtitle_pos = (0, 0)

        self._load_tracks()
        self._build_layout()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                return "back"
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return "play"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"
            if self._play_rect.collidepoint(event.pos):
                return "play"
            for i, row_rect in enumerate(self._row_rects):
                if row_rect.collidepoint(event.pos):
                    ti = self._tracks[i]["index"]
                    if ti in self.enabled_tracks:
                        if len(self.enabled_tracks) > 1:
                            self.enabled_tracks.discard(ti)
                    else:
                        self.enabled_tracks.add(ti)
                    return None

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_rows()
        self._draw_buttons()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_tracks(self) -> None:
        self._tracks = MidiFilePlayer.get_tracks_info(self.midi_path)
        self.enabled_tracks = {t["index"] for t in self._tracks}
        if not self.enabled_tracks and self._tracks:
            self.enabled_tracks = {self._tracks[0]["index"]}

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Select Tracks", True, TITLE_COLOR)
        title_y = max(16, sr.height // 10)
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        subtitle_y = title_y + title_surf.get_height() + 6
        self._subtitle_pos = (cx, subtitle_y)

        list_top = subtitle_y + self._small_font.get_height() + 28

        self._row_rects = []
        self._check_rects = []
        y = list_top
        for _ in self._tracks:
            row = pygame.Rect(cx - ROW_WIDTH // 2, y, ROW_WIDTH, ROW_HEIGHT)
            check = pygame.Rect(
                row.left + 14,
                row.centery - CHECK_SIZE // 2,
                CHECK_SIZE,
                CHECK_SIZE,
            )
            self._row_rects.append(row)
            self._check_rects.append(check)
            y += ROW_HEIGHT + ROW_GAP

        btn_y = max(y + 24, sr.height - BACK_BTN_H - 24)
        total_btn_w = BACK_BTN_W + BTN_GAP + PLAY_BTN_W
        self._back_rect = pygame.Rect(
            cx - total_btn_w // 2,
            btn_y,
            BACK_BTN_W,
            BACK_BTN_H,
        )
        self._play_rect = pygame.Rect(
            cx - total_btn_w // 2 + BACK_BTN_W + BTN_GAP,
            btn_y,
            PLAY_BTN_W,
            PLAY_BTN_H,
        )

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_play = self._play_rect.collidepoint(pos)
        self._hover_row = -1
        for i, rect in enumerate(self._row_rects):
            if rect.collidepoint(pos):
                self._hover_row = i
                break

    def _draw_title(self) -> None:
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)
        # File name subtitle
        name = _truncate(self._small_font, self.midi_path.name, self.screen.get_width() - 40)
        sub = self._small_font.render(name, True, SUBTITLE_COLOR)
        cx = self._subtitle_pos[0]
        self.screen.blit(sub, sub.get_rect(midtop=(cx, self._subtitle_pos[1])))

    def _draw_rows(self) -> None:
        if not self._tracks:
            sr = self.screen.get_rect()
            msg = self._label_font.render(
                "No note tracks found in this MIDI file.", True, MUTED_COLOR
            )
            self.screen.blit(msg, msg.get_rect(center=sr.center))
            return

        for i, track in enumerate(self._tracks):
            row_rect = self._row_rects[i]
            check_rect = self._check_rects[i]
            hovered = i == self._hover_row
            is_enabled = track["index"] in self.enabled_tracks

            bg = BUTTON_HOVER_BG if hovered else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, bg, row_rect, border_radius=6)
            pygame.draw.rect(
                self.screen, BUTTON_BORDER_COLOR, row_rect, width=1, border_radius=6
            )

            # Checkbox
            cb_bg = (50, 50, 65)
            pygame.draw.rect(self.screen, cb_bg, check_rect, border_radius=4)
            pygame.draw.rect(
                self.screen, BUTTON_BORDER_COLOR, check_rect, width=1, border_radius=4
            )
            if is_enabled:
                inner = check_rect.inflate(-6, -6)
                pygame.draw.rect(self.screen, CHECK_ON_COLOR, inner, border_radius=3)

            # Track name (left-aligned after checkbox)
            max_name_w = row_rect.width - check_rect.width - 24 - 180
            name_text = _truncate(self._label_font, track["name"], max_name_w)
            name_surf = self._label_font.render(name_text, True, BUTTON_TEXT_COLOR)
            self.screen.blit(
                name_surf,
                name_surf.get_rect(midleft=(check_rect.right + 14, row_rect.centery)),
            )

            # Channel / note info (right-aligned)
            chans = track["channels"]
            if chans:
                ch_str = "Ch " + ", ".join(str(c + 1) for c in chans[:4])
                if len(chans) > 4:
                    ch_str += "…"
                info = f"{track['note_count']} notes  ·  {ch_str}"
            else:
                info = f"{track['note_count']} notes"
            info_surf = self._small_font.render(info, True, MUTED_COLOR)
            self.screen.blit(
                info_surf,
                info_surf.get_rect(midright=(row_rect.right - 14, row_rect.centery)),
            )

    def _draw_buttons(self) -> None:
        # BACK
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8
        )
        bs = self._btn_font.render("BACK", True, fg)
        self.screen.blit(bs, bs.get_rect(center=self._back_rect.center))

        # PLAY
        pbg = PLAY_HOVER_BG if self._hover_play else PLAY_NORMAL_BG
        pygame.draw.rect(self.screen, pbg, self._play_rect, border_radius=8)
        pygame.draw.rect(
            self.screen, PLAY_BORDER_COLOR, self._play_rect, width=1, border_radius=8
        )
        ps = self._btn_font.render("▶  PLAY", True, PLAY_TEXT_COLOR)
        self.screen.blit(ps, ps.get_rect(center=self._play_rect.center))
