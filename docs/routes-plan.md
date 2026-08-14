# Plan: terrain-derived nodes and routes

## Why

The current board is a lattice drawn on top of a map. A lattice asserts the space is
uniform and directionless; the terrain asserts the opposite. The two make contradictory
claims about the same pixels, and the imported one loses. This is not a rendering problem
and no amount of stroke work fixes it.

The fix is to make the graph **derived from** the terrain: pick nodes out of the existing
fields, connect them by how expensive the ground between them is, and the network cannot
help but belong to the map.

**None of this is shader work.** Every step is numpy / plain algorithms on the data grid.

## The pipeline

1. **Nodes** — many of them, scattered on traversable ground. A small fraction (~10%) are
   flagged as *Sites*: the meaningful places (peak, shore, clearing, settlement).
2. **Connect** — one cost flood (multi-source Dijkstra) gives adjacency.
3. **Weight and prune** — the same flood gives each edge's cost; drop the expensive ones.
4. **Draw** — nodes and surviving edges.
5. **At play time** — A* over the finished graph.

**One node type, not two.** An earlier draft had sparse Sites plus a separate pass that
subdivided routes into sub-nodes. Unifying them removes a whole stage: there is one node
set, and "important" is a flag rather than a different kind of object.

**The consequence that makes everything else simpler:** because nodes are dense, neighbours
are close together, so a straight segment between two of them is already a good
approximation of the ground between them. A chain of short straight edges bends around a
mountain on its own. That means **no curve fitting is needed** — the road's shape comes
from the path through the graph, not from a smoothed polyline. (Chaikin smoothing, in the
earlier draft, was solving a problem that only existed with sparse sites; see the appendix
if node density ever drops far enough to bring it back.)

**Two different A\*s — do not confuse them.** A* over the *grid* finds the physical curve
between two points and is a map-generation step. A* over the *node graph* finds the
cheapest sequence of nodes and is a gameplay query. This plan needs only the second. The
grid is walked once, by the flood, and never again.

## Guiding constraint: build it as a read-only overlay first

The whole first pass touches nothing. `Models/Board.py` keeps running its lattice
underneath; nodes and edges draw on top. If it looks wrong, one file gets deleted.
Only after the overlay looks right does the Board integration question get asked.

---

## What already exists (reuse, don't rewrite)

| Need | Already in the repo |
|---|---|
| Terrain classification per cell | `Terrain.biome_mat`, `Terrain.get_biome_mask()` |
| Elevation | `Terrain.height_map` |
| **Slope** (the cost field) | `Terrain.height_map_grad` -> `gy, gx`, built for the sun |
| Distance-to-region-edge | `Terrain._edt(mask)` |
| **Spacing-constrained point picking** | `Terrain.compute_glyph_points_mat_unif(mask, spacing, how_many, rng)` |
| Data space -> screen space | `Terrain.to_render_coords(coords, data_shape, out_size)` |
| Node/site selection | `Models/Routes.py` (`Sites`, `SiteKind`) — done |

All work happens in **data space** (the noise grid, 450x256) and converts to render space
only at draw time, matching how glyphs already work.

---

## Phase 1 — Nodes  *(done, in `Models/Routes.py`)*

`Sites.construct_sites` already picks four kinds off the terrain fields via
`compute_glyph_points_mat_unif`. What remains is the density split: raise the node count,
then flag a minority as important rather than generating them separately.

`density` in that file is currently **inverse spacing** (`spacing = 1/density`), chosen
deliberately for a small number of meaningful places. The docstring still claims "sites per
unit AREA" — that is the sentence to fix, since it is what would send the next reader back
to a square root.

---

## Phase 2 — Connect: the cost flood  *(done, in `Models/Routes.py`)*

### The idea

Drop dye at every node simultaneously. It spreads fast over flat ground and slowly over
steep ground. Every cell is claimed by whichever dye reaches it first. **Two nodes are
neighbours if their patches touch.**

That is a multi-source Dijkstra over the grid: one pass for all nodes, not one per node.

