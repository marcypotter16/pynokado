import os
import random

import pygame as p

from GameObject import GameObject
from Models.Board import Board
from Models.Card import FACTION_INK
from Models.Pawn import Pawn
from Models.Terrain import TerrainMode
from PawnRenderer import PawnRenderer
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


class MoveMarkers(GameObject):
    """Rings on the nodes the selected pawn can reach, and a lit road to each.

    A leaf drawn above the board rather than by the board, because whose turn it
    is and what is selected are campaign state -- Board owns the map, not the
    play on top of it."""

    RING = (196, 84, 44)
    ROAD = (206, 128, 82)

    def __init__(self, state: "BoardTestState"):
        super().__init__()
        self.state = state

    def render(self, surf: p.Surface):
        st = self.state
        if st.selected is None:
            return
        here = st._to_screen(st.selected.node)
        # Which node the piece would land on if released now. Showing it while
        # the piece is still in the air is what makes a drop feel aimed rather
        # than gambled -- without it the player only learns where it went after
        # letting go, which is the wrong order.
        cursor = p.Vector2(st.game.cursorpos)
        armed = min(
            ((cursor - p.Vector2(st._to_screen(rc))).length_squared(), rc)
            for rc in st.legal_moves
        ) if st.legal_moves else None
        armed_rc = armed[1] if armed and armed[0] <= st.DROP_R ** 2 else None

        for rc in st.legal_moves:
            there = st._to_screen(rc)
            hot = rc == armed_rc
            p.draw.line(surf, self.ROAD, here, there, 7 if hot else 5)
            p.draw.circle(surf, self.RING, there, 22 if hot else 16,
                          width=0 if hot else 4)
        # The origin last, so it reads as where the piece came from rather than
        # as another place it could go.
        p.draw.circle(surf, self.RING, here, 19, width=3)


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

        self.map_menu.add_child(
            TextButton(
                self.map_menu,
                text="topomap",
                command=lambda: self.board.change_terrain_mode(TerrainMode.TOPOMAP),
                bg_color=(190, 190, 190)
            ),
        )

        # --- campaign pieces (see docs/campaign-and-duel.md) ---
        # Click a pawn to pick it up, click a lit node to send it there. One
        # step at a time along the ROAD network -- not the substrate, which
        # holds every connection the terrain would allow and nobody built.
        self.pawn_renderer = PawnRenderer(game.glctx, (game.GAME_W, game.GAME_H))
        self.pawns: list[Pawn] = []
        self.selected: Pawn | None = None
        self.legal_moves: list[tuple[int, int]] = []

        rng = random.Random(4)
        on_road = sorted({rc for e in self.board.sites.roads
                          for rc in (e.start, e.end)})
        for rc, faction in zip(rng.sample(on_road, 3),
                               ("tech", "monster", "ancient")):
            # Lightened: FACTION_INK is chosen to read as ink ON parchment, so
            # used raw it makes a lit 3D surface look like a black blob.
            r, g, b = FACTION_INK[faction]
            self.pawns.append(Pawn(
                pos=self._to_screen(rc),
                node=rc,
                color=(min(255, r + 70), min(255, g + 70), min(255, b + 70)),
            ))
        self.markers = MoveMarkers(self)
        self.add_to_render_queue(self.markers, z_index=1)
        game.post_render_callbacks.append(self._render_pawns)

    def _to_screen(self, rc: tuple[int, int]) -> tuple[float, float]:
        """Data-space node -> screen pixels. `render_pos` is relative to the
        terrain's own rect, which is centred, so the origin has to be added."""
        ox, oy = self.board.terrain_rect.topleft
        x, y = self.board.sites.sites[rc].render_pos
        return (x + ox, y + oy)

    # How close the cursor has to be, in px, to grab a piece and to drop it on a
    # node. Generous on both: the pawn's base is ~26px across and a node dot is
    # 8, so requiring a hit on the drawn pixels would be a precision test.
    # DROP_R is the larger of the two -- releasing is a coarser gesture than
    # pressing, and a drop that misses costs the player the whole move.
    GRAB_R = 34
    DROP_R = 52

    def _handle_drag(self) -> None:
        """Pick a piece up, carry it, put it down -- the board-game gesture.

        Press, move, release rather than click-select-click: a physical piece is
        never 'selected', it is in your hand or on the board, and the legal
        moves are worth showing exactly while it is in the air."""
        cursor = p.Vector2(self.game.cursorpos)

        # clicked_sx is the EDGE (+1 press, -1 release); actions["mouse_sx"] is
        # the held state. Both are needed -- a drag is bounded by two edges and
        # everything in between.
        if self.game.clicked_sx == 1 and self.selected is None:
            for pawn in self.pawns:
                # A piece already walking cannot be grabbed: it is between nodes,
                # so it has no node to offer moves from.
                if pawn.moving:
                    continue
                if (cursor - p.Vector2(pawn.pos)).length_squared() <= self.GRAB_R ** 2:
                    self.selected = pawn
                    pawn.held = True
                    self.legal_moves = self.board.sites.road_neighbours(pawn.node)
                    break

        if self.selected is None:
            return

        if self.game.actions["mouse_sx"]:
            # Follows the cursor 1:1 rather than easing toward it. A card can
            # lag behind the hand and feel weighty; a game piece under your
            # finger cannot, and any smoothing reads as the board being slippery.
            self.selected.pos = (cursor.x, cursor.y)
            return

        # Released: put it down on a legal node, or back where it came from.
        drop = min(
            ((cursor - p.Vector2(self._to_screen(rc))).length_squared(), rc)
            for rc in self.legal_moves
        )[1] if self.legal_moves else None
        if drop is not None and (
            cursor - p.Vector2(self._to_screen(drop))
        ).length_squared() <= self.DROP_R ** 2:
            self.selected.place_at(drop, self._to_screen(drop))
        else:
            # Snap home. A piece dropped on nothing was never moved -- silently
            # leaving it mid-board would make `node` disagree with what is drawn.
            self.selected.place_at(self.selected.node,
                                   self._to_screen(self.selected.node))
        self.selected.held = False
        self.selected = None
        self.legal_moves = []

    def _render_pawns(self) -> None:
        self.pawn_renderer.render(self.pawns, self.game.gl_renderer.viewport)

    def exit_state(self):
        # post_render_callbacks is never cleared by Game, so a state that adds
        # to it has to take itself back out or it keeps drawing after it's gone.
        if self._render_pawns in self.game.post_render_callbacks:
            self.game.post_render_callbacks.remove(self._render_pawns)
        self.pawn_renderer.release()
        super().exit_state()

    def update(self, delta_time):
        super().update(delta_time)
        self.board.update(delta_time)
        self._handle_drag()
        for pawn in self.pawns:
            pawn.update(delta_time)

    def render(self, surface):
        super().render(surface)
