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
        decimals: int = 0,
    ):
        super().__init__(
            parent, x, y, center, width, height, bg_color, fg_color, text, corner_radius
        )
        self.start, self.end, self.value = start, end, default
        self.decimals = decimals
        # A small grip. TextButton defaults to a 100x100 rect, which would make
        # the handle's collision area overlap several stacked sliders' rows and
        # let one press grab multiple sliders -- so size it explicitly here.
        self._handle_w = 14
        self._handle_h = max(int(self.height) + 8, 20)
        self.slider_button = TextButton(
            parent=self,
            center=(self.x, self.y + 0.5 * self.height),
            width=self._handle_w,
            height=self._handle_h,
            text="|",
            bg_color="transparent",
            fg_color=fg_color,
            command=None,
        )
        # TextButton overrides its own height in __init__ and derives x/y from
        # the (pre-override) 100x100 size, so recompute the grip's top-left from
        # the track centre and force the rect to the size we actually want.
        self._track_cy = self.y + 0.5 * self.height
        self.slider_button.x = round(self.x - 0.5 * self._handle_w)
        self.slider_button.y = round(self._track_cy - 0.5 * self._handle_h)
        self.slider_button.width = self._handle_w
        self.slider_button.height = self._handle_h
        self.slider_button.rect.update(
            self.slider_button.x, self.slider_button.y,
            self._handle_w, self._handle_h,
        )
        self.value_label = Label(
            parent=self,
            center=(round(self.x + 0.5 * width), self.y),
            fg_color=(255, 255, 255),
        )
        # place the handle at the default value's position
        span = self.end - self.start
        frac = 0.0 if span == 0 else (default - self.start) / span
        self.slider_button.x = round(
            self.x + frac * self.width - 0.5 * self.slider_button.width
        )
        self.slider_button.rect.x = self.slider_button.x
        self.value_label.text = self._format_value()
        # True only while THIS slider is being dragged. A slider grabs the drag
        # on mouse-press over its own handle and keeps it until release, so
        # neighbouring sliders whose handles overlap the cursor never react.
        self._grabbed = False

    def _format_value(self) -> str:
        return f"{self.value:.{self.decimals}f}"

    def _set_from_cursor_x(self, cursor_x: float):
        half_btn_width = round(0.5 * self.slider_button.width)
        clamped = max(self.x, min(cursor_x, self.x + self.width))
        self.slider_button.x = round(clamped - half_btn_width)
        self.slider_button.rect.x = self.slider_button.x
        self.value = (
            self.start
            + float(clamped - self.x) / self.width * (self.end - self.start)
        )
        self.value_label.text = self._format_value()

    def move_slider(self):
        held = self.game.actions["mouse_sx"] == 1
        if not held:
            self._grabbed = False
            return
        # Claim the grab only on the press EDGE (clicked_sx == 1) over our handle.
        # Dragging a held cursor onto another handle can't grab it, because that
        # slider never saw the press begin on itself.
        if not self._grabbed:
            if (self.game.clicked_sx == 1
                    and self.slider_button.rect.collidepoint(self.game.cursorpos)):
                self._grabbed = True
            else:
                return
        self._set_from_cursor_x(self.game.cursorpos[0])

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
