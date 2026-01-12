from UI.Abstract import UIContainer, UICanvas, UIElement
from Utils.Text import draw_centered_text


# Abstract Container class
class VertContainer(UIContainer):
    """Vertical container"""

    def __init__(
        self,
        parent: UICanvas,
        x=0,
        y=0,
        center: tuple[int, int] = None,
        width=100,
        height=100,
        bg_color: tuple | str = "transparent",
        fg_color=(0, 0, 0),
        corner_radius=10,
        pad=(0, 0),
        font=None,
    ):
        super().__init__(
            parent, x, y, center, width, height, bg_color, fg_color, font, corner_radius
        )

        self.pad = pad
        self.modify_children_dimensions_to_fit = True

    def add_child(self, child: UIElement):
        super().add_child(child)
        # child.pack(
        #     side="vert",
        #     padx=self.pad[0],
        #     pady=self.pad[1],
        #     modify_dimensions_to_fit=self.modify_children_dimensions_to_fit,
        # )


class HorizContainer(UIContainer):
    """Horizontal container"""

    def __init__(
        self,
        parent: UICanvas,
        x=0,
        y=0,
        center: tuple[int, int] = None,
        width=100,
        height=100,
        bg_color: tuple | str = "transparent",
        fg_color=(0, 0, 0),
        corner_radius=10,
        pad=(0, 0),
        font=None,
    ):
        super().__init__(
            parent, x, y, center, width, height, bg_color, fg_color, font, corner_radius
        )

        self.pad = pad
        self.modify_children_dimensions_to_fit = True

    def add_child(self, child: UIElement):
        super().add_child(child)
        child.pack(
            side="horiz",
            padx=self.pad[0],
            pady=self.pad[1],
            modify_dimensions_to_fit=self.modify_children_dimensions_to_fit,
        )
