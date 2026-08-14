"""Campaign-map pieces: a solid pawn standing on the paper map.

Two things live here and neither of them touches OpenGL -- geometry generation
and per-piece state. The GL pass that draws them is `PawnRenderer.py`. Keeping
the split means the mesh can be built and asserted on headlessly, with no
window and no context.

WHY A SOLID PIECE ON A FLAT DRAWING. The map is deliberately flat ink on
parchment, and an animated 3D *character* would fight that -- it would read as
something composited onto a picture. A pawn is not a character: it is the
virtual equivalent of the physical piece you put on a board to mark a position,
and a solid object resting on a paper map is what a tabletop game actually looks
like. The flatness of the map and the solidity of the piece are the two halves
of that look, not a contradiction in it.

WHY THE MODEL IS GENERATED, NOT LOADED. A pawn is a surface of revolution, so
the whole shape is one list of (radius, height) points spun about the Y axis.
That means no model format, no loader, no dependency, exact analytic normals --
and, the actual point, the silhouette is tuned by editing numbers in this file
rather than by opening Blender and re-exporting.
"""

from dataclasses import dataclass, field
import math

import numpy as np

Coords = tuple[int, int]

# The pawn's silhouette: (radius, height), base first, spun about Y.
#
# Heights run 0 -> 1 so `Pawn.size_px` is literally the piece's height on screen
# and the profile can be reshaped without rescaling anything downstream. Radii
# are in the same units, so 0.3 at the base means the foot is 30% as wide as the
# piece is tall -- roughly a chess pawn, which is stable-looking without eating
# much of the map.
#
# The two waists (0.100 at y=0.300 and 0.105 at y=0.585) are what make it read
# as a turned wooden piece rather than a cone. Do not flatten them out: the
# narrow neck under the head is most of the silhouette's character, and it is
# the part that survives being drawn 40px tall.
PAWN_PROFILE: tuple[tuple[float, float], ...] = (
    (0.000, 0.000),   # centre of the base
    (0.300, 0.000),   # base rim
    (0.300, 0.045),   # rim wall
    (0.255, 0.075),   # bevel inward
    (0.135, 0.150),   # into the stem
    (0.100, 0.300),   # narrowest point of the stem
    (0.112, 0.420),   # stem swelling toward the collar
    (0.165, 0.500),   # collar underside
    (0.175, 0.530),   # collar edge
    (0.105, 0.585),   # neck
    (0.150, 0.660),   # head underside
    (0.185, 0.760),   # head at its widest
    (0.150, 0.860),   # head narrowing
    (0.085, 0.940),   # crown
    (0.000, 1.000),   # top
)

# How many times the profile is copied around the axis. 32 is well past the
# point where the silhouette stops looking faceted at the sizes this draws at
# (~40px tall), and the whole mesh is still under a thousand triangles.
PAWN_SEGMENTS = 32


