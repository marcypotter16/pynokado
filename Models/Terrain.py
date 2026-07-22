# I want to generate terrain with perlin noise.

from dataclasses import dataclass
from enum import Enum
import math
import random as pyrandom

import noise
import numpy as np
from numpy import random
import pygame as p

from Utils.Image import knockout

class TerrainMode(Enum):
    HEIGHTMAP = 0
    TEMPMAP = 1
    BIOMESMAP = 2
    SHADOWMAP = 3
    GLYPHMAP = 4
    COLOURMAP = 5

class MoistureLevels(Enum):
    DRY = 0
    NORMAL = 1
    WET = 2

class TemperatureLevels(Enum):
    COLD = 0
    TEMPERATE = 1
    HOT = 2

class Biome(Enum):
    SEASIDE = 0
    PLAIN = 1
    RAINFOREST = 2
    MOUNTAIN = 3
    SNOW = 4
    CAVE = 5
    TUNDRA = 6
    TAIGA = 7
    DESERT = 8
    SAVANNAH = 9

MOISTURE_THRESHOLDS: dict[tuple[float, float], MoistureLevels] = {
    (0.0, 0.2): MoistureLevels.DRY,
    (0.2, 0.8): MoistureLevels.NORMAL,
    (0.8, 1.0): MoistureLevels.WET
}

# Operates on Terrain.normalize(temp_map), NOT raw degrees -- min_temperature is
# re-rolled per terrain instance (random.randint(-40, -20)), so a fixed degree
# cutoff would drift terrain-to-terrain. Normalizing keeps COLD/TEMPERATE/HOT
# relative to THIS map's own range, same treatment as MOISTURE_THRESHOLDS.
TEMPERATURE_THRESHOLDS: dict[tuple[float, float], TemperatureLevels] = {
    (0.0, 0.35): TemperatureLevels.COLD,
    (0.35, 0.65): TemperatureLevels.TEMPERATE,
    (0.65, 1.0): TemperatureLevels.HOT,
}

BIOME_THRESHOLDS: dict[tuple[float, float], Biome] = {
    (0.0, 0.1): Biome.SEASIDE,
    (0.1, 0.5): Biome.PLAIN,
    (0.5, 0.65): Biome.RAINFOREST,
    # TEMP: widened for glyph testing (more mountain, snow kept minimal).
    (0.65, 0.95): Biome.MOUNTAIN,
    (0.95, 1.0): Biome.SNOW,
    # we will think about CAVE later
}

BIOME_THRESHOLDS_REV: dict[Biome, tuple[float, float]] = dict((v, k) for k, v in BIOME_THRESHOLDS.items())

# Simplified Whittaker biome diagram: (temperature, moisture) -> biome, for
# everything that ISN'T gated purely by elevation (get_biome_from_val still
# special-cases SEASIDE/MOUNTAIN/SNOW by height first -- those are about being
# underwater/at altitude, not climate). Some biomes cover more than one cell,
# same as a real Whittaker diagram's biomes bleeding across several bands.
WHITTAKER_TABLE: dict[tuple[TemperatureLevels, MoistureLevels], Biome] = {
    (TemperatureLevels.COLD, MoistureLevels.DRY):         Biome.TUNDRA,
    (TemperatureLevels.COLD, MoistureLevels.NORMAL):      Biome.TAIGA,
    (TemperatureLevels.COLD, MoistureLevels.WET):         Biome.TAIGA,
    (TemperatureLevels.TEMPERATE, MoistureLevels.DRY):    Biome.PLAIN,
    (TemperatureLevels.TEMPERATE, MoistureLevels.NORMAL): Biome.PLAIN,
    (TemperatureLevels.TEMPERATE, MoistureLevels.WET):    Biome.RAINFOREST,
    (TemperatureLevels.HOT, MoistureLevels.DRY):          Biome.DESERT,
    (TemperatureLevels.HOT, MoistureLevels.NORMAL):       Biome.SAVANNAH,
    (TemperatureLevels.HOT, MoistureLevels.WET):          Biome.RAINFOREST,
}

