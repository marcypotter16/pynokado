from dataclasses import dataclass, field
from enum import Enum
import heapq
import math
import random
import numpy as np
import pygame as p

from Models.Terrain import Terrain, _edt
from Models.TerrainStyle import BIOME_THRESHOLDS_REV, FORESTED, WATER, Biome
from Utils.Colors import BLACK, BLUE, DARK_GRAY, GRAY, GREEN, WHITE


class SiteKind(Enum):
    PEAK = 0
    SHORE = 1
    CLEARING = 2
    SETTLEMENT = 3


SITEKIND_COLORS: dict[SiteKind, tuple] = {
    SiteKind.PEAK: WHITE,
    SiteKind.SHORE: BLUE,
    SiteKind.CLEARING: GREEN,
    SiteKind.SETTLEMENT: GRAY,
}

Coords = tuple[int, int]

# --- Mask thresholds -------------------------------------------------------
#
# The ones that are distances are in DATA pixels, on a grid that is currently
# 450x256 -- they do not survive a big change to NoiseParams.size unchanged.
# Every number here was picked by counting how many cells it actually selects
# (see the note on each), not by eye.

# How far above the mountain floor a cell has to be to count as a peak. Raw
# height rather than biome_mat on purpose: MOUNTAIN and SNOW are both gated on
# elevation, so going through the classification would just be deriving height
# from height -- and a snowcap IS a peak.
PEAK_HEIGHT_ABOVE_MOUNTAIN = 0.1
# Land within this of open water. 5 keeps the ring tight to the coast.
SHORE_DIST_TO_WATER = 5.0
# How deep inside a forest a clearing has to sit. 20 was too deep to exist:
# the deepest point of any taiga region measured 20.5 and 14.0 on two seeds,
# giving 1 clearing and 0 clearings respectively. 8 gives a few hundred
# candidate cells, which the spacing constraint then thins to a handful.
CLEARING_DEPTH_IN_FOREST = 8.0
# Settlements want gentle ground, as a QUANTILE of the slope over the whole
# map rather than an absolute cutoff. Same reason as Terrain.plateau_mask:
# gradient magnitude has no stable scale on fBm (it is near-flat across
# octaves), so an absolute number silently stops meaning anything the moment
# the noise params move. For reference, on the current params the whole map
# spans slope 0 .. 0.023 with a median of 0.0056 -- an absolute cutoff of 0.1
# selects every cell on the map.
SETTLEMENT_SLOPE_QUANTILE = 0.35
# Waypoints are packed this many times closer than Sites. Node count goes as
# 1/spacing^2, so a ratio of 3 gives roughly 9x as many waypoints as sites --
# i.e. sites end up around 10% of the graph, which is the split the plan wants.
# Using the SITE spacing for waypoints (as the first version did) makes them
# exactly as rare as sites and there is no point generating them at all.
WAYPOINT_SPACING_RATIO = 2.0

# --- Edge ink --------------------------------------------------------------
#
# Cost drives the stroke INVERSELY: cheap edges draw bold and dark, expensive
# ones thin and pale. That is the cartographic reading -- a well-travelled road
# is a strong line, a hard crossing is a faint track -- and it also previews
# Phase 3 for free, since the edges pruning is going to drop are exactly the
# ones that already look faint. Swap the pairs to invert.
EDGE_WIDTH_CHEAP_TO_DEAR = (5, 1)
EDGE_INK_CHEAP_TO_DEAR = ((30, 26, 22), (150, 140, 125))
# Cost is normalized against PERCENTILES, not min/max. A single edge over a
# cliff grades several times steeper than the median (measured: max 0.0138 vs
# median 0.0030), and stretching the ramp to reach it would push every ordinary
# edge into the bottom of the range and flatten the whole map to one weight.
# Everything outside the band clamps.
EDGE_COST_PERCENTILES = (5.0, 95.0)

# What Phase 3 threw away, and what it had to put back. Drawn UNDER the surviving
# network in colours that read as annotation rather than as road, so the question
# "is the threshold right" can be answered by looking instead of by counting.
PRUNED_INK = (182, 104, 92)     # roads the map decided not to have
RESTORED_INK = (146, 118, 40)   # dropped, then forced back to keep it connected

# --- The cost field --------------------------------------------------------
#
# What one grid cell costs to walk through. See docs/routes-plan.md, "The cost
# field", for the reasoning behind every term here.

# The base cost of a cell before any terrain penalty. Load-bearing: without it
# flat ground is FREE, distance stops meaning anything, and the flood crosses a
# whole plain for nothing -- every node on it ends up adjacent to every other.
BASE_COST = 1.0
# How hard slope is punished. A weight rather than a threshold on purpose:
# gradient magnitude has no stable scale on fBm (same reason as
# SETTLEMENT_SLOPE_QUANTILE above), so an absolute cutoff silently stops meaning
# anything when NoiseParams moves, while a weight scales the whole field with it.
# On the current params slope runs 0 .. 0.023, median 0.0056, so 900 makes a
# typical cell cost ~6 and a steep one roughly 20x a flat one.
SLOPE_W = 900.0
# Water is expensive, NOT impassable -- the graph keeps lake crossings as real
# edges and the rules layer gates them on a card's WATER_TRAVEL. This multiplier
# exists because a lake is FLAT, so `BASE_COST + SLOPE_W * slope` scores it as
# cheap as a plain and every route on the map would run along the water.
WATER_COST = 8.0

SQRT2 = math.sqrt(2.0)

