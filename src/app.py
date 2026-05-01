import queue
import sys
import pathlib
import math
import re
from collections import deque
import pygame
from enum import Enum, auto
from typing import Optional

from src import config as cfg
from src.control_server import ControlServer
from src.audience_color_client import AudienceColorClient
from src.audience_settings import AudienceSettingsScreen
from src.audio_device_select import AudioDeviceSelect
from src.audio_mic_test import AudioMicTestScreen
from src.led_output import LedOutput
from src.midi_input import MidiInput
from src.note_fx import NoteEffectRenderer
from src.piano import Piano
from src.device_select import DeviceSelect
from src.display_settings import DisplaySettingsScreen
from src.keyboard_settings import KeyboardSettingsScreen
from src.led_settings import LedSettingsScreen
from src.midi_hotkeys_settings import MidiHotkeysSettingsScreen
from src.midi_settings import MidiSettingsScreen
from src.midi_actions import get_action_def
from src.midi_hotkeys import find_matching_actions
from src.notes_settings import NotesSettingsScreen
from src.performance_settings import PerformanceSettingsScreen
from src.settings import SettingsScreen
from src.song_select import SongSelect
from src.theme_settings import ThemeSettingsScreen
from src.voice_controller import VoiceController, VoiceState
from src.voice_settings import VoiceSettingsScreen
import src.performance_store as perf_store


FREEPLAY_PARTICLE_HEIGHT_PX = 32
_VOICE_PREFIXES: tuple[str, ...] = (
    "go to theme ",
    "switch to theme ",
    "theme ",
    "go to ",
    "switch to ",
)


class State(Enum):
    MENU = auto()
    DEVICE_SELECT = auto()
    AUDIO_MIC_TEST = auto()
    AUDIO_DEVICE_SELECT = auto()
    SETTINGS = auto()
    PERFORMANCE_SETTINGS = auto()
    MIDI_SETTINGS = auto()
    MIDI_HOTKEYS_SETTINGS = auto()
    NOTES_SETTINGS = auto()
    KEYBOARD_SETTINGS = auto()
    LED_SETTINGS = auto()
    DISPLAY_SETTINGS = auto()
    AUDIENCE_SETTINGS = auto()
    VOICE_SETTINGS = auto()
    THEME_SETTINGS = auto()
    SONG_SELECT = auto()
    HIGHWAY = auto()