### The cost field — where slope and height enter

```python
gy, gx = t.height_map_grad          # np.gradient's (d/dy, d/dx) -- TWO arrays
slope = np.hypot(gy, gx)            # the magnitude; comparing the tuple raises
cost = 1.0 + SLOPE_W * slope
cost[Terrain.get_biomes_mask(t.biome_mat, WATER).astype(bool)] *= WATER_COST
```

- **The `1.0` matters.** Without a base cost, flat ground is free and distance stops
  meaning anything — the dye would cross a plain instantly and everything would be
  adjacent to everything.
- **`SLOPE_W` is the one number to tune.** On the current noise params slope runs 0 to
  0.023 with a median of 0.0056, so `SLOPE_W = 900` makes a typical cell cost ~6 and a
  steep one ~20x a flat one. An absolute *threshold* on slope would be wrong here (see
  `Terrain.plateau_mask` for why), but a *weight* is fine — it scales the whole field
  together.
- **Nothing is impassable.** There is no `passable` array; every cell has a cost and the
  flood enters all of them.

### Water: traversable but gated  *(decision changed — see below)*

Water is ordinary expensive ground here, and whether a piece may actually use a water edge
is a **runtime** question, not a graph-construction one: a card carries a `WATER_TRAVEL`
property, and edges that cross water are simply unavailable to pieces without it. Lake
crossings are real edges with real costs; the graph offers them and the rules layer decides
who may take them.

This **reverses an earlier decision in this document**, and the reasoning is worth keeping
because the old argument is not wrong, it just stopped being about correctness. The original
rule made water impassable, on the grounds that Dijkstra assigns an owner to every cell it
reaches, so a passable lake gets region borders drawn across open water and "nobody should
own the lake". That is true — and it is a complaint about how the partition *looks*, not
about whether it is right. Once a lake crossing is a real edge that a boat-capable piece can
travel, a border across the lake is the correct answer rather than an artifact. The
cartography can hide it; the graph should not lie about it.

Two consequences that have to be handled, both easy to miss:

- **A lake is flat, so `1 + SLOPE_W * slope` makes it CHEAP.** Left alone, water becomes the
  fastest way across the map and every route runs along the lakes. `WATER_COST` is the
  multiplier that stops that — high enough that crossing is a real detour, low enough that
  it stays worth doing for a piece that can. Historically water transport genuinely *was*
  fast, so the temptation to leave it cheap is real; resist it until a naval faction exists
  to make that interesting.
- **The edge has to record that it crosses water**, or the runtime gate has nothing to test.
  See the adjacency section below for where that flag comes from.

### The flood

```python
import heapq
dist = np.full((H, W), np.inf)
owner = np.full((H, W), -1, np.int32)
pq = []
for i, (r, c) in enumerate(nodes):
    dist[r, c] = 0.0
    owner[r, c] = i
    heapq.heappush(pq, (0.0, r, c))

NB = [(-1,0,1.0), (1,0,1.0), (0,-1,1.0), (0,1,1.0),
      (-1,-1,1.4142), (-1,1,1.4142), (1,-1,1.4142), (1,1,1.4142)]

while pq:
    d, r, c = heapq.heappop(pq)
    if d > dist[r, c]:
        continue                      # stale entry -- see note below
    for dr, dc, step in NB:
        nr, nc = r + dr, c + dc
        if 0 <= nr < H and 0 <= nc < W:
            nd = d + step * 0.5 * (cost[r, c] + cost[nr, nc])
            if nd < dist[nr, nc]:
                dist[nr, nc] = nd
                owner[nr, nc] = owner[r, c]
                heapq.heappush(pq, (nd, nr, nc))
```

Four things that are easy to get wrong:

- **`if d > dist[r, c]: continue`** — `heapq` has no decrease-key, so improving a cell
  pushes a second entry instead of updating the first. This line discards the stale one.
  Without it the result is still correct but the loop does far more work.
- **Average the two cells' costs** (`0.5 * (cost[here] + cost[there])`), don't use the
  destination's alone. The average is symmetric, so the distance is a proper metric and
  a->b costs the same as b->a.
