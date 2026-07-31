"""Look at a Terrain's height_map as an actual 3D mesh.

About "surely moderngl can render a mesh for me": it can't, and no library on
top of it will either -- moderngl is a thin, honest wrapper over OpenGL. It
hands you buffers, shaders and vertex arrays; it has no notion of a camera, a
transform, a light or a material. The nearest thing to a batteries-included
option is `moderngl-window`, whose scene module can load a glTF/OBJ and orbit a
camera around it, but it wants to own the window and the event loop -- which
pygame already owns here -- and it still wouldn't build a mesh out of a numpy
heightmap for you.

The good news is that "writing a 3D renderer" for this is small. What's
genuinely needed is on this page:

  * a vertex buffer and an index buffer built from the heightmap (build_mesh),
  * two 4x4 matrices, projection and view (_perspective / _look_at),
  * ~30 lines of GLSL for lambert + hemisphere ambient shading.

Everything past that -- scene graphs, materials, shadow maps, frustum culling --
is what a real engine adds, and none of it is needed to look at a heightmap.

HOW IT HANGS OFF THE EXISTING PIPELINE

Game.render() paints the 2D canvas, uploads it as a texture and draws it as a
fullscreen quad, then calls `post_render_callbacks` before flipping. That
callback list is exactly the right hook: the 3D pass runs after the parchment is
on screen and draws over it.

The mesh is NOT drawn straight to the window, though. It goes into an offscreen
framebuffer that owns a depth buffer (the window's own depth bits are whatever
SDL happened to give us) and multisampling, and that framebuffer is then
composited over the parchment. Its sky is cleared fully transparent, so the
terrain reads as a model sitting on the page rather than a rectangle pasted over
it.

Run it with:  python -m States.Terrain3dTestState

TODO
    Flatten the plains. Seen in 3D the mountains read as mountains, but the
    lowlands carry the same octave structure scaled down, so farmland sits on a
    permanent gentle swell instead of on flat ground -- which reads wrong next
    to the field parcels the 2D map now draws there (BIOME_FIELDS in
    Models/Terrain.py). This is a generation fix, not a rendering one: the
    detail octaves want to be attenuated where the terrain is low, so `height`
    itself comes out flat there. Whatever lands, it must not move the biome
    thresholds out from under the 2D map.
"""

import math
from typing import cast

import moderngl
import numpy as np
import pygame as p

from Game import Game
from Models.Terrain import (
    BIOME_THRESHOLDS_REV,
    Biome,
    NoiseParams,
    SunParams,
    Terrain,
)
from States.State import State

# ---------------------------------------------------------------------------
# Matrices
#
# Built row-major (the textbook convention: M @ v, with v a column vector), so
# a composite transform reads left-to-right as projection-then-view-then-model.
# GL wants column-major memory, hence the .T at upload time -- see _write_mat4.
# ---------------------------------------------------------------------------


def _perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) * 0.5)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def _look_at(eye: np.ndarray, target: np.ndarray, up=(0.0, 1.0, 0.0)) -> np.ndarray:
    """World -> camera space. The rotation part is the camera's own axes as
    ROWS (i.e. the inverse of the camera's orientation, which is what a view
    matrix is), and the translation column is that rotation applied to -eye."""
    forward = target - eye
    forward /= np.linalg.norm(forward)
    side = np.cross(forward, np.asarray(up, dtype=np.float64))
    side /= np.linalg.norm(side)
    true_up = np.cross(side, forward)

    m = np.eye(4, dtype=np.float64)
    m[0, :3], m[1, :3], m[2, :3] = side, true_up, -forward
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def _uniform(prog: moderngl.Program, name: str) -> moderngl.Uniform:
    """`prog[name]` is typed as Uniform | UniformBlock | Attribute | Varying,
    since a program's members include its inputs and outputs too. Everything
    looked up here is a uniform; narrowing it once keeps `.value` and
    `.write()` legible instead of unchecked."""
    return cast(moderngl.Uniform, prog[name])


def _write_mat4(prog: moderngl.Program, name: str, m: np.ndarray) -> None:
    """Row-major numpy -> column-major GL. Transposing here rather than
    building the matrices transposed keeps the maths above readable."""
    _uniform(prog, name).write(np.ascontiguousarray(m.T, dtype="f4").tobytes())