def pawn_mesh(
    profile: tuple[tuple[float, float], ...] = PAWN_PROFILE,
    segments: int = PAWN_SEGMENTS,
) -> tuple[np.ndarray, np.ndarray]:
    """Spin `profile` about the Y axis into a mesh.

    Returns `(vertices, indices)` where vertices is (N, 6) float32 of
    (px, py, pz, nx, ny, nz) and indices is (M, 3) uint32.

    Normals are ANALYTIC, not averaged from face normals. For a surface of
    revolution the outward normal at a profile point lies in the same (r, y)
    half-plane as the point, perpendicular to the profile's tangent there, so it
    can be written down exactly: tangent (dr, dy) -> normal (dy, -dr). Averaging
    face normals would approximate that same vector, more slowly and less well
    at the poles.

    The seam is DUPLICATED -- there are `segments + 1` columns, the first and
    last at the same angle. Wrapping the index buffer around to column 0 instead
    would share those vertices, which is fine for position and normal but makes
    any future per-vertex UV discontinuous across the seam. One extra ring of
    vertices is cheaper than that problem.
    """
    prof = np.asarray(profile, dtype=np.float64)
    if prof.ndim != 2 or prof.shape[1] != 2:
        raise ValueError(f"profile must be (N, 2) of (radius, height); got {prof.shape}")
    if len(prof) < 2:
        raise ValueError("profile needs at least two points to sweep")
    if segments < 3:
        raise ValueError("a surface of revolution needs at least 3 segments")

    r, y = prof[:, 0], prof[:, 1]

    # Central differences along the profile give the tangent at each point, with
    # one-sided differences at the two ends. np.gradient does exactly this and
    # handles the endpoints itself.
    dr, dy = np.gradient(r), np.gradient(y)
    # Perpendicular to (dr, dy), pointing away from the axis. Check the sign on
    # a cylinder: profile goes (1,0) -> (1,1), so (dr, dy) = (0, 1) and the
    # normal is (1, 0) -- straight out. On a cone tip, (1,0) -> (0,1) gives
    # (dr, dy) = (-1, 1) and a normal of (1, 1), out and up. Both correct.
    n_r, n_y = dy, -dr
    ln = np.hypot(n_r, n_y)
    # A profile with two identical consecutive points has a zero-length tangent
    # and would divide by zero here. Leave those normals pointing outward rather
    # than producing NaN, which would silently poison the whole vertex buffer.
    degenerate = ln < 1e-12
    n_r = np.where(degenerate, 1.0, n_r / np.where(degenerate, 1.0, ln))
    n_y = np.where(degenerate, 0.0, n_y / np.where(degenerate, 1.0, ln))

    theta = np.linspace(0.0, 2.0 * math.pi, segments + 1)
    cos_t, sin_t = np.cos(theta), np.sin(theta)

    # (rings, cols) grids via broadcasting: profile down the rows, angle across.
    px = r[:, None] * cos_t[None, :]
    pz = r[:, None] * sin_t[None, :]
    py = np.broadcast_to(y[:, None], px.shape)
    nx = n_r[:, None] * cos_t[None, :]
    nz = n_r[:, None] * sin_t[None, :]
    ny = np.broadcast_to(n_y[:, None], nx.shape)

    verts = np.stack(
        [px.ravel(), py.ravel(), pz.ravel(), nx.ravel(), ny.ravel(), nz.ravel()],
        axis=1,
    ).astype(np.float32)

    rings, cols = px.shape
    # Quad corners as flat indices, then two triangles per quad. Wound
    # counter-clockwise seen from outside, which is what GL calls front-facing
    # by default -- so backface culling remains available even though the depth
    # buffer means nothing currently depends on it.
    i0 = (np.arange(rings - 1)[:, None] * cols + np.arange(cols - 1)[None, :]).ravel()
    i1, i2, i3 = i0 + 1, i0 + cols, i0 + cols + 1
    idx = np.concatenate(
        [np.stack([i0, i2, i1], axis=1), np.stack([i1, i2, i3], axis=1)]
    ).astype(np.uint32)

    # The poles produce degenerate triangles (both corners of the quad sit on the
    # axis, so two of the three vertices coincide). They rasterise to nothing, so
    # they are harmless, but dropping them keeps the triangle count honest.
    a, b, c = verts[idx[:, 0], :3], verts[idx[:, 1], :3], verts[idx[:, 2], :3]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    return verts, idx[area > 1e-12]


