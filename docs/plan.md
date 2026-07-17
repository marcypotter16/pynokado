# Plan: Particles, Bloom, Graph Mechanics, and Stroke-Edge Softening

## Context

`pynokado` is a Go-inspired, ink/parchment strategy game built on pygame + moderngl.
The user wants to move it beyond a static "place a stone" test toward (a) a real,
distinctive two-player mechanic, and (b) a darker, older, more atmospheric look.
Four independent tracks were requested; this plan sequences them by risk/dependency
so each lands as a self-contained, testable slice:

1. **Stroke-edge softening** — the brush strokes/frames/circles were background-removed
   off-repo by hard white-keying, leaving aliased ("rough") alpha edges. Cleanly-cut
   strokes look smoother by comparison. Quick, isolated win — do first.
2. **Graph mechanics** — the actual game: a growable 4×4 graph, two colours (BLACK/RED),
   turn alternation, and a per-turn choice of **brush** (extend an edge to a new vertex)
   or **place a stone**. This is the heart of the work.
3. **GPU dust particles** — slow drifting motes for atmosphere (petals deferred).
4. **Bloom post-processing** — an offscreen FBO + bright-pass + separable blur + composite,
   to make dust glow and the whole scene read darker/older.

Design decisions confirmed with the user:
- **Edges are neutral scaffolding** (not owned/coloured); brushing only extends the graph
  and makes a new vertex *reachable*.
- **Ownership lives only on stones** (BLACK/RED = whose turn placed it); vertices are
  neutral until stoned.
- **Placement legality**: any existing, empty, graph-connected vertex — **invasion is
  allowed by design**; influence/combat balance is explicitly out of scope for v1.
