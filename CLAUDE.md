# pynokado

A Go-inspired ink-and-parchment strategy game: pygame + moderngl, procedurally
generated hand-drawn-looking maps. Python 3.13, dependencies via `uv`.

```bash
uv run main.py
```

`main.py` pushes `BoardTestState`, which is the real entry point for everything
currently being worked on. To launch, drive or screenshot the window, use the
**`run-game` skill** — there is a Windows 200%-DPI trap that silently crops every
screenshot into looking like a zoomed-in game.

## Layout

| Path | What lives there |
|---|---|
| `Game.py` | `Game`: window, GL context, state stack, per-frame loop, fonts, `cursorpos`, letterbox scaling |
| `GLRenderer.py` + `*.glsl` | moderngl passes. `window_scaling` (embedded) and `hover_glow.glsl` are the live ones |
| `States/` | one file per screen; `BoardTestState` is the current one |
| `Models/Terrain.py` | terrain generation + rendering (the big one) |
| `Models/TerrainStyle.py` | all terrain *configuration* — see below |
| `Models/Board.py` | the playable grid: `GridNode` graph, brush growth, owns the `Terrain` and `Weather` |
| `Models/Weather.py`, `Haze.py`, `Particles.py` | atmosphere layers |
| `Models/Card.py`, `AllCards.py` | cards and stones |
| `UI/`, `Utils/`, `Collections/`, `Tween/` | widgets, helpers, data structures, tweening |
| `docs/*.md` | design plans — **read the relevant one before starting terrain or board work** |
| `scratch/` | debug tools and previews. **Gitignored** |

## Concepts worth knowing before editing

**Terrain has two resolutions and they are kept strictly apart.** DATA SPACE is
the noise grid (`NoiseParams.size`, e.g. 450x256) where every physical field
lives — `height_map`, `moisture_map`, `temp_map`, `biome_mat`. RENDER SPACE is
`bounding_rect.size`, i.e. screen pixels. Images are produced *at* render size by
re-evaluating the fields there, never by upscaling a small picture — that is what
keeps biome edges crisp and glyphs unmagnified when the map is stretched. Most
terrain bugs are a data-space array used where render space was meant (it lands
as a small patch in the top-left corner) or a threshold that was not scaled
between the two.

**`TerrainStyle.py` is declarative only.** Knobs — thresholds, palettes,
per-biome style records, registries keyed by `Biome` — live there; anything that
computes lives in `Terrain.py`. It must never import `Terrain`. `Terrain.py`
re-exports every public name from it, so `from Models.Terrain import Biome,
NoiseParams, BIOME_GLYPHS, ...` is the import path callers use and the one to
keep working.

**Biome classification is a hard threshold on smooth fields.** `classify_biomes`
is a Whittaker (temperature x moisture) lookup with elevation overrides layered
on top, applied in a deliberate order (MOUNTAIN, then PLATEAU, then SNOW, then
LAKE). It is re-run at render resolution on every re-render — cheap because it is
fully vectorized, and that is *why* it is vectorized.

**Rendering is a per-object queue with `z_index`.** `add_to_render_queue(obj,
z_index=...)`; default 0 preserves the old flat ordering.

**The board is a graph, not just a lattice.** `GridNode` carries a `neighbors`
dict; the `(row, col)` indexing is a current convenience. `docs/routes-plan.md`
proposes replacing the lattice with terrain-derived sites and least-cost routes —
if the board's coordinate assumptions look load-bearing, that plan is why.

## Verifying changes

**Prefer headless assertions to screenshots.** `Terrain` builds standalone under
`SDL_VIDEODRIVER=dummy` (still needs `p.init()` + `p.display.set_mode((1,1))`
before any sprite loads). Building across several seeds and asserting on
`biome_mat` / `height_map` / `_render_biomes()` takes seconds and catches things
the eye does not — e.g. that a data-space and a render-space computation agree.
Screenshot only to judge how something *looks*.

Type checking:

```bash
uvx pyright
```

There is **no clean baseline** — expect ~100 pre-existing errors in `Utils/`,
`States/` and elsewhere (mostly numpy/pygame typing noise). The useful check is
that *your* files report zero and the total did not rise, not that the run is
green. `pyrightconfig.json` excludes `scratch/`, so debug tools are unchecked.

There is no test suite.

## Conventions

Comments in this codebase explain **why**, often at length, and frequently record
an approach that was tried and rejected and the reason. That is deliberate —
match it. A comment that restates the code is noise here; one that stops the next
person re-making a decision is the point. Several are load-bearing warnings (e.g.
why `SNOW` gets no contour, why a glyph `margin` cannot be lowered) — check for
one before "simplifying" a constant that looks arbitrary.

Design plans live in `docs/` and are written before the code. When starting
substantial work, read the matching plan and update it if the design moves.