# Faint wash colours, one per biome, drawn UNDER the ink strokes. Tuned to read
# on the warm sepia parchment (~(226,208,176)): mostly desaturated and a shade
# darker/cooler than the paper, so each biome is a distinguishable stain without
# fighting the ink aesthetic. SEASIDE is the lone cool hue so water pops; PLAIN
# sits nearest the paper (the "empty" default); CAVE is darkest.
BIOME_TINTS: dict[Biome, p.Color] = {
    Biome.SEASIDE: p.Color(126, 164, 178, 255),   # dusty blue-teal (water)
    Biome.PLAIN: p.Color(214, 196, 150, 255),     # pale warm straw (near paper)
    Biome.RAINFOREST: p.Color(122, 148, 108, 255),    # muted sage/olive
    Biome.MOUNTAIN: p.Color(158, 148, 152, 255),  # cool stone grey-mauve
    Biome.SNOW: p.Color(232, 234, 240, 255),
    Biome.CAVE: p.Color(86, 84, 104, 255),        # deep indigo-charcoal (shadow)
    Biome.TUNDRA: p.Color(176, 176, 168, 255),    # pale frost-grey lichen
    Biome.TAIGA: p.Color(88, 118, 100, 255),      # deep boreal spruce-green
    Biome.DESERT: p.Color(216, 178, 120, 255),    # warm sand/ochre
    Biome.SAVANNAH: p.Color(198, 178, 96, 255),   # dry golden grassland
}

# Per-biome glyph sprite sets for GLYPHMAP compositing. Only biomes with actual
# art go here -- _build_glyph_map only stamps the biomes present as keys, so
# everything else just shows its flat BIOME_TINTS wash until more art exists.
BIOME_GLYPH_PATHS: dict[Biome, list[str]] = {
    Biome.RAINFOREST: [
        "Assets/sprites/glyphs/forest/tree1.png",
        "Assets/sprites/glyphs/forest/tree2.png",
    ],
    Biome.MOUNTAIN: [
        "Assets/sprites/glyphs/mountain/mountain1_og.png",
        "Assets/sprites/glyphs/mountain/mountain2_og.png",
        "Assets/sprites/glyphs/mountain/mountain3_og.png",
    ],
}

@dataclass
class NoiseParams:
    size:           tuple[int, int]
    scale:          float = 200.0
    octaves:        int = 4
    persistence:    float = 0.5
    lacunarity:     float = 1.8
    seed:           int = 0

@dataclass
class SunParams:
    elevation:  float = 45.0
    azimuth:    float = 315.0
    solar_max_temp_gain: float = 8.0
    shadow_max_temp_loss: float = 3.0
    # how fast the shadow-casting ray falls per column: bigger -> shorter shadows, smaller -> longer shadows.
    # 0.005 is a good default found by eye in scratch/temp_shadow_debug.py; None -> compute_shadows picks 1/width instead.
    shadow_falloff: float | None = 0.005
    # extra cooling for cells shadowed most of the DAY (see shadow_accumulation_map), separate from
    # shadow_max_temp_loss which only reacts to the current instant's shadow. Models valleys hemmed in
    # by mountains staying cold even when the current moment's sun happens to reach them directly.
    accumulated_shadow_temp_loss: float = 6.0

