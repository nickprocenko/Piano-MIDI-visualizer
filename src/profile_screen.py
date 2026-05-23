"""Profile save/load screen — save and restore complete app configurations."""

from __future__ import annotations

import json
import pathlib
import pygame
from src import config as cfg

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
INPUT_ACTIVE_BORDER = (0, 180, 180)
LOAD_BG = (25, 55, 55)
LOAD_BG_HOVER = (40, 80, 80)
LOAD_TEXT = (110, 215, 210)
DEL_BG = (58, 25, 25)
DEL_BG_HOVER = (95, 38, 38)
DEL_TEXT = (220, 140, 140)
STATUS_OK_COLOR = (110, 215, 110)
STATUS_ERR_COLOR = (220, 100, 100)

TITLE_FONT_SIZE = 42
LABEL_FONT_SIZE = 22
BTN_FONT_SIZE = 24
SMALL_FONT_SIZE = 20
BACK_W = 160
BACK_H = 52
PANEL_MARGIN_X = 26
PANEL_GAP = 16
ROW_H = 46
ROW_GAP = 6
LOAD_BTN_W = 72
DEL_BTN_W = 44

_PROFILE_KEYS = (
    "note_style", "keyboard_style", "led_output", "display_style",
    "hardware", "audience_control", "kick_chat", "user_themes",
    "search_folders",
)


