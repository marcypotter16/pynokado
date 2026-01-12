import os

import pygame

from UI.Button import TextButton
from UI.Abstract import UIElement, UIContainer, UICanvas
from Utils.Text import draw_centered_text


class Menu(UIElement):
    def __init__(
        self,
        parent: UICanvas = None,
        x=0,
        y=0,
        center=None,
        width=100,
        height=100,
        bg_color: tuple | str = (40, 40, 40),
        default: str = None,
        fg_color=(0, 0, 0),
        text: str = "",
        corner_radius=10,
        options: list[str] = [""],
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
            None,
            text,
            corner_radius,
        )
        self.options = options
        self.options_container = UIContainer(
            parent=self,
            x=x,
            y=y + height,
            width=width,
            height=height * len(options),
            corner_radius=10,
        )
        self.options_container.visible = False

        self.buttons: list[TextButton] = []
        if default is None:
            self.selected_option: str = options[0]
        else:
            self.selected_option: str = default
        for option in options:
            button = TextButton(
                parent=self.options_container,
                height=height,
                bg_color=bg_color,
                fg_color=fg_color,
                text=option,
                command=self.option_selected_event_handler,
            )
            button.visible = False
            self.buttons.append(button)

        # Pack the buttons inside the options_container
        self.options_container.pack(side="vert", padx=10, pady=10)
        self.open = False

        self.ui_sprites_dir: str = None
        self.open_menu_sprite: pygame.image = None
        self.close_menu_sprite: pygame.image = None
        self.menu_sprite_rect: pygame.Rect = None
        self.load_sprites()

    def option_selected_event_handler(self):
        for button in self.buttons:
            if button.rect.collidepoint(self.game.cursorpos):
                self.selected_option = button.text
                self.close_menu()

    def render(self, surface: pygame.Surface):
        if self.visible:
            super().render(surface)
            pygame.draw.rect(surface, self.bg_color, self.rect, border_radius=10)
            draw_centered_text(
                self.font, surface, self.selected_option, self.fg_color, self.rect
            )

            if self.open:
                surface.blit(self.close_menu_sprite, self.menu_sprite_rect)
                self.options_container.render(surface)
            else:
                surface.blit(self.open_menu_sprite, self.menu_sprite_rect)

    def update(self, dt):
        for child in self.children:
            child.update(dt)
        # al momento del rilascio del bottone del mouse
        if self.game.clicked_sx == -1:
            if self.rect.collidepoint(self.game.cursorpos):
                if self.open:
                    self.close_menu()
                else:
                    self.open_menu()

    def open_menu(self):
        self.open = True
        self.options_container.visible = True
        for button in self.buttons:
            button.visible = True

    def close_menu(self):
        self.open = False
        self.options_container.visible = False
        for button in self.buttons:
            button.visible = False

    def load_sprites(self):
        self.ui_sprites_dir = os.path.join(self.game.base_dir, "Assets/sprites/ui")
        self.open_menu_sprite = pygame.image.load(
            os.path.join(self.ui_sprites_dir, "Open Menu.png")
        ).convert_alpha()
        oms = self.open_menu_sprite.copy()
        # cms = self.close_menu_sprite.copy()
        padx = 5
        pady = 5
        self.menu_sprite_rect = pygame.rect.Rect(
            self.x + self.width - self.height + padx,
            self.y + pady,
            self.height - 2 * padx,
            self.height - 2 * pady,
        )
        self.close_menu_sprite = pygame.transform.scale(
            pygame.transform.flip(oms, flip_x=False, flip_y=True),
            self.menu_sprite_rect.size,
        )
        self.open_menu_sprite = pygame.transform.scale(oms, self.menu_sprite_rect.size)