class Terrain:
    def __init__(self, height_noise_params: NoiseParams, moisture_noise_params: NoiseParams, sun_params: SunParams, bounding_rect: p.Rect, max_height: float = 4000.0, sea_level_temperature: float = 20.0):
        self.max_height = max_height
        self.sea_level_temperature = sea_level_temperature
        self.min_temperature = random.randint(-40, -20)
        self.noise_params = height_noise_params
        self.moisture_params = moisture_noise_params
        self.sun_params = sun_params
        self.maps: dict[TerrainMode, np.ndarray] = {}
        self.height_map = np.zeros(height_noise_params.size)
        self.colour_map = np.zeros((height_noise_params.size[0], height_noise_params.size[1], 3)) # rgb
        self.temp_map = np.zeros_like(self.height_map)
        self.height_map = Terrain.generate_height_map(height_noise_params)
        self.height_map_grad = np.gradient(self.height_map)
        self.shadow_map = Terrain.compute_shadows(self.height_map, self.sun_params, self.sun_params.shadow_falloff)
        self.shadow_accumulation_map = Terrain.compute_shadow_accumulation(self.height_map, self.sun_params)
        self.moisture_map = Terrain.generate_height_map(moisture_noise_params)
        self._build_maps()

        # Game interface
        self.bounding_rect = bounding_rect
        self.mode: TerrainMode = TerrainMode.GLYPHMAP
        self.surfaces: dict[TerrainMode, p.Surface]
        self._build_surfaces()

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
    def _level_from_thresholds(val: float, thresholds: dict[tuple[float, float], Enum]) -> Enum:
        # value is normalized to [0, 1], so clamp defensively and pick the last
        # band whose lower bound the value clears (bands are contiguous, ascending).
        val = min(max(float(val), 0.0), 1.0)
        level = next(iter(thresholds.values()))
        for (lo, _hi), lvl in thresholds.items():
            if val >= lo:
                level = lvl
        return level

    def get_biome_from_val(self, height_val: float, moisture_val: float, temperature_val: float) -> Biome:
        """height_val/moisture_val are height_map/moisture_map values (already
        [0,1]-normalized); temperature_val must be Terrain.normalize(temp_map)
        at that same cell -- temp_map itself is in real degrees and its range
        shifts terrain-to-terrain with the randomized min_temperature.

        Elevation still gates the biomes that aren't about climate -- coastline,
        peaks and snowcaps are about being underwater/at altitude, not about
        temperature/moisture. Everything in between is a Whittaker-style lookup:
        temperature x moisture -> biome (see WHITTAKER_TABLE)."""
        height_val = min(max(float(height_val), 0.0), 1.0)
        if height_val < BIOME_THRESHOLDS_REV[Biome.SEASIDE][1]:
            return Biome.SEASIDE
        if height_val >= BIOME_THRESHOLDS_REV[Biome.SNOW][0]:
            return Biome.SNOW
        if height_val >= BIOME_THRESHOLDS_REV[Biome.MOUNTAIN][0]:
            return Biome.MOUNTAIN

        moisture_level = Terrain._level_from_thresholds(moisture_val, MOISTURE_THRESHOLDS) # type: ignore
        temperature_level = Terrain._level_from_thresholds(temperature_val, TEMPERATURE_THRESHOLDS) # type: ignore
        return WHITTAKER_TABLE[(temperature_level, moisture_level)] # type: ignore

    @staticmethod
    def generate_height_map(noise_params: NoiseParams) -> np.ndarray:
        heightmap = np.zeros(noise_params.size)
        for i in range(noise_params.size[0]):
            for j in range(noise_params.size[1]):
                heightmap[i][j] = noise.pnoise2(
                    i / noise_params.scale,
                    j / noise_params.scale,
                    octaves=noise_params.octaves,
                    persistence=noise_params.persistence,
                    lacunarity=noise_params.lacunarity,
                    repeatx=noise_params.size[0],
                    repeaty=noise_params.size[1],
                    base=noise_params.seed,
                )
        heightmap = Terrain.normalize(heightmap)
        return heightmap
    
    def _build_temp_map(self):
        if self.height_map is None:
            raise NotImplementedError("trying to build temp map over None height map")
        sea_level = BIOME_THRESHOLDS_REV[Biome.SEASIDE][1]

        self.temp_map = np.interp(self.height_map, [sea_level, 1.0], [self.sea_level_temperature, self.min_temperature])
        # self.temp_map[self.temp_map > self.sea_level_temperature] = self.sea_level_temperature
        # last line commented out because numpy automatically clamps output between sea level temperature and min temperature

        # now adjust based on illumination: if sun ray is hitting perpendicular then hotter
        not_in_shadow = 1 - self.shadow_map
        gy, gx = self.height_map_grad            # each is (H, W), per-cell ∂h/∂y and ∂h/∂x
        theta, phi = np.radians(self.sun_params.elevation), np.radians(self.sun_params.azimuth)
        Lx = np.cos(theta) * np.cos(phi)
        Ly = np.cos(theta) * np.sin(phi)
        Lz = np.sin(theta)

        NdotL = (-gx*Lx - gy*Ly + Lz) / np.sqrt(gx**2 + gy**2 + 1.0)
        illum = np.clip(NdotL, 0.0, None)

        self.temp_map += self.sun_params.solar_max_temp_gain * illum * not_in_shadow
        self.temp_map -= self.sun_params.shadow_max_temp_loss * self.shadow_map
        # persistent "valley coldness": cells shadowed most of the day stay cold even at
        # moments (like right now) when the sun happens to be hitting them directly.
        self.temp_map -= self.sun_params.accumulated_shadow_temp_loss * self.shadow_accumulation_map

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
        """Classify every cell exactly once (height + moisture + temperature ->
        biome via the Whittaker lookup in get_biome_from_val) and cache it as
        Biome.value integer codes. Everything downstream that used to re-derive
        "which cells are biome X" from height_map alone (colour_mat, glyph
        placement via get_biome_mask, get_biome_at_coords) reads this instead,
        so they can never disagree with each other again."""
        self.biome_mat = np.vectorize(lambda h, m, t: self.get_biome_from_val(h, m, t).value)(
            self.height_map, self.moisture_map, self.temp_map_normalized
        ).astype(np.uint8)

    def _build_colour_map(self):
        """Bake an (H, W, 4) uint8 RGBA image of the biome map: biome_mat ->
        BIOME_TINTS colour. Useful for previewing the terrain; the board itself
        samples biomes per-node via get_biome_at_coords."""
        rows, cols = self.height_map.shape
        self.colour_map = np.zeros((rows, cols, 4), dtype=np.uint8)
        for biome, colour in BIOME_TINTS.items():
            rgba = (colour.r, colour.g, colour.b, colour.a)
            self.colour_map[self.biome_mat == biome.value] = rgba

    def _build_maps(self):
        """Run the height/moisture-derived map builders in the order they
        depend on each other, then bake every TerrainMode's (H, W, 4) uint8
        RGBA image into self.maps so _build_surfaces can blit each one directly
        via Terrain.to_pygame_surf without any per-mode branching. RGBA
        everywhere, even where alpha is always opaque, so every map in this
        dict shares one shape."""
        self._build_temp_map()   # must run first: _build_biome_map's Whittaker lookup needs temp_map_normalized
        self._build_biome_map()
        self._build_colour_map()

        self.maps[TerrainMode.HEIGHTMAP] = Terrain.apply_palette(self.height_map, Terrain.ELEVATION_PALETTE)
        self.maps[TerrainMode.TEMPMAP] = Terrain.apply_palette(Terrain.normalize(self.temp_map), Terrain.TEMPERATURE_PALETTE)
        self.maps[TerrainMode.BIOMESMAP] = self.colour_map
        self.maps[TerrainMode.SHADOWMAP] = Terrain._grey_to_rgba(self.shadow_map)
        self.maps[TerrainMode.GLYPHMAP] = self._build_glyph_map()
        self.maps[TerrainMode.COLOURMAP] = self.colour_map

    def _build_surfaces(self):
        self.surfaces: dict[TerrainMode, p.Surface] = {}
        for terrain_mode in TerrainMode:
            surf = p.Surface(self.noise_params.size, p.SRCALPHA)
            Terrain.to_pygame_surf(self.maps[terrain_mode], surf)
            surf = p.transform.smoothscale(surf, self.bounding_rect.size)
            self.surfaces[terrain_mode] = surf

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
    def apply_palette(mat: np.ndarray, palette: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
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
        (0.00, (18, 42, 110)),    # deep water
        (0.10, (46, 100, 176)),   # shallow water
        (0.12, (210, 200, 150)),  # shoreline
        (0.35, (96, 156, 72)),    # lowland green
        (0.65, (176, 148, 84)),   # highland brown
        (0.85, (150, 90, 70)),    # mountain red-brown
        (1.00, (214, 60, 50)),    # peak red
    ]

    # Classic thermal ramp: cold blue -> temperate green -> hot red. Meant for
    # temp_map (which is NOT [0,1]-normalized, unlike height_map) -- normalize
    # it first, e.g. via `Terrain.normalize(t.temp_map)`.
    TEMPERATURE_PALETTE: list[tuple[float, tuple[int, int, int]]] = [
        (0.00, (30, 60, 170)),    # coldest (mountaintop)
        (0.35, (90, 160, 200)),   # cool
        (0.55, (150, 200, 120)),  # temperate
        (0.75, (230, 190, 70)),   # warm
        (1.00, (210, 50, 40)),    # hottest (sea level)
    ]

    @staticmethod
    def to_pygame_surf(mat: np.ndarray, surf: p.Surface,
                        palette: list[tuple[float, tuple[int, int, int]]] | None = None, size: tuple | None = None) -> None:
        """Blit a matrix onto `surf`. Two shapes are accepted:
        - (H, W): a [0,1]-normalized scalar matrix, with no colour baked in
          yet. With no palette this is plain greyscale; pass a palette (see
          `ELEVATION_PALETTE`) to colour-map it instead. Either way this path
          produces fully opaque pixels.
        - (H, W, 4): an already-RGBA image (e.g. colour_map, apply_palette's
          own output, or a glyph composite) -- blitted as-is, `palette` is
          ignored. This is the shape every self.maps entry uses.
        Important: the size of the surface must exactly match the number of
        rows and cols of the matrix."""
        if surf.get_size() != (mat.shape[0], mat.shape[1]):
            raise ValueError(f"Error: trying to blit_array a matrix of shape {mat.shape} onto a surface of size {surf.get_size()}")
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
    def build_inked_mat(mat: np.ndarray, ink_colour: tuple[int, int, int, int], ink_width: float = 0.02) -> np.ndarray:
        """Build coloured matrix with INK colour between areas"""
        out = np.zeros((mat.shape[0], mat.shape[1], 4), dtype=np.uint8)
        rows, cols = mat.shape
        for i in range(rows):
            for j in range(cols):
                for interval, biome in BIOME_THRESHOLDS.items():
                    val = mat[i,j]
                    if interval[1] - ink_width * .5 <= val <= interval[1] + ink_width * .5:
                        # then it's the contour
                        out[i,j] = ink_colour
                        break
                    elif interval[0] <= val <= interval[1]:
                        out[i,j] = BIOME_TINTS[biome]
                        break
        return out
    
    @staticmethod
    def compute_glyph_points_mat(mask: np.ndarray, spacing: int = 5) -> np.ndarray:
        """This function takes in a mask representing a set of points, then gives back a mask representing where to spawn the glyphs inside that area (out_mask is all 0 except 1 where you gotta spawn them, use np.argwhere(out_mask) to get coordinates)"""
        mask2 = np.zeros_like(mask)
        mask2[::spacing, ::spacing] = 1
        return mask * mask2
    
    @staticmethod
    def compute_glyph_points_mat_unif(mask: np.ndarray, spacing=10, how_many: int | None = 20,
                                       return_coords=True):
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
        grid_like path in _get_point_cloud_coords does."""
        mask_cp = mask.copy()
        accepted = []

        # precompute disk offsets
        r = int(np.ceil(spacing))
        di, dj = np.mgrid[-r:r+1, -r:r+1]
        disk = (di**2 + dj**2) < spacing**2
        di, dj = di[disk], dj[disk]

        # how_many=None -> uncapped; the mask-exhausted break below is then the
        # ONLY stop condition, so this samples the max points the spacing allows.
        while how_many is None or len(accepted) < how_many:
            coords = np.argwhere(mask_cp)
            if len(coords) == 0:
                # mask fully stamped out -- normal/expected exit when
                # how_many=None, and also the natural cap for a finite how_many
                # that asks for more points than the spacing constraint fits.
                break
            p = coords[np.random.randint(len(coords))]
            accepted.append(p)

            # stamp out the disk
            ii, jj = p[0] + di, p[1] + dj
            valid = (ii >= 0) & (ii < mask.shape[0]) & (jj >= 0) & (jj < mask.shape[1])
            mask_cp[ii[valid], jj[valid]] = 0

        if return_coords:
            return accepted
        sample = np.array(accepted)
        mask2 = np.zeros_like(mask)
        mask2[sample[:, 0], sample[:, 1]] = 1
        return mask2

    @staticmethod
    def get_biome_mask(biome_mat: np.ndarray, biome: Biome, separator_thickness: float = 0.0) -> np.ndarray:
        """{0,1} mask of every cell classified as `biome` in biome_mat (see
        Terrain._build_biome_mat -- the cached height+moisture+temperature
        Whittaker classification, NOT a height-only approximation, so this
        always agrees with colour_mat).

        `separator_thickness` erodes the mask inward (same [0,1]-normalized
        units the old height-band padding used, converted to a pixel radius via
        the mask's own resolution) so the mask stays clear of neighbouring
        biomes -- same idea as the ink gap in `build_inked_mat`: sample glyph
        points from the padded mask instead of the raw region, so glyphs from
        adjacent biomes can't overlap across the border."""
        mask = (biome_mat == biome.value).astype(np.float64)
        if separator_thickness > 0:
            from scipy.ndimage import binary_erosion
            radius_px = max(1, round(separator_thickness * 0.5 * biome_mat.shape[0]))
            mask = binary_erosion(mask.astype(bool), iterations=radius_px).astype(np.float64)
        return mask

    def get_point_cloud_coords(self, biome: Biome, spacing=18, grid_like=True,
                                how_many: int | None = 20, separator_thickness: float = 0.0):
        """Coordinates to spawn glyphs at, in PAINT ORDER (ascending row/y)."""
        biome_mask = Terrain.get_biome_mask(self.biome_mat, biome, separator_thickness=separator_thickness)
        if not grid_like:
            # keyword args here on purpose: compute_glyph_points_mat_unif's
            # signature is (mask, spacing, how_many, return_coords) -- a stray
            # positional call can silently send how_many into `spacing` and
            # True (=1) into `how_many`, so only ONE point ever comes back
            # regardless of the requested how_many.
            coords = Terrain.compute_glyph_points_mat_unif(
                biome_mask, spacing=spacing, how_many=how_many, return_coords=True)
        else:
            glyph_mask = Terrain.compute_glyph_points_mat(biome_mask, spacing=spacing)
            coords = np.argwhere(glyph_mask)
        return sorted(coords, key=lambda c: c[0])

    @staticmethod
    def _stamp_glyphs(surf: p.Surface, coords, glyph_paths: list[str], glyph_size: int, seed: int = 0,
                       max_rotation: float = 5.0, scale_range: tuple[float, float] = (0.8, 1.2),
                       knockout_glyphs: bool = False,
                       knockout_background_color=(255, 255, 255)) -> None:
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
            glyphs = [knockout(g, knockout_background_color) for g in glyphs]
        glyphs = [p.transform.smoothscale(g, (glyph_size, glyph_size)) for g in glyphs]

        rng = pyrandom.Random(seed)
        for row, col in coords:
            g = rng.choice(glyphs)
            angle = rng.uniform(-max_rotation, max_rotation)
            scale = rng.uniform(*scale_range)
            # rotozoom recomputes the surface's bounding box on rotation, so the
            # rect must come from the TRANSFORMED surface, not the original, or
            # the stamp drifts off its intended point once rotated.
            g_t = p.transform.rotozoom(g, angle, scale)
            surf.blit(g_t, g_t.get_rect(center=(int(col), int(row))))

    def _build_glyph_map(self) -> np.ndarray:
        """Every biome in BIOME_GLYPH_PATHS stamped onto a transparent canvas --
        glyphs only, no colour_map wash underneath (see TerrainMode.COLOURMAP
        for that). Returns an (H, W, 4) uint8 RGBA array; everywhere not
        covered by a glyph sprite stays alpha=0."""
        surf = p.Surface(self.noise_params.size, p.SRCALPHA)
        for biome, glyph_paths in BIOME_GLYPH_PATHS.items():
            coords = self.get_point_cloud_coords(biome, grid_like=False, how_many=None,
                                                  spacing=12, separator_thickness=0.02)
            Terrain._stamp_glyphs(surf, coords, glyph_paths, glyph_size=18)
        rgb = p.surfarray.array3d(surf)
        alpha = p.surfarray.array_alpha(surf)
        rgba = np.dstack([rgb, alpha])
        return np.transpose(rgba, (1, 0, 2))

    @staticmethod
    def hatch(mask: np.ndarray, angle: float, line_spacing=4, thickness=1.2,
              wobble_amp: float = 0.0) -> np.ndarray:
        """Parallel hatch-line mask at `angle` degrees, masked to `mask`. Lines
        `line_spacing` px apart, `thickness` px wide. `wobble_amp` > 0 jitters
        the lines for a hand-drawn feel (uses pnoise2 -- pnoise1 only takes a
        single scalar coordinate, not per-pixel x/y arrays, so it can't drive a
        2D wobble field directly)."""
        w, h = mask.shape
        y, x = np.mgrid[0:h, 0:w]
        a = np.radians(angle)
        coord = x * np.cos(a) + y * np.sin(a)
        if wobble_amp:
            wobble = np.vectorize(
                lambda xi, yi: noise.pnoise2(xi * 0.05, yi * 0.05)
            )(x, y)
            coord = coord + wobble * wobble_amp
        hatch = (coord % line_spacing) < thickness
        return hatch & (mask > 0)
    
    @staticmethod
    def compute_shadows(height_map: np.ndarray,
                        sun_params: SunParams,
                        shadow_falloff: float | None = None   # how fast the ray falls per column, normalized to the same [0,1] scale
                                                               # as height values; bigger -> shorter shadows, smaller -> longer shadows.
                                                               # defaults to 1/width so a 45 degree sun only drops the ray by the map's
                                                               # full height range after crossing its ENTIRE width, not after 1 column
                        ) -> np.ndarray:
        """Returns bool mask, True = in cast shadow."""
        from scipy.ndimage import rotate

        a = sun_params.azimuth - 270.0                      # rotate so light travels along +x
        Hr = rotate(height_map, a, reshape=True, order=1,
                    mode='constant', cval=height_map.min())

        if shadow_falloff is None:
            shadow_falloff = 1.0 / Hr.shape[1] # type: ignore
        drop = np.tan(np.radians(sun_params.elevation)) * shadow_falloff
        shadow_r = _sweep(Hr, drop)

        back = rotate(shadow_r.astype(np.float32), -a, reshape=True,
                    order=1, mode='constant', cval=0.0)
        oy, ox = height_map.shape
        y0 = (back.shape[0] - oy) // 2
        x0 = (back.shape[1] - ox) // 2 # type: ignore
        return back[y0:y0+oy, x0:x0+ox] > 0.5

    @staticmethod
    def compute_shadow_accumulation(height_map: np.ndarray,
                                    sun_params: SunParams,
                                    num_samples: int = 32,
                                    max_elevation: float = 60.0,
                                    azimuth_range: tuple[float, float] = (60.0, 300.0)
                                    ) -> np.ndarray:
        """Sweeps a simplified day (elevation rises/falls like a sine arc, azimuth
        sweeps linearly across azimuth_range) and returns, per cell, the FRACTION
        of that sampled day spent in cast shadow -- how perpetually gloomy a spot
        is, as opposed to compute_shadows' single instant. Not real solar geometry,
        just enough spread to find valleys shadowed from many directions across
        the day. Midpoint sampling keeps elevation off exactly 0, where drop -> 0
        would make compute_shadows degenerate (everything but a running peak reads
        as shadowed)."""
        accumulator = np.zeros(height_map.shape, dtype=np.float64)
        azimuth_start, azimuth_end = azimuth_range
        for i in range(num_samples):
            t = (i + 0.5) / num_samples
            sample_params = SunParams(
                elevation=max_elevation * np.sin(np.pi * t),
                azimuth=azimuth_start + t * (azimuth_end - azimuth_start),
            )
            accumulator += Terrain.compute_shadows(height_map, sample_params, sun_params.shadow_falloff)
        return accumulator / num_samples

    def change_mode(self, new_mode: TerrainMode):
        self.mode = new_mode

    def render(self, surf: p.Surface):
        surf.blit(self.surfaces[self.mode], self.bounding_rect)

def _sweep(H: np.ndarray, drop: float) -> np.ndarray:
    """Light travels left->right (+x). True = in shadow. O(rows*cols)."""
    shadow = np.empty(H.shape, dtype=bool)
    horizon = np.full(H.shape[0], -np.inf)      # one 'depth buffer' value per row
    for x in range(H.shape[1]):                  # python loop over cols only;
        horizon -= drop                          # each step vectorized over rows
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

# TODO remove from uv scipy and pillow
from PIL import Image

if __name__ == "__main__":
    # DPI awareness is opt-in (Windows scales the window otherwise). To make this
    # preview a fixed pixel size, uncomment:
    # from Resolution import set_dpi_awareness; set_dpi_awareness()

    # image.load/convert_alpha and surfarray need a display mode set first.
    p.init()
    p.display.set_mode((1, 1))

    # t = Terrain((2**9, 2**9), random.randint(0, 10000))   # 512x512
    par = NoiseParams((2**9, 2**9), seed=0)
    moisture_par = NoiseParams((2**9, 2**9), seed=1)
    sun_par = SunParams()
    t = Terrain(par, moisture_par, sun_par, bounding_rect=p.Rect((0, 0), par.size))   # 512x512
    INK = (30, 26, 22, 255)

    def _mask_to_rgba(mask: np.ndarray) -> np.ndarray:
        """A {0,1} float mask (band/step output) -> (H, W, 4) opaque RGBA."""
        return Terrain._grey_to_rgba(mask)


    def _glyph_view(coords, glyph_paths: list[str], glyph_size: int, seed: int = 0,
                     max_rotation: float = 5.0,
                     scale_range: tuple[float, float] = (0.8, 1.2),
                     knockout_glyphs: bool = False,
                     knockout_background_color=(255, 255, 255)) -> p.Surface:
        """Preview helper: a fresh coloured-biome-map surface with one biome's
        glyphs stamped on top, via Terrain._stamp_glyphs. Unlike
        Terrain._build_glyph_map (which composites every BIOME_GLYPH_PATHS
        entry onto ONE shared surface), each call here starts from a clean
        copy of colour_map -- these preview tiles show one biome in isolation."""
        surf = _rgba_to_surf(t.colour_map)
        Terrain._stamp_glyphs(surf, coords, glyph_paths, glyph_size, seed=seed,
                               max_rotation=max_rotation, scale_range=scale_range,
                               knockout_glyphs=knockout_glyphs,
                               knockout_background_color=knockout_background_color)
        return surf

    def _hatch_view(mask: np.ndarray, colour: tuple[int, int, int], angle: float = 45, line_spacing: int = 4, thickness: float = 1.2,
                     wobble_amp: float = 0.0) -> p.Surface:
        """Coloured biome map with parallel hatch lines drawn in `colour`,
        confined to `biome`'s region (Terrain.hatch masks itself to the biome,
        so no separate clipping needed here)."""
        lines = Terrain.hatch(mask, angle=angle, line_spacing=line_spacing,
                               thickness=thickness, wobble_amp=wobble_amp)

        rgba = t.colour_map.copy()
        rgba[lines] = (*colour, 255)
        return _rgba_to_surf(rgba)

    MOUNTAIN_GLYPHS_KNOCKOUT = [
        "Assets/sprites/glyphs/mountain/mountain1_knockout.png",
        "Assets/sprites/glyphs/mountain/mountain2_knockout.png",
        "Assets/sprites/glyphs/mountain/mountain3_knockout.png",
    ]
    FOREST_GLYPHS = BIOME_GLYPH_PATHS[Biome.RAINFOREST]
    MOUNTAIN_GLYPHS_OG = BIOME_GLYPH_PATHS[Biome.MOUNTAIN]

    # Each entry: (label, either an (H, W, 4) uint8 RGBA array [converted via
    # _rgba_to_surf] or an already-built p.Surface [glyph views, which need to
    # blit sprites rather than just display an array]).
    hatched_shadow = Terrain.hatch(t.shadow_map, 45)
    views: list[tuple[str, np.ndarray | p.Surface]] = [
        ("greyscale heightmap", Terrain._grey_to_rgba(as_image_array(t.height_map) / 255.0)),
        ("elevation heightmap (blue-red)", Terrain.apply_palette(t.height_map, Terrain.ELEVATION_PALETTE)),
        ("temperature map (blue-red)", Terrain.apply_palette(Terrain.normalize(t.temp_map), Terrain.TEMPERATURE_PALETTE)),
        ("coloured biome map", t.colour_map),
        ("glyph map", t.maps[TerrainMode.GLYPHMAP]),
        ("inked biome map", Terrain.build_inked_mat(t.height_map, INK, ink_width=0.02)),
        ("band @0.4 w0.05", _mask_to_rgba(Terrain.band(t.height_map, center=0.4, width=0.05))),
        ("step @0.5", _mask_to_rgba(Terrain.step(t.height_map, edge=0.5))),
        ("forest glyphs", _glyph_view(t.get_point_cloud_coords(Biome.RAINFOREST, grid_like=False, how_many=400, separator_thickness=0.02), FOREST_GLYPHS, glyph_size=18)),
        ("forest glyphs (dense)", _glyph_view(t.get_point_cloud_coords(Biome.RAINFOREST, grid_like=False, how_many=None, spacing=8, separator_thickness=0.02), FOREST_GLYPHS, glyph_size=18)),
        ("forest glyphs (dense, knockout)", _glyph_view(t.get_point_cloud_coords(Biome.RAINFOREST, grid_like=False, how_many=None, spacing=8, separator_thickness=0.02), FOREST_GLYPHS, glyph_size=18, knockout_glyphs=True)),
        ("mountain glyphs (og)", _glyph_view(t.get_point_cloud_coords(Biome.MOUNTAIN, grid_like=False, how_many=None, spacing=16, separator_thickness=0.02), MOUNTAIN_GLYPHS_OG, glyph_size=24)),
        ("mountain glyphs (ko)", _glyph_view(t.get_point_cloud_coords(Biome.MOUNTAIN, grid_like=False, how_many=None, separator_thickness=0.02), MOUNTAIN_GLYPHS_KNOCKOUT, glyph_size=24)),
        ("forest hatch", _hatch_view(Terrain.get_biome_mask(t.biome_mat, Biome.RAINFOREST), (60, 130, 70), angle=45,
                                     line_spacing=5, thickness=1.2, wobble_amp=1.5)),
        ("hatched shadows", _hatch_view(t.shadow_map, (20, 20, 20), angle=45, line_spacing=5, thickness=1.2, wobble_amp=1.5))
    ]
    view_index = 0

    def _make_surf(view: np.ndarray | p.Surface) -> p.Surface:
        if isinstance(view, p.Surface):
            return view
        return _rgba_to_surf(view)

    label, rgb = views[view_index]
    surf = _make_surf(rgb)
    screen = p.display.set_mode(surf.get_size())
    p.display.set_caption(f"Terrain preview: {label}  --  [R] next view, ESC to quit")
    clock = p.time.Clock()
    running = True
            
    while running:
        for event in p.event.get():
            if event.type == p.QUIT:
                running = False
            elif event.type == p.KEYDOWN and event.key == p.K_ESCAPE:
                running = False
            elif event.type == p.KEYDOWN and event.key == p.K_r:
                view_index = (view_index + 1) % len(views)
                label, rgb = views[view_index]
                surf = _make_surf(rgb)
                p.display.set_caption(f"Terrain preview: {label}  --  [R] next view, ESC to quit")
        # GLYPHMAP has real (anti-aliased, partial-alpha) transparency, unlike
        # every other view which is fully opaque -- without a clear here, each
        # frame re-composites those soft edges onto the PREVIOUS frame's result
        # instead of a clean background, so alpha visibly accumulates over time
        # (looks like the glyphs "fade in" and thicken at their edges).
        screen.fill((255, 255, 255))
        screen.blit(surf, (0, 0))
        p.display.flip()
        clock.tick(60)
    p.quit()