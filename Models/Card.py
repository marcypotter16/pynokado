import os

import pygame as p

from Game import Game
from Utils.Text import draw_centered_text


# Per-faction accent used to tint the ink brush strokes (frame + enso).
# Palette: Steel Azure / Chocolate / Black Cherry.
# (Golden Glow #dec62b is reserved for a future strong-glow effect.)
FACTION_INK = {
    "tech":    (4, 67, 137),    # #044389 Steel Azure
    "monster": (100, 13, 20),   # #640d14 Black Cherry
    "ancient": (139, 71, 4),    # #8b4704 Chocolate
}
DEFAULT_INK = (18, 16, 14)


def _cover_scale(img: p.Surface, target_w: int, target_h: int) -> p.Surface:
    """Scale `img` to *fill* target (cover), then crop the overflow so the
    aspect ratio is preserved — no stretching."""
    iw, ih = img.get_size()
    scale = max(target_w / iw, target_h / ih)
    scaled = p.transform.smoothscale(img, (round(iw * scale), round(ih * scale)))
    sw, sh = scaled.get_size()
    crop = p.Rect((sw - target_w) // 2, (sh - target_h) // 2, target_w, target_h)
    return scaled.subsurface(crop).copy()


def _focal_crop(img: p.Surface, d: int, focus: tuple, zoom: float) -> p.Surface:
    """Cover-scale `img` to a d×d square, but zoomed by `zoom` and centred on the
    `focus` point (fx, fy in 0..1 of the source). Used to frame a card's face /
    focal detail for its round board icon instead of a plain centre crop."""
    iw, ih = img.get_size()
    scale = max(d / iw, d / ih) * max(1.0, zoom)
    sc = p.transform.smoothscale(img, (round(iw * scale), round(ih * scale)))
    sw, sh = sc.get_size()
    cx, cy = int(focus[0] * sw), int(focus[1] * sh)
    crop = p.Rect(cx - d // 2, cy - d // 2, d, d)
    crop.clamp_ip(p.Rect(0, 0, sw, sh))     # keep inside the scaled image
    return sc.subsurface(crop).copy()


def _tint_ink(img: p.Surface, color: tuple) -> p.Surface:
    """Recolour a black-on-transparent brush sprite to `color`, preserving its
    alpha (the brush texture)."""
    out = img.copy()
    # Black strokes + additive fill -> strokes become `color`; alpha untouched.
    out.fill(color, special_flags=p.BLEND_RGB_ADD)
    return out


def make_stone(game: Game, card_model: "CardModel", diameter: int,
               ring_file: str = "ink_circle.png") -> p.Surface:
    """Render a card as a round Go-style "stone": the card art fills a circle,
    framed by the hand-inked brush ring (`ring_file`, tinted to the faction).
    Used when a card is placed on the board. Pass a different `ring_file` for
    stronger-card variants. Cached by the caller if needed."""
    d = diameter
    ink = FACTION_INK.get(card_model.faction, DEFAULT_INK)
    surf = p.Surface((d, d), p.SRCALPHA)

    # Crop the ring to its ink bounding box FIRST: the source PNGs aren't
    # centred in their canvas, so scaling the raw canvas leaves the ring
    # off-centre (and the art disc misaligned). After cropping, the ink fills
    # the surface, so canvas-centre == ring-centre.
    ring_src = _load_ui(game, ring_file)
    ring_src = ring_src.subsurface(ring_src.get_bounding_rect(min_alpha=1))

    # The ring's inner opening (measured on the cropped ring) sets how big the
    # art disc is, so the art sits *inside* the ink, not under it.
    hole = _inner_hole(ring_src)
    art_frac = min(hole.width, hole.height) / min(ring_src.get_size())
    art_d = max(4, int(d * art_frac))

    # Light backing disc so the dark ink art pops against the paper.
    off = (d - art_d) // 2
    p.draw.circle(surf, (246, 243, 236), (d // 2, d // 2), art_d // 2)

    # Focal art crop (zoom to the card's face / focal detail), masked to a disc.
    art = _focal_crop(p.image.load(card_model.art_path).convert_alpha(),
                      art_d, card_model.icon_focus, card_model.icon_zoom)
    mask = p.Surface((art_d, art_d), p.SRCALPHA)
    p.draw.circle(mask, (255, 255, 255, 255), (art_d // 2, art_d // 2), art_d // 2)
    art.blit(mask, (0, 0), special_flags=p.BLEND_RGBA_MULT)
    surf.blit(art, (off, off))

    # Strong faction ring: a solid tinted circle under the brush ring makes the
    # faction read even when the icon is ambiguous.
    ring_col = tuple(min(255, c + 55) for c in ink)
    p.draw.circle(surf, ring_col, (d // 2, d // 2), art_d // 2 + 2,
                  width=max(3, d // 20))
    # Faction-tinted brush ring on top (now centred).
    ring = _tint_ink(p.transform.smoothscale(ring_src, (d, d)), ink)
    surf.blit(ring, (0, 0))
    return surf


# Brush frames (in the midjourney folder). The frame is chosen by card
# strength: plain box for ordinary cards, the ornate flourish for the strongest.
FRAME_BASIC = "frame_basic.png"      # ordinary cards
FRAME_STRONG = "frame_flourish.png"  # exceptionally strong cards
# strength >= this uses the ornate frame.
STRONG_THRESHOLD = 9


def frame_for_strength(strength: int) -> str:
    return FRAME_STRONG if strength >= STRONG_THRESHOLD else FRAME_BASIC


_IMG_CACHE: dict[str, p.Surface] = {}


def _load_ui(game: Game, name: str) -> p.Surface:
    if name not in _IMG_CACHE:
        path = os.path.join(game.assets_dir, "sprites", "ui", name)
        _IMG_CACHE[name] = p.image.load(path).convert_alpha()
    return _IMG_CACHE[name]


def _inner_hole(img: p.Surface, alpha_th: int = 40) -> p.Rect:
    """Measure the transparent opening in the middle of a frame sprite: from the
    centre, cast rays outward on many rows/cols and take the median distance to
    the first ink on each side. This is the window the art shows through -- the
    strokes and the flourish live *outside* it and are meant to overhang."""
    w, h = img.get_size()
    cx, cy = w // 2, h // 2

    def first_ink(x0, y0, dx, dy):
        x, y = x0, y0
        while 0 <= x < w and 0 <= y < h:
            if img.get_at((x, y)).a > alpha_th:
                return x if dx else y
            x += dx
            y += dy
        return None

    def median(vals):
        vals.sort()
        return vals[len(vals) // 2]

    lefts, rights, tops, bottoms = [], [], [], []
    for y in range(int(h * 0.35), int(h * 0.65)):
        l = first_ink(cx, y, -1, 0)
        r = first_ink(cx, y, 1, 0)
        if l is not None:
            lefts.append(l)
        if r is not None:
            rights.append(r)
    for x in range(int(w * 0.35), int(w * 0.65)):
        t = first_ink(x, cy, 0, -1)
        b = first_ink(x, cy, 0, 1)
        if t is not None:
            tops.append(t)
        if b is not None:
            bottoms.append(b)

    l, r, t, b = median(lefts), median(rights), median(tops), median(bottoms)
    return p.Rect(l, t, r - l, b - t)


def _load_frame(game: Game, filename: str) -> tuple[p.Surface, p.Rect]:
    """Return (frame_sprite, inner_hole_rect) for the given frame file. Cached
    per file; the hole rect is in the sprite's own pixel coordinates."""
    key = f"__frame__{filename}"
    if key not in _IMG_CACHE:
        path = os.path.join(game.assets_dir, "sprites", "midjourney-session", filename)
        raw = p.image.load(path).convert_alpha()
        _IMG_CACHE[key] = (raw, _inner_hole(raw))
    return _IMG_CACHE[key]


class CardModel:
    def __init__(
        self,
        art_path: str,
        strength: int,
        name: str = "",
        faction: str = "",
        icon_focus: tuple[float, float] = (0.5, 0.5),
        icon_zoom: float = 1.0,
    ):
        self.art_path = art_path
        self.strength = strength
        self.name = name
        self.faction = faction
        # For the round board stone: which part of the art to frame, and how
        # far to zoom in. (0.5, 0.5)/1.0 = centred, full (current behaviour);
        # e.g. (0.5, 0.3)/1.9 zooms to a face in the upper-middle.
        self.icon_focus = icon_focus
        self.icon_zoom = icon_zoom


class CardModelNotFoundError(SyntaxError):
    def __init_subclass__(cls):
        return super().__init_subclass__()


class Card:
    WIDTH, HEIGHT = 200, 300
    MARGIN = 8           # inset of the art from the card edge
    TITLE_H = 30         # space reserved for the name at the bottom
    GEM_R = 30           # enso radius (drawn diameter of the ink circle)
    # How far *inside* the card edge the frame's inner opening should sit. The
    # strokes then straddle the card border and the flourish overhangs outward.
    FRAME_INSET = 6
    # Shrinks/grows the whole frame (strokes AND flourish) about the card
    # centre. <1 makes the flourish overhang less, but also pulls the box
    # strokes off the card edge (they're locked in one ratio in the asset).
    # 1.0 = opening on the card edge, box hugging the art.
    FRAME_SCALE = 1.0
    # Drag follow tightness (0..1 per 1/60s frame). Higher = snappier / less
    # trailing lag; ~0.2 gives a soft, tween-like follow.
    DRAG_SMOOTH = 0.25
    # Hover "lift" feel.
    LIFT_SMOOTH = 0.22    # how fast the lift eases in/out
    LIFT_SCALE = 0.08     # extra scale at full lift (1.08x)
    LIFT_RISE = 20        # pixels the card rises toward the viewer at full lift

    def __init__(self,
                 game: Game,
                 card_model: CardModel = None,
                 topleft: p.Vector2 = p.Vector2(0, 0),
                 font_family: str = "korean_calligraphy",
                 frame_file: str = None,
                 ) -> None:
        self.game = game
        self.topleft = p.Vector2(topleft)
        if card_model is None:
            raise CardModelNotFoundError
        self.card_model = card_model
        self.font_family = font_family
        # Frame chosen by strength unless one is explicitly passed in.
        self.frame_file = frame_file or frame_for_strength(card_model.strength)

        # rect is the logical card (hit-testing / layout). frame_rect is the
        # padded surface actually blitted, sized to fit the frame's overhang
        # (computed in _build_face). center drives movement.
        self.rect = p.Rect(int(topleft.x), int(topleft.y), self.WIDTH, self.HEIGHT)
        self.center = p.Vector2(self.rect.center)

        # Drag state: while dragging we follow the cursor 1:1 using a fixed
        # grab offset (cursor -> card centre at pick-up), so the card doesn't
        # snap and doesn't drop when the cursor leaves the card bounds.
        self.dragging = False
        self.grab_offset = p.Vector2(0, 0)

        # Hover / lift state. `lift` eases 0..1; `glow_rect`/`glow_color` are
        # read by the shader pass. glow_rect is the on-screen (lifted) card box.
        self.hover = False
        self.lift = 0.0
        self.glow_rect = p.Rect(self.rect)
        self.glow_color = tuple(min(1.0, (c + 40) / 255.0) for c in
                                FACTION_INK.get(card_model.faction, DEFAULT_INK))

        self.ink = FACTION_INK.get(card_model.faction, DEFAULT_INK)
        self.raw_art = p.image.load(card_model.art_path).convert_alpha()

        # Pre-render the whole card face once, then just blit it each frame.
        # Also sets self.pad (surface padding) and self.frame_rect.
        self.surface = self._build_face()
        self._build_hover_surfaces()

    def _build_hover_surfaces(self):
        """Pre-build the soft drop shadow once (its shape never changes; we just
        fade its alpha). The lifted card face is smoothscaled per frame in
        render() so the scale animates gradually -- cheap enough for 8 cards."""
        self.shadow_surface = p.Surface((self.rect.w + 24, self.rect.h + 24),
                                        p.SRCALPHA)
        p.draw.rect(self.shadow_surface, (0, 0, 0, 90),
                    self.shadow_surface.get_rect(), border_radius=14)

    def set_font_family(self, family: str):
        """Swap the font used for the name + power number and rebuild the face."""
        if family != self.font_family:
            self.font_family = family
            self.surface = self._build_face()
            self._build_hover_surfaces()

    def _font(self, size: str) -> p.font.Font:
        return self.game.fonts[self.font_family][size]

    # ------------------------------------------------------------------ build
    def _build_face(self) -> p.Surface:
        w, h, m = self.WIDTH, self.HEIGHT, self.MARGIN

        # --- work out how the frame must be scaled/placed relative to the card.
        raw_frame, hole = _load_frame(self.game, self.frame_file)
        fw, fh = raw_frame.get_size()

        # We want the frame's inner opening to sit just inside the card edge, so
        # the strokes straddle the border. Target opening (in card-local coords).
        # FRAME_SCALE < 1 shrinks the whole frame: the opening is enlarged about
        # the card centre so the strokes + flourish scale down proportionally.
        inset = self.FRAME_INSET
        target = p.Rect(inset, inset, w - 2 * inset, h - 2 * inset)
        target = target.inflate(target.width * (1 / self.FRAME_SCALE - 1),
                                target.height * (1 / self.FRAME_SCALE - 1))

        # Independent x/y scale mapping the source hole onto the target opening.
        sx = target.width / hole.width
        sy = target.height / hole.height
        scaled_fw, scaled_fh = round(fw * sx), round(fh * sy)

        # Where the scaled frame's opening lands inside the scaled frame:
        hole_x = hole.x * sx
        hole_y = hole.y * sy

        # For the opening to align with `target` on the card, the frame's
        # top-left must go here (in card-local coords, may be negative):
        frame_x = target.x - hole_x
        frame_y = target.y - hole_y

        # Padding = how far the frame overhangs each side of the card body.
        pad_l = max(0, -frame_x)
        pad_t = max(0, -frame_y)
        pad_r = max(0, (frame_x + scaled_fw) - w)
        pad_b = max(0, (frame_y + scaled_fh) - h)
        pad_l, pad_t = int(pad_l) + 1, int(pad_t) + 1
        pad_r, pad_b = int(pad_r) + 1, int(pad_b) + 1
        self.pad = (pad_l, pad_t)

        surf = p.Surface((w + pad_l + pad_r, h + pad_t + pad_b), p.SRCALPHA)
        ox, oy = pad_l, pad_t  # card body origin within the padded surface

        # frame_rect: padded surface positioned so the card body lands on rect.
        self.frame_rect = p.Rect(0, 0, surf.get_width(), surf.get_height())
        self.frame_rect.topleft = (self.rect.x - pad_l, self.rect.y - pad_t)

        # Ivory paper base (card body).
        p.draw.rect(surf, (238, 234, 226), (ox, oy, w, h), border_radius=6)

        # Art window: cover-fit, inset, leaving room for the name.
        aw = w - 2 * m
        ah = h - 2 * m - self.TITLE_H
        art = _cover_scale(self.raw_art, aw, ah)
        surf.blit(art, (ox + m, oy + m))

        # Brush frame, tinted, scaled so its opening frames the card.
        frame = _tint_ink(p.transform.smoothscale(raw_frame, (scaled_fw, scaled_fh)),
                          self.ink)
        surf.blit(frame, (ox + round(frame_x), oy + round(frame_y)))

        # Card name, ink-coloured, on the paper strip below the art.
        if self.card_model.name:
            name_rect = p.Rect(ox + m, oy + h - m - self.TITLE_H, aw, self.TITLE_H)
            draw_centered_text(self._font("small"), surf, self.card_model.name,
                               tuple(min(255, c + 6) for c in self.ink), name_rect)

        # Power enso (ink circle) with the strength number, top-left of the card.
        self._draw_power_enso(surf, ox + m + self.GEM_R, oy + m + self.GEM_R)

        return surf

    def _draw_power_enso(self, surf, cx, cy):
        d = self.GEM_R * 2
        # Small ivory disc so the number stays readable over busy art.
        p.draw.circle(surf, (240, 236, 228), (cx, cy), self.GEM_R - 6)
        enso = _tint_ink(_load_ui(self.game, "ink_circle.png"), self.ink)
        enso = p.transform.smoothscale(enso, (d, d))
        surf.blit(enso, (cx - self.GEM_R, cy - self.GEM_R))

        num = str(self.card_model.strength)
        text = self._font("medium").render(num, True, self.ink)
        surf.blit(text, text.get_rect(center=(cx, cy)))

    # ----------------------------------------------------------------- update
    def update(self, dt: float, allow_grab: bool = True):
        cursor = p.Vector2(self.game.cursorpos)

        # Pick up on the frame the left button goes down, if over the card.
        if allow_grab and self.game.clicked_sx == 1 and self.rect.collidepoint(cursor):
            self.dragging = True
            # Offset from cursor to card centre, so the grab point is preserved.
            # self.grab_offset = self.center - cursor

        # Drop as soon as the button is released.
        if not self.game.actions["mouse_sx"]:
            self.dragging = False

        # While dragging, ease toward the cursor each frame (exponential
        # smoothing) for a trailing, tween-like feel. We can't use a one-shot
        # tween here: the target (cursor) moves every frame, so recreating a
        # tween per frame just resets its progress and it never advances --
        # that's why it only "played" once dragging stopped. This lerp is
        # framerate-independent and never fights the tween manager.
        if self.dragging:
            target = cursor + self.grab_offset
            # SMOOTH ~ how snappy: bigger = tighter follow. dt keeps it stable.
            t = 1.0 - pow(1.0 - self.DRAG_SMOOTH, dt * 60.0)
            self.center = self.center.lerp(target, min(1.0, t))

        # Hover: cursor over the (non-dragged) card, or actively dragged.
        self.hover = self.dragging or self.rect.collidepoint(cursor)
        # Ease the lift amount 0..1 toward the hover target each frame.
        goal = 1.0 if self.hover else 0.0
        t = 1.0 - pow(1.0 - self.LIFT_SMOOTH, dt * 60.0)
        self.lift += (goal - self.lift) * min(1.0, t)

        self.rect.center = (round(self.center.x), round(self.center.y))
        # frame_rect keeps the card body aligned; padding is asymmetric so we
        # offset by self.pad rather than centring.
        self.frame_rect.topleft = (self.rect.x - self.pad[0],
                                   self.rect.y - self.pad[1])

    def render(self, surf: p.Surface):
        lift = self.lift
        if lift <= 0.001:
            # Resting: plain blit, glow rect matches the card.
            surf.blit(self.surface, self.frame_rect)
            self.glow_rect = p.Rect(self.rect)
            return

        rise = int(self.LIFT_RISE * lift)
        scale = 1.0 + self.LIFT_SCALE * lift
        cx, cy = self.frame_rect.centerx, self.frame_rect.centery - rise

        # Soft drop shadow (pre-built; only fade its alpha -- no redraw).
        self.shadow_surface.set_alpha(int(255 * lift))
        surf.blit(self.shadow_surface, self.shadow_surface.get_rect(
            center=(self.rect.centerx, self.rect.centery - rise + 14)))

        # Smoothscale the card face per frame so the scale animates gradually
        # (fine for 8 cards; profiled ~1ms/card).
        sw = int(self.surface.get_width() * scale)
        sh = int(self.surface.get_height() * scale)
        scaled = p.transform.smoothscale(self.surface, (sw, sh))
        surf.blit(scaled, scaled.get_rect(center=(cx, cy)))

        # Glow rect = the on-screen lifted *card* box so the halo hugs the edge.
        self.glow_rect = p.Rect(0, 0, int(self.rect.w * scale),
                                int(self.rect.h * scale))
        self.glow_rect.center = (self.rect.centerx, self.rect.centery - rise)
