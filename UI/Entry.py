import pygame
import pyperclip

from UI.Abstract import UIElement, UICanvas
from Utils.Text import draw_centered_text
from Utils.Timer import Timer, SpacedCallback

from Game import Game

ALLOWED_SPECIAL_CHARS = [
    " ",
    ".",
    ",",
    "!",
    "?",
    ":",
    ";",
    "-",
    "_",
    "+",
    "=",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "<",
    ">",
    "/",
    "\\",
    "|",
    "*",
    "&",
    "%",
    "$",
    "#",
    "@",
    "'",
    '"',
    "`",
    "^",
    "~",
]


class Entry(UIElement):
    def __init__(
        self,
        parent: UICanvas = None,
        x=0,
        y=0,
        center=None,
        width=100,
        height=100,
        bg_color: tuple | str = (50, 50, 50),
        fg_color=(0, 0, 0),
        font=None,
        placeholder: str = "",
        border_width=1,
        corner_radius=10,
        focus_color=(150, 150, 150),
        is_password=False,
    ):

        super().__init__(
            parent,
            x,
            y,
            center,
            width,
            height,
            bg_color,
            fg_color,
            font,
            placeholder,
            corner_radius,
        )
        self.border_width = border_width
        self.focused = False
        self.focus_color = focus_color
        self.original_fg_color = fg_color
        self.is_password = is_password
        if is_password:
            self.text = ""
        self.key_pressed_timer = Timer()
        self.placeholder = placeholder

        self.key_pressed = None
        self.enter_key_callback = None

        self.caret = Caret(self.game, self)

    def render(self, surface: pygame.Surface):
        if self.visible:
            super().render(surface)
            pygame.draw.rect(
                surface, self.bg_color, self.rect, border_radius=self.corner_radius
            )
            pygame.draw.rect(
                surface,
                self.fg_color,
                self.rect,
                width=self.border_width,
                border_radius=self.corner_radius,
            )
            text = "*" * len(self.text) if self.is_password else self.text
            if text:  # Only draw if there's text to display
                draw_centered_text(self.font, surface, text, self.fg_color, self.rect)

            # Render caret
            self.caret.render(surface)

    def update(self, dt):
        if self.visible:

            # Update caret
            self.caret.update(dt)

            if self.key_pressed:
                self.key_pressed_timer.start(0.5)
                if self.key_pressed_timer.finished:
                    if self.key_pressed == pygame.K_BACKSPACE:
                        self._handle_backspace()
                    elif self.key_pressed == pygame.K_LEFT:
                        self._handle_arrow_left()
                    elif self.key_pressed == pygame.K_RIGHT:
                        self._handle_arrow_right()
                    elif (
                        self.key_pressed.isalnum()
                        or self.key_pressed in ALLOWED_SPECIAL_CHARS
                    ):
                        self._handle_printable(self.key_pressed)
                self.key_pressed_timer.update()

            if self.game.clicked_sx == -1:
                if self.rect.collidepoint(self.game.cursorpos):
                    self.focused = True
                    self.fg_color = self.focus_color
                    self.game.need_key_event_handling = False

                    # Clear placeholder
                    if self.text == self.placeholder:
                        self.text = ""
                        self.caret.reset_position()
                else:
                    self.focused = False
                    self.fg_color = self.original_fg_color
                    self.game.need_key_event_handling = True

                    # Restore placeholder
                    if self.text == "":
                        self.text = self.placeholder
                        self.caret.reset_position()

            if self.focused:
                for event in self.game.events:
                    if event.type == pygame.KEYDOWN:

                        if event.mod & pygame.KMOD_CTRL:
                            if event.key == pygame.K_BACKSPACE:
                                if self.caret.index_in_text == 0:
                                    return
                                if self.text[self.caret.index_in_text - 1] == " ":
                                    self._handle_backspace()
                                    return
                                while (
                                    self.caret.index_in_text > 0
                                    and self.text[self.caret.index_in_text - 1] != " "
                                ):
                                    self._handle_backspace()

                            if event.key == pygame.K_DELETE:
                                if self.caret.index_in_text == len(self.text):
                                    return
                                if self.text[self.caret.index_in_text] == " ":
                                    self._hande_delete()
                                    return
                                while (
                                    self.caret.index_in_text < len(self.text)
                                    and self.text[self.caret.index_in_text] != " "
                                ):
                                    self._hande_delete()

                            if event.key == pygame.K_v:
                                self.text = pyperclip.paste()
                                try:
                                    surf = self.font.render(
                                        self.text, True, (255, 255, 255)
                                    )
                                    rect = surf.get_rect()
                                except pygame.error:
                                    print(f"Error in rendering text: {self.text}")
                                    self.text = ""
                                    self.caret.reset_position()
                                else:
                                    self.caret.move_to(rect.top, rect.right)

                        else:
                            if event.key == pygame.K_BACKSPACE:
                                # Delete character at the caret position
                                self._handle_backspace()

                            if event.key == pygame.K_DELETE:
                                # Delete character after the caret position
                                if event.key == pygame.KMOD_CTRL:
                                    self.clear_text()
                                self._hande_delete()

                            elif event.key == pygame.K_LEFT:
                                self._handle_arrow_left()

                            elif event.key == pygame.K_RIGHT:
                                self._handle_arrow_right()

                            elif (
                                event.key == pygame.K_RETURN and self.enter_key_callback
                            ):
                                self.enter_key_callback()

                            elif (
                                event.unicode.isalnum()
                                or event.unicode in ALLOWED_SPECIAL_CHARS
                            ):
                                self._handle_printable(event.unicode)

                    if event.type == pygame.KEYUP:
                        self.key_pressed = None
                        self.key_pressed_timer.stop()

    def pack(self):
        surf = self.font.render(self.text, True, (255, 255, 255))
        rect = surf.get_rect()
        center = self.rect.center
        self.rect.size = rect.size
        self.rect.center = center
        self.rect.width += 10
        self.rect.height += 10
        self.width, self.height = rect.size

    def clear_text(self):
        self.text = ""
        self.caret.reset_position()

    def set_enter_key_callback(self, callback):
        self.enter_key_callback = callback

    def _handle_backspace(self):
        if self.caret.index_in_text == 0:
            return
        self.caret.remove_char(self.text[self.caret.index_in_text - 1])
        aux_text = list(self.text)
        aux_text.pop(self.caret.index_in_text)
        aux_text = "".join(aux_text)
        self.text = self.text if self.text == "" else aux_text
        self.key_pressed = pygame.K_BACKSPACE

    def _hande_delete(self):
        if self.caret.index_in_text == len(self.text):
            return
        self.caret.delete_char(self.text[self.caret.index_in_text])
        aux_text = list(self.text)
        aux_text.pop(self.caret.index_in_text)
        aux_text = "".join(aux_text)
        self.text = self.text if self.text == "" else aux_text
        self.key_pressed = pygame.K_DELETE

    def _handle_printable(self, char):
        if self.font.size(self.text)[0] <= self.width - 40:
            aux_text = list(self.text)
            aux_text.insert(self.caret.index_in_text, char)
            self.text = "".join(aux_text)
            self.caret.add_char(char)
            # Update rect if needed (This would make the entry scale when exceeding length)
            # surf, rect = self.font.render(self.text)
            # if self.rect.width <= rect.width:
            #     self.rect.width = self.width = rect.width
            self.key_pressed = char

    def _handle_arrow_left(self):
        if self.caret.index_in_text == 0:
            return
        self.caret.shift_char_left(self.text[self.caret.index_in_text - 1])
        self.key_pressed = pygame.K_LEFT

    def _handle_arrow_right(self):
        if self.caret.index_in_text == len(self.text):
            return
        self.caret.shift_char_right(self.text[self.caret.index_in_text])
        self.key_pressed = pygame.K_RIGHT