- **Diagonals cost sqrt(2)**, or paths develop a visible diagonal bias.
- **`owner` is still initialised to -1** even though nothing is impassable any more. Every
  cell reachable from a node gets claimed, so -1 survives only where the grid is genuinely
  disconnected — which is a bug signal now rather than the expected state of the lakes.

### Adjacency, weights and passes — all three from the same array

Compare `owner` with its right and down neighbour. Where they differ and both are >= 0,
that cell pair straddles a border between two regions.

For each pair keep the border cell minimising `dist[a-side] + dist[b-side]`. That sum is
the cost of travelling from node *a* to node *b* **through that point**, so:

- the minimum over the border is the **edge weight**,
- the cell achieving it is the **pass** — the natural crossing between the two,
- and `biome_mat[pass] in WATER` is the edge's **water flag**, the thing `WATER_TRAVEL`
  is tested against at runtime.

That last one is an approximation and should be written down as such: it asks whether the
*crossing point* is on water, not whether the whole route is. An edge whose pass sits on a
spit of land but whose middle runs through open water reads as dry and would be offered to
a piece that cannot swim. It is the right test for the common case — the pass is where the
road actually changes region, so it is where a bridge or a ford would be — and the exact
version needs the path walked cell by cell, which is machinery Phase 2 deliberately avoids.
Revisit if lakes turn out to be shaped such that this misfires often.

Verified against real single-source Dijkstra on 10 pairs: **mean error 4.7%**, most pairs
within 1-2%. The outliers (up to 18%) are pairs whose true cheapest path detours through a
*third* region instead of crossing their shared border — which makes the border figure the
more useful number anyway, since it is the cost of the direct road through the pass, and
that is the road being drawn.

**As built** (`scratch/check_flood.py`, three seeds, 10 pairs each): mean absolute error
**0.6-1.7%**, worst pair +9.7%, and never negative. Do not read that as beating the 4.7%
above: that figure was measured on **29** nodes and this one on **~300**, and the error mode
is a true path detouring through a third region, which needs long edges to have room to
happen. Denser nodes mean shorter edges mean less detour, so the two numbers are not
comparable. ~300 nodes, ~820 edges, mean degree 5.5,
graph connected before any pruning, and the whole `construct_sites` call runs in **0.9s**
on the 450x256 grid, so no caching is needed beyond the existing re-bake.

**The crossing step is easy to leave out and it is a real term.** `dist[a-side] +
dist[b-side]` is the walk up to *each side* of the border and stops there, so the step from
the a-cell into the b-cell is counted in neither. Omitting it made every weight undershoot
true Dijkstra by ~1% — small, but systematic and always in the same direction, which is
exactly the kind of error that survives eyeballing. Both scans are orthogonal, so the
missing term is just `0.5 * (cost[a] + cost[b])`. With it in, the estimate is never below
truth, which is a cheap invariant worth asserting: an undershoot means a term went missing
again.

### Why not k-nearest

Measured on this map, 29 nodes:

| | edges | crossing pairs | edges over water/mountain |
|---|---|---|---|
| k-nearest, k=4 | 67 | **7** | 8 |
| flood adjacency | 61 | **0** | 6 |

(These were measured while water was still impassable, and the last column counted edges
over water as *defects*. Under the current rule a water edge is a legitimate gated crossing,
so only the mountain half of that column is still a complaint. The crossing-pairs column —
the one the argument actually rests on — is unaffected.)

- **Planar.** No two edges cross without a junction. Crossing roads are the single thing
  that most makes a generated network look like a mesh instead of a map.
- **No `k` to choose.** A node in a crowded area gets few neighbours, one in open ground
  gets more, automatically.

It does **not** remove edges that cross a ridge — two nodes either side of a mountain still
meet *at* the mountain, so they are still adjacent (6 vs 8 above is noise). That is Phase 3's
job, and it is why Phase 3 is not optional.

---

## Phase 3 — Weight and prune  *(done, in `Models/Routes.py`)*