# --- Phase 3: pruning ------------------------------------------------------
#
# An edge's DETOUR RATIO is what it actually cost divided by what crossing
# median ground in a straight line would have cost:
#
#     ratio = cost / (straight_line_distance * median_cell_cost)
#
# 1.0 is an ordinary edge. Above that the ground in between is worse than
# typical, and far above it the two nodes are not really neighbours.
#
# 1.7 keeps everything at or below and drops the rest. Measured over three
# seeds (scratch/measure_ratio.py), that is the worst ~7-8% of dry edges, and
# the steepest cell along those crossings averages ~0.0130 against ~0.0072 for
# the ones kept -- so the cut really does separate hard ground from easy.
# Neighbouring settings, same measurement: 1.5 drops ~15%, 2.0 drops ~2.5%.
#
# TWO THINGS THIS NUMBER IS NOT, both found by measuring rather than reasoning:
#
# 1. It is not a natural break. The plan expected cross-ridge edges to stand out
#    as a separate population; they do not. The ratio distribution is a smooth
#    continuum -- p50 ~0.98, p99 ~2.2, max ~2.5 -- with no gap to cut at. That
#    is a property of THIS terrain: the noise params make a smooth field (see
#    the note on dithering in docs/routes-plan.md), so there are no cliffs for
#    an edge to be catastrophically wrong about. Pruning here is a mild cleanup,
#    not a rescue, and the number is a dial rather than a discovered threshold.
#
# 2. It is not a test for mountains. The ratio tracks the STEEPEST CELL on the
#    crossing (correlation +0.90 to +0.93), not altitude. Those are different
#    things on this map: MOUNTAIN and SNOW are gated on height, so they select
#    flat summits, while the steep part of a mountain is its flank -- which is
#    classified as whatever biome its altitude gives. An edge climbing a cliff
#    without reaching the top registers as steep here and as no-mountain-at-all
#    on any biome test. Do not "fix" this by testing biomes.
PRUNE_RATIO = 1.7

# --- Roads: the playable network -------------------------------------------
#
# The pruned graph is the SUBSTRATE -- every connection the terrain permits.
# Roads are a subset of it, and they are GROWN rather than filtered.
#
# Why growth and not another filter: a triangulation answers "who is next to
# whom", which is a property of space, and every node in it is equivalent. Roads
# answer "who built what, from where, toward what", which is a process with
# origins. Filtering the first can only ever produce a thinner mesh -- measured,
# repeatedly, before this was written. Growing from settlements produces
# something with centres, trunk links and dead ends because those are what the
# process makes.
#
# Growth only ever selects edges that already exist in the substrate. Connecting
# a town directly to anything inside its radius would invent segments that cross
# each other, and planarity is the single property that most makes a network
# read as a map rather than a mesh; selecting from a planar substrate inherits
# it for free.

# Reach of a settlement's road-building, in multiples of the MEDIAN EDGE COST so
# it survives a change to node spacing. It is the standard deviation of the
# acceptance bell, and growth stops at 3x it. Scaled by town size on top.
ROAD_SIGMA_TOWN = 4.0
# A port is a lesser town, not a town.
ROAD_SIGMA_SHORE = 1.0
# An edge whose far end is ALREADY on the network is a loop rather than an
# extension. Allowed at a discount: this is the only source of alternate routes,
# and at 0 the result is a forest of strict trees that reads as a river system.
ROAD_LOOP_DISCOUNT = 0.35
# Every road already meeting at either end makes the next one less likely.
# Real crossroads rarely join six ways, and a "fan" artefact IS a high-degree
# node -- so this hits it directly. It is also what lets ROAD_SIGMA_TOWN go high
# enough to cover the map without stars reappearing; measured, raising sigma
# without this brings 21 nodes of degree >= 5 back.
ROAD_DEGREE_FALLOFF = 0.55
# Which settlement pairs get a trunk road, as a quantile of the gravity score
# `size_a * size_b / distance^2`. Gravity is the standard model for which cities
# get a highway between them: big and close beats small and far.
ROAD_TRUNK_QUANTILE = 0.35
# Placeholder until something real drives town size -- surrounding good land is
# the obvious candidate. It only scales sigma, so it changes how far a town
# reaches and nothing else.
ROAD_TOWN_SIZE_RANGE = (0.45, 1.0)

# How willing each biome is to CARRY a road, as a multiplier on the acceptance
# probability at the destination node.
#
# This is where "plains have lots of roads" lives, and it deliberately does NOT
# make plains a road SOURCE. Seeding growth at every plains waypoint was tried:
# each one becomes a small star, and a field of overlapping stars is a
# triangulation arriving by another route -- the exact artefact this approach
# exists to avoid. Open country should make roads cheaper to EXTEND, never spawn
# them out of nowhere.
#
# Not a hard gate either. A road can still climb a mountain; it is just unlikely
# to be built there without a reason, and the trunk pass supplies reasons.
ROAD_GROUND: dict[Biome, float] = {
    Biome.PLAIN: 1.00, Biome.SAVANNAH: 0.90, Biome.DESERT: 0.65,
    Biome.TAIGA: 0.55, Biome.RAINFOREST: 0.40, Biome.PLATEAU: 0.50,
    Biome.TUNDRA: 0.55, Biome.MOUNTAIN: 0.22, Biome.SNOW: 0.12,
    Biome.CAVE: 0.30, Biome.LAKE: 0.15,
}
ROAD_GROUND_DEFAULT = 0.5

# Roads ramp from pale to full ink with how much traffic they carry. Ramping the
# INK and not only the width is what stops the quiet roads competing with the
# trunk -- and the pale end deliberately stops well short of the parchment,
# because the terrain's own field-parcel decoration lives down there and two
# line networks at the same value merge into one visual mess.
ROAD_INK_QUIET_TO_BUSY = ((150, 140, 124), (26, 22, 18))
ROAD_WIDTH_QUIET_TO_BUSY = (1, 6)
# Substrate edges, drawn only when Sites.show_substrate is on: these are
# connections the terrain allows but nobody built, i.e. what a player could pay
# to open up.
SUBSTRATE_INK = (198, 194, 184)
# Water crossings, and connections the player opened. Both deliberately read as
# a different KIND of thing rather than a heavier road: one needs a boat, the
# other was not there when the map was made.
BRIDGE_INK = (58, 96, 134)
PLAYER_LINK_INK = (150, 62, 40)


@dataclass
class Waypoint:
    rc: Coords
    biome: Biome
    render_pos: tuple[float, float] = (0.0, 0.0)
    height: float = 0.0
    slope: float = 0.0


