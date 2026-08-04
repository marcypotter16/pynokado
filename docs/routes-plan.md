# Plan: Terrain-derived sites and routes (read-only overlay first)

## Why

The current board is a lattice drawn on top of a map. A lattice asserts the space is
uniform and directionless; the terrain asserts the opposite. The two make contradictory
claims about the same pixels, and the imported one loses. This is not a rendering problem
and no amount of stroke work fixes it.

The fix is to make the graph **derived from** the terrain: pick points of interest out of
the existing fields, connect them with least-cost paths over those same fields, and the
network cannot help but belong to the map.

**None of this is shader work.** Every step is numpy / plain algorithms on the data grid.

## Guiding constraint: Phase 1-4 change nothing

The whole first pass is a **read-only overlay**. `Models/Board.py` is not touched. The
existing lattice keeps running underneath. Sites and routes draw on top as plain dots and
lines. If it looks wrong, one file gets deleted and nothing else moved.

Only after the overlay looks right does the Board integration question even get asked.

---

## What already exists (reuse, don't rewrite)

| Need | Already in `Models/Terrain.py` |
|---|---|
| Terrain classification per cell | `biome_mat`, `get_biome_mask()` |
| Elevation | `height_map` |
| **Slope** (the routing cost) | `height_map_grad` -> `gy, gx` per cell, built for the sun at `:781` |
| Distance-to-region-edge | `_edt(mask)` at `:1900` |
| **Spacing-constrained point picking** | `compute_glyph_points_mat_unif(mask, spacing, how_many, rng)` at `:1108` |
| Data space -> screen space | `to_render_coords(coords, data_shape, out_size)` at `:1207` |
| Stroke stamping along a line | `Board._bake_board_surface` / `blit_line` |

Site selection is *already written* — `compute_glyph_points_mat_unif` is exactly a
blue-noise picker over a mask, which is what site placement is. It just needs a different
mask handed to it.

All work happens in **data space** (the noise grid, e.g. 512x512) and converts to render
space only at draw time, matching how glyphs already work.

---

## Phase 1 — Sites

New file `Models/Routes.py`. No dependency on Board.

```
@dataclass
class Site:
    rc: tuple[int, int]      # data-space (row, col)
    kind: SiteKind           # PEAK | SHORE | CLEARING | SETTLEMENT
    biome: Biome
```

**Candidate mask per kind** — each is a boolean array over the data grid:

- `PEAK` — `biome_mat == MOUNTAIN` and height in the top few percent of the local
  neighbourhood. A max filter comparison, or simply `height_map > percentile`.
- `SHORE` — `_edt(lake_mask == 0)` small but nonzero, i.e. land within N cells of water.
- `CLEARING` — `_edt(forest_mask)` large, i.e. deep inside a forest.
- `SETTLEMENT` — `PLAIN`/farmland cells with low local slope.

**Pick** — feed each mask to `compute_glyph_points_mat_unif(mask, spacing=..., how_many=N,
rng=seeded)`. Pass a seeded rng: sites must be identical run-to-run for a given terrain
seed, the same reason glyph placement is seeded.

Different `spacing` per kind is the tuning knob — peaks rare and far apart, settlements
denser.

**Payoff:** each site carries its biome, so terrain-keyed card effects are a field lookup
later. No new subsystem needed for that.

**Verify:** draw sites as coloured dots over the terrain, one colour per kind. Are they in
places a person would call interesting? Tune spacing/thresholds until yes. Stop here until
this looks right — everything downstream depends on the sites being sensible.

---

## Phase 2 — Cost field and routing

**Cost field**, one array over the data grid:

```
gy, gx = terrain.height_map_grad
slope  = np.sqrt(gx**2 + gy**2)
cost   = 1.0 + SLOPE_W * slope + WATER_W * (biome_mat == LAKE)
```

That's the whole thing. `SLOPE_W` is the single most important number in this plan: low
and routes run straight ignoring terrain, high and they take absurd detours to avoid a
gentle rise. Expect to tune it by eye.

**Routing** — A* (or Dijkstra; at 512^2 = ~260k cells either runs in well under a second,
and this is one-off at map generation, never per frame) over 8-connected neighbours,
accumulating `cost`. Standard `heapq` implementation, no dependency.

Diagonal steps must cost `sqrt(2)` times the cell cost or paths develop a diagonal bias.

**Which pairs to connect** — do NOT connect all pairs.

1. Candidates: each site's k nearest sites by straight-line distance, k ~= 4.
2. Route each candidate pair.
3. **Prune:** drop the edge if `path_cost > RATIO * straight_line_cost`.