class Paragraph(Entry):
    def __init__(
        self,
        parent: UICanvas = None,
        x=0,
        y=0,
        center=None,
        width=100,
        height=100,
        bg_color: tuple | str = (50, 50, 50),
        fg_color=(0, 0, 0),
        font=None,
        placeholder: str = "",
        border_width=1,
        corner_radius=10,
        focus_color=(150, 150, 150),
        is_password=False,
    ):
        super().__init__(
            parent,
            x,
            y,
            center,
            width,
            height,
            bg_color,
            fg_color,
            font,
            placeholder,
            border_width,
            corner_radius,
            focus_color,
            is_password,
        )

        self.lines = ["" for _ in range(height // self.font.get_height())]
        self.line_index = 0
        self.line_height = self.font.get_height()

    def _handle_printable(self, char):
        txt = self.lines[self.line_index]
        if self.font.size(txt)[0] <= self.width - 40:
            aux_text = list(txt)
            aux_text.insert(self.caret.index_in_text, char)
            self.lines[self.line_index] = "".join(aux_text)
            print(self.lines)
            self.caret.add_char(char)
            self.key_pressed = char
        else:
            self.caret.reset_position()
            self.text += "\n"
            self.caret.move_by(0, self.line_height * (self.line_index + 1))
            self.line_index += 1

    def _handle_backspace(self):
        # TODO
        pass

    def get_text(self):
        return "\n".join(l for l in self.lines if l != "")

    def render(self, surface: pygame.Surface):
        if self.visible:
            pygame.draw.rect(
                surface,
                self.bg_color,
                self.rect,
                width=self.border_width,
                border_radius=self.corner_radius,
            )
            self.caret.render(surface)
            for i, line in enumerate(self.lines):
                draw_centered_text(
                    self.font,
                    surface,
                    line,
                    self.fg_color,
                    pygame.Rect(
                        self.rect.x,
                        self.rect.y + i * self.line_height,
                        self.rect.width,
                        self.line_height,
                    ),
                )


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


class Caret:
    def __init__(self, game: Game, parent: Entry):
        self.game = game
        self.parent = parent
        self.font = self.parent.font
        self.reset_position()
        self.timer = Timer()
        self.visible = True

        self.CARET_BLINK_SPEED = 0.4
        self.blink = SpacedCallback(self.toggle_visibility, 0.5)
        self.blink.start()

        self.color = (230, 230, 230)

        self.hiding = False

        # abc|defg <- index_in_text = 3
        # |abcdefg <- index_in_text = 0
        # abcdefg| <- index_in_text = 7 = len(text)
        # Removing a character from the text will move the caret to the left:
        # abc|defg <- index_in_text = 2
        # ab|defg <- index_in_text = 1

    def reset_position(self):
        # self.offset = pygame.Vector2((self.parent.rect.width * .5 + self.parent.font.size(
        #     self.parent.text)[0] * .5, (self.parent.rect.height - self.parent.font.get_height()) // 2 - 3))
        self.offset = pygame.Vector2(
            (
                self.parent.rect.width * 0.5
                + self.font.size(self.parent.text)[0] * 0.5,
                (self.parent.rect.h - self.font.get_height()) * 0.5 - 3,
            )
        )

        self.topleft: pygame.Vector2 = self.parent.rect.topleft + self.offset
        self.rect = pygame.Rect(self.topleft, (2, self.parent.font.get_height() + 6))
        self.index_in_text = len(self.parent.text)

    def add_char(self, char):
        self.topleft += pygame.Vector2(self.parent.font.size(char)[0] * 0.5, 0)
        self.rect.update(self.topleft, self.rect.size)
        self.index_in_text += 1

    def remove_char(self, char):
        self.topleft -= pygame.Vector2(self.parent.font.size(char)[0] * 0.5, 0)
        self.rect.topleft = self.topleft
        self.index_in_text -= 1

    def delete_char(self, char):
        # We don't need to move the caret to the left because the character after the caret will be deleted
        self.topleft += pygame.Vector2(self.parent.font.size(char)[0] * 0.5, 0)
        self.rect.topleft = self.topleft

    def shift_char_right(self, char):
        self.topleft += pygame.Vector2(self.parent.font.size(char)[0], 0)
        self.rect.topleft = self.topleft
        self.index_in_text += 1

    def shift_char_left(self, char):
        self.topleft -= pygame.Vector2(self.parent.font.size(char)[0], 0)
        self.rect.topleft = self.topleft
        self.index_in_text -= 1

    def hide(self):
        self.visible = False
        self.hiding = True

    def update(self, dt):
        if not self.hiding:
            self.blink.update()
            # print("Caret position:", self.topleft, self.index_in_text)

    def render(self, surface: pygame.Surface):
        if self.visible and self.parent.focused:
            # pygame.draw.rect(surface, self.parent.fg_color, self.rect, width=3)
            pygame.draw.rect(surface, self.color, self.rect, width=3)

    def move_to(self, x, y):
        self.topleft = pygame.Vector2(x, y)
        self.rect.topleft = self.topleft

    def move_by(self, dx, dy):
        self.topleft += pygame.Vector2(dx, dy)
        self.rect.topleft = self.topleft

    def toggle_visibility(self):
        self.visible = not self.visible