- Board starts **4×4, expandable** up to a max bound; **BLACK and RED start on opposite
  corners**. Both players share the existing `ALL_CARDS` pool (a card just supplies stone
  art; the *player's colour*, not card faction, tints the stone).
- v1 is a **sandbox**: no win condition, no influence scoring yet.

---

## Ground-truth findings from exploration

**GL pipeline (`GLRenderer.py`, `Game.py`)**
- Everything renders to the **default framebuffer**; there are **no FBOs anywhere** yet.
  Bloom introduces the first ones.
- Reusable: the fullscreen-quad VBO + `VERT_SRC` vertex shader; the per-program-VAO pattern
  (`hover_glow` at `GLRenderer.py:95-112`).
- Per-frame order (`Game.py:218-244`): opaque canvas (`window_scaling`) → `post_render_callbacks`
  (additive glows) → transparent `fg_canvas` overlay (`window_scaling` again) → `flip`.
- New GPU passes hook in cleanly via `game.post_render_callbacks.append(bound_method)`
  (registered in state `__init__`; note: never removed — avoid duplicate stacking).
- `buff_sheen.glsl` is referenced but **does not exist**; that "buff" pass is dead. Only
  `window_scaling` (embedded) and `hover_glow.glsl` are live.

**Game state (`States/BoardTestState.py`, `Models/Card.py`, `AllCards.py`)**
- No Player / turn / ownership / graph layer exists — mechanics are greenfield.
- `self.points[r][c]` is a rigid full lattice; `self.stones: dict[(r,c)->{surf,pos,model}]`.
- `_build_board_surface()` bakes the *entire* grid once from tinted `board_line_*.png`
  strokes via `_tint_ink` (`Models/Card.py:65`). This must become **graph-driven** and
  **re-bakeable** when the graph grows.
- `make_stone(game, model, diameter)` (`Models/Card.py:74`) builds the round stone; colour
  currently derives from `card_model.faction` via `FACTION_INK`. Player colour must be able
  to override this (a tint param / variant).
- Input edges available: `game.clicked_sx`, `game.clicked_dx`, `game.cursorpos`.

**Assets / stroke edges**
- No background-removal code is in the repo; strokes were white-keyed off-repo (commits
  `2338925`, `790f80a`) → binary/aliased alpha. `_tint_ink` (`Models/Card.py:65-71`) copies
  source alpha verbatim; loaders crop to ink bbox with `get_bounding_rect(min_alpha=1)`.
- **No feathering / blur / smoothstep on sprite alpha anywhere.** `smoothstep` is only in
  `hover_glow.glsl`; `smoothscale` is the only softening and it can't restore keyed edges.
- Fix belongs in the **load path** (soften alpha once at load, cached), not per-frame.

---

## Track 1 — Stroke-edge softening (do first; isolated)

done: solution for now involves just changing the brush strokes to better ones.

---

## Track 2 — Graph mechanics (the game)

v1 = sandbox: two players (BLACK/RED) alternate; each turn is exactly one action, BRUSH or
PLACE. Growable graph over an integer grid, start 4×4 → max bound. No win/influence/combat.

### Data model (replaces the rigid `self.points` lattice)
Constants in `__init__`: `INIT = 4` (start block), `MAX = 12` (hard bound; no grown cell may
fall outside `[0, MAX-1]`), keep `CELL = 72`. Center `board_origin` on the **MAX** span (not
INIT) so the board doesn't drift as it grows.

```
self.verts:  set[(r,c)]                # active graph vertices (neutral)
self.edges:  set[frozenset({a, b})]    # undirected 4-adjacent edges (neutral scaffolding)
self.stones: dict[(r,c) -> {"owner","surf","model","pos"}]   # ownership lives ONLY here
```
`frozenset` edges give free undirected dedup/lookup. Occupancy = membership in `self.stones`.

Derive screen positions (delete the `self.points` matrix; replace every read):
```
def _pt(self, r, c): return self.board_origin + p.Vector2(c*self.CELL, r*self.CELL)
```
Helpers: `_in_bounds(r,c)` (`0<=r,c<MAX`), `_neighbors(r,c)` (4-adjacent in-bounds),
`_cell_under(cursor)` (round `(cursor-origin)/CELL`, accept within `SNAP_DIST`; picks over the
FULL integer grid, needed to target empty non-vertex cells).

**Reachability simplification (deliberate, v1):** because BRUSH only grows from an existing
vertex, the scaffold stays one connected mass, so placement "reachable" reduces to
`cell in self.verts`. A real BFS is deferred until disconnected fragments are possible.

### Turn / player model (inline in the state; no new file for v1)
```
PLAYER_COLORS = {"BLACK": (24,22,20), "RED": (150,24,28)}   # stone/board tint per player
class Player: key ("BLACK"/"RED"), color (RGB)
self.players=[Player("BLACK",…), Player("RED",…)]; self.turn=0
self.brush_src=None; self.acted_this_turn=False
current() -> players[turn % 2]
_end_turn(): turn+=1; brush_src=None; acted_this_turn=False
```
One action per turn: a **successful** PLACE or BRUSH sets `acted_this_turn`, then `_end_turn()`.
Failed/cancelled attempts do NOT end the turn.

### Start setup
Seed the `INIT×INIT` block fully connected (add verts + left/up edges). Place two home stones
via `_place`: BLACK at `(0,0)`, RED at `(INIT-1, INIT-1)` (opposite corners), owner-coloured.

### Input mapping (least new machinery — reuse existing drag-drop)
- **LEFT-drag a hand card → PLACE** (existing `Card.update` drag + drop-resolve, unchanged feel).
- **RIGHT-click (`clicked_dx==1`) → BRUSH**, a two-click state machine:
  1st right-click on an existing vertex → set `brush_src` (highlight); 2nd right-click on a
  4-adjacent, in-bounds, **new** (non-vertex) cell → commit edge+vertex. Invalid/elsewhere →
  cancel `brush_src`, no turn spent.
  Both actions gated by `not self.acted_this_turn`. `action_mode` becomes implicit (kept only
  as a HUD label). Explicit BRUSH/PLACE toggle UI deferred.

### Concrete method changes in `BoardTestState.py`
- **`_place`** → new signature `(_place(self, r, c, model, owner, from_card=None)`); builds the
  stone via `make_stone(..., tint=owner.color)`, stores `owner`. **Shared-pool semantics:** do
  NOT remove the card from the hand — cards are reusable art stamps; the card tweens home after
  a successful place (board keeps its own `surf`).
- **`_nearest_free_point`** → replaced by **`_legal_place_target(pos)`**: nearest cell within
  `SNAP_DIST` that is in `self.verts`, not in `self.stones` (iterates the small `verts` set,
  not the full lattice); returns `(r,c)`.
