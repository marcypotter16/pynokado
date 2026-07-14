import os

import pygame as p

from AllCards import ALL_CARDS
from Models.Card import Card, make_stone
from States.State import State
from Utils.Text import draw_centered_text


class BoardTestState(State):
    """
    A Go-inspired board test. A 7x7 grid of line intersections sits on the paper
    background; cards are dealt into a hand at the bottom. Drag a card near an
    intersection and release to place it: the card snaps (tweens) to the nearest
    empty point and becomes a round "stone" showing its art. Drop it anywhere
    invalid and it tweens back to its hand slot.
    """

    GRID = 7                 # 7x7 intersections
    CELL = 96                # pixels between adjacent intersections
    STONE_D = 84             # placed-stone diameter
    SNAP_DIST = 70           # how close to a point a drop must be to place

    def __init__(self, game, msg=None, layer="foreground"):
        super().__init__(game, msg, layer, bg_color=(235, 232, 224))

        # Paper background.
        paper_path = os.path.join(
            game.assets_dir, "sprites", "midjourney-session", "paper-texture.jpg"
        )
        self.paper = p.transform.smoothscale(
            p.image.load(paper_path).convert(), (game.GAME_W, game.GAME_H)
        )

        # --- board geometry: intersection points, centred on screen ---
        span = (self.GRID - 1) * self.CELL
        self.board_origin = p.Vector2(
            (game.GAME_W - span) // 2, (game.GAME_H - span) // 2 - 120
        )
        self.points: list[list[p.Vector2]] = [
            [self.board_origin + p.Vector2(c * self.CELL, r * self.CELL)
             for c in range(self.GRID)]
            for r in range(self.GRID)
        ]
        # occupancy: (row, col) -> placed stone dict, or absent if empty.
        self.stones: dict[tuple[int, int], dict] = {}

        # --- deal a hand along the bottom ---
        models = list(ALL_CARDS.values())
        self.hand: list[Card] = []
        hand_gap = 220
        hand_w = (len(models) - 1) * hand_gap
        hand_x0 = (game.GAME_W - hand_w) // 2
        hand_y = game.GAME_H - 200
        for i, model in enumerate(models):
            card = Card(game, card_model=model,
                        topleft=p.Vector2(hand_x0 + i * hand_gap - Card.WIDTH // 2,
                                          hand_y - Card.HEIGHT // 2))
            card.home = p.Vector2(card.center)   # where it returns to on invalid drop
            self.hand.append(card)

        self.hud_font = game.fonts["comfortaa"]["small"]
        self.title_font = game.fonts["sigokae"]["big"]
        self.ink = (30, 26, 22)

        # GPU hover-glow pass for hand cards.
        game.post_render_callbacks.append(self._render_hover_glow)

    # ------------------------------------------------------------- placement
    def _nearest_free_point(self, pos: p.Vector2):
        """Return (row, col, point) of the closest empty intersection within
        SNAP_DIST of `pos`, or None."""
        best = None
        best_d = self.SNAP_DIST
        for r in range(self.GRID):
            for c in range(self.GRID):
                if (r, c) in self.stones:
                    continue
                d = pos.distance_to(self.points[r][c])
                if d < best_d:
                    best_d = d
                    best = (r, c, self.points[r][c])
        return best

    def _place(self, card: Card, r: int, c: int, point: p.Vector2):
        """Turn a dragged hand card into a placed stone at (r, c)."""
        stone_surf = make_stone(card.card_model, self.STONE_D)
        self.stones[(r, c)] = {"surf": stone_surf, "pos": point,
                               "model": card.card_model}
        self.hand.remove(card)

    # ------------------------------------------------------------------ loop
    def update(self, delta_time):
        super().update(delta_time)

        # Track which card (if any) was dragging before this update, so we can
        # detect the release and resolve the drop.
        was_dragging = [c for c in self.hand if c.dragging]

        allow_grab = self.game.clicked_sx == 1
        for card in reversed(self.hand):
            card.update(delta_time, allow_grab=allow_grab)
            if allow_grab and card.dragging:
                allow_grab = False

        # Keep a dragged card rendered on top.
        for card in self.hand:
            if card.dragging and card is not self.hand[-1]:
                self.hand.remove(card)
                self.hand.append(card)
                break

        # Resolve drops: a card that WAS dragging but no longer is.
        for card in was_dragging:
            if not card.dragging:
                spot = self._nearest_free_point(p.Vector2(card.center))
                if spot is not None:
                    self._place(card, *spot)
                else:
                    # Snap back home.
                    self.game.tweener_manager.add_tween(
                        card, "center", p.Vector2(card.center),
                        p.Vector2(card.home), 0.25)

    def render(self, surface):
        super().render(surface)
        surface.blit(self.paper, (0, 0))

        self._draw_board(surface)

        # Placed stones.
        for stone in self.stones.values():
            rect = stone["surf"].get_rect(center=stone["pos"])
            surface.blit(stone["surf"], rect)

        # Hand cards (dragged one is last -> drawn on top).
        for card in self.hand:
            card.render(surface)

        hud = "Drag a card onto an intersection to place it."
        hud_rect = p.Rect(0, self.game.GAME_H - 44, self.game.GAME_W, 32)
        draw_centered_text(self.hud_font, surface, hud, self.ink, hud_rect)

    def _draw_board(self, surface):
        span = (self.GRID - 1) * self.CELL
        o = self.board_origin
        # Grid lines.
        for i in range(self.GRID):
            # horizontal
            p.draw.line(surface, self.ink,
                        (o.x, o.y + i * self.CELL),
                        (o.x + span, o.y + i * self.CELL), 2)
            # vertical
            p.draw.line(surface, self.ink,
                        (o.x + i * self.CELL, o.y),
                        (o.x + i * self.CELL, o.y + span), 2)
        # Intersection dots.
        for row in self.points:
            for pt in row:
                p.draw.circle(surface, self.ink, (int(pt.x), int(pt.y)), 4)

    # -------------------------------------------------------- hover glow pass
    def _render_hover_glow(self):
        glows = [
            ((c.glow_rect.x, c.glow_rect.y, c.glow_rect.w, c.glow_rect.h),
             c.glow_color, c.lift)
            for c in self.hand if c.lift > 0.01
        ]
        self.game.gl_renderer.render_glows(glows, time_s=self.game.elapsed)
