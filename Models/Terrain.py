# I want to generate terrain with perlin noise.

from enum import Enum
import math
import random as pyrandom

import noise
import numpy as np
from numpy import random
import pygame as p

class Biome(Enum):
    SEASIDE = 0
    PLAIN = 1
    FOREST = 2
    MOUNTAIN = 3
    SNOW = 4
    CAVE = 5

BIOME_THRESHOLDS: dict[tuple[float, float], Biome] = {
    (0.0, 0.1): Biome.SEASIDE,
    (0.1, 0.5): Biome.PLAIN,
    (0.5, 0.65): Biome.FOREST,
    # TEMP: widened for glyph testing (more mountain, snow kept minimal).
    (0.65, 0.95): Biome.MOUNTAIN,
    (0.95, 1.0): Biome.SNOW,
    # we will think about CAVE later
}

BIOME_THRESHOLDS_REV: dict[Biome, tuple[float, float]] = dict((v, k) for k, v in BIOME_THRESHOLDS.items())

# Faint wash colours, one per biome, drawn UNDER the ink strokes. Tuned to read
# on the warm sepia parchment (~(226,208,176)): mostly desaturated and a shade
# darker/cooler than the paper, so each biome is a distinguishable stain without
# fighting the ink aesthetic. SEASIDE is the lone cool hue so water pops; PLAIN
# sits nearest the paper (the "empty" default); CAVE is darkest.
BIOME_TINTS: dict[Biome, p.Color] = {
    Biome.SEASIDE: p.Color(126, 164, 178, 255),   # dusty blue-teal (water)
    Biome.PLAIN: p.Color(214, 196, 150, 255),     # pale warm straw (near paper)
    Biome.FOREST: p.Color(122, 148, 108, 255),    # muted sage/olive
    Biome.MOUNTAIN: p.Color(158, 148, 152, 255),  # cool stone grey-mauve
    Biome.SNOW: p.Color(232, 234, 240, 255),
    Biome.CAVE: p.Color(86, 84, 104, 255),        # deep indigo-charcoal (shadow)
}

class Terrain:
    def __init__(self, size: tuple[int, int], seed: int = 0):
        self.size = size
        self.scale = 200.0
        self.octaves = 4
        self.persistence = 0.5
        self.lacunarity = 1.8
        self.height_map = np.zeros(self.size)
        self.colour_mat = np.zeros([size[0], size[1], 3]) # rgb
        self.generate_height_map(seed)

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
        return self.get_biome_from_val(self.height_map[x, y])

    def get_biome_from_val(self, val: float) -> Biome:
        # matrix is normalized to [0, 1], so clamp defensively and pick the first
        # band whose lower bound the value clears (bands are contiguous, ascending).
        val = min(max(float(val), 0.0), 1.0)
        biome = Biome.SEASIDE
        for (lo, _hi), b in BIOME_THRESHOLDS.items():
            if val >= lo:
                biome = b
        return biome

    def generate_height_map(self, seed):
        for i in range(self.size[0]):
            for j in range(self.size[1]):
                self.height_map[i][j] = noise.pnoise2(
                    i / self.scale,
                    j / self.scale,
                    octaves=self.octaves,
                    persistence=self.persistence,
                    lacunarity=self.lacunarity,
                    repeatx=self.size[0],
                    repeaty=self.size[1],
                    base=seed,
                )
        self.normalize()
        self._build_colour_mat()

    def _build_colour_mat(self):
        """Bake an (H, W, 3) uint8 RGB image of the biome map: each cell's height
        -> biome -> BIOME_TINTS colour. Useful for previewing the terrain; the
        board itself samples biomes per-node via get_biome_at_coords."""
        rows, cols = self.height_map.shape
        self.colour_mat = np.zeros((rows, cols, 4), dtype=np.uint8)
        for biome, colour in BIOME_TINTS.items():
            rgba = (colour.r, colour.g, colour.b, colour.a)
            # mask of every cell whose height falls in this biome
            mask = np.vectorize(self.get_biome_from_val)(self.height_map) == biome
            self.colour_mat[mask] = rgba

    def normalize(self):
        low, hi = self.height_map.min(), self.height_map.max()
        self.height_map = np.interp(self.height_map, [low, hi], [0, 1])

    @staticmethod
    def to_pygame_surf(mat: np.ndarray, surf: p.Surface) -> None:
        p.surfarray.array_to_surface(surf, mat)

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
    def get_biome_mask(mat: np.ndarray, biome: Biome) -> np.ndarray:
        """{0,1} mask of every cell whose height falls inside `biome`'s band."""
        lo, hi = BIOME_THRESHOLDS_REV[biome]
        mask = np.zeros_like(mat)
        # chained comparison (lo < mat < hi) doesn't work elementwise on arrays --
        # Python desugars it to an `and`, which numpy can't evaluate for an array
        # with more than one element. Use & with each side parenthesised instead.
        mask[(lo < mat) & (mat < hi)] = 1
        return mask
    
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
    