- **`_try_brush(cursor)`** — NEW (the two-right-click state machine above); on commit adds vert
  + edge, re-bakes the board, `_end_turn()`.
- **`_build_board_surface`** → graph-driven: iterate `self.edges`, draw one tinted brush stroke
  per edge (reuse existing `blit_line`; horizontal vs vertical from whether rows or cols
  differ); ink dots at each `self.verts` cell; keep seeded splats. **Stability:** iterate edges
  in a deterministic sorted order and re-seed per rebuild so existing edges render identically
  after each brush (no re-jitter). Drop the border/inner distinction (all edges use `inner`
  strokes) for v1. Re-baked from `_try_brush` (infrequent, discrete — fine off the frame path).
- **`update`**: gate grab/place on `not acted_this_turn`; drop-resolve via `_legal_place_target`
  → `_place(...)` + `_end_turn()`; preview via `_legal_place_target`→`_pt`; add
  `if clicked_dx==1 and not acted_this_turn: _try_brush(cursorpos)`.

### `Models/Card.py` change — player-tinted stone
`make_stone(game, card_model, diameter, ring_file="ink_circle.png", tint=None)`: when `tint`
is given, use it for the ring/ink instead of `FACTION_INK.get(...)`. Interior art disc stays
the card art (piece identity); only the ring adopts the player colour. Default `None` =
current behaviour, so nothing else breaks.

### HUD / feedback (reuse `draw_centered_text` + hover-glow pass)
Turn banner top-center: `f"{current.key}'s turn"` in `current.color`, plus a hint line
`"Left-drag card = place · Right-click = brush"`. Highlight `brush_src` (ring/glow in
`current.color`, reusing the glow-entry format from `_render_hover_glow`). Keep the existing
ghost preview for PLACE but only when `_legal_place_target` is non-None.

**Files:** `States/BoardTestState.py` (bulk), `Models/Card.py` (`make_stone` `tint` param).

### Smallest playable slice first, then grow
1) graph structs + `_pt` + seed INIT block + two home stones → 2) `Player`/`turn`/`_end_turn`
→ 3) PLACE via left-drag + `_legal_place_target` + tinted stone + end turn → 4) BRUSH
right-click state machine + graph-driven re-bake → 5) turn-banner HUD.
**Defer:** BFS reachability, explicit mode-toggle UI, border-stroke styling on grown edges,
any win/influence/combat/scoring, card economy/undo, edge-growth animation, `Player` in its
own file.

> **Refactor in progress:** the graph is being extracted into `Models/Board.py` with an
> explicit `GridNode` (per-node `neighbors` dict) + a `Board` owner. This supersedes the
> `set[(r,c)]` / `set[frozenset]` sketch above — same *semantics* (neutral verts/edges,
> ownership only on stones), different representation. Decisions made for `Board.py`:
> - **Index:** `dict[(r,c) -> GridNode]`, and each `GridNode` carries `rc = (row,col)`.
>   (Neighbor pointers alone can't author a terrain map, position vertices, or answer
>   "what's at (2,3)"; the coordinate index is needed for terrain + render + growth.)
> - `GridNode` gains a `terrain` field (see Track 2b).

---

## Track 2b — Terrain (map semantics on the graph)

**Why:** the abstract graph is symmetric and directionless. Terrain gives vertices meaning —
mountains/rivers/forests — so cards can have terrain-keyed effects and players get a
**direction to push** (e.g. race to control the mountain before the opponent). Composes with
the graph: terrain is per-vertex data; no new subsystem.

**Model (v1):**
- `Terrain` = a small set of string/enum tags: `PLAIN, MOUNTAIN, RIVER, FOREST` (extensible).
- Lives on `GridNode.terrain` (a **vertex tag** for v1 — rivers flavor the tile and trigger
  card effects but do NOT block brush growth yet; promoting rivers to an **edge** property
  that blocks/costs crossing is deferred).

**Source — seeded procedural, as a pure function of coordinate:**
- `terrain_at(seed, r, c) -> Terrain` — a deterministic function over the **whole** `MAX×MAX`
  coordinate space (hashed seed + value/simplex noise, thresholded into terrain bands).