def _pick_directory() -> str | None:
    """Open a native folder-picker dialog and return the chosen path."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        folder = filedialog.askdirectory(parent=root, title="Select profiles directory")
        root.destroy()
        return folder if folder else None
    except Exception:
        return None


def _truncate(font: pygame.font.Font, text: str, max_w: int) -> str:
    if font.render(text, True, (0, 0, 0)).get_width() <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        if font.render(text + "…", True, (0, 0, 0)).get_width() <= max_w:
            return text + "…"
    return "…"


class ProfileScreen:
    """
    Screen for saving and loading named configuration profiles to/from a local directory.

    handle_event() returns:
      ``"back"``           — return to Highway
      ``"profile_loaded"`` — profile was loaded; app should refresh in-memory styles
      ``None``             — no action needed
    """

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)
        self._small_font = pygame.font.SysFont("Arial", SMALL_FONT_SIZE)

        self._profiles_dir: str = ""
        self._profiles: list[str] = []  # stems only, sorted

        self._name_input: str = ""
        self._name_active: bool = False

        self._scroll: int = 0
        self._max_scroll: int = 0

        self._status_text: str = ""
        self._status_ok: bool = True

        self._hover_back = False
        self._hover_dir_btn = False
        self._hover_save = False
        self._hover_name_box = False
        self._hover_profile: int = -1
        self._hover_load: int = -1
        self._hover_delete: int = -1

        self._title_pos = (0, 0)
        self._title_surf: pygame.Surface | None = None
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._dir_btn_rect = pygame.Rect(0, 0, 0, 46)
        self._name_input_rect = pygame.Rect(0, 0, 0, 38)
        self._save_btn_rect = pygame.Rect(0, 0, 0, BACK_H)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._list_viewport = pygame.Rect(0, 0, 0, 0)
        self._profile_row_rects: list[pygame.Rect] = []  # in list-local coords
        self._load_btn_rects: list[pygame.Rect] = []
        self._del_btn_rects: list[pygame.Rect] = []

        self._load_state()
        self._build_layout()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            self._update_hover(event.pos)
            return None

        if event.type == pygame.MOUSEWHEEL:
            if self._right_panel.collidepoint(pygame.mouse.get_pos()):
                self._scroll = max(0, min(self._max_scroll, self._scroll - event.y * 20))
            return None

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self._name_active:
                    self._name_active = False
                else:
                    return "back"
            elif self._name_active:
                if event.key == pygame.K_BACKSPACE:
                    self._name_input = self._name_input[:-1]
                elif event.key == pygame.K_RETURN:
                    self._do_save()
                elif event.unicode and event.unicode.isprintable():
                    # Limit filename length
                    if len(self._name_input) < 48:
                        self._name_input += event.unicode
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._dir_btn_rect.collidepoint(event.pos):
                folder = _pick_directory()
                if folder:
                    self._profiles_dir = folder
                    self._save_dir_to_config()
                    self._refresh_profiles()
                    self._scroll = 0
                    self._build_layout()
                return None

            if self._name_input_rect.collidepoint(event.pos):
                self._name_active = True
                return None

            if self._save_btn_rect.collidepoint(event.pos):
                self._do_save()
                return None

            # Check profile list hits (translate screen pos to list-local)
            if self._right_panel.collidepoint(event.pos):
                self._name_active = False
                lx = event.pos[0] - self._list_viewport.x
                ly = event.pos[1] - self._list_viewport.y + self._scroll
                for i, row in enumerate(self._profile_row_rects):
                    if not row.collidepoint(lx, ly):
                        continue
                    # Check specific buttons
                    if self._del_btn_rects[i].collidepoint(lx, ly):
                        self._do_delete(i)
                        return None
                    if self._load_btn_rects[i].collidepoint(lx, ly):
                        self._do_load(i)
                        return "profile_loaded"
                    # Click anywhere else on row → also load
                    self._do_load(i)
                    return "profile_loaded"
            else:
                self._name_active = False

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        self._draw_left_panel()
        self._draw_right_panel()
        self._draw_back()

    # ------------------------------------------------------------------
    # Private: data
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        data = cfg.load()
        self._profiles_dir = str(data.get("profiles", {}).get("profiles_dir", ""))
        self._refresh_profiles()

    def _refresh_profiles(self) -> None:
        if not self._profiles_dir:
            self._profiles = []
            return
        p = pathlib.Path(self._profiles_dir)
        if p.is_dir():
            self._profiles = sorted(f.stem for f in p.glob("*.json"))
        else:
            self._profiles = []
        self._build_list_rects()

    def _save_dir_to_config(self) -> None:
        data = cfg.load()
        data.setdefault("profiles", {})["profiles_dir"] = self._profiles_dir
        cfg.save(data)

    def _do_save(self) -> None:
        name = self._name_input.strip()
        if not name:
            self._status_text = "Enter a profile name first."
            self._status_ok = False
            return
        if not self._profiles_dir:
            self._status_text = "Choose a directory first."
            self._status_ok = False
            return
        # Sanitise: replace path separators
        safe = name.replace("/", "_").replace("\\", "_").replace(":", "_")
        dest = pathlib.Path(self._profiles_dir) / f"{safe}.json"
        try:
            current = cfg.load()
            profile: dict = {"active_user_theme_index": current.get("active_user_theme_index", 0)}
            for key in _PROFILE_KEYS:
                if key in current:
                    profile[key] = current[key]
            with dest.open("w", encoding="utf-8") as fh:
                json.dump(profile, fh, indent=2)
            self._status_text = f"Saved \"{safe}\""
            self._status_ok = True
            self._refresh_profiles()
            self._build_layout()
        except Exception as exc:
            self._status_text = f"Save failed: {exc}"
            self._status_ok = False

    def _do_load(self, index: int) -> None:
        if index < 0 or index >= len(self._profiles):
            return
        src = pathlib.Path(self._profiles_dir) / f"{self._profiles[index]}.json"
        try:
            with src.open("r", encoding="utf-8") as fh:
                profile = json.load(fh)
            if not isinstance(profile, dict):
                raise ValueError("Invalid profile format")
            data = cfg.load()
            for key in _PROFILE_KEYS:
                if key in profile:
                    data[key] = profile[key]
            if "active_user_theme_index" in profile:
                data["active_user_theme_index"] = profile["active_user_theme_index"]
            cfg.save(data)
            self._status_text = f"Loaded \"{self._profiles[index]}\""
            self._status_ok = True
        except Exception as exc:
            self._status_text = f"Load failed: {exc}"
            self._status_ok = False

    def _do_delete(self, index: int) -> None:
        if index < 0 or index >= len(self._profiles):
            return
        target = pathlib.Path(self._profiles_dir) / f"{self._profiles[index]}.json"
        try:
            target.unlink(missing_ok=True)
            self._status_text = f"Deleted \"{self._profiles[index]}\""
            self._status_ok = True
            self._profiles.pop(index)
            self._scroll = max(0, min(self._max_scroll, self._scroll))
            self._build_list_rects()
        except Exception as exc:
            self._status_text = f"Delete failed: {exc}"
            self._status_ok = False

    # ------------------------------------------------------------------
    # Private: layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("Profiles", True, TITLE_COLOR)
        title_y = sr.height // 10
        self._title_surf = title_surf
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)

        content_top = title_y + title_surf.get_height() + 18
        content_bottom = sr.height - BACK_H - 28
        content_h = max(200, content_bottom - content_top)
        content_w = sr.width - 2 * PANEL_MARGIN_X
        half_w = (content_w - PANEL_GAP) // 2

        self._left_panel = pygame.Rect(PANEL_MARGIN_X, content_top, half_w, content_h)
        self._right_panel = pygame.Rect(self._left_panel.right + PANEL_GAP, content_top, half_w, content_h)

        lp = self._left_panel
        row_w = lp.width - 24

        # Directory button
        self._dir_btn_rect = pygame.Rect(lp.left + 12, lp.top + 44, row_w, 46)
        # Name input
        self._name_input_rect = pygame.Rect(lp.left + 12, self._dir_btn_rect.bottom + 44, row_w, 38)
        # Save button
        self._save_btn_rect = pygame.Rect(lp.left + 12, self._name_input_rect.bottom + 10, row_w, BACK_H)

        self._list_viewport = pygame.Rect(
            self._right_panel.left + 4,
            self._right_panel.top + 4,
            self._right_panel.width - 8,
            self._right_panel.height - 8,
        )

        self._back_rect = pygame.Rect(cx - BACK_W // 2, content_bottom + 10, BACK_W, BACK_H)

        self._build_list_rects()

    def _build_list_rects(self) -> None:
        """(Re)compute profile row rects in list-local coordinates."""
        vp_w = self._list_viewport.width
        self._profile_row_rects = []
        self._load_btn_rects = []
        self._del_btn_rects = []
        y = 4
        for _ in self._profiles:
            row = pygame.Rect(2, y, vp_w - 4, ROW_H)
            load_btn = pygame.Rect(vp_w - LOAD_BTN_W - DEL_BTN_W - 6, y + (ROW_H - 30) // 2, LOAD_BTN_W, 30)
            del_btn = pygame.Rect(vp_w - DEL_BTN_W - 2, y + (ROW_H - 30) // 2, DEL_BTN_W, 30)
            self._profile_row_rects.append(row)
            self._load_btn_rects.append(load_btn)
            self._del_btn_rects.append(del_btn)
            y += ROW_H + ROW_GAP
        total_h = y
        visible_h = self._list_viewport.height
        self._max_scroll = max(0, total_h - visible_h)
        self._scroll = min(self._scroll, self._max_scroll)

    # ------------------------------------------------------------------
    # Private: hover tracking
    # ------------------------------------------------------------------

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_dir_btn = self._dir_btn_rect.collidepoint(pos)
        self._hover_save = self._save_btn_rect.collidepoint(pos)
        self._hover_name_box = self._name_input_rect.collidepoint(pos)

        self._hover_profile = -1
        self._hover_load = -1
        self._hover_delete = -1
        if self._right_panel.collidepoint(pos):
            lx = pos[0] - self._list_viewport.x
            ly = pos[1] - self._list_viewport.y + self._scroll
            for i, row in enumerate(self._profile_row_rects):
                if row.collidepoint(lx, ly):
                    self._hover_profile = i
                    if self._del_btn_rects[i].collidepoint(lx, ly):
                        self._hover_delete = i
                    elif self._load_btn_rects[i].collidepoint(lx, ly):
                        self._hover_load = i
                    break

    # ------------------------------------------------------------------
    # Private: drawing
    # ------------------------------------------------------------------

    def _draw_title(self) -> None:
        if self._title_surf:
            self.screen.blit(self._title_surf, self._title_pos)

    def _draw_left_panel(self) -> None:
        lp = self._left_panel
        pygame.draw.rect(self.screen, PANEL_BG, lp, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, lp, width=1, border_radius=8)

        # Directory label
        dir_label = self._label_font.render("Profiles Directory", True, MUTED_TEXT_COLOR)
        self.screen.blit(dir_label, (lp.left + 12, lp.top + 12))

        # Directory button
        dir_text = self._profiles_dir if self._profiles_dir else "Choose Directory..."
        dir_text = _truncate(self._small_font, dir_text, self._dir_btn_rect.width - 16)
        db_bg = BUTTON_HOVER_BG if self._hover_dir_btn else BUTTON_NORMAL_BG
        db_fg = BUTTON_HOVER_TEXT_COLOR if self._hover_dir_btn else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, db_bg, self._dir_btn_rect, border_radius=7)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._dir_btn_rect, width=1, border_radius=7)
        ds = self._small_font.render(dir_text, True, db_fg)
        self.screen.blit(ds, ds.get_rect(midleft=(self._dir_btn_rect.left + 8, self._dir_btn_rect.centery)))

        # Name input label
        name_label = self._label_font.render("Save As", True, MUTED_TEXT_COLOR)
        self.screen.blit(name_label, (lp.left + 12, self._name_input_rect.top - name_label.get_height() - 4))

        # Name input box
        inp_border = INPUT_ACTIVE_BORDER if self._name_active else BUTTON_BORDER_COLOR
        pygame.draw.rect(self.screen, BUTTON_NORMAL_BG, self._name_input_rect, border_radius=6)
        pygame.draw.rect(self.screen, inp_border, self._name_input_rect, width=2, border_radius=6)
        display_text = self._name_input + ("|" if self._name_active else "")
        inp_s = self._small_font.render(display_text, True, TEXT_COLOR)
        self.screen.blit(
            inp_s,
            inp_s.get_rect(midleft=(self._name_input_rect.left + 8, self._name_input_rect.centery)),
        )

        # Save button
        sv_bg = BUTTON_HOVER_BG if self._hover_save else BUTTON_NORMAL_BG
        sv_fg = BUTTON_HOVER_TEXT_COLOR if self._hover_save else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, sv_bg, self._save_btn_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._save_btn_rect, width=1, border_radius=8)
        sv_s = self._btn_font.render("SAVE PROFILE", True, sv_fg)
        self.screen.blit(sv_s, sv_s.get_rect(center=self._save_btn_rect.center))

        # Status message
        if self._status_text:
            sc = STATUS_OK_COLOR if self._status_ok else STATUS_ERR_COLOR
            ss = self._small_font.render(self._status_text, True, sc)
            sy = self._save_btn_rect.bottom + 10
            self.screen.blit(ss, (lp.left + 12, sy))

    def _draw_right_panel(self) -> None:
        rp = self._right_panel
        pygame.draw.rect(self.screen, PANEL_BG, rp, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rp, width=1, border_radius=8)

        # Header
        hdr = self._label_font.render(
            f"Saved Profiles ({len(self._profiles)})" if self._profiles_dir else "No directory set",
            True, MUTED_TEXT_COLOR,
        )
        self.screen.blit(hdr, (rp.left + 12, rp.top + 8))

        if not self._profiles:
            if self._profiles_dir:
                empty = self._small_font.render("No profiles found. Save one to get started.", True, MUTED_TEXT_COLOR)
                self.screen.blit(empty, empty.get_rect(center=(rp.centerx, rp.centery)))
            return

        # Clip to viewport and render list with scroll offset
        vp = self._list_viewport
        # Adjust viewport top to be below the header
        hdr_vp = pygame.Rect(vp.left, rp.top + 30, vp.width, rp.bottom - rp.top - 34)

        self.screen.set_clip(hdr_vp)
        for i, name in enumerate(self._profiles):
            row = self._profile_row_rects[i]
            load = self._load_btn_rects[i]
            dl = self._del_btn_rects[i]

            # Translate to screen coordinates
            sx = hdr_vp.left + row.left
            sy = hdr_vp.top + row.top - self._scroll

            if sy + ROW_H < hdr_vp.top or sy > hdr_vp.bottom:
                continue

            row_screen = pygame.Rect(sx, sy, row.width, row.height)
            is_hover = self._hover_profile == i
            rb = BUTTON_HOVER_BG if is_hover else BUTTON_NORMAL_BG
            pygame.draw.rect(self.screen, rb, row_screen, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row_screen, width=1, border_radius=6)

            # Name label
            max_name_w = row.width - LOAD_BTN_W - DEL_BTN_W - 20
            name_text = _truncate(self._small_font, name, max_name_w)
            ns = self._small_font.render(name_text, True, TEXT_COLOR)
            self.screen.blit(ns, ns.get_rect(midleft=(sx + 8, sy + ROW_H // 2)))

            # LOAD button
            lsx = sx + load.left - row.left
            lsy = sy + load.top - row.top
            lb_bg = LOAD_BG_HOVER if self._hover_load == i else LOAD_BG
            load_rect_s = pygame.Rect(lsx, lsy, load.width, load.height)
            pygame.draw.rect(self.screen, lb_bg, load_rect_s, border_radius=5)
            pygame.draw.rect(self.screen, (0, 150, 150), load_rect_s, width=1, border_radius=5)
            ls = self._small_font.render("LOAD", True, LOAD_TEXT)
            self.screen.blit(ls, ls.get_rect(center=load_rect_s.center))

            # DELETE button
            dsx = sx + dl.left - row.left
            dsy = sy + dl.top - row.top
            db_bg2 = DEL_BG_HOVER if self._hover_delete == i else DEL_BG
            del_rect_s = pygame.Rect(dsx, dsy, dl.width, dl.height)
            pygame.draw.rect(self.screen, db_bg2, del_rect_s, border_radius=5)
            pygame.draw.rect(self.screen, (120, 50, 50), del_rect_s, width=1, border_radius=5)
            xs = self._small_font.render("✕", True, DEL_TEXT)
            self.screen.blit(xs, xs.get_rect(center=del_rect_s.center))

        self.screen.set_clip(None)

        # Scrollbar
        if self._max_scroll > 0:
            sb_x = rp.right - 8
            sb_h = hdr_vp.height
            sb_y = hdr_vp.top
            ratio = sb_h / (sb_h + self._max_scroll)
            knob_h = max(20, int(sb_h * ratio))
            knob_y = sb_y + int((sb_h - knob_h) * (self._scroll / max(1, self._max_scroll)))
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, pygame.Rect(sb_x, sb_y, 4, sb_h), border_radius=2)
            pygame.draw.rect(self.screen, BUTTON_HOVER_BG, pygame.Rect(sb_x, knob_y, 4, knob_h), border_radius=2)

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
