# Plan: campaign map and tactical duel

## Why

The game was Go-derived: identical stones on a lattice, meaning carried entirely by
position. Two things killed that, and both are worth recording because they are the reason
this document exists rather than an extension of `docs/routes-plan.md`.

**The lattice fought the map.** That is the diagnosis `routes-plan.md` opens with, and the
graph it proposes is the fix. Nothing here contradicts it.

**Cards are not stones.** This is the new one. Go is beautiful *because* every stone is
identical — all meaning comes from position, and none from the piece. Our pieces have
`strength` 4..10, a `faction`, and art. The moment pieces are asymmetric, position stops
carrying the game on its own and Go's elegance is gone: what is left is a mediocre
area-control game with card stats bolted onto it. Placing cards on graph nodes and calling
captures "cutting a road" was considered and set aside for exactly this reason (see the
appendix) — it is not a tuning problem, the two ideas are incompatible at the root.

So the board stops being where cards are *played* and becomes where armies *move*. The
structure is Heroes of Might & Magic III, not Total War: tokens move on a terrain map,
contact opens a short tactical fight, and the army you spend is the army you keep.

## The shape of a session

```
  campaign map            contact              duel                back to map
  tokens move    ---->   two enemy    ---->   60-90s card   ---->  spent cards gone,
  on the graph            tokens meet          battle              loser retreats
        ^                                                               |
        +---------------------------------------------------------------+
```

Two layers, and each has to answer for itself:

| Layer | The decision | Time |
|---|---|---|
| Campaign | where to go, what to avoid, when to accept a fight | most of the session |
| Duel | how *cheaply* to win this one | 60-90 seconds |

## The joint that makes or breaks it

**The duel must inherit the terrain of the place it happens.** If it does not, the map is
decoration again — just decoration one level up, scheduling fights instead of hosting them,
and it will still read as a 4X. This is the single load-bearing claim in the document.

Concretely, the encounter node already carries everything needed:

| Duel property | Comes from | Field that exists today |
|---|---|---|
| What the rows *are* | biome at the encounter node | `Waypoint.biome` |
| How many slots per row | terrain openness | `Waypoint.slope`, node degree |
| Which cards may deploy where | per-card affinity | new: `CardModel.biome_bonus` |
| Who deploys second | who arrived by the cheaper road | `WaypointEdge.cost` |
| Whether a route may be taken at all | boat-capable or not | new: `CardModel.water_travel` |

`water_travel` is the only hard gate in that table; everything else is a modifier. It is
also the reason `routes-plan.md` now *keeps* water edges in the graph rather than excluding
them: a lake crossing is a real route that only some pieces may use. That makes a
boat-capable card a **mobility** card rather than a combat one, which is a kind of card the
design otherwise has no slot for.

Worked example. Meet on a SHORE node: the rows are water / shore / inland, and a card with
no water affinity simply cannot take the front row. Meet at a **pass** (the cheapest border
cell between two regions, which Phase 2 of `routes-plan.md` computes for free): two rows
only, and both narrow — so raw card count stops deciding the fight and card quality starts
to. Arriving downhill grants second deployment, which is an advantage earned on the map
rather than granted by the duel.

None of that is a new system. It is lookups against fields that are already computed and
cached.

## The economy: why 90 seconds is enough

Gwent's foundation is the three-round card economy — a fixed hand for the whole match, and
passing as a real decision. That is also why a Gwent match runs 10-15 minutes. A 90-second
duel cannot hold it.

So the economy moves up a level:

> **Your deck is your army for the entire campaign.** Cards committed to a duel are spent —
> exhausted, wounded, gone — until you rest at a SETTLEMENT.

Now the short duel is fine, because the interesting question was never "how do I win this
fight". It is *how cheaply* — with another enemy two nodes east and the Drake still in hand.
That is Gwent's pass-or-commit tension exactly, relocated from the round to the campaign.

The consequences are all good and all load-bearing:

- **Pass becomes the escape hatch.** A player caught on terrible ground can fight badly,
  pass early, spend almost nothing and retreat. Losing a fight you should not have taken
  costs tempo and position, not your army. This is what stops terrain disadvantage from
  being a death sentence — see the ceiling below.
- **SETTLEMENT sites acquire a purpose** beyond being a dot on the map. They are where the
  army comes back. That makes the settled parts of the map contested for a reason that
  falls out of the terrain generator.
- **The visual problem solves itself.** The duel screen is cards at full size; the map only
  appears between fights. The current 1800x1024 map filling the screen while 200x300 cards
  live somewhere off it is exactly what makes the game read as Civ, and this splits them
  into two screens that each have one job.

