"""ESP32 LED output settings screen."""

from __future__ import annotations

import threading
from typing import Optional

import pygame
from src import config as cfg
from src.led_output import LedOutput

try:
    from serial.tools import list_ports  # type: ignore
except Exception:
    list_ports = None

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
CHECK_ON_COLOR = (0, 180, 180)

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

PANEL_MARGIN_X = 26
PANEL_GAP = 16

_SWEEP_MS_PER_STEP = 8  # ms between LED steps (~1.4 s for 177 LEDs)


class LedSettingsScreen:
    """UI for LED serial port, baud, and color/mapping tuning."""

    BAUD_OPTIONS = [115200, 230400, 460800, 921600]
    FIELDS = [
        ("fps_limit",      "LED FPS",          5,   120, 1),
        ("mirror_per_key", "LEDs Per Key",      1,     4, 1),
    ]

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._label_font = pygame.font.SysFont("Arial", LABEL_FONT_SIZE)
        self._value_font = pygame.font.SysFont("Arial", VALUE_FONT_SIZE)
        self._btn_font = pygame.font.SysFont("Arial", BTN_FONT_SIZE)

        self._values: dict[str, int | bool | str] = {}
        self._ports: list[str] = []

        self._hover_back = False
        self._hover_slider: int = -1
        self._drag_slider: int = -1
        self._hover_enable = False
        self._hover_port = False
        self._hover_baud = False
        self._hover_refresh = False

        self._title_pos = (0, 0)
        self._left_panel = pygame.Rect(0, 0, 0, 0)
        self._right_panel = pygame.Rect(0, 0, 0, 0)
        self._back_rect = pygame.Rect(0, 0, BACK_W, BACK_H)
        self._row_rects: list[pygame.Rect] = []
        self._slider_rects: list[pygame.Rect] = []

        self._enable_rect = pygame.Rect(0, 0, 28, 28)
        self._port_rect = pygame.Rect(0, 0, 0, 0)
        self._baud_rect = pygame.Rect(0, 0, 0, 0)
        self._refresh_rect = pygame.Rect(0, 0, 0, 0)
        self._preview_bar_rect = pygame.Rect(0, 0, 0, 0)
        self._sweep_rect = pygame.Rect(0, 0, 0, 0)
        self._conn_dot_center: tuple[int, int] = (0, 0)

        # LED output connection state (owned by this screen for test purposes)
        self._led_output: Optional[LedOutput] = None
        self._connecting = False
        self._closed = False
        self._sweep_pos: int = -1
        self._sweep_timer_ms: float = 0.0
        self._hover_sweep = False

        self._load()
        self._refresh_ports()
        self._build_layout()
        self._start_connect()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEMOTION:
            if self._drag_slider >= 0:
                self._set_slider_from_x(self._drag_slider, event.pos[0])
            self._update_hover(event.pos)
            return None

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "back"

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._back_rect.collidepoint(event.pos):
                return "back"

            if self._enable_rect.collidepoint(event.pos):
                self._values["enabled"] = not bool(self._values["enabled"])
                self._save()
                return None

            if self._refresh_rect.collidepoint(event.pos):
                self._refresh_ports()
                return None

            if self._port_rect.collidepoint(event.pos):
                self._cycle_port()
                return None

            if self._baud_rect.collidepoint(event.pos):
                self._cycle_baud()
                return None

            for i, rect in enumerate(self._slider_rects):
                if rect.inflate(0, 18).collidepoint(event.pos):
                    self._drag_slider = i
                    self._set_slider_from_x(i, event.pos[0])
                    return None

            if self._sweep_rect.collidepoint(event.pos):
                if bool(self._values.get("enabled", False)) and not self._connecting:
                    if self._led_output is not None and self._led_output.connected:
                        if self._sweep_pos < 0:
                            self._sweep_pos = 0
                            self._sweep_timer_ms = 0.0
                    else:
                        if self._led_output is not None:
                            self._led_output.close()
                            self._led_output = None
                        self._start_connect()
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
        full = cfg.load()
        data = full.get("led_output", {})
        note = full.get("note_style", {})
        self._values = {
            "enabled": bool(data.get("enabled", False)),
            "port": str(data.get("port", "COM5")),
            "baudrate": int(data.get("baudrate", 115200)),
            "led_count": int(data.get("led_count", 176)),
            "fps_limit": int(data.get("fps_limit", 30)),
            "mirror_per_key": int(data.get("mirror_per_key", 2)),
            # Active colour tracks note colour — not stored separately
            "active_r": int(note.get("color_r", 0)),
            "active_g": int(note.get("color_g", 230)),
            "active_b": int(note.get("color_b", 230)),
        }

    def _save(self) -> None:
        data = cfg.load()
        # Merge — only overwrite fields this screen owns; preserve transport/ble_* etc.
        # active_r/g/b are NOT saved here — they track note colour at runtime.
        data.setdefault("led_output", {}).update({
            "enabled": bool(self._values["enabled"]),
            "port": str(self._values["port"]),
            "baudrate": int(self._values["baudrate"]),
            "led_count": int(self._values["led_count"]),
            "mirror_per_key": int(self._values["mirror_per_key"]),
            "fps_limit": int(self._values["fps_limit"]),
        })
        cfg.save(data)

    def _refresh_ports(self) -> None:
        if list_ports is None:
            self._ports = []
            return
        try:
            self._ports = [p.device for p in list_ports.comports()]
        except Exception:
            self._ports = []

    def _cycle_port(self) -> None:
        if not self._ports:
            return
        current = str(self._values["port"])
        if current not in self._ports:
            self._values["port"] = self._ports[0]
            self._save()
            return
        i = self._ports.index(current)
        self._values["port"] = self._ports[(i + 1) % len(self._ports)]
        self._save()

    def _cycle_baud(self) -> None:
        current = int(self._values["baudrate"])
        if current not in self.BAUD_OPTIONS:
            self._values["baudrate"] = self.BAUD_OPTIONS[0]
            self._save()
            return
        i = self.BAUD_OPTIONS.index(current)
        self._values["baudrate"] = self.BAUD_OPTIONS[(i + 1) % len(self.BAUD_OPTIONS)]
        self._save()

    def _build_layout(self) -> None:
        sr = self.screen.get_rect()
        cx = sr.centerx

        title_surf = self._title_font.render("LED Settings", True, TITLE_COLOR)
        title_y = sr.height // 14
        self._title_pos = (cx - title_surf.get_width() // 2, title_y)
        self._title_surf = title_surf

        content_top = title_y + title_surf.get_height() + 20
        content_bottom = sr.height - BACK_H - 34
        content_h = max(200, content_bottom - content_top)

        content_w = sr.width - 2 * PANEL_MARGIN_X
        half_w = (content_w - PANEL_GAP) // 2

        self._left_panel = pygame.Rect(PANEL_MARGIN_X, content_top, half_w, content_h)
        self._right_panel = pygame.Rect(self._left_panel.right + PANEL_GAP, content_top, half_w, content_h)

        self._row_rects = []
        self._slider_rects = []
        y = self._left_panel.top + 12
        row_w = self._left_panel.width - 24
        total_gaps = ROW_GAP * (len(self.FIELDS) - 1)
        max_row_h = (self._left_panel.height - 24 - total_gaps) // max(1, len(self.FIELDS))
        row_h = max(40, min(ROW_H, max_row_h))
        slider_bottom_pad = max(10, min(16, row_h // 3))
        for _ in self.FIELDS:
            row = pygame.Rect(self._left_panel.left + 12, y, row_w, row_h)
            slider = pygame.Rect(row.left + 4, row.bottom - slider_bottom_pad, row.width - 8, SLIDER_H)
            self._row_rects.append(row)
            self._slider_rects.append(slider)
            y += row_h + ROW_GAP

        rp = self._right_panel
        self._enable_rect = pygame.Rect(rp.left + 20, rp.top + 26, 28, 28)
        self._port_rect = pygame.Rect(rp.left + 20, rp.top + 78, rp.width - 40, 46)
        self._baud_rect = pygame.Rect(rp.left + 20, rp.top + 134, rp.width - 40, 46)
        self._refresh_rect = pygame.Rect(rp.left + 20, rp.top + 190, rp.width - 40, 46)

        self._back_rect = pygame.Rect(cx - BACK_W // 2, sr.height - BACK_H - 24, BACK_W, BACK_H)

        preview_y = self._refresh_rect.bottom + 90
        self._preview_bar_rect = pygame.Rect(rp.left + 20, preview_y, rp.width - 40, 24)
        self._sweep_rect = pygame.Rect(rp.left + 20, self._preview_bar_rect.bottom + 14, rp.width - 40, 46)
        self._conn_dot_center = (rp.right - 18, rp.top + 18)

    def _update_hover(self, pos: tuple[int, int]) -> None:
        self._hover_back = self._back_rect.collidepoint(pos)
        self._hover_enable = self._enable_rect.collidepoint(pos)
        self._hover_port = self._port_rect.collidepoint(pos)
        self._hover_baud = self._baud_rect.collidepoint(pos)
        self._hover_refresh = self._refresh_rect.collidepoint(pos)
        self._hover_sweep = self._sweep_rect.collidepoint(pos)
        self._hover_slider = -1
        for i, rect in enumerate(self._slider_rects):
            if rect.inflate(0, 18).collidepoint(pos):
                self._hover_slider = i
                break

    def _set_slider_from_x(self, index: int, mouse_x: int) -> None:
        rect = self._slider_rects[index]
        key, _label, min_v, max_v, step = self.FIELDS[index]
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

    def _draw_title(self) -> None:
        self.screen.blit(self._title_surf, self._title_pos)

    def _draw_rows(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._left_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._left_panel, width=1, border_radius=8)

        for i, (key, label, _min_v, _max_v, _step) in enumerate(self.FIELDS):
            row = self._row_rects[i]
            slider = self._slider_rects[i]

            pygame.draw.rect(self.screen, BG_COLOR, row, border_radius=6)
            pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, row, width=1, border_radius=6)

            label_surf = self._label_font.render(label, True, TEXT_COLOR)
            self.screen.blit(label_surf, (row.left + 10, row.top + 6))

            value_surf = self._value_font.render(str(int(self._values[key])), True, MUTED_TEXT_COLOR)
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

    def _draw_right_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, self._right_panel, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._right_panel, width=1, border_radius=8)

        title = self._label_font.render("Output", True, TEXT_COLOR)
        self.screen.blit(title, (self._right_panel.left + 16, self._right_panel.top + 14))

        # Connection status dot (top-right of panel)
        if not bool(self._values.get("enabled", False)):
            _dot_color = (70, 70, 90)      # gray  — disabled
        elif self._connecting:
            _dot_color = (230, 160, 0)     # amber — connecting
        elif self._led_output is not None and self._led_output.connected:
            _dot_color = (0, 200, 80)      # green — connected
        else:
            _dot_color = (200, 50, 50)     # red   — disconnected
        pygame.draw.circle(self.screen, _dot_color, self._conn_dot_center, 7)
        pygame.draw.circle(self.screen, (40, 40, 60), self._conn_dot_center, 7, width=1)

        cb_bg = (45, 45, 60) if self._hover_enable else (35, 35, 45)
        pygame.draw.rect(self.screen, cb_bg, self._enable_rect, border_radius=5)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._enable_rect, width=1, border_radius=5)
        if bool(self._values["enabled"]):
            pygame.draw.rect(self.screen, CHECK_ON_COLOR, self._enable_rect.inflate(-8, -8), border_radius=3)
        enabled_txt = self._value_font.render("Enable LED Serial Output", True, MUTED_TEXT_COLOR)
        self.screen.blit(enabled_txt, (self._enable_rect.right + 10, self._enable_rect.top + 2))

        self._draw_action_row(self._port_rect, self._hover_port, f"Port: {self._values['port']}")
        self._draw_action_row(self._baud_rect, self._hover_baud, f"Baud: {self._values['baudrate']}")
        ports_label = f"Refresh Ports ({len(self._ports)})"
        self._draw_action_row(self._refresh_rect, self._hover_refresh, ports_label)

        info = self._label_font.render("Mapping: 88 keys x LEDs/Key", True, MUTED_TEXT_COLOR)
        self.screen.blit(info, (self._right_panel.left + 20, self._refresh_rect.bottom + 20))

        led_count = int(self._values["mirror_per_key"]) * 88
        count_txt = self._value_font.render(f"LED Count: {led_count}", True, TEXT_COLOR)
        self.screen.blit(count_txt, (self._right_panel.left + 20, self._refresh_rect.bottom + 54))

        pygame.draw.rect(self.screen, (20, 20, 24), self._preview_bar_rect, border_radius=6)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._preview_bar_rect, width=1, border_radius=6)
        note_c = (int(self._values["active_r"]), int(self._values["active_g"]), int(self._values["active_b"]))
        note_bar = pygame.Rect(self._preview_bar_rect.left + 2, self._preview_bar_rect.top + 3, self._preview_bar_rect.width - 4, self._preview_bar_rect.height - 6)
        pygame.draw.rect(self.screen, note_c, note_bar, border_radius=4)

        # Sweep test / connect button
        if bool(self._values.get("enabled", False)):
            if self._connecting:
                self._draw_action_row(self._sweep_rect, False, "Connecting...")
            elif self._led_output is not None and self._led_output.connected:
                if self._sweep_pos >= 0:
                    led_count = int(self._values["mirror_per_key"]) * 88
                    self._draw_action_row(self._sweep_rect, False, f"Sweeping {self._sweep_pos}/{led_count}")
                else:
                    self._draw_action_row(self._sweep_rect, self._hover_sweep, "Sweep Test")
            else:
                self._draw_action_row(self._sweep_rect, self._hover_sweep, "Reconnect")

    def _draw_action_row(self, rect: pygame.Rect, hover: bool, text: str) -> None:
        bg = BUTTON_HOVER_BG if hover else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if hover else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, rect, width=1, border_radius=8)
        label = self._value_font.render(text, True, fg)
        self.screen.blit(label, label.get_rect(center=rect.center))

    def _value_ratio(self, index: int) -> float:
        key, _label, min_v, max_v, _step = self.FIELDS[index]
        span = max(1, max_v - min_v)
        return (int(self._values[key]) - min_v) / float(span)

    # ------------------------------------------------------------------
    # BLE/Serial test connection
    # ------------------------------------------------------------------

    def update(self, dt: int) -> None:
        """Called every frame from App._update while this screen is active."""
        if self._sweep_pos < 0:
            return
        if self._led_output is None or not self._led_output.connected:
            self._sweep_pos = -1
            return

        self._sweep_timer_ms += dt
        if self._sweep_timer_ms < _SWEEP_MS_PER_STEP:
            return
        self._sweep_timer_ms -= _SWEEP_MS_PER_STEP

        led_count = int(self._values["mirror_per_key"]) * 88
        if self._sweep_pos >= led_count:
            blank = f"LEDS,{led_count}," + ",".join(["0,0,0"] * led_count) + "\n"
            self._led_output.send_raw(blank.encode())
            self._sweep_pos = -1
            return

        leds = ["0,0,0"] * led_count
        leds[self._sweep_pos] = "255,0,0"
        frame = f"LEDS,{led_count}," + ",".join(leds) + "\n"
        self._led_output.send_raw(frame.encode())
        self._sweep_pos += 1

    def cleanup(self) -> None:
        """Release the LED connection.  Call before discarding this screen."""
        self._closed = True
        self._sweep_pos = -1
        if self._led_output is not None:
            if self._led_output.connected:
                try:
                    led_count = int(self._values["mirror_per_key"]) * 88
                    blank = f"LEDS,{led_count}," + ",".join(["0,0,0"] * led_count) + "\n"
                    self._led_output.send_raw(blank.encode())
                except Exception:
                    pass
            self._led_output.close()
            self._led_output = None
        self._connecting = False

    def _start_connect(self) -> None:
        if self._connecting or self._closed:
            return
        if not bool(self._values.get("enabled", False)):
            return
        self._connecting = True
        t = threading.Thread(target=self._do_connect, daemon=True)
        t.start()

    def _do_connect(self) -> None:
        try:
            lo = LedOutput.from_config()
            lo.connect()
            if self._closed:
                lo.close()
                return
            old = self._led_output
            self._led_output = lo
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self._connecting = False

    def _draw_back(self) -> None:
        bg = BUTTON_HOVER_BG if self._hover_back else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self._hover_back else BUTTON_TEXT_COLOR
        pygame.draw.rect(self.screen, bg, self._back_rect, border_radius=8)
        pygame.draw.rect(self.screen, BUTTON_BORDER_COLOR, self._back_rect, width=1, border_radius=8)
        surf = self._btn_font.render("BACK", True, fg)
        self.screen.blit(surf, surf.get_rect(center=self._back_rect.center))
