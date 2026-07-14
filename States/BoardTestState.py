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

        # Aged parchment background: the clean paper texture, warmed to a
        # sepia/tan, darkened at the edges (worn vignette) with a few stains.
        paper_path = os.path.join(
            game.assets_dir, "sprites", "midjourney-session", "paper-texture.jpg"
        )
        self.paper = self._age_parchment(
            p.transform.smoothscale(
                p.image.load(paper_path).convert(), (game.GAME_W, game.GAME_H))
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

    def _age_parchment(self, paper: p.Surface) -> p.Surface:
        """Warm the paper to a worn sepia parchment: a sepia tint plus a gentle
        worn vignette at the edges. (Ink blotches live on the board layer, not
        here.) Baked once.

        Note: BLEND_MULT ignores the alpha channel, so the darkening layers are
        built as *fully opaque* gradients (transparent-black would multiply the
        paper to black). Softness comes from the gradient values, not alpha."""
        w, h = paper.get_size()
        out = paper.copy()

        # Warm sepia tint (multiply toward a soft tan; kept light).
        tint = p.Surface((w, h)); tint.fill((226, 208, 176))
        out.blit(tint, (0, 0), special_flags=p.BLEND_MULT)

        # Gentle worn vignette. Opaque radial gradient, brightest centre
        # (255 = no change) fading to a mild edge darkening.
        vig = p.Surface((w, h)); vig.fill((205, 195, 178))   # edge darkness
        cx, cy = w // 2, h // 2
        maxr = int((w ** 2 + h ** 2) ** 0.5 / 2)
        for i in range(80):
            t = i / 79
            r = int(maxr * (1 - t))
            v = int(205 + (255 - 205) * (t ** 1.5))          # 205(edge)->255(centre)
            p.draw.circle(vig, (v, v, v), (cx, cy), r)
        out.blit(vig, (0, 0), special_flags=p.BLEND_MULT)
        return out

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

    # Sliced brush strokes, widest -> thinnest (from lines.png).
    BORDER_STROKES = ["board_line_0.png", "board_line_2.png"]   # bigger
    INNER_STROKES = ["board_line_1.png", "board_line_3.png",
                     "board_line_4.png", "board_line_5.png"]    # thinner
    # A single ink blob for the odd scattered splotch.
    SPLAT = "thick_line_3.png"

    def _build_board_surface(self) -> p.Surface:
        """Bake the 10x10 board from tinted brush strokes onto one surface. Each
        grid line is a scaled (rotated for horizontals) stroke with seeded
        jitter; border lines use the bigger strokes. A couple of solid black ink
        blotches are dropped nearby for character. Seeded -> stable."""
        surf = p.Surface((self.game.GAME_W, self.game.GAME_H), p.SRCALPHA)
        span = (self.GRID - 1) * self.CELL
        o = self.board_origin
        rng = random.Random(1337)   # fixed seed -> stable board
        ui = os.path.join(self.game.assets_dir, "sprites", "ui")

        def tinted(subdir, name):
            img = p.image.load(os.path.join(ui, subdir, name)).convert_alpha()
            return _tint_ink(img, self.ink)

        border = [tinted("board_lines", n) for n in self.BORDER_STROKES]
        inner = [tinted("board_lines", n) for n in self.INNER_STROKES]

        def blit_line(fixed, lo, hi, is_border, horizontal):
            src = rng.choice(border if is_border else inner)
            length = hi - lo
            grow = rng.randint(6, 20)
            stroke = p.transform.smoothscale(src, (src.get_width(), length + grow))
            if rng.random() < 0.5:
                stroke = p.transform.flip(stroke, True, False)
            if horizontal:
                stroke = p.transform.rotate(stroke, 90)
            jitter = rng.randint(-2, 2)
            mid = lo + length / 2
            center = (mid, fixed + jitter) if horizontal else (fixed + jitter, mid)
            surf.blit(stroke, stroke.get_rect(center=center))

        # Columns then rows; first/last are the border.
        for c in range(self.GRID):
            blit_line(o.x + c * self.CELL, o.y, o.y + span,
                      c in (0, self.GRID - 1), horizontal=False)
        for r in range(self.GRID):
            blit_line(o.y + r * self.CELL, o.x, o.x + span,
                      r in (0, self.GRID - 1), horizontal=True)

        # Small ink dots at intersections.
        for row in self.points:
            for pt in row:
                p.draw.circle(surf, self.ink, (int(pt.x), int(pt.y)), 3)

        # A couple of solid BLACK ink blotches near the board -- it's ink, so
        # they're near-opaque, not faint.
        splat = tinted("thick_lines", self.SPLAT)
        margin = 120
        for _ in range(3):
            d = rng.randint(20, 40)
            s = p.transform.rotate(p.transform.smoothscale(splat, (d, d)),
                                   rng.uniform(0, 360))
            s.set_alpha(rng.randint(210, 255))
            px = rng.randint(int(o.x - margin), int(o.x + span + margin))
            py = rng.randint(int(o.y - margin), int(o.y + span + margin))
            surf.blit(s, s.get_rect(center=(px, py)))

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
