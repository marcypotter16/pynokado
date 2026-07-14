import os
import random

import pygame as p

from AllCards import ALL_CARDS
from Models.Card import Card, make_stone, _tint_ink
from States.State import State
from Utils.Text import draw_centered_text


class BoardTestState(State):
    """
    A Go-inspired board test. A 10x10 grid of brush-stroke line intersections
    sits on the paper background; cards are dealt into a hand at the bottom.
    Drag a card near an intersection and release to place it: the card snaps
    (tweens) to the nearest empty point and becomes a round "stone" showing its
    art. Drop it anywhere invalid and it tweens back to its hand slot.
    """

    GRID = 10                # 10x10 intersections
    CELL = 72                # pixels between adjacent intersections
    STONE_D = 76             # placed-stone diameter
    SNAP_DIST = 52           # how close to a point a drop must be to place

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
            card.stone = make_stone(game, model, self.STONE_D)  # cached round form
            self.hand.append(card)

        # While dragging over the board, this holds (row, col, point) of the
        # intersection the card would snap to -- or None. `dragged` is the card
        # currently being dragged (or None).
        self.preview = None
        self.dragged = None

        self.hud_font = game.fonts["comfortaa"]["small"]
        self.title_font = game.fonts["sigokae"]["big"]
        self.ink = (30, 26, 22)

        # Bake the brush-stroke board onto a surface once (it never changes),
        # so we don't re-blit ~40 rotated/scaled strokes every frame.
        self.board_surface = self._build_board_surface()

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
        self.stones[(r, c)] = {"surf": card.stone, "pos": point,
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

        # Placement preview: nearest free intersection to the dragged card.
        self.preview = None
        self.dragged = next((c for c in self.hand if c.dragging), None)
        if self.dragged is not None:
            self.preview = self._nearest_free_point(p.Vector2(self.dragged.center))

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

        surface.blit(self.board_surface, (0, 0))

        # Placed stones.
        for stone in self.stones.values():
            rect = stone["surf"].get_rect(center=stone["pos"])
            surface.blit(stone["surf"], rect)

        # Ghost preview stone on the target intersection.
        if self.dragged is not None and self.preview is not None:
            _, _, point = self.preview
            ghost = self.dragged.stone.copy()
            ghost.set_alpha(120)
            surface.blit(ghost, ghost.get_rect(center=point))

        # Non-dragged hand cards. The dragged one is drawn LATER in
        # render_foreground(), so it sits above its own glow pass.
        for card in self.hand:
            if card is not self.dragged:
                card.render(surface)

        hud = "Drag a card onto an intersection to place it."
        hud_rect = p.Rect(0, self.game.GAME_H - 44, self.game.GAME_W, 32)
        draw_centered_text(self.hud_font, surface, hud, self.ink, hud_rect)

    def render_foreground(self, surface):
        """Drawn OVER the glow pass. The dragged card/stone lives here so the
        glow sits behind it instead of covering it."""
        card = self.dragged
        if card is None:
            return
        if self.preview is not None:
            # Over a valid point: show it as the round stone it will place.
            center = (round(card.center.x), round(card.center.y))
            surface.blit(card.stone, card.stone.get_rect(center=center))
        else:
            card.render(surface)

    # Sliced brush strokes, widest -> thinnest (measured from lines.png).
    BORDER_STROKES = ["board_line_0.png", "board_line_2.png"]   # bigger
    INNER_STROKES = ["board_line_1.png", "board_line_3.png",
                     "board_line_4.png", "board_line_5.png"]    # thinner

    def _build_board_surface(self) -> p.Surface:
        """Bake the 10x10 board from tinted brush strokes onto one surface.
        Each grid line is a scaled (and rotated for horizontals) stroke sprite
        with small seeded jitter, so the board looks hand-painted but is stable
        frame-to-frame. Border lines use the bigger strokes."""
        surf = p.Surface((self.game.GAME_W, self.game.GAME_H), p.SRCALPHA)
        span = (self.GRID - 1) * self.CELL
        o = self.board_origin
        rng = random.Random(1337)   # fixed seed -> stable board

        ui = os.path.join(self.game.assets_dir, "sprites", "ui", "board_lines")

        def tinted(name):
            img = p.image.load(os.path.join(ui, name)).convert_alpha()
            return _tint_ink(img, self.ink)

        border = [tinted(n) for n in self.BORDER_STROKES]
        inner = [tinted(n) for n in self.INNER_STROKES]

        def stroke_for(is_border):
            return rng.choice(border if is_border else inner)

        def blit_line(fixed, lo, hi, is_border, horizontal):
            """Draw one grid line. `fixed` is the constant coordinate (x for a
            vertical line, y for a horizontal one); the line runs from `lo` to
            `hi` along the other axis."""
            src = stroke_for(is_border)
            length = hi - lo
            grow = rng.randint(6, 20)          # slight overshoot past endpoints
            stroke = p.transform.smoothscale(src, (src.get_width(), length + grow))
            if rng.random() < 0.5:             # organic: flip half of them
                stroke = p.transform.flip(stroke, True, False)
            if horizontal:
                stroke = p.transform.rotate(stroke, 90)
            jitter = rng.randint(-2, 2)        # perpendicular nudge
            mid = lo + length / 2
            center = (mid, fixed + jitter) if horizontal else (fixed + jitter, mid)
            surf.blit(stroke, stroke.get_rect(center=center))

        # Vertical lines (columns): fixed x, running down y.
        for c in range(self.GRID):
            x = o.x + c * self.CELL
            blit_line(x, o.y, o.y + span, c in (0, self.GRID - 1), horizontal=False)
        # Horizontal lines (rows): fixed y, running across x.
        for r in range(self.GRID):
            y = o.y + r * self.CELL
            blit_line(y, o.x, o.x + span, r in (0, self.GRID - 1), horizontal=True)

        # Small ink dots at intersections for definition.
        for row in self.points:
            for pt in row:
                p.draw.circle(surf, self.ink, (int(pt.x), int(pt.y)), 3)

        return surf

    # -------------------------------------------------------- hover glow pass
    def _render_hover_glow(self):
        glows = []
        for c in self.hand:
            if c.lift <= 0.01:
                continue
            if c is self.dragged and self.preview is not None:
                # Over the board: the card is shown as a round stone at the
                # cursor, so glow a CIRCLE around the stone instead of the card
                # rectangle (which otherwise lingers where the card was).
                # corner = radius -> circle; fill=1 lights the whole disc and
                # bleeds out over `falloff` px past the ring (backlit stone).
                cx, cy = round(c.center.x), round(c.center.y)
                d = self.STONE_D
                rect = (cx - d // 2, cy - d // 2, d, d)
                glows.append((rect, c.glow_color, c.lift, d / 2, d * 0.22, 1.0))
            else:
                g = c.glow_rect
                glows.append(((g.x, g.y, g.w, g.h), c.glow_color, c.lift))
        self.game.gl_renderer.render_glows(glows, time_s=self.game.elapsed)