The weights already exist from Phase 2. Drop every edge whose weight is far above what its
straight-line distance would predict:

```python
if weight > RATIO * straight_line_distance * median_cost:
    drop
```

A high ratio means the ground between those two nodes is expensive and they are not really
neighbours. `RATIO` is the second tuning knob after `SLOPE_W`.

Check afterwards that the graph is still **connected**; over-pruning can strand a region.
If it does, keep the cheapest edge out of each stranded component regardless of ratio.

### Three corrections the measurements forced

The rule above survives. The reasoning printed around it did not, and all three of these
were found by measuring (`scratch/measure_ratio.py`, `scratch/check_prune.py`) rather than
by reading the code.

**1. Water has to be exempt, or the pass does the opposite of its job.** `WATER_COST`
multiplies lake cells by 8, so a crossing is expensive *by construction* and its ratio is
enormous. Measured on seed 17: of the 42 worst edges on the map, **41 were water**. A plain
ratio cut therefore deletes almost exactly the set of edges the current design deliberately
keeps and gates on `WATER_TRAVEL`. Expensive-because-wet and expensive-because-steep are
different claims and only the second is grounds for saying two nodes are not neighbours.

**2. This is not a test for mountains, and must not be turned into one.** The earlier
sentence here — "a mountain sits between them" — is wrong about this terrain. The ratio
tracks the **steepest cell** on the crossing (correlation **+0.90 to +0.93** across three
seeds), not altitude, and on this map those come apart: MOUNTAIN and SNOW are gated on
*height*, so they select comparatively flat summits, while the steep part of a mountain is
its *flank* — classified as whatever biome its altitude gives, often plain or forest. An
edge climbing a cliff without reaching the top is steep, and registers as no-mountain-at-all
on any biome test. The first attempt at validating this used "fraction of the line inside a
HIGH_GROUND biome" as ground truth and got a *negative* result — high-ratio edges had **less**
high ground than low-ratio ones — purely because of that. The statistic was wrong, not the
rule.

**3. There is no natural break to cut at.** Cross-ridge edges were expected to stand out as
a separate population. They do not: the ratio distribution is a smooth continuum (p50 ≈
0.98, p99 ≈ 2.2, max ≈ 2.5) with no gap. That follows from the noise params making a smooth
field — see the Taylor-expansion note under *terrain realism*, section A — so there are no
cliffs for an edge to be catastrophically wrong about. **Pruning here is a mild cleanup, not
a rescue**, and `RATIO` is a dial rather than a discovered threshold.

### As built

`RATIO = 1.7`. Over four seeds: **6.0–7.8%** of edges dropped, the graph **connected on
every seed**, mean degree 5.5 → ~5.1, and the steepest cell along a pruned crossing averages
**1.73–1.88x** that of the surviving ones — so the cut does separate hard ground from easy.

Connectivity repair is Kruskal over the dropped edges, cheapest first, restoring only those
that actually join two components — minimal by construction, so nothing goes back that did
not have to. In practice it restores **0–2 edges** per map, and their ratios (1.96–2.24) sit
just above the threshold, which is the reassuring outcome: when the graph does need a bad
road, it gets the least bad one available.

Dropped and restored edges are kept on `Sites.pruned` / `Sites.restored` rather than
discarded — "which roads did the map decide not to have" is what you want to draw when
judging whether the threshold is right.

One consequence worth knowing: minimum degree goes from 2 to **1**, so pruning creates
dead-end nodes. That is not a defect — a spur ending at a peak is a real feature of a road
network — but anything that assumes every node has a way onward will now be wrong.

---

## Phase 4 — Draw

1. `Terrain.to_render_coords(...)` for the node positions. It returns **(y, x)** — row
   first, matching the arrays — while pygame wants (x, y). Swap once, at the boundary.
2. Positions are relative to the terrain's own rect, and `Board.terrain_rect` is centred on
   screen, so drawing without adding its topleft shifts everything up and left. (This
   already bit once: `Sites.render` takes an explicit `origin` for exactly this reason.)
