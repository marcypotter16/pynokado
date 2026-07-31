import os

import pygame as p

from GameObject import GameObject
from Models.Board import Board
from Models.Terrain import TerrainMode
from States.State import State
from UI.Button import ImageButton, TextButton
from UI.Containers import VertContainer
from UI.Grid import UIGrid
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
        ) # type: ignore
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

        self.map_menu = VertContainer(
            self.canvas,
            x=int(0.85 * self.game.GAME_W),
            y=int(0.8 * self.game.GAME_H),
            width=int(0.1 * self.game.GAME_W),
            height=200,
            bg_color=(200, 200, 200, 200),
            pad=(5, 5)
        )

        self.map_menu.add_child(
            TextButton(
                self.map_menu,
                text="glyphmap",
                command=lambda: self.board.change_terrain_mode(TerrainMode.GLYPHMAP),
                bg_color=(190, 190, 190)
            ),
        )

        self.map_menu.add_child(
            TextButton(
                self.map_menu,
                text="colmap",
                command=lambda: self.board.change_terrain_mode(TerrainMode.COLOURMAP),
                bg_color=(190, 190, 190)
            ),
        )

        self.map_menu.add_child(
            TextButton(
                self.map_menu,
                text="heightmap",
                command=lambda: self.board.change_terrain_mode(TerrainMode.HEIGHTMAP),
                bg_color=(190, 190, 190)
            ),
        )

    def update(self, delta_time):
        super().update(delta_time)
        self.board.update(delta_time)

    def render(self, surface):
        super().render(surface)