class App:
    """Main application state machine."""

    def __init__(self, screen: pygame.Surface, gl_ctx=None) -> None:
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
        self._audio_mic_test_screen: Optional[AudioMicTestScreen] = None
        self._audio_device_select: Optional[AudioDeviceSelect] = None
        self._settings_screen: Optional[SettingsScreen] = None
        self._performance_settings_screen: Optional[PerformanceSettingsScreen] = None
        self._midi_settings_screen: Optional[MidiSettingsScreen] = None
        self._midi_hotkeys_settings_screen: Optional[MidiHotkeysSettingsScreen] = None
        self._notes_settings_screen: Optional[NotesSettingsScreen] = None
        self._keyboard_settings_screen: Optional[KeyboardSettingsScreen] = None
        self._led_settings_screen: Optional[LedSettingsScreen] = None
        self._display_settings_screen: Optional[DisplaySettingsScreen] = None
        self._audience_settings_screen: Optional[AudienceSettingsScreen] = None
        self._voice_settings_screen: Optional[VoiceSettingsScreen] = None
        self._theme_settings_screen: Optional[ThemeSettingsScreen] = None
        self._song_select: Optional[SongSelect] = None
        self._selected_port: int = 0
        self._selected_audio_input_device: int = -1
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
        self._gl_renderer = None
        self._gl_bg_surf: Optional[pygame.Surface] = None
        self._gl_overlay_surf: Optional[pygame.Surface] = None
        self._led_output: Optional[LedOutput] = None
        # Background animation: list of slides, each slide is (frames, durations_ms)
        self._bg_slides: list[tuple[list[pygame.Surface], list[float]]] = []
        self._bg_slide_index: int = 0
        self._bg_slide_ms: float = 0.0
        self._bg_frame_index: int = 0
        self._bg_frame_ms: float = 0.0
        self._bg_scale_cache: dict[tuple[int, int, int], pygame.Surface] = {}
        self._bg_scale_cache_screen_size: tuple[int, int] = (0, 0)
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
        # Slide-linked colour palette cycling
        self._slide_palette_cfg: dict = {}
        self._palette_index: int = 0
        self._palette_color_current: list[float] = list(self._color_current)
        self._palette_color_start: list[float] = list(self._color_current)
        self._palette_color_target: list[float] = list(self._color_current)
        self._palette_interior_current: list[float] = [float(self._note_style.get("interior_r", 200)),
                                                        float(self._note_style.get("interior_g", 220)),
                                                        float(self._note_style.get("interior_b", 255))]
        self._palette_interior_start: list[float] = list(self._palette_interior_current)
        self._palette_interior_target: list[float] = list(self._palette_interior_current)
        self._palette_blend_ms: int = 0
        self._palette_blend_elapsed_ms: int = 0
        self._active_style_cue_index: int = 0
        self._last_dt_ms: int = 0
        self._smoothed_dt_ms: float = 16.67
        self._last_phase: str = "init"
        self._midi_action_gate: dict[str, bool] = {}
        self._notes_return_state: State = State.PERFORMANCE_SETTINGS
        self._transition_overlay_until_ms: int = 0
        self._transition_overlay_duration_ms: int = 420
        self._pending_highway_entry: bool = False
        self._pending_highway_midi_file: Optional[pathlib.Path] = None
        self._voice_mode: bool = False
        self._voice_continuous_listen: bool = False
        self._voice_continuous_gap_ms: int = 220
        self._voice_word_buffer: deque[str] = deque(maxlen=6)
        self._voice_word_buffer_size: int = 6
        self._voice_section_scoped_only: bool = False
        self._voice_section_cues: dict[int, list[dict[str, object]]] = {}
        self._voice_next_auto_listen_ms: int = 0
        self._voice_controller: Optional[VoiceController] = None
        self._refresh_claire_script_state()
        self._selected_port = self._load_selected_port()
        self._selected_audio_input_device = self._load_selected_audio_input_device()

        self._control_patches: queue.SimpleQueue = queue.SimpleQueue()
        self._control_server = ControlServer(self._control_patches, self._get_panel_state)
        self._control_server.start()

        if gl_ctx is not None:
            try:
                from src.gl_renderer import GLEffectsRenderer
                self._gl_renderer = GLEffectsRenderer(gl_ctx, screen.get_size())
            except Exception as exc:
                print(f"[gl] GLEffectsRenderer init failed, using CPU renderer: {exc}")

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
            if self._gl_renderer is not None and self.state != State.HIGHWAY:
                self._gl_renderer.present_pygame(self.screen)
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

    def _enter_audio_mic_test(self) -> None:
        self._audio_mic_test_screen = AudioMicTestScreen(
            self.screen,
            selected_device=self._selected_audio_input_device,
        )
        self._audio_mic_test_screen.refresh()

    def _enter_audio_device_select(self) -> None:
        self._audio_device_select = AudioDeviceSelect(
            self.screen,
            selected_device=self._selected_audio_input_device,
        )
        self._audio_device_select.refresh()

    def _enter_performance_settings(self) -> None:
        self._performance_settings_screen = PerformanceSettingsScreen(self.screen)

    def _enter_midi_settings(self) -> None:
        self._midi_settings_screen = MidiSettingsScreen(self.screen)

    def _enter_midi_hotkeys_settings(self) -> None:
        self._midi_hotkeys_settings_screen = MidiHotkeysSettingsScreen(self.screen)

    def _enter_notes_settings(
        self,
        performance_id: str = "",
        theme_index: int = -1,
        selected_channel: int = 0,
        return_state: State = State.PERFORMANCE_SETTINGS,
    ) -> None:
        self._notes_return_state = return_state
        self._notes_settings_screen = NotesSettingsScreen(
            self.screen,
            performance_id=performance_id,
            theme_index=theme_index,
            selected_channel=selected_channel,
        )

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
        self._clear_background_scale_cache()

    def _enter_audience_settings(self) -> None:
        self._audience_settings_screen = AudienceSettingsScreen(self.screen)

    def _enter_voice_settings(self) -> None:
        self._voice_settings_screen = VoiceSettingsScreen(self.screen)

    def _enter_theme_settings(self) -> None:
        self._theme_settings_screen = ThemeSettingsScreen(self.screen)

    def _cycle_theme(self) -> None:
        """Advance to the next theme in the active performance."""
        performance_id = perf_store.get_active_performance_id()
        themes = perf_store.load_themes(performance_id) if performance_id else []
        if not themes:
            return
        idx = perf_store.get_active_theme_index(performance_id)
        idx = (idx + 1) % len(themes)
        self._apply_performance_theme_index(performance_id, idx)

    def _cycle_theme_previous(self) -> None:
        """Move to the previous theme in the active performance."""
        performance_id = perf_store.get_active_performance_id()
        themes = perf_store.load_themes(performance_id) if performance_id else []
        if not themes:
            return
        idx = perf_store.get_active_theme_index(performance_id)
        idx = (idx - 1) % len(themes)
        self._apply_performance_theme_index(performance_id, idx)

    def _select_theme_index(self, index: int) -> None:
        """Select a theme by index from the active performance."""
        performance_id = perf_store.get_active_performance_id()
        themes = perf_store.load_themes(performance_id) if performance_id else []
        if not (0 <= index < len(themes)):
            return
        self._apply_performance_theme_index(performance_id, index)

    def _apply_performance_theme_index(self, performance_id: str, theme_index: int) -> None:
        """Apply a performance theme to config and refresh live runtime state."""
        if not performance_id:
            return
        perf_store.apply_theme_to_config(performance_id, theme_index)
        self._note_style = self._load_note_style()
        self._note_style_meta = self._load_note_style_meta()
        self._display_style = self._load_display_style()

        new_r = float(self._note_style.get("color_r", 0))
        new_g = float(self._note_style.get("color_g", 230))
        new_b = float(self._note_style.get("color_b", 230))
        self._color_current = [new_r, new_g, new_b]
        self._color_start   = [new_r, new_g, new_b]
        self._color_target  = [new_r, new_g, new_b]
        self._color_blend_ms = 0
        self._color_blend_elapsed_ms = 0

        self._refresh_claire_script_state()
        self._bg_slides = self._load_background_slides()

    def _load_saved_note_styles(self) -> list[dict]:
        data = cfg.load()
        raw_styles = data.get("note_styles", [])
        return [dict(entry) for entry in raw_styles if isinstance(entry, dict)]

    def _apply_saved_note_style_index(self, style_index: int) -> None:
        data = cfg.load()
        raw_styles = data.get("note_styles", [])
        if not isinstance(raw_styles, list) or not (0 <= style_index < len(raw_styles)):
            return
        style_entry = raw_styles[style_index]
        if not isinstance(style_entry, dict):
            return

        style = dict(style_entry)
        style.pop("name", None)
        style["active_theme_id"] = "custom"
        style["experimental_claire_script_enabled"] = 0
        data["note_style"] = style
        data["active_note_style_index"] = style_index
        data.setdefault("slide_palette", {})["enabled"] = False
        cfg.save(data)

        self._note_style = self._load_note_style()
        self._note_style_meta = self._load_note_style_meta()

        new_r = float(self._note_style.get("color_r", 0))
        new_g = float(self._note_style.get("color_g", 230))
        new_b = float(self._note_style.get("color_b", 230))
        self._color_current = [new_r, new_g, new_b]
        self._color_start = [new_r, new_g, new_b]
        self._color_target = [new_r, new_g, new_b]
        self._color_blend_ms = 0
        self._color_blend_elapsed_ms = 0

        self._refresh_claire_script_state()
        if self._led_output is not None:
            self._led_output.set_active_color(int(new_r), int(new_g), int(new_b))
        self._clear_background_scale_cache()
        self._bg_slide_index = 0
        self._bg_slide_ms = 0.0
        self._bg_frame_index = 0
        self._bg_frame_ms = 0.0
        self._active_style_cue_index = 0
        self._apply_active_style_cue()

        if self._led_output is not None:
            self._led_output.set_active_color(int(new_r), int(new_g), int(new_b))

    def _enter_song_select(self) -> None:
        self._song_select = SongSelect(self.screen)

    def _begin_highway_transition(self, midi_file: Optional[pathlib.Path] = None) -> None:
        self._pending_highway_entry = True
        self._pending_highway_midi_file = midi_file
        self._transition_overlay_until_ms = (
            pygame.time.get_ticks() + self._transition_overlay_duration_ms
        )

    def _save_selected_port(self) -> None:
        data = cfg.load()
        midi_settings = data.setdefault("midi_settings", {})
        midi_settings["selected_input_port"] = int(self._selected_port)
        cfg.save(data)

    def _load_selected_port(self) -> int:
        midi_settings = cfg.load().get("midi_settings", {})
        return int(midi_settings.get("selected_input_port", 0))

    def _save_selected_audio_input_device(self) -> None:
        data = cfg.load()
        audio_settings = data.setdefault("audio_settings", {})
        audio_settings["selected_input_device"] = int(self._selected_audio_input_device)
        cfg.save(data)

    def _load_selected_audio_input_device(self) -> int:
        audio_settings = cfg.load().get("audio_settings", {})
        return int(audio_settings.get("selected_input_device", -1))

    def _enter_highway(self, midi_file: Optional[pathlib.Path] = None) -> None:
        """Set up MIDI and piano when entering the HIGHWAY state."""
        self._sanitize_legacy_note_automation()
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
        self._clear_background_scale_cache()
        self._bg_slide_index = 0
        self._bg_slide_ms = 0.0
        self._bg_frame_index = 0
        self._bg_frame_ms = 0.0
        self._active_style_cue_index = 0
        self._prev_active_notes.clear()
        self._active_note_trails.clear()
        self._note_trails.clear()
        self._fx_renderer = NoteEffectRenderer(self.screen)
        # Load slide palette config and initialise colour state from first entry.
        self._slide_palette_cfg = cfg.load().get("slide_palette", {})
        palette = self._slide_palette_cfg.get("palette", [])
        self._palette_index = 0
        if palette:
            entry = palette[0]
            self._palette_color_current  = [float(entry.get("color_r", self._note_style["color_r"])),
                                             float(entry.get("color_g", self._note_style["color_g"])),
                                             float(entry.get("color_b", self._note_style["color_b"]))]
            self._palette_interior_current = [float(entry.get("interior_r", self._note_style.get("interior_r", 200))),
                                               float(entry.get("interior_g", self._note_style.get("interior_g", 220))),
                                               float(entry.get("interior_b", self._note_style.get("interior_b", 255)))]
        else:
            self._palette_color_current  = [float(self._note_style["color_r"]),
                                             float(self._note_style["color_g"]),
                                             float(self._note_style["color_b"])]
            self._palette_interior_current = [float(self._note_style.get("interior_r", 200)),
                                               float(self._note_style.get("interior_g", 220)),
                                               float(self._note_style.get("interior_b", 255))]
        self._palette_color_start    = list(self._palette_color_current)
        self._palette_color_target   = list(self._palette_color_current)
        self._palette_interior_start  = list(self._palette_interior_current)
        self._palette_interior_target = list(self._palette_interior_current)
        self._palette_blend_ms = 0
        self._palette_blend_elapsed_ms = 0
        self._apply_active_style_cue()

        voice_cfg = cfg.load().get("voice_settings", {})

        self._voice_continuous_listen = bool(voice_cfg.get("continuous_listen", False)) and self._voice_mode
        self._voice_continuous_gap_ms = max(80, min(2000, int(voice_cfg.get("continuous_gap_ms", 220))))
        self._voice_word_buffer_size = max(2, min(24, int(voice_cfg.get("word_buffer_size", 6))))
        self._voice_word_buffer = deque(maxlen=self._voice_word_buffer_size)
        self._voice_section_scoped_only = bool(voice_cfg.get("section_scoped_only", False))
        self._voice_section_cues = self._load_voice_section_cues(voice_cfg.get("section_cues", []))
        self._voice_next_auto_listen_ms = pygame.time.get_ticks() + 250

        max_record_secs = float(voice_cfg.get("push_to_talk_record_secs", 6.0))
        if self._voice_continuous_listen:
            max_record_secs = float(voice_cfg.get("continuous_record_secs", 1.2))
        result_display_secs = 0.6 if self._voice_continuous_listen else 3.0

        self._voice_controller = VoiceController(
            self._apply_voice_transcript,
            input_device_index=self._selected_audio_input_device,
            stt_backend=str(voice_cfg.get("backend", "vosk")),
            vosk_model_path=str(voice_cfg.get("vosk_model_path", "")),
            allow_google_fallback=bool(voice_cfg.get("allow_google_fallback", True)),
            max_record_secs=max_record_secs,
            result_display_secs=result_display_secs,
        )

        if self._gl_renderer is not None:
            w, h = self.screen.get_size()
            self._gl_bg_surf = pygame.Surface((w, h))
            self._gl_overlay_surf = pygame.Surface((w, h), pygame.SRCALPHA)
            self._gl_renderer.resize((w, h))

    def _leave_highway(self) -> None:
        """Clean up MIDI resources when leaving the HIGHWAY state."""
        if self._voice_controller is not None:
            self._voice_controller.stop()
            self._voice_controller = None
        self._voice_mode = False
        self._voice_continuous_listen = False
        self._voice_word_buffer = deque(maxlen=self._voice_word_buffer_size)
        self._voice_section_scoped_only = False
        self._voice_section_cues = {}
        self._voice_next_auto_listen_ms = 0
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
        self._clear_background_scale_cache()
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
        if self._gl_renderer is not None:
            # GL overlay is always full-screen — skip width-scaled surface
            target = self._gl_overlay_surf if self._gl_overlay_surf is not None else self.screen
            if self._piano is not None:
                self._piano.set_target(target)
            if self._fx_renderer is not None:
                self._fx_renderer.set_target(target)
            return
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
                if self._pending_highway_entry:
                    continue
                action = self.menu.handle_event(event)
                if action == "select_file":
                    self._enter_song_select()
                    self.state = State.SONG_SELECT
                elif action == "freeplay":
                    self._voice_mode = True
                    self._begin_highway_transition()
                elif action == "voice_play":
                    self._voice_mode = True
                    self._begin_highway_transition()
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
                        self._save_selected_port()
                        self._device_select = None
                        self.state = State.MIDI_SETTINGS
                    elif result == "back":
                        self._device_select = None
                        self.state = State.MIDI_SETTINGS

            elif self.state == State.AUDIO_DEVICE_SELECT:
                if self._audio_device_select is not None:
                    result = self._audio_device_select.handle_event(event)
                    if result == "select":
                        self._selected_audio_input_device = self._audio_device_select.selected_device
                        self._save_selected_audio_input_device()
                        self._audio_device_select = None
                        if self._audio_mic_test_screen is not None:
                            self._audio_mic_test_screen.selected_device = self._selected_audio_input_device
                        self.state = State.AUDIO_MIC_TEST
                    elif result == "back":
                        self._audio_device_select = None
                        self.state = State.AUDIO_MIC_TEST

            elif self.state == State.AUDIO_MIC_TEST:
                if self._audio_mic_test_screen is not None:
                    result = self._audio_mic_test_screen.handle_event(event)
                    if result == "audio_device_select":
                        self._audio_mic_test_screen.close()
                        self._enter_audio_device_select()
                        self.state = State.AUDIO_DEVICE_SELECT
                    elif result == "back":
                        self._audio_mic_test_screen.close()
                        self._audio_mic_test_screen = None
                        self.state = State.MIDI_SETTINGS

            elif self.state == State.SETTINGS:
                if self._settings_screen is not None:
                    result = self._settings_screen.handle_event(event)
                    if result == "back":
                        self._settings_screen = None
                        self.state = State.MENU
                    elif result == "performance_settings":
                        self._enter_performance_settings()
                        self.state = State.PERFORMANCE_SETTINGS
                    elif result == "midi_settings":
                        self._enter_midi_settings()
                        self.state = State.MIDI_SETTINGS
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
                    elif result == "voice_settings":
                        self._enter_voice_settings()
                        self.state = State.VOICE_SETTINGS

            elif self.state == State.PERFORMANCE_SETTINGS:
                if self._performance_settings_screen is not None:
                    result = self._performance_settings_screen.handle_event(event)
                    if result == "back":
                        self._performance_settings_screen = None
                        self.state = State.SETTINGS
                    elif result == "theme_settings":
                        self._enter_theme_settings()
                        self.state = State.THEME_SETTINGS
                    elif result == "notes_settings":
                        self._enter_notes_settings(return_state=State.PERFORMANCE_SETTINGS)
                        self.state = State.NOTES_SETTINGS

            elif self.state == State.MIDI_SETTINGS:
                if self._midi_settings_screen is not None:
                    result = self._midi_settings_screen.handle_event(event)
                    if result == "back":
                        self._midi_settings_screen = None
                        self.state = State.SETTINGS
                    elif result == "device_select":
                        self._enter_device_select()
                        self.state = State.DEVICE_SELECT
                    elif result == "midi_hotkeys":
                        self._enter_midi_hotkeys_settings()
                        self.state = State.MIDI_HOTKEYS_SETTINGS
                    elif result == "audio_device_select":
                        self._enter_audio_mic_test()
                        self.state = State.AUDIO_MIC_TEST

            elif self.state == State.NOTES_SETTINGS:
                if self._notes_settings_screen is not None:
                    result = self._notes_settings_screen.handle_event(event)
                    if result == "back":
                        self._notes_settings_screen = None
                        if self._notes_return_state == State.THEME_SETTINGS:
                            active_perf_id = perf_store.get_active_performance_id()
                            active_theme_index = perf_store.get_active_theme_index(active_perf_id)
                            if active_perf_id and active_theme_index >= 0:
                                perf_store.apply_theme_to_config(active_perf_id, active_theme_index)
                        self.state = self._notes_return_state

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

            elif self.state == State.VOICE_SETTINGS:
                if self._voice_settings_screen is not None:
                    result = self._voice_settings_screen.handle_event(event)
                    if result == "back":
                        self._voice_settings_screen = None
                        self.state = State.SETTINGS

            elif self.state == State.THEME_SETTINGS:
                if self._theme_settings_screen is not None:
                    result = self._theme_settings_screen.handle_event(event)
                    if result == "back":
                        self._theme_settings_screen = None
                        self.state = State.PERFORMANCE_SETTINGS
                    elif result == "notes_settings":
                        active_perf_id = perf_store.get_active_performance_id()
                        active_theme_index = perf_store.get_active_theme_index(active_perf_id)
                        self._enter_notes_settings(
                            performance_id=active_perf_id,
                            theme_index=active_theme_index,
                            selected_channel=0,
                            return_state=State.THEME_SETTINGS,
                        )
                        self.state = State.NOTES_SETTINGS

            elif self.state == State.MIDI_HOTKEYS_SETTINGS:
                if self._midi_hotkeys_settings_screen is not None:
                    result = self._midi_hotkeys_settings_screen.handle_event(event)
                    if result == "back":
                        self._midi_hotkeys_settings_screen = None
                        self.state = State.MIDI_SETTINGS

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
                    elif event.key == pygame.K_SPACE:
                        if self._voice_controller is not None and not self._voice_continuous_listen:
                            self._voice_controller.start_recording()
                    elif self._midi is not None:
                        self._midi.handle_keydown(event.key)
                elif event.type == pygame.KEYUP:
                    if event.key == pygame.K_SPACE:
                        if self._voice_controller is not None and not self._voice_continuous_listen:
                            self._voice_controller.stop_recording()
                    elif self._midi is not None:
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
                performance_id = perf_store.get_active_performance_id()
                themes = perf_store.load_themes(performance_id) if performance_id else []
                if 0 <= idx < len(themes):
                    self._apply_performance_theme_index(performance_id, idx)

    def _update(self, dt: int) -> None:
        self._drain_control_patches()
        if self.state == State.MENU and self._pending_highway_entry:
            if pygame.time.get_ticks() >= self._transition_overlay_until_ms:
                self._pending_highway_entry = False
                pending_file = self._pending_highway_midi_file
                self._pending_highway_midi_file = None
                self._enter_highway(midi_file=pending_file)
                self.state = State.HIGHWAY
            return

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

        if self.state == State.AUDIO_MIC_TEST and self._audio_mic_test_screen is not None:
            self._audio_mic_test_screen.update(dt)
            return

        if self.state != State.HIGHWAY:
            return

        if self._voice_controller is not None:
            self._voice_controller.tick()
            self._update_continuous_voice()

        self._sync_highway_targets()

        self._update_audience_color(dt)
        self._update_slide_palette(dt)

        if self._selected_midi_file is not None:
            return
        if self._midi is None or not self._midi.connected or self._piano is None:
            self._prev_active_notes.clear()
            self._active_note_trails.clear()
            self._note_trails.clear()
            return

        self._process_midi_cc_events()

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
        elif self.state == State.AUDIO_MIC_TEST:
            if self._audio_mic_test_screen is not None:
                self._audio_mic_test_screen.draw()
        elif self.state == State.AUDIO_DEVICE_SELECT:
            if self._audio_device_select is not None:
                self._audio_device_select.draw()
        elif self.state == State.PERFORMANCE_SETTINGS:
            if self._performance_settings_screen is not None:
                self._performance_settings_screen.draw()
        elif self.state == State.MIDI_SETTINGS:
            if self._midi_settings_screen is not None:
                self._midi_settings_screen.draw()
        elif self.state == State.MIDI_HOTKEYS_SETTINGS:
            if self._midi_hotkeys_settings_screen is not None:
                self._midi_hotkeys_settings_screen.draw()
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
        elif self.state == State.VOICE_SETTINGS:
            if self._voice_settings_screen is not None:
                self._voice_settings_screen.draw()
        elif self.state == State.THEME_SETTINGS:
            if self._theme_settings_screen is not None:
                self._theme_settings_screen.draw()
        elif self.state == State.SONG_SELECT:
            if self._song_select is not None:
                self._song_select.draw()
        elif self.state == State.HIGHWAY:
            self._draw_highway()
            self._draw_voice_hud()

        self._draw_transition_overlay()

    def _draw_voice_hud(self) -> None:
        """Draw the push-to-talk status pill at the bottom of the screen."""
        if self._voice_controller is None:
            return

        if self._small_font is None:
            self._small_font = pygame.font.SysFont("Arial", 20)

        state = self._voice_controller.state
        now_ms = pygame.time.get_ticks()

        if state == VoiceState.IDLE:
            if self._voice_continuous_listen:
                text = "Voice cue listening (continuous)"
            else:
                text = "Hold SPACE and say a theme name"
            text_color = (160, 160, 180)
            bg_alpha = 120
        elif state == VoiceState.RECORDING:
            pulse = int(abs(math.sin(now_ms / 300.0)) * 80 + 175)
            text = "\u25CF  Listening..."
            text_color = (pulse, 80, 80)
            bg_alpha = 180
        elif state == VoiceState.PROCESSING:
            text = "Processing..."
            text_color = (200, 200, 80)
            bg_alpha = 180
        elif state == VoiceState.MATCHED:
            name = self._voice_controller.last_text
            text = f"\u2713  {name}"
            text_color = (80, 220, 120)
            bg_alpha = 200
        else:  # NO_MATCH
            hw_err = self._voice_controller.last_hardware_error if self._voice_controller is not None else ""
            if hw_err:
                hw_lower = hw_err.lower()
                if any(kw in hw_lower for kw in ("9999", "unanticipated", "unknown", "access")):
                    text = "Mic blocked \u2014 check Windows Settings \u2192 Privacy \u2192 Microphone"
                else:
                    text = f"Mic error \u2014 {hw_err[:60]}"
            else:
                text = "Not recognized \u2014 try again"
            text_color = (220, 80, 80)
            bg_alpha = 200

        surf = self._small_font.render(text, True, text_color)
        pad_x, pad_y = 18, 8
        pill_w = surf.get_width() + pad_x * 2
        pill_h = surf.get_height() + pad_y * 2
        sw, sh = self.screen.get_size()
        pill_x = (sw - pill_w) // 2
        pill_y = sh - pill_h - 16
        pill = pygame.Surface((pill_w, pill_h), pygame.SRCALPHA)
        pill.fill((20, 20, 30, bg_alpha))
        pygame.draw.rect(pill, (80, 80, 120, bg_alpha + 40), pill.get_rect(), width=1, border_radius=pill_h // 2)
        self.screen.blit(pill, (pill_x, pill_y))
        self.screen.blit(surf, (pill_x + pad_x, pill_y + pad_y))

    def _apply_voice_transcript(self, transcript: str | None) -> None:
        """Match a transcript against theme names and apply on hit (called from worker thread)."""
        if not transcript:
            return

        normalized = self._normalize_voice_text(transcript)
        if normalized:
            for token in normalized.split():
                self._voice_word_buffer.append(token)

        performance_id = perf_store.get_active_performance_id()
        themes = perf_store.load_themes(performance_id) if performance_id else []
        saved_styles = self._load_saved_note_styles()

        match = self._resolve_section_cue_command(transcript, themes, saved_styles)
        if match is None and self._voice_word_buffer:
            buffered_phrase = " ".join(self._voice_word_buffer)
            if buffered_phrase and buffered_phrase != normalized:
                match = self._resolve_section_cue_command(buffered_phrase, themes, saved_styles)

        if match is None and not self._voice_section_scoped_only:
            match = self._resolve_theme_command(transcript, themes, saved_styles)
            if match is None and self._voice_word_buffer:
                buffered_phrase = " ".join(self._voice_word_buffer)
                if buffered_phrase and buffered_phrase != normalized:
                    match = self._resolve_theme_command(buffered_phrase, themes, saved_styles)
        if match is not None:
            match_kind, idx, matched_name = match
            if match_kind == "performance_theme":
                self._apply_performance_theme_index(performance_id, idx)
            elif match_kind == "saved_note_style":
                self._apply_saved_note_style_index(idx)
            if self._voice_controller is not None:
                self._voice_controller.last_text = matched_name
            return

        if self._voice_controller is not None:
            self._voice_controller.last_text = f'Heard "{transcript}" (no matching theme)'

    def _update_continuous_voice(self) -> None:
        """Auto-rearm short voice captures in continuous mode without blocking render."""
        if not self._voice_continuous_listen or self._voice_controller is None:
            return

        now_ms = pygame.time.get_ticks()
        if now_ms < self._voice_next_auto_listen_ms:
            return

        if self._voice_controller.state != VoiceState.IDLE:
            return

        if self._voice_controller.start_recording():
            self._voice_next_auto_listen_ms = now_ms + self._voice_continuous_gap_ms

    @staticmethod
    def _normalize_voice_text(value: str) -> str:
        lowered = value.lower()
        lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
        return " ".join(lowered.split())

    def _strip_voice_prefix(self, normalized_text: str) -> str:
        candidate = normalized_text
        for prefix in _VOICE_PREFIXES:
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix):].strip()
                break
        return candidate

    def _load_voice_section_cues(self, raw_config: object) -> dict[int, list[dict[str, object]]]:
        parsed: dict[int, list[dict[str, object]]] = {}
        if not isinstance(raw_config, list):
            return parsed

        for section_cfg in raw_config:
            if not isinstance(section_cfg, dict):
                continue
            try:
                section_idx = int(section_cfg.get("section", section_cfg.get("cue_index", -1)))
            except Exception:
                section_idx = -1
            if section_idx < 0:
                continue

            cues = section_cfg.get("cues", [])
            if not isinstance(cues, list):
                continue

            for cue_cfg in cues:
                if not isinstance(cue_cfg, dict):
                    continue

                phrase_cfg = cue_cfg.get("phrases", cue_cfg.get("words", []))
                if isinstance(phrase_cfg, str):
                    phrase_values = [phrase_cfg]
                elif isinstance(phrase_cfg, list):
                    phrase_values = [str(v) for v in phrase_cfg]
                else:
                    phrase_values = []

                phrases: list[str] = []
                for raw_phrase in phrase_values:
                    phrase = self._normalize_voice_text(raw_phrase)
                    if phrase:
                        phrases.append(phrase)
                if not phrases:
                    continue

                target_kind = str(cue_cfg.get("target_kind", "performance_theme")).strip().lower()
                target_name_raw = str(cue_cfg.get("target", "")).strip()
                if not target_name_raw:
                    target_name_raw = str(cue_cfg.get("target_theme", cue_cfg.get("theme", ""))).strip()
                    if target_name_raw:
                        target_kind = "performance_theme"
                if not target_name_raw:
                    target_name_raw = str(cue_cfg.get("target_saved_style", cue_cfg.get("saved_style", ""))).strip()
                    if target_name_raw:
                        target_kind = "saved_note_style"

                target_name = self._normalize_voice_text(target_name_raw)
                target_index_raw = cue_cfg.get("target_index", None)
                target_index: int | None = None
                if target_index_raw is not None:
                    try:
                        target_index = int(target_index_raw)
                    except Exception:
                        target_index = None

                if target_kind not in {"performance_theme", "saved_note_style"}:
                    continue
                if not target_name and target_index is None:
                    continue

                parsed.setdefault(section_idx, []).append(
                    {
                        "phrases": phrases,
                        "target_kind": target_kind,
                        "target_name": target_name,
                        "target_index": target_index,
                    }
                )

        return parsed

    def _resolve_section_cue_command(
        self,
        transcript: str,
        themes: list[dict],
        saved_styles: list[dict],
    ) -> tuple[str, int, str] | None:
        if not self._voice_section_cues:
            return None

        section_cues = self._voice_section_cues.get(max(0, self._active_style_cue_index), [])
        if not section_cues:
            return None

        normalized = self._normalize_voice_text(transcript)
        if not normalized:
            return None
        candidate = self._strip_voice_prefix(normalized)
        if not candidate:
            return None
        candidate_padded = f" {candidate} "

        for cue in section_cues:
            phrases = cue.get("phrases", [])
            if not isinstance(phrases, list):
                continue

            matched_phrase = False
            for phrase in phrases:
                phrase_text = str(phrase).strip()
                if not phrase_text:
                    continue
                if phrase_text == candidate or f" {phrase_text} " in candidate_padded:
                    matched_phrase = True
                    break
            if not matched_phrase:
                continue

            target_kind = str(cue.get("target_kind", "performance_theme"))
            target_name = str(cue.get("target_name", "")).strip()
            target_index_raw = cue.get("target_index")
            target_index: int | None
            if isinstance(target_index_raw, int):
                target_index = target_index_raw
            else:
                target_index = None

            if target_kind == "performance_theme":
                if target_index is not None and 0 <= target_index < len(themes):
                    raw_name = str(themes[target_index].get("name", "")).strip() or f"Theme {target_index + 1}"
                    return "performance_theme", target_index, raw_name
                for i, theme in enumerate(themes):
                    raw_name = str(theme.get("name", "")).strip()
                    if self._normalize_voice_text(raw_name) == target_name:
                        return "performance_theme", i, raw_name
            elif target_kind == "saved_note_style":
                if target_index is not None and 0 <= target_index < len(saved_styles):
                    raw_name = str(saved_styles[target_index].get("name", "")).strip() or f"Style {target_index + 1}"
                    return "saved_note_style", target_index, raw_name
                for i, style in enumerate(saved_styles):
                    raw_name = str(style.get("name", "")).strip()
                    if self._normalize_voice_text(raw_name) == target_name:
                        return "saved_note_style", i, raw_name

        return None

    def _resolve_theme_command(
        self,
        transcript: str,
        themes: list[dict],
        saved_styles: list[dict],
    ) -> tuple[str, int, str] | None:
        normalized = self._normalize_voice_text(transcript)
        if not normalized:
            return None
        candidate = self._strip_voice_prefix(normalized)
        if not candidate:
            return None

        normalized_theme_names: list[tuple[str, int, str, str]] = []
        for i, theme in enumerate(themes):
            raw_name = str(theme.get("name", "")).strip()
            normalized_name = self._normalize_voice_text(raw_name)
            if normalized_name:
                normalized_theme_names.append(("performance_theme", i, raw_name, normalized_name))

        for i, style in enumerate(saved_styles):
            raw_name = str(style.get("name", "")).strip()
            normalized_name = self._normalize_voice_text(raw_name)
            if normalized_name:
                normalized_theme_names.append(("saved_note_style", i, raw_name, normalized_name))

        # Prefer exact theme-name matches first.
        for match_kind, idx, raw_name, theme_name in normalized_theme_names:
            if theme_name == candidate:
                return match_kind, idx, raw_name

        # Fallback: phrase contains a full theme name.
        for match_kind, idx, raw_name, theme_name in normalized_theme_names:
            if theme_name and theme_name in candidate:
                return match_kind, idx, raw_name
        return None

    def _draw_transition_overlay(self) -> None:
        now_ms = pygame.time.get_ticks()
        if now_ms >= self._transition_overlay_until_ms:
            return

        if self._small_font is None:
            self._small_font = pygame.font.SysFont("Arial", 20)

        sr = self.screen.get_rect()
        overlay = pygame.Surface((sr.width, sr.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 86))
        self.screen.blit(overlay, (0, 0))

        panel_w, panel_h = 270, 88
        panel = pygame.Rect(0, 0, panel_w, panel_h)
        panel.center = sr.center
        pygame.draw.rect(self.screen, (22, 22, 30), panel, border_radius=10)
        pygame.draw.rect(self.screen, (80, 80, 110), panel, width=1, border_radius=10)

        # Spinner
        spinner_cx = panel.left + 34
        spinner_cy = panel.centery
        spinner_r = 11
        phase = (now_ms % 900) / 900.0
        start_angle = phase * 2.0 * math.pi
        end_angle = start_angle + (math.pi * 1.35)
        spinner_rect = pygame.Rect(
            spinner_cx - spinner_r,
            spinner_cy - spinner_r,
            spinner_r * 2,
            spinner_r * 2,
        )
        pygame.draw.arc(self.screen, (0, 200, 200), spinner_rect, start_angle, end_angle, width=3)

        label = "Loading Free Play..." if self._pending_highway_entry else "Please wait..."
        text = self._small_font.render(label, True, (220, 220, 230))
        self.screen.blit(text, text.get_rect(midleft=(spinner_cx + 20, panel.centery)))

    def _draw_highway(self) -> None:
        if self._gl_renderer is not None:
            self._draw_highway_gl()
            return
        self.screen.fill((10, 10, 10))

        # Background always fills the full screen width.
        bg_frame, bg_next_frame, bg_blend = self._advance_background(self._smoothed_dt_ms)
        if bg_frame is not None:
            base_alpha = int(self._display_style.get("background_alpha", 120))
            if bg_next_frame is None or bg_blend <= 0.0:
                bg = self._get_scaled_background_surface(bg_frame).copy()
                bg.set_alpha(base_alpha)
                self.screen.blit(bg, (0, 0))
            else:
                # Slow, soft dissolve with no directional motion.
                bg_a = self._get_scaled_background_surface(bg_frame).copy()
                bg_b = self._get_scaled_background_surface(bg_next_frame).copy()
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

    def _draw_highway_gl(self) -> None:
        """Highway rendering via GLEffectsRenderer (OpenGL path)."""
        bg_surf = self._gl_bg_surf
        overlay_surf = self._gl_overlay_surf
        if bg_surf is None or overlay_surf is None:
            return

        # Background → bg_surf
        bg_surf.fill((10, 10, 10))
        bg_frame, bg_next_frame, bg_blend = self._advance_background(self._smoothed_dt_ms)
        base_alpha = int(self._display_style.get("background_alpha", 120))
        if bg_frame is not None:
            if bg_next_frame is None or bg_blend <= 0.0:
                scaled = self._get_scaled_background_surface(bg_frame).copy()
                bg_surf.blit(scaled, (0, 0))
            else:
                bg_a = self._get_scaled_background_surface(bg_frame).copy()
                bg_b = self._get_scaled_background_surface(bg_next_frame).copy()
                bg_a.set_alpha(max(0, min(255, int(255 * (1.0 - bg_blend)))))
                bg_b.set_alpha(max(0, min(255, int(255 * bg_blend))))
                bg_surf.blit(bg_a, (0, 0))
                bg_surf.blit(bg_b, (0, 0))

        # Overlay → overlay_surf (piano + text on transparent surface)
        overlay_surf.fill((0, 0, 0, 0))

        if self._highway_font is None:
            self._highway_font = pygame.font.SysFont("Arial", 28)
        if self._small_font is None:
            self._small_font = pygame.font.SysFont("Arial", 20)

        screen_rect = self.screen.get_rect()

        if self._midi is None or not self._midi.connected:
            overlay_surf.fill((10, 10, 10))
            if self._midi is not None and not self._midi.available:
                msg = "python-rtmidi not installed. Run: pip install python-rtmidi"
            else:
                msg = "No MIDI device detected. Connect a MIDI device and press R to retry."
            text = self._highway_font.render(msg, True, (220, 100, 100))
            overlay_surf.blit(text, text.get_rect(center=screen_rect.center))
            esc = self._small_font.render("Press ESC to return", True, (150, 150, 150))
            overlay_surf.blit(esc, esc.get_rect(topright=(screen_rect.right - 16, 12)))
            self._gl_renderer.end_frame(bg_surf, 0.0, overlay_surf)
            return

        if self._selected_midi_file is not None:
            dev = self._small_font.render(f"MIDI: {self._midi.port_name}", True, (100, 200, 100))
            overlay_surf.blit(dev, (16, 12))
            song = self._small_font.render(f"Song: {self._selected_midi_file.name}", True, (180, 180, 100))
            overlay_surf.blit(song, (16, 36))
            esc = self._small_font.render("Press ESC to return", True, (150, 150, 150))
            overlay_surf.blit(esc, esc.get_rect(topright=(screen_rect.right - 16, 12)))

        # Piano drawn to overlay_surf
        active_notes = self._midi.get_active_notes()
        if self._piano is not None:
            self._piano.set_target(overlay_surf)
            self._piano.draw(active_notes)
            self._piano.set_target(self.screen)

        if self._audience_client is not None and self._audience_client.connected:
            live = self._small_font.render("Live", True, (90, 255, 140))
            overlay_surf.blit(live, (10, screen_rect.bottom - live.get_height() - 8))

        # GL effects pass
        self._gl_renderer.begin_frame()
        if self._selected_midi_file is None:
            for trail in self._note_trails:
                self._gl_renderer.draw_trail(
                    self._interpolated_trail_for_draw(trail), self._note_style
                )
        self._gl_renderer.end_frame(bg_surf, base_alpha / 255.0, overlay_surf)

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

    def _process_midi_cc_events(self) -> None:
        """Resolve incoming MIDI CC events against the hotkey map."""
        if self._midi is None:
            return

        seen_actions: set[str] = set()
        for midi_channel, cc_number, value in self._midi.drain_cc_events():
            for mapping in find_matching_actions(midi_channel, cc_number, value):
                action_id = str(mapping.get("action_id", "")).strip()
                if not action_id:
                    continue
                seen_actions.add(action_id)
                self._perform_midi_action(action_id, int(value), int(midi_channel), mapping)

        active_actions = {
            action_id: gate
            for action_id, gate in self._midi_action_gate.items()
            if gate or action_id in seen_actions
        }
        self._midi_action_gate = active_actions

    def _perform_midi_action(
        self,
        action_id: str,
        value: int,
        midi_channel: int,
        mapping: dict[str, object] | None = None,
    ) -> None:
        """Dispatch one incoming MIDI hotkey event."""
        _ = midi_channel
        action_def = get_action_def(action_id)
        if action_def is None:
            return

        mode = str((mapping or {}).get("mode", action_def.get("mode", "trigger")))
        threshold = int((mapping or {}).get("threshold", action_def.get("threshold", 64)))
        if bool((mapping or {}).get("invert", False)):
            value = 127 - value
        is_active = value >= threshold
        was_active = bool(self._midi_action_gate.get(action_id, False))

        if mode == "continuous":
            self._apply_continuous_midi_action(action_id, value)
            self._midi_action_gate[action_id] = is_active
            return

        if is_active and not was_active:
            if mode == "toggle":
                self._apply_toggle_midi_action(action_id)
            else:
                self._apply_trigger_midi_action(action_id)

        self._midi_action_gate[action_id] = is_active

    def _apply_trigger_midi_action(self, action_id: str) -> None:
        if action_id == "performance.theme_next":
            self._cycle_theme()
        elif action_id == "performance.theme_previous":
            self._cycle_theme_previous()
        elif action_id == "performance.theme_select_1":
            self._select_theme_index(0)
        elif action_id == "performance.theme_select_2":
            self._select_theme_index(1)
        elif action_id == "performance.theme_select_3":
            self._select_theme_index(2)
        elif action_id == "performance.theme_select_4":
            self._select_theme_index(3)

    def _apply_toggle_midi_action(self, action_id: str) -> None:
        if action_id == "effects.glow_toggle":
            self._toggle_note_style_flag("effect_glow_enabled")
        elif action_id == "effects.sparks_toggle":
            self._toggle_note_style_flag("effect_sparks_enabled")
        elif action_id == "effects.smoke_toggle":
            self._toggle_note_style_flag("effect_smoke_enabled")
        elif action_id == "keyboard.visible_toggle":
            self._toggle_keyboard_visible()

    def _apply_continuous_midi_action(self, action_id: str, value: int) -> None:
        if action_id == "effects.glow_strength":
            self._set_note_style_value_from_cc("glow_strength_percent", value, 0, 180)
        elif action_id == "effects.spark_amount":
            self._set_note_style_value_from_cc("spark_amount_percent", value, 0, 300)
        elif action_id == "effects.smoke_amount":
            self._set_note_style_value_from_cc("smoke_amount_percent", value, 0, 300)
        elif action_id == "visual.note_speed":
            self._set_note_style_value_from_cc("speed_px_per_sec", value, 80, 1200)
        elif action_id == "visual.note_width":
            self._set_note_style_value_from_cc("width_px", value, 4, 40)
        elif action_id == "visual.background_alpha":
            self._set_display_value_from_cc("background_alpha", value, 0, 255)

    def _cc_to_range(self, value: int, min_v: int, max_v: int) -> int:
        ratio = max(0.0, min(1.0, float(value) / 127.0))
        return int(round(min_v + ratio * (max_v - min_v)))

    def _toggle_note_style_flag(self, key: str) -> None:
        new_value = 0 if int(self._note_style.get(key, 0)) else 1
        self._note_style[key] = new_value
        self._persist_note_style_patch({key: new_value})

    def _set_note_style_value_from_cc(
        self,
        key: str,
        value: int,
        min_v: int,
        max_v: int,
    ) -> None:
        new_value = self._cc_to_range(value, min_v, max_v)
        if int(self._note_style.get(key, new_value)) == new_value:
            return
        self._note_style[key] = new_value
        self._persist_note_style_patch({key: new_value})

    def _persist_note_style_patch(self, patch: dict[str, int]) -> None:
        data = cfg.load()
        note_style = data.setdefault("note_style", {})
        note_style.update(patch)
        note_style["active_theme_id"] = "custom"
        note_style["experimental_claire_script_enabled"] = 0
        data.setdefault("slide_palette", {})["enabled"] = False
        cfg.save(data)

    def _sanitize_legacy_note_automation(self) -> None:
        """Clear stale Claire/palette metadata when timed sync is not enabled."""
        data = cfg.load()
        changed = False

        if not bool(data.get("slide_palette", {}).get("enabled", False)):
            note_style = data.setdefault("note_style", {})
            if (
                str(note_style.get("active_theme_id", "custom")) == "claire_de_lune"
                or bool(note_style.get("experimental_claire_script_enabled", 0))
            ):
                note_style["active_theme_id"] = "custom"
                note_style["experimental_claire_script_enabled"] = 0
                changed = True

            note_styles = data.get("note_styles", [])
            if isinstance(note_styles, list):
                for style in note_styles:
                    if not isinstance(style, dict):
                        continue
                    if (
                        str(style.get("active_theme_id", "custom")) == "claire_de_lune"
                        or bool(style.get("experimental_claire_script_enabled", 0))
                    ):
                        style["active_theme_id"] = "custom"
                        style["experimental_claire_script_enabled"] = 0
                        changed = True

            performances = data.get("performances", [])
            if isinstance(performances, list):
                for performance in performances:
                    if not isinstance(performance, dict):
                        continue
                    for theme in performance.get("themes", []):
                        if not isinstance(theme, dict):
                            continue
                        note_cfg = theme.get("note_style", {})
                        if isinstance(note_cfg, dict) and (
                            str(note_cfg.get("active_theme_id", "custom")) == "claire_de_lune"
                            or bool(note_cfg.get("experimental_claire_script_enabled", 0))
                        ):
                            note_cfg["active_theme_id"] = "custom"
                            note_cfg["experimental_claire_script_enabled"] = 0
                            changed = True
                        channels = theme.get("channels", {})
                        if isinstance(channels, dict):
                            for channel_entry in channels.values():
                                if not isinstance(channel_entry, dict):
                                    continue
                                channel_style = channel_entry.get("note_style", {})
                                if isinstance(channel_style, dict) and (
                                    str(channel_style.get("active_theme_id", "custom")) == "claire_de_lune"
                                    or bool(channel_style.get("experimental_claire_script_enabled", 0))
                                ):
                                    channel_style["active_theme_id"] = "custom"
                                    channel_style["experimental_claire_script_enabled"] = 0
                                    changed = True

        if changed:
            cfg.save(data)

    def _set_display_value_from_cc(
        self,
        key: str,
        value: int,
        min_v: int,
        max_v: int,
    ) -> None:
        new_value = self._cc_to_range(value, min_v, max_v)
        if int(self._display_style.get(key, new_value)) == new_value:
            return
        self._display_style[key] = new_value
        data = cfg.load()
        display_style = data.setdefault("display_style", {})
        display_style[key] = new_value
        cfg.save(data)

    def _toggle_keyboard_visible(self) -> None:
        current = bool(self._keyboard_style.get("visible", True))
        new_value = not current
        self._keyboard_style["visible"] = new_value
        data = cfg.load()
        keyboard_style = data.setdefault("keyboard_style", {})
        keyboard_style["visible"] = new_value
        cfg.save(data)
        if self._piano is not None:
            self._piano.visible = new_value

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

    def _on_slide_advance(self) -> None:
        """Called each time the background slideshow advances to the next slide.
        If a slide palette is active, cycle to the next palette colour entry."""
        self._active_style_cue_index = self._bg_slide_index
        self._apply_active_style_cue()
        sp = self._slide_palette_cfg
        if not sp.get("enabled", False):
            return
        palette: list[dict] = sp.get("palette", [])
        if len(palette) < 2:
            return
        self._palette_index = (self._palette_index + 1) % len(palette)
        entry = palette[self._palette_index]
        transition_ms = max(200, int(sp.get("transition_ms", 2000)))
        self._palette_color_start    = list(self._palette_color_current)
        self._palette_color_target   = [float(entry.get("color_r", 86)),
                                         float(entry.get("color_g", 128)),
                                         float(entry.get("color_b", 220))]
        self._palette_interior_start  = list(self._palette_interior_current)
        self._palette_interior_target = [float(entry.get("interior_r", 180)),
                                          float(entry.get("interior_g", 210)),
                                          float(entry.get("interior_b", 255))]
        self._palette_blend_ms = transition_ms
        self._palette_blend_elapsed_ms = 0

    def _update_slide_palette(self, dt: int) -> None:
        """Advance the slide-palette colour blend and push colours to note_style + LEDs."""
        sp = self._slide_palette_cfg
        if not sp.get("enabled", False):
            return
        palette: list[dict] = sp.get("palette", [])
        if not palette:
            return

        if self._palette_blend_ms > 0 and self._palette_blend_elapsed_ms < self._palette_blend_ms:
            self._palette_blend_elapsed_ms = min(self._palette_blend_ms,
                                                  self._palette_blend_elapsed_ms + dt)
            a = self._palette_blend_elapsed_ms / float(max(1, self._palette_blend_ms))
            smooth = a * a * (3.0 - 2.0 * a)
            self._palette_color_current = [
                self._palette_color_start[i] + (self._palette_color_target[i] - self._palette_color_start[i]) * smooth
                for i in range(3)
            ]
            self._palette_interior_current = [
                self._palette_interior_start[i] + (self._palette_interior_target[i] - self._palette_interior_start[i]) * smooth
                for i in range(3)
            ]

        r  = max(0, min(255, int(self._palette_color_current[0])))
        g  = max(0, min(255, int(self._palette_color_current[1])))
        b  = max(0, min(255, int(self._palette_color_current[2])))
        ir = max(0, min(255, int(self._palette_interior_current[0])))
        ig = max(0, min(255, int(self._palette_interior_current[1])))
        ib = max(0, min(255, int(self._palette_interior_current[2])))

        self._note_style["color_r"] = r
        self._note_style["color_g"] = g
        self._note_style["color_b"] = b
        self._note_style["interior_r"] = ir
        self._note_style["interior_g"] = ig
        self._note_style["interior_b"] = ib

        # Keep the audience-color tracker in sync so audience events blend
        # from the current palette colour rather than jumping.
        self._color_current = [float(r), float(g), float(b)]

        if self._led_output is not None:
            entry = palette[self._palette_index % len(palette)]
            prev_entry = palette[(self._palette_index - 1) % len(palette)]
            bratio = min(1.0, self._palette_blend_elapsed_ms / float(max(1, self._palette_blend_ms))) \
                if self._palette_blend_ms > 0 else 1.0
            smooth = bratio * bratio * (3.0 - 2.0 * bratio)
            pr = prev_entry.get("active_r", r)
            tr = entry.get("active_r", r)
            pg = prev_entry.get("active_g", g)
            tg = entry.get("active_g", g)
            pb = prev_entry.get("active_b", b)
            tb = entry.get("active_b", b)
            ar = max(0, min(255, int(pr + (tr - pr) * smooth)))
            ag = max(0, min(255, int(pg + (tg - pg) * smooth)))
            ab = max(0, min(255, int(pb + (tb - pb) * smooth)))
            self._led_output.set_active_color(ar, ag, ab)

    def _apply_live_note_style(self, note_style: dict[str, int]) -> None:
        style_patch = dict(note_style)
        style_patch.pop("speed_px_per_sec", None)
        self._note_style.update(style_patch)
        self._note_style["speed_px_per_sec"] = int(cfg.load().get("note_style", {}).get("speed_px_per_sec", 420))
        new_r = float(self._note_style.get("color_r", 0))
        new_g = float(self._note_style.get("color_g", 230))
        new_b = float(self._note_style.get("color_b", 230))
        self._color_current = [new_r, new_g, new_b]
        self._color_start = [new_r, new_g, new_b]
        self._color_target = [new_r, new_g, new_b]
        self._color_blend_ms = 0
        self._color_blend_elapsed_ms = 0
        self._refresh_claire_script_state()
        if self._led_output is not None:
            self._led_output.set_active_color(int(new_r), int(new_g), int(new_b))

    def _apply_active_style_cue(self) -> None:
        performance_id = perf_store.get_active_performance_id()
        theme_index = perf_store.get_active_theme_index(performance_id)
        if not performance_id or theme_index < 0:
            return
        if not perf_store.is_theme_style_sync_enabled(performance_id, theme_index):
            return
        cue_count = perf_store.get_theme_style_cue_count(performance_id, theme_index)
        if cue_count <= 0:
            return
        cue_index = max(0, min(cue_count - 1, self._active_style_cue_index))
        cue_style = perf_store.get_theme_cue_note_style(performance_id, theme_index, cue_index, 0)
        if cue_style:
            self._apply_live_note_style(cue_style)

    @staticmethod
    def _blend_style_value(a: object, b: object, t: float) -> int:
        # Treat bool-like toggles as a threshold flip, not a partial value.
        a_int = int(a) if isinstance(a, (int, float, bool)) else 0
        b_int = int(b) if isinstance(b, (int, float, bool)) else a_int
        if (a_int in (0, 1)) and (b_int in (0, 1)):
            return b_int if t >= 0.5 else a_int
        return int(round(a_int + (b_int - a_int) * t))

    def _apply_style_sync_transition_blend(
        self,
        performance_id: str,
        theme_index: int,
        cue_index: int,
        next_cue_index: int,
        blend: float,
    ) -> None:
        if not perf_store.is_theme_style_sync_enabled(performance_id, theme_index):
            return
        current_style = perf_store.get_theme_cue_note_style(performance_id, theme_index, cue_index, 0)
        next_style = perf_store.get_theme_cue_note_style(performance_id, theme_index, next_cue_index, 0)
        if not current_style or not next_style:
            return

        blended: dict[str, int] = {}
        for key, cur_v in current_style.items():
            nxt_v = next_style.get(key, cur_v)
            blended[key] = self._blend_style_value(cur_v, nxt_v, blend)
        self._apply_live_note_style(blended)

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
        transition_pct = int(self._display_style.get("background_transition_percent", 35))
        performance_id = perf_store.get_active_performance_id()
        theme_index = perf_store.get_active_theme_index(performance_id)
        if (
            performance_id
            and theme_index >= 0
            and perf_store.is_theme_style_sync_enabled(performance_id, theme_index)
        ):
            cue_count = perf_store.get_theme_style_cue_count(performance_id, theme_index)
            cue_index = max(0, min(cue_count - 1, self._active_style_cue_index))
            transition_pct = perf_store.get_theme_cue_transition_percent(
                performance_id,
                theme_index,
                cue_index,
            )
        transition_ratio = transition_pct / 100.0
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
                self._on_slide_advance()

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
                if performance_id and theme_index >= 0:
                    cue_count = perf_store.get_theme_style_cue_count(performance_id, theme_index)
                    cue_index = max(0, min(cue_count - 1, self._bg_slide_index))
                    next_cue_index = max(0, min(cue_count - 1, next_idx))
                    self._apply_style_sync_transition_blend(
                        performance_id,
                        theme_index,
                        cue_index,
                        next_cue_index,
                        blend,
                    )

        return current_frame, next_frame, blend

    def _clear_background_scale_cache(self) -> None:
        self._bg_scale_cache.clear()
        self._bg_scale_cache_screen_size = (0, 0)

    def _get_scaled_background_surface(self, frame: pygame.Surface) -> pygame.Surface:
        sw, sh = self.screen.get_size()
        if self._bg_scale_cache_screen_size != (sw, sh):
            self._bg_scale_cache.clear()
            self._bg_scale_cache_screen_size = (sw, sh)

        key = (id(frame), sw, sh)
        cached = self._bg_scale_cache.get(key)
        if cached is not None:
            return cached

        scaled = pygame.transform.smoothscale(frame, (sw, sh))
        self._bg_scale_cache[key] = scaled
        if len(self._bg_scale_cache) > 48:
            self._bg_scale_cache.pop(next(iter(self._bg_scale_cache)))
        return scaled

    def _quit(self) -> None:
        self._leave_highway()
        self.running = False
        pygame.quit()
        sys.exit()
