import os

import pygame as p

from GameObject import GameObject
from Models.Board import Board
from States.State import State
from UI.Button import ImageButton
from Utils.Image import age_parchment


class PaperBackground(GameObject):
    """Static full-screen parchment. A leaf: it just blits its baked surface,
    and the render queue's z_index is what puts it under the board."""

    def __init__(self, paper: p.Surface):
        super().__init__()
        self.paper = paper

    def render(self, surf: p.Surface):
        surf.blit(self.paper, (0, 0))


class BoardTestState(State):
    def __init__(self, game, data = None, layer="foreground", bg_color=..., previous_state=None):
        super().__init__(game, data, layer, bg_color=(235, 232, 224), previous_state=None)

        paper_path = os.path.join(
            game.assets_dir, "sprites", "midjourney-session", "paper-texture.jpg"
        )
        # Baked once: the tint/vignette pass is far too slow to run per frame.
        self.paper = PaperBackground(age_parchment(
            p.transform.smoothscale(
                p.image.load(paper_path).convert(), (game.GAME_W, game.GAME_H)
            )
        ))
        self.add_to_render_queue(self.paper, z_index=-10)

        self.board = Board(game)
        self.add_to_render_queue(self.board, z_index=0)

        brush_icon = p.image.load(
            os.path.join("Assets", "sprites", "ui", "icons8-calligraphy-brush-100.png")
        )
        # Parented to the State's canvas, which updates and renders it above the board.
        self.brush_button = ImageButton(
            self.canvas,
            x=20,
            y=20,
            width=64,
            height=64,
            corner_radius=8,
            command=self.board.toggle_brush_mode,
            hover_animation=[brush_icon],
        )

    def update(self, delta_time):
        super().update(delta_time)
        self.board.update(delta_time)

    def render(self, surface):
        super().render(surface)
