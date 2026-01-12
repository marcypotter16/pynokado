import pygame.draw
from pygame import Surface

from UI.Abstract import UIElement, UICanvas
from UI.Button import TextButton
from UI.Label import Label


class Slider(UIElement):
    def __init__(
        self,
        parent: UICanvas = None,
        x=0,
        y=0,
        center=None,
        width=100,
        height=100,
        bg_color: tuple | str = (40, 40, 40),
        fg_color=(0, 0, 0),
        text: str = "",
        corner_radius=10,
        start: float = 0,
        end: float = 100,
        default: float = 0,
    ):
        super().__init__(
            parent, x, y, center, width, height, bg_color, fg_color, text, corner_radius
        )
        self.start, self.end, self.value = start, end, default
        self.slider_button = TextButton(
            parent=self,
            center=(self.x, self.y + 0.5 * self.height),
            text="|",
            bg_color="transparent",
            fg_color=fg_color,
            command=None,
        )
        self.value_label = Label(
            parent=self,
            center=(round(self.x + 0.5 * width), self.y),
            fg_color=(255, 255, 255),
        )
        self.value_label.text = str(self.value)

    def move_slider(self):
        if self.game.actions["mouse_sx"] == 1:
            if self.slider_button.rect.collidepoint(self.game.cursorpos):
                self.slider_button.x = (
                    self.x
                    if self.game.cursorpos[0] <= self.x
                    else min(self.game.cursorpos[0], self.x + self.width)
                )
                half_btn_width = round(0.5 * self.slider_button.width)
                self.slider_button.x -= half_btn_width
                self.value = (
                    self.start
                    + float(self.slider_button.x + half_btn_width - self.x)
                    / self.width
                    * self.end
                )
                self.slider_button.rect.x = self.slider_button.x
                self.value_label.text = str(round(self.value))

    def update(self, dt):
        self.move_slider()
        # self.slider_button.update(dt)

    def render(self, surface: Surface):
        super().render(surface)
        pygame.draw.line(
            surface,
            self.fg_color,
            (self.x, self.y + 0.5 * self.height),
            (self.x + self.width, self.y + 0.5 * self.height),
            width=3,
        )
        self.slider_button.render(surface)
        self.value_label.render(surface)