## Deckbuilding is route planning

The strongest consequence, and the reason to build this rather than something else.

If ancient cards are strong near Sites, then **choosing an ancient deck is choosing to fight
along the site chain.** A monster deck wants deep forest and avoids settled ground. A tech
deck wants the cheap edges — the roads — and falls apart off them. The deck is not a
loadout, it is a declared intention about geography.

The factions map onto the three axes the terrain actually has, which is luck but worth
exploiting:

| Faction | Scales with | Field |
|---|---|---|
| tech | low edge cost — roads, connected ground | `WaypointEdge.cost` |
| monster | distance from settlement, depth in forest | `_edt(FORESTED)` |
| ancient | proximity to a Site, any kind | `SiteKind` |

And because the map is generated per seed, **the correct deck differs every campaign.** The
opening move of a session becomes: look at the map, then build the deck. That is an unusual
and good opening for a card game, and it is the payoff for having a real generator.

## Guard rails

Three numbers that will decide whether this works, recorded now so they are tuned
deliberately rather than discovered by accident.

**1. The modifier ceiling.** Terrain should swing roughly a third of a card's value, never
double it. If terrain is stronger than that, the fight is decided before a card is played,
the duel is a formality, and the micro layer dies — the failure mode is a game that is
secretly Risk with a longer animation. The macro should make fights *favourable*, not
*decided*.

**2. Duels per campaign.** Risk can have fifty battles because its micro is a dice roll with
no decisions in it. Ours has real decisions and real time cost, so the count has to be low
— target roughly 8-15 duels per campaign. If the map generates more contact than that, the
session drags regardless of how good any single duel is.

**3. Rest rate.** How fast SETTLEMENT restores spent cards is what sets the whole game's
attrition curve, and it is the knob to reach for first when campaigns feel too forgiving or
too brutal. Do not tune the duel to fix an attrition problem.

## Showing a piece move

The map is ink on parchment and everything drawn on it is flat, unlit and hand-stroked. A
small 3D model walking around would be the only lit, perspective-projected object in a
deliberately flat drawing — it would read as a game piece sitting *on top of* a picture,
which is the same mismatch the lattice had and which this whole redesign exists to fix. It
also costs a whole subsystem the renderer does not have: model loading, skeletal animation,
a lit shader, depth against a painter's-algorithm `z_index` queue, a camera — none of which
a top-down flat map gives any perspective to justify. **Draw it in ink.**

The reference is the Marauder's Map, and its actual insight is that it shows **no figure at
all** — footprints and a name, in ink, on the map's own paper. That is the right answer here
for a concrete reason beyond taste: the map draws at 1800x1024, so a piece is small, and a
24px walking sprite at that size is mush while a footprint trail and a label read at any
scale.

- **The piece** is `make_stone`'s output: a round faction-inked disc with the card art in it.
  Already built.
- **The motion** is a trail of ink footprints behind it, fading over time.

Four cheap tricks carry the whole animation, and none of them needs a frame of art:

- **Alternate the prints left/right**, offset perpendicular to the direction of travel. This
  single detail is the entire gait illusion — without it a trail reads as a dotted line,
  with it the eye sees walking.
- **Stride length is speed.** Walking and running differ only in the spacing between prints
  and how fast the stone moves. A 3D model needs a second animation cycle for this; here it
  is one number.
- **Bob the stone** on a small sine as it travels, so it does not slide.
- **Fade prints IN, not just out** — ink blooming into paper rather than appearing. The
  alpha work for this already exists in `Utils.Image.soften_alpha`.

The first pass needs **no asset at all**: a footprint can be a small ink ellipse drawn with
`p.draw.ellipse`, tinted through `FACTION_INK`. Only replace that with real art once the
motion feels right, so the question "does this read as walking" is never confused with "is
this a good drawing of a foot".

**The trail is a mechanic, not decoration.** Footprints that fade over time are a record of
where someone has *been* — so tracking an enemy, reading which route they took, and noticing
that something passed through a valley an hour ago all fall out of the same feature. That is
scouting information carried by the art rather than by a UI layer, which is the cheapest
kind. How long they persist is therefore a balance knob, not a visual one.

## What has to be finished first

This design wants a *real* travel cost. Half of that is now in place:

