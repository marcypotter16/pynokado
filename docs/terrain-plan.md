# Plan: Perlin terrain linked to the growable board

## Context
The board is an abstract, directionless graph. Give it *place* — mountain, seaside, cave,
forest, plain — so players have a direction to push. Perlin gen already exists
(`Models/Terrain.py`). Chosen approach (option 2): one high-res canvas that grid nodes
**sample into**, not grid-resolution noise — because the board grows, and a fixed field
means growth just samples more of it (biomes stay stable across rebakes; identical per seed).

## Approach

**1. `Models/Terrain.py`** — add:
- `Biome` enum: `SEASIDE, PLAIN, FOREST, MOUNTAIN, CAVE`.
- `biome_for_height(h)` — ordered height→biome thresholds (tune later).
- `Terrain.biome_at(r, c)` — map coord `(r,c)` → normalized pos → canvas pixel → sample
  `self.matrix` → biome. This is the core of option 2.
- `BIOME_TINT: {Biome: RGB}` — soft parchment-friendly wash colors.

**2. `Models/Board.py`** — 
- `Board.__init__`: `self.terrain = Terrain((512,512))` (seeded, one-time bake).
- `GridNode.terrain: Biome`, tagged **at node creation** via a `_make_node(coord)` helper
  used in both `_build_starting_board` (`:71`) and `_drop_new_vertex` (`:169`).
- In `_bake_board_surface` (`:237`), before the strokes: draw a faint soft blob of
  `BIOME_TINT[node.terrain]` at `_coords2abspos(r,c)` for each vertex. Rides the existing
  lazy-bake/invalidate path, so growth re-washes automatically.

## Reuse
`_coords2abspos` (grid→pixel), the lazy bake + `invalidate_board_surface`, `step`/`band`
(later, for coastlines). No new render hook — terrain rides the board surface.

## Note
Terrain lives on `Models/Board.py`, used by `States/BoardTestState.py` — **not**
`BoardTestState2.py` and **not** the launched `TestParticleState`. Verifying live needs
`main.py` pointed at `BoardTestState`.

## Verify
1. Headless: `Terrain((512,512))`, print `biome_at` over all 13×13 coords — all 5 biomes
   appear, sensible split; save a PNG and eyeball regions.
2. Windowed: temporarily launch `BoardTestState`; confirm faint wash under strokes, growth
   (`A`+drag) reveals biome-tinted cells, existing cells keep their tint. Clean stderr.

## Deferred
Bilinear sampling; coastline/contour render; glyphs; visible heightmap; terrain-keyed card
effects; directional-objective scoring; per-biome rules.