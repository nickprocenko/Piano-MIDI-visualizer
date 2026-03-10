import sys
import pygame
from enum import Enum, auto
from typing import Optional

from src.midi_input import MidiInput
from src.piano import Piano


class State(Enum):
    MENU = auto()
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

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(60)
            self._handle_events()
            self._update(dt)
            self._draw()
            pygame.display.flip()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _enter_highway(self) -> None:
        """Set up MIDI and piano when entering the HIGHWAY state."""
        self._piano = Piano(self.screen)
        self._midi = MidiInput()
        self._midi.connect()

    def _leave_highway(self) -> None:
        """Clean up MIDI resources when leaving the HIGHWAY state."""
        if self._midi is not None:
            self._midi.close()
            self._midi = None
        self._piano = None

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._quit()
                return

            if self.state == State.MENU:
                action = self.menu.handle_event(event)
                if action == "start":
                    self._enter_highway()
                    self.state = State.HIGHWAY
                elif action == "settings":
                    pass  # TODO: implement Settings screen in a future phase
                elif action == "quit":
                    self._quit()

            elif self.state == State.HIGHWAY:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._leave_highway()
                        self.state = State.MENU
                    elif event.key == pygame.K_r:
                        # Retry MIDI connection
                        if self._midi is not None and not self._midi.connected:
                            self._midi.connect()

    def _update(self, dt: int) -> None:
        pass

    def _draw(self) -> None:
        if self.state == State.MENU:
            self.menu.draw()
        elif self.state == State.HIGHWAY:
            self._draw_highway()

    def _draw_highway(self) -> None:
        self.screen.fill((10, 10, 10))

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

        # Connected — show device name and piano
        device_label = self._small_font.render(
            f"MIDI: {self._midi.port_name}", True, (100, 200, 100)
        )
        self.screen.blit(device_label, (16, 12))

        esc_text = self._small_font.render("Press ESC to return", True, (150, 150, 150))
        esc_rect = esc_text.get_rect(topright=(screen_rect.right - 16, 12))
        self.screen.blit(esc_text, esc_rect)

        # Draw piano with active notes highlighted
        active_notes = self._midi.get_active_notes()
        if self._piano is not None:
            self._piano.draw(active_notes)

    def _quit(self) -> None:
        self._leave_highway()
        self.running = False
        pygame.quit()
        sys.exit()
