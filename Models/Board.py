from enum import Enum
import os
import random

from Game import Game
import pygame as p

from GameObject import GameObject
from Models.Card import Card, _tint_ink
from Models.Routes import Sites
from Models.Terrain import Biome, NoiseParams, SunParams, Terrain, TerrainMode
from Models.Weather import Weather
from Utils.Colors import BLUE, GREEN, WHITE

class BoardStates(Enum):
    IDLE = 1
    ADD_BRUSH_STATE = 2

class GridNode:
    def __init__(self, content: Card | None = None):
        self.content = content
        self.neighbors: dict[str, "GridNode | None" ] = {
            "north": None,
            "south": None,
            "east": None,
            "west": None
        }

def to_int_coords(vec: p.Vector2) -> tuple[int, int]:
    return (int(vec.x), int(vec.y))


class Board(GameObject):
    MAX_SIZE = 13
    SNAP_DIST = 52           # how close to a point a drop must be to place
    EDGE_LENGTH = 72
    # Deep blood red, NOT the map's brush black (Terrain.INK). The board and
    # the terrain are two different things drawn on the same paper, and in the
    # same ink they read as one drawing -- the grid looks like part of the map
    # rather than something laid over it. Dark enough to still read as ink on
    # parchment rather than as paint; the hue is what separates the layers.
    INK = (112, 26, 24)
    # Per-stroke lightness swing around INK. A brush carries a different load of
    # ink each time it's dipped, so no two lines are quite the same black.
    INK_LOAD_VARIATION = 18
    CURSOR_INK = (235, 232, 224)  # pale, to read against the dark strokes
    DEBUG_POINT_RADIUS = 6   # temporary extension markers; see render()
    STARTING_SIZE = 3
    INNER_STROKES = {
        0: p.image.load(os.path.join("Assets", "sprites", "ui", "board_lines", "board_line_1.png")), 
        1: p.image.load(os.path.join("Assets", "sprites", "ui", "board_lines", "board_line_3.png")),
        2: p.image.load(os.path.join("Assets", "sprites", "ui", "board_lines", "board_line_4.png")), 
        3: p.image.load(os.path.join("Assets", "sprites", "ui", "board_lines", "board_line_5.png"))
    }    # thinner

    def __init__(self, game: Game):
        super().__init__()
        self.game = game
        self.vertices: dict[tuple[int, int], GridNode] = {} # (r,c) -> Node
        self.cards: list[Card] = []
        self.board_state = BoardStates.IDLE
        self.brush_cursor = _tint_ink(
            p.image.load("Assets/sprites/ui/icons8-calligraphy-brush-50.png"),
            self.CURSOR_INK,
        )
        # The baked board picture. None means stale: it re-bakes on next render.
        self._board_surface: p.Surface | None = None
        # Origin of the FULL MAX_SIZE grid, centred on screen. The starting grid
        # is built around that grid's middle, so centring the full span centres
        # the starting grid too, and the board stays centred as it grows out.
        full_span = (self.MAX_SIZE - 1) * self.EDGE_LENGTH
        self.origin_abs_pos = p.Vector2(
            (game.GAME_W - full_span) / 2, (game.GAME_H - full_span) / 2
        )
        # stroke thickness -> list of (start, end) runs. Per-instance: rebuilding
        # the board must not stack duplicate runs on the previous board's.
        self.board_lines: dict[int, list[tuple[p.Vector2, p.Vector2]]] = {}
        self._show_extendable_nodes = False
        self._show_routes = False   # R toggles; T toggles the pruned overlay
        self._start_node_for_board_extenstion = None
        self._available_new_nodes = []
        self._build_starting_board()

        # --- TERRAIN ---
        self.terrain_map_size = (450, 256)
        self.terrain_rect = p.Rect((0, 0), (1800, 1024))
        self.terrain_rect.center = self.game.GAME_CENTER
        # TODO: noise.pnoise2's `base` indexes a 256-entry permutation table --
        # values outside [0,255] silently degenerate for ~1/3 of integers (one
        # axis of the noise becomes constant, i.e. visible stripes). Clamped to
        # 255 here as the immediate fix; the real fix belongs in NoiseParams /
        # generate_height_map itself (e.g. `seed % 256`) so no caller can hit
        # this footgun again.
        self.terrain = Terrain(
            height_noise_params=NoiseParams(self.terrain_map_size, seed=random.randint(0, 255)),
            moisture_noise_params=NoiseParams(self.terrain_map_size, seed=random.randint(0, 255)),
            sun_params=SunParams(),
            bounding_rect=self.terrain_rect
        )

        # --- WEATHER ---
        # Live layer over the baked map: clouds sitting on the peaks, snow
        # falling out of them. Everything about how it works is in
        # Models/Weather.py; all it needs from here is where the high ground is
        # and how big the terrain is drawn.
        #
        # Two different regions, deliberately. The CLOUD area is snow AND
        # mountain, weighted so the caps count for more -- weather gathers on
        # the cold high ground but still reaches down the flanks, so the range
        # reads as overcast rather than as one cloud on one peak. The SNOW
        # area is just the snowcaps: flakes are emitted uniformly over it (an
        # AreaSource, see Models/Weather.py), so snow lands on ground that is
        # actually snowy instead of anywhere the cloud happens to overhang.
        #
        # fog stays OFF: Terrain already bakes a static haze into the glyph map
        # (BIOME_HAZE), and the two do the same job of filling the paper between
        # glyphs. Both on double-tints the same gaps.
        aoi = (0.2 * Terrain.get_biome_mask(self.terrain.biome_mat, Biome.MOUNTAIN)
               + 1.4 * Terrain.get_biome_mask(self.terrain.biome_mat, Biome.SNOW))
        snow_mask = Terrain.get_biome_mask(self.terrain.biome_mat, Biome.SNOW)
        self.weather = Weather(aoi, self.terrain.render_size,
                               seed=self.terrain.noise_params.seed, fog=False,
                               origin=self.terrain_rect.topleft, snow_mask=snow_mask)

        self.sites = Sites.construct_sites(self.terrain, self.terrain_rect.size)
        # self.add_to_render_queue(self.sites, 10)

    def _build_starting_board(self):
        center_coords = p.Vector2(1, 1) * (self.MAX_SIZE - 1) / 2
        bottom_right_coords = center_coords - p.Vector2(1, 1) * (self.STARTING_SIZE - 1) / 2
        for row in range(self.STARTING_SIZE):
            for col in range(self.STARTING_SIZE):
                coord = bottom_right_coords + p.Vector2(row, col)
                self.vertices[to_int_coords(coord)] = GridNode()
        self._update_node_neighbors()
        self._calc_board_lines()

    def _get_node_new_neighs(self, coord):
        return {
                "east": (coord[0] + 1, coord[1]),
                "west": (coord[0] - 1, coord[1]),
                "north": (coord[0], coord[1] - 1),
                "south": (coord[0], coord[1] + 1),
            }

    def _update_node_neighbors(self):
        for coord, node in self.vertices.items():
            possible_neigh_coords = self._get_node_new_neighs(coord)
            for direction, neigh_coord in possible_neigh_coords.items():
                node.neighbors[direction] = self.vertices.get(neigh_coord) # if None it's fine, it remains None.


    def toggle_brush_mode(self):
        """Flip between IDLE and ADD_BRUSH_STATE. Shared by the brush button
        and the `A` key, so the two can't disagree about the current mode."""
        self.board_state = (
            BoardStates.IDLE
            if self.board_state == BoardStates.ADD_BRUSH_STATE
            else BoardStates.ADD_BRUSH_STATE
        )
        self._show_extendable_nodes = self.board_state == BoardStates.ADD_BRUSH_STATE

    def change_terrain_mode(self, new_terrain_mode: TerrainMode):
        self.terrain.change_mode(new_terrain_mode)

    def _in_bounds(self, coord: tuple[int, int]) -> bool:
        """Coords run 0..MAX_SIZE-1; outside that the grid would grow off the
        centred full span (and eventually off-screen)."""
        return all(0 <= c <= self.MAX_SIZE - 1 for c in coord)

    def _free_neigh_coords(self, coord: tuple[int, int]) -> list[tuple[int, int]]:
        """The in-bounds neighbour slots of `coord` that are still empty."""
        node = self.vertices[coord]
        return [
            neigh_coord
            for direction, neigh_coord in self._get_node_new_neighs(coord).items()
            if node.neighbors[direction] is None and self._in_bounds(neigh_coord)
        ]

    def _get_verts_with_at_least_one_free_neigh(self) -> list[tuple[int, int]]:
        # A vertex on the edge of the full grid has empty neighbours pointing off
        # it; those don't count, or it would offer candidates it can't place.
        return [coord for coord in self.vertices if self._free_neigh_coords(coord)]

    def _toggle_show_extendable_nodes(self):
        self._show_extendable_nodes = not self._show_extendable_nodes

    def update(self, dt: float):
        self.weather.update(dt)
        for event in self.game.events:
            if event.type == p.KEYDOWN:
                if event.key == p.K_a:
                    self.toggle_brush_mode()
                if event.key == p.K_s:
                    self._toggle_show_extendable_nodes()
                if event.key == p.K_r:
                    self._show_routes = not self._show_routes
                if event.key == p.K_t:
                    self.sites.show_substrate = not self.sites.show_substrate

        # The routes overlay is independent of brush mode. It used to be driven
        # by it alone, which meant the only way to look at the graph was to
        # enter a mode that also draws a brush cursor and candidate markers over
        # the thing being looked at.
        self.sites.show = (
            self._show_routes or self.board_state == BoardStates.ADD_BRUSH_STATE
        )

        if self.board_state == BoardStates.ADD_BRUSH_STATE:
            # actions["mouse_sx"] is the HELD state (1 down, 0 up, never -1);
            # clicked_sx is the edge (+1 on press, -1 on release). Both branches
            # want an edge, so latching on clicked_sx also stops the candidate
            # list being rebuilt on every held frame.
            if self.game.clicked_sx == 1:
                cursor = p.Vector2(self.game.cursorpos)
                for point in self._get_verts_with_at_least_one_free_neigh():
                    if cursor.distance_squared_to(self._coords2abspos(*point)) <= self.SNAP_DIST ** 2:
                        self._start_node_for_board_extenstion = point
                if self._start_node_for_board_extenstion is not None:
                    self._available_new_nodes.extend(
                        self._free_neigh_coords(self._start_node_for_board_extenstion)
                    )

            elif self.game.clicked_sx == -1:
                self._drop_new_vertex(p.Vector2(self.game.cursorpos))
                self._start_node_for_board_extenstion = None
                self._available_new_nodes.clear()

    def _drop_new_vertex(self, cursor: p.Vector2):
        """Place a vertex at the candidate nearest `cursor`, if one is in range.
        Nearest rather than every candidate in range: SNAP_DIST (52) is more than
        half EDGE_LENGTH (72), so a release between two candidates is within
        range of both and would otherwise add them both."""
        if not self._available_new_nodes:
            return
        nearest = min(
            self._available_new_nodes,
            key=lambda c: cursor.distance_squared_to(self._coords2abspos(*c)),
        )
        if cursor.distance_squared_to(self._coords2abspos(*nearest)) > self.SNAP_DIST ** 2:
            return
        self.vertices[nearest] = GridNode()
        self._update_node_neighbors()
        # Not just invalidate_board_surface(): the new vertex changes which runs
        # exist and how far they reach, and the bake draws from board_lines.
        # Re-baking stale geometry would redraw the identical picture.
        self._calc_board_lines()



    def _coords2abspos(self, row: int, col: int) -> p.Vector2:
        # col -> x, row -> y, offset from the grid origin.
        return self.origin_abs_pos + p.Vector2(col, row) * self.EDGE_LENGTH

    def _nearest_free_point(self, pos: p.Vector2):
        """Return (row, col, point) of the closest empty intersection within
        SNAP_DIST of `pos`, or None."""
        # TODO if this function happens to be called a lot, switch to a Quadtree implementation, much faster.
        best = None
        best_d = self.SNAP_DIST
        for r, c in self.vertices.keys():
            point = self._coords2abspos(r, c)
            d = pos.distance_to(point)
            if d < best_d:
                best_d = d
                best = (r, c, point)
        return best

    def _run_end(self, start: tuple, step: tuple) -> tuple:
        """Last vertex reachable from `start` stepping by `step` without a gap."""
        row, col = start
        d_row, d_col = step
        while (row + d_row, col + d_col) in self.vertices:
            row, col = row + d_row, col + d_col
        return (row, col)

    def invalidate_board_surface(self):
        """Call after anything that changes what the board looks like. The next
        render re-bakes; call it as often as you like, it costs nothing."""
        self._board_surface = None

    def _calc_board_lines(self):
        self.board_lines = {thickness: [] for thickness in self.INNER_STROKES}
        self.invalidate_board_surface()
        # One stroke per maximal straight run, not per segment — a brush sprite
        # gets stretched along the whole run, so a 3-wide row is 1 stroke, not 2.
        # A vertex heads a run only when nothing sits behind it in that
        # direction, which also splits runs correctly across gaps in the graph.
        for step in ((0, 1), (1, 0)):   # first draw the horiz then the vert lines
            d_row, d_col = step
            for row, col in self.vertices:
                if (row - d_row, col - d_col) in self.vertices:
                    continue            # mid-run, not the head
                end = self._run_end((row, col), step)
                if end != (row, col):   # skip lone vertices
                    # Seeded on the run's own geometry, not the global rng: this
                    # runs again on every vertex added, and an unchanged run must
                    # keep the stroke it already had rather than re-rolling.
                    thickness = random.Random(hash(((row, col), end))).randint(0, 3)
                    self.board_lines[thickness].append((
                        self._coords2abspos(row, col),
                        self._coords2abspos(*end)
                    ))

    def _stroke_ink(self, rng: random.Random) -> tuple[int, int, int]:
        """INK, lightened or darkened a little, for one stroke."""
        d = rng.randint(-self.INK_LOAD_VARIATION, self.INK_LOAD_VARIATION)
        return tuple(max(0, min(255, c + d)) for c in self.INK) # type: ignore

    def _bake_board_surface(self) -> p.Surface:
        """Draw every run onto one surface, once. The scale/flip/rotate/tint per
        stroke depends only on the board, not the frame, so it lives here rather
        than in render(). Its own seeded rng -> the same board every bake, and no
        reseeding of the global rng that everything else shares."""
        surf = p.Surface((self.game.GAME_W, self.game.GAME_H), p.SRCALPHA)
        rng = random.Random(1337)

        def blit_line(src: p.Surface, start: p.Vector2, end: p.Vector2):
            length = (end - start).magnitude()
            grow = rng.randint(6, 20)
            horizontal = (end.y == start.y)
            # Tint the black source per stroke, before scaling.
            stroke = _tint_ink(src, self._stroke_ink(rng))
            stroke = p.transform.smoothscale(stroke, (stroke.get_width(), length + grow))
            if rng.random() < 0.5:
                stroke = p.transform.flip(stroke, True, False)
            if horizontal:
                stroke = p.transform.rotate(stroke, 90)
            jitter = rng.randint(-2, 2)
            mid = (start + end) / 2
            # Nudge perpendicular to the run so strokes don't sit dead straight.
            center = mid + (p.Vector2(0, jitter) if horizontal else p.Vector2(jitter, 0))
            surf.blit(stroke, stroke.get_rect(center=center))

        for thickness, list_of_coords in self.board_lines.items():
            src = self.INNER_STROKES[thickness]
            for start, end in list_of_coords:
                blit_line(src, start, end)
        return surf

    # The crimson brush lattice is the last of the Go board, and the campaign
    # design replaced it: pieces stand on terrain-derived route nodes now, not
    # on grid intersections (see docs/campaign-and-duel.md). Drawn, it asserts a
    # second, contradictory board on top of the roads.
    #
    # The baking machinery below is kept rather than deleted -- `blit_line` is
    # the only brush-stroke renderer in the codebase, and the roads will
    # eventually want strokes instead of `p.draw.line`. Set this True to see the
    # old board again.
    SHOW_GO_LATTICE = False

    def render_board(self, surf: p.Surface):
        if not self.SHOW_GO_LATTICE:
            return
        if self._board_surface is None:
            self._board_surface = self._bake_board_surface()
        surf.blit(self._board_surface, (0, 0))

    def render(self, surf: p.Surface):
        self.terrain.render(surf)
        # Between the land and the board: weather sits over the map it falls
        # on, but under the pieces played on top of it.
        if self.terrain.mode == TerrainMode.GLYPHMAP:
            self.weather.render(surf)
        self.render_board(surf)
        # origin is not optional in practice: site positions are relative to the
        # terrain's own rect, and terrain_rect is CENTRED on the screen rather
        # than at (0, 0), so leaving it out shifts every site up and left by the
        # rect's topleft -- (60, 28) at the current size.
        self.sites.render(surf, origin=self.terrain_rect.topleft)
        if self.board_state == BoardStates.ADD_BRUSH_STATE and self.game.cursorpos:
            # Suppress Game's default circle cursor this frame; draw the brush instead.
            self.game.custom_cursor = True
            surf.blit(self.brush_cursor,
                      self.brush_cursor.get_rect(bottomleft=self.game.cursorpos))
        # --- temporary extension debug markers ---
        r = self.DEBUG_POINT_RADIUS
        if self._start_node_for_board_extenstion is not None:
            p.draw.circle(surf, GREEN, self._coords2abspos(*self._start_node_for_board_extenstion), r)
            for coord in self._available_new_nodes:
                p.draw.circle(surf, BLUE, self._coords2abspos(*coord), r)
        elif self._show_extendable_nodes:
            for row, col in self._get_verts_with_at_least_one_free_neigh():
                p.draw.circle(surf, WHITE, self._coords2abspos(row, col), r)
        # Last, so nothing draws over it.
        if self.terrain.mode is TerrainMode.COLOURMAP:
            self._render_biome_tooltip(surf)

    # Tooltip geometry. Offset from the cursor's hotspot so the box sits clear
    # of the pointer instead of under it.
    TOOLTIP_OFFSET = (16, 16)
    TOOLTIP_PAD = 6
    TOOLTIP_BG = (28, 24, 20, 216)
    TOOLTIP_FG = (238, 232, 220)

    def _render_biome_tooltip(self, surf: p.Surface):
        """Name the biome under the cursor, next to the cursor. COLOURMAP only:
        that view is a flat wash with no glyphs or labels, so which stain is
        which is otherwise guesswork -- the whole reason this exists is to make
        the mode readable while tuning thresholds."""
        if not self.game.cursorpos:
            return
        cx, cy = int(self.game.cursorpos[0]), int(self.game.cursorpos[1])
        biome = self.terrain.biome_at_render_px(
            cx - self.terrain_rect.left, cy - self.terrain_rect.top
        )
        if biome is None:  # cursor is off the map
            return

        font = self.game.fonts["inconsolata"]["small"]
        label = biome.name.replace("_", " ").title()
        text = font.render(label, True, self.TOOLTIP_FG)
        pad = self.TOOLTIP_PAD
        box = p.Surface(
            (text.get_width() + 2 * pad, text.get_height() + 2 * pad), p.SRCALPHA
        )
        box.fill(self.TOOLTIP_BG)
        box.blit(text, (pad, pad))

        rect = box.get_rect(topleft=(cx + self.TOOLTIP_OFFSET[0], cy + self.TOOLTIP_OFFSET[1]))
        # Flip to the other side of the cursor rather than letting the box run
        # off-screen -- near the right or bottom edge is exactly where you end
        # up when checking what the map does at its border.
        if rect.right > self.game.GAME_W:
            rect.right = cx - self.TOOLTIP_OFFSET[0]
        if rect.bottom > self.game.GAME_H:
            rect.bottom = cy - self.TOOLTIP_OFFSET[1]
        surf.blit(box, rect)