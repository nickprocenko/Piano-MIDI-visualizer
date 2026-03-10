import pygame

# Colour palette
BG_COLOR = (15, 15, 20)
TITLE_COLOR = (230, 230, 230)
BUTTON_NORMAL_BG = (35, 35, 45)
BUTTON_HOVER_BG = (60, 60, 80)
BUTTON_TEXT_COLOR = (210, 210, 210)
BUTTON_HOVER_TEXT_COLOR = (255, 255, 255)
BUTTON_BORDER_COLOR = (80, 80, 110)

TITLE_FONT_SIZE = 56
BUTTON_FONT_SIZE = 32
BUTTON_WIDTH = 280
BUTTON_HEIGHT = 60
BUTTON_GAP = 20
TITLE_MARGIN_BOTTOM = 70


class Button:
    """A single clickable menu button."""

    def __init__(self, label: str, rect: pygame.Rect, font: pygame.font.Font) -> None:
        self.label = label
        self.rect = rect
        self.font = font
        self.hovered = False

    def draw(self, surface: pygame.Surface) -> None:
        bg = BUTTON_HOVER_BG if self.hovered else BUTTON_NORMAL_BG
        fg = BUTTON_HOVER_TEXT_COLOR if self.hovered else BUTTON_TEXT_COLOR
        pygame.draw.rect(surface, bg, self.rect, border_radius=8)
        pygame.draw.rect(surface, BUTTON_BORDER_COLOR, self.rect, width=1, border_radius=8)
        text = self.font.render(self.label, True, fg)
        text_rect = text.get_rect(center=self.rect.center)
        surface.blit(text, text_rect)

    def update_hover(self, mouse_pos: tuple[int, int]) -> None:
        self.hovered = self.rect.collidepoint(mouse_pos)

    def is_clicked(self, event: pygame.event.Event) -> bool:
        return (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(event.pos)
        )


class Menu:
    """Main menu screen with START, SETTINGS, and QUIT buttons."""

    BUTTON_LABELS = ["START", "SETTINGS", "QUIT"]
    BUTTON_ACTIONS = ["start", "settings", "quit"]

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self._title_font = pygame.font.SysFont("Arial", TITLE_FONT_SIZE, bold=True)
        self._button_font = pygame.font.SysFont("Arial", BUTTON_FONT_SIZE)
        self._buttons: list[Button] = []
        self._build_layout()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def handle_event(self, event: pygame.event.Event) -> str | None:
        """Process an event and return an action string or None."""
        if event.type == pygame.MOUSEMOTION:
            for btn in self._buttons:
                btn.update_hover(event.pos)
            return None

        for btn, action in zip(self._buttons, self.BUTTON_ACTIONS):
            if btn.is_clicked(event):
                return action

        return None

    def draw(self) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_title()
        for btn in self._buttons:
            btn.draw(self.screen)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        screen_rect = self.screen.get_rect()
        num_buttons = len(self.BUTTON_LABELS)
        total_height = num_buttons * BUTTON_HEIGHT + (num_buttons - 1) * BUTTON_GAP
        title_surf = self._title_font.render("Piano MIDI Visualizer", True, TITLE_COLOR)
        block_height = title_surf.get_height() + TITLE_MARGIN_BOTTOM + total_height
        start_y = (screen_rect.height - block_height) // 2
        cx = screen_rect.centerx

        self._title_pos = (cx - title_surf.get_width() // 2, start_y)
        self._title_surf = title_surf

        button_y = start_y + title_surf.get_height() + TITLE_MARGIN_BOTTOM
        self._buttons = []
        for label in self.BUTTON_LABELS:
            rect = pygame.Rect(cx - BUTTON_WIDTH // 2, button_y, BUTTON_WIDTH, BUTTON_HEIGHT)
            self._buttons.append(Button(label, rect, self._button_font))
            button_y += BUTTON_HEIGHT + BUTTON_GAP

    def _draw_title(self) -> None:
        self.screen.blit(self._title_surf, self._title_pos)