- **Done.** `Sites._build_edges` runs the real cost flood. `WaypointEdge.cost` is a genuine
  integrated travel cost, within ~1% of true Dijkstra, and each edge also carries its
  `pass_rc` and a `crosses_water` flag. The Euclidean partition and the `calc_edge_cost`
  endpoint-gradient placeholder are both gone.
- **Done.** Phase 3 pruning. The 6–8% of edges whose cost is far above what their length
  predicts are gone, water crossings are exempt (they are expensive by design, not bad), and
  the graph is still connected on every seed tested.

So the routes pipeline is complete and both things the campaign layer needs are now real:
`WaypointEdge.cost` for deployment order, march time and the tech faction bonus, and the
edge *set* for where a token may actually go.

Two properties to design against, both established by measurement (see
`docs/routes-plan.md`, Phase 3):

- **Minimum node degree is now 1.** Pruning creates dead ends. A spur ending at a peak is a
  real road network, but anything assuming every node has a way onward is wrong — which
  includes the wandering pawn in `BoardTestState` and, more importantly, any retreat rule
  that assumes a defeated piece can always fall back.
- **The map is smoother than the plan assumed**, so there is no dramatic separation between
  good and bad routes. Chokepoints will have to be *made* interesting by mechanics rather
  than discovered in the terrain — which weakens the "pass as a natural strategic object"
  idea above. Worth checking against a generated map before building a mechanic on it.

## Build order

**Step 0 — the falsification test.** Two tokens on the existing graph, arrow keys to move,
and on contact open a stub screen that prints the node's biome, slope, height and the
incoming edge cost as a proposed row setup. **No card logic at all.**

The only question being answered: does reading that screen make you think *"I should have
gone around the mountain"*? If yes, the design works and the rest is content. If it reads as
noise, terrain is not affecting the duel enough, and that is worth finding out in an
afternoon rather than after a combat system exists.

Only if step 0 passes:

1. `CardModel` gains `biome_bonus`, `max_slope`, and a faction scaling rule. Hand-author it
   on three cards from `AllCards.py` — one per faction — and nothing else.
2. The duel screen: rows derived from the encounter node, deploy, resolve, pass.
3. Spend-and-rest: cards leave the deck on commit, return at a SETTLEMENT.
4. Only then, deckbuilding as a pre-campaign screen.

`Board.py`'s lattice and brush growth are dead weight under this design, but they are not in
the way either — leave them until step 2 needs the screen.

**`make_stone` is not dead weight — it is the campaign token.** It already renders a card as
a round faction-inked disc with the art inside, which is exactly what a piece moving on the
map should look like, so the character representation is a solved problem that just has not
been pointed at this yet. Movement is drawn as an ink footprint trail behind it (see
"Showing a piece move" below).

## Open questions

- **Whose turn is it on the map?** Simultaneous movement with contact resolution, or strict
  alternation. Affects whether an ambush is possible, which affects how much the terrain
  advantage is worth.
- **Do the AI's tokens build decks too?** If they do, the AI's deck should be read off the
  terrain it spawns in, which makes it legible to the player — you can tell what the forest
  faction is holding because it lives in a forest.
- **Map validation.** `routes-plan.md` already raises this and it matters more now: a
  campaign on an unfair map is a wasted session, not just an ugly one. Validate and reroll
  before building mechanics on top, or every judgement below is made on lucky samples.

---

## Appendix: options considered and set aside

**Go on the terrain graph.** Stones on graph nodes, capture as cutting a road, territory as
the Voronoi cell. Attractive because node degree varies — a pass has degree 2 and is
naturally cuttable — so chokepoints would be valuable with no new rule. Set aside for the
reason in the "Why": Go's elegance requires identical pieces, and ours are not. The degree
argument also cuts the other way, since a degree-2 node is not a chokepoint the player
*earned*, it is a piece lost to map luck.

**Provinces / cost-weighted Voronoi as the board.** The `owner` array from the flood is
already a partition; play cards into provinces, control spreads along edges. Set aside as
the most Civ-shaped of the options — it is the direction to take only if the decision is to
lean into that read rather than fight it.

**The map as the deck.** Every Site becomes a card, players draft off the map, the map
depletes as it is drafted. Elegant, needs no board logic, makes the seed the whole
replayability engine. Set aside because every decision happens before play begins — the map
becomes a draft menu, and the goal is a strategic card game rather than a good drafting
screen.

**Route lanes as a standalone design.** Routes between two capitals as Gwent-style rows, the
map generating the lanes. Not rejected — *absorbed*. It is what the duel screen should look
like when the encounter happens along a road rather than at a single node, and it is the
natural shape for step 2.
