from pygame import Surface

from UI.Abstract import UICanvas, UIContainer
from UI.Button import TextButton


class TabsFrame(UIContainer):
    def __init__(
        self,
        parent: UICanvas,
        x=0,
        y=0,
        center: tuple[int, int] = None,
        width=100,
        height=100,
        bg_color: tuple | str = (40, 40, 40),
        fg_color=(0, 0, 0),
        corner_radius=10,
        button_hover_color=(63, 200, 255, 20),
        tabs: dict[str, UIContainer] = None,
    ):
        super().__init__(
            parent, x, y, center, width, height, bg_color, fg_color, corner_radius
        )
        self.buttons = []
        self.tabs = tabs
        self.selected_tab = list(tabs.keys())[0]
        self.button_hover_color = button_hover_color
        self.load_ui()

    def load_ui(self):
        self.top_panel = UIContainer(
            parent=self,
            x=self.x,
            y=self.y,
            width=self.width,
            height=50,
            bg_color=self.bg_color,
            fg_color=self.fg_color,
        )
        num_tabs = len(self.tabs)
        for tab in self.tabs.values():
            tab.parent = self
        content_panel = UIContainer(
            parent=self,
            x=self.x,
            y=1.1 * self.y,
            width=self.width,
            height=0.9 * self.height,
            bg_color=self.bg_color,
            fg_color=self.fg_color,
        )
        for tab in self.tabs.values():
            tab.rescale(content_panel.rect)
        for i, tab_name in enumerate(self.tabs.keys()):
            button = TextButton(
                parent=self.top_panel,
                x=self.x + float(i * self.width) / num_tabs,
                y=self.y,
                bg_color="transparent",
                width=float(self.width) / num_tabs,
                height=self.top_panel.height,
                fg_color=self.fg_color,
                text=tab_name,
                hover_color=self.button_hover_color,
                command=self.goto_tab,
            )
            self.buttons.append(button)

    def goto_tab(self):
        for button in self.buttons:
            if button.rect.collidepoint(self.game.cursorpos):
                self.selected_tab = button.text
                button.original_bg_color = self.button_hover_color
            else:
                button.original_bg_color = self.bg_color

    def render(self, surface: Surface):
        super().render(surface)
        self.top_panel.render(surface)
        self.tabs[self.selected_tab].render(surface)

    def update(self, dt):
        self.top_panel.update(dt)
        for button in self.buttons:
            button.update(dt)
