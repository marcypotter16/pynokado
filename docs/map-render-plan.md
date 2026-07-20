# Plan: Ink-map terrain rendering on the parchment (BoardTestState)

## Context
The Terrain (Models/Terrain.py) works: heightmap, biome thresholds, `band()` draws
brush-like iso-lines at threshold heights (e.g. 0.4 = coastline). Goal: paint the map on
the parchment in `States/BoardTestState.py` like a black-ink LOTR chart, without the black
grid drowning in it. Chosen style (confirmed): **hybrid** — faint biome colour washes
under **black ink iso-lines**, black grid on top (washes are light, iso-lines thin, so the
grid stays readable). **No markers in v1.** Map does **not** cover the whole parchment: it
covers the board span and **fades to nothing at its edges** via the user's superellipse
alpha mask (p-norm distance `d_n = (Σ|x_i-c_i|^n)^(1/n)`, large n ≈ rounded square,
smoothstepped 1→0), so it blends into the paper.

## Approach

**1. `Models/Terrain.py` — two additions**
- `superellipse_mask(size, n=8, fade=0.15) -> np.ndarray` (float 0..1, (H,W)): normalized
  coords in [-1,1], `d = (|x|^n + |y|^n)^(1/n)`, mask = `1 - smoothstep(1-fade, 1, d)`.
  Reuse the existing `Terrain.smoothstep`.
- `build_ink_layers()` (or inline in the state): for each interior threshold in
  `BIOME_THRESHOLDS` (0.4, 0.5, 0.8, 0.95), `band(matrix, thr, width)` — coastline (0.4)
  wider (~0.05), others thinner (~0.02). Returns the {0,1} masks. (Band width in *height*
  units makes line thickness follow the gradient — organic, brush-like, keep it.)

**2. `States/BoardTestState.py` — a `TerrainLayer` GameObject** (mirror `PaperBackground`)
- Owns/reads a `Terrain` (per docs/terrain-plan.md the Board owns it; construct it in
  Board.__init__ as planned and let the layer read `board.terrain`).
- Bakes ONCE into an SRCALPHA surface sized to the board's full span
  (`Board._coords2abspos(0,0)` .. `(MAX-1,MAX-1)`) — same rect the grid samples via
  `get_biome_at_coords`, so node biomes match the map under them. Matrix is (row,col):
  transpose `(1,0,2)` before `surfarray` blits (same as Terrain's `__main__`).
  1. **Washes:** `colour_mat` scaled to the span (`smoothscale`), alpha ~60-80.
  2. **Ink iso-lines:** each band mask → ink colour `Board.INK` (30,26,22), scaled to
     span; slight per-line alpha variation for a hand-drawn feel.
  3. **Fade:** multiply the combined layer's alpha channel (`surfarray.pixels_alpha`)
     by `superellipse_mask` so the map feathers into the parchment.
- Add to render queue at `z_index=-5` (between paper -10 and board 0).

**3. Docs:** append a “Rendering” section to `docs/terrain-plan.md` summarizing this.

## Reuse
`Terrain.band`/`smoothstep`/`colour_mat`, `BIOME_TINTS`, `Board.INK`,
`Board._coords2abspos`, `PaperBackground` pattern + render-queue z_index,
`surfarray` transpose convention from Terrain `__main__`.

## Verify
1. Headless: bake the layer, save PNG — washes faint, ink iso-lines crisp, map fades to
   transparent at the superellipse edge; assert corner alpha == 0, centre alpha > 0.
2. Windowed (`BoardTestState` via main.py): map sits under the black grid, grid readable;
   `A`+drag growth still works; biome under a node matches the painted map.

## Deferred
Markers (tree_nobg.png stamp for FOREST, procedural carets/waves); red-ink grid variant;
CAVE band; marker assets from midjourney.
