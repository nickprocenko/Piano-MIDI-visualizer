import sys
import pathlib
import pygame
from enum import Enum, auto
from typing import Optional

from src import config as cfg
from src.audience_color_client import AudienceColorClient
from src.audience_settings import AudienceSettingsScreen
from src.led_output import LedOutput
from src.midi_input import MidiInput
from src.note_fx import NoteEffectRenderer
from src.piano import Piano
from src.device_select import DeviceSelect
from src.display_settings import DisplaySettingsScreen
from src.keyboard_settings import KeyboardSettingsScreen
from src.led_settings import LedSettingsScreen
from src.notes_settings import NotesSettingsScreen
from src.settings import SettingsScreen
from src.song_select import SongSelect


FREEPLAY_PARTICLE_HEIGHT_PX = 32


class State(Enum):
    MENU = auto()
    DEVICE_SELECT = auto()
    SETTINGS = auto()
    NOTES_SETTINGS = auto()
    KEYBOARD_SETTINGS = auto()
    LED_SETTINGS = auto()
    DISPLAY_SETTINGS = auto()
    AUDIENCE_SETTINGS = auto()
    SONG_SELECT = auto()
    HIGHWAY = auto()


class App:
    """Main application state machine."""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.state = State.MENU
        self.clock = pygame.time.Clock()
        self.running = True

        from src.menu import Menu
        self.menu = Menu(screen)

        self._highway_font: Optional[pygame.font.Font] = None
        self._small_font: Optional[pygame.font.Font] = None
        self._midi: Optional[MidiInput] = None
        self._piano: Optional[Piano] = None
        self._device_select: Optional[DeviceSelect] = None
        self._settings_screen: Optional[SettingsScreen] = None
        self._notes_settings_screen: Optional[NotesSettingsScreen] = None
        self._keyboard_settings_screen: Optional[KeyboardSettingsScreen] = None
        self._led_settings_screen: Optional[LedSettingsScreen] = None
        self._display_settings_screen: Optional[DisplaySettingsScreen] = None
        self._audience_settings_screen: Optional[AudienceSettingsScreen] = None
        self._song_select: Optional[SongSelect] = None
        self._selected_port: int = 0
        self._selected_midi_file: Optional[pathlib.Path] = None
        self._note_style: dict[str, int] = self._load_note_style()
        self._note_style_meta: dict[str, str | bool] = self._load_note_style_meta()
        self._keyboard_style: dict[str, int | bool] = self._load_keyboard_style()
        self._display_style: dict[str, int | str] = self._load_display_style()
        self._highway_surface: Optional[pygame.Surface] = None
        self._prev_active_notes: set[int] = set()
        self._active_note_trails: dict[int, dict[str, float | bool]] = {}
        self._note_trails: list[dict[str, float | bool]] = []
        self._fx_renderer: Optional[NoteEffectRenderer] = None
        self._led_output: Optional[LedOutput] = None
        # Background animation: list of slides, each slide is (frames, durations_ms)
        self._bg_slides: list[tuple[list[pygame.Surface], list[float]]] = []
        self._bg_slide_index: int = 0
        self._bg_slide_ms: float = 0.0
        self._bg_frame_index: int = 0
        self._bg_frame_ms: float = 0.0
        self._audience_client: Optional[AudienceColorClient] = None
        self._color_current = [float(self._note_style["color_r"]), float(self._note_style["color_g"]), float(self._note_style["color_b"])]
        self._color_start = list(self._color_current)
        self._color_target = list(self._color_current)
        self._color_blend_ms = 0
        self._color_blend_elapsed_ms = 0
        self._claire_script_enabled = False
        self._claire_low_eb_seen = False
        self._claire_color_current = list(self._color_current)
        self._claire_color_start = list(self._color_current)
        self._claire_color_target = list(self._color_current)
        self._claire_blend_ms = 0
        self._claire_blend_elapsed_ms = 0
        self._last_dt_ms: int = 0
        self._smoothed_dt_ms: float = 16.67
        self._last_phase: str = "init"
        self._refresh_claire_script_state()

    def run(self) -> None:
        while self.running:
            raw_dt = self.clock.tick(60)
            dt = max(1, min(33, raw_dt))
            self._smoothed_dt_ms = (self._smoothed_dt_ms * 0.85) + (dt * 0.15)
            self._last_dt_ms = dt
            self._last_phase = "events"
            self._handle_events()
            self._last_phase = "update"
            self._update(dt)
            self._last_phase = "draw"
            self._draw()
            self._last_phase = "flip"
            pygame.display.flip()
        self._last_phase = "stopped"

    def get_debug_snapshot(self) -> dict[str, object]:
        """Return a safe runtime snapshot for crash logs."""
        midi_connected = bool(self._midi is not None and self._midi.connected)
        midi_available = bool(self._midi is not None and self._midi.available)
        active_count = 0
        if self._midi is not None and self._midi.connected:
            try:
                active_count = len(self._midi.get_active_notes())
            except Exception:
                active_count = -1

        return {
            "state": self.state.name,
            "last_phase": self._last_phase,
            "last_dt_ms": self._last_dt_ms,
            "selected_port": self._selected_port,
            "selected_midi_file": str(self._selected_midi_file) if self._selected_midi_file else None,
            "midi_connected": midi_connected,
            "midi_available": midi_available,
            "midi_port_name": self._midi.port_name if self._midi is not None else "",
            "piano_initialized": self._piano is not None,
            "active_note_count": active_count,
            "trail_count": len(self._note_trails),
            "active_trail_count": len(self._active_note_trails),
            "prev_active_note_count": len(self._prev_active_notes),
            "note_style": dict(self._note_style),
            "keyboard_style": dict(self._keyboard_style),
            "display_style": dict(self._display_style),
            "led_output_connected": bool(self._led_output is not None and self._led_output.connected),
            "audience_connected": bool(self._audience_client is not None and self._audience_client.connected),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _enter_device_select(self) -> None:
        self._device_select = DeviceSelect(self.screen)
        self._device_select.refresh()

    def _enter_settings(self) -> None:
        self._settings_screen = SettingsScreen(self.screen)

    def _enter_notes_settings(self) -> None:
        self._notes_settings_screen = NotesSettingsScreen(self.screen)

    def _enter_keyboard_settings(self) -> None:
        self._keyboard_settings_screen = KeyboardSettingsScreen(self.screen)

    def _enter_led_settings(self) -> None:
        self._led_settings_screen = LedSettingsScreen(self.screen)

    def _enter_display_settings(self) -> None:
        self._display_settings_screen = DisplaySettingsScreen(self.screen)

    def _toggle_fullscreen(self) -> None:
        data = cfg.load()
        currently_fullscreen = bool(data.get("display_style", {}).get("fullscreen", True))
        new_fullscreen = not currently_fullscreen
        data.setdefault("display_style", {})["fullscreen"] = new_fullscreen
        cfg.save(data)
        if new_fullscreen:
            info = pygame.display.Info()
            new_screen = pygame.display.set_mode(
                (info.current_w, info.current_h),
                pygame.NOFRAME | pygame.FULLSCREEN,
            )
        else:
            new_screen = pygame.display.set_mode((1280, 720), pygame.RESIZABLE)
        self.screen = new_screen
        self.menu = type(self.menu)(self.screen)

    def _enter_audience_settings(self) -> None:
        self._audience_settings_screen = AudienceSettingsScreen(self.screen)

    def _enter_song_select(self) -> None:
        self._song_select = SongSelect(self.screen)

    def _enter_highway(self, midi_file: Optional[pathlib.Path] = None) -> None:
        """Set up MIDI and piano when entering the HIGHWAY state."""
        self._note_style = self._load_note_style()
        self._note_style_meta = self._load_note_style_meta()
        self._keyboard_style = self._load_keyboard_style()
        self._display_style = self._load_display_style()
        self._refresh_claire_script_state()
        self._selected_midi_file = midi_file
        self._piano = Piano(
            self.screen,
            height_percent=int(self._keyboard_style["height_percent"]),
            brightness_percent=int(self._keyboard_style["brightness"]),
            visible=bool(self._keyboard_style["visible"]),
        )
        self._midi = MidiInput()
        self._midi.connect(self._selected_port)
        self._midi.sustain_latch = bool(self._keyboard_style.get("sustain_latch", False))
        self._led_output = LedOutput.from_config()
        self._led_output.connect()
        self._audience_client = AudienceColorClient.from_config()
        self._audience_client.start()
        self._bg_slides = self._load_background_slides()
        self._bg_slide_index = 0
        self._bg_slide_ms = 0.0
        self._bg_frame_index = 0
        self._bg_frame_ms = 0.0
        self._prev_active_notes.clear()
        self._active_note_trails.clear()
        self._note_trails.clear()
        self._fx_renderer = NoteEffectRenderer(self.screen)

    def _leave_highway(self) -> None:
        """Clean up MIDI resources when leaving the HIGHWAY state."""
        if self._midi is not None:
            self._midi.close()
            self._midi = None
        if self._led_output is not None:
            self._led_output.close()
            self._led_output = None
        if self._audience_client is not None:
            self._audience_client.stop()
            self._audience_client = None
        self._bg_slides = []
        self._piano = None
        self._highway_surface = None
        self._prev_active_notes.clear()
        self._active_note_trails.clear()
        self._note_trails.clear()
        self._fx_renderer = None

    def _get_highway_draw_target(self) -> tuple[pygame.Surface, bool]:
        """Return the active highway render surface and whether it is scaled."""
        width_scale = int(self._display_style.get("width_scale_percent", 100))
        if width_scale >= 100:
            self._highway_surface = None
            return self.screen, False

        sw, sh = self.screen.get_size()
        scaled_w = max(1, int(sw * (width_scale / 100.0)))
        desired_size = (scaled_w, sh)
        if self._highway_surface is None or self._highway_surface.get_size() != desired_size:
            self._highway_surface = pygame.Surface(desired_size, pygame.SRCALPHA)
        return self._highway_surface, True

    def _sync_highway_targets(self) -> None:
        """Keep piano and note-fx geometry aligned with the active highway surface."""
        target, _scaled = self._get_highway_draw_target()
        if self._piano is not None:
            self._piano.set_target(target)
        if self._fx_renderer is not None:
            self._fx_renderer.set_target(target)

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._quit()
                return

            if self.state == State.MENU:
                action = self.menu.handle_event(event)
                if action == "select_file":
                    self._enter_song_select()
                    self.state = State.SONG_SELECT
                elif action == "freeplay":
                    self._enter_highway()
                    self.state = State.HIGHWAY
                elif action == "midi_device":
                    self._enter_device_select()
                    self.state = State.DEVICE_SELECT
                elif action == "settings":
                    self._enter_settings()
                    self.state = State.SETTINGS
                elif action == "quit":
                    self._quit()

            elif self.state == State.DEVICE_SELECT:
                if self._device_select is not None:
                    result = self._device_select.handle_event(event)
                    if result == "select":
                        self._selected_port = self._device_select.selected_port
                        self._device_select = None
                        self.state = State.MENU
                    elif result == "back":
                        self._device_select = None
                        self.state = State.MENU

            elif self.state == State.SETTINGS:
                if self._settings_screen is not None:
                    result = self._settings_screen.handle_event(event)
                    if result == "back":
                        self._settings_screen = None
                        self.state = State.MENU
                    elif result == "notes_settings":
                        self._enter_notes_settings()
                        self.state = State.NOTES_SETTINGS
                    elif result == "keyboard_settings":
                        self._enter_keyboard_settings()
                        self.state = State.KEYBOARD_SETTINGS
                    elif result == "led_settings":
                        self._enter_led_settings()
                        self.state = State.LED_SETTINGS
                    elif result == "display_settings":
                        self._enter_display_settings()
                        self.state = State.DISPLAY_SETTINGS
                    elif result == "audience_settings":
                        self._enter_audience_settings()
                        self.state = State.AUDIENCE_SETTINGS

            elif self.state == State.NOTES_SETTINGS:
                if self._notes_settings_screen is not None:
                    result = self._notes_settings_screen.handle_event(event)
                    if result == "back":
                        self._notes_settings_screen = None
                        self.state = State.SETTINGS

            elif self.state == State.KEYBOARD_SETTINGS:
                if self._keyboard_settings_screen is not None:
                    result = self._keyboard_settings_screen.handle_event(event)
                    if result == "back":
                        self._keyboard_style = self._load_keyboard_style()
                        self._keyboard_settings_screen = None
                        self.state = State.SETTINGS

            elif self.state == State.LED_SETTINGS:
                if self._led_settings_screen is not None:
                    result = self._led_settings_screen.handle_event(event)
                    if result == "back":
                        self._led_settings_screen.cleanup()
                        self._led_settings_screen = None
                        self.state = State.SETTINGS

            elif self.state == State.DISPLAY_SETTINGS:
                if self._display_settings_screen is not None:
                    result = self._display_settings_screen.handle_event(event)
                    if result == "back":
                        self._display_style = self._load_display_style()
                        self._display_settings_screen = None
                        self.state = State.SETTINGS
                    elif result == "toggle_fullscreen":
                        self._toggle_fullscreen()
                        # Rebuild the screen after toggling so layout fits new size
                        self._enter_display_settings()

            elif self.state == State.AUDIENCE_SETTINGS:
                if self._audience_settings_screen is not None:
                    result = self._audience_settings_screen.handle_event(event)
                    if result == "back":
                        self._audience_settings_screen = None
                        self.state = State.SETTINGS

            elif self.state == State.SONG_SELECT:
                if self._song_select is not None:
                    result = self._song_select.handle_event(event)
                    if result == "select":
                        chosen = self._song_select.selected_file
                        self._song_select = None
                        self._enter_highway(midi_file=chosen)
                        self.state = State.HIGHWAY
                    elif result == "back":
                        self._song_select = None
                        self.state = State.MENU

            elif self.state == State.HIGHWAY:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._leave_highway()
                        self.state = State.MENU
                    elif event.key == pygame.K_r:
                        # Retry MIDI connection
                        if self._midi is not None and not self._midi.connected:
                            self._midi.connect(self._selected_port)
                    elif self._midi is not None:
                        self._midi.handle_keydown(event.key)
                elif event.type == pygame.KEYUP:
                    if self._midi is not None:
                        self._midi.handle_keyup(event.key)

    def _update(self, dt: int) -> None:
        if self.state == State.NOTES_SETTINGS and self._notes_settings_screen is not None:
            self._notes_settings_screen.update(dt)
            return

        if self.state == State.KEYBOARD_SETTINGS and self._keyboard_settings_screen is not None:
            return

        if self.state == State.LED_SETTINGS and self._led_settings_screen is not None:
            self._led_settings_screen.update(dt)
            return

        if self.state == State.DISPLAY_SETTINGS and self._display_settings_screen is not None:
            return

        if self.state == State.AUDIENCE_SETTINGS and self._audience_settings_screen is not None:
            return

        if self.state != State.HIGHWAY:
            return

        self._sync_highway_targets()

        self._update_audience_color(dt)

        if self._selected_midi_file is not None:
            return
        if self._midi is None or not self._midi.connected or self._piano is None:
            self._prev_active_notes.clear()
            self._active_note_trails.clear()
            self._note_trails.clear()
            return

        active_notes = self._midi.get_active_notes()
        if self._led_output is not None:
            self._led_output.update(active_notes, dt)
        newly_pressed = active_notes - self._prev_active_notes
        released_notes = self._prev_active_notes - active_notes

        self._update_claire_de_lune_script(dt, newly_pressed)

        for note in newly_pressed:
            self._start_note_trail(note)

        for note in released_notes:
            self._release_note_trail(note)

        for note in active_notes:
            self._anchor_note_trail(note)

        self._prev_active_notes = active_notes
        self._update_note_trails(dt)

    def _update_audience_color(self, dt: int) -> None:
        if self._audience_client is None:
            return

        for evt in self._audience_client.drain_events():
            self._color_start = list(self._color_current)
            self._color_target = [float(evt.r), float(evt.g), float(evt.b)]
            self._color_blend_ms = max(20, evt.transition_ms)
            self._color_blend_elapsed_ms = 0

        if self._color_blend_ms > 0 and self._color_blend_elapsed_ms < self._color_blend_ms:
            self._color_blend_elapsed_ms = min(self._color_blend_ms, self._color_blend_elapsed_ms + dt)
            a = self._color_blend_elapsed_ms / float(max(1, self._color_blend_ms))
            smooth = a * a * (3.0 - 2.0 * a)
            self._color_current = [
                self._color_start[0] + (self._color_target[0] - self._color_start[0]) * smooth,
                self._color_start[1] + (self._color_target[1] - self._color_start[1]) * smooth,
                self._color_start[2] + (self._color_target[2] - self._color_start[2]) * smooth,
            ]

        r = max(0, min(255, int(self._color_current[0])))
        g = max(0, min(255, int(self._color_current[1])))
        b = max(0, min(255, int(self._color_current[2])))
        self._note_style["color_r"] = r
        self._note_style["color_g"] = g
        self._note_style["color_b"] = b
        if self._led_output is not None:
            self._led_output.set_active_color(r, g, b)

    def _start_note_trail(self, note: int) -> None:
        if self._piano is None:
            return
        rect = self._piano.get_note_rect(note)
        if rect is None:
            return

        trail = {
            "note": float(note),
            "x": float(rect.centerx),
            "top_y": float(self._note_anchor_y(note)),
            "bottom_y": float(self._note_anchor_y(note)),
            "width": float(max(3, min(rect.width - 2, self._note_style["width_px"]))),
            "render_x": float(rect.centerx),
            "render_top_y": float(self._note_anchor_y(note)),
            "render_bottom_y": float(self._note_anchor_y(note)),
            "render_width": float(max(3, min(rect.width - 2, self._note_style["width_px"]))),
            "released": False,
            "age_ms": 0.0,
        }
        self._active_note_trails[note] = trail
        self._note_trails.append(trail)
        NoteEffectRenderer.spawn_sparks(trail, self._note_style)
        NoteEffectRenderer.spawn_press_smoke(trail, self._note_style)

    def _release_note_trail(self, note: int) -> None:
        trail = self._active_note_trails.pop(note, None)
        if trail is not None:
            trail["released"] = True
            NoteEffectRenderer.spawn_smoke(trail, self._note_style)

    def _anchor_note_trail(self, note: int) -> None:
        if self._piano is None:
            return
        trail = self._active_note_trails.get(note)
        if trail is None:
            return
        rect = self._piano.get_note_rect(note)
        if rect is None:
            return

        trail["x"] = float(rect.centerx)
        trail["bottom_y"] = float(self._note_anchor_y(note))
        trail["width"] = float(max(3, min(rect.width - 2, self._note_style["width_px"])))

    def _note_anchor_y(self, note: int) -> float:
        if self._piano is None:
            return float(self.screen.get_height())
        if not bool(self._keyboard_style.get("visible", True)):
            return float(self.screen.get_height())
        rect = self._piano.get_note_rect(note)
        if rect is None:
            return float(self.screen.get_height())
        return float(rect.top)

    def _update_note_trails(self, dt: int) -> None:
        if not self._note_trails:
            return

        NoteEffectRenderer.update_particles(self._note_trails, dt)

        sim_dt_ms = max(1.0, min(33.0, self._smoothed_dt_ms))
        dy = float(self._note_style["speed_px_per_sec"]) * (sim_dt_ms / 1000.0)
        survivors: list[dict[str, float | bool]] = []
        for trail in self._note_trails:
            trail["age_ms"] = float(trail.get("age_ms", 0.0)) + sim_dt_ms
            trail["top_y"] = float(trail["top_y"]) - dy
            if bool(trail["released"]):
                trail["bottom_y"] = float(trail["bottom_y"]) - dy
            if float(trail["bottom_y"]) > 0:
                survivors.append(trail)
        self._note_trails = survivors

    def _interpolated_trail_for_draw(self, trail: dict[str, float | bool]) -> dict[str, float | bool]:
        """Return a temporally smoothed trail copy for rendering."""
        target_x = float(trail["x"])
        target_top = float(trail["top_y"])
        target_bottom = float(trail["bottom_y"])
        target_width = float(trail["width"])

        render_x = float(trail.get("render_x", target_x))
        render_top = float(trail.get("render_top_y", target_top))
        render_bottom = float(trail.get("render_bottom_y", target_bottom))
        render_width = float(trail.get("render_width", target_width))

        blend = max(0.12, min(0.60, self._smoothed_dt_ms / 34.0))
        render_x += (target_x - render_x) * blend
        render_top += (target_top - render_top) * blend
        render_bottom += (target_bottom - render_bottom) * blend
        render_width += (target_width - render_width) * blend

        trail["render_x"] = render_x
        trail["render_top_y"] = render_top
        trail["render_bottom_y"] = render_bottom
        trail["render_width"] = render_width

        draw_trail = dict(trail)
        draw_trail["x"] = render_x
        draw_trail["top_y"] = render_top
        draw_trail["bottom_y"] = render_bottom
        draw_trail["width"] = render_width
        return draw_trail

    def _draw(self) -> None:
        if self.state == State.MENU:
            self.menu.draw()
        elif self.state == State.DEVICE_SELECT:
            if self._device_select is not None:
                self._device_select.draw()
        elif self.state == State.SETTINGS:
            if self._settings_screen is not None:
                self._settings_screen.draw()
        elif self.state == State.NOTES_SETTINGS:
            if self._notes_settings_screen is not None:
                self._notes_settings_screen.draw()
        elif self.state == State.KEYBOARD_SETTINGS:
            if self._keyboard_settings_screen is not None:
                self._keyboard_settings_screen.draw()
        elif self.state == State.LED_SETTINGS:
            if self._led_settings_screen is not None:
                self._led_settings_screen.draw()
        elif self.state == State.DISPLAY_SETTINGS:
            if self._display_settings_screen is not None:
                self._display_settings_screen.draw()
        elif self.state == State.AUDIENCE_SETTINGS:
            if self._audience_settings_screen is not None:
                self._audience_settings_screen.draw()
        elif self.state == State.SONG_SELECT:
            if self._song_select is not None:
                self._song_select.draw()
        elif self.state == State.HIGHWAY:
            self._draw_highway()

    def _draw_highway(self) -> None:
        self.screen.fill((10, 10, 10))

        # Background always fills the full screen width.
        bg_frame, bg_next_frame, bg_blend = self._advance_background(self._smoothed_dt_ms)
        if bg_frame is not None:
            base_alpha = int(self._display_style.get("background_alpha", 120))
            if bg_next_frame is None or bg_blend <= 0.0:
                bg = pygame.transform.smoothscale(bg_frame, self.screen.get_size())
                bg.set_alpha(base_alpha)
                self.screen.blit(bg, (0, 0))
            else:
                # Slow, soft dissolve with no directional motion.
                bg_a = pygame.transform.smoothscale(bg_frame, self.screen.get_size())
                bg_b = pygame.transform.smoothscale(bg_next_frame, self.screen.get_size())
                bg_a.set_alpha(max(0, min(255, int(base_alpha * (1.0 - bg_blend)))))
                bg_b.set_alpha(max(0, min(255, int(base_alpha * bg_blend))))
                self.screen.blit(bg_a, (0, 0))
                self.screen.blit(bg_b, (0, 0))

        _highway_surf, scaled_mode = self._get_highway_draw_target()

        if self._highway_font is None:
            self._highway_font = pygame.font.SysFont("Arial", 28)
        if self._small_font is None:
            self._small_font = pygame.font.SysFont("Arial", 20)

        screen_rect = self.screen.get_rect()

        if self._midi is None or not self._midi.connected:
            # No MIDI device — show retry message
            if self._midi is not None and not self._midi.available:
                msg = "python-rtmidi not installed. Run: pip install python-rtmidi"
            else:
                msg = "No MIDI device detected. Connect a MIDI device and press R to retry."
            text = self._highway_font.render(msg, True, (220, 100, 100))
            rect = text.get_rect(center=screen_rect.center)
            self.screen.blit(text, rect)
            esc_text = self._small_font.render("Press ESC to return", True, (150, 150, 150))
            esc_rect = esc_text.get_rect(topright=(screen_rect.right - 16, 12))
            self.screen.blit(esc_text, esc_rect)
            return

        # Show overlay text only for song playback mode.
        if self._selected_midi_file is not None:
            device_label = self._small_font.render(
                f"MIDI: {self._midi.port_name}", True, (100, 200, 100)
            )
            self.screen.blit(device_label, (16, 12))

            song_label = self._small_font.render(
                f"Song: {self._selected_midi_file.name}", True, (180, 180, 100)
            )
            self.screen.blit(song_label, (16, 36))

            esc_text = self._small_font.render("Press ESC to return", True, (150, 150, 150))
            esc_rect = esc_text.get_rect(topright=(screen_rect.right - 16, 12))
            self.screen.blit(esc_text, esc_rect)

        # If scaling, draw highway content (trails + piano) onto the scaled surface
        # then blit it centred over the background.  Background is never included.
        orig_screen = self.screen

        if scaled_mode:
            _highway_surf.fill((0, 0, 0, 0))
            self.screen = _highway_surf
            if self._piano is not None:
                self._piano.set_target(_highway_surf)

        if self._selected_midi_file is None:
            self._draw_freeplay_trails()

        # Draw piano with active notes highlighted
        active_notes = self._midi.get_active_notes()
        if self._piano is not None:
            self._piano.draw(active_notes)

        if scaled_mode:
            # Restore all screen references then blit the highway centred.
            self.screen = orig_screen
            if self._piano is not None:
                self._piano.set_target(_highway_surf)
            sw, sh = orig_screen.get_size()
            scaled_w = _highway_surf.get_width()
            orig_screen.blit(_highway_surf, ((sw - scaled_w) // 2, 0))

        if self._audience_client is not None and self._audience_client.connected:
            if self._small_font is None:
                self._small_font = pygame.font.SysFont("Arial", 20)
            live = self._small_font.render("Live", True, (90, 255, 140))
            self.screen.blit(live, (10, self.screen.get_height() - live.get_height() - 8))

    def _draw_freeplay_trails(self) -> None:
        if not self._note_trails or self._fx_renderer is None:
            return

        self._fx_renderer.set_target(self.screen)
        self._fx_renderer.begin_frame()
        for trail in self._note_trails:
            self._fx_renderer.draw_trail(self._interpolated_trail_for_draw(trail), self._note_style)
        self._fx_renderer.end_frame()

    def _load_note_style(self) -> dict[str, int]:
        style = cfg.load().get("note_style", {})
        return {
            "speed_px_per_sec": int(style.get("speed_px_per_sec", 420)),
            "width_px": int(style.get("width_px", 12)),
            "edge_roundness_px": int(style.get("edge_roundness_px", 4)),
            "outer_edge_width_px": int(style.get("outer_edge_width_px", 2)),
            "decay_speed": int(style.get("decay_speed", 80)),
            "decay_value": int(style.get("decay_value", 20)),
            "inner_blend_percent": int(style.get("inner_blend_percent", 35)),
            "glow_strength_percent": int(style.get("glow_strength_percent", 80)),
            "effect_glow_enabled": int(bool(style.get("effect_glow_enabled", 1))),
            "effect_highlight_enabled": int(bool(style.get("effect_highlight_enabled", 1))),
            "effect_sparks_enabled": int(bool(style.get("effect_sparks_enabled", 1))),
            "effect_smoke_enabled": int(bool(style.get("effect_smoke_enabled", 1))),
            "effect_press_smoke_enabled": int(bool(style.get("effect_press_smoke_enabled", 0))),
            "effect_moon_dust_enabled": int(bool(style.get("effect_moon_dust_enabled", 0))),
            "effect_steam_smoke_enabled": int(bool(style.get("effect_steam_smoke_enabled", 0))),
            "effect_halo_pulse_enabled": int(bool(style.get("effect_halo_pulse_enabled", 0))),
            "highlight_strength_percent": int(style.get("highlight_strength_percent", 70)),
            "spark_amount_percent": int(style.get("spark_amount_percent", 100)),
            "smoke_amount_percent": int(style.get("smoke_amount_percent", 100)),
            "press_smoke_amount_percent": int(style.get("press_smoke_amount_percent", 100)),
            "color_r": int(style.get("color_r", 0)),
            "color_g": int(style.get("color_g", 230)),
            "color_b": int(style.get("color_b", 230)),
            "interior_r": int(style.get("interior_r", 120)),
            "interior_g": int(style.get("interior_g", 255)),
            "interior_b": int(style.get("interior_b", 255)),
        }

    def _load_keyboard_style(self) -> dict[str, int | bool]:
        style = cfg.load().get("keyboard_style", {})
        return {
            "height_percent": int(style.get("height_percent", 18)),
            "brightness": int(style.get("brightness", 100)),
            "visible": bool(style.get("visible", True)),
            "sustain_latch": bool(style.get("sustain_latch", False)),
        }

    def _load_note_style_meta(self) -> dict[str, str | bool]:
        style = cfg.load().get("note_style", {})
        return {
            "active_theme_id": str(style.get("active_theme_id", "custom")),
            "experimental_claire_script_enabled": bool(style.get("experimental_claire_script_enabled", 0)),
        }

    def _refresh_claire_script_state(self) -> None:
        theme_id = str(self._note_style_meta.get("active_theme_id", "custom"))
        exp_enabled = bool(self._note_style_meta.get("experimental_claire_script_enabled", False))
        self._claire_script_enabled = exp_enabled and theme_id == "claire_de_lune"
        self._claire_low_eb_seen = False
        base = [
            float(self._note_style["color_r"]),
            float(self._note_style["color_g"]),
            float(self._note_style["color_b"]),
        ]
        self._claire_color_current = list(base)
        self._claire_color_start = list(base)
        self._claire_color_target = list(base)
        self._claire_blend_ms = 0
        self._claire_blend_elapsed_ms = 0

    def _set_claire_color_target(self, r: int, g: int, b: int, transition_ms: int) -> None:
        self._claire_color_start = list(self._claire_color_current)
        self._claire_color_target = [float(r), float(g), float(b)]
        self._claire_blend_ms = max(80, int(transition_ms))
        self._claire_blend_elapsed_ms = 0

    def _update_claire_de_lune_script(self, dt: int, newly_pressed: set[int]) -> None:
        if not self._claire_script_enabled:
            return

        if 27 in newly_pressed and not self._claire_low_eb_seen:
            # Distinct one-off low E-flat bloom color.
            self._claire_low_eb_seen = True
            self._set_claire_color_target(72, 104, 198, 2400)
        elif any(n >= 84 for n in newly_pressed):
            self._set_claire_color_target(196, 226, 255, 1200)
        elif any(72 <= n < 84 for n in newly_pressed):
            self._set_claire_color_target(154, 194, 246, 1300)
        elif any(n <= 45 for n in newly_pressed):
            self._set_claire_color_target(102, 136, 220, 1650)
        elif len(newly_pressed) >= 3:
            self._set_claire_color_target(134, 176, 238, 1000)
        elif newly_pressed:
            self._set_claire_color_target(118, 158, 232, 950)

        if self._claire_blend_ms > 0 and self._claire_blend_elapsed_ms < self._claire_blend_ms:
            self._claire_blend_elapsed_ms = min(self._claire_blend_ms, self._claire_blend_elapsed_ms + dt)
            a = self._claire_blend_elapsed_ms / float(max(1, self._claire_blend_ms))
            smooth = a * a * (3.0 - 2.0 * a)
            self._claire_color_current = [
                self._claire_color_start[0] + (self._claire_color_target[0] - self._claire_color_start[0]) * smooth,
                self._claire_color_start[1] + (self._claire_color_target[1] - self._claire_color_start[1]) * smooth,
                self._claire_color_start[2] + (self._claire_color_target[2] - self._claire_color_start[2]) * smooth,
            ]

        r = max(0, min(255, int(self._claire_color_current[0])))
        g = max(0, min(255, int(self._claire_color_current[1])))
        b = max(0, min(255, int(self._claire_color_current[2])))
        self._note_style["color_r"] = r
        self._note_style["color_g"] = g
        self._note_style["color_b"] = b
        # Keep inner color tied to the scripted tone, but brighter.
        self._note_style["interior_r"] = max(r, min(255, r + 86))
        self._note_style["interior_g"] = max(g, min(255, g + 74))
        self._note_style["interior_b"] = max(b, min(255, b + 48))

    def _load_display_style(self) -> dict[str, int | str]:
        style = cfg.load().get("display_style", {})
        width_scale = int(style.get("width_scale_percent", 66))
        width_scale = max(60, min(80, width_scale))
        return {
            "width_scale_percent": width_scale,
            "background_alpha": int(style.get("background_alpha", 120)),
            "background_image": str(style.get("background_image", "")),
            "background_slideshow_paths": list(style.get("background_slideshow_paths", [])),
            "background_slide_duration_sec": int(style.get("background_slide_duration_sec", 5)),
            "background_transition_percent": int(style.get("background_transition_percent", 35)),
            "gif_speed_percent": int(style.get("gif_speed_percent", 100)),
        }

    @staticmethod
    def _load_image_frames(path: pathlib.Path) -> tuple[list[pygame.Surface], list[float]]:
        """Load an image file into (frames, durations_ms). Animated GIFs use Pillow."""
        if path.suffix.lower() == ".gif":
            try:
                from PIL import Image as _PILImage  # type: ignore
                pil = _PILImage.open(str(path))
                frames: list[pygame.Surface] = []
                durations: list[float] = []
                try:
                    while True:
                        rgba = pil.convert("RGBA")
                        surf = pygame.image.fromstring(rgba.tobytes(), rgba.size, "RGBA").convert_alpha()
                        frames.append(surf)
                        # Some GIFs store 0ms or tiny durations; clamp for stable playback.
                        dur = float(pil.info.get("duration", 100))
                        durations.append(max(16.0, dur))
                        pil.seek(pil.tell() + 1)
                except EOFError:
                    pass
                if frames:
                    return frames, durations
            except ImportError:
                pass  # Pillow not available — fall through to static load
        try:
            img = pygame.image.load(str(path))
            surf = img.convert_alpha() if img.get_alpha() is not None else img.convert()
            return [surf], [1_000_000.0]
        except Exception:
            return [], []

    def _load_background_slides(self) -> list[tuple[list[pygame.Surface], list[float]]]:
        """Build slide list from config. Slideshow paths take priority over single image."""
        slideshow_paths: list[str] = list(self._display_style.get("background_slideshow_paths", []))
        single_path: str = str(self._display_style.get("background_image", ""))

        paths_to_use: list[str] = slideshow_paths if slideshow_paths else ([single_path] if single_path else [])
        slides: list[tuple[list[pygame.Surface], list[float]]] = []
        for p_str in paths_to_use:
            p = pathlib.Path(p_str)
            if p.exists():
                frames, durs = self._load_image_frames(p)
                if frames:
                    slides.append((frames, durs))
        return slides

    def _advance_background(self, dt_ms: float) -> tuple[Optional[pygame.Surface], Optional[pygame.Surface], float]:
        """Advance background timers and return (current_frame, next_frame, blend)."""
        if not self._bg_slides:
            return None, None, 0.0

        slide_dur_ms = max(500.0, float(self._display_style.get("background_slide_duration_sec", 5)) * 1000.0)
        transition_ratio = int(self._display_style.get("background_transition_percent", 35)) / 100.0
        transition_ratio = max(0.10, min(0.90, transition_ratio))
        transition_ms = max(500.0, min(3000.0, slide_dur_ms * transition_ratio))

        # Advance slide if there are multiple slides
        if len(self._bg_slides) > 1:
            self._bg_slide_ms += dt_ms
            while self._bg_slide_ms >= slide_dur_ms:
                self._bg_slide_ms -= slide_dur_ms
                self._bg_slide_index = (self._bg_slide_index + 1) % len(self._bg_slides)
                self._bg_frame_index = 0
                self._bg_frame_ms = 0.0

        frames, durations = self._bg_slides[self._bg_slide_index % len(self._bg_slides)]
        if not frames:
            return None, None, 0.0

        # Advance GIF frame. Speed slider scales playback rate.
        if len(frames) > 1:
            speed_pct = int(self._display_style.get("gif_speed_percent", 100))
            speed_pct = max(10, min(200, speed_pct))
            self._bg_frame_ms += dt_ms * (speed_pct / 100.0)
            while durations and self._bg_frame_ms >= durations[self._bg_frame_index % len(durations)]:
                self._bg_frame_ms -= durations[self._bg_frame_index % len(durations)]
                self._bg_frame_index = (self._bg_frame_index + 1) % len(frames)

        current_frame = frames[self._bg_frame_index % len(frames)]

        # Soft dissolve near the end of the slide interval.
        next_frame: Optional[pygame.Surface] = None
        blend = 0.0
        if len(self._bg_slides) > 1:
            blend_start_ms = slide_dur_ms - transition_ms
            if self._bg_slide_ms >= blend_start_ms:
                t = (self._bg_slide_ms - blend_start_ms) / max(1.0, transition_ms)
                t = max(0.0, min(1.0, t))
                blend = t * t * (3.0 - 2.0 * t)
                next_idx = (self._bg_slide_index + 1) % len(self._bg_slides)
                next_frames, _next_durations = self._bg_slides[next_idx]
                if next_frames:
                    next_frame = next_frames[0]

        return current_frame, next_frame, blend

    def _quit(self) -> None:
        self._leave_highway()
        self.running = False
        pygame.quit()
        sys.exit()