3. Straight lines for edges first — that alone answers whether the network belongs to the
   map. Brush strokes after, reusing `Board._bake_board_surface`'s `blit_line`.

Bake to a surface and cache; re-bake only when the terrain regenerates, like the glyph map.

**Verify:** toggle the overlay over the existing map. The only question being answered is
"does this look like it grew out of the terrain" — not whether it plays well.

---

## Phase 5 — Roads  *(done, in `Models/Routes.py`)*

The pruned graph turned out **not** to be the playable network. It is the **substrate**:
every connection the terrain permits. Roads are a subset of it, and they are **grown**, not
filtered.

**Why filtering could never work, established the hard way.** A triangulation answers "who
is next to whom" — a property of space, in which every node is equivalent. Roads answer "who
built what, from where, toward what" — a process with origins. Three separate filters were
tried on the dense graph (ratio pruning, a greedy t-spanner, traffic-weighted styling) and
every one produced a *thinner mesh*, because none of them introduced an origin. Growth
produces centres, trunk links and dead ends for free, because that is what the process makes.

**Growth only ever selects existing substrate edges.** Joining a town directly to anything
inside its radius would invent segments that cross each other, and planarity is the property
that most makes a network read as a map. Selecting from a planar substrate inherits it.

Four passes, in `Sites._grow_roads`:

1. **Radiate** from each hub, accepting an edge with `exp(-d²/2σ²)` where `d` is **cost**
   distance. Cost, not Euclidean: the bell becomes terrain-shaped, so roads run far over a
   plain and die against a mountainside. Ordered by distance and gated on the near end being
   reached already — accepting edges independently gives confetti, not a network.
2. **Trunk** roads between town pairs, chosen by gravity (`size_a·size_b/d²`).
3. **Spurs**, so no Site is unreachable.
4. **Connectivity**, by *path* rather than by edge — see the trap below.

### Four things measured, not reasoned

- **Plains must not be road SOURCES.** Seeding growth at every plains waypoint makes each one
  a small star, and a field of overlapping stars is a triangulation arriving by another
  route. Open country must make roads cheaper to *extend* — hence `ROAD_GROUND` multiplying
  acceptance at the destination — never spawn them.
- **Junctions need a degree limit.** A "fan" artefact *is* a high-degree node, so
  `ROAD_DEGREE_FALLOFF` hits it directly. It is also what allows `ROAD_SIGMA_TOWN` to go high
  enough to cover the map: raising sigma without it brings 21 nodes of degree ≥ 5 back.
- **Loops are not optional.** At `ROAD_LOOP_DISCOUNT = 0` the result is a forest of strict
  trees and reads as a river system. This is the only source of alternate routes.
- **Connectivity repair must add a PATH.** Two road components are usually separated by nodes
  no road reaches, so no single substrate edge has both ends on the network. Repairing
  edge-by-edge silently leaves them apart — measured on seed 88, 79 of 81 nodes reachable
  with an edge-wise repair, all 84 with a path-wise one.

**Bridges solved themselves.** Water is expensive, so cost distance across a lake is large,
so acceptance is near zero and growth simply declines to build crossings. The dense graph had
24 per map — a dozen fanning across each lake — and growth leaves 0–1. Scarcity as a
consequence of the model rather than a rule bolted on, which also makes the surviving
crossing the cheapest one on the map, where a real ferry would run.

As built, over five seeds: **82–141 roads of ~350 substrate edges**, mean degree 2.2–2.7,
every Site reachable, the road network connected on every seed.

### The movement API

`Sites.road_neighbours(rc)` — one step from `rc`, over `roads | player_links`. **Go through
this, never through `edges`**, which is the substrate and includes every connection nobody
built. `Sites.connection(a, b)` gives the edge; `Sites.add_player_link(a, b)` opens a
substrate connection during play and refuses anything that is not a substrate edge, so a
player cannot introduce a crossing either.

`player_links` is deliberately separate from `roads`: the generated network is a property of
the seed and must stay reproducible from it, while player links are game state that has to be
saved and undone.

