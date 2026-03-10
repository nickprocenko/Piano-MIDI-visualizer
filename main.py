import sys
import pygame
from src.app import App


def main() -> None:
    pygame.init()
    pygame.font.init()

    info = pygame.display.Info()
    screen = pygame.display.set_mode(
        (info.current_w, info.current_h),
        pygame.NOFRAME | pygame.FULLSCREEN,
    )
    pygame.display.set_caption("Piano MIDI Visualizer")

    app = App(screen)
    app.run()


if __name__ == "__main__":
    main()