def shadow_quad(extent: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """A flat quad on the ground plane, used as the pawn's contact shadow.

    Same (position, normal) vertex layout as `pawn_mesh` so both can be drawn by
    one program, switched on a uniform. The soft round falloff is computed in
    the fragment shader from the model-space XZ, NOT baked into geometry: a
    quad's four corners cannot express a radial gradient, and a fan of triangles
    that could would overlap itself and darken where the triangles meet.

    The contact shadow is not decoration. Without something anchoring it to the
    paper, a solid object drawn over a flat map reads as floating above it --
    this is the single detail that makes the piece sit ON the map.
    """
    verts = np.array(
        [
            [-extent, 0.0, -extent, 0.0, 1.0, 0.0],
            [extent, 0.0, -extent, 0.0, 1.0, 0.0],
            [-extent, 0.0, extent, 0.0, 1.0, 0.0],
            [extent, 0.0, extent, 0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    idx = np.array([[0, 2, 1], [1, 2, 3]], dtype=np.uint32)
    return verts, idx


@dataclass
class Pawn:
    """One piece on the campaign map.

    `pos` is in GAME pixels (the letterboxed canvas Board and Terrain draw in),
    not data space and not screen space -- it is where the piece's BASE touches
    the paper, so the model sits on the map rather than being centred on it.
    """

    pos: tuple[float, float]
    color: tuple[int, int, int]
    # Which graph node the piece is ON, in DATA space rc -- the same key
    # Sites.sites uses. This is the authoritative position; `pos` is where it is
    # currently being drawn, which during a move is somewhere between two nodes
    # and belongs to nothing.
    #
    # The split matters beyond tidiness: `pos` is in game pixels and so assumes
    # the map is drawn at one fixed place and scale. The moment the camera can
    # pan or zoom that stops being true, while `rc` keeps meaning what it meant.
    node: Coords = (0, 0)
    size_px: float = 44.0
    # Radians, rotation about the vertical axis. A surface of revolution looks
    # identical at every facing, so this does nothing visible yet; it is here
    # because the moment the pawn is replaced by anything with a front, every
    # caller that moves it would otherwise have to be revisited.
    facing: float = 0.0
    # Waypoints in game px still to be walked, nearest first.
    path: list[tuple[float, float]] = field(default_factory=list)
    speed_px_s: float = 90.0
    # Vertical bob, in units of size_px. A piece sliding along at a constant
    # height reads as a cursor; a small rise and fall reads as being carried.
    bob_amp: float = 0.022
    bob_hz: float = 2.6
    # Picked up by the player. While true the piece follows the cursor and is
    # held clear of the paper -- see bob_px.
    held: bool = False
    # How far a held piece rises, in units of size_px. Constant rather than
    # oscillating: it is being CARRIED, not walking. The renderer draws the
    # contact shadow at zero lift, so raising only the piece separates the two
    # and that gap is the entire "in hand" read.
    hold_lift: float = 0.34
    _t: float = 0.0
    # Where the piece will BE once the walk finishes. `node` only changes on
    # arrival, so a move that is interrupted leaves the piece belonging to the
    # node it actually started from rather than to the one it was heading for.
    _dest: Coords | None = None

    def move_to(self, node: Coords, screen_pos: tuple[float, float]) -> None:
        """Walk to an adjacent node. The caller owns the node -> screen mapping,
        because only it knows where the map is currently drawn."""
        self._dest = node
        self.path = [screen_pos]

    @property
    def moving(self) -> bool:
        return bool(self.path)

    @property
    def bob_px(self) -> float:
        """Current vertical offset. Zero while stationary -- a piece that
        breathes on the spot looks like an idle animation nobody asked for."""
        if self.held:
            return self.hold_lift * self.size_px
        if not self.moving:
            return 0.0
        return (
            math.sin(self._t * self.bob_hz * 2.0 * math.pi)
            * self.bob_amp
            * self.size_px
        )

    def place_at(self, node: Coords, screen_pos: tuple[float, float]) -> None:
        """Put the piece down on a node immediately, cancelling any walk.

        The drop half of drag-and-drop. Deliberately a SNAP rather than a walk:
        the player has already carried it there by hand, and animating a second
        journey afterwards would be the piece moving twice."""
        self.node = node
        self._dest = None
        self.path = []
        self.pos = screen_pos

    def update(self, dt: float) -> None:
        """Walk toward the next waypoint, consuming as many as `dt` allows."""
        self._t += dt
        budget = self.speed_px_s * dt
        while self.path and budget > 0.0:
            tx, ty = self.path[0]
            dx, dy = tx - self.pos[0], ty - self.pos[1]
            d = math.hypot(dx, dy)
            if d <= budget:
                # Snap exactly onto the waypoint before taking the next one, or
                # the leftover budget is spent from a position that is merely
                # near it and the error compounds down a long path.
                self.pos = (tx, ty)
                budget -= d
                self.path.pop(0)
                continue
            self.pos = (self.pos[0] + dx / d * budget, self.pos[1] + dy / d * budget)
            self.facing = math.atan2(dx, -dy)
            budget = 0.0
        if not self.path and self._dest is not None:
            self.node = self._dest
            self._dest = None