Step 3 is the good part. A high ratio means the terrain routed the path a long way around
something — a mountain sits between those two sites and they are not really neighbours.
**The map prunes its own graph.** No hand-authored adjacency, and chokepoints (the one
cheap pass through a ridge) emerge on their own, which a lattice can never produce.

**Verify:** draw raw A* output as thin polylines. Do roads hug valleys and go around
peaks? Tune `SLOPE_W` and `RATIO` here, before smoothing hides what the router is doing.

---

## Phase 3 — Smoothing (Chaikin's corner cutting)

A* output is 8-connected, so it staircases. Chaikin fixes this and is genuinely trivial —
no splines, no libraries, no maths beyond a weighted average.

**The whole algorithm:** for each consecutive pair of points `P[i], P[i+1]`, emit two new
points at 1/4 and 3/4 along that segment:

```
Q = 0.75 * P[i] + 0.25 * P[i+1]
R = 0.25 * P[i] + 0.75 * P[i+1]
```

Discard the original interior points, keep the two endpoints, repeat. Each pass cuts every
corner off; two or three passes is plenty. That's it — about 10 lines, and it converges to
a quadratic B-spline, which is why the result looks properly drawn rather than merely
rounded.

One property to know: it pulls the curve slightly *inside* corners, so a road bends a
little early going around a peak. Visually this is an improvement (real roads cut corners),
so no correction needed — just don't run legality checks on the pre-smoothed path and then
assume the drawn one matches.

Optionally drop near-collinear points first so the smoother isn't fed hundreds of
redundant cells.

---

## Phase 4 — Draw

1. Convert smoothed data-space points to screen with `to_render_coords(...)`.
2. First pass: `pygame.draw.aalines`. Ugly but instantly answers whether the network reads
   as belonging to the map.
3. Then swap in the brush strokes from `Board._bake_board_surface`. Stamping strokes along
   a smoothed polyline is the *same operation* as stamping along a lattice edge — it just
   follows a curve. No new rendering technique.

Bake to a surface once and cache; re-bake only when the terrain regenerates, exactly like
the glyph map.

**Verify:** toggle the overlay on/off over the existing map. The question being answered is
only "does this look like it grew out of the terrain" — not whether it plays well.

---

## Only then: the Board question

If the overlay looks right, the graph moves into `Board.py` and the lattice goes away.

What survives: `GridNode` and its `neighbors` dict. A graph is still a graph; it just stops
being grid-shaped. Sites become nodes, routes become edges, ownership still lives only on
stones.

What breaks: everything assuming integer lattice coordinates — `_coords2abspos`,
`_in_bounds`, `_free_neigh_coords`, `_nearest_free_point`. Real work, but `Board.py` is 348
lines.

What inverts: today `get_biome_at_coords(row, col, grid_size)` maps board -> terrain, so the
board is primary and terrain is looked up. After this, terrain is primary and the board
falls out of it. That is the actual conceptual change and it is the right direction.

Open questions to decide then, not now:

- **Growth.** Brushing currently extends a lattice outward. With sites it becomes
  *revealing further sites* — a different feel, and it needs deciding before the brush
  mechanic is rebuilt on top of it.
- **Balance / seed quality.** Terrain-derived maps can generate unfair *and* ugly — the
  quality of any given map is visibly seed-dependent today. Validate a generated map (site
  count, rough symmetry between the two starting corners, biome coverage) and reroll if it
  fails. **Do this before building mechanics on top, not after:** if the good maps are the
  lucky ones, every downstream judgement about whether the game reads well is being made on
  an unrepresentative sample.

---

## Sequencing

Phase 1 -> verify -> Phase 2 -> verify -> Phase 3 -> Phase 4 -> stop and look.

Phases 1, 2 and 3 are self-contained pure functions with obvious inputs and outputs
(candidate masks; cost field + A*; Chaikin), so they are the natural pieces to hand off.
The tuning constants (`spacing` per kind, `SLOPE_W`, `RATIO`) are judgement calls and want
eyes on the actual map.

---

# Separate track: terrain realism

Independent of the routes work above. Listed by value per line of code.

## A. Edge shape and density (cheap, do first)

**1. Dither the classification threshold.** Add fine noise to the resampled fields just
before `classify_biomes` in `_render_biomes`. Turns every biome boundary from a smooth
iso-contour into a ragged organic edge.

