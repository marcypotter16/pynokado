"""Styling, classification tables and tuning knobs for Models/Terrain.py.

This module is DECLARATIVE ONLY. The rule for what belongs here: if it is a
knob -- a threshold, a palette, a per-biome style record, a registry keyed by
Biome -- it lives in this file. If it computes something, it lives in
Terrain.py. Nothing here may import Terrain, and nothing here should contain
logic beyond building a lookup table out of the declarations above it; that
one-way dependency is what keeps this file readable as a settings surface
rather than turning into a helpers junk drawer.

Terrain.py re-exports every public name defined here, so
`from Models.Terrain import Biome, NoiseParams, BIOME_GLYPHS, ...` keeps
working unchanged -- Terrain.py remains the single import point for callers.
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pygame as p


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
    # Water. Named LAKE rather than SEASIDE because that is what it actually
    # produces: the biome is gated on height below sea level, and the maps are
    # generated as inland terrain with no ocean off any edge, so every region
    # that qualifies is an enclosed body of water. A real seaside -- water
    # running off the edge of the map, with a shore on one side only -- needs
    # the generator to know where the map's coast is, and would be its own
    # biome alongside this one rather than a rename of it.
    LAKE = 0
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
    (0.8, 1.0): MoistureLevels.WET,
}

# Operates on Terrain.normalize(temp_map), NOT raw degrees -- min_temperature is
# re-rolled per terrain instance (see Terrain.__init__), so a fixed degree
# cutoff would drift terrain-to-terrain. Normalizing keeps COLD/TEMPERATE/HOT
# relative to THIS map's own range, same treatment as MOISTURE_THRESHOLDS.
TEMPERATURE_THRESHOLDS: dict[tuple[float, float], TemperatureLevels] = {
    (0.0, 0.35): TemperatureLevels.COLD,
    (0.35, 0.65): TemperatureLevels.TEMPERATE,
    (0.65, 1.0): TemperatureLevels.HOT,
}

BIOME_THRESHOLDS: dict[tuple[float, float], Biome] = {
    (0.0, 0.1): Biome.LAKE,
    (0.1, 0.5): Biome.PLAIN,
    (0.5, 0.80): Biome.RAINFOREST,
    # TEMP: widened for glyph testing (more mountain, snow kept minimal).
    (0.8, 0.95): Biome.MOUNTAIN,
    (0.95, 1.0): Biome.SNOW,
    # we will think about CAVE later
}

BIOME_THRESHOLDS_REV: dict[Biome, tuple[float, float]] = dict(
    (v, k) for k, v in BIOME_THRESHOLDS.items()
)

# Simplified Whittaker biome diagram: (temperature, moisture) -> biome, for
# everything that ISN'T gated purely by elevation (get_biome_from_val still
# special-cases LAKE/MOUNTAIN/SNOW by height first -- those are about being
# underwater/at altitude, not climate). Some biomes cover more than one cell,
# same as a real Whittaker diagram's biomes bleeding across several bands.
WHITTAKER_TABLE: dict[tuple[TemperatureLevels, MoistureLevels], Biome] = {
    (TemperatureLevels.COLD, MoistureLevels.DRY): Biome.TUNDRA,
    (TemperatureLevels.COLD, MoistureLevels.NORMAL): Biome.TAIGA,
    (TemperatureLevels.COLD, MoistureLevels.WET): Biome.TAIGA,
    (TemperatureLevels.TEMPERATE, MoistureLevels.DRY): Biome.PLAIN,
    (TemperatureLevels.TEMPERATE, MoistureLevels.NORMAL): Biome.PLAIN,
    (TemperatureLevels.TEMPERATE, MoistureLevels.WET): Biome.RAINFOREST,
    (TemperatureLevels.HOT, MoistureLevels.DRY): Biome.DESERT,
    (TemperatureLevels.HOT, MoistureLevels.NORMAL): Biome.SAVANNAH,
    (TemperatureLevels.HOT, MoistureLevels.WET): Biome.RAINFOREST,
}

# WHITTAKER_TABLE as an array, so classification can be a single fancy-index
# over whole maps instead of a per-cell dict lookup. Rows/cols are indexed by
# BAND INDEX (position within TEMPERATURE_THRESHOLDS / MOISTURE_THRESHOLDS),
# which is what Terrain._level_indices returns -- built from those dicts'
# own order rather than the enums' so the two can never drift apart.
_TEMPERATURE_LEVELS: list[TemperatureLevels] = list(TEMPERATURE_THRESHOLDS.values())
_MOISTURE_LEVELS: list[MoistureLevels] = list(MOISTURE_THRESHOLDS.values())
_WHITTAKER_LUT: np.ndarray = np.array(
    [
        [WHITTAKER_TABLE[(t, m)].value for m in _MOISTURE_LEVELS]
        for t in _TEMPERATURE_LEVELS
    ],
    dtype=np.uint8,
)

# Faint wash colours, one per biome, drawn UNDER the ink strokes. Tuned to read
# on the warm sepia parchment (~(226,208,176)): mostly desaturated and a shade
# darker/cooler than the paper, so each biome is a distinguishable stain without
# fighting the ink aesthetic. LAKE is the lone cool hue so water pops; PLAIN
# sits nearest the paper (the "empty" default); CAVE is darkest.
BIOME_TINTS: dict[Biome, p.Color] = {
    Biome.LAKE: p.Color(126, 164, 178, 255),  # dusty blue-teal (water)
    Biome.PLAIN: p.Color(214, 196, 150, 255),  # pale warm straw (near paper)
    Biome.RAINFOREST: p.Color(122, 148, 108, 255),  # muted sage/olive
    Biome.MOUNTAIN: p.Color(158, 148, 152, 255),  # cool stone grey-mauve
    Biome.SNOW: p.Color(232, 234, 240, 255),
    Biome.CAVE: p.Color(86, 84, 104, 255),  # deep indigo-charcoal (shadow)
    Biome.TUNDRA: p.Color(176, 176, 168, 255),  # pale frost-grey lichen
    Biome.TAIGA: p.Color(88, 118, 100, 255),  # deep boreal spruce-green
    Biome.DESERT: p.Color(216, 178, 120, 255),  # warm sand/ochre
    Biome.SAVANNAH: p.Color(198, 178, 96, 255),  # dry golden grassland
}


@dataclass
class GlyphStyle:
    """How one biome's glyphs are drawn. ALL THREE numbers are in RENDER
    pixels, so a biome's glyph field looks the same on screen no matter how far
    the terrain underneath is stretched:

    - `size` -- how big the sprite lands on screen. Source sprites are
      128-512px, so any size below that is a downscale and stays crisp.
    - `spacing` -- the minimum gap between glyph centres on screen. Sampling
      still happens on the data grid, so this gets divided by the scale factor
      first (see Terrain._build_glyph_coords); what you set here is what you
      measure on the finished image.
    - `margin` -- the distance-to-border knob: glyph centres stay at least this
      far from the edge of their biome. Keeps a biome's glyphs from crowding
      its neighbours, and clear of any outline BIOME_CONTOURS inks on that
      border. It's the distance to the glyph's CENTRE, so a sprite still
      overhangs by up to half its size -- budget margin >= contour thickness +
      size/2 for no touching at all. A region thinner than 2*margin gets no
      glyphs, which is usually the right call for a pond.

    Keep `spacing` BELOW `size` -- around 75% of it is a good starting point.
    These sprites are line art: their ink covers only a quarter to a bit under
    half of their square, so at spacing == size the sprite boxes merely touch
    while the drawings themselves leave obvious gaps, and a forest reads as
    scattered dots rather than a wood. Overlapping them is also just how hand
    drawn maps look. Glyphs are stamped in paint order (ascending y, see
    get_point_cloud_coords), so overlaps stack front-to-back correctly.

    That's the whole point: stretch the terrain, and the glyphs neither grow
    nor drift apart -- only which terrain they sit on changes.
    """

    paths: list[str]
    size: int = 40  # render px
    spacing: float = 40.0  # render px
    margin: float = 12.0  # render px, distance from the biome's border
    # Fill the sprite's interior with an opaque `knockout_colour` before
    # stamping (Utils.Image.knockout). Turns line art the paper shows through
    # into a solid body -- which is how a peak becomes a SNOW-capped peak
    # rather than an outline. Note this must be done at stamp time rather than
    # by pointing `paths` at the pre-baked `*_knockout.png` files: in those the
    # fill escaped the open base and flooded the lower corners of the square
    # (their bottom corners are alpha 255), so they stamp as white BLOCKS with
    # a mountain drawn on them. Doing it here bounds the fill by the ink itself.
    knockout: bool = False
    knockout_colour: tuple[int, int, int] = (255, 255, 255)
    # "holes" for closed silhouettes (trees), "span" for shapes whose interior
    # isn't enclosed (mountains). See Utils.Image.knockout -- picking the wrong
    # one is silent, it just gives back a sprite barely knocked out at all.
    knockout_fill: str = "holes"
    # How many differently-shaded knockouts to prepare per sprite, and how far
    # apart (per channel) their bodies sit. One flat tone across a whole field
    # of opaque glyphs makes it read as a single cut-out shape rather than as
    # separate ones, so a handful of tones lets neighbours come apart. Costs a
    # knockout pass per variant per sprite at bake time and nothing after.
    knockout_variants: int = 1
    knockout_spread: int = 0


# Per-biome glyph sprite sets for GLYPHMAP compositing. Only biomes with actual
# art go here -- _build_glyph_map only stamps the biomes present as keys, so
# everything else just shows its flat BIOME_TINTS wash until more art exists.
BIOME_GLYPHS: dict[Biome, GlyphStyle] = {
    # TODO placeholder art -- a downloaded icon, not hand-drawn like the trees
    # and mountains, so it reads a bit too geometric next to them. Redraw in
    # the same ink style and drop the replacement in here.
    # Listed first so waves stamp UNDER any land glyph that overhangs a shore.
    Biome.LAKE: GlyphStyle(
        paths=["Assets/sprites/glyphs/water/water-waves.png"],
        size=34,
        # Sparse on purpose: open water with a few wave marks reads as sea,
        # where a dense field would read as texture and fight the coastline.
        spacing=90.0,
        # Clear of the shoreline: the 2px contour plus half a glyph, rounded up
        # generously so waves sit in open water rather than lapping the ink.
        margin=32.0,
    ),
    # Broadleaf only. tree2/tree3 are conifers and used to be mixed in here,
    # which put spruce in the jungle and left the boreal biome with no art at
    # all -- the two forests now split the set along the species line.
    Biome.RAINFOREST: GlyphStyle(
        paths=["Assets/sprites/glyphs/forest/tree1.png"],
        size=24,
        spacing=18.0,
    ),
    # Boreal forest: the same trees stand further apart than jungle canopy, and
    # a taiga that reads as dense as a rainforest loses the distinction between
    # them -- the glyphs are the only thing telling the two apart on the page.
    #
    # tree3 is the other conifer and belongs here, but it's watercolour, not
    # ink: 62% of its pixels are partially transparent against 5-11% for tree1
    # and tree2, which are clean cutouts. Stamped at this size its soft grey
    # ground reads as a smudge around every tree. Add it once that background
    # is knocked out; until then one sprite plus _stamp_glyphs' per-instance
    # rotation and scale carries the variety.
    Biome.TAIGA: GlyphStyle(
        paths=["Assets/sprites/glyphs/forest/tree2.png"],
        size=22,
        spacing=26.0,
    ),
    # Peaks with a KNOCKOUT body: identical ink to MOUNTAIN below, over an
    # opaque near-white flank instead of bare paper. That difference is the
    # whole point -- SNOW sits at the top of a range, so it wants the same
    # mountains as its neighbour, and the white flank is what makes them read
    # as capped rather than as more of the same. It also finally fills the
    # region: a snowfield stopped being a hole in the range the moment
    # something opaque got stamped in it.
    #
    # Listed BEFORE Mountain, so the dark peaks stamp over the caps rather than
    # the other way round. Snowcaps are the far, high ground: having the near
    # ridges overlap them is what puts them behind the range instead of pasted
    # on top of it, and it also stops a bright flank cutting across a dark
    # summit that should be in front of it.
    #
    # Size and spacing sit CLOSE to MOUNTAIN's and should stay that way: a cap
    # is the top of the range it's in, so peaks that were markedly bigger or
    # sparser would read as a change of terrain rather than of altitude. The
    # caps run slightly tighter (26.8 against 30.8) because their opaque bodies
    # hide more of each other than line art does, so they need a little more
    # crowding to read as equally dense. Hand-tuned in SnowTestState.
    #
    # That does mean opaque bodies at spacing well below size, which the rule
    # in GlyphStyle's docstring warns against -- and the warning is real, it's
    # what merged an earlier attempt into one white blob. It's survivable here
    # only because `knockout_fill="span"` bounds each body to the mountain's
    # own silhouette: overlapping peaks still show their ink outline against
    # the white flank behind, so they layer like a range instead of dissolving.
    # Widen the spacing before reaching for a bigger size if it stops reading.
    # Margin stays small so the modest caps get any glyphs at all.
    Biome.SNOW: GlyphStyle(
        paths=[
            "Assets/sprites/glyphs/mountain/mountain1_og.png",
            "Assets/sprites/glyphs/mountain/mountain2_og.png",
            "Assets/sprites/glyphs/mountain/mountain3_og.png",
        ],
        size=48,
        spacing=26.8,
        margin=6.0,
        knockout=True,
        knockout_fill="span",
        # Barely cool, barely off-white: snow has to be brighter than the
        # parchment or the cap goes back to reading as bare paper, but pure
        # white on a warm page reads as a cut-out hole rather than as snow.
        knockout_colour=(244, 246, 250),
        # ... and not all the same white. One flat tone across every cap makes
        # the field read as a single cut-out shape with ink drawn on it; a few
        # tones let individual peaks separate from their neighbours. Kept to a
        # luminance offset rather than a hue shift, because snow varies in how
        # bright it is, not in what colour it is.
        knockout_variants=5,
        knockout_spread=22,
    ),
    Biome.MOUNTAIN: GlyphStyle(
        paths=[
            "Assets/sprites/glyphs/mountain/mountain1_og.png",
            "Assets/sprites/glyphs/mountain/mountain2_og.png",
            "Assets/sprites/glyphs/mountain/mountain3_og.png",
        ],
        size=48,
        spacing=30.8,
    ),
}

# Brush black. Pure black reads harsh on parchment, same reasoning as Board.INK
# (which is the same colour, minus the alpha).
INK: tuple[int, int, int, int] = (30, 26, 22, 255)


@dataclass
class ContourStyle:
    """How one biome's outline is inked into the glyph map. `thickness` is in
    RENDER pixels, like GlyphStyle's numbers, so a coastline stays the same
    weight on screen however far the terrain is stretched.

    `align` decides which side of the boundary the line sits on -- "outer"
    draws it on the land side of a water body (the classic shoreline), "inner"
    keeps it within the region itself. `offset` then nudges that line across
    the boundary in render px, negative being into the region -- the fine
    adjustment `align` is too coarse for. See Terrain.contour."""

    colour: tuple[int, int, int, int] = INK
    thickness: float = 2.0  # render px
    align: str = "outer"
    offset: float = 0.0     # render px, negative = into the region


# Biomes whose region outline gets inked into the GLYPHMAP, drawn UNDER the
# glyphs. Same shape as BIOME_GLYPHS: only the biomes present as keys get a
# line, so adding a mountain-range outline later is one entry, not a code path.
BIOME_CONTOURS: dict[Biome, ContourStyle] = {
    # The shoreline. LAKE is the one biome gated purely on being below sea
    # level, so its outline IS the waterline. Pulled a pixel into the water:
    # "outer" alone puts the whole line on the land side, which leaves the
    # water's own edge undrawn and reads as the line bounding the LAND rather
    # than the lake. Overlapping the water slightly makes it the lake's edge.
    Biome.LAKE: ContourStyle(colour=INK, thickness=2.0, align="outer", offset=-1.0),
    # SNOW deliberately has NO entry here yet, and it's worth writing down why
    # so nobody adds the obvious one again. A snowcap draws no glyphs and no
    # wash, so it's bare paper, which surrounded by dense mountain glyphs reads
    # as a hole punched in the range. Outlining it does not fix that: on this
    # map an outlined blank region already MEANS water (see LAKE above), so
    # a snowline turns an ambiguous gap into a confident lie -- a lake sitting
    # on top of a mountain. What separates the two has to be inside the region,
    # not around it: snow is lighter than the paper, water is not.
}


@dataclass
class HatchStyle:
    """Parallel hatching filling a biome's region -- the shading half of the
    ink layer, where BIOME_CONTOURS is the outline half.

    `line_spacing` and `thickness` are in RENDER pixels, like every other
    on-screen measurement in this file, so the shading keeps its weight when
    the terrain stretches. Note the defaults on Terrain.hatch itself (4 and
    1.2) were tuned back when masks were data-resolution; at render size those
    same numbers give a hatch four times finer than intended, hence the
    coarser values here.

    `wobble_amp` > 0 gives the lines a hand-drawn waver, but it costs about
    five seconds at 1800x1024 -- Terrain.hatch drives it through np.vectorize
    over pnoise2, i.e. one Python call per pixel. Leave it at 0 unless you're
    willing to pay that at every render."""

    colour: tuple[int, int, int, int] | p.Color
    angle: float = 45.0
    line_spacing: float = 14.0  # render px
    thickness: float = 1.6  # render px
    wobble_amp: float = 0.0


# Biomes whose region gets hatched into the GLYPHMAP. Drawn UNDER the contours
# (so an outline reads as the edge of its own shading) and under the glyphs.
# Empty: water is drawn as open paper with sparse wave glyphs instead (see
# BIOME_GLYPHS[Biome.LAKE]). Kept because the machinery is wired up and the
# next biome that wants shading is one entry away -- e.g.
#   Biome.LAKE: HatchStyle(colour=BIOME_TINTS[Biome.LAKE], angle=45.0),
BIOME_HATCHES: dict[Biome, HatchStyle] = {}


@dataclass
class HazeStyle:
    """Faint uneven tone laid through a biome's region, UNDER everything else.

    Its job is to stop a field of glyphs reading as a scatter of separate
    stamps: bare parchment between the peaks is what makes a range look like
    loose stamps rather than one landform, and a little tone in those gaps
    binds them. It draws nothing itself -- see Models/Haze.py for the field.

    Only the colour and the strength are per-biome. The FIELD is built once and
    masked per biome (see _build_glyph_map), so haze runs continuously across
    the MOUNTAIN/SNOW border instead of two independent patches meeting at a
    seam down the snowline -- which is the whole point, since those two biomes
    are one mountain.

    Keep the colours DARKER than the parchment. Lighter reads as a wash laid
    over the paper; darker reads as air and shadow between the peaks, which is
    what's wanted, and it stays out of the way of the snowcaps' pale glyphs.
    """

    colour: tuple[int, int, int, int]
    strength: float = 1.0  # scales the alpha; 0 is off


# Shared parameters for the one haze field. Cells are the grid it's BAKED at,
# not pixels -- it's resampled to render size, so this is about how coarse the
# haze is, not how sharp (see Models/Haze.py).
HAZE_CELLS: tuple[int, int] = (120, 200)
HAZE_COVERAGE: float = 0.10
HAZE_VARIATION: float = 0.45
# Render px of blur on the region mask. The haze field is soft but the biome
# mask is not, so without this the haze stops dead on the classification
# boundary -- a smudge with a cut edge, which is worse than no smudge. Blurring
# also lets it overhang the region slightly, which is right: the air around a
# mountain doesn't end where the rock does.
HAZE_EDGE_SOFTNESS: float = 9.0
# ... and the gain that undoes what the blur costs the INTERIOR. A blur this
# wide doesn't only soften the border: over a fragmented region -- which is
# what a mountain range is, arms and outliers rather than a disc -- it pulls
# the middle down as well, because most of the region is within a sigma of
# some edge. Measured, that left the haze averaging 7% opacity, i.e. present
# but invisible. Multiplying back up and clipping restores solid interiors
# while keeping the soft falloff, since only the edge is below 1 after the
# gain.
HAZE_EDGE_GAIN: float = 2.0

# Biomes that get hazed. Mountains and their snowcaps, because they're the
# regions drawn as dense glyph fields with paper showing through -- forests are
# dense enough to close their own gaps.
BIOME_HAZE: dict[Biome, HazeStyle] = {
    Biome.MOUNTAIN: HazeStyle(colour=(118, 108, 96, 215)),
    # Cooler and a touch stronger: the cap's glyphs are knocked out to near
    # white, so they need more contrast behind them than the dark peaks do.
    Biome.SNOW: HazeStyle(colour=(122, 128, 142, 220), strength=1.2),
}


@dataclass
class FieldStyle:
    """Farmland: a biome's region cut into Voronoi parcels, each one outlined
    and (some of them) hatched, the way cultivated land is drawn on an estate
    map. The shading counterpart to HatchStyle, except the hatching is per
    PARCEL rather than per biome -- neighbouring fields run their furrows in
    different directions, which is most of what makes the pattern read as
    farmland rather than as texture.

    Every measurement is in RENDER pixels, like GlyphStyle and ContourStyle, so
    a field keeps its size on screen however far the terrain is stretched:

    - `cell_size` -- the average parcel width. This is the one to reach for:
      everything else is proportion.
    - `jitter` -- how far a parcel's seed strays from its lattice position.
      0 gives a graph-paper grid of identical squares, 1 lets a seed land
      anywhere in its cell. The middle is what looks farmed: parcels visibly
      hand-shaped but of comparable size, because nobody ploughs a sliver.
    - `margin` -- parcels stay this far inside the biome's border, same knob as
      GlyphStyle.margin, so the outermost furrow doesn't run into whatever
      BIOME_CONTOURS inked on that boundary.
    - `crop_fraction` -- share of parcels that get hatched at all. The rest are
      left as bare paper (fallow), which is what stops the whole region turning
      into one flat grey mass -- the contrast between worked and empty parcels
      is the pattern.
    - `angles` -- the directions a parcel's furrows may run, picked per parcel.
      Keep them well apart; two angles a few degrees off each other read as one
      badly drawn field rather than two neighbouring ones.
    - `min_coverage` -- a parcel is dropped unless this fraction of a full
      cell's worth of it lands inside the region. Without it, every stray
      pocket of the biome catches a corner or a vertex of some parcel and inks
      a few disconnected line fragments, which read as scratches on the paper
      rather than as fields. Nobody farms a plot that size either.
    """

    cell_size: float = 64.0  # render px, average parcel width
    jitter: float = 0.6  # 0 = lattice, 1 = anywhere in its cell
    min_coverage: float = 0.35  # of a full cell's area, else dropped
    edge_colour: tuple[int, int, int, int] = (*INK[:3], 190)
    edge_thickness: float = 1.4  # render px
    margin: float = 14.0  # render px, distance from the biome's border
    crop_fraction: float = 0.55  # share of parcels that are hatched
    hatch_colour: tuple[int, int, int, int] | p.Color = (108, 96, 68, 120)
    hatch_spacing: float = 7.0  # render px
    hatch_thickness: float = 1.1  # render px
    angles: tuple[float, ...] = (18.0, 63.0, 108.0, 153.0)


# Biomes whose region gets cut into farmland parcels, drawn UNDER the contours
# and the glyphs. Same shape as BIOME_GLYPHS/BIOME_HATCHES: a biome with no
# entry here simply isn't cultivated.
BIOME_FIELDS: dict[Biome, FieldStyle] = {
    # PLAIN is the temperate/dry-to-normal cell of the Whittaker table -- the
    # one biome that is neither underwater, at altitude, nor jungle, which is
    # exactly where people farm.
    Biome.PLAIN: FieldStyle(),
}


@dataclass
class NoiseParams:
    size: tuple[
        int, int
    ]  # (width, height) -- x,y order, like a pygame Surface/Rect size
    scale: float = 200.0
    octaves: int = 4
    persistence: float = 0.5
    lacunarity: float = 1.8
    seed: int = 0


@dataclass
class SunParams:
    elevation: float = 45.0
    azimuth: float = 315.0
    solar_max_temp_gain: float = 8.0
    shadow_max_temp_loss: float = 3.0
    # how fast the shadow-casting ray falls per column: bigger -> shorter shadows, smaller -> longer shadows.
    # 0.005 is a good default found by eye in scratch/temp_shadow_debug.py; None -> compute_shadows picks 1/width instead.
    shadow_falloff: float | None = 0.005
    # extra cooling for cells shadowed most of the DAY (see shadow_accumulation_map), separate from
    # shadow_max_temp_loss which only reacts to the current instant's shadow. Models valleys hemmed in
    # by mountains staying cold even when the current moment's sun happens to reach them directly.
    accumulated_shadow_temp_loss: float = 6.0
