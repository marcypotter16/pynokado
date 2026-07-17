import os

import pygame as p

from AllCards import ALL_CARDS
from Models.Card import Card
from States.State import State
from Utils.Text import draw_centered_text


class CardShowcaseState(State):
    """
    Lays out every card in ALL_CARDS in a grid. Press F (or 1-4) to cycle the
    font family used for card names + power numbers, to compare them live.
    """

    CARD_W, CARD_H = 200, 300

    # (font_family_key, label). The keys must exist in game.fonts.
    # Index 0 is the default. F cycles forward, B backward.
    FONT_OPTIONS = [
        # Best for small card text - stays legible at the name size.
        ("korean_calligraphy", "Korean Calligraphy"),
        ("ghibli", "Ghibli"),
        # Heavy brush faces - illegible small, but great for titles / big text.
        ("kashima", "Kashima (brush, title)"),
        ("mgs4_brush", "MGS4 Brush (title)"),
        ("sigokae", "Sigokae (brush, title)"),
        ("harukaze", "Harukaze (title)"),
        # handwritten / script
        ("biro_script", "Biro Script"),
        ("handmade", "Handmade"),
        ("hogback", "Hogback"),
        ("sandwich", "Sandwich"),
        # themed - e.g. a true in-game shop
        ("chinese_watch_shop", "Chinese Watch Shop (shop)"),
        # earlier candidates
        ("inconsolata", "Inconsolata"),
        ("october_crow", "October Crow (creepy)"),
        ("comfortaa", "Comfortaa"),
    ]

    def __init__(self, game, msg=None, layer="foreground"):
        super().__init__(game, msg, layer, bg_color=(235, 232, 224))

        self.font_index = 0
        self.frame_style = "sprite"   # toggled with G ("sprite" <-> "lines")

        # GPU hover-glow pass (drawn after the main canvas is on screen).
        game.post_render_callbacks.append(self._render_hover_glow)

        # --- lay the cards out on two rows, centred horizontally ---
        cards = list(ALL_CARDS.values())
        per_row = 4
        gap_x, gap_y = 40, 60
        row_w = per_row * self.CARD_W + (per_row - 1) * gap_x
        start_x = (game.GAME_W - row_w) // 2
        start_y = 200

        family = self.FONT_OPTIONS[self.font_index][0]
        self.cards: list[Card] = []
        for i, model in enumerate(cards):
            col = i % per_row
            row = i // per_row
            x = start_x + col * (self.CARD_W + gap_x)
            y = start_y + row * (self.CARD_H + gap_y)
            self.cards.append(
                Card(game, card_model=model, topleft=p.Vector2(x, y),
                     font_family=family)
            )

        # --- paper texture background, scaled to fill the screen once ---
        paper_path = os.path.join(
            game.assets_dir, "sprites", "midjourney-session", "paper-texture.jpg"
        )
        self.paper = p.transform.smoothscale(
            p.image.load(paper_path).convert(), (game.GAME_W, game.GAME_H)
        )

        # --- ink-brush header ---
        ui_dir = os.path.join(game.assets_dir, "sprites", "ui")
        self.ink_rectangle = p.image.load(
            os.path.join(ui_dir, "ink_rectangle.png")
        ).convert_alpha()
        self.header = p.transform.smoothscale(self.ink_rectangle, (760, 120))
        self.header_rect = self.header.get_rect(midtop=(game.GAME_W // 2, 20))

        self.title_font = game.fonts["harukaze"]["big"]
        self.hud_font = game.fonts["comfortaa"]["small"]

    # ------------------------------------------------------------------ input
    def _set_font(self, index):
        index %= len(self.FONT_OPTIONS)
        if index == self.font_index:
            return
        self.font_index = index
        family = self.FONT_OPTIONS[index][0]
        for card in self.cards:
            card.set_font_family(family)

    def _toggle_frame_style(self):
        self.frame_style = "lines" if self.frame_style == "sprite" else "sprite"
        for card in self.cards:
            card.set_frame_style(self.frame_style)

    def _handle_font_keys(self):
        for event in self.game.events:
            if event.type == p.KEYDOWN:
                if event.key == p.K_f:
                    self._set_font(self.font_index + 1)   # F: next font
                elif event.key == p.K_b:
                    self._set_font(self.font_index - 1)   # B: previous font
                elif event.key == p.K_g:
                    self._toggle_frame_style()            # G: toggle frame style

    def update(self, delta_time):
        super().update(delta_time)
        self._handle_font_keys()

        # Only one card may pick up per click. If a fresh click would land on
        # several overlapping cards, let the top-most (last drawn) grab it and
        # suppress the click for the rest.
        allow_grab = self.game.clicked_sx == 1
        for card in reversed(self.cards):
            card.update(delta_time, allow_grab=allow_grab)
            if allow_grab and card.dragging:
                allow_grab = False  # consumed by this card

        # Keep a dragged card on top of the render order.
        for card in self.cards:
            if card.dragging and card is not self.cards[-1]:
                self.cards.remove(card)
                self.cards.append(card)
                break

    def _render_hover_glow(self):
        """Post-render GPU pass: ONE draw for all lifted cards. Each card's glow
        fades with its own lift, so sliding between cards cross-fades (no
        teleport / pop). Glowing all lifted cards in a single array-fed pass
        also avoids a draw call per card."""
        glows = [
            ((c.glow_rect.x, c.glow_rect.y, c.glow_rect.w, c.glow_rect.h),
             c.glow_color, c.lift)
            for c in self.cards if c.lift > 0.01
        ]
        self.game.gl_renderer.render_glows(glows, time_s=self.game.elapsed)

    def render(self, surface):
        super().render(surface)

        # Paper texture behind everything (over the bg fill / canvas).
        surface.blit(self.paper, (0, 0))

        surface.blit(self.header, self.header_rect)
        draw_centered_text(
            self.title_font, surface, "CARD SHOWCASE", (20, 18, 16), self.header_rect, _offset=p.Vector2(0,18)
        )

        for card in self.cards:
            card.render(surface)

        # Font switch HUD along the bottom.
        label = self.FONT_OPTIONS[self.font_index][1]
        n = len(self.FONT_OPTIONS)
        hud = f"Font [F next / B prev]  {self.font_index + 1}/{n}:  {label}"
        hud_rect = p.Rect(0, self.game.GAME_H - 44, self.game.GAME_W, 32)
        draw_centered_text(self.hud_font, surface, hud, (30, 26, 22), hud_rect)