## Only then: the Board question

If the overlay looks right, the graph moves into `Board.py` and the lattice goes away.

What survives: `GridNode` and its `neighbors` dict. A graph is still a graph; it just stops
being grid-shaped. Nodes become vertices, edges become edges, ownership still lives only on
stones.

What breaks: everything assuming integer lattice coordinates — `_coords2abspos`,
`_in_bounds`, `_free_neigh_coords`, `_nearest_free_point`. Real work, but `Board.py` is
~350 lines.

What inverts: today `get_biome_at_coords(row, col, grid_size)` maps board -> terrain, so the
board is primary and terrain is looked up. After this, terrain is primary and the board
falls out of it. That is the actual conceptual change and it is the right direction.

How many nodes: the old lattice at `MAX_SIZE = 13` was 169 points; Go is 361. Aim for the
low hundreds.

Open questions to decide then, not now:

- **Growth.** Brushing currently extends a lattice outward. With a fixed node set it becomes
  *revealing* further nodes — a different feel, and it needs deciding before the brush
  mechanic is rebuilt on it.
- **Balance / seed quality.** Terrain-derived maps can generate unfair *and* ugly, and map
  quality is visibly seed-dependent today. Validate a generated map (node count, rough
  symmetry between starting corners, connectivity) and reroll if it fails. **Do this before
  building mechanics on top:** if the good maps are the lucky ones, every downstream
  judgement is being made on an unrepresentative sample.

---

## Appendix: options considered and set aside

**Terrain-masked lattice.** Keep a regular lattice, delete impassable cells, snap nodes to
survivors. Much the cheapest option, and it deserves more credit than it first appears: the
original problem was never that the lattice was *regular*, it was that it *ignored the
land*. A lattice whose boundary follows the coast and the ridgeline does not read as
imposed. Cost: edges stay straight lattice edges of uniform length, so the network loses
any relationship to distance. Worth trying if the flood turns out to be more machinery than
the payoff justifies.

**Cost-weighted Voronoi as the board itself.** The flood's `owner` array is already a
partition into provinces. Using those provinces *as* the playable units gives a Risk/Civ
map. Set aside because it makes nodes into areas, and this game is Go-derived — stones sit
on intersections. The partition is still computed; it is just used for adjacency rather
than being the board.

**Sparse sites + grid A\* + Chaikin smoothing.** The original draft: few sites, a real A*
path over the grid between each pair, then corner-cutting to smooth the staircase. Superseded
by dense nodes, which get the same curved appearance from the chain of short edges for far
less machinery. Bring it back only if node count has to drop a long way.

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
depth -> intensity. It does not port at the level of the marks — refraction, animated foam
and normal maps have no pen equivalent. In ink cartography depth is carried by **line
density**, so keep the depth->intensity idea and render it as isobath spacing/weight.

Also: scale the wave-glyph count with lake area instead of a fixed `how_many`, and let them
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
arid. This has the *same structure* as the existing shadow pass: a front advancing in one
direction, consumed by obstacles. Same algorithm, different accumulator — instead of "am I
in shadow?", carry "how much moisture is left?", depositing it on ascent and drying on
descent. `_sweep` is already 90% of it.

Give wind its **own direction parameter**, not `SunParams.azimuth`. Coupling them ties the
lit slope to the wet slope, and a slope that is shaded *and* rainy is a real combination
worth being able to produce.

**3. Ridged noise (a flag in `NoiseParams`).** `pnoise2` fBm produces rounded blobs. Real
ranges are linear and branching because they are tectonic. The standard trick is
`1 - abs(noise)`, which turns zero crossings into sharp crests. Most direct attack on
"mountains have a certain distribution".

**4. Treeline for the wooded biomes.** `GlyphStyle.max_height` exists and PLATEAU uses it;
the other forest biomes still have no elevation gate.

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

The full fix — a latitude term plus an independent noise octave for temperature —
rebalances every biome at once, so it comes after A, B and C have been tried.