class OrbitCamera:
    """Spherical coordinates around a target. `yaw`/`pitch` are radians,
    `distance` is in world units (the terrain's longest side is 2.0)."""

    def __init__(self, target=(0.0, 0.0, 0.0), distance=3.0, yaw=0.6, pitch=0.5):
        self.target = np.asarray(target, dtype=np.float64)
        self.distance = distance
        self.yaw = yaw
        self.pitch = pitch

    # Never quite +-90 degrees: straight down makes the view matrix's `up`
    # parallel to the view direction and the cross product degenerate.
    MAX_PITCH = math.radians(89.0)

    def orbit(self, dyaw: float, dpitch: float) -> None:
        self.yaw += dyaw
        self.pitch = max(-self.MAX_PITCH, min(self.MAX_PITCH, self.pitch + dpitch))

    def zoom(self, factor: float) -> None:
        self.distance = max(0.35, min(12.0, self.distance * factor))

    @property
    def eye(self) -> np.ndarray:
        cp = math.cos(self.pitch)
        offset = np.array(
            [cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)]
        )
        return self.target + self.distance * offset

    def view(self) -> np.ndarray:
        return _look_at(self.eye, self.target)


# ---------------------------------------------------------------------------
# Mesh
# ---------------------------------------------------------------------------


def build_mesh(height: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    """A (rows, cols) heightmap in [0,1] -> (vertices, indices, extent).

    One vertex per heightmap cell, two triangles per cell quad. Vertices are
    (x, h, z, dh/dx, dh/dz): the x/z grid in world units, the RAW height, and
    the two slope components -- everything the vertex shader needs to place the
    point and derive its normal.

    Storing the raw height (not a scaled one) is what makes the vertical
    exaggeration a free uniform: the shader multiplies both the height and the
    slopes by u_height_scale, and since a normal is just (-dY/dX, 1, -dY/dZ)
    normalized, scaling the slopes gives the correct normal for the scaled
    surface. Nothing has to be re-uploaded when the exaggeration changes.

    The grid keeps the heightmap's aspect ratio with its longest side spanning
    2.0 world units, centred on the origin, so the camera distances below mean
    the same thing for any map size.
    """
    rows, cols = height.shape
    longest = max(rows, cols)
    world_w = 2.0 * cols / longest
    world_d = 2.0 * rows / longest

    xs = np.linspace(-world_w * 0.5, world_w * 0.5, cols)
    zs = np.linspace(-world_d * 0.5, world_d * 0.5, rows)
    xx, zz = np.meshgrid(xs, zs)  # (rows, cols), matching the heightmap

    # np.gradient with an explicit spacing gives dh per WORLD unit, so the
    # slopes stay meaningful whatever the grid resolution is.
    dz = world_d / (rows - 1)
    dx = world_w / (cols - 1)
    slope_z, slope_x = np.gradient(height, dz, dx)

    verts = np.stack([xx, height, zz, slope_x, slope_z], axis=-1).astype("f4")

    # Two triangles per quad, from the four corner indices of every cell. Done
    # as whole-array slices rather than a Python loop -- at 450x256 that's
    # ~687k indices, which is a second of interpreted looping and about a
    # millisecond this way.
    idx = np.arange(rows * cols, dtype=np.uint32).reshape(rows, cols)
    v00, v01 = idx[:-1, :-1], idx[:-1, 1:]
    v10, v11 = idx[1:, :-1], idx[1:, 1:]
    indices = np.stack([v00, v10, v11, v00, v11, v01], axis=-1).astype("u4")

    return verts.reshape(-1, 5), indices.reshape(-1), (world_w, world_d)


# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------

TERRAIN_VERT = """
#version 330

in vec3 in_pos;      // x, raw height in [0,1], z
in vec2 in_slope;    // dh/dx, dh/dz -- for an unexaggerated surface
in vec3 in_color;

uniform mat4 u_vp;
uniform float u_height_scale;

out vec3 v_color;
out vec3 v_normal;
out vec3 v_world;

void main() {
    vec3 world = vec3(in_pos.x, in_pos.y * u_height_scale, in_pos.z);
    // Slopes were computed for height_scale == 1, and scaling the surface
    // vertically scales them linearly -- so the normal of the exaggerated
    // surface comes straight out of the stored ones.
    v_normal = normalize(vec3(-in_slope.x * u_height_scale,
                              1.0,
                              -in_slope.y * u_height_scale));
    v_color = in_color;
    v_world = world;
    gl_Position = u_vp * vec4(world, 1.0);
}
"""

TERRAIN_FRAG = """
#version 330

in vec3 v_color;
in vec3 v_normal;
in vec3 v_world;

uniform vec3 u_light_dir;     // normalized, points TOWARD the sun
uniform vec3 u_sun_color;
uniform vec3 u_sky_color;     // hemisphere ambient from above
uniform vec3 u_ground_color;  // ... and the bounce from below

out vec4 fragColor;

void main() {
    vec3 n = normalize(v_normal);
    float ndl = max(dot(n, u_light_dir), 0.0);
    // Hemisphere ambient: an up-facing slope catches sky, a down-facing one
    // catches bounce. Cheaper than any real GI and enough to keep the shaded
    // side of a ridge from going flat black.
    vec3 ambient = mix(u_ground_color, u_sky_color, n.y * 0.5 + 0.5);
    fragColor = vec4(v_color * (ambient + u_sun_color * ndl), 1.0);
}
"""

WATER_VERT = """
#version 330

in vec2 in_xz;

uniform mat4 u_vp;
uniform float u_sea_y;

out vec3 v_world;

void main() {
    v_world = vec3(in_xz.x, u_sea_y, in_xz.y);
    gl_Position = u_vp * vec4(v_world, 1.0);
}
"""

WATER_FRAG = """
#version 330

in vec3 v_world;

uniform vec3 u_cam;
uniform vec4 u_water;

out vec4 fragColor;

void main() {
    // Cheap Fresnel: the shallower the view angle, the more the surface acts
    // like a mirror -- brighter and more opaque toward the horizon, clear
    // enough to read the seabed when looked at from above.
    vec3 view = normalize(u_cam - v_world);
    float fresnel = pow(1.0 - abs(view.y), 3.0);
    fragColor = vec4(mix(u_water.rgb, vec3(1.0), fresnel * 0.35),
                     mix(u_water.a, 0.9, fresnel));
}
"""

COMPOSITE_VERT = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

COMPOSITE_FRAG = """
#version 330
uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;
void main() { fragColor = texture(tex, v_uv); }
"""


class TerrainMeshRenderer:
    """Owns every GL object the 3D pass needs, and the offscreen framebuffer it
    draws into. Nothing here knows about Terrain or about the State -- it takes
    a mesh, a camera and a light, and puts pixels over whatever is on screen."""

    def __init__(self, ctx: moderngl.Context, size: tuple[int, int]):
        self.ctx = ctx
        self.size = size

        self.terrain_prog = ctx.program(vertex_shader=TERRAIN_VERT, fragment_shader=TERRAIN_FRAG)
        self.water_prog = ctx.program(vertex_shader=WATER_VERT, fragment_shader=WATER_FRAG)
        self.composite_prog = ctx.program(vertex_shader=COMPOSITE_VERT, fragment_shader=COMPOSITE_FRAG)

        # --- offscreen target ---
        # A depth buffer of our own, because the window's depth bits are
        # whatever SDL defaulted to, and multisampling because a heightmap is
        # nothing but silhouette edges. `samples > 1` renderbuffers can't be
        # sampled as textures, so they're resolved into `self.color` first.
        self.samples = min(4, ctx.max_samples)
        self.color = ctx.texture(size, 4)
        self.color.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.resolve_fbo = ctx.framebuffer(color_attachments=[self.color])
        if self.samples > 1:
            self.fbo = ctx.framebuffer(
                color_attachments=[ctx.renderbuffer(size, 4, samples=self.samples)],
                depth_attachment=ctx.depth_renderbuffer(size, samples=self.samples),
            )
        else:
            self.fbo = ctx.framebuffer(
                color_attachments=[self.color],
                depth_attachment=ctx.depth_renderbuffer(size),
            )

        quad = np.array(
            # x, y, u, v -- a triangle strip, no V flip: we render this texture
            # ourselves, so its rows already run bottom-up like GL expects.
            [-1, -1, 0, 0,
              1, -1, 1, 0,
             -1,  1, 0, 1,
              1,  1, 1, 1],
            dtype="f4",
        )
        self.quad_vbo = ctx.buffer(quad.tobytes())
        self.quad_vao = ctx.simple_vertex_array(self.composite_prog, self.quad_vbo, "in_pos", "in_uv")

        # Filled by set_mesh.
        self.vbo = self.color_vbo = self.ibo = self.vao = None
        self.water_vbo = self.water_vao = None
        self.index_count = 0

    # -- mesh upload ------------------------------------------------------

    def set_mesh(self, verts: np.ndarray, indices: np.ndarray, colors: np.ndarray,
                 extent: tuple[float, float]) -> None:
        """`verts` is (N, 5) as built by build_mesh, `colors` is (N, 3) floats
        in [0,1]. Geometry and colour live in SEPARATE buffers so recolouring
        the map (biome wash vs elevation ramp) is one small write instead of a
        full re-interleave of every vertex."""
        self._release_mesh()
        self.vbo = self.ctx.buffer(np.ascontiguousarray(verts, dtype="f4").tobytes())
        self.color_vbo = self.ctx.buffer(np.ascontiguousarray(colors, dtype="f4").tobytes())
        self.ibo = self.ctx.buffer(np.ascontiguousarray(indices, dtype="u4").tobytes())
        self.vao = self.ctx.vertex_array(
            self.terrain_prog,
            [
                (self.vbo, "3f 2f", "in_pos", "in_slope"),
                (self.color_vbo, "3f", "in_color"),
            ],
            self.ibo,
        )
        self.index_count = len(indices)

        w, d = extent
        water = np.array(
            [-w * 0.5, -d * 0.5,
              w * 0.5, -d * 0.5,
             -w * 0.5,  d * 0.5,
              w * 0.5,  d * 0.5],
            dtype="f4",
        )
        self.water_vbo = self.ctx.buffer(water.tobytes())
        self.water_vao = self.ctx.simple_vertex_array(self.water_prog, self.water_vbo, "in_xz")

    def set_colors(self, colors: np.ndarray) -> None:
        if self.color_vbo is not None:
            self.color_vbo.write(np.ascontiguousarray(colors, dtype="f4").tobytes())

    # -- drawing ----------------------------------------------------------

    def render(self, camera: OrbitCamera, light_dir: np.ndarray, height_scale: float,
               screen_viewport: tuple[int, int, int, int], sea_y: float | None = None,
               wireframe: bool = False, water_color=(0.30, 0.50, 0.62, 0.55)) -> None:
        if self.vao is None:
            return
        ctx = self.ctx
        aspect = self.size[0] / self.size[1]
        vp = _perspective(45.0, aspect, 0.05, 100.0) @ camera.view()
        eye = camera.eye

        self.fbo.use()
        # Transparent sky: the parchment underneath shows through everywhere
        # the mesh isn't, and multisampled edges resolve to partial coverage
        # that composites cleanly (see the premultiplied blend below).
        self.fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        # Backface culling stays OFF on purpose -- orbiting under the map to
        # look at its underside is genuinely useful when checking a heightmap.
        ctx.wireframe = wireframe

        _write_mat4(self.terrain_prog, "u_vp", vp)
        _uniform(self.terrain_prog, "u_height_scale").value = height_scale
        _uniform(self.terrain_prog, "u_light_dir").value = tuple(light_dir)
        # Sun + peak ambient deliberately sums to just under 1: the biome tints
        # are pale washes already, and a brighter key clips the sandy ones to
        # flat white on any slope facing the sun.
        _uniform(self.terrain_prog, "u_sun_color").value = (0.82, 0.78, 0.68)
        _uniform(self.terrain_prog, "u_sky_color").value = (0.34, 0.38, 0.46)
        _uniform(self.terrain_prog, "u_ground_color").value = (0.16, 0.14, 0.12)
        self.vao.render(moderngl.TRIANGLES, vertices=self.index_count)

        if sea_y is not None and not wireframe and self.water_vao is not None:
            # Depth TEST on (so the sea is hidden behind land it sits behind)
            # but depth WRITE off, the standard treatment for a transparent
            # surface -- writing it would occlude anything drawn later.
            #
            # The mask lives on the FRAMEBUFFER, not the context. `ctx.depth_mask`
            # is not a moderngl attribute at all: assigning it silently created
            # a stray Python attribute and depth writes stayed on the whole
            # time. A type checker is what caught it -- nothing about the
            # rendered image made it obvious, since the sea is drawn last.
            self.fbo.depth_mask = False
            _write_mat4(self.water_prog, "u_vp", vp)
            _uniform(self.water_prog, "u_sea_y").value = sea_y
            _uniform(self.water_prog, "u_cam").value = tuple(eye)
            _uniform(self.water_prog, "u_water").value = water_color
            self.water_vao.render(moderngl.TRIANGLE_STRIP)
            self.fbo.depth_mask = True

        ctx.wireframe = False
        ctx.disable(moderngl.DEPTH_TEST)
        if self.samples > 1:
            ctx.copy_framebuffer(self.resolve_fbo, self.fbo)

        # --- composite over the 2D canvas already on screen ---
        ctx.screen.use()
        ctx.viewport = screen_viewport
        # Premultiplied alpha: a resolved MSAA edge pixel is (colour * coverage,
        # coverage), so multiplying by src alpha a second time would darken
        # every silhouette into a halo. Restored afterwards because GLRenderer
        # sets the blend func once at startup and expects it to stay put.
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self.color.use(0)
        self.quad_vao.render(moderngl.TRIANGLE_STRIP)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    # -- teardown ---------------------------------------------------------

    def _release_mesh(self) -> None:
        for obj in (self.vao, self.vbo, self.color_vbo, self.ibo, self.water_vao, self.water_vbo):
            if obj is not None:
                obj.release()
        self.vao = self.vbo = self.color_vbo = self.ibo = None
        self.water_vao = self.water_vbo = None
        self.index_count = 0

    def release(self) -> None:
        self._release_mesh()
        for obj in (self.quad_vao, self.quad_vbo, self.fbo, self.resolve_fbo, self.color,
                    self.terrain_prog, self.water_prog, self.composite_prog):
            obj.release()


# ---------------------------------------------------------------------------
# The state
# ---------------------------------------------------------------------------

# Same data resolution Board uses, so what shows up here is the same terrain
# the 2D map is drawn from -- 115k vertices, which is nothing for a GPU.
DATA_SIZE = (450, 256)

COLOR_MODES = ("biome", "elevation", "paper")


class Terrain3dTestState(State):
    """Orbit around a Terrain's heightmap as a lit 3D mesh.

    Controls
        left-drag       orbit
        wheel           zoom
        UP / DOWN       vertical exaggeration
        1 / 2 / 3       biome wash / elevation ramp / flat paper
        W               wireframe
        L               sea level plane on/off
        SPACE           auto-rotate
        R               reset camera
        N               regenerate the terrain (~1s, it's noise on the CPU)
        ESC             quit
    """

    def __init__(self, game: Game, data=None, layer="foreground", bg_color=..., previous_state=None):
        super().__init__(game, data, layer, bg_color=(235, 232, 224), previous_state=None)

        self.height_scale = 0.35
        self.color_mode = 0
        self.wireframe = False
        self.show_water = True
        self.auto_rotate = False
        self.camera = OrbitCamera(target=(0.0, 0.05, 0.0), distance=3.0, yaw=0.6, pitch=0.5)
        self._drag_from: p.Vector2 | None = None
        self._font = game.fonts["ant"]["small"]

        self.renderer = TerrainMeshRenderer(game.glctx, (game.GAME_W, game.GAME_H))
        self._build_terrain()

        # Game.render() runs these after the 2D canvas is on screen and before
        # the flip -- exactly where a pass that draws OVER the page belongs.
        game.post_render_callbacks.append(self._draw_3d)

    # -- terrain ----------------------------------------------------------

    def _build_terrain(self, seed: int | None = None) -> None:
        seed = np.random.randint(0, 256) if seed is None else seed
        # The bounding rect only sizes the 2D surfaces Terrain bakes, and this
        # state never blits one -- it reads the data-space fields directly. So
        # keep it tiny: Terrain's constructor eagerly bakes the glyph map, and
        # at 1800x1024 that's seconds of stamping sprites we'd throw away.
        self.terrain = Terrain(
            height_noise_params=NoiseParams(DATA_SIZE, seed=seed),
            moisture_noise_params=NoiseParams(DATA_SIZE, seed=(seed + 97) % 256),
            sun_params=SunParams(),
            bounding_rect=p.Rect((0, 0), (64, 64)),
        )

        verts, indices, extent = build_mesh(self.terrain.height_map)
        self.renderer.set_mesh(verts, indices, self._vertex_colors(), extent)

        # Same convention as Terrain._build_temp_map: elevation from the
        # horizon, azimuth around it. Its (x, y) are the map's column/row axes
        # and its z is up, which here means x -> x, row -> z, up -> y.
        sun = self.terrain.sun_params
        theta, phi = math.radians(sun.elevation), math.radians(sun.azimuth)
        self.light_dir = np.array(
            [math.cos(theta) * math.cos(phi), math.sin(theta), math.cos(theta) * math.sin(phi)]
        )
        self.light_dir /= np.linalg.norm(self.light_dir)

        self.sea_level = BIOME_THRESHOLDS_REV[Biome.SEASIDE][1]

    def _vertex_colors(self) -> np.ndarray:
        """One RGB per vertex, in [0,1]. Every mode reuses a Terrain palette
        rather than inventing colours here, so the 3D view and the 2D map can't
        disagree about where a biome starts."""
        mode = COLOR_MODES[self.color_mode]
        if mode == "biome":
            rgba = Terrain.colour_from_biomes(self.terrain.biome_mat)
        elif mode == "elevation":
            rgba = Terrain.apply_palette(self.terrain.height_map, Terrain.ELEVATION_PALETTE)
        else:
            # Flat off-white: nothing but the shading, which is the honest way
            # to judge whether the mesh and its normals are right.
            rgba = np.full((*self.terrain.height_map.shape, 4), 232, dtype=np.uint8)
        return (rgba[:, :, :3].reshape(-1, 3).astype("f4") / 255.0)

    # -- input ------------------------------------------------------------

    def update(self, delta_time):
        super().update(delta_time)

        for event in self.game.events:
            if event.type == p.MOUSEWHEEL:
                self.camera.zoom(0.9 ** event.y)
            elif event.type == p.KEYDOWN:
                if event.key in (p.K_1, p.K_2, p.K_3):
                    self.color_mode = {p.K_1: 0, p.K_2: 1, p.K_3: 2}[event.key]
                    self.renderer.set_colors(self._vertex_colors())
                elif event.key == p.K_w:
                    self.wireframe = not self.wireframe
                elif event.key == p.K_l:
                    self.show_water = not self.show_water
                elif event.key == p.K_SPACE:
                    self.auto_rotate = not self.auto_rotate
                elif event.key == p.K_r:
                    self.camera = OrbitCamera(target=(0.0, 0.05, 0.0), distance=3.0, yaw=0.6, pitch=0.5)
                elif event.key == p.K_n:
                    self._build_terrain()

        # Drag deltas come from Game.cursorpos (already letterbox-corrected and
        # in game coordinates) rather than mouse.get_rel(), which is global
        # state anything else in the frame could consume first.
        cursor = self.game.cursorpos
        if self.game.actions["mouse_sx"]:
            if self._drag_from is not None:
                delta = cursor - self._drag_from
                self.camera.orbit(-delta.x * 0.006, delta.y * 0.006)
            self._drag_from = p.Vector2(cursor)
        else:
            self._drag_from = None

        keys = p.key.get_pressed()
        if keys[p.K_UP]:
            self.height_scale = min(2.0, self.height_scale + 0.5 * delta_time)
        if keys[p.K_DOWN]:
            self.height_scale = max(0.0, self.height_scale - 0.5 * delta_time)

        if self.auto_rotate:
            self.camera.orbit(0.3 * delta_time, 0.0)

    # -- rendering --------------------------------------------------------

    def render(self, surface: p.Surface):
        super().render(surface)
        mode = COLOR_MODES[self.color_mode]
        lines = [
            "TERRAIN 3D  --  drag: orbit   wheel: zoom   UP/DOWN: height",
            f"1/2/3 colours [{mode}]   W wireframe [{'on' if self.wireframe else 'off'}]"
            f"   L water [{'on' if self.show_water else 'off'}]",
            f"SPACE auto-rotate [{'on' if self.auto_rotate else 'off'}]   R reset   N new terrain   ESC quit",
            f"grid {DATA_SIZE[0]}x{DATA_SIZE[1]}   tris {self.renderer.index_count // 3:,}"
            f"   exaggeration {self.height_scale:.2f}   MSAA x{self.renderer.samples}",
        ]
        for i, line in enumerate(lines):
            surface.blit(self._font.render(line, True, (60, 52, 44)), (24, 24 + i * 22))

    def _draw_3d(self) -> None:
        self.renderer.render(
            camera=self.camera,
            light_dir=self.light_dir,
            height_scale=self.height_scale,
            screen_viewport=self.game.gl_renderer.viewport,
            sea_y=(self.sea_level * self.height_scale) if self.show_water else None,
            wireframe=self.wireframe,
        )

    def exit_state(self):
        # post_render_callbacks is never cleared by Game, so a state that adds
        # to it has to take itself back out or it keeps drawing after it's gone.
        if self._draw_3d in self.game.post_render_callbacks:
            self.game.post_render_callbacks.remove(self._draw_3d)
        self.renderer.release()
        super().exit_state()


if __name__ == "__main__":
    game = Game()
    game.push_state(Terrain3dTestState(game))
    game.game_loop()