# unsafe_hash rather than plain @dataclass or frozen=True, and the name is
# scarier than the situation. A plain dataclass sets __hash__ = None (eq=True
# implies it), so `set[WaypointEdge]` raises unhashable; frozen=True would fix
# that but then `cost` could never be filled in, and filling it in later is the
# whole point of Phase 3. unsafe_hash generates __hash__ while leaving the class
# mutable -- "unsafe" only if a HASHED field is mutated, and cost is excluded
# from the hash by compare=False below, so it is safe here specifically.
@dataclass(unsafe_hash=True)
class WaypointEdge:
    # Endpoints are data-space rc, keying straight into Sites.sites -- NOT node
    # ids, which are positions in a list that only exists during construction.
    start: Coords
    end: Coords
    # compare=False keeps identity on the endpoints alone: an edge IS its pair
    # of points, and two WaypointEdges over the same pair are the same edge
    # whatever cost each carries. That is what lets the horizontal and vertical
    # border scans dedup against each other, since a pair found by both would
    # otherwise be stored twice.
    cost: float = field(default=0.0, compare=False)
    # The PASS: the cheapest cell on the border between the two nodes' regions,
    # i.e. where the road between them actually crosses. Data-space rc, like
    # every other coordinate on this class.
    pass_rc: Coords = field(default=(0, 0), compare=False)
    # Whether that crossing is on water, which is what a piece's WATER_TRAVEL is
    # tested against. Deliberately an approximation -- it asks about the crossing
    # POINT, not the whole route, so an edge whose pass sits on a spit of land
    # but whose middle runs through open lake reads as dry. See the note in
    # docs/routes-plan.md under "Adjacency, weights and passes" for why the exact
    # version needs machinery this phase avoids on purpose.
    crosses_water: bool = field(default=False, compare=False)
    # Cost relative to what this edge's LENGTH predicts -- see PRUNE_RATIO. Kept
    # on the edge rather than recomputed because it is the honest measure of how
    # bad a road is: `cost` alone grows with length, so a long easy highway and a
    # short cliff score alike. Filled in by _prune_edges; 0.0 means unpruned.
    ratio: float = field(default=0.0, compare=False)
    # How many Site-to-Site cheapest paths use this edge. Only meaningful for
    # edges that are roads, and it is what drives the stroke: an edge carrying
    # through-traffic between places is what a trunk road IS, so the hierarchy
    # is measured rather than thresholded into existence.
    traffic: int = field(default=0, compare=False)


@dataclass
class Site(Waypoint):
    kind: SiteKind = SiteKind.PEAK  # PEAK | SHORE | CLEARING | SETTLEMENT


class _DisjointSet:
    """Union-find, for the connectivity repair in _prune_edges.

    Only two things are asked of it -- "are these already joined" and "join
    them" -- and `union` returning whether it actually did the joining is what
    makes the Kruskal pass a one-liner."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        # Path HALVING rather than full path compression: one pass, no
        # recursion, and it flattens the tree nearly as well.
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> bool:
        """True if this call actually merged two different components."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True


