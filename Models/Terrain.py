# I want to generate terrain with perlin noise.

# TODO remove scipy from uv (pillow is already gone: the PIL import that used
# to sit above the __main__ preview block was dead, and the block itself now
# lives in scratch/terrain_preview.py).

from enum import Enum
import random as pyrandom
from typing import cast

import noise
import numpy as np
from numpy import random
import pygame as p

from Models.Haze import haze_field
from Utils.Image import knockout

# The styling/classification surface lives in TerrainStyle.py. Re-exported here
# so this module stays the single import point: every existing
# `from Models.Terrain import Biome, NoiseParams, BIOME_GLYPHS, ...` keeps
# working without a change at the call site.
from Models.TerrainStyle import (
    BIOME_CONTOURS,
    BIOME_FIELDS,
    BIOME_GLYPHS,
    BIOME_HATCHES,
    BIOME_HAZE,
    BIOME_THRESHOLDS,
    BIOME_THRESHOLDS_REV,
    BIOME_TINTS,
    HAZE_CELLS,
    HAZE_COVERAGE,
    HAZE_EDGE_GAIN,
    HAZE_EDGE_SOFTNESS,
    HAZE_VARIATION,
    INK,
    MOISTURE_THRESHOLDS,
    TEMPERATURE_THRESHOLDS,
    WHITTAKER_TABLE,
    Biome,
    ContourStyle,
    FieldStyle,
    GlyphStyle,
    HatchStyle,
    HazeStyle,
    MoistureLevels,
    NoiseParams,
    SunParams,
    TemperatureLevels,
    TerrainMode,
    _MOISTURE_LEVELS,
    _TEMPERATURE_LEVELS,
    _WHITTAKER_LUT,
)


