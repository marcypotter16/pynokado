"""Weather over a map: density-field clouds, drifting fog, and the snow that
falls out of them.

Lifted out of States/SnowTestState.py so the real map can use it too, and kept
out of Models/Terrain.py, which is quite large enough. Terrain bakes STATIC ink
-- glyphs, contours, farmland, haze -- once per render size. Everything here is
LIVE: it has a clock, it moves, and it is composited over the terrain each
frame rather than into it.

CLOUDS
    The Sebastian Lague density-field recipe reduced to two dimensions. Three
    ideas survive the reduction and they're the three that matter:

    - Density is fBm noise, not a painted shape (`CloudField._bake`).
    - Coverage is a REMAP, not a threshold: `(d - coverage) / (1 - coverage)`
      clipped at zero. Cutting the noise off at a level gives hard-edged blobs;
      rescaling what survives keeps a soft falloff, so a cloud thins out at its
      edge the way it should. This is what turns noise into distinct puffs
      rather than uniform fog.
    - Light is absorbed on its way through: transmittance is `exp(-k * D)`
      where D is the density accumulated ABOVE a point (Beer's law). In 3D
      that's a march toward the sun; here the sun is overhead and the march
      collapses into one cumulative sum down each column, which numpy does in
      a single pass. It is the entire reason the clouds read as lit volumes --
      bright tops, heavy shadowed undersides -- rather than as grey smudges.

    What does NOT survive is the raymarch: there's no volume to march through
    on a flat page, and no view ray to march along.

    Animation is two layers of the same baked field scrolling at different
    speeds and fractionally interpolated between cells, so clouds drift AND
    evolve without re-baking noise per frame (which would be thousands of
    Python-level pnoise2 calls a frame, and hopeless).

WHERE THE WEATHER IS
    A CloudField is placed by an AREA OF INTEREST, not by a rectangle someone
    measured out by hand. It takes a data-space mask (e.g. SNOW | MOUNTAIN), an
    `out_size` in render pixels -- the same data-to-render convention Terrain
    uses throughout -- and a `cloud_height`, then works out its own screen
    position by scaling the AOI up and lifting it by that height. The weather
    ends up shaped like the ground it belongs to, and above it.

    Fog is then the same object with `cloud_height = 0`: cloud lying ON the
    terrain instead of over it. That is the entire difference between the two,
    which is why they share a class rather than merely resembling each other.

SNOW
    Snow does not fall from the whole cloud. A handful of SOURCES -- points, or
    horizontal stripes -- are picked inside it, weighted by density so they land
    where there is actually cloud, and placed at its underside. They are
    re-picked every few seconds, so squalls start, drift and stop instead of the
    whole range sitting under uniform snowfall forever.

    Flakes are drawn UNDER the cloud layer, so they emerge from beneath it
    rather than appearing on top of the thing they are falling out of.
"""

import math
import random
from typing import Callable

import noise
import numpy as np
import pygame as p

from Models.Particles import Dust2D, DustParams, Particle
from Models.Terrain import Terrain

CLOUD_STYLES = ("chalk", "ink", "outline")

# How far above its area of interest the cloud layer floats, in RENDER px --
# the same units as everything else measured on screen. Fog is the same layer
# with this set to 0.
CLOUD_HEIGHT = 120.0

# Per-style (shadow, lit) colour pair for the density render. "fog" isn't in
# CLOUD_STYLES because it isn't a cloud you cycle to -- it's the same field used
# for a different job, hugging the ground instead of floating over it.
CLOUD_PALETTES = {
    "chalk": ((120, 118, 126), (252, 250, 246)),
    "ink": ((28, 24, 22), (138, 128, 116)),
    # Barely darker and slightly cooler than the parchment: enough to register
    # as air between the peaks, not enough to read as a cloud lying on them.
    "fog": ((132, 124, 112), (208, 198, 182)),
}