class Sites:
    DEBUG_RADIUS = 8

    def __init__(self) -> None:
        self.sites: dict[Coords, Waypoint] = {}
        # Node ids are positions in self.sites' insertion order, so this is just
        # list(self.sites.values()). It exists to turn the integer ids the flood
        # works in back into rc, and nothing outside _build_edges needs it --
        # edges store rc, so render() goes through self.sites instead.
        self.nodes: list[Waypoint] = []
        # Endpoints are always ordered (lo, hi) by rc, so an edge found from
        # either side is stored once and any caller holding two rc can build
        # the same key.
        self.edges: set[WaypointEdge] = set()
        # What Phase 3 threw away, and what it had to put back to keep the graph
        # connected. Neither is used for play; both exist so the threshold can be
        # judged by looking at it.
        self.pruned: list[WaypointEdge] = []
        self.restored: list[WaypointEdge] = []
        # The playable network: the subset of `edges` that roads were grown
        # along. This is what pieces move on, NOT `edges`.
        self.roads: set[WaypointEdge] = set()
        # Connections players open up during play, at some cost. Kept separate
        # from `roads` on purpose -- the generated network is a property of the
        # map and should stay reproducible from the seed, while this is game
        # state that has to be saved, undone and shown differently. Movement
        # reads the union of the two, via road_neighbours().
        self.player_links: set[WaypointEdge] = set()
        # rc -> the edge joining them, for both roads and player links. Rebuilt
        # by _index_roads whenever either set changes.
        self._road_adj: dict[Coords, dict[Coords, WaypointEdge]] = {}
        # Every substrate edge by endpoint pair, so a caller holding two rc can
        # ask what connection exists between them without scanning.
        self.edge_by_pair: dict[tuple[Coords, Coords], WaypointEdge] = {}
        self.town_size: dict[Coords, float] = {}
        # Median cost of ONE cell, the yardstick the prune ratio is measured
        # against. Filled in by _build_edges.
        self._median_cell_cost: float = 0.0
        # The cost band the stroke ramp spans, filled in once by _build_edges.
        # Kept off WaypointEdge on purpose: cost is a physical quantity, this is
        # a presentation detail, and normalizing is a property of the whole SET
        # rather than of any one edge.
        self._cost_range: tuple[float, float] = (0.0, 1.0)
        self.t_size: tuple[int, int] = (0, 0)
        self.out_size: tuple[int, int] = (0, 0)
        self.show = True
        # Draw the connections the terrain allows that no road was grown along.
        # Off by default: at full density the substrate competes with the roads,
        # which is the whole reason roads are a subset of it.
        self.show_substrate = False
        # The traffic the stroke ramp tops out at, set by _measure_traffic.
        self._traffic_hi: float = 1.0

    @staticmethod
    def construct_sites(
        t: Terrain, out_size: tuple[int, int], density: float = 0.01
    ) -> "Sites":
        """Pick the points of interest out of an already-built Terrain.

        `out_size` is (width, height) in render px -- the same convention
        Terrain.to_render_coords takes -- and is only used to precompute where
        each site draws. `density` is sites per unit AREA.
        """
        sites = Sites()
        sites.t_size = (t.height_map.shape[0], t.height_map.shape[1])
        sites.out_size = out_size

        spacing = 1.0 / density

        # --- PEAKS ---
        mountain_lo = BIOME_THRESHOLDS_REV[Biome.MOUNTAIN][0]
        peaks = t.height_map > mountain_lo + PEAK_HEIGHT_ABOVE_MOUNTAIN
        # A PLATEAU is high ground that is FLAT by construction (see
        # Terrain.plateau_mask), so it passes a pure height test while being
        # the one place in the range that is definitionally not a peak.
        peaks &= t.biome_mat != Biome.PLATEAU.value
        sites._set_sites_from_mask(t, peaks, spacing, SiteKind.PEAK)

        # --- SHORES ---
        # _edt(mask) is the distance to the nearest ZERO cell, so feeding it
        # "is land" gives the distance to the nearest WATER. That is 0 ON the
        # water, which means the near-water test alone selects the whole lake
        # -- measured, 3734 of 5536 selected cells were open water. The land
        # term is what makes these shores rather than buoys.
        water_mask = Terrain.get_biomes_mask(t.biome_mat, WATER)
        dist_to_water = _edt(~water_mask)
        shores = (dist_to_water < SHORE_DIST_TO_WATER) & ~water_mask
        sites._set_sites_from_mask(t, shores, spacing, SiteKind.SHORE)

        # --- CLEARINGS ---
        # The whole FORESTED group, not just TAIGA: a clearing is a gap in the
        # canopy, and the canopy does not care which forest it is. Treating the
        # group as one region also means a wood that is half taiga and half
        # rainforest counts as deep in ONE forest rather than shallow in two.
        forest_mask = Terrain.get_biomes_mask(t.biome_mat, FORESTED)
        dist_to_forest_edge = _edt(forest_mask)
        clearings = dist_to_forest_edge > CLEARING_DEPTH_IN_FOREST
        sites._set_sites_from_mask(t, clearings, spacing, SiteKind.CLEARING)

        # --- SETTLEMENTS ---
        # height_map_grad is the tuple np.gradient returns, (d/dy, d/dx) -- two
        # arrays, not one. Slope is the MAGNITUDE of that vector, so the two
        # components have to be combined; comparing the tuple itself raises,
        # and comparing either component alone would call a steep east-west
        # ridge flat as long as it does not also fall to the south.
        gy, gx = t.height_map_grad
        slope = np.hypot(gy, gx)
        plain = Terrain.get_biome_mask(t.biome_mat, Biome.PLAIN).astype(bool)
        # get_biome_mask hands back float64 (it can carry a fractional EDT
        # inset), and `float64 & bool` is a TypeError -- hence .astype(bool)
        # on every mask above that gets combined with another.
        settlements = plain & (slope < np.quantile(slope, SETTLEMENT_SLOPE_QUANTILE))
        sites._set_sites_from_mask(t, settlements, spacing, SiteKind.SETTLEMENT)
        sites._generate_waypoints(t, spacing * 0.5)
        sites._build_edges(t)
        sites._prune_edges()
        sites._grow_roads(t.noise_params.seed)
        return sites

    @staticmethod
    def build_cost_field(t: Terrain) -> np.ndarray:
        """What each data cell costs to walk through. See the constants above."""
        gy, gx = t.height_map_grad
        # hypot, not either component: a steep east-west ridge is steep even if
        # the ground does not also fall to the south. Same note as in
        # construct_sites' SETTLEMENTS block.
        cost = BASE_COST + SLOPE_W * np.hypot(gy, gx)
        # get_biomes_mask returns float64 (it can carry a fractional EDT inset),
        # and float64 cannot index -- hence astype(bool).
        cost[Terrain.get_biomes_mask(t.biome_mat, WATER).astype(bool)] *= WATER_COST
        return cost

    @staticmethod
    def _cost_flood(
        cost: np.ndarray, seeds: list[Coords]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Multi-source Dijkstra over the cost grid. Returns (dist, owner).

        Drop dye at every node at once; it spreads fast over cheap ground and
        slowly over dear ground, and every cell is claimed by whichever dye
        reaches it first. One pass for all nodes, not one per node.

        This REPLACES a Euclidean distance transform that used to do the same
        job. The EDT is the degenerate case of this function -- with a constant
        cost field, Dijkstra collapses into a nearest-seed lookup, which is what
        scipy computes -- and it was wrong in the two ways that matter: the
        partition was decided by straight-line distance and so knew nothing
        about the terrain, and it produced no cost at all, which is why edge
        weight used to be a separate placeholder reading endpoint heights.

        Nothing is impassable (see docs/routes-plan.md on water), so `owner`
        coming back as -1 anywhere means the grid is genuinely disconnected,
        which is a bug rather than the expected state of the lakes.

        Plain Python lists rather than numpy arrays for `dist`/`owner`/`cost`
        inside the loop, deliberately: this does ~1M relaxations and every
        numpy scalar index boxes a np.float64 on the way out. Measured, the
        list version is several times faster; the arrays are rebuilt at the end
        where vectorized work resumes.
        """
        h, w = cost.shape
        n = h * w
        cost_flat: list[float] = cost.ravel().tolist()
        dist = [math.inf] * n
        owner = [-1] * n

        pq: list[tuple[float, int]] = []
        for node_id, (r, c) in enumerate(seeds):
            i = r * w + c
            dist[i] = 0.0
            owner[i] = node_id
            pq.append((0.0, i))
        heapq.heapify(pq)

        # (flat offset, step length, column delta). The column delta is what
        # catches wrap-around: on a flat grid, "one cell left" from column 0 is
        # the last column of the previous ROW, which is a perfectly valid index
        # and so passes a bounds check while being geometrically nonsense.
        nb = (
            (-w, 1.0, 0), (w, 1.0, 0), (-1, 1.0, -1), (1, 1.0, 1),
            (-w - 1, SQRT2, -1), (-w + 1, SQRT2, 1),
            (w - 1, SQRT2, -1), (w + 1, SQRT2, 1),
        )
        push, pop = heapq.heappush, heapq.heappop
        while pq:
            d, i = pop(pq)
            # heapq has no decrease-key, so improving a cell pushes a SECOND
            # entry rather than updating the first. This discards the stale one.
            # Without it the answer is still correct and the loop does far more
            # work.
            if d > dist[i]:
                continue
            ci = i % w
            here, mine = cost_flat[i], owner[i]
            for off, step, dc in nb:
                nc = ci + dc
                if nc < 0 or nc >= w:
                    continue
                j = i + off
                if j < 0 or j >= n:
                    continue
                # The AVERAGE of the two cells, not the destination's alone:
                # the average is symmetric, so a->b costs what b->a costs and
                # the result is a proper metric.
                nd = d + step * 0.5 * (here + cost_flat[j])
                if nd < dist[j]:
                    dist[j] = nd
                    owner[j] = mine
                    push(pq, (nd, j))

        return (
            np.asarray(dist, dtype=np.float64).reshape(h, w),
            np.asarray(owner, dtype=np.int32).reshape(h, w),
        )

    def _build_edges(self, t: Terrain) -> None:
        """Adjacency, edge weights and passes -- all three out of one flood.

        Two nodes are neighbours if their dye patches touch. For each such pair,
        the border cell minimising `dist[a-side] + dist[b-side]` gives both the
        edge WEIGHT (that sum is the cost of travelling a->b through that point)
        and the PASS (the cell achieving it -- the natural crossing).

        The adjacency this yields is planar, so no two edges cross without a
        junction, and there is no `k` to pick: a node in a crowded area gets few
        neighbours and one in open ground gets more, on its own.

        It does NOT drop edges that cross a ridge. Two nodes either side of a
        mountain still meet AT the mountain, so they are still adjacent -- they
        just meet expensively, which is what makes the weights computed here the
        input Phase 3's pruning needs.
        """
        if len(self.sites) < 2:
            return  # zip(*{}) raises, and one node has nobody to pair with
        self.nodes = list(self.sites.values())
        n_nodes = len(self.nodes)

        cost = Sites.build_cost_field(t)
        dist, owner = Sites._cost_flood(cost, [wp.rc for wp in self.nodes])
        water = Terrain.get_biomes_mask(t.biome_mat, WATER).astype(bool)

        # Where a cell and its right (or lower) neighbour have different owners,
        # that pair straddles a border between two regions.
        #
        # Both scans are collected BEFORE the group-minimum below rather than
        # reduced separately: a border runs in both directions, so the same node
        # pair appears in both scans, and reducing them apart would take the
        # minimum over half the border twice instead of over the whole of it
        # once. The concatenated version cannot get that wrong.
        keys: list[np.ndarray] = []
        sums: list[np.ndarray] = []
        prs: list[np.ndarray] = []
        pcs: list[np.ndarray] = []
        for a, b, dr, dc in (
            (owner[:, :-1], owner[:, 1:], 0, 1),
            (owner[:-1, :], owner[1:, :], 1, 0),
        ):
            m = a != b
            if not m.any():
                continue
            rows, cols = np.nonzero(m)
            av, bv = a[m].astype(np.int64), b[m].astype(np.int64)
            lo, hi = np.minimum(av, bv), np.maximum(av, bv)
            # One integer per unordered pair, so (3, 7) and (7, 3) collapse to
            # the same group and an edge is not reduced twice under two names.
            keys.append(lo * n_nodes + hi)
            # dist[a-side] + dist[b-side] is the walk UP TO each side of the
            # border and stops there, so the step ACROSS it -- from the a-cell
            # into the b-cell -- is in neither term and has to be added back.
            # Both scans are orthogonal (right, down), so its length is 1 and
            # only the usual averaged cell cost applies. Measured, leaving it
            # out makes the weight undershoot true Dijkstra by ~1%, which is
            # small but systematic and always in the same direction.
            sums.append(
                dist[rows, cols]
                + dist[rows + dr, cols + dc]
                + 0.5 * (cost[rows, cols] + cost[rows + dr, cols + dc])
            )
            # The a-side cell stands for the pass. The two sides are adjacent by
            # construction, so this is within one cell of "the" crossing, which
            # is well inside the accuracy of everything downstream.
            prs.append(rows)
            pcs.append(cols)
        if not keys:
            return  # a single region: one node, or every node in the same cell

        key = np.concatenate(keys)
        s = np.concatenate(sums)
        pr, pc = np.concatenate(prs), np.concatenate(pcs)

        # Group-minimum without a Python loop over border cells (there are
        # hundreds of thousands of them). lexsort orders by key first and by sum
        # within each key, so the FIRST row of every key run is that pair's
        # cheapest border cell -- which is the weight and the pass together.
        order = np.lexsort((s, key))
        key_s = key[order]
        first = np.empty(len(key_s), dtype=bool)
        first[0] = True
        np.not_equal(key_s[1:], key_s[:-1], out=first[1:])
        sel = order[first]

        edges: set[WaypointEdge] = set()
        for idx in sel:
            i, j = divmod(int(key[idx]), n_nodes)
            # Ordered by rc, NOT by node id. Ids are positions in self.nodes,
            # which only exists during construction, so an id-ordered endpoint
            # pair could not be rebuilt later -- a caller holding two rc and
            # asking "is there an edge between these?" would have to guess which
            # way round. Sorting the coordinates makes the key intrinsic.
            start, end = sorted((self.nodes[i].rc, self.nodes[j].rc))
            prc = (int(pr[idx]), int(pc[idx]))
            edges.add(WaypointEdge(
                start=start,
                end=end,
                cost=float(s[idx]),
                pass_rc=prc,
                crosses_water=bool(water[prc]),
            ))
        self.edges = edges
        self._median_cell_cost = float(np.median(cost))
        self._refresh_cost_range()

    def _refresh_cost_range(self) -> None:
        if not self.edges:
            return
        lo_p, hi_p = np.percentile([e.cost for e in self.edges], EDGE_COST_PERCENTILES)
        # A map flat enough for the two percentiles to coincide would divide by
        # zero in render(); nudging hi above lo puts every edge at the cheap end
        # of the ramp, which is what a flat map should look like.
        self._cost_range = (float(lo_p), max(float(hi_p), float(lo_p) + 1e-9))

    def _prune_edges(self) -> None:
        """Phase 3: drop edges that cost far more than their length predicts.

        The flood makes two nodes either side of a ridge adjacent -- they meet
        AT the ridge -- so adjacency alone cannot tell a road from a climb. The
        weight can: an edge whose cost is far above `length * median_cell_cost`
        crossed ground much worse than typical. See PRUNE_RATIO for what the
        number is and, more usefully, for the two things it is not.

        WATER EDGES ARE EXEMPT, and this is the correction that makes the pass
        work at all. `WATER_COST` multiplies lake cells by 8, so a crossing is
        expensive BY CONSTRUCTION and its ratio is enormous -- measured, water
        was 41 of the 42 worst edges on one seed. A plain ratio cut therefore
        deletes almost exactly the set of edges the design deliberately keeps
        and gates on WATER_TRAVEL. Expensive-because-wet and
        expensive-because-steep are different claims and only the second one is
        grounds for saying two nodes are not neighbours.
        """
        if not self.edges or self._median_cell_cost <= 0.0:
            return

        index = {rc: i for i, rc in enumerate(self.sites)}
        keep: set[WaypointEdge] = set()
        dropped: list[WaypointEdge] = []
        for e in self.edges:
            run = math.hypot(e.start[0] - e.end[0], e.start[1] - e.end[1])
            e.ratio = e.cost / (run * self._median_cell_cost)
            if e.crosses_water or e.ratio <= PRUNE_RATIO:
                keep.add(e)
            else:
                dropped.append(e)

        # Connectivity repair. Pruning can strand a region behind the very ridge
        # that made its edges expensive, and a stranded region is worse than a
        # bad road -- the campaign layer would simply never reach it.
        #
        # Kruskal over the dropped edges, cheapest first, restoring only those
        # that actually join two components. That is minimal by construction:
        # no cheaper set of edges reconnects the graph, so nothing is put back
        # that did not have to be.
        ds = _DisjointSet(len(index))
        for e in keep:
            ds.union(index[e.start], index[e.end])
        restored: set[WaypointEdge] = set()
        for e in sorted(dropped, key=lambda x: x.cost):
            if ds.union(index[e.start], index[e.end]):
                keep.add(e)
                restored.add(e)

        self.edges = keep
        # Kept for inspection rather than discarded: "which roads did the map
        # decide not to have" is exactly what you want to draw when judging
        # whether the threshold is right.
        self.pruned = [e for e in dropped if e not in restored]
        self.restored = sorted(restored, key=lambda x: x.cost)
        self._refresh_cost_range()

    # ---------------------------------------------------------------- roads
    @staticmethod
    def _pair(a: Coords, b: Coords) -> tuple[Coords, Coords]:
        return (a, b) if a < b else (b, a)

    def _substrate_adj(self) -> dict[Coords, list[tuple[Coords, float]]]:
        adj: dict[Coords, list[tuple[Coords, float]]] = {rc: [] for rc in self.sites}
        for e in self.edges:
            adj[e.start].append((e.end, e.cost))
            adj[e.end].append((e.start, e.cost))
        return adj

    @staticmethod
    def _dijkstra(adj, src: Coords, limit: float = math.inf):
        """Cheapest paths from `src` over whatever adjacency is handed in.
        Returns (dist, prev); `prev` reconstructs a path by walking backwards."""
        dist: dict[Coords, float] = {src: 0.0}
        prev: dict[Coords, Coords] = {}
        done: set[Coords] = set()
        pq: list[tuple[float, Coords]] = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if u in done:
                continue
            done.add(u)
            if d > limit:
                break
            for v, w in adj[u]:
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        return dist, prev

    @staticmethod
    def _path_pairs(prev: dict, dst: Coords) -> list[tuple[Coords, Coords]]:
        out, cur = [], dst
        while cur in prev:
            out.append(Sites._pair(cur, prev[cur]))
            cur = prev[cur]
        return out

    def _radiate(self, adj, src: Coords, sigma: float, rng, deg: dict) -> None:
        """Grow roads outward from `src`, thinning with COST distance.

        Cost distance, not Euclidean: the bell then stops being a circle and
        becomes terrain-shaped, so roads reach far across a plain and die
        quickly against a mountainside. That is the whole reason the flood's
        weights exist.

        Ordered by distance, and an edge is only considered once its near end is
        already reached. Both matter: accepting edges independently by
        probability gives scattered confetti instead of something radiating from
        the town as a connected whole.
        """
        reached = {src}
        seen: dict[Coords, float] = {src: 0.0}
        pq: list[tuple[float, Coords]] = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > 3.0 * sigma or d > seen.get(u, math.inf):
                continue
            for v, w in adj[u]:
                pair = Sites._pair(u, v)
                nd = d + w
                if pair in self.roads:
                    # Already a road: free to travel along, and it extends the
                    # frontier without being paid for again.
                    if v not in reached:
                        reached.add(v)
                        if nd < seen.get(v, math.inf):
                            seen[v] = nd
                            heapq.heappush(pq, (nd, v))
                    continue
                pr = math.exp(-(nd * nd) / (2.0 * sigma * sigma))
                pr *= ROAD_GROUND.get(self.sites[v].biome, ROAD_GROUND_DEFAULT)
                pr *= ROAD_DEGREE_FALLOFF ** (deg.get(u, 0) + deg.get(v, 0))
                if v in reached:
                    pr *= ROAD_LOOP_DISCOUNT
                if rng.random() >= pr:
                    continue
                self._add_road(self.edge_by_pair[pair], deg)
                if v not in reached:
                    reached.add(v)
                    if nd < seen.get(v, math.inf):
                        seen[v] = nd
                        heapq.heappush(pq, (nd, v))

    def _add_road(self, e: WaypointEdge, deg: dict) -> None:
        self.roads.add(e)
        deg[e.start] = deg.get(e.start, 0) + 1
        deg[e.end] = deg.get(e.end, 0) + 1

    def _grow_roads(self, seed: int) -> None:
        """Build the playable network on top of the substrate. See the block of
        constants above for why this is a growth process rather than a filter."""
        self.edge_by_pair = {Sites._pair(e.start, e.end): e for e in self.edges}
        if not self.edges:
            return
        rng = random.Random(seed)
        adj = self._substrate_adj()
        med_edge = float(np.median([e.cost for e in self.edges]))
        deg: dict[Coords, int] = {}

        kinds: dict[SiteKind, list[Coords]] = {}
        for rc, node in self.sites.items():
            if isinstance(node, Site):
                kinds.setdefault(node.kind, []).append(rc)
        towns = kinds.get(SiteKind.SETTLEMENT, [])
        self.town_size = {rc: rng.uniform(*ROAD_TOWN_SIZE_RANGE) for rc in towns}

        # 1. radiate from every hub. Hub-ness is a property of SiteKind, and
        #    that is also the answer to how a PEAK connects: it is a
        #    DESTINATION, somewhere you go to rather than through, so it gets no
        #    radiating pass at all and picks up a single spur in step 3.
        for rc in towns:
            self._radiate(adj, rc, ROAD_SIGMA_TOWN * self.town_size[rc] * med_edge,
                          rng, deg)
        for rc in kinds.get(SiteKind.SHORE, []):
            self._radiate(adj, rc, ROAD_SIGMA_SHORE * med_edge, rng, deg)

        # 2. trunk roads between the towns worth joining.
        gravity: list[tuple[float, Coords, dict]] = []
        for i, a in enumerate(towns):
            dist, prev = Sites._dijkstra(adj, a)
            for b in towns[i + 1:]:
                d = dist.get(b, 0.0)
                if d > 0.0:
                    gravity.append(
                        (self.town_size[a] * self.town_size[b] / (d * d), b, prev))
        if gravity:
            thr = float(np.quantile([g for g, _, _ in gravity], ROAD_TRUNK_QUANTILE))
            for g, b, prev in gravity:
                if g >= thr:
                    for pair in Sites._path_pairs(prev, b):
                        if self.edge_by_pair[pair] not in self.roads:
                            self._add_road(self.edge_by_pair[pair], deg)

        # 3. spurs, so no Site is unreachable. A place with no way in is not a
        #    place; this is also what makes dead ends MEANINGFUL, unlike the
        #    anonymous waypoint stubs Phase 3 pruning produced by accident.
        on_road = {rc for e in self.roads for rc in (e.start, e.end)}
        for kind in SiteKind:
            for rc in kinds.get(kind, []):
                if rc in on_road or not on_road:
                    continue
                dist, prev = Sites._dijkstra(adj, rc)
                reachable = [(d, n) for n, d in dist.items() if n in on_road]
                if not reachable:
                    continue
                for pair in Sites._path_pairs(prev, min(reachable)[1]):
                    if self.edge_by_pair[pair] not in self.roads:
                        self._add_road(self.edge_by_pair[pair], deg)
                on_road = {rc2 for e in self.roads for rc2 in (e.start, e.end)}

        # 4. connectivity. This has to join components with a PATH, not with a
        #    single edge: two road components are often separated by nodes that
        #    no road reaches, and then no individual substrate edge has both
        #    ends on the network. Repairing edge-by-edge silently leaves them
        #    apart -- measured on seed 88, 79 of 81 nodes reachable.
        while True:
            comps = self._road_components()
            if len(comps) <= 1:
                break
            # Smallest first, so the little offshoot reaches for the mainland
            # rather than the other way round.
            comps.sort(key=len)
            src = next(iter(comps[0]))
            others = set().union(*comps[1:])
            dist, prev = Sites._dijkstra(adj, src)
            reachable = [(d, n) for n, d in dist.items() if n in others]
            if not reachable:
                break  # the substrate itself is disconnected; nothing to do
            for pair in Sites._path_pairs(prev, min(reachable)[1]):
                if self.edge_by_pair[pair] not in self.roads:
                    self._add_road(self.edge_by_pair[pair], deg)

        self._index_roads()
        self._measure_traffic()

    def _road_components(self) -> list[set[Coords]]:
        """Connected components of the road network, ignoring off-road nodes."""
        adj: dict[Coords, list[Coords]] = {}
        for e in self.roads:
            adj.setdefault(e.start, []).append(e.end)
            adj.setdefault(e.end, []).append(e.start)
        seen: set[Coords] = set()
        out: list[set[Coords]] = []
        for rc in adj:
            if rc in seen:
                continue
            comp: set[Coords] = set()
            stack = [rc]
            while stack:
                cur = stack.pop()
                if cur in comp:
                    continue
                comp.add(cur)
                stack.extend(n for n in adj[cur] if n not in comp)
            seen |= comp
            out.append(comp)
        return out

    def _index_roads(self) -> None:
        """Rebuild the movement adjacency. Call after touching player_links."""
        adj: dict[Coords, dict[Coords, WaypointEdge]] = {rc: {} for rc in self.sites}
        for e in self.roads | self.player_links:
            adj[e.start][e.end] = e
            adj[e.end][e.start] = e
        self._road_adj = adj

    def _measure_traffic(self) -> None:
        """Count how many Site-to-Site cheapest paths use each road.

        Done once, at construction: it is ~n_sites^2 Dijkstras over a few
        hundred nodes, which is nothing here but is far too much per frame, and
        the answer cannot change while the network does not."""
        for e in self.edges:
            e.traffic = 0
        adj: dict[Coords, list[tuple[Coords, float]]] = {rc: [] for rc in self.sites}
        for e in self.roads:
            adj[e.start].append((e.end, e.cost))
            adj[e.end].append((e.start, e.cost))
        on_road = {rc for e in self.roads for rc in (e.start, e.end)}
        site_rcs = [rc for rc, n in self.sites.items()
                    if isinstance(n, Site) and rc in on_road]
        for i, src in enumerate(site_rcs):
            _, prev = Sites._dijkstra(adj, src)
            # Only the LATER sites, so each unordered pair is counted once.
            for dst in site_rcs[i + 1:]:
                for pair in Sites._path_pairs(prev, dst):
                    self.edge_by_pair[pair].traffic += 1
        busy = [e.traffic for e in self.roads if e.traffic]
        # Against a percentile, not the max: one edge on a natural isthmus can
        # carry several times an ordinary trunk road, and stretching the ramp to
        # reach it pushes every real road into the pale end.
        self._traffic_hi = max(float(np.percentile(busy, 90)), 1.0) if busy else 1.0

    # ------------------------------------------------------------- movement
    def road_neighbours(self, rc: Coords) -> list[Coords]:
        """Nodes reachable from `rc` in one step, over roads AND player links.

        This is the movement API -- go through it rather than through `edges`,
        which is the substrate and includes every connection nobody built."""
        return list(self._road_adj.get(rc, {}))

    def connection(self, a: Coords, b: Coords) -> WaypointEdge | None:
        """The road or player link joining two nodes, or None if not adjacent."""
        return self._road_adj.get(a, {}).get(b)

    def add_player_link(self, a: Coords, b: Coords) -> WaypointEdge | None:
        """Open a substrate connection that no road was grown along.

        Returns the edge, or None if the terrain permits no connection there --
        players extend the network along ground that could carry a road, not
        between arbitrary pairs of nodes, so this cannot introduce a crossing."""
        e = self.edge_by_pair.get(Sites._pair(a, b))
        if e is None or e in self.roads:
            return None
        self.player_links.add(e)
        self._index_roads()
        return e

    def _set_sites_from_mask(
        self,
        t: Terrain,
        mask: np.ndarray,
        spacing: float,
        sitekind: SiteKind,
        is_waypoint: bool = False,
    ) -> None:
        coords = Terrain.compute_glyph_points_mat_unif(
            mask,
            spacing=spacing,
            # Uncapped: the default is 20, which silently becomes the site
            # count for any mask big enough to hold more. `spacing` is meant to
            # be the only thing deciding how many sites there are.
            how_many=None,
            return_coords=True,
            # Seeded off the terrain AND the kind: sites have to be identical
            # run-to-run for a given map (routes, the graph and eventually the
            # game all key off them), and folding in the kind means adding a
            # new SiteKind later cannot reshuffle the existing ones.
            rng=np.random.default_rng(
                (t.noise_params.seed, sitekind.value, int(is_waypoint))
            ),
        )
        if not coords:
            return

        # to_render_coords returns (y, x) -- ROW first, matching the arrays it
        # came from. pygame wants (x, y). Swapping here, once, is the whole
        # reason render() does not do this itself.
        render_yx = Terrain.to_render_coords(coords, self.t_size, self.out_size)

        for coord, (y, x) in zip(coords, render_yx):
            # np.argwhere yields ndarrays, which are unhashable and so cannot
            # key a dict, and would slice height_map by ROW if used as an
            # index. Convert to plain ints at this boundary and nowhere else.
            rc = (int(coord[0]), int(coord[1]))
            # KEYWORDS, not positional. Site subclasses Waypoint, and dataclass
            # inheritance APPENDS the subclass's fields after the base's, so the
            # signature is (rc, biome, render_pos, kind) -- `kind` last, not
            # second where it is declared. Passing positionally silently loads
            # every field with the wrong value instead of raising.
            biome = Biome(int(t.biome_mat[rc]))
            pos = (float(x), float(y))
            height = float(t.height_map[rc])
            # height_map_grad is the TUPLE np.gradient returns, (d/dy, d/dx) --
            # so `height_map_grad[rc]` is a tuple indexed by a tuple, which
            # raises. Slope is the magnitude of the two components; see the
            # longer note in construct_sites' SETTLEMENTS block.
            #
            # Indexed at rc BEFORE the hypot, not after: np.hypot(gy, gx) on the
            # whole field would build a 450x256 array once per node, ~300 times.
            gy, gx = t.height_map_grad
            slope = float(np.hypot(gy[rc], gx[rc]))
            self.sites[rc] = (
                Waypoint(
                    rc=rc,
                    biome=biome,
                    height=height,
                    slope=slope,
                    render_pos=pos,
                )
                if is_waypoint
                else Site(
                    rc=rc,
                    biome=biome,
                    height=height,
                    slope=slope,
                    render_pos=pos,
                    kind=sitekind,
                )
            )

    def _generate_waypoints(self, t: Terrain, spacing: float) -> None:
        """Fill the ground between the Sites with plain nodes.

        The waypoints are what make the graph playable -- Sites are the few
        meaningful places, waypoints are the board you actually move on."""
        if not self.sites:
            return  # zip(*{}) raises; a map with no sites has nothing to fill around
        wp_spacing = spacing / WAYPOINT_SPACING_RATIO

        seeds = np.ones_like(t.height_map, dtype=bool)
        rows, cols = zip(*self.sites)  # rows and cols of the sites already placed
        seeds[rows, cols] = False
        # _edt gives distance to the nearest zero cell, so zeroing the sites
        # turns it into distance-to-nearest-site: one call punches a disk around
        # every site at once. The radius is the WAYPOINT spacing -- punching at
        # the site spacing would clear almost the whole map (a 100px hole around
        # each site on a 450x256 grid) and leave nowhere to put anything.
        punched = _edt(seeds) >= wp_spacing

        # SiteKind.PEAK is arbitrary here -- Waypoint has no kind. It only still
        # reaches the rng seed, which is why _set_sites_from_mask folds
        # is_waypoint in too; otherwise this pass would draw the same random
        # stream as the real PEAK pass.
        self._set_sites_from_mask(t, punched, wp_spacing, SiteKind.PEAK, True)

    def render(self, surf: p.Surface, origin: tuple[int, int] = (0, 0)):
        """Debug markers, one circle per site. `origin` is where the terrain's
        own rect starts on `surf` -- render_pos is relative to the map, not to
        the screen, so without it every site lands in the top-left corner."""
        if not self.show:
            return
        ox, oy = origin

        def seg(edge: WaypointEdge):
            ax, ay = self.sites[edge.start].render_pos
            bx, by = self.sites[edge.end].render_pos
            return (ax + ox, ay + oy), (bx + ox, by + oy)

        # The substrate goes UNDER everything: these are connections the terrain
        # would allow that nobody built, i.e. exactly what a player can pay to
        # open. Off by default -- at full density it competes with the roads.
        if self.show_substrate:
            for edge in self.edges:
                if edge not in self.roads:
                    p.draw.line(surf, SUBSTRATE_INK, *seg(edge), 1)

        quiet_ink, busy_ink = ROAD_INK_QUIET_TO_BUSY
        w_quiet, w_busy = ROAD_WIDTH_QUIET_TO_BUSY
        # Busiest LAST, so a trunk road is never buried under a lane crossing it.
        for edge in sorted(self.roads, key=lambda e: e.traffic):
            k = min(edge.traffic / self._traffic_hi, 1.0)
            width = max(1, round(w_quiet + (w_busy - w_quiet) * k))
            if edge.crosses_water:
                # A crossing keeps its own hue whatever it carries: needing a
                # boat is a capability gate rather than a matter of degree, and
                # an untravelled ferry would otherwise be invisible.
                ink = BRIDGE_INK
            else:
                # Lerped in plain RGB rather than by alpha: surf is the opaque
                # board surface, so per-line alpha would need its own SRCALPHA
                # layer per stroke.
                ink = tuple(round(c + (d - c) * k)
                            for c, d in zip(quiet_ink, busy_ink))
            p.draw.line(surf, ink, *seg(edge), width)

        for edge in self.player_links:
            p.draw.line(surf, PLAYER_LINK_INK, *seg(edge), 3)

        on_road = {rc for e in self.roads | self.player_links
                   for rc in (e.start, e.end)}
        for rc, node in self.sites.items():
            pos = (node.render_pos[0] + ox, node.render_pos[1] + oy)
            if isinstance(node, Site):
                # Towns are drawn at their size; every other Site at the base
                # radius, since only settlements carry a size today.
                r = self.DEBUG_RADIUS + round(8 * self.town_size.get(rc, 0.0))
                p.draw.circle(surf, BLACK, pos, r + 3)
                p.draw.circle(surf, SITEKIND_COLORS[node.kind], pos, r)
            elif rc in on_road:
                p.draw.circle(surf, DARK_GRAY, pos, 4)