from scipy.ndimage import rotate    

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

def compute_shadows(height_map: np.ndarray,
                    sun_elevation: float,        # degrees above horizon
                    sun_azimuth: float = 315.0,  # degrees, where light comes FROM (0=N, 90=E; 315=NW, the cartographic classic)
                    cell_size: float = 1.0       # horizontal size of one cell, in the SAME units as height values
                    ) -> np.ndarray:
    """Returns bool mask, True = in cast shadow."""
    drop = np.tan(np.radians(sun_elevation)) * cell_size

    a = sun_azimuth - 270.0                      # rotate so light travels along +x
    Hr = rotate(height_map, a, reshape=True, order=1,
                mode='constant', cval=height_map.min())
    shadow_r = _sweep(Hr, drop)

    back = rotate(shadow_r.astype(np.float32), -a, reshape=True,
                  order=1, mode='constant', cval=0.0)
    oy, ox = height_map.shape
    y0 = (back.shape[0] - oy) // 2
    x0 = (back.shape[1] - ox) // 2
    return back[y0:y0+oy, x0:x0+ox] > 0.5

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
    t = Terrain((2**9, 2**9), 0)   # 512x512
    INK = (30, 26, 22, 255)

    def _mask_to_rgb(mask: np.ndarray) -> np.ndarray:
        """A {0,1} float mask (band/step output) -> (H, W, 3) greyscale uint8."""
        grey = (mask * 255).astype(np.uint8)
        return np.repeat(grey[:, :, None], 3, axis=2)

    def _rgb_to_surf(rgb: np.ndarray) -> p.Surface:
        # rgb is (row, col, 3); array_to_surface wants (x=col, y=row), so swap
        # the first two axes to avoid a transposed image.
        surf = p.Surface((rgb.shape[1], rgb.shape[0]))
        p.surfarray.blit_array(surf, np.transpose(rgb, (1, 0, 2)))
        return surf

    def _get_point_cloud_coords(biome: Biome, spacing=18, grid_like=True, how_many=20):
        """Coordinates to spawn glyphs at, in PAINT ORDER (ascending row/y)."""
        biome_mask = Terrain.get_biome_mask(t.height_map, biome)
        if not grid_like:
            # keyword args here on purpose: compute_glyph_points_mat_unif's
            # signature is (mask, spacing, how_many, return_coords) -- the old
            # positional call (biome_mask, how_many, True) silently sent
            # how_many into `spacing` and `True` (=1) into `how_many`, so only
            # ONE point ever came back regardless of the requested how_many.
            coords = Terrain.compute_glyph_points_mat_unif(
                biome_mask, spacing=spacing, how_many=how_many, return_coords=True)
        else:
            glyph_mask = Terrain.compute_glyph_points_mat(biome_mask, spacing=spacing)
            coords = np.argwhere(glyph_mask)
        return sorted(coords, key=lambda c: c[0])
    
    def _glyph_view(coords, glyph_paths: list[str], glyph_size: int, seed: int = 0,
                     max_rotation: float = 5.0,
                     scale_range: tuple[float, float] = (0.8, 1.2)) -> p.Surface:
        """Coloured biome map with a glyph sprite stamped at each
        compute_glyph_points_mat location inside `biome`'s region. Glyphs are
        picked randomly (seeded) from `glyph_paths` for visual variety, and each
        stamped instance gets its own random rotation (+-max_rotation degrees)
        and scale (uniform in scale_range) so a repeated glyph doesn't look
        mechanically identical every time -- reads more hand-placed/organic.
        Rotation/scale are per-instance (not baked into the shared glyph list),
        so use p.transform.rotozoom rather than pre-scaling once."""
        glyphs = [p.image.load(path).convert_alpha() for path in glyph_paths]
        glyphs = [p.transform.smoothscale(g, (glyph_size, glyph_size)) for g in glyphs]

        surf = _rgb_to_surf(t.colour_mat[:, :, :3])
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
        return surf

    def _hatch_view(biome: Biome, colour: tuple[int, int, int], angle: float = 45,
                     line_spacing: int = 4, thickness: float = 1.2,
                     wobble_amp: float = 0.0) -> p.Surface:
        """Coloured biome map with parallel hatch lines drawn in `colour`,
        confined to `biome`'s region (Terrain.hatch masks itself to the biome,
        so no separate clipping needed here)."""
        biome_mask = Terrain.get_biome_mask(t.height_map, biome)
        lines = Terrain.hatch(biome_mask, angle=angle, line_spacing=line_spacing,
                               thickness=thickness, wobble_amp=wobble_amp)

        rgb = t.colour_mat[:, :, :3].copy()
        rgb[lines] = colour
        return _rgb_to_surf(rgb)

    MOUNTAIN_GLYPHS_KNOCKOUT = [
        "Assets/sprites/glyphs/mountain/mountain1_knockout.png",
        "Assets/sprites/glyphs/mountain/mountain2_knockout.png",
        "Assets/sprites/glyphs/mountain/mountain3_knockout.png",
    ]
    MOUNTAIN_GLYPHS_OG = [
        "Assets/sprites/glyphs/mountain/mountain1_og.png",
        "Assets/sprites/glyphs/mountain/mountain2_og.png",
        "Assets/sprites/glyphs/mountain/mountain3_og.png",
    ]
    FOREST_GLYPHS = ["Assets/sprites/glyphs/forest/tree1.png"]

    # Each entry: (label, either an (H, W, 3) uint8 RGB array [converted via
    # _rgb_to_surf] or an already-built p.Surface [glyph views, which need to
    # blit sprites rather than just display an array]).
    views: list[tuple[str, np.ndarray | p.Surface]] = [
        ("greyscale heightmap", np.repeat(as_image_array(t.height_map)[:, :, None], 3, axis=2)),
        ("coloured biome map", t.colour_mat[:, :, :3]),
        ("inked biome map", Terrain.build_inked_mat(t.height_map, INK, ink_width=0.02)[:, :, :3]),
        ("band @0.4 w0.05", _mask_to_rgb(Terrain.band(t.height_map, center=0.4, width=0.05))),
        ("step @0.5", _mask_to_rgb(Terrain.step(t.height_map, edge=0.5))),
        ("forest glyphs", _glyph_view(_get_point_cloud_coords(Biome.FOREST, grid_like=False, how_many=400), FOREST_GLYPHS, glyph_size=18)),
        ("mountain glyphs (og)", _glyph_view(_get_point_cloud_coords(Biome.MOUNTAIN, grid_like=False, how_many=None, spacing=16), MOUNTAIN_GLYPHS_OG, glyph_size=24)),
        ("mountain glyphs (ko)", _glyph_view(_get_point_cloud_coords(Biome.MOUNTAIN, grid_like=False, how_many=None), MOUNTAIN_GLYPHS_KNOCKOUT, glyph_size=24)),
        # ("mountain glyphs (knockout)", _glyph_view(Biome.MOUNTAIN, MOUNTAIN_GLYPHS_KNOCKOUT, spacing=20, glyph_size=24)),
        ("forest hatch", _hatch_view(Biome.FOREST, (60, 130, 70), angle=45,
                                     line_spacing=5, thickness=1.2, wobble_amp=1.5)),
    ]
    view_index = 0

    def _make_surf(view: np.ndarray | p.Surface) -> p.Surface:
        if isinstance(view, p.Surface):
            return view
        return _rgb_to_surf(view)

    label, rgb = views[view_index]
    surf = _make_surf(rgb)
    screen = p.display.set_mode(surf.get_size())
    p.display.set_caption(f"Terrain preview: {label}  --  [R] next view, ESC to quit")
    clock = p.time.Clock()
    running = True

    matrix = np.matrix(t.height_map)
    with open("outfile.txt", "wb") as f:
        for line in matrix:
            np.savetxt(f, line, fmt='%.2e')
            
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
        screen.blit(surf, (0, 0))
        p.display.flip()
        clock.tick(60)
    p.quit()