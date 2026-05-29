import queue
import sys
import pathlib
import time
import pygame
from enum import Enum, auto
from typing import Optional

from src import config as cfg
from src.control_server import ControlServer
from src.audience_color_client import AudienceColorClient
from src.audience_settings import AudienceSettingsScreen
from src.kick_chat_client import KickChatClient
from src.led_output import LedOutput
from src.midi_input import MidiInput
from src.note_fx import NoteEffectRenderer
from src.piano import Piano
from src.device_select import DeviceSelect
from src.display_settings import DisplaySettingsScreen
from src.keyboard_settings import KeyboardSettingsScreen
from src.hardware_settings import HardwareSettingsScreen
from src.led_settings import LedSettingsScreen
from src.notes_settings import NotesSettingsScreen
from src.profile_screen import ProfileScreen
from src.settings import SettingsScreen
from src.song_select import SongSelect
from src.theme_settings import ThemeSettingsScreen
from src.trail_constants import TRAIL_KEY_EDGE_INSET_PX, TRAIL_MIN_WIDTH_PX
import src.themes as themes_mod

try:
    from src.midi_player import MidiFilePlayer as _MidiFilePlayer
    from src.track_select import TrackSelect as _TrackSelect
    _MIDO_AVAILABLE = True
except ImportError:
    _MIDO_AVAILABLE = False
    _MidiFilePlayer = None  # type: ignore
    _TrackSelect = None  # type: ignore

try:
    from src.fluid_web_bridge import FluidWebBridge as _FluidWebBridge
    _FLUID_AVAILABLE = True
except ImportError:
    _FLUID_AVAILABLE = False
    _FluidWebBridge = None  # type: ignore

# Fluid UI params are stored as integers; dividing by this scale gives the
# float value passed to the simulation (e.g. stored 22 → sim 2.2).
_FLUID_DISSIPATION_SCALE = 10.0
# Fluid pressure is stored 0–100 and maps to sim range 0.0–1.0.
_FLUID_PRESSURE_SCALE = 100.0


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
    THEME_SETTINGS = auto()
    HARDWARE_SETTINGS = auto()
    PROFILE_SCREEN = auto()
    SONG_SELECT = auto()
    TRACK_SELECT = auto()
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
        self._theme_settings_screen: Optional[ThemeSettingsScreen] = None
        self._hardware_settings_screen: Optional[HardwareSettingsScreen] = None
        self._profile_screen: Optional[ProfileScreen] = None
        self._profile_btn_hover: bool = False
        self._profile_btn_rect: pygame.Rect = pygame.Rect(0, 0, 120, 32)
        self._song_select: Optional[SongSelect] = None
        self._track_select: Optional[object] = None
        self._selected_port: int = int(cfg.load().get("hardware", {}).get("selected_midi_port", 0))
        self._device_select_return_state: State = State.MENU
        self._selected_midi_file: Optional[pathlib.Path] = None
        self._enabled_tracks: Optional[set[int]] = None
        self._midi_player: Optional[object] = None
        self._note_style: dict[str, int] = self._load_note_style()
        self._note_style_meta: dict[str, str | bool] = self._load_note_style_meta()
        self._keyboard_style: dict[str, int | bool] = self._load_keyboard_style()
        self._display_style: dict[str, int | str] = self._load_display_style()
        self._hardware: dict = self._load_hardware()
        self._highway_surface: Optional[pygame.Surface] = None
        self._prev_active_notes: set[int] = set()
        self._active_note_trails: dict[int, dict[str, float | bool]] = {}
        self._note_trails: list[dict[str, float | bool]] = []
        self._fx_renderer: Optional[NoteEffectRenderer] = None
        self._fluid_renderer: Optional[object] = None
        self._led_output: Optional[LedOutput] = None
        # Background animation: list of slides, each slide is (frames, durations_ms)
        self._bg_slides: list[tuple[list[pygame.Surface], list[float], dict]] = []
        self._bg_slide_index: int = 0
        self._bg_slide_ms: float = 0.0
        self._bg_frame_index: int = 0
        self._bg_frame_ms: float = 0.0
        self._audience_client: Optional[AudienceColorClient] = None
        self._kick_client: Optional[KickChatClient] = None
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
        self._sustain_tap_times: list[float] = []
        self._refresh_claire_script_state()

        self._control_patches: queue.SimpleQueue = queue.SimpleQueue()
        self._control_server = ControlServer(self._control_patches, self._get_panel_state)
        self._control_server.start()

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

    def _enter_theme_settings(self) -> None:
        self._theme_settings_screen = ThemeSettingsScreen(self.screen)

    def _cycle_theme(self) -> None:
        """Advance to the next user theme (wraps around).  Called on triple sustain-tap."""
        user_themes = themes_mod.load_user_themes()
        if not user_themes:
            return
        idx = themes_mod.get_active_index()
        idx = (idx + 1) % len(user_themes)
        themes_mod.set_active_index(idx)
        themes_mod.apply_theme_to_config(user_themes[idx])
        self._apply_theme_to_live(user_themes[idx])

    def _apply_theme_to_live(self, theme: dict) -> None:
        """Immediately update in-memory note style and LED colors from a theme dict."""
        patch = themes_mod.build_live_note_style_patch(theme)
        self._note_style.update(patch)

        # Reset colour animation to the new note base colour
        new_r = float(self._note_style.get("color_r", 0))
        new_g = float(self._note_style.get("color_g", 230))
        new_b = float(self._note_style.get("color_b", 230))
        self._color_current = [new_r, new_g, new_b]
        self._color_start   = [new_r, new_g, new_b]
        self._color_target  = [new_r, new_g, new_b]
        self._color_blend_ms = 0
        self._color_blend_elapsed_ms = 0

        # Disable claire script so it can't override note colours each frame
        self._note_style_meta["active_theme_id"] = "custom"
        self._note_style_meta["experimental_claire_script_enabled"] = False
        self._refresh_claire_script_state()

        # Apply LED colour immediately (don't wait for next _update_audience_color tick)
        if self._led_output is not None:
            self._led_output.set_active_color(int(new_r), int(new_g), int(new_b))

    def _enter_song_select(self) -> None:
        self._song_select = SongSelect(self.screen)

    def _enter_track_select(self, midi_path: pathlib.Path) -> None:
        if _TrackSelect is not None:
            self._track_select = _TrackSelect(self.screen, midi_path)
        else:
            self._track_select = None

    def _enter_highway(
        self,
        midi_file: Optional[pathlib.Path] = None,
        enabled_tracks: Optional[set[int]] = None,
    ) -> None:
        """Set up MIDI and piano when entering the HIGHWAY state."""
        self._note_style = self._load_note_style()
        self._note_style_meta = self._load_note_style_meta()
        self._keyboard_style = self._load_keyboard_style()
        self._display_style = self._load_display_style()
        self._refresh_claire_script_state()
        self._selected_midi_file = midi_file
        self._enabled_tracks = enabled_tracks
        if midi_file is not None and _MIDO_AVAILABLE and _MidiFilePlayer is not None:
            self._midi_player = _MidiFilePlayer(midi_file, enabled_tracks=enabled_tracks)
        else:
            self._midi_player = None
        self._piano = Piano(
            self.screen,
            height_percent=int(self._keyboard_style["height_percent"]),
            brightness_percent=int(self._keyboard_style["brightness"]),
            visible=bool(self._keyboard_style["visible"]),
        )
        self._midi = MidiInput()
        self._midi.connect(self._selected_port)
        self._midi.set_sustain_enabled(bool(self._hardware.get("sustain_enabled", False)))
        self._led_output = LedOutput.from_config()
        self._led_output.connect()
        self._audience_client = AudienceColorClient.from_config()
        self._audience_client.start()
        self._kick_client = KickChatClient.from_config()
        self._kick_client.start()
        self._bg_slides = self._load_background_slides()
        self._bg_slide_index = 0
        self._bg_slide_ms = 0.0
        self._bg_frame_index = 0
        self._bg_frame_ms = 0.0
        self._prev_active_notes.clear()
        self._active_note_trails.clear()
        self._note_trails.clear()
        self._fx_renderer = NoteEffectRenderer(self.screen)
        if _FLUID_AVAILABLE and self._note_style.get("effect_fluid_enabled", 0):
            sw, sh = self.screen.get_size()
            wx, wy = self._get_window_position()
            bridge = _FluidWebBridge(
                wx, wy, sw, sh,
                curl_strength=float(self._note_style.get("fluid_curl", 30)),
                vel_dissipation=float(self._note_style.get("fluid_velocity_dissipation", 7)) / _FLUID_DISSIPATION_SCALE,
                dye_dissipation=float(self._note_style.get("fluid_density_dissipation", 22)) / _FLUID_DISSIPATION_SCALE,
                pressure=float(self._note_style.get("fluid_pressure", 80)) / _FLUID_PRESSURE_SCALE,
            )
            self._fluid_renderer = bridge if bridge.available else None
        else:
            self._fluid_renderer = None

    def _leave_highway(self) -> None:
        """Clean up MIDI resources when leaving the HIGHWAY state."""
        self._midi_player = None
        if self._midi is not None:
            self._midi.close()
            self._midi = None
        if self._led_output is not None:
            self._led_output.close()
            self._led_output = None
        if self._audience_client is not None:
            self._audience_client.stop()
            self._audience_client = None
        if self._kick_client is not None:
            self._kick_client.stop()
            self._kick_client = None
        self._bg_slides = []
        self._piano = None
        self._highway_surface = None
        self._prev_active_notes.clear()
        self._active_note_trails.clear()
        self._note_trails.clear()
        self._fx_renderer = None
        if self._fluid_renderer is not None:
            self._fluid_renderer.destroy()
            self._fluid_renderer = None

    def _get_window_position(self) -> tuple[int, int]:
        """Return the top-left screen position of the pygame window.

        Used to position the WebGL fluid overlay on top of the pygame window.
        Falls back to (0, 0) when the position cannot be determined (e.g.
        fullscreen mode or unsupported platform).
        """
        try:
            if hasattr(pygame.display, "get_wm_info"):
                info = pygame.display.get_wm_info()
                # Windows: info contains "window" (HWND); use GetWindowRect.
                # Check that the handle is integer-like before passing to ctypes.
                if "window" in info and isinstance(info["window"], int):
                    import ctypes
                    import ctypes.wintypes
                    rect = ctypes.wintypes.RECT()
                    if ctypes.windll.user32.GetWindowRect(
                        info["window"], ctypes.byref(rect)
                    ):
                        return int(rect.left), int(rect.top)
        except Exception:
            pass
        return 0, 0

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
                if action == "learn_mode":
                    if self._selected_port == 0:
                        # No hardware MIDI selected yet — prompt first
                        self._device_select_return_state = State.SONG_SELECT
                        self._enter_device_select()
                        self.state = State.DEVICE_SELECT
                    else:
                        self._enter_song_select()
                        self.state = State.SONG_SELECT
                elif action == "freeplay":
                    self._enter_highway()
                    self.state = State.HIGHWAY
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
                        data = cfg.load()
                        data.setdefault("hardware", {})["selected_midi_port"] = self._selected_port
                        cfg.save(data)
                        self._device_select = None
                        ret = self._device_select_return_state
                        if ret == State.HARDWARE_SETTINGS:
                            self._enter_hardware_settings()
                        elif ret == State.SONG_SELECT:
                            self._enter_song_select()
                        self.state = ret
                    elif result == "back":
                        self._device_select = None
                        ret = self._device_select_return_state
                        # SONG_SELECT has nothing to go back to; fall through to MENU
                        if ret in (State.HARDWARE_SETTINGS,):
                            self.state = ret
                        else:
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
                    elif result == "theme_settings":
                        self._enter_theme_settings()
                        self.state = State.THEME_SETTINGS
                    elif result == "hardware_settings":
                        self._enter_hardware_settings()
                        self.state = State.HARDWARE_SETTINGS

            elif self.state == State.HARDWARE_SETTINGS:
                if self._hardware_settings_screen is not None:
                    result = self._hardware_settings_screen.handle_event(event)
                    if result in ("back", "sustain_changed"):
                        self._hardware = self._load_hardware()
                        if self._midi is not None:
                            self._midi.set_sustain_enabled(bool(self._hardware.get("sustain_enabled", False)))
                        if result == "back":
                            self._hardware_settings_screen = None
                            self.state = State.SETTINGS
                    elif result == "midi_device":
                        self._device_select_return_state = State.HARDWARE_SETTINGS
                        self._enter_device_select()
                        self.state = State.DEVICE_SELECT

            elif self.state == State.PROFILE_SCREEN:
                if self._profile_screen is not None:
                    result = self._profile_screen.handle_event(event)
                    if result == "back":
                        self._profile_screen = None
                        self.state = State.HIGHWAY
                    elif result == "profile_loaded":
                        self._note_style = self._load_note_style()
                        self._note_style_meta = self._load_note_style_meta()
                        self._keyboard_style = self._load_keyboard_style()
                        self._display_style = self._load_display_style()
                        self._hardware = self._load_hardware()
                        self._bg_slides = self._load_background_slides()
                        self._refresh_claire_script_state()
                        if self._piano is not None:
                            self._piano.set_height_percent(int(self._keyboard_style.get("height_percent", 18)))
                        if self._led_output is not None:
                            r = self._note_style["color_r"]
                            g = self._note_style["color_g"]
                            b = self._note_style["color_b"]
                            self._led_output.set_active_color(r, g, b)
                        if self._midi is not None:
                            self._midi.set_sustain_enabled(bool(self._hardware.get("sustain_enabled", False)))

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

            elif self.state == State.THEME_SETTINGS:
                if self._theme_settings_screen is not None:
                    result = self._theme_settings_screen.handle_event(event)
                    if result == "back":
                        self._theme_settings_screen = None
                        self.state = State.SETTINGS

            elif self.state == State.SONG_SELECT:
                if self._song_select is not None:
                    result = self._song_select.handle_event(event)
                    if result == "select":
                        chosen = self._song_select.selected_file
                        self._song_select = None
                        if _MIDO_AVAILABLE and _MidiFilePlayer is not None:
                            note_tracks = _MidiFilePlayer.get_tracks_info(chosen)
                        else:
                            note_tracks = []
                        if len(note_tracks) > 1:
                            self._enter_track_select(chosen)
                            self.state = State.TRACK_SELECT
                        else:
                            self._enter_highway(midi_file=chosen, enabled_tracks=None)
                            self.state = State.HIGHWAY
                    elif result == "back":
                        self._song_select = None
                        self.state = State.MENU

            elif self.state == State.TRACK_SELECT:
                if self._track_select is not None:
                    result = self._track_select.handle_event(event)
                    if result == "play":
                        chosen = self._track_select.midi_path
                        enabled = self._track_select.enabled_tracks
                        self._track_select = None
                        self._enter_highway(midi_file=chosen, enabled_tracks=enabled)
                        self.state = State.HIGHWAY
                    elif result == "back":
                        self._track_select = None
                        self._enter_song_select()
                        self.state = State.SONG_SELECT

            elif self.state == State.HIGHWAY:
                if event.type == pygame.MOUSEMOTION:
                    self._profile_btn_hover = self._profile_btn_rect.collidepoint(event.pos)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self._profile_btn_rect.collidepoint(event.pos):
                        self._enter_profile_screen()
                        self.state = State.PROFILE_SCREEN
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._leave_highway()
                        self.state = State.MENU
                    elif event.key == pygame.K_p:
                        self._enter_profile_screen()
                        self.state = State.PROFILE_SCREEN
                    elif event.key == pygame.K_r:
                        # Retry MIDI connection
                        if self._midi is not None and not self._midi.connected:
                            self._midi.connect(self._selected_port)
                    elif self._midi is not None:
                        self._midi.handle_keydown(event.key)
                elif event.type == pygame.KEYUP:
                    if self._midi is not None:
                        self._midi.handle_keyup(event.key)

    def _get_panel_state(self) -> dict:
        """Return current config for the web control panel (called from background thread)."""
        data = cfg.load()
        return {
            "note_style": data.get("note_style", {}),
            "keyboard_style": data.get("keyboard_style", {}),
        }

    def _drain_control_patches(self) -> None:
        """Apply any patches queued by the web control panel."""
        while True:
            try:
                patch = self._control_patches.get_nowait()
            except queue.Empty:
                break

            ptype = patch.get("type")

            if ptype == "note_style":
                data = {k: v for k, v in patch.get("patch", {}).items()}
                conf = cfg.load()
                conf.setdefault("note_style", {}).update(data)
                cfg.save(conf)
                for k, v in data.items():
                    if k in self._note_style:
                        self._note_style[k] = int(v)
                # If outer color changed, snap the live blend to the new value.
                if any(k in data for k in ("color_r", "color_g", "color_b")):
                    nr = float(self._note_style["color_r"])
                    ng = float(self._note_style["color_g"])
                    nb = float(self._note_style["color_b"])
                    self._color_current = [nr, ng, nb]
                    self._color_start   = [nr, ng, nb]
                    self._color_target  = [nr, ng, nb]
                    self._color_blend_ms = 0
                    self._color_blend_elapsed_ms = 0
                    if self._led_output is not None:
                        self._led_output.set_active_color(int(nr), int(ng), int(nb))

            elif ptype == "keyboard_style":
                data = patch.get("patch", {})
                conf = cfg.load()
                conf.setdefault("keyboard_style", {}).update(data)
                cfg.save(conf)
                self._keyboard_style.update(data)
                if self._piano is not None:
                    if "height_percent" in data:
                        self._piano.set_height_percent(int(data["height_percent"]))
                    if "brightness" in data:
                        self._piano.set_brightness(int(data["brightness"]))
                    if "visible" in data:
                        self._piano.set_visible(bool(data["visible"]))

            elif ptype == "theme":
                idx = int(patch.get("index", 0))
                user_themes = themes_mod.load_user_themes()
                if 0 <= idx < len(user_themes):
                    themes_mod.set_active_index(idx)
                    themes_mod.apply_theme_to_config(user_themes[idx])
                    self._apply_theme_to_live(user_themes[idx])

    def _update(self, dt: int) -> None:
        self._drain_control_patches()
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

        if self.state == State.THEME_SETTINGS and self._theme_settings_screen is not None:
            return

        if self.state == State.HARDWARE_SETTINGS and self._hardware_settings_screen is not None:
            return

        if self.state == State.PROFILE_SCREEN and self._profile_screen is not None:
            return

        if self.state != State.HIGHWAY:
            return

        self._sync_highway_targets()

        self._update_audience_color(dt)

        if self._selected_midi_file is not None:
            if self._midi_player is not None:
                self._midi_player.update(dt)
                if self._midi_player.done and _MidiFilePlayer is not None:
                    self._midi_player = _MidiFilePlayer(
                        self._selected_midi_file, enabled_tracks=self._enabled_tracks
                    )
            return
        if self._midi is None or not self._midi.connected or self._piano is None:
            self._prev_active_notes.clear()
            self._active_note_trails.clear()
            self._note_trails.clear()
            return

        # --- Sustain-pedal triple-tap theme cycling ---
        for cc_num, cc_val in self._midi.drain_cc_events():
            if cc_num == 64 and cc_val > 0:  # sustain pedal pressed down
                now = time.monotonic()
                self._sustain_tap_times.append(now)
                # Keep only taps within the last second
                cutoff = now - 1.0
                self._sustain_tap_times = [t for t in self._sustain_tap_times if t >= cutoff]
                if len(self._sustain_tap_times) >= 3:
                    self._cycle_theme()
                    self._sustain_tap_times = []

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

        if self._fluid_renderer is not None:
            self._fluid_renderer.step(dt / 1000.0)
            # Continuously inject dye for each held note so fluid fills the bar length
            if active_notes:
                render_target, _scaled = self._get_highway_draw_target()
                sw = float(render_target.get_width())
                sh = float(render_target.get_height())
                intensity = self._note_style.get("fluid_intensity", 100) / 100.0
                r = self._note_style["color_r"] / 255.0
                g = self._note_style["color_g"] / 255.0
                b = self._note_style["color_b"] / 255.0
                vel_y = -self._note_style["speed_px_per_sec"] * 0.30 * intensity
                for note in active_notes:
                    trail = self._active_note_trails.get(note)
                    if trail is None:
                        continue
                    norm_x = float(trail["x"]) / sw
                    norm_y = float(trail["bottom_y"]) / sh
                    radius = max(0.025, float(trail["width"]) / sw * 4.5)
                    self._fluid_renderer.add_splat(
                        norm_x, norm_y, 0.0, vel_y, r, g, b, radius
                    )

    def _update_audience_color(self, dt: int) -> None:
        all_events = []
        if self._audience_client is not None:
            all_events.extend(self._audience_client.drain_events())
        if self._kick_client is not None:
            all_events.extend(self._kick_client.drain_events())
        if not all_events and self._audience_client is None and self._kick_client is None:
            return

        for evt in all_events:
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
        trail_width = self._trail_width_for_rect(rect)

        trail = {
            "note": float(note),
            "x": float(rect.centerx),
            "top_y": float(self._note_anchor_y(note)),
            "bottom_y": float(self._note_anchor_y(note)),
            "width": trail_width,
            "render_x": float(rect.centerx),
            "render_top_y": float(self._note_anchor_y(note)),
            "render_bottom_y": float(self._note_anchor_y(note)),
            "render_width": trail_width,
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
        trail["width"] = self._trail_width_for_rect(rect)

    def _trail_width_for_rect(self, rect: pygame.Rect) -> float:
        return float(max(TRAIL_MIN_WIDTH_PX, min(rect.width - TRAIL_KEY_EDGE_INSET_PX, self._note_style["width_px"])))

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
        elif self.state == State.THEME_SETTINGS:
            if self._theme_settings_screen is not None:
                self._theme_settings_screen.draw()
        elif self.state == State.HARDWARE_SETTINGS:
            if self._hardware_settings_screen is not None:
                self._hardware_settings_screen.draw()
        elif self.state == State.PROFILE_SCREEN:
            if self._profile_screen is not None:
                self._profile_screen.draw()
        elif self.state == State.SONG_SELECT:
            if self._song_select is not None:
                self._song_select.draw()
        elif self.state == State.TRACK_SELECT:
            if self._track_select is not None:
                self._track_select.draw()
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

        in_learn_mode = self._selected_midi_file is not None

        if self._midi is None or not self._midi.connected:
            if not in_learn_mode:
                # Freeplay with no MIDI device — show retry message
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
                self._draw_profile_btn()
                return

        # Show overlay text for song playback mode.
        if in_learn_mode and self._selected_midi_file is not None:
            if self._midi is not None and self._midi.connected:
                device_label = self._small_font.render(
                    f"MIDI: {self._midi.port_name}", True, (100, 200, 100)
                )
                self.screen.blit(device_label, (16, 12))
                song_label = self._small_font.render(
                    f"Song: {self._selected_midi_file.name}", True, (180, 180, 100)
                )
                self.screen.blit(song_label, (16, 36))
            else:
                song_label = self._small_font.render(
                    f"Song: {self._selected_midi_file.name}", True, (180, 180, 100)
                )
                self.screen.blit(song_label, (16, 12))

            esc_text = self._small_font.render("Press ESC to return", True, (150, 150, 150))
            esc_rect = esc_text.get_rect(topright=(screen_rect.right - 16, 12))
            self.screen.blit(esc_text, esc_rect)

        render_target = _highway_surf if scaled_mode else self.screen
        if scaled_mode:
            render_target.fill((0, 0, 0, 0))

        if in_learn_mode:
            self._draw_learn_bars(render_target)
        else:
            self._draw_freeplay_trails(render_target)

        # Determine active notes for piano highlighting
        if in_learn_mode and self._midi_player is not None:
            active_notes = self._midi_player.get_active_notes()
        elif self._midi is not None and self._midi.connected:
            active_notes = self._midi.get_active_notes()
        else:
            active_notes = set()

        if self._piano is not None:
            self._piano.set_target(render_target)
            self._piano.draw(active_notes)

        if scaled_mode:
            sw, _sh = self.screen.get_size()
            scaled_w = render_target.get_width()
            self.screen.blit(render_target, ((sw - scaled_w) // 2, 0))

        if self._audience_client is not None and self._audience_client.connected:
            if self._small_font is None:
                self._small_font = pygame.font.SysFont("Arial", 20)
            live = self._small_font.render("Live", True, (90, 255, 140))
            self.screen.blit(live, (10, self.screen.get_height() - live.get_height() - 8))

        self._draw_profile_btn()

    def _draw_profile_btn(self) -> None:
        """Draw the floating [PROFILES] button in the top-right corner of the screen."""
        if self._small_font is None:
            self._small_font = pygame.font.SysFont("Arial", 20)
        pb_w, pb_h = 110, 30
        self._profile_btn_rect = pygame.Rect(self.screen.get_width() - pb_w - 10, 8, pb_w, pb_h)
        pb_bg = (60, 60, 80) if self._profile_btn_hover else (30, 30, 42)
        pygame.draw.rect(self.screen, pb_bg, self._profile_btn_rect, border_radius=6)
        pygame.draw.rect(self.screen, (80, 80, 110), self._profile_btn_rect, width=1, border_radius=6)
        pb_s = self._small_font.render("[PROFILES]", True, (180, 180, 210))
        self.screen.blit(pb_s, pb_s.get_rect(center=self._profile_btn_rect.center))

    def _draw_freeplay_trails(self, target: pygame.Surface) -> None:
        if not self._note_trails or self._fx_renderer is None:
            return

        # The WebGL fluid overlay renders directly in its own window on top of
        # the pygame display; no pixel read-back or blitting is needed here.

        self._fx_renderer.set_target(target)
        self._fx_renderer.begin_frame()
        for trail in self._note_trails:
            self._fx_renderer.draw_trail(self._interpolated_trail_for_draw(trail), self._note_style)
        self._fx_renderer.end_frame()

    def _draw_learn_bars(self, target: pygame.Surface) -> None:
        """Draw Synthesia-style falling note bars for learn/file-playback mode."""
        if self._midi_player is None or self._piano is None:
            return

        speed_px_per_ms = max(1.0, float(self._note_style["speed_px_per_sec"])) / 1000.0
        target_h = target.get_height()

        # Piano top edge: use any valid note's rect.top
        piano_top_y: float = float(target_h)
        ref_rect = self._piano.get_note_rect(60)
        if ref_rect is not None:
            piano_top_y = float(ref_rect.top)
        elif not bool(self._keyboard_style.get("visible", True)):
            piano_top_y = float(target_h)

        lookahead_ms = piano_top_y / speed_px_per_ms if speed_px_per_ms > 0 else 5000.0
        current_ms = float(self._midi_player.current_ms)
        visible = self._midi_player.get_notes_in_window(lookahead_ms)

        r = self._note_style["color_r"]
        g = self._note_style["color_g"]
        b = self._note_style["color_b"]
        ir = min(255, self._note_style["interior_r"])
        ig = min(255, self._note_style["interior_g"])
        ib = min(255, self._note_style["interior_b"])
        glow = bool(self._note_style.get("effect_glow_enabled", 1))

        bar_surf = pygame.Surface((target.get_width(), target_h), pygame.SRCALPHA)

        for note, start_ms, end_ms in visible:
            note_rect = self._piano.get_note_rect(note)
            if note_rect is None:
                continue

            bar_bottom = piano_top_y - (start_ms - current_ms) * speed_px_per_ms
            bar_top = piano_top_y - (end_ms - current_ms) * speed_px_per_ms

            draw_top = max(0.0, bar_top)
            draw_bottom = min(piano_top_y, bar_bottom)
            if draw_bottom <= draw_top:
                continue

            inset = max(1, int(note_rect.width * 0.08))
            bx = note_rect.left + inset
            bw = max(2, note_rect.width - inset * 2)
            br = pygame.Rect(bx, int(draw_top), bw, int(draw_bottom - draw_top))

            pygame.draw.rect(bar_surf, (r, g, b, 210), br, border_radius=3)

            # Inner highlight strip
            if br.height > 6:
                hl_h = max(4, min(12, br.height // 4))
                hl = pygame.Rect(br.left + 2, br.top + 2, br.width - 4, hl_h)
                pygame.draw.rect(bar_surf, (ir, ig, ib, 160), hl, border_radius=2)

            # Soft glow halo
            if glow and bw > 4:
                glow_r = pygame.Rect(bx - 3, int(draw_top) - 2, bw + 6, int(draw_bottom - draw_top) + 4)
                glow_surf = pygame.Surface((glow_r.width, glow_r.height), pygame.SRCALPHA)
                pygame.draw.rect(glow_surf, (r, g, b, 45), glow_surf.get_rect(), border_radius=5)
                bar_surf.blit(glow_surf, (glow_r.x, glow_r.y))

        target.blit(bar_surf, (0, 0))

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
            "effect_fluid_enabled": int(bool(style.get("effect_fluid_enabled", 0))),
            "fluid_intensity": int(style.get("fluid_intensity", 100)),
            "fluid_curl": int(style.get("fluid_curl", 30)),
            "fluid_density_dissipation": int(style.get("fluid_density_dissipation", 22)),
            "fluid_velocity_dissipation": int(style.get("fluid_velocity_dissipation", 7)),
            "fluid_pressure": int(style.get("fluid_pressure", 80)),
        }

    def _load_keyboard_style(self) -> dict[str, int | bool]:
        style = cfg.load().get("keyboard_style", {})
        return {
            "height_percent": int(style.get("height_percent", 18)),
            "brightness": int(style.get("brightness", 100)),
            "visible": bool(style.get("visible", True)),
        }

    def _load_note_style_meta(self) -> dict[str, str | bool]:
        style = cfg.load().get("note_style", {})
        return {
            "active_theme_id": str(style.get("active_theme_id", "custom")),
            "experimental_claire_script_enabled": bool(style.get("experimental_claire_script_enabled", 0)),
        }

    def _load_hardware(self) -> dict:
        return dict(cfg.load().get("hardware", {"sustain_enabled": False}))

    def _enter_hardware_settings(self) -> None:
        port_name = self._get_current_port_name()
        self._hardware_settings_screen = HardwareSettingsScreen(self.screen, current_device_name=port_name)

    def _get_current_port_name(self) -> str:
        ports = MidiInput().list_ports()
        if 0 <= self._selected_port < len(ports):
            return ports[self._selected_port]
        return f"Port {self._selected_port}"

    def _enter_profile_screen(self) -> None:
        self._profile_screen = ProfileScreen(self.screen)

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

    def _load_display_style(self) -> dict:
        style = cfg.load().get("display_style", {})
        width_scale = max(60, min(80, int(style.get("width_scale_percent", 66))))
        items = list(style.get("background_slideshow_items", []))
        if not items:
            # Migrate from old format
            paths = list(style.get("background_slideshow_paths", []))
            single = str(style.get("background_image", ""))
            slide_sec     = int(style.get("background_slide_duration_sec", 5))
            trans_pct     = int(style.get("background_transition_percent", 35))
            gif_speed_pct = int(style.get("gif_speed_percent", 100))
            all_paths = paths if paths else ([single] if single else [])
            items = [{"path": p, "slide_sec": slide_sec, "transition_pct": trans_pct, "gif_speed_pct": gif_speed_pct} for p in all_paths]
        return {
            "width_scale_percent": width_scale,
            "background_alpha": int(style.get("background_alpha", 120)),
            "background_image": str(style.get("background_image", "")),
            "background_slideshow_items": items,
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

    def _load_background_slides(self) -> list[tuple[list[pygame.Surface], list[float], dict]]:
        """Build slide list from config. Returns (frames, durations, item_dict) per slide."""
        items: list[dict] = list(self._display_style.get("background_slideshow_items", []))
        slides: list[tuple[list[pygame.Surface], list[float], dict]] = []
        for item in items:
            p = pathlib.Path(item.get("path", ""))
            if p.exists():
                frames, durs = self._load_image_frames(p)
                if frames:
                    slides.append((frames, durs, item))
        return slides

    def _advance_background(self, dt_ms: float) -> tuple[Optional[pygame.Surface], Optional[pygame.Surface], float]:
        """Advance background timers and return (current_frame, next_frame, blend)."""
        if not self._bg_slides:
            return None, None, 0.0

        cur_idx   = self._bg_slide_index % len(self._bg_slides)
        frames, durations, item = self._bg_slides[cur_idx]

        slide_dur_ms     = max(500.0, float(item.get("slide_sec", 5)) * 1000.0)
        transition_ratio = max(0.10, min(0.90, item.get("transition_pct", 35) / 100.0))
        transition_ms    = max(500.0, min(3000.0, slide_dur_ms * transition_ratio))
        speed_pct        = max(10, min(200, int(item.get("gif_speed_pct", 100))))

        # Advance slide if there are multiple slides
        if len(self._bg_slides) > 1:
            self._bg_slide_ms += dt_ms
            while self._bg_slide_ms >= slide_dur_ms:
                self._bg_slide_ms -= slide_dur_ms
                self._bg_slide_index = (self._bg_slide_index + 1) % len(self._bg_slides)
                self._bg_frame_index = 0
                self._bg_frame_ms = 0.0
                # Reload per-item settings for the new slide
                cur_idx = self._bg_slide_index % len(self._bg_slides)
                frames, durations, item = self._bg_slides[cur_idx]
                slide_dur_ms     = max(500.0, float(item.get("slide_sec", 5)) * 1000.0)
                transition_ratio = max(0.10, min(0.90, item.get("transition_pct", 35) / 100.0))
                transition_ms    = max(500.0, min(3000.0, slide_dur_ms * transition_ratio))
                speed_pct        = max(10, min(200, int(item.get("gif_speed_pct", 100))))

        if not frames:
            return None, None, 0.0

        # Advance GIF frame using per-item speed
        if len(frames) > 1:
            self._bg_frame_ms += dt_ms * (speed_pct / 100.0)
            while durations and self._bg_frame_ms >= durations[self._bg_frame_index % len(durations)]:
                self._bg_frame_ms -= durations[self._bg_frame_index % len(durations)]
                self._bg_frame_index = (self._bg_frame_index + 1) % len(frames)

        current_frame = frames[self._bg_frame_index % len(frames)]

        # Soft dissolve near the end of the slide interval
        next_frame: Optional[pygame.Surface] = None
        blend = 0.0
        if len(self._bg_slides) > 1:
            blend_start_ms = slide_dur_ms - transition_ms
            if self._bg_slide_ms >= blend_start_ms:
                t = (self._bg_slide_ms - blend_start_ms) / max(1.0, transition_ms)
                t = max(0.0, min(1.0, t))
                blend = t * t * (3.0 - 2.0 * t)
                next_idx = (self._bg_slide_index + 1) % len(self._bg_slides)
                next_frames, _next_durations, _next_item = self._bg_slides[next_idx]
                if next_frames:
                    next_frame = next_frames[0]

        return current_frame, next_frame, blend

    def _quit(self) -> None:
        self._leave_highway()
        self.running = False
        pygame.quit()
        sys.exit()