*Why the edges are smooth in the first place:* the boundary of a biome is a level set of a
smooth field. Near a non-degenerate extremum, a smooth function is approximated by its
second-order Taylor expansion, and the level sets of a quadratic form are exactly ellipses
— so **small** regions around a hill or a pit come out elliptical. The noise parameters
make this strong: with `scale=200, octaves=4, persistence=0.5, lacunarity=1.8`, amplitude
falls faster than frequency rises, so there is almost no high-frequency content left to
crinkle a boundary at small scales. Dithering the threshold puts that content back exactly
where it is missing — at the boundary.

*Falsifiable prediction worth checking before spending time on this:* large lakes should
already be ragged, only small ones elliptical. If large ones are round too, the cause is
elsewhere and this fix will not help.

**2. Feather glyph density.** `compute_glyph_points_mat_unif` samples at constant spacing
inside the mask and nothing outside — density is a step function, which is the other half
of "hard edges". Weight acceptance by `_edt` of the biome mask so forests thin out over
their last ~30px instead of stopping dead at full density.

## B. Lakes: isobaths, not distance rings

Water lining is the old-map convention of contours echoing the shore, inside the water,
thinning toward the middle.

Do **not** build these from `_edt` (distance from shore). The real depth is available:
`sea_level - height_map` inside the lake mask. So the lines are **isobaths** — level sets
of the height field below sea level — which means they are the same object `contour()`
already draws, just evaluated at thresholds under the waterline. No new machinery at all,
and it is bathymetrically correct rather than a distance proxy.

Depth-driven water rendering (e.g. Sebastian Lague's) ports at the level of the *mapping*:
depth -> intensity. It does not port at the level of the marks — refraction, animated
foam and normal maps have no pen equivalent. In ink cartography depth is carried by **line
density**, so keep the depth->intensity idea and render it as isobath spacing/weight.

Also: scale `≈` glyph count with lake area instead of a fixed `how_many`, and let them
sit near the edges, not only dead centre.

**Note on SEA vs LAKE:** water forms closed regions because `border_fade` (the island mask)
prevents it from reaching the map edge. No sea is possible while that mask is active,
whatever the biome is named. Renaming SEA to LAKE changed the label, not the cause — if an
actual coastline is wanted, the falloff has to let water reach an edge.

## C. Orography — the distribution problem

The real complaint: mountains do not have the distribution real ranges have, and valleys
below mountains do not reliably hold forest. Both are the same root cause — **relief and
climate are not coupled.** `moisture_map` is `generate_height_map(moisture_params)`, an
independent noise field with its own seed. Nothing in the moisture field knows where the
mountains are.

**1. Valley wetness (one line).** Valleys are concave, and concavity is the negative
Laplacian of the height field:

```
moisture += K * (-laplacian(height_map))
```

This alone produces forest in the valleys under mountains. No new fields, no new passes.

**2. Rain shadow (~15 lines, reusing `_sweep`).** Windward slopes are wet, leeward slopes
arid. This has the *same structure* as the existing shadow pass at `Terrain.py:1915`: a
front advancing in one direction, consumed by obstacles. Same algorithm, different
accumulator — instead of "am I in shadow?", carry "how much moisture is left?", depositing
it on ascent and drying on descent. `_sweep` is already 90% of it.

Gives the windward/leeward asymmetry that is currently absent, which is a large part of why
biome distribution reads as arbitrary.

**3. Ridged noise (a flag in `NoiseParams`).** `pnoise2` fBm produces rounded blobs. Real
ranges are linear and branching because they are tectonic. The standard trick is
`1 - abs(noise)`, which turns zero crossings into sharp crests. Most direct attack on
"mountains have a certain distribution".

**4. Treeline (one line).** Forest currently has no elevation gate — above a certain
altitude there should be no trees regardless of what temperature and moisture say.

(1) and (2) together cover the specific observation about valleys.

## D. Deferred: give temperature its own signal

`temp_map` is **not** a monotonic relabeling of height — the illumination and shadow terms
depend on the *gradient*, so two cells at equal altitude can differ in temperature. But
every term is still a function of `height_map` and its derivatives, so the classification
has only **two independent axes** (height, moisture), not three. Temperature adds detail,
not information.

Cheap partial mitigation available now: the illumination term is directional, so it is
already the only thing breaking radial symmetry around hills. Raising `solar_max_temp_gain`
relative to the lapse-rate range pushes in that direction using a knob that already exists.

The full fix — a latitude term plus an independent noise octave for temperature — rebalances
every biome at once, so it comes after A, B and C have been tried.
