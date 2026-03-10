import sys
import pygame
from enum import Enum, auto


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

        self._highway_font: pygame.font.Font | None = None

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

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._quit()
                return

            if self.state == State.MENU:
                action = self.menu.handle_event(event)
                if action == "start":
                    self.state = State.HIGHWAY
                elif action == "settings":
                    pass  # TODO: implement Settings screen in a future phase
                elif action == "quit":
                    self._quit()

            elif self.state == State.HIGHWAY:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.state = State.MENU

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
            self._highway_font = pygame.font.SysFont("Arial", 36)
        text = self._highway_font.render("Press ESC to return", True, (200, 200, 200))
        rect = text.get_rect(center=self.screen.get_rect().center)
        self.screen.blit(text, rect)

    def _quit(self) -> None:
        self.running = False
        pygame.quit()
        sys.exit()