- **Why pure-of-coordinate (not random-at-creation):** the graph *grows* by brushing, and the
  board re-bakes. Terrain must be stable per `(r,c)` across growth and rebuilds and identical
  run-to-run for a given seed. So evaluate `terrain_at` **lazily** when a `GridNode` is created
  (store the result on the node); never roll fresh randomness per placement.
- Bonus: because terrain is only *seen* as the graph expands into it, seeded generation gives a
  light **fog-of-exploration** feel that reinforces "push toward the mountain".

**Payoff hooks (design now, wire as cards need them):**
- **Card effects** read `node.terrain` at resolution (e.g. `+strength` on MOUNTAIN, ignore
  RIVER). Pure lookup — no new machinery.
- **Directional objective:** tag some vertices as goals (mountains); first to control one
  grants a bonus. This is what gives the symmetric board intent.

**Rendering:** terrain drawn *under* stones during the graph-driven board bake — a faint
per-tile tint / glyph / texture on the parchment (blue-ish RIVER cell, mountain glyph, etc.).
Slots into the same re-bake as edges/dots.

**Files:** `Models/Board.py` (`Terrain`, `GridNode.terrain`, `terrain_at(seed,r,c)`, lazy
assignment on node creation), board-bake rendering of terrain, and later `Models/Card.py` for
terrain-keyed effects.

**Defer:** river-as-edge (blocking/cost), procedural tuning/balancing, goal-vertex bonus
scoring, terrain reveal animation.

---

## Track 0 — Per-state render stack (infrastructure; do early)

**Why:** renders are scattered across classes (`Board`, `Card`, stones, cursor, glow) and
"who draws last" is implicit in call order across files — fragile and hard to reason about
(the mouse-cursor-on-top-of-brush bug was exactly this). Centralize *ordering* so each object
declares a z-priority and Game/State draws everything in one sorted pass.

