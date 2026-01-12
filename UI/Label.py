import pygame

from Game import Game

# from States.State import State
from UI.Abstract import UIElement, UICanvas
from Utils.Text import draw_centered_text


# TODO Refactor this entire file!
class Label(UIElement):
    def __init__(
        self,
        parent: UICanvas = None,
        x=0,
        y=0,
        center=None,
        width=None,
        height=None,
        font: pygame.font.Font = None,
        bg_color: tuple | str = "transparent",
        fg_color=(0, 0, 0),
        text: str = "",
        corner_radius=10,
        underline=False,
    ):
        super().__init__(
            parent,
            x,
            y,
            center,
            width if width is not None else 0,
            height if height is not None else 0,
            bg_color,
            fg_color,
            font,
            text,
            corner_radius,
        )
        self.underline = underline

        if font is None:
            # self.font = self.game.fonts["ant"]["small"]
            self.font = self.game.get_font("ant", 15)
        else:
            self.font = font

        # try:
        #     self.font.render(self.text if self.text else " ")
        # except pygame.error as e:
        #     print(f"Label render error during init: text='{self.text}', error={e}")
        #     self.text = ""

        # Auto-size the label based on text if width/height not provided
        if width is None:
            surf = self.font.render(
                self.text if self.text else " ", True, (255, 255, 255)
            )
            rect = surf.get_rect()
            self.width = self.rect.width = rect.width + 20
        else:
            self.width = self.rect.width = width

        if height is None:
            self.height = self.rect.height = self.font.get_height() + 10
        else:
            self.height = self.rect.height = height

        # Update rect with new dimensions
        self.rect.update(self.x, self.y, self.width, self.height)

        if center is not None:
            self.rect.center = center
            self.x, self.y = self.rect.x, self.rect.y

        self.lines = [""]
        self.set_text(self.text)

    def set_text(self, new_text: str):
        try:
            surf = self.font.render(new_text, True, (255, 255, 255))
            self.text = new_text
            self.lines = self._wrap_text()
            # print(self.text, self.lines)
        except:
            print(f"Label set_text error")

    def _wrap_text(self, max_width: int = None) -> list[str]:
        """
        Wraps text to fit within max_width, breaking at word boundaries.
        Returns a list of lines.
        """
        max_width = max_width if max_width else self.rect.width
        words = self.text.split()
        lines = []
        current_line = []

        for word in words:
            # Try adding this word to the current line
            test_line = " ".join(current_line + [word])
            text_width = self.font.size(test_line)[0]

            if text_width <= max_width:
                # Word fits, add it to current line
                current_line.append(word)
            else:
                # Word doesn't fit
                if current_line:
                    # Save current line and start new one with this word
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    # Single word is too long, add it anyway
                    lines.append(word)
                    current_line = []

        # Add remaining words
        if current_line:
            lines.append(" ".join(current_line))

        return lines if lines else [""]

    def render(self, surface: pygame.Surface):
        super().render(surface)
        # Render each line
        # print(self.lines)
        if len(self.lines) == 1:
            draw_centered_text(self.font, surface, self.text, self.fg_color, self.rect)
            return
        for i, line in enumerate(self.lines):
            surf = self.font.render(line, True, self.fg_color)
            rect = surf.get_rect()
            line_y = self.rect.y + i * rect.height
            line_rect = pygame.Rect(self.rect.x, line_y, rect.w, rect.h)

            # print(line_rect)
            pygame.draw.rect(surface, (0, 255, 0), line_rect, width=1)
            surface.blit(surf, line_rect)
            if self.underline:
                pygame.draw.rect(
                    surface,
                    self.fg_color,
                    pygame.Rect(
                        self.rect.x - 10,
                        self.rect.bottom - 0.1 * self.rect.height + 6,
                        self.rect.w + 20,
                        self.rect.h * 0.1,
                    ),
                    border_radius=int(self.rect.h * 0.05),
                )
        pygame.draw.rect(surface, (255, 0, 0), self.rect, width=1)


def _wrap_text(font, text, max_width: int = None) -> list[str]:
    """
    Wraps text to fit within max_width, breaking at word boundaries.
    Returns a list of lines.
    """
    max_width = max_width if max_width else 200
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        # Try adding this word to the current line
        test_line = " ".join(current_line + [word])
        text_width = font.size(test_line)[0]

        if text_width <= max_width:
            # Word fits, add it to current line
            current_line.append(word)
        else:
            # Word doesn't fit
            if current_line:
                # Save current line and start new one with this word
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                # Single word is too long, add it anyway
                lines.append(word)
                current_line = []

    # Add remaining words
    if current_line:
        lines.append(" ".join(current_line))

    return lines if lines else [""]


if __name__ == "__main__":
    pygame.init()
    font = pygame.font.SysFont("consolas", 20)
    text = "The brown fox jumps over the lazy dog. Zio pera"
    print(_wrap_text(font, text, 100))
    print(_wrap_text(font, text, 200))
    g = Game()
    s = State(g)
    l = Label(
        s.canvas,
        center=g.GAME_CENTER,
        width=100,
        height=20,
        text=text,
        fg_color=(255, 255, 255),
    )
    g.push_state(s)
    while g.running:
        g.game_loop()
