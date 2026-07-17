import pygame

from UI.Abstract import UIElement, UICanvas
from Utils.Text import draw_centered_text


class TextButton(UIElement):
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
        text: str = "",
        font: pygame.font.Font | None = None,
        corner_radius=10,
        command=lambda: print("Clicked"),
        hover_color=(150, 150, 150),
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
            text,
            corner_radius,
        )
        self.font: pygame.font.Font = (
            self.game.fonts["comfortaa"]["medium"] if font is None else font
        )
        self.hover_color = hover_color if type(hover_color) == tuple else (0,0,0,0)
        self.height = self.font.get_height() + 10
        self.command = None
        if callable(command):
            self.command = command

    def update(self, dt):
        if self.visible:
            if self.interactable:
                if self.rect.collidepoint(self.game.cursorpos):
                    self.hover(dt)
                    # == -1 perchè voglio che il bottone sia cliccato quando rilasci il bottone del mouse
                    if self.game.clicked_sx == -1:
                        self.__clicked()
                else:
                    self.unhover()

    def hover(self, dt):
        self.bg_color = self.hover_color

    def unhover(self):
        self.bg_color = self.original_bg_color

    def __clicked(self):
        if self.command is not None:
            self.command.__call__()

    def pack(self, margin=(10, 10)):
        """Packs the button tightly to the text"""
        # self.height = self.font.get_height()
        # print(self.text)
        surf = self.font.render(self.text, True, (255, 255, 255))
        rect = surf.get_rect()
        self.width = rect.width + margin[0]
        self.height = rect.height + margin[1]
        self.rect.update(self.x, self.y, self.width, self.height)

    def render(self, surface: pygame.Surface):
        if self.visible:
            super().render(surface)
            # x = int(self.x + .5 * self.width)
            # y = int(self.y + self.height * .5)
            # x, y = self.x, self.y
            if self.text != "":
                draw_centered_text(
                    self.font, surface, self.text, self.fg_color, self.rect
                )


class ImageButton(TextButton):
    def __init__(
        self,
        parent: UICanvas = None,
        x=0,
        y=0,
        center=None,
        width=100,
        height=100,
        bg_color: tuple | str = "transparent",
        fg_color=(0, 0, 0),
        text: str = "",
        font: pygame.font.Font | None = None,
        corner_radius=10,
        command=lambda: print("Clicked"),
        hover_color: tuple | str = "transparent",
        hover_animation: list[pygame.Surface] = None,
        mouse_pressed_image: pygame.Surface = None,
        animation_fps: int = 60,
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
            text,
            font,
            corner_radius,
            command,
            hover_color,
        )
        self.animation = [
            pygame.transform.smoothscale(image, self.rect.size)
            for image in hover_animation
        ]

        if mouse_pressed_image is not None:
            self.mouse_pressed_image = pygame.transform.scale(
                mouse_pressed_image, self.rect.size
            )
        else:
            self.mouse_pressed_image = self.animation[0]

        self.current_image_index: int = 0
        self.current_image: pygame.image = self.animation[0]
        self.animation_list_length: int = len(hover_animation)
        self.prev_timestamp: float = 0
        # Time in seconds between animation frames
        self._SECONDS_BETWEEN_FRAMES: float = 1.0 / animation_fps

    def update(self, dt):
        # print(self.current_image_index)
        if self.rect.collidepoint(self.game.cursorpos):
            if self.game.actions["mouse_sx"]:
                self.current_image = self.mouse_pressed_image
            elif self.game.clicked_sx == -1:
                self.command.__call__()
            else:
                self.hover(dt)
        else:
            self.unhover()
        if self.game.clicked_sx == -1 and not self.rect.collidepoint(
            self.game.cursorpos
        ):
            self.current_image = self.animation[0]
            self.current_image_index = 0

    def hover(self, dt):
        self.prev_timestamp += dt
        if self.prev_timestamp >= self._SECONDS_BETWEEN_FRAMES:
            self.current_image_index = (
                self.current_image_index + 1
            ) % self.animation_list_length
            self.current_image = self.animation[self.current_image_index]
            self.prev_timestamp = 0
        self.bg_color = self.hover_color
        # if self.game.clicked_sx == -1:
        #     self.command.__call__()

    def unhover(self):
        """
        Resets the animation
        :return:
        """
        self.current_image_index = 0
        self.bg_color = self.original_bg_color

    def render(self, surface: pygame.Surface):
        if self.visible:
            super().render(surface)
            surface.blit(self.current_image, self.rect)