**Mental model (user's):** states are Godot-like *scenes*, not game objects. So the render
stack lives **on `State`**, each state owns its own subscribers, and teardown is automatic
when the state is popped. **Retained mode** (objects subscribe once and persist) — consistent
with the existing retained-mode UI (`UICanvas`), NOT immediate mode.

**Current state of the code (finish, don't duplicate):**
- `Game.render_stack = {"background","foreground","above_all"}` (Game.py:103) exists but
  `Game.render()` (Game.py:221) **never iterates it** — it calls `state_stack.top().render()`
  directly. Dead scaffold.
- `State` appends `self.render` into `game.render_stack[layer]` on `enter_state` — also unused.
- `State.render_stack = Stack()` (State.py:32) is a second, unused field. `Stack` is LIFO with
  front-insert `push` — **wrong structure** for z-ordered drawing.

**Design:**
- A small `RenderStack` (new, e.g. `Collections/RenderStack.py` or inline in `State`): holds
  `(z, obj)` entries; `subscribe(obj, z=0)`, `unsubscribe(obj)`, and `render(surface)` that
  draws every subscriber in ascending z (stable for equal z = insertion order). `obj` is
  anything with `render(surface)`.
- Replace `State.render_stack = Stack()` with this `RenderStack`. `State.render(surface)` fills
  bg, then delegates to `self.render_stack.render(surface)` (canvas subscribes too, at a low z).
- Objects subscribe to **their state's** stack: e.g. `state.render_stack.subscribe(self.board,
  z=10)`, cards at a higher z, cursor/overlays highest. `Board`/`Card`/etc. lose their ad-hoc
  render call sites; they just expose `render(surface)` and subscribe once in the state's
  `__init__`.
- **Teardown:** because the stack is owned by the state, popping the state drops it — no leak
  (contrast the never-removed `post_render_callbacks`, which this pattern should eventually
  replace for glow passes too).
- **Remove the dead `Game.render_stack` dict** and the `State` registrations into it, OR
  repurpose Game's three buckets as coarse z-bands — recommend deleting to avoid two systems.

**Interaction with the GL pipeline:** the per-state stack composes the CPU `game_canvas`
(what today's `state.render()` produces). The GL passes (background upload, glow callbacks,
fg overlay) are unchanged — the render stack only reorganizes *how the canvas is assembled*,
not the GL flip. The `custom_cursor` flag added for the brush cursor can later become just a
high-z cursor subscriber.

**Files:** `States/State.py` (swap `Stack`→`RenderStack`, delegate in `render`), new
`Collections/RenderStack.py`, `Models/Board.py` + `Models/Card.py` (subscribe instead of being
called directly), `Game.py` (delete dead `render_stack` dict). Migrate one state first
(`BoardTestState`) as the reference, then the rest.

**Verify:** run the board; confirm draw order is correct (board < stones < cards < cursor),
the brush cursor sits above everything, and popping a state leaves no dangling renders.

**Defer:** converting the glow `post_render_callbacks` to the stack; z-bands/named layers on
top of raw z (add only if raw z gets unwieldy).

---

## Track 3 — GPU dust particles

**Goal:** slow drifting dust motes for atmosphere; build the emitter generically so a
**petal** preset can be added later.

**Approach:** mirror the `hover_glow` pattern in `GLRenderer.py`:
- New `particles.glsl` (+ vertex shader; the existing `VERT_SRC` is for the fullscreen quad —
  particles need a **per-particle attribute VBO**, so add a small dedicated vertex shader that
  places point sprites / small quads from instance attributes: position, size, seed, alpha).
- New program + its own VAO + a per-particle VBO in `GLRenderer.__init__`.
- A `render_particles(...)` method setting uniforms (`u_time`, `u_res`, wind/params); CPU
  side advances a lightweight particle array (can reuse the existing tween/update tick for
  time). Soft round motes via a radial falloff in the fragment shader (cheap; no texture).
- Register a bound callback in the board state via `game.post_render_callbacks.append(...)`
  so dust draws between background and foreground.

**Design for reuse:** parameterize emitter (count, size range, drift/wind, alpha, colour) so
a `petals` preset (textured/rotating quads) slots in later without restructuring.

**Files:** `GLRenderer.py` (+ new `particles.glsl`), `States/BoardTestState.py` (register
callback + per-frame update). Petals deferred.

**Verify:** run the board; confirm dust drifts slowly, is subtle, and costs one draw call.

---

## Track 4 — Bloom post-processing (introduces the first FBOs)

**Goal:** a soft bloom pass so dust motes glow and the scene reads darker/older.

**Approach (first FBO scaffolding in the codebase):**
- In `GLRenderer.__init__`, create offscreen FBOs at **full game resolution** (not the
  letterboxed viewport): one scene target + two ping-pong targets for separable blur.
- Render the scene (currently `render()` → default FB) into the **scene FBO** instead.
- Add programs: **bright-pass** (threshold/knee), **separable Gaussian blur** (horizontal +
  vertical, ping-ponging between the two FBOs), and a **composite/tonemap** pass that draws
  the fullscreen quad to `ctx.screen` combining scene + blurred bloom, applying the
  letterboxed `self.viewport` **only** on this final pass.
- Reuse the existing fullscreen-quad VBO + `VERT_SRC` for all these passes.

**Ordering note:** particles should be captured by bloom, so dust must render into the scene
FBO *before* the bright-pass. This reorders the pipeline (scene+glows+particles → FBO →
bloom → composite → foreground overlay). Foreground `fg_canvas` (crisp dragged card) should
composite **after** bloom to stay sharp.

**Files:** `GLRenderer.py` (FBOs, passes, reordered render), new `bloom_bright.glsl`,
`blur.glsl`, `bloom_composite.glsl`, and small changes in `Game.py` render loop for ordering.

**Verify:** run the board with dust; confirm motes bloom, edges of bright ink glow softly,
no letterbox/viewport artifacts, and the crisp foreground card is unaffected.

---

## Overall verification

- Track 1: visual before/after of stroke edges (headless render to scratchpad PNG).
- Track 2: launch `main.py`; play a few turns — alternate colours, brush to grow the graph,
  place stones on connected vertices, confirm illegal placements are rejected and the HUD
  reflects turn/action.
- Track 3/4: launch `main.py`; observe dust + bloom live; check frame time stays reasonable
  (`show_stats`).

## Sequencing / deferral

1. Track 1 (quick, isolated) → 2. Track 2 smallest playable slice, then BRUSH growth →
3. Track 3 dust → 4. Track 4 bloom (depends on particles for the payoff, adds FBOs).
Deferred: rose petals; influence/combat/win rules; retreat action; per-player hands/decks.