class CloudField:
    """A scrolling 2D density field, rendered three ways. See the module
    docstring for what this keeps from the volumetric version and what it drops.

    All the per-frame maths happens at WORK resolution (a few thousand cells)
    and only the finished RGBA image is scaled up to the band, which is what
    keeps a full noise-driven cloud layer inside a frame budget.
    """

    def __init__(self, aoi: np.ndarray, out_size: tuple[int, int],
                 cloud_height: float = 0.0, work_cols: int = 128, work_rows: int = 104,
                 seed: int = 5, style: str = "chalk", pad: float = 70.0,
                 periods: tuple[int, int] = (2, 3), thickness_variation: float = 0.0,
                 origin: tuple[int, int] = (0, 0)):
        """`aoi` is a DATA-SPACE field marking the ground this weather belongs
        to -- (rows, cols), like every mask in Terrain. It need not be binary:
        values above 1 make the field heavier there, which is how fog is told to
        gather on the snowcaps rather than merely reach them.

        `out_size` is (width, height) in render px, the same convention as
        Terrain._resample and to_render_coords. `cloud_height` lifts the result
        that many render pixels, so the layer floats above its ground; 0 leaves
        it lying on it.

        `origin` is where the terrain's top-left sits on the surface this will
        be drawn onto. The AOI knows the shape of the ground but not where it
        was blitted, and Board centres its terrain rather than drawing it at
        (0, 0) -- so without this the weather lands offset from the land it
        belongs to, by however far the map is inset.
        """
        self.aoi = np.asarray(aoi, dtype=float)
        self.out_size = out_size
        self.cloud_height = cloud_height
        self.shape = (work_rows, work_cols)
        self.t = 0.0
        self.origin = origin
        self.band, self.mask = self._place(pad)

        self.coverage = 0.58      # 0 = overcast, ->1 = clear sky
        self.absorption = 3.2     # Beer's law k: how fast light dies going down
        self.opacity = 5.2        # density -> alpha steepness
        self.speed = 26.0         # px/s of the main layer
        self.style = style
        self.taper = (0.15, 0.55)  # top fade ends / bottom fade starts

        # Two octaved fields at different scales. One would drift rigidly, like
        # a painted backdrop sliding past; two at different speeds shear against
        # each other and the shapes visibly evolve.
        #
        # `periods` is (across, down) and it's the shape control: how many
        # features fit across the band versus down it. A low period across a
        # wide band gives few, broad masses; raising the vertical period against
        # it stacks them instead of smearing them into a horizontal streak.
        px, py = periods
        self._a = self._bake(px, py, octaves=4, seed=seed)
        self._b = self._bake(px * 2, py * 2, octaves=3, seed=seed + 41)

        # A third, much coarser field multiplied over the density. Without it
        # the coverage remap gives a field that's the same weight everywhere it
        # exists -- consistent, and so a bit flat. This makes it broadly thicker
        # in some places than others, which is what a real bank of anything
        # looks like. 0 disables it entirely.
        self.thickness_variation = thickness_variation
        self._m = (self._bake(2, 1, octaves=2, seed=seed + 7)
                   if thickness_variation > 0.0 else None)

        # Where snow comes out of. See _pick_sources.
        self.source_count = 5
        self.source_width = 110.0     # render px; 0 makes them points
        self.source_lifetime = 3.0    # seconds before the squalls move
        self.sources: list[tuple[float, float, float]] = []   # (x0, x1, y)
        self._source_age = 0.0

        self._density = np.zeros(self.shape)
        # Per column, the lowest work row still holding cloud. Filled by
        # update(); starts at the bottom row so a source picked before the
        # first update still lands inside the band.
        self._bottom: np.ndarray = np.full(work_cols, work_rows - 1, dtype=int)
        self.surface = p.Surface(self.band.size, p.SRCALPHA)
        self.update(0.0)

    # -- placement --------------------------------------------------------

    def _place(self, pad: float) -> tuple[p.Rect, np.ndarray]:
        """Scale the AOI into render space, lift it by `cloud_height`, and
        return the screen rect it occupies plus the AOI sampled over that rect
        at work resolution.

        The rect is the AOI's own bounding box rather than the page, because
        the per-frame cost of one of these layers is dominated by the
        smoothscale up to its band -- a band the size of the subject instead of
        the size of the screen is most of the budget.
        """
        rows, cols = self.aoi.shape
        out_w, out_h = self.out_size
        sy, sx = out_h / rows, out_w / cols

        ys, xs = np.nonzero(self.aoi > 0.0)
        rect = p.Rect(int(xs.min() * sx), int(ys.min() * sy),
                      int((xs.max() - xs.min() + 1) * sx),
                      int((ys.max() - ys.min() + 1) * sy))
        rect = rect.inflate(pad * 2, pad * 2)
        rect.y -= int(self.cloud_height)          # ... and float it above
        band = rect.clip(p.Rect(0, 0, out_w, out_h))

        # The AOI under this band is the band pushed back DOWN by the same
        # height. Read in data cells, and taken from the CLIPPED band so the
        # mask lines up with the pixels that actually get drawn.
        r0 = int(np.floor((band.top + self.cloud_height) / sy))
        r1 = int(np.ceil((band.bottom + self.cloud_height) / sy))
        c0, c1 = int(np.floor(band.left / sx)), int(np.ceil(band.right / sx))
        crop = self._crop(self.aoi, r0, r1, c0, c1)

        from scipy.ndimage import gaussian_filter
        work_rows, work_cols = self.shape
        small = Terrain._resample(crop, (work_cols, work_rows), order=1)
        # Softened so the layer thins out at the AOI's edge instead of ending
        # on a line. Clipped above 1 so an emphasised region stays emphasised.
        mask = np.clip(gaussian_filter(small, sigma=1.6), 0.0, float(self.aoi.max()))
        # Everything above worked in the terrain's own coordinates; only now
        # does the band move onto the surface it will actually be drawn on.
        # Doing it last means the mask lookup above never has to know about it.
        return band.move(self.origin), mask

    @staticmethod
    def _crop(field: np.ndarray, r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
        """Slice `field`, zero-padding wherever the window falls outside it.
        Plain slicing would silently return a SMALLER array at the edges, and a
        smaller array resampled to the same work grid is a mask that no longer
        lines up with the band it's masking."""
        out = np.zeros((r1 - r0, c1 - c0), dtype=float)
        rr0, rr1 = max(0, r0), min(field.shape[0], r1)
        cc0, cc1 = max(0, c0), min(field.shape[1], c1)
        if rr0 < rr1 and cc0 < cc1:
            out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = field[rr0:rr1, cc0:cc1]
        return out

    def _bake(self, period_x: int, period_y: int, octaves: int, seed: int) -> np.ndarray:
        """A TILEABLE fBm field, [0,1]. Tileable is the requirement, not a
        nicety: scrolling wraps with np.roll, and a field that doesn't tile
        would show a seam marching across the sky once per lap. pnoise2's
        repeat args give exact periodicity as long as the coordinates span
        whole periods, hence the periods being ints and lacunarity left at 2."""
        rows, cols = self.shape
        period_x, period_y = max(1, period_x), max(1, period_y)
        out = np.empty(self.shape)
        for j in range(rows):
            for i in range(cols):
                out[j, i] = noise.pnoise2(
                    i / cols * period_x, j / rows * period_y,
                    octaves=octaves, persistence=0.5, lacunarity=2.0,
                    repeatx=period_x, repeaty=period_y, base=seed)
        return Terrain.normalize(out)

    @staticmethod
    def _scroll(field: np.ndarray, px: float) -> np.ndarray:
        """Roll by a FRACTIONAL number of cells, lerping between the two
        bracketing integer rolls. Rolling to whole cells only would make the
        sky jump a cell at a time -- several screen pixels per step once this
        is scaled up, which reads as a stutter no amount of smoothing hides."""
        whole = math.floor(px)
        frac = px - whole
        near = np.roll(field, -whole, axis=1)
        far = np.roll(field, -(whole + 1), axis=1)
        return near * (1.0 - frac) + far * frac

    def update(self, dt: float) -> None:
        self.t += dt
        rows, cols = self.shape
        cell_w = self.band.w / cols

        a = self._scroll(self._a, self.t * self.speed / cell_w)
        b = self._scroll(self._b, self.t * self.speed * 1.7 / cell_w)
        d = 0.65 * a + 0.35 * b

        # Coverage as a remap rather than a cut -- see the module docstring.
        d = np.clip((d - self.coverage) / max(1e-3, 1.0 - self.coverage), 0.0, 1.0)

        # Broad thick/thin variation, drifting slower than the field it
        # modulates so the heavy patches don't travel locked to the shapes.
        if self._m is not None:
            v = self.thickness_variation
            m = self._scroll(self._m, self.t * self.speed * 0.6 / cell_w)
            d *= (1.0 - v) + 2.0 * v * m
        # Fade both edges of the band: it floats over the map rather than
        # starting at the top of the page, so at high cover an unfaded edge
        # draws a hard horizontal rule straight across the drawing -- at either
        # end. Fog wants no taper at all (it's bounded by its mask instead),
        # hence this being a knob rather than a constant.
        top_end, bottom_start = self.taper
        t = np.linspace(0.0, 1.0, rows)
        # Guarded because a zero-width fade is the legitimate way to say "no
        # taper" (fog), and smoothstep divides by (hi - lo).
        top = np.ones(rows) if top_end <= 0.0 else Terrain.smoothstep(0.0, top_end, t)
        bottom = (np.ones(rows) if bottom_start >= 1.0
                  else 1.0 - Terrain.smoothstep(bottom_start, 1.0, t))
        d *= (top * bottom)[:, None]
        # ... and confine it to the ground it belongs to.
        d *= self.mask
        self._density = d

        # Beer's law, marched downward: transmittance at a cell is set by how
        # much cloud is stacked ABOVE it. cumsum is the whole light march.
        above = np.cumsum(d, axis=0) - d
        lit = np.exp(-self.absorption * above / rows * 8.0)
        alpha = 1.0 - np.exp(-self.opacity * d)

        self._render(d, lit, alpha)

        # Per column, the lowest row still holding cloud -- the underside snow
        # comes off. argmax on the reversed column finds the last True; columns
        # with no cloud never get picked, so their value doesn't matter.
        self._bottom = rows - 1 - np.argmax((d > 0.05)[::-1], axis=0)

        self._source_age += dt
        if not self.sources or self._source_age >= self.source_lifetime:
            self._pick_sources()
            self._source_age = 0.0

    def _render(self, d: np.ndarray, lit: np.ndarray, alpha: np.ndarray) -> None:
        style = self.style
        rows, cols = self.shape

        if style == "outline":
            # The cartographic reading: throw the volume away and keep the
            # silhouette, inked like every other region boundary on the map.
            band = Terrain.contour(d > 0.35, thickness=1.0, align="center", soft=True)
            rgba = np.zeros((rows, cols, 4), dtype=np.uint8)
            rgba[:, :, :3] = (60, 52, 44)
            rgba[:, :, 3] = (band * 210).astype(np.uint8)
        else:
            lo, hi = (np.array(c, dtype=float) for c in CLOUD_PALETTES[style])
            rgb = lo + (hi - lo) * lit[:, :, None]
            rgba = np.empty((rows, cols, 4), dtype=np.uint8)
            rgba[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
            rgba[:, :, 3] = (np.clip(alpha, 0.0, 1.0) * 255).astype(np.uint8)

        small = p.Surface((cols, rows), p.SRCALPHA)
        Terrain.to_pygame_surf(rgba, small)
        # Scaling the FINISHED image is the trick that makes this affordable,
        # and clouds are the one subject where the softness is free realism.
        self.surface = p.transform.smoothscale(small, self.band.size)

    def _pick_sources(self) -> None:
        """Choose where it's snowing FROM: a few points or stripes on the
        cloud's underside, drawn with probability proportional to the cloud in
        each column.

        Weighted rather than uniform-over-the-area because a source in a gap
        would be snow falling out of clear sky. Re-picked on a timer, which is
        what turns steady snowfall into squalls that come and go -- and since
        the weighting follows the density, they follow the weather as it
        drifts rather than sitting at fixed spots under a moving cloud."""
        rows, cols = self.shape
        weight = self._density.sum(axis=0)
        total = weight.sum()
        if total <= 1e-6:
            self.sources = []
            return

        cdf = np.cumsum(weight) / total
        cell_w = self.band.w / cols
        half = self.source_width * 0.5
        self.sources = []
        for _ in range(self.source_count):
            col = min(int(np.searchsorted(cdf, random.random())), cols - 1)
            x = self.band.x + (col + random.random()) * cell_w
            # A stripe hangs off the underside along its whole width, so take
            # the LOWEST cloud across the columns it spans rather than the one
            # under its centre -- otherwise one end can start above the cloud.
            lo = max(0, int((x - half - self.band.x) / cell_w))
            hi = min(cols - 1, int((x + half - self.band.x) / cell_w))
            row = int(self._bottom[lo:hi + 1].max()) if lo <= hi else int(self._bottom[col])
            y = self.band.y + (row + 0.5) * self.band.h / rows
            self.sources.append((x - half, x + half, y))

    def spawn_point(self) -> p.Vector2 | None:
        """A point on one of the current sources, for the emitter to fire."""
        if not self.sources:
            return None
        x0, x1, y = random.choice(self.sources)
        return p.Vector2(random.uniform(x0, x1) if x1 > x0 else x0, y)

    def render(self, surf: p.Surface) -> None:
        surf.blit(self.surface, self.band.topleft)


def _smoothstep(lo: float, hi: float, x: float) -> float:
    """Scalar smoothstep. Terrain.smoothstep is the array version; this runs
    per particle per frame, where routing through numpy costs more than the
    arithmetic it does."""
    t = min(1.0, max(0.0, (x - lo) / (hi - lo)))
    return t * t * (3.0 - 2.0 * t)


class SnowFlake(Particle):
    """A Particle that remembers where it was born.

    Needed because a flake here is retired by how far it has FALLEN, not by
    reaching a fixed height (see SnowEmitter.fall_distance), and both the cull
    and the fade are expressed against that distance."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spawn_y: float = self.pos.y


class SnowEmitter(Dust2D):
    """Dust2D is a POINT source firing into a cone -- right for a dust puff,
    wrong for weather, which falls across a width. This takes a `source`
    callable returning a spawn position, so the same emitter can rain from a
    line or out of the underside of a cloud, and spawns at a steady RATE rather
    than the base class's one-particle-per-interval (which caps at one per
    frame and can't reach a snowfield's density).

    The base spawn is disabled by putting its interval out of reach; Dust2D's
    physics -- gravity, drag, turbulence, wind, gust -- is inherited untouched.
    """

    def __init__(self, source: Callable[[], p.Vector2 | None], rate: float,
                 grey: int = 255, max_alpha: int = 170,
                 cull_below: float | None = None, fall_distance: float | None = None,
                 **kwargs):
        super().__init__(min_spawn_interval=1e9, max_spawn_interval=1e9, **kwargs)
        self.source = source
        self.rate = rate
        self.grey = grey
        self.max_alpha = max_alpha
        self.cull_below = cull_below
        # How far a flake may descend from where it was born before it's
        # retired. Distance from ITS OWN spawn, not an absolute y, because the
        # cloud underside is a ragged line -- a single cutoff height would let
        # flakes from the low parts fall a few pixels and the high parts fall
        # hundreds. This is what keeps snow sitting ON the peaks.
        self.fall_distance = fall_distance
        self._pending = 0.0

    def _fade(self, fallen: float) -> float:
        """Alpha over a flake's fall, in [0,1]: in as it leaves the cloud, out
        as it settles.

        Dust2D fades alpha over the LIFESPAN, which is the right curve for dust
        and useless here -- fall_distance retires a flake in well under a
        second while its lifespan runs to ten or twenty, so every flake was
        being drawn at essentially full opacity for its whole life. That's what
        made dense snow read as hard white bars rather than as falling snow.
        """
        if not self.fall_distance:
            return 1.0
        f = fallen / self.fall_distance
        return _smoothstep(0.0, 0.35, f) * (1.0 - _smoothstep(0.6, 1.0, f))

    def update(self, dt: float):
        # Fractional accumulator, so a rate below one per frame still averages
        # out right instead of rounding away to nothing.
        self._pending += self.rate * dt
        while self._pending >= 1.0 and len(self.particles) < self.max_particles:
            self._pending -= 1.0
            pos = self.source()
            if pos is None:
                self._pending = 0.0
                break
            self.particles.append(SnowFlake(
                pos, self._rand_velocity(),
                col=p.Color(self.grey, self.grey, self.grey, 255),
                rad=random.uniform(self.min_rad, self.max_rad),
                lifespan=random.uniform(self.min_dur, self.max_dur)))
        super().update(dt)
        for part in self.particles:
            if not isinstance(part, SnowFlake):
                continue
            fallen = part.pos.y - part.spawn_y
            if self.cull_below is not None and part.pos.y > self.cull_below:
                part.need_destroy = True
            elif self.fall_distance is not None and fallen > self.fall_distance:
                part.need_destroy = True
            # Written after super(), which sets col.a from the lifespan fade.
            part.col.a = int(self.max_alpha * self._fade(fallen))




class Weather:
    """Clouds, optional fog, and the snow falling out of them, over one area of
    interest. The whole layer behind three calls, so a caller that owns a map
    needs `Weather(...)`, `update(dt)` and `render(surf)` and nothing else.

    `aoi` is a DATA-SPACE mask -- the same (rows, cols) shape as Terrain's
    biome_mat -- and `out_size` is (width, height) in render px, so a caller
    hands over exactly what it already has: a biome mask and the size it draws
    the terrain at.

    `fog` defaults OFF for a reason. Terrain bakes a static haze into the glyph
    map (see BIOME_HAZE), and that haze and this fog do the same job -- filling
    the paper between glyphs. Turning both on double-tints the same gaps.
    Switch this on only where the terrain underneath ISN'T hazed.
    """

    # Fog drifts at a few px/s. Rebuilding it every frame redraws a picture
    # that moved a fraction of a pixel, and it's the most expensive layer here
    # -- the smoothscale up to its band dominates. At 15 Hz the motion is
    # indistinguishable and it costs a quarter as much. The surface persists
    # between updates, so rendering is untouched.
    FOG_INTERVAL = 1.0 / 15.0

    def __init__(self, aoi: np.ndarray, out_size: tuple[int, int], seed: int = 0,
                 cloud_height: float = CLOUD_HEIGHT, style: str = "chalk",
                 coverage: float = 0.40, snowfall: float = 60.0,
                 flake_grey: int = 255, fall_distance: float = 26.0,
                 windy: bool = True, fog: bool = False,
                 origin: tuple[int, int] = (0, 0)):
        self.out_size = out_size
        self.clouds = CloudField(aoi, out_size, cloud_height=cloud_height,
                                 style=style, seed=seed, periods=(2, 3),
                                 origin=origin)
        self.clouds.coverage = coverage

        self.fog: CloudField | None = None
        self._fog_accum = 0.0
        if fog:
            self.fog = CloudField(aoi, out_size, cloud_height=0.0, seed=seed + 19,
                                  work_cols=160, work_rows=110, style="fog",
                                  periods=(4, 3), thickness_variation=0.45,
                                  origin=origin)
            self.fog.coverage = 0.08
            self.fog.opacity = 2.9
            self.fog.absorption = 1.4
            self.fog.speed = 4.0
            self.fog.taper = (0.0, 1.0)

        self.snow = SnowEmitter(
            source=self.clouds.spawn_point, rate=snowfall, grey=flake_grey,
            cull_below=origin[1] + out_size[1] + 20, fall_distance=fall_distance,
            # Slow drift, not a fall: terminal speed is gravity/drag, so 55/0.9
            # is about 60 px/s -- roughly a real flake, and slow enough that the
            # eye reads individual motes.
            min_speed=4.0, max_speed=16.0, direction=(0, 1), scatter=math.pi / 3,
            min_rad=1.6, max_rad=3.4,
            # Lifespan is the backstop, not the limit -- fall_distance retires a
            # flake long before this in the normal case.
            min_dur=8.0, max_dur=20.0, max_particles=1600,
            dust_params=DustParams(
                gravity=55.0, drag=0.9, turbulence=18.0, turbulence_drift=90.0,
                wind=p.Vector2(14.0, 0.0) if windy else p.Vector2(0.0, 0.0),
                wind_gust=22.0 if windy else 0.0, wind_gust_period=5.0,
                # Snow doesn't twinkle. Dust does -- that's what glow is for,
                # and leaving it on is what would make this read as embers.
                glow=0.0,
            ),
        )

    def update(self, dt: float) -> None:
        self.clouds.update(dt)
        if self.fog is not None:
            self._fog_accum += dt
            if self._fog_accum >= self.FOG_INTERVAL:
                # Hand over the whole accumulated time, not one interval's
                # worth, or the fog falls progressively behind the clock.
                self.fog.update(self._fog_accum)
                self._fog_accum = 0.0
        self.snow.update(dt)

    def render(self, surf: p.Surface) -> None:
        # Fog lies on the ground, so it goes under; snow goes under the cloud
        # it's falling out of.
        if self.fog is not None:
            self.fog.render(surf)
        self.snow.render(surf)
        self.clouds.render(surf)