class Terrain:
    """Two resolutions, kept strictly apart.

    DATA SPACE is the simulation grid, `NoiseParams.size` -- every physical
    field (height, moisture, temperature, shadows, the biome classification)
    lives here and never changes size. It's the terrain's actual content.
    Glyph positions are sampled on this grid too, though how densely depends
    on the render size (their spacing is specified in screen pixels).

    RENDER SPACE is `bounding_rect.size`, i.e. pixels on screen. Every image in
    `self.surfaces` is produced AT that size, by re-evaluating the fields there
    -- not by baking a small picture and stretching it. So stretching the
    terrain across a wider rect costs it no sharpness: palette ramps and biome
    edges are resolved at screen resolution, and glyphs are stamped at their
    own pixel size onto the full-size canvas rather than being magnified along
    with everything else.

    Surfaces are built LAZILY, one mode at a time: `self.surfaces` starts all
    None and `surface_for` bakes (and then caches) a mode the first time
    something asks for it. Only the mode actually on screen is paid for at
    startup; the rest cost their build the first time you switch to them and
    nothing after that.

    `resize` re-renders at a new size without touching a single field, so the
    terrain can never shift around underneath the board.
    """

    def __init__(
        self,
        height_noise_params: NoiseParams,
        moisture_noise_params: NoiseParams,
        sun_params: SunParams,
        bounding_rect: p.Rect,
        max_height: float = 4000.0,
        sea_level_temperature: float = 20.0,
        min_temperature: float | None = None,
    ):
        self.max_height = max_height
        self.sea_level_temperature = sea_level_temperature
        # The coldest point on the map, in degrees. Left to chance so no two
        # terrains have quite the same climate, but derived from the SEEDS
        # rather than from global randomness, because it is a climate input:
        # every temperature band, and so every Whittaker biome, moves with it.
        # Drawn from np.random it made the same pair of seeds produce different
        # biome maps run to run, which quietly defeats seeding at all -- you
        # could not A/B a generation change against a fixed map. Pass an
        # explicit value to pin it (or to sweep climate independently of shape).
        self.min_temperature = (
            int(
                np.random.default_rng(
                    (height_noise_params.seed, moisture_noise_params.seed)
                ).integers(-40, -20)
            )
            if min_temperature is None
            else min_temperature
        )
        self.noise_params = height_noise_params
        self.moisture_params = moisture_noise_params
        self.sun_params = sun_params
        self._build_fields()

        # Game interface
        self.bounding_rect = bounding_rect
        self.render_size: tuple[int, int] = bounding_rect.size
        self.fade_borders = True
        self.mode: TerrainMode = TerrainMode.GLYPHMAP
        # None = not baked yet. See surface_for.
        self.surfaces: dict[TerrainMode, p.Surface | None] = {}
        self._invalidate_render()
        self.surface_for(self.mode)  # only the mode we start on

    def _build_fields(self):
        """Everything that IS the terrain, in data space (see the class
        docstring). Runs exactly once, at construction -- none of it depends on
        how big the terrain is drawn, so `resize` never re-runs any of it."""
        self.height_map = Terrain.generate_height_map(self.noise_params)
        self.height_map_grad = np.gradient(self.height_map)
        self.shadow_map = Terrain.compute_shadows(
            self.height_map, self.sun_params, self.sun_params.shadow_falloff
        )
        self.shadow_accumulation_map = Terrain.compute_shadow_accumulation(
            self.height_map, self.sun_params
        )
        self.moisture_map = Terrain.generate_height_map(self.moisture_params)
        self._build_temp_map()  # must run first: _build_biome_map's Whittaker lookup needs temp_map_normalized
        self._build_biome_map()
        self.colour_map = Terrain.colour_from_biomes(self.biome_mat)
        # Glyph positions can't be sampled yet: their spacing is specified in
        # render px, so it takes a render size to know how dense to make them.
        # _build_maps fills these in and re-uses them across re-renders.
        self.glyph_coords: dict[Biome, list] = {}
        self._glyph_spacing: dict[Biome, float] = {}

    @staticmethod
    def step(matrix: np.ndarray, edge: float) -> np.ndarray:
        mat = np.zeros_like(matrix)
        mat[matrix >= edge] = 1.0
        return mat

    @staticmethod
    def smoothstep(lo: float, hi: float, matrix: np.ndarray) -> np.ndarray:
        """Smooth 0->1 ramp: 0 below `lo`, 1 above `hi`, an S-curve between. The
        soft-edged cousin of `step`; used to blend biome colours across their
        boundaries instead of hard-classifying."""
        t = np.clip((matrix - lo) / (hi - lo), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def band(matrix: np.ndarray, center: float, width: float) -> np.ndarray:
        """Band-pass mask: 1.0 where the value lies within `width` (total) of
        `center`, 0.0 elsewhere. Think of it as an iso-contour of thickness
        `width` around the height `center`."""
        mat = np.zeros_like(matrix)
        half = width * 0.5
        mat[np.abs(matrix - center) <= half] = 1.0
        return mat

    @staticmethod
    def border_fade(
        shape: tuple[int, int], inner: float = 0.75, outer: float = 1.0, n: float = 8.0
    ) -> np.ndarray:
        """(H, W) fade mask in [0,1]: 1.0 through the interior, smoothstepped
        down to 0.0 at the border. Distance from centre is the L^n (Minkowski)
        norm, normalized so 1.0 lands exactly on the nearest edge in each axis
        -- a large `n` biases the falloff toward the rectangle's actual
        border (Chebyshev-like) instead of an ellipse (n=2 would be circular).
        `inner`/`outer` are that normalized distance: unfaded up to `inner`,
        fully transparent at `outer`, smoothstepped in between.

        Computed from two 1-D profiles rather than two full 2-D coordinate
        grids: |x-cx| doesn't depend on the row and |y-cy| doesn't depend on
        the column, so `nx**n` is one value per column and `ny**n` one per row,
        and broadcasting adds them into the (H, W) sum. Only the final root
        touches every pixel. Same output to the bit, ~2.4x faster at 1800x1024
        -- worth it because this runs over the whole render-size canvas."""
        rows, cols = shape
        cy, cx = (rows - 1) / 2.0, (cols - 1) / 2.0
        ny_n = (np.abs(np.arange(rows) - cy) / cy) ** n  # (rows,)
        nx_n = (np.abs(np.arange(cols) - cx) / cx) ** n  # (cols,)
        d = (ny_n[:, None] + nx_n[None, :]) ** (1.0 / n)
        return 1.0 - Terrain.smoothstep(inner, outer, d)

    def get_biome_at_coords(self, row: int, col: int, grid_size: int) -> Biome:
        """Overlap the Board.py grid onto the terrain canvas: map a grid cell
        (row, col in 0..grid_size-1) to the corresponding canvas pixel and return
        the biome there."""
        # .shape[i] is the pixel count; valid indices are 0..shape-1, so map the
        # grid's last coord (grid_size-1) onto the last pixel (shape-1).
        rows, cols = self.height_map.shape
        x = int(np.interp(row, [0, grid_size - 1], [0, rows - 1]))
        y = int(np.interp(col, [0, grid_size - 1], [0, cols - 1]))
        return Biome(self.biome_mat[x, y])

    @staticmethod
    def _level_indices(
        vals: np.ndarray, thresholds: dict[tuple[float, float], Enum]
    ) -> np.ndarray:
        """Which band of `thresholds` each value falls in, as an index into the
        dict's own order. Bands are contiguous and ascending, so "the last band
        whose lower bound the value clears" is just a searchsorted against the
        interior lower bounds. Values are [0,1]-normalized; clamp defensively."""
        lower_bounds = np.array([lo for (lo, _hi) in thresholds])
        return np.searchsorted(lower_bounds[1:], np.clip(vals, 0.0, 1.0), side="right")

    @staticmethod
    def classify_biomes(
        height: np.ndarray, moisture: np.ndarray, temperature: np.ndarray
    ) -> np.ndarray:
        """height/moisture are height_map/moisture_map values (already
        [0,1]-normalized); temperature must be Terrain.normalize(temp_map) --
        temp_map itself is in real degrees and its range shifts
        terrain-to-terrain with the randomized min_temperature.

        Elevation still gates the biomes that aren't about climate -- coastline,
        peaks and snowcaps are about being underwater/at altitude, not about
        temperature/moisture. Everything in between is a Whittaker-style lookup:
        temperature x moisture -> biome (see WHITTAKER_TABLE).

        Fully vectorized over whole maps (returns Biome.value codes, same shape
        as the inputs) rather than classifying cell by cell. That's not just
        speed: it makes classifying at RENDER resolution cheap enough to do on
        every re-render, which is what gives biome edges their crispness when
        the terrain is stretched -- see _build_maps."""
        h = np.clip(height, 0.0, 1.0)
        temperature_bands = Terrain._level_indices(temperature, TEMPERATURE_THRESHOLDS)  # type: ignore
        moisture_bands = Terrain._level_indices(moisture, MOISTURE_THRESHOLDS)  # type: ignore
        biomes = _WHITTAKER_LUT[temperature_bands, moisture_bands]

        # Height overrides, applied after the climate lookup. LAKE (low) and
        # SNOW/MOUNTAIN (high) can't both fire on one cell, so order between
        # those groups doesn't matter; SNOW must win over MOUNTAIN though, as
        # its band sits inside the "at least mountain height" range.
        biomes = np.where(
            h >= BIOME_THRESHOLDS_REV[Biome.MOUNTAIN][0],
            np.uint8(Biome.MOUNTAIN.value),
            biomes,
        )
        biomes = np.where(
            h >= BIOME_THRESHOLDS_REV[Biome.SNOW][0], np.uint8(Biome.SNOW.value), biomes
        )
        biomes = np.where(
            h < BIOME_THRESHOLDS_REV[Biome.LAKE][1],
            np.uint8(Biome.LAKE.value),
            biomes,
        )
        return biomes.astype(np.uint8)

    def get_biome_from_val(
        self, height_val: float, moisture_val: float, temperature_val: float
    ) -> Biome:
        """Single-cell classification -- a thin wrapper over classify_biomes so
        the scalar and whole-map paths can't disagree about where a boundary
        sits. See classify_biomes for what the three values must be."""
        return Biome(
            int(
                Terrain.classify_biomes(
                    np.float64(height_val), np.float64(moisture_val), np.float64(temperature_val)  # type: ignore
                )
            )
        )

    @staticmethod
    def generate_height_map(noise_params: NoiseParams) -> np.ndarray:
        # noise_params.size is (width, height) in x,y order; the array itself
        # is (rows, cols) = (height, width), like every other map in this
        # file, so callers thinking in width/height never have to transpose.
        width, height = noise_params.size
        heightmap = np.zeros((height, width))
        for x in range(width):
            for y in range(height):
                heightmap[y][x] = noise.pnoise2(
                    x / noise_params.scale,
                    y / noise_params.scale,
                    octaves=noise_params.octaves,
                    persistence=noise_params.persistence,
                    lacunarity=noise_params.lacunarity,
                    repeatx=width,
                    repeaty=height,
                    base=noise_params.seed,
                )
        heightmap = Terrain.normalize(heightmap)
        return heightmap

    def _build_temp_map(self):
        if self.height_map is None:
            raise NotImplementedError("trying to build temp map over None height map")
        sea_level = BIOME_THRESHOLDS_REV[Biome.LAKE][1]

        self.temp_map = np.interp(
            self.height_map,
            [sea_level, 1.0],
            [self.sea_level_temperature, self.min_temperature],
        )
        # self.temp_map[self.temp_map > self.sea_level_temperature] = self.sea_level_temperature
        # last line commented out because numpy automatically clamps output between sea level temperature and min temperature

        # now adjust based on illumination: if sun ray is hitting perpendicular then hotter
        not_in_shadow = 1 - self.shadow_map
        gy, gx = self.height_map_grad  # each is (H, W), per-cell ∂h/∂y and ∂h/∂x
        theta, phi = np.radians(self.sun_params.elevation), np.radians(
            self.sun_params.azimuth
        )
        Lx = np.cos(theta) * np.cos(phi)
        Ly = np.cos(theta) * np.sin(phi)
        Lz = np.sin(theta)

        NdotL = (-gx * Lx - gy * Ly + Lz) / np.sqrt(gx**2 + gy**2 + 1.0)
        illum = np.clip(NdotL, 0.0, None)

        self.temp_map += self.sun_params.solar_max_temp_gain * illum * not_in_shadow
        self.temp_map -= self.sun_params.shadow_max_temp_loss * self.shadow_map
        # persistent "valley coldness": cells shadowed most of the day stay cold even at
        # moments (like right now) when the sun happens to be hitting them directly.
        self.temp_map -= (
            self.sun_params.accumulated_shadow_temp_loss * self.shadow_accumulation_map
        )

        # shadow_map is a hard 0/1 mask, so every shadow boundary was a sudden
        # step of shadow_max_temp_loss degrees -- a small blur turns that into a
        # gradient instead, which also reads more physically (heat diffuses).
        from scipy.ndimage import gaussian_filter

        self.temp_map = gaussian_filter(self.temp_map, sigma=1.5)

        # cached for the Whittaker lookup (get_biome_from_val) -- temp_map is in real
        # degrees and its range shifts terrain-to-terrain, so climate classification
        # needs it normalized to THIS map's own [0,1] range instead.
        self.temp_map_normalized = Terrain.normalize(self.temp_map)

    def _build_biome_map(self):
        """Classify every data-space cell exactly once (height + moisture +
        temperature -> biome, see classify_biomes) and cache it as Biome.value
        integer codes. Everything that asks "which cells are biome X" in data
        space -- glyph placement via get_biome_mask, get_biome_at_coords, the
        preview colour_map -- reads this, so they can never disagree.

        Note the rendered biome images do NOT come from here: they re-classify
        at render resolution (see _build_maps). Same function, same thresholds,
        just evaluated where the pixels are."""
        self.biome_mat = Terrain.classify_biomes(
            self.height_map, self.moisture_map, self.temp_map_normalized
        )

    @staticmethod
    def colour_from_biomes(biome_mat: np.ndarray) -> np.ndarray:
        """Biome.value codes -> an (H, W, 4) uint8 RGBA image via BIOME_TINTS.
        Resolution-agnostic: fed the data-space biome_mat it produces the
        preview wash, fed a render-space classification it produces the real
        thing."""
        colours = np.zeros((biome_mat.shape[0], biome_mat.shape[1], 4), dtype=np.uint8)
        for biome, colour in BIOME_TINTS.items():
            colours[biome_mat == biome.value] = (colour.r, colour.g, colour.b, colour.a)
        return colours

    @staticmethod
    def _resample(
        field: np.ndarray, out_size: tuple[int, int], order: int = 1
    ) -> np.ndarray:
        """Sample a data-space (H, W) field at `out_size` = (width, height)
        RENDER pixels. This is the one place where data resolution becomes
        render resolution.

        Resampling the FIELD and colouring afterwards is what keeps the maps
        sharp: an upscaled picture is blurry because its palette bands and
        biome edges were already rasterized at 450x256, whereas an upscaled
        field still lands those edges on exact render pixels.

        `order` is the spline order: 1 (bilinear) for masks and anything that
        must stay within its original range, 3 (bicubic) for smooth continuous
        fields, where it avoids the faceted look bilinear gives on a big
        upscale. Output pixel CENTRES are mapped back to input pixel centres
        (hence the -0.5 shifts), so the field doesn't drift half a cell."""
        from scipy.ndimage import map_coordinates

        rows, cols = field.shape
        out_w, out_h = out_size
        if (cols, rows) == (out_w, out_h):
            return field.astype(np.float64)
        y = (np.arange(out_h) + 0.5) * (rows / out_h) - 0.5
        x = (np.arange(out_w) + 0.5) * (cols / out_w) - 0.5
        yy, xx = np.meshgrid(y, x, indexing="ij")
        # mode='nearest' clamps the half-pixel overhang at the borders instead
        # of fading it toward a fill value.
        return map_coordinates(
            field.astype(np.float64), [yy, xx], order=order, mode="nearest"
        )

    def _invalidate_render(self):
        """Drop everything that was baked for the current render size. Called
        on construction and on resize; the next surface_for rebuilds what's
        actually asked for."""
        self.surfaces = {mode: None for mode in TerrainMode}
        self._render_biomes_cache: np.ndarray | None = None
        self._fade_cache: np.ndarray | None = None

    def _render_field(self, field: np.ndarray, order: int) -> np.ndarray:
        """A data-space field, resampled to render size and clipped back into
        [0,1] (cubic overshoots slightly at sharp features)."""
        return np.clip(Terrain._resample(field, self.render_size, order), 0.0, 1.0)

    def _render_biomes(self) -> np.ndarray:
        """Biome codes at RENDER resolution: the three inputs resampled, then
        re-classified here rather than the data-space biome_mat being scaled
        up. That's what makes region edges hard where the classification says
        they're hard, instead of a few px of interpolated mud between tints.

        Cached because three of the six modes want it (both biome washes, and
        the glyph map's coastline) and it's the expensive half of building
        them: 1.8MB of uint8 to avoid re-resampling three float fields on every
        mode switch. The float fields themselves are deliberately NOT cached --
        at render size they're ~15MB each, and only one mode each ever reads
        them."""
        if self._render_biomes_cache is None:
            # These three must be resampled together and read by both the
            # heightmap ramp and the classification, or the two would disagree
            # about exactly where the shoreline is.
            height_r = self._render_field(self.height_map, order=3)
            moisture_r = self._render_field(self.moisture_map, order=3)
            temp_r = self._render_field(self.temp_map_normalized, order=3)
            self._render_biomes_cache = Terrain.classify_biomes(
                height_r, moisture_r, temp_r
            )
        return self._render_biomes_cache

    def _render_map(self, mode: TerrainMode) -> np.ndarray:
        """One mode's (H_out, W_out, 4) uint8 RGBA image, at render size. RGBA
        even where alpha is always opaque, so every mode shares one shape and
        _bake_surface needs no per-mode branching.

        Each is re-derived from the data-space fields rather than scaled up
        from a small picture: the continuous fields are resampled and THEN run
        through their palette, so the ramps' colour boundaries land on render
        pixels; biomes are re-classified (see _render_biomes); glyphs are
        stamped at their own pixel size (see _build_glyph_map). Only the shadow
        mask is genuinely a picture, and bilinear is the right answer for it
        anyway -- it antialiases the 0/1 edges.

        Transient: the array is handed straight to _bake_surface and dropped.
        The surface is the cache, so nothing holds 7MB per mode twice."""
        if mode is TerrainMode.GLYPHMAP:
            return self._build_glyph_map(self.render_size, self._render_biomes())
        if mode is TerrainMode.BIOMESMAP or mode is TerrainMode.COLOURMAP:
            return Terrain.colour_from_biomes(self._render_biomes())
        if mode is TerrainMode.HEIGHTMAP:
            return Terrain.apply_palette(
                self._render_field(self.height_map, order=3), Terrain.ELEVATION_PALETTE
            )
        if mode is TerrainMode.TEMPMAP:
            return Terrain.apply_palette(
                self._render_field(self.temp_map_normalized, order=3),
                Terrain.TEMPERATURE_PALETTE,
            )
        if mode is TerrainMode.SHADOWMAP:
            return Terrain._grey_to_rgba(
                self._render_field(self.shadow_map.astype(np.float64), order=1)
            )
        raise ValueError(f"no renderer for terrain mode {mode!r}")

    def _bake_surface(self, rgba: np.ndarray) -> p.Surface:
        """A render-size RGBA image -> a blittable surface. Pure format
        conversion: the image already comes out of _render_map at render size,
        so nothing here scales anything."""
        out_w, out_h = self.render_size
        if self.fade_borders:
            # Faded at render resolution too -- the falloff is a smooth
            # analytic function, so there's no reason to compute it coarsely
            # and stretch it. Copy first: _render_map's output may be freshly
            # built, but the fade must never be applied to an array twice.
            if self._fade_cache is None:
                self._fade_cache = Terrain.border_fade((out_h, out_w))
            rgba = rgba.copy()
            rgba[:, :, 3] = (rgba[:, :, 3] * self._fade_cache).astype(np.uint8)
        surf = p.Surface((out_w, out_h), p.SRCALPHA)
        Terrain.to_pygame_surf(rgba, surf)
        return surf

    def surface_for(self, mode: TerrainMode) -> p.Surface:
        """The blittable surface for `mode`, built on first request and cached
        from then on. This is the only way surfaces come into existence -- go
        through it rather than indexing self.surfaces, which holds None for
        anything not baked yet."""
        surf = self.surfaces[mode]
        if surf is None:
            surf = self._bake_surface(self._render_map(mode))
            self.surfaces[mode] = surf
        return surf

    def resize(self, bounding_rect: p.Rect):
        """Re-render to fit a new on-screen rect. The fields are untouched, so
        the terrain keeps its exact shape -- stretching the rect stretches the
        LAND, not the drawing of it. Glyphs keep their pixel size and their
        screen spacing, which means a scale change re-samples their positions
        (deterministically, see _build_glyph_coords); a resize that keeps the
        scale keeps the layout too.

        Only the mode currently on screen is rebuilt here; the others are
        dropped and rebuilt if and when they're next asked for."""
        self.bounding_rect = bounding_rect
        self.render_size = bounding_rect.size
        self._invalidate_render()
        self.surface_for(self.mode)

    @staticmethod
    def normalize(mat: np.ndarray) -> np.ndarray:
        low, hi = mat.min(), mat.max()
        return np.interp(mat, [low, hi], [0, 1]).reshape(mat.shape)

    @staticmethod
    def _grey_to_rgba(mat: np.ndarray) -> np.ndarray:
        """A {0,1} or bool (H, W) matrix -> a fully opaque (H, W, 4) uint8 RGBA
        greyscale image. Shared by every mask/greyscale preview so they match
        the RGBA shape the rest of self.maps uses."""
        grey = (np.clip(mat.astype(np.float64), 0.0, 1.0) * 255).astype(np.uint8)
        rgb = np.repeat(grey[:, :, None], 3, axis=2)
        alpha = np.full((mat.shape[0], mat.shape[1], 1), 255, dtype=np.uint8)
        return np.concatenate([rgb, alpha], axis=2)

    @staticmethod
    def apply_palette(
        mat: np.ndarray, palette: list[tuple[float, tuple[int, int, int]]]
    ) -> np.ndarray:
        """Map a [0,1]-normalized matrix through a piecewise-linear colour ramp.
        `palette` is a list of (stop, rgb) pairs, stops ascending in [0,1] and
        covering the full range (e.g. the first stop should be 0.0, the last
        1.0) -- values are linearly blended between the two bracketing stops.
        Returns an (H, W, 4) uint8 RGBA array, fully opaque (alpha=255) --
        every map in this file is RGBA for consistency, even where alpha is
        never anything but opaque."""
        stops = np.array([s for s, _ in palette])
        colours = np.array([c for _, c in palette], dtype=float)  # (N, 3)
        flat = np.clip(mat, 0.0, 1.0).reshape(-1)
        out = np.empty((flat.shape[0], 3))
        for channel in range(3):
            out[:, channel] = np.interp(flat, stops, colours[:, channel])
        rgb = out.reshape(mat.shape[0], mat.shape[1], 3).astype(np.uint8)
        alpha = np.full((mat.shape[0], mat.shape[1], 1), 255, dtype=np.uint8)
        return np.concatenate([rgb, alpha], axis=2)

    # Classic topographic ramp: deep blue (sea) -> cyan/green (shallows/coast)
    # -> yellow-green (lowland) -> brown (highland) -> red (peaks).
    ELEVATION_PALETTE: list[tuple[float, tuple[int, int, int]]] = [
        (0.00, (18, 42, 110)),  # deep water
        (0.10, (46, 100, 176)),  # shallow water
        (0.12, (210, 200, 150)),  # shoreline
        (0.35, (96, 156, 72)),  # lowland green
        (0.65, (176, 148, 84)),  # highland brown
        (0.85, (150, 90, 70)),  # mountain red-brown
        (1.00, (214, 60, 50)),  # peak red
    ]

    # Classic thermal ramp: cold blue -> temperate green -> hot red. Meant for
    # temp_map (which is NOT [0,1]-normalized, unlike height_map) -- normalize
    # it first, e.g. via `Terrain.normalize(t.temp_map)`.
    TEMPERATURE_PALETTE: list[tuple[float, tuple[int, int, int]]] = [
        (0.00, (30, 60, 170)),  # coldest (mountaintop)
        (0.35, (90, 160, 200)),  # cool
        (0.55, (150, 200, 120)),  # temperate
        (0.75, (230, 190, 70)),  # warm
        (1.00, (210, 50, 40)),  # hottest (sea level)
    ]

    @staticmethod
    def to_pygame_surf(
        mat: np.ndarray,
        surf: p.Surface,
        palette: list[tuple[float, tuple[int, int, int]]] | None = None,
        size: tuple | None = None,
    ) -> None:
        """Blit a matrix onto `surf`. Two shapes are accepted:
        - (H, W): a [0,1]-normalized scalar matrix, with no colour baked in
          yet. With no palette this is plain greyscale; pass a palette (see
          `ELEVATION_PALETTE`) to colour-map it instead. Either way this path
          produces fully opaque pixels.
        - (H, W, 4): an already-RGBA image (e.g. colour_map, apply_palette's
          own output, or a glyph composite) -- blitted as-is, `palette` is
          ignored. This is the shape every self.maps entry uses.
        Important: the surface's (width, height) must match the matrix's
        (cols, rows) -- pygame sizes are (W, H), matrices here are (H, W, ...)."""
        if surf.get_size() != (mat.shape[1], mat.shape[0]):
            raise ValueError(
                f"Error: trying to blit_array a matrix of shape {mat.shape} onto a surface of size {surf.get_size()}"
            )
        if mat.ndim == 2 and palette is not None:
            mat = Terrain.apply_palette(mat, palette)
        elif mat.ndim == 2:
            mat = Terrain._grey_to_rgba(mat)
        # mat is now (H, W, 4) RGBA. blit RGB then restore alpha explicitly --
        # blit_array alone would keep the destination surface's OWN alpha
        # (usually opaque), making every transparent source pixel render as
        # solid black instead of see-through.
        p.surfarray.blit_array(surf, np.transpose(mat[:, :, :3], (1, 0, 2)))
        p.surfarray.pixels_alpha(surf)[:, :] = np.transpose(mat[:, :, 3], (1, 0))

    @staticmethod
    def build_inked_mat(
        mat: np.ndarray, ink_colour: tuple[int, int, int, int], ink_width: float = 0.02
    ) -> np.ndarray:
        """Build coloured matrix with INK colour between areas"""
        out = np.zeros((mat.shape[0], mat.shape[1], 4), dtype=np.uint8)
        rows, cols = mat.shape
        for i in range(rows):
            for j in range(cols):
                for interval, biome in BIOME_THRESHOLDS.items():
                    val = mat[i, j]
                    if (
                        interval[1] - ink_width * 0.5
                        <= val
                        <= interval[1] + ink_width * 0.5
                    ):
                        # then it's the contour
                        out[i, j] = ink_colour
                        break
                    elif interval[0] <= val <= interval[1]:
                        out[i, j] = BIOME_TINTS[biome]
                        break
        return out

    @staticmethod
    def compute_glyph_points_mat(mask: np.ndarray, spacing: int = 5) -> np.ndarray:
        """This function takes in a mask representing a set of points, then gives back a mask representing where to spawn the glyphs inside that area (out_mask is all 0 except 1 where you gotta spawn them, use np.argwhere(out_mask) to get coordinates)"""
        mask2 = np.zeros_like(mask)
        mask2[::spacing, ::spacing] = 1
        return mask * mask2

    @staticmethod
    def compute_glyph_points_mat_unif(
        mask: np.ndarray,
        spacing: float = 10.0,
        how_many: int | None = 20,
        return_coords=True,
        rng=None,
    ):
        """Blue-noise-ish sample of points inside `mask`, each at least
        `spacing` px from every other accepted point (a random point is picked,
        accepted, then a disk of radius `spacing` around it is stamped out of a
        working copy of the mask so later picks can't land too close).

        `how_many`:
          - an int: sample up to that many points (fewer if the mask runs out of
            room under the spacing constraint first -- the loop always stops
            when the working mask is exhausted, whichever limit hits first).
          - None: no count cap. Keep sampling until the working mask is fully
            stamped out, i.e. take the MAXIMUM number of points that fit under
            the spacing constraint. Denser `spacing` -> more points; this is the
            "fill the area as densely as `spacing` allows" mode.

        Order is NOT depth-sorted here (this is a general point-sampling
        utility) -- callers that draw the points as overlapping sprites are
        responsible for sorting into paint order themselves, same as the
        grid_like path in _get_point_cloud_coords does.

        Implemented by walking ONE random permutation of the mask's cells and
        skipping the ones already stamped out. That's distributionally
        identical to re-picking a random survivor each round (a uniform
        permutation restricted to the surviving cells is still uniform) but
        costs a single argwhere instead of one per accepted point -- which
        matters now that dense glyph fields ask for thousands of points.

        `rng` is anything with .permutation (a np.random.Generator, or the
        np.random module itself by default). Pass a seeded one where the point
        set has to come out the same twice -- glyph placement does, or a
        re-render would re-scatter the whole map."""
        rng = rng if rng is not None else np.random
        candidates = np.argwhere(mask)
        free = mask.astype(bool)
        accepted = []

        # precompute disk offsets
        r = int(np.ceil(spacing))
        di, dj = np.mgrid[-r : r + 1, -r : r + 1]
        disk = (di**2 + dj**2) < spacing**2
        di, dj = di[disk], dj[disk]

        # how_many=None -> uncapped; running out of candidates is then the ONLY
        # stop condition, so this samples the max points the spacing allows.
        for idx in rng.permutation(len(candidates)):
            if how_many is not None and len(accepted) >= how_many:
                break
            i, j = candidates[idx]
            if not free[i, j]:
                continue  # inside an earlier point's exclusion disk
            accepted.append(candidates[idx])

            # stamp out the disk
            ii, jj = i + di, j + dj
            valid = (ii >= 0) & (ii < mask.shape[0]) & (jj >= 0) & (jj < mask.shape[1])
            free[ii[valid], jj[valid]] = False

        if return_coords:
            return accepted
        mask2 = np.zeros_like(mask)
        if accepted:
            sample = np.array(accepted)
            mask2[sample[:, 0], sample[:, 1]] = 1
        return mask2

    @staticmethod
    def get_biome_mask(
        biome_mat: np.ndarray, biome: Biome, margin_px: float = 0.0
    ) -> np.ndarray:
        """{0,1} mask of every cell classified as `biome` in biome_mat (see
        Terrain._build_biome_mat -- the cached height+moisture+temperature
        Whittaker classification, NOT a height-only approximation, so this
        always agrees with colour_mat).

        `margin_px` is the distance-to-border knob: a cell survives only if it
        lies at least that many pixels (of biome_mat) from the nearest cell of
        any other biome, pulling the mask in from the region's edge. Sampling
        glyph points from the inset mask instead of the raw region is what
        keeps glyphs from adjacent biomes off each other across a border, and
        what holds them clear of an inked outline drawn on that border.

        Uses the distance transform rather than repeated binary_erosion: the
        inset is then isotropic (erosion's default 3x3 cross gives a diamond,
        so a margin of N would only be N/sqrt(2) diagonally) and `margin_px`
        can be fractional."""
        mask = biome_mat == biome.value
        if margin_px > 0:
            # EDT = distance to the nearest cell NOT in this biome, so this
            # reads literally as "at least margin_px in from the border".
            mask = _edt(mask) >= margin_px
        return mask.astype(np.float64)

    @staticmethod
    def to_render_coords(
        coords, data_shape: tuple[int, int], out_size: tuple[int, int]
    ):
        """Data-space (row, col) points -> render-space (y, x) points.

        Cell CENTRES map to the centre of the render pixels that cell covers,
        matching _resample's convention, so a glyph sits over the same terrain
        feature the colours put there. Returns floats -- _stamp_glyphs rounds
        at blit time, and rounding here instead would quantize every glyph to
        the coarse data grid, which is exactly the stair-stepping this whole
        refactor is trying to get rid of."""
        rows, cols = data_shape
        out_w, out_h = out_size
        scale_y, scale_x = out_h / rows, out_w / cols
        return [
            ((row + 0.5) * scale_y - 0.5, (col + 0.5) * scale_x - 0.5)
            for row, col in coords
        ]

    def get_point_cloud_coords(
        self,
        biome: Biome,
        spacing: float = 18.0,
        grid_like=True,
        how_many: int | None = 20,
        margin_px: float = 0.0,
        out_size: tuple[int, int] | None = None,
        rng=None,
    ):
        """Coordinates to spawn glyphs at, in PAINT ORDER (ascending row/y).

        Sampling happens on the data grid, so `spacing` and `margin_px` are in
        DATA pixels here -- convert render-space values with
        Terrain.to_data_px first, the way _build_glyph_coords does. Pass
        `out_size` = (width, height) to get the result scaled into render
        space; leave it None for raw data-space coordinates. `rng` is forwarded
        to the sampler (see compute_glyph_points_mat_unif) for reproducible
        placement."""
        biome_mask = Terrain.get_biome_mask(self.biome_mat, biome, margin_px=margin_px)
        if not grid_like:
            # keyword args here on purpose: compute_glyph_points_mat_unif's
            # signature is (mask, spacing, how_many, return_coords) -- a stray
            # positional call can silently send how_many into `spacing` and
            # True (=1) into `how_many`, so only ONE point ever comes back
            # regardless of the requested how_many.
            coords = Terrain.compute_glyph_points_mat_unif(
                biome_mask,
                spacing=spacing,
                how_many=how_many,
                return_coords=True,
                rng=rng,
            )
        else:
            # The grid sampler strides the array, so this branch alone needs a
            # whole number -- the blue-noise one above takes a real spacing.
            glyph_mask = Terrain.compute_glyph_points_mat(
                biome_mask, spacing=max(1, int(spacing))
            )
            coords = np.argwhere(glyph_mask)
        if out_size is not None:
            coords = Terrain.to_render_coords(coords, self.biome_mat.shape, out_size)
        return sorted(coords, key=lambda c: c[0])

    @staticmethod
    def _blit_ink(
        surf: p.Surface,
        coverage: np.ndarray,
        colour: tuple[int, int, int, int] | p.Color,
    ) -> None:
        """Composite a flat `colour` onto `surf` through a coverage mask -- a
        bool matrix, or float in [0,1] for an antialiased edge (what
        Terrain.contour(soft=True) returns). Drawn in place, like
        _stamp_glyphs, so several ink layers can share one canvas.

        Goes through a temporary layer + blit rather than writing the colour
        straight into `surf`'s pixels, so partial coverage BLENDS with whatever
        is already on the canvas instead of replacing it."""
        alpha = (np.clip(coverage.astype(np.float64), 0.0, 1.0) * colour[3]).astype(
            np.uint8
        )
        if not alpha.any():
            return
        layer = p.Surface((coverage.shape[1], coverage.shape[0]), p.SRCALPHA)
        layer.fill((*colour[:3], 255))
        # numpy is (rows, cols); pygame surfaces are (x, y) -- hence the swap,
        # same convention as to_pygame_surf.
        p.surfarray.pixels_alpha(layer)[:, :] = np.transpose(alpha, (1, 0))
        surf.blit(layer, (0, 0))

    @staticmethod
    def _stamp_glyphs(
        surf: p.Surface,
        coords,
        glyph_paths: list[str],
        glyph_size: int,
        seed: int = 0,
        max_rotation: float = 5.0,
        scale_range: tuple[float, float] = (0.8, 1.2),
        knockout_glyphs: bool = False,
        knockout_background_color=(255, 255, 255),
        knockout_fill: str = "holes",
        knockout_variants: int = 1,
        knockout_spread: int = 0,
    ) -> None:
        """Stamp a glyph sprite at each `coords` location directly onto `surf`
        (drawn in place, so callers compositing multiple biomes' glyphs onto
        one shared surface just call this once per biome). Glyphs are picked
        randomly (seeded) from `glyph_paths` for visual variety, and each
        stamped instance gets its own random rotation (+-max_rotation degrees)
        and scale (uniform in scale_range) so a repeated glyph doesn't look
        mechanically identical every time -- reads more hand-placed/organic.
        Rotation/scale are per-instance (not baked into the shared glyph list),
        so use p.transform.rotozoom rather than pre-scaling once.

        `knockout_glyphs=True` runs each sprite through Utils.Image.knockout
        (ink outline -> ink on opaque `knockout_background_color` body) before
        scaling, same look as the pre-baked mountain `_knockout.png` assets, but
        for glyph sets (like forest) that only ship a plain ink-on-transparent
        png. Pass a parchment tint for `knockout_background_color` to blend the
        knocked-out body into the page instead of standing out as white."""
        glyphs = [p.image.load(path).convert_alpha() for path in glyph_paths]
        if knockout_glyphs:
            # Each sprite knocked out at `knockout_variants` brightnesses, all
            # of them going into the same pool the per-stamp rng picks from --
            # so a variant is just another sprite as far as placement cares.
            # Seeded off `seed` so a re-render lays down the same tones.
            vrng = pyrandom.Random(seed ^ 0x5A17)
            variants = []
            for g in glyphs:
                for i in range(max(1, knockout_variants)):
                    # A single luminance offset per variant, not per channel:
                    # jittering channels independently drifts the hue, and
                    # snow that varies in colour rather than brightness reads
                    # as a printing fault.
                    d = (
                        vrng.randint(-knockout_spread, knockout_spread)
                        if knockout_spread
                        else 0
                    )
                    body = tuple(
                        max(0, min(255, c + d)) for c in knockout_background_color[:3]
                    )
                    variants.append(knockout(g, body, fill=knockout_fill))
            glyphs = variants
        # Pre-scale to the LARGEST size any instance will be drawn at, then let
        # the per-instance scale below only ever shrink from there. Pre-scaling
        # to glyph_size instead would make every instance above 1.0 a blur,
        # magnifying a sprite that had already been thrown away down to
        # glyph_size -- while the source art (128-512px) had the detail all
        # along. Final sizes are unchanged, they're just never round-tripped
        # through a smaller intermediate.
        #
        # `glyph_size` sets the sprite's LONGEST side, and the other side
        # follows the source's aspect ratio. Forcing a square would stretch any
        # art whose canvas isn't square -- e.g. the wave glyph, cropped to its
        # ink at 388x304, would come out 28% too tall. Square sources (the
        # trees and mountains) are unaffected: longest-side-to-glyph_size is
        # exactly what scaling both sides to glyph_size already did.
        largest = max(scale_range)
        target = round(glyph_size * largest)
        glyphs = [
            p.transform.smoothscale(
                g,
                tuple(
                    max(1, round(side * target / max(g.get_size())))
                    for side in g.get_size()
                ),
            )
            for g in glyphs
        ]

        rng = pyrandom.Random(seed)
        for row, col in coords:
            g = rng.choice(glyphs)
            angle = rng.uniform(-max_rotation, max_rotation)
            scale = rng.uniform(*scale_range) / largest
            # rotozoom recomputes the surface's bounding box on rotation, so the
            # rect must come from the TRANSFORMED surface, not the original, or
            # the stamp drifts off its intended point once rotated.
            g_t = p.transform.rotozoom(g, angle, scale)
            surf.blit(g_t, g_t.get_rect(center=(round(col), round(row))))

    @staticmethod
    def data_spacing_for(
        render_spacing: float, data_shape: tuple[int, int], out_size: tuple[int, int]
    ) -> float:
        """A minimum gap in render px -> the minimum gap in data px that
        guarantees it. Two points `d` data cells apart end up `d * scale_x`
        apart horizontally and `d * scale_y` vertically, so the axis that can
        violate the gap first is the SMALLER scale -- divide by that one and
        both axes are safe. (With a uniform scale, which is the usual case,
        min() just picks the shared factor.)

        Floored at 1.0: the mask has no structure finer than one data cell, so
        asking for a sub-cell gap doesn't buy denser glyphs, it just makes the
        sampler accept nearly every cell it looks at."""
        return max(1.0, Terrain.to_data_px(render_spacing, data_shape, out_size))

    @staticmethod
    def to_data_px(
        render_px: float, data_shape: tuple[int, int], out_size: tuple[int, int]
    ) -> float:
        """A render-space distance -> the same distance in data cells. The raw
        conversion behind data_spacing_for, without its floor -- a margin of 0
        has to stay 0."""
        rows, cols = data_shape
        out_w, out_h = out_size
        return render_px / min(out_w / cols, out_h / rows)

    def _build_glyph_coords(self, out_size: tuple[int, int]):
        """Sample each glyph biome's positions, in data space.

        GlyphStyle.spacing and .margin are in render px, so both the point
        count and the inset from the biome's border depend on how far the
        terrain is stretched -- hence the conversion to data cells here.
        Results are cached against the data spacing they were sampled at: a
        re-render at the same size (or any size with the same scale) reuses the
        layout rather than re-scattering every tree and mountain. A resize that
        really does change the scale has to re-sample, since holding screen
        density constant means a different number of glyphs -- but the sampler
        is seeded off the terrain's own noise seed, so a given size always
        produces the same map back."""
        for biome, style in BIOME_GLYPHS.items():
            spacing = Terrain.data_spacing_for(
                style.spacing, self.biome_mat.shape, out_size
            )
            if self._glyph_spacing.get(biome) == spacing:
                continue
            self.glyph_coords[biome] = self.get_point_cloud_coords(
                biome,
                grid_like=False,
                how_many=None,
                spacing=spacing,
                margin_px=Terrain.to_data_px(
                    style.margin, self.biome_mat.shape, out_size
                ),
                rng=np.random.default_rng((self.noise_params.seed, biome.value)),
            )
            self._glyph_spacing[biome] = spacing

    def _build_glyph_map(
        self, out_size: tuple[int, int], biomes: np.ndarray
    ) -> np.ndarray:
        """The map's ink layer: every biome in BIOME_CONTOURS outlined, every
        biome in BIOME_GLYPHS stamped, on a transparent canvas -- no colour_map
        wash underneath (see TerrainMode.COLOURMAP for that). Returns an
        (H_out, W_out, 4) uint8 RGBA array; everywhere not inked stays alpha=0.

        The canvas is the FULL render size and each sprite is drawn at its own
        GlyphStyle.size in render pixels, so glyphs are never magnified with
        the terrain -- and since GlyphStyle.spacing is in render pixels too,
        they don't drift apart with it either.

        `biomes` is the RENDER-resolution classification from _build_maps, not
        the data-space biome_mat: contours trace it directly, so a coastline is
        a crisp screen-resolution line rather than an upscaled one."""
        self._build_glyph_coords(out_size)
        surf = p.Surface(out_size, p.SRCALPHA)

        # Haze first, under everything: it's air and shadow lying on the
        # ground, so anything drawn on that ground belongs on top of it. ONE
        # field, masked per biome -- see BIOME_HAZE for why they share it.
        if BIOME_HAZE:
            from scipy.ndimage import gaussian_filter

            haze = np.clip(
                Terrain._resample(
                    haze_field(
                        HAZE_CELLS,
                        seed=self.noise_params.seed,
                        coverage=HAZE_COVERAGE,
                        variation=HAZE_VARIATION,
                    ),
                    out_size,
                    order=3,
                ),
                0.0,
                1.0,
            )
            for biome, style in BIOME_HAZE.items():
                region = np.clip(
                    gaussian_filter(
                        (biomes == biome.value).astype(np.float64),
                        sigma=HAZE_EDGE_SOFTNESS,
                    )
                    * HAZE_EDGE_GAIN,
                    0.0,
                    1.0,
                )
                Terrain._blit_ink(surf, haze * region * style.strength, style.colour)

        # Painter's order: farmland, then region shading, then the outlines
        # bounding it, then the glyphs on top -- a tree at the water's edge
        # should sit ON the coastline, not be sliced by it, and a field's
        # furrows belong under everything since they're what's on the ground.
        #
        # All of them read `biomes`, never self.biome_mat: these are drawn onto
        # a render-size canvas, so a data-space mask would land as a small patch
        # in the top-left corner rather than covering the map.
        for biome, style in BIOME_FIELDS.items():
            # Parcels are laid out in render pixels, so the biome mask they're
            # clipped to (margin included) has to be the render-resolution one.
            region = Terrain.get_biome_mask(biomes, biome, margin_px=style.margin) > 0
            if region.any():
                Terrain._build_field_layer(
                    surf, region, style, seed=self.noise_params.seed
                )
        for biome, style in BIOME_HATCHES.items():
            Terrain._blit_ink(
                surf,
                Terrain.hatch(
                    biomes == biome.value,
                    angle=style.angle,
                    line_spacing=int(style.line_spacing),
                    thickness=style.thickness,
                    wobble_amp=style.wobble_amp,
                ),
                style.colour,
            )
        for biome, style in BIOME_CONTOURS.items():
            Terrain._blit_ink(
                surf,
                Terrain.contour(
                    biomes == biome.value,
                    thickness=style.thickness,
                    align=style.align,
                    soft=True,
                    offset=style.offset,
                ),
                style.colour,
            )
        for biome, style in BIOME_GLYPHS.items():
            coords = Terrain.to_render_coords(
                self.glyph_coords[biome], self.biome_mat.shape, out_size
            )
            Terrain._stamp_glyphs(
                surf,
                coords,
                style.paths,
                glyph_size=style.size,
                knockout_glyphs=style.knockout,
                knockout_background_color=style.knockout_colour,
                knockout_fill=style.knockout_fill,
                knockout_variants=style.knockout_variants,
                knockout_spread=style.knockout_spread,
            )
        rgb = p.surfarray.array3d(surf)
        alpha = p.surfarray.array_alpha(surf)
        rgba = np.dstack([rgb, alpha])

        # TODO this thing seems very unoptimized, we pass through pygame surfaces, and then copy everything to a matrix, which will then be rendered to a pygame surface

        return np.transpose(rgba, (1, 0, 2))

    @staticmethod
    def voronoi_fields(
        shape: tuple[int, int], cell_size: float, jitter: float = 0.6, seed: int = 0
    ) -> tuple[np.ndarray, np.ndarray]:
        """Jittered-grid Voronoi (Worley/cellular noise) over an (H, W) pixel
        grid -> (labels, gap).

        `labels` is which parcel each pixel belongs to -- the id of its nearest
        seed. `gap` is F2 - F1, the difference between the distances to the two
        nearest seeds: it is 0 exactly on a parcel boundary and grows inward, and
        half of it is (to first order) the distance to that boundary. That's what
        gives the boundaries for free, as an antialiasable distance rather than a
        separate contour pass over the labels.

        One seed per `cell_size` grid cell, displaced within its cell by
        `jitter`. Keeping seeds on a lattice is both what makes this cheap and
        what makes it look farmed: parcels come out with comparable areas, where
        uniformly random seeds give slivers next to huge lots.

        Cost is a fixed number of passes over the image no matter how many
        parcels there are, because only cells near a pixel's own can hold its
        nearest seed. How near depends on the jitter, and the bound is worth
        writing down since it decides the cost. With cell side c and jitter j, a
        pixel is at most 0.707*c*(1+j) from its own cell's seed (opposite corners
        of the jitter box), while the nearest a seed two cells away can be is
        c*(1.5 - j/2). The 3x3 window is therefore provably sufficient while
        0.707*(1+j) < 1.5 - j/2, i.e. j < 0.657. Past that a 5x5 window is
        needed -- 25 passes instead of 9 -- which is why `jitter` defaults just
        under the threshold. Cheating it (as most Worley implementations do, by
        always using 3x3) misplaces the occasional boundary segment.

        Evaluated at whatever resolution it's asked for, so like every other
        image in this file it's built AT render size rather than upscaled.
        """
        rows, cols = shape
        radius = 1 if jitter <= 0.657 else 2

        # The seed lattice is padded by `radius` cells on every side, so a pixel
        # in a border cell can look `radius` cells outward without the index
        # being clamped. Clamping would make one seed appear twice in the same
        # comparison, F2 would tie with F1, and the resulting zero `gap` would
        # ink a spurious parcel boundary along all four edges of the map.
        n_rows = int(np.ceil(rows / cell_size)) + 2 * radius
        n_cols = int(np.ceil(cols / cell_size)) + 2 * radius
        rng = np.random.default_rng((seed, int(cell_size * 1000)))
        offsets = (rng.random((n_rows, n_cols, 2)) - 0.5) * (jitter * cell_size)
        gi, gj = np.mgrid[0:n_rows, 0:n_cols] - radius
        seed_y = ((gi + 0.5) * cell_size + offsets[:, :, 0]).astype(np.float32)
        seed_x = ((gj + 0.5) * cell_size + offsets[:, :, 1]).astype(np.float32)

        y = np.arange(rows, dtype=np.float32)[:, None]
        x = np.arange(cols, dtype=np.float32)[None, :]
        cell_row = (y // cell_size).astype(np.int32)  # (rows, 1)
        cell_col = (x // cell_size).astype(np.int32)  # (1, cols)

        f1 = np.full(shape, np.inf, dtype=np.float32)
        f2 = np.full(shape, np.inf, dtype=np.float32)
        labels = np.zeros(shape, dtype=np.int32)
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                # +radius converts a lattice index to an index into the padded
                # arrays. The two operands broadcast (rows,1) x (1,cols), so
                # each of these is one full-image gather.
                ii = cell_row + di + radius
                jj = cell_col + dj + radius
                d = np.hypot(seed_y[ii, jj] - y, seed_x[ii, jj] - x)
                closer = d < f1
                # Order matters: the old F1 becomes the candidate for F2 before
                # F1 itself is overwritten.
                f2 = np.where(closer, f1, np.minimum(f2, d))
                labels = np.where(closer, (ii * n_cols + jj).astype(np.int32), labels)
                f1 = np.where(closer, d, f1)
        return labels, f2 - f1

    @staticmethod
    def _build_field_layer(
        surf: p.Surface, region: np.ndarray, style: FieldStyle, seed: int = 0
    ) -> None:
        """Cut `region` (a bool mask, at the resolution of `surf`) into parcels
        and ink them onto `surf` in place -- furrows first, then the boundaries
        over them, same painter's order as the rest of the ink layer.

        Which parcels are cropped, and which way their furrows run, is drawn
        once per parcel id from a seeded generator, so a re-render at the same
        size lays down the same fields rather than re-rolling the whole county.
        """
        labels, gap = Terrain.voronoi_fields(
            region.shape, style.cell_size, style.jitter, seed
        )

        # One draw per parcel id, then indexed by the label image -- a lookup
        # table, so the per-pixel work stays vectorized.
        rng = np.random.default_rng((seed, 0xF1E1D))
        n_parcels = int(labels.max()) + 1
        parcel_angle = rng.integers(0, len(style.angles), n_parcels)
        parcel_cropped = rng.random(n_parcels) < style.crop_fraction

        # Drop the parcels that barely clip the region (see FieldStyle
        # .min_coverage). bincount over the labels of the region's pixels is
        # the parcel areas in one pass, no per-parcel masking.
        area = np.bincount(labels[region], minlength=n_parcels)
        region = region & (area >= style.min_coverage * style.cell_size**2)[labels]

        cropped = region & parcel_cropped[labels]
        for k, angle in enumerate(style.angles):
            # hatch() masks its lines to what it's given, so restricting the
            # mask to this angle's parcels is all the clipping needed.
            Terrain._blit_ink(
                surf,
                Terrain.hatch(
                    cropped & (parcel_angle[labels] == k),
                    angle=angle,
                    line_spacing=style.hatch_spacing,
                    thickness=style.hatch_thickness,
                ),
                style.hatch_colour,
            )

        # gap/2 is the distance to the boundary, so a line `edge_thickness` wide
        # centred on it covers |gap/2| <= edge_thickness/2; the +0.5 is the same
        # one-pixel analytic antialiasing `contour` uses.
        edge = np.clip(0.5 * (style.edge_thickness - gap) + 0.5, 0.0, 1.0)
        Terrain._blit_ink(surf, edge * region, style.edge_colour)

    @staticmethod
    def hatch(
        mask: np.ndarray,
        angle: float,
        line_spacing: float = 4.0,
        thickness: float = 1.2,
        wobble_amp: float = 0.0,
    ) -> np.ndarray:
        """Parallel hatch-line mask at `angle` degrees, masked to `mask`. Lines
        `line_spacing` px apart, `thickness` px wide. `wobble_amp` > 0 jitters
        the lines for a hand-drawn feel (uses pnoise2 -- pnoise1 only takes a
        single scalar coordinate, not per-pixel x/y arrays, so it can't drive a
        2D wobble field directly).

        :return: a zero matrix with ones in places where you should draw the pixels"""
        rows, cols = mask.shape
        # Two 1-D profiles rather than two full coordinate grids: the projection
        # is separable (x*cos + y*sin), so only the sum needs to be (H, W).
        # Same output, one materialized array instead of three -- the same trick
        # border_fade uses, and it matters here because BIOME_FIELDS runs this
        # once per furrow direction over the whole render-size canvas.
        y = np.arange(rows)[:, None]
        x = np.arange(cols)[None, :]
        a = np.radians(angle)
        coord = x * np.cos(a) + y * np.sin(a)
        if wobble_amp:
            wobble = np.vectorize(lambda xi, yi: noise.pnoise2(xi * 0.05, yi * 0.05))(
                x, y
            )
            coord = coord + wobble * wobble_amp
        hatch = (coord % line_spacing) < thickness
        return hatch & (mask > 0)

    @staticmethod
    def contour(
        mask: np.ndarray,
        thickness: float = 1.0,
        align: str = "inner",
        soft: bool = False,
        offset: float = 0.0,
    ) -> np.ndarray:
        """
        Like hatch, returns a matrix contouring the mask -- the outline of every
        region in it (holes included), as a band `thickness` px wide.

        Built from a signed distance field rather than morphology. The EDT of a
        mask gives, per pixel, the distance to the nearest pixel of the opposite
        class, so subtracting the two sides gives a field that is negative
        inside the region, positive outside, and crosses zero exactly on the
        boundary -- thresholding it then yields a band. A dilation/erosion pair
        would be the other way to do this, but it can only step in whole pixels
        and its structuring element leaks its own square/diamond shape into
        diagonal edges; the distance field is isotropic and takes a real-valued
        thickness, which also matches how `hatch` takes one.

        :param thickness: line thickness, in pixels OF `mask` -- so run this on
            a render-resolution mask, not the data-space one, or the line gets
            upscaled and goes soft (see the class docstring).
        :param align: which side of the boundary the band sits on. "inner"
            (default) keeps it inside the region, so two adjacent biomes each
            keep their own line instead of both inking the same pixels;
            "outer" keeps it outside; "center" straddles the boundary.
        :param soft: False (default) returns a bool matrix, True where you
            should draw the contour pixels -- same contract as `hatch`, usable
            directly as a boolean index. True instead returns float coverage in
            [0,1]: the band edges are antialiased and `thickness` becomes
            genuinely fractional, which is what you want when the line is going
            to be drawn as ink rather than used as a mask.
        :param offset: slide the whole band across the boundary, in pixels of
            `mask`. NEGATIVE moves it into the region, positive out of it. This
            is the fine adjustment `align` is too coarse for: a shoreline drawn
            "outer" sits entirely on the land side, and nudging it a pixel or
            two into the water reads better without going all the way to
            "center". Costs one extra distance transform when non-zero (see
            below), so leave it at 0 unless you want the nudge.
        :return: bool matrix, or float coverage if `soft`

        Note a region running off the edge of the array gets no contour along
        that edge -- there's no "outside" out there to measure a distance to.
        For a map that's usually what you want (no box drawn around the image).
        """
        inside = mask > 0

        # Every alignment is the same thing -- a signed-distance interval --
        # so they only differ in where that interval sits relative to zero.
        bands = {
            "inner": (-thickness, 0.0),
            "outer": (0.0, thickness),
            "center": (-thickness / 2.0, thickness / 2.0),
        }
        if align not in bands:
            raise ValueError(
                f"contour: align must be one of {sorted(bands)}, got {align!r}"
            )
        lo, hi = bands[align]
        lo, hi = lo + offset, hi + offset

        # The EDT gives distance to the nearest pixel of the OTHER class: >= 1
        # on its own side, 0 on the other. The half-pixel shift recentres it on
        # the interface itself, which runs half a pixel outside the region's
        # last pixel rather than through that pixel's centre.
        #
        # A one-sided band only needs ONE transform: for "outer", pixels inside
        # the region fall out at -0.5 (their outside-distance is 0), already
        # below the band, and "inner" is the mirror image. The EDT is the whole
        # cost of this function, so that halves the common case.
        #
        # That shortcut relies on the band staying on one side of zero, which
        # an `offset` is exactly the thing that breaks -- shift an "outer" band
        # inward and those -0.5 pixels are suddenly inside it, so every pixel
        # of the region would ink. With an offset, pay for both transforms.
        if offset:
            signed = np.where(inside, 0.5 - _edt(inside), _edt(~inside) - 0.5)
        elif align == "outer":
            signed = _edt(~inside) - 0.5
        elif align == "inner":
            signed = 0.5 - _edt(inside)
        else:
            signed = np.where(inside, 0.5 - _edt(inside), _edt(~inside) - 0.5)
        if not soft:
            # `signed` is never exactly 0 (the nearest pixel centre to the
            # interface is half a pixel off it), so the closed interval can't
            # pick up the boundary twice for two adjacent regions.
            return (signed >= lo) & (signed <= hi)
        # Distance from the nearest band edge, in pixels, +0.5 so a pixel
        # centred exactly on an edge comes out half covered -- standard
        # one-pixel analytic antialiasing.
        return np.clip(np.minimum(signed - lo, hi - signed) + 0.5, 0.0, 1.0)

    @staticmethod
    def compute_shadows(
        height_map: np.ndarray,
        sun_params: SunParams,
        shadow_falloff: float | None = None,
    ) -> np.ndarray:
        """
        Returns bool mask, True = in cast shadow.

        :param shadow_falloff: how fast the ray falls per column, normalized to the same [0,1] scale as height values; bigger -> shorter shadows, smaller -> longer shadows. defaults to 1/width so a 45 degree sun only drops the ray by the map's full height range after crossing its ENTIRE width, not after 1 column
        """
        from scipy.ndimage import rotate

        a = sun_params.azimuth - 270.0  # rotate so light travels along +x
        Hr = rotate(
            height_map, a, reshape=True, order=1, mode="constant", cval=height_map.min()
        )

        if shadow_falloff is None:
            shadow_falloff = 1.0 / Hr.shape[1]  # type: ignore
        drop = np.tan(np.radians(sun_params.elevation)) * shadow_falloff
        shadow_r = _sweep(Hr, drop)

        back = rotate(
            shadow_r.astype(np.float32),
            -a,
            reshape=True,
            order=1,
            mode="constant",
            cval=0.0,
        )
        oy, ox = height_map.shape
        y0 = (back.shape[0] - oy) // 2
        x0 = (back.shape[1] - ox) // 2  # type: ignore
        return back[y0 : y0 + oy, x0 : x0 + ox] > 0.5

    @staticmethod
    def compute_shadow_accumulation(
        height_map: np.ndarray,
        sun_params: SunParams,
        num_samples: int = 16,
        max_elevation: float = 60.0,
        azimuth_range: tuple[float, float] = (60.0, 300.0),
    ) -> np.ndarray:
        """Sweeps a simplified day (elevation rises/falls like a sine arc, azimuth
        sweeps linearly across azimuth_range) and returns, per cell, the FRACTION
        of that sampled day spent in cast shadow -- how perpetually gloomy a spot
        is, as opposed to compute_shadows' single instant. Not real solar geometry,
        just enough spread to find valleys shadowed from many directions across
        the day. Midpoint sampling keeps elevation off exactly 0, where drop -> 0
        would make compute_shadows degenerate (everything but a running peak reads
        as shadowed).

        `num_samples` is the whole cost of building the terrain's fields -- each
        sample is a full compute_shadows, i.e. two scipy rotations of the entire
        height map. 16 was 32: this feeds nothing but a temperature nudge
        (SunParams.accumulated_shadow_temp_loss), which then gets a sigma=1.5
        gaussian blur in _build_temp_map anyway, so the extra angular resolution
        was being smoothed away before it reached a biome boundary."""
        accumulator = np.zeros(height_map.shape, dtype=np.float64)
        azimuth_start, azimuth_end = azimuth_range
        for i in range(num_samples):
            t = (i + 0.5) / num_samples
            sample_params = SunParams(
                elevation=max_elevation * np.sin(np.pi * t),
                azimuth=azimuth_start + t * (azimuth_end - azimuth_start),
            )
            accumulator += Terrain.compute_shadows(
                height_map, sample_params, sun_params.shadow_falloff
            )
        return accumulator / num_samples

    def change_mode(self, new_mode: TerrainMode):
        """Switch which map is drawn. Baking the new mode here rather than
        letting render() discover it means the cost (a second or so the first
        time, nothing after) lands on the click that asked for it, not on a
        frame that was supposed to be 16ms."""
        self.mode = new_mode
        self.surface_for(new_mode)

    def render(self, surf: p.Surface):
        # surface_for, not self.surfaces[...]: change_mode normally has it
        # baked already, but this keeps a directly-assigned .mode working too.
        surf.blit(self.surface_for(self.mode), self.bounding_rect)


def _edt(mask: np.ndarray) -> np.ndarray:
    """Euclidean distance transform: per cell, the distance to the nearest
    zero cell.

    Wrapped only to pin the return type. scipy declares
    distance_transform_edt as returning `ndarray | tuple[ndarray, ...] | None`,
    because `return_indices=True` makes it a tuple and `return_distances=False`
    makes it None -- so at every call site a type checker sees an operand that
    might be a tuple or None and flags the arithmetic. With the defaults it is
    always a single array, and saying so once here beats casting five times."""
    from scipy.ndimage import distance_transform_edt

    return cast(np.ndarray, distance_transform_edt(mask))


def _sweep(H: np.ndarray, drop: float) -> np.ndarray:
    """Light travels left->right (+x). True = in shadow. O(rows*cols)."""
    shadow = np.empty(H.shape, dtype=bool)
    horizon = np.full(H.shape[0], -np.inf)  # one 'depth buffer' value per row
    for x in range(H.shape[1]):  # python loop over cols only;
        horizon -= drop  # each step vectorized over rows
        col = H[:, x]
        shadow[:, x] = col < horizon
        np.maximum(horizon, col, out=horizon)
    return shadow


def as_image_array(matrix: np.ndarray) -> np.ndarray:
    """Normalise the raw [-1, 1]-ish noise to a 0..255 uint8 greyscale array
    that PIL/pygame can actually display. Without this the near-zero float
    values render as solid black."""
    m = matrix
    lo, hi = m.min(), m.max()
    if hi - lo < 1e-9:  # flat matrix -> avoid divide by zero
        return np.zeros(matrix.shape, dtype=np.uint8)
    norm = (m - lo) / (hi - lo)  # -> [0, 1]
    return (norm * 255).astype(np.uint8)


def _rgba_to_surf(rgba: np.ndarray) -> p.Surface:
    # rgba is (row, col, 4); array_to_surface wants (x=col, y=row), so swap
    # the first two axes to avoid a transposed image. SRCALPHA so a non-opaque
    # alpha channel (e.g. a glyph-only composite) actually renders as see-through
    # instead of the surface's own default-opaque alpha overriding it.
    surf = p.Surface((rgba.shape[1], rgba.shape[0]), p.SRCALPHA)
    Terrain.to_pygame_surf(rgba, surf)
    return surf
