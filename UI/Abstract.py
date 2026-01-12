import pygame

from Game import Game
from Utils import Draw


class UICanvas:
    def __init__(self, game: Game):
        self.game = game
        self.font: pygame.font.Font = game.fonts["comfortaa"]["medium"]
        self.y = None
        self.width = None
        self.x = None
        self.rect = None
        self.children: list[UIContainer] = []
        self.visible = True
        self.interactable = True

    def add_child(self, child):
        if child.parent is not None:
            child.parent.children.remove(child)
        self.children.append(child)
        child.parent = self

    def render(self, surface: pygame.Surface):
        if self.visible:
            for child in self.children:
                child.render(surface)

    def update(self, dt):
        if self.visible and self.interactable:
            for ui_element in self.children:
                ui_element.update(dt)

    def toggle_visibility(self):
        self.visible = not self.visible
        for child in self.children:
            child.visible = not child.visible

    def toggle_interactable(self):
        self.interactable = not self.interactable
        for child in self.children:
            child.interactable = not child.interactable


class UIContainer(UICanvas):
    def __init__(
        self,
        parent: UICanvas,
        x=0,
        y=0,
        center: tuple[int, int] = None,
        width=None,
        height=None,
        bg_color: tuple | str = (40, 40, 40),
        fg_color=(0, 0, 0),
        font: pygame.font.Font | None = None,
        corner_radius=10,
        border_width=0,
    ):
        """
        Container for GUI
        :param parent: the parent, usually a UICanvas
        :param x: x of the center of the container
        :param y: y of the center of the container
        :param center: tuple containing the center of the container. If this is not none, this will overwrite x and y
        :param width: width of the container
        :param height: height of the container
        :param bg_color: background colour
        :param fg_color: foreground colour (text)
        :param corner_radius: corner radius for smoothed rectangles
        """
        super().__init__(parent.game)
        self.font = font if font is not None else self.game.fonts["comfortaa"]["medium"]
        self.children: list[UIContainer] = []

        self.parent = parent

        self.parent.children.append(self)

        self.x = x
        self.y = y
        if center is not None:
            self.x, self.y = center[0] - width / 2, center[1] - height / 2
        self.width, self.height = width if width is not None else 1, (
            height if height is not None else 1
        )
        self.rect = pygame.rect.Rect(self.x, self.y, self.width, self.height)
        if bg_color == "transparent":
            self.original_bg_color = self.bg_color = (0, 0, 0, 0)
        else:
            self.original_bg_color = self.bg_color = bg_color
        self.fg_color = fg_color
        self.corner_radius = corner_radius
        self.border_width = border_width

    def rescale(self, rect: pygame.rect.Rect):
        px, py = self.x, self.y
        self.rect = rect
        horizontal_scaling_factor = float(rect.width) / self.width
        vertical_scaling_factor = float(rect.height) / self.height
        self.x, self.y, self.width, self.height = (
            rect.x,
            rect.y,
            rect.width,
            rect.height,
        )
        for child in self.children:
            child.x = self.x + round(horizontal_scaling_factor * (child.x - px))
            child.y = self.y + round(vertical_scaling_factor * (child.y - py))
            child.height = round(child.height * vertical_scaling_factor)
            child.width = round(child.width * horizontal_scaling_factor)
            child.rect.update(child.x, child.y, child.width, child.height)

    def render(self, surface: pygame.Surface):
        # super().render(surface)
        # surface.fill(self.original_bg_color, self.rect)
        if self.visible:
            # pygame.draw.rect(surface, self.bg_color, self.rect, border_radius=self.corner_radius)
            Draw.draw_rect_alpha(
                surface,
                color=self.bg_color,
                rect=self.rect,
                corner_radius=self.corner_radius,
                width=self.border_width,
            )
            for child in self.children:
                child.render(surface)

    def update(self, dt):
        if self.visible:
            for ui_element in self.children:
                ui_element.update(dt)

    def pack(
        self,
        side: str = "vert",
        padx: int = 0,
        pady: int = 0,
        modify_dimensions_to_fit=True,
    ):
        """
        Makes the children fit nicely inside the parent. Width or Height might get modified to fit in the frame.
        :param side: vert or horiz
        :param padx: horizontal padding
        :param pady: vertical padding
        :return: None
        """

        # self.parent.width = max([child.width for child in self.parent.children]) + 2 * padx

        # TODO: Rewrite this method, it's kinda garbage

        s = side.lower()
        if s == "vert":
            # Not very stonks
            self.height = sum(child.height + pady for child in self.children) + pady
            for i, c in enumerate(self.children):
                c.x = self.x + padx
                if modify_dimensions_to_fit:
                    c.width = self.width - 2 * padx
                if i > 0:
                    last_child = self.children[i - 1]
                    c.y = last_child.y + last_child.height + pady
                else:
                    c.y = self.y + pady
                c.rect.update(c.x, c.y, c.width, c.height)

        # TODO: rewrite
        elif s == "horiz":
            # Not very stonks
            self.parent.width = (
                sum(child.width + padx for child in self.parent.children) + padx
            )
            self.y = self.parent.y + pady
            if modify_dimensions_to_fit:
                self.height = self.parent.height - 2 * pady
            if len(self.parent.children) > 1:
                self.x = self.parent.children[0].x + padx + self.width
            else:
                self.x = self.parent.x + padx

        self.rect.update(self.x, self.y, self.width, self.height)

    def clear(self):
        self.children.clear()


class UIElement(UIContainer):
    def __init__(
        self,
        parent: UICanvas = None,
        x=0,
        y=0,
        center=None,
        width=None,
        height=None,
        bg_color: tuple | str = (40, 40, 40),
        fg_color=(0, 0, 0),
        font: pygame.font.Font | None = None,
        text: str = "",
        corner_radius=10,
    ):
        super().__init__(
            parent, x, y, center, width, height, bg_color, fg_color, font, corner_radius
        )

        self.clickable: bool = False
        self.text = text

        self.game = self.parent.game

    def render(self, surface: pygame.Surface):
        super().render(surface)

    def update(self, dt):
        if self.visible:
            super().update(dt)
            for ui_element in self.children:
                ui_element.update(dt)

    def __str__(self):
        return f"{self.x}, {self.y}, {self.width}, {self.height}\nChildren: {len(self.children)}"
