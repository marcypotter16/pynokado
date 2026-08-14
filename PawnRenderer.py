"""The 3D pass that draws campaign pawns over the 2D map.

Everything else in this renderer is a full-screen quad: pygame draws the world
into a surface, the surface becomes a texture, the texture becomes a quad. This
is the one pass with real geometry in it, and it is deliberately kept to the
same shape as the others -- it renders into its own framebuffer and then
composites that framebuffer as one more quad, so from `GLRenderer`'s point of
view nothing has changed.

THE CAMERA IS A CHEAT AND THAT IS THE POINT. There is no shared 3D scene: the
map is a flat picture in screen pixels and has no camera at all. So the pawn is
drawn with a fixed OBLIQUE orthographic projection -- the same tilt for every
piece regardless of where it stands -- which is exactly how a board game looks
in a photograph taken from above the table, and how Civ II and HoMM III drew
their pieces. Tilting a real camera instead would tilt the map with it and
would mean re-authoring the UI, the weather layer and the glyph pass, all of
which assume screen space.

WHY ITS OWN FRAMEBUFFER. A 3D pass needs a depth buffer, and it needs that
buffer cleared every frame without clearing the colour underneath it -- which
moderngl's `clear()` cannot do, since it always clears both. Owning the
framebuffer sidesteps that completely: the depth attachment is ours to clear,
and `Game.py`'s context creation does not have to request anything new.

PREMULTIPLIED ALPHA, throughout. The fragment shader emits `rgb * a`, the
framebuffer blends with `(ONE, ONE_MINUS_SRC_ALPHA)`, and so does the composite.
Straight (non-premultiplied) alpha is wrong when compositing a layer that was
itself built by blending: the usual `(SRC_ALPHA, ONE_MINUS_SRC_ALPHA)` applies
to the alpha channel as well, so a half-transparent shadow drawn onto a
transparent buffer ends up with alpha a*a instead of a, and the shadow comes out
too faint by exactly the amount it is transparent.
"""

import math
from typing import cast

import moderngl
import numpy as np
from moderngl import Context

from GLRenderer import VERT_SRC
from Models.Pawn import Pawn, pawn_mesh, shadow_quad


def _uniform(prog: moderngl.Program, name: str) -> moderngl.Uniform:
    """`prog[name]` is typed as Uniform | UniformBlock | Attribute | Varying,
    since a program's members include its inputs and outputs. Everything looked
    up here is a uniform; narrowing once keeps `.value` legible.

    (Twin of the same helper in States/Terrain3dTestState.py. Copied rather than
    imported: a renderer importing a State inverts the dependency, and this is
    three lines.)"""
    return cast(moderngl.Uniform, prog[name])

# How far the camera is tilted off straight-down, in degrees. 0 would look
# vertically at the board and a surface of revolution would be a disc; 90 would
# be at eye level with the paper and the piece would have no footprint at all.
# ~58 is around where a photograph of a board taken from a seated player's side
# sits, and it is high enough that the piece still clearly occupies a spot
# rather than leaning across half the map.
CAMERA_TILT_DEG = 58.0

# Direction TO the light, in world space (x right, y up out of the paper, z down
# the map). Pulled up and to the left so the lit side faces the same way as the
# terrain's default sun. Not wired to SunParams yet on purpose -- that couples
# the piece to the map's lighting, which is a decision worth making deliberately
# rather than by import.
LIGHT_DIR = (-0.45, 0.78, -0.44)

# How far the contact shadow reaches, as a multiple of the piece's height, and
# how dark it gets at the centre. The shadow is what makes a solid object read as
# standing ON the paper instead of floating over it -- drop it and the piece
# immediately looks pasted on.
SHADOW_EXTENT = 0.42
SHADOW_ALPHA = 0.34

# Screen-space offset of the shadow from the piece's base, in units of its
# height. Small and down-right, away from LIGHT_DIR.
SHADOW_OFFSET = (0.035, 0.02)


PAWN_VERT_SRC = """
#version 330

in vec3 in_pos;
in vec3 in_normal;

uniform vec2 u_res;          // game canvas size in px
uniform vec2 u_origin;       // where the piece's BASE meets the paper, game px
uniform float u_scale;       // px per unit of model height
uniform vec2 u_tilt;         // (cos, sin) of the camera tilt off straight-down
uniform vec2 u_facing;       // (cos, sin) of the spin about the vertical axis
uniform float u_lift;        // px the piece rises off the paper (the bob)
uniform float u_depth_bias;  // per-piece depth slot, from its position down the map

out vec3 v_normal;
out vec2 v_xz;

void main() {
    float cf = u_facing.x, sf = u_facing.y;
    vec3 pr = vec3( in_pos.x * cf + in_pos.z * sf,
                    in_pos.y,
                   -in_pos.x * sf + in_pos.z * cf);
    vec3 nr = vec3( in_normal.x * cf + in_normal.z * sf,
                    in_normal.y,
                   -in_normal.x * sf + in_normal.z * cf);

    // The oblique projection. Height (y) pushes the piece UP the screen and
    // toward the viewer in depth; distance down the map (z) does both in the
    // opposite mix. With tilt 0 this collapses to a plan view, which is why the
    // tilt has to be non-zero for the piece to have any silhouette at all.
    float ca = u_tilt.x, sa = u_tilt.y;
    float sx = pr.x * u_scale;
    float sy = (pr.z * ca - pr.y * sa) * u_scale - u_lift;
    float depth = pr.z * sa + pr.y * ca;

    vec2 px = u_origin + vec2(sx, sy);
    // px is in pygame convention (y down from the top-left); NDC is y up.
    gl_Position = vec4(px.x / u_res.x * 2.0 - 1.0,
                       1.0 - px.y / u_res.y * 2.0,
                       clamp(u_depth_bias - depth * 0.02, -0.999, 0.999),
                       1.0);
    v_normal = nr;
    v_xz = in_pos.xz;
}
"""

PAWN_FRAG_SRC = """
#version 330

in vec3 v_normal;
in vec2 v_xz;

uniform vec3 u_color;
uniform vec3 u_light;
uniform vec3 u_view;
uniform int u_mode;            // 0 = the piece, 1 = its contact shadow
uniform float u_alpha;
uniform float u_shadow_extent;

out vec4 fragColor;

void main() {
    if (u_mode == 1) {
        // Radial falloff computed here rather than baked into geometry: a quad
        // has four corners and cannot carry a round gradient, and a triangle fan
        // that could would overlap itself and darken along every seam.
        float r = length(v_xz) / u_shadow_extent;
        float a = (1.0 - smoothstep(0.20, 1.0, r)) * u_alpha;
        fragColor = vec4(0.0, 0.0, 0.0, a);   // premultiplied: black * a is 0
        return;
    }

    vec3 n = normalize(v_normal);
    float d = max(dot(n, normalize(u_light)), 0.0);
    // A soft two-step ramp rather than raw Lambert. Straight N.L reads as
    // plastic; the ramp reads as a turned wooden piece, which is what it is
    // meant to be sitting on the paper.
    float lit = 0.42 + 0.58 * smoothstep(0.0, 0.9, d);
    vec3 c = u_color * lit;

    // Darkened silhouette edge. The map is a pen drawing and everything on it
    // has an outline; without this the piece is the only object on screen with
    // a soft edge and it stops belonging to the picture.
    float rim = 1.0 - abs(dot(n, normalize(u_view)));
    c *= mix(1.0, 0.42, smoothstep(0.72, 1.0, rim));

    fragColor = vec4(c * u_alpha, u_alpha);
}
"""

COMPOSITE_FRAG_SRC = """
#version 330

uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    // No .bgra swizzle and no V flip, unlike the pygame-surface path: this
    // texture was rendered BY GL, so it is already RGBA and already bottom-up.
    fragColor = texture(tex, v_uv);
}
"""


class PawnRenderer:
    """Draws `Pawn`s as solid pieces standing on the 2D map."""

    def __init__(self, ctx: Context, game_size: tuple[int, int]):
        self.ctx = ctx
        self.game_w, self.game_h = game_size

        # Multisampled, because a pawn is almost nothing BUT silhouette -- a
        # turned curve against parchment, at ~44px tall. Aliasing on that edge is
        # the difference between a carved piece and a jagged sprite, and it is
        # the one artefact no amount of shading hides.
        #
        # A `samples > 1` renderbuffer cannot be sampled as a texture, so the
        # multisampled buffer is resolved into `color_tex` before compositing.
        self.samples = min(4, ctx.max_samples)
        self.color_tex = ctx.texture(game_size, 4)
        self.color_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.color_tex.repeat_x = False
        self.color_tex.repeat_y = False
        self.resolve_fbo = ctx.framebuffer(color_attachments=[self.color_tex])
        if self.samples > 1:
            self.ms_color = ctx.renderbuffer(game_size, 4, samples=self.samples)
            self.depth_buf = ctx.depth_renderbuffer(game_size, samples=self.samples)
            self.fbo = ctx.framebuffer(
                color_attachments=[self.ms_color], depth_attachment=self.depth_buf
            )
        else:
            self.ms_color = None
            self.depth_buf = ctx.depth_renderbuffer(game_size)
            self.fbo = ctx.framebuffer(
                color_attachments=[self.color_tex], depth_attachment=self.depth_buf
            )

        self.prog = ctx.program(
            vertex_shader=PAWN_VERT_SRC, fragment_shader=PAWN_FRAG_SRC
        )
        self.composite_prog = ctx.program(
            vertex_shader=VERT_SRC, fragment_shader=COMPOSITE_FRAG_SRC
        )

        verts, idx = pawn_mesh()
        self.pawn_vbo = ctx.buffer(verts.tobytes())
        self.pawn_ibo = ctx.buffer(idx.tobytes())
        self.pawn_vao = ctx.vertex_array(
            self.prog,
            [(self.pawn_vbo, "3f 3f", "in_pos", "in_normal")],
            self.pawn_ibo,
        )

        # The shadow quad shares the pawn's vertex layout so one program can draw
        # both, switched on u_mode. A second program for ten lines of shader
        # would mean a second VAO, a second set of uniforms to keep in step, and
        # two places to change the camera.
        s_verts, s_idx = shadow_quad(SHADOW_EXTENT)
        self.shadow_vbo = ctx.buffer(s_verts.tobytes())
        self.shadow_ibo = ctx.buffer(s_idx.tobytes())
        self.shadow_vao = ctx.vertex_array(
            self.prog,
            [(self.shadow_vbo, "3f 3f", "in_pos", "in_normal")],
            self.shadow_ibo,
        )

        quad = np.array(
            [-1.0, -1.0, 0.0, 0.0,
             1.0, -1.0, 1.0, 0.0,
             -1.0, 1.0, 0.0, 1.0,
             1.0, 1.0, 1.0, 1.0],
            dtype="f4",
        )
        self.quad_vbo = ctx.buffer(quad.tobytes())
        self.composite_vao = ctx.simple_vertex_array(
            self.composite_prog, self.quad_vbo, "in_pos", "in_uv"
        )

        tilt = math.radians(CAMERA_TILT_DEG)
        self._tilt = (math.cos(tilt), math.sin(tilt))
        # The direction from the scene toward the viewer, in the same world space
        # the normals live in. Falls straight out of the projection above: depth
        # is `z*sin + y*cos`, so its gradient is (0, cos, sin).
        self._view = (0.0, math.cos(tilt), math.sin(tilt))

    def release(self) -> None:
        for obj in (
            self.pawn_vao, self.shadow_vao, self.composite_vao,
            self.pawn_vbo, self.pawn_ibo, self.shadow_vbo, self.shadow_ibo,
            self.quad_vbo, self.fbo, self.resolve_fbo, self.ms_color,
            self.color_tex, self.depth_buf, self.prog, self.composite_prog,
        ):
            if obj is not None:
                obj.release()

    def _set_common(self) -> None:
        _uniform(self.prog, "u_res").value = (float(self.game_w), float(self.game_h))
        _uniform(self.prog, "u_tilt").value = self._tilt
        _uniform(self.prog, "u_light").value = LIGHT_DIR
        _uniform(self.prog, "u_view").value = self._view
        _uniform(self.prog, "u_shadow_extent").value = SHADOW_EXTENT

    def render(self, pawns: list[Pawn], viewport: tuple[int, int, int, int]) -> None:
        """Draw `pawns` over whatever is already on screen.

        `viewport` is `GLRenderer.viewport` -- the letterboxed screen rect. The
        offscreen pass runs at full canvas size and only the final composite is
        letterboxed, so the pieces scale with the map exactly like every other
        layer does.
        """
        if not pawns:
            return

        ctx = self.ctx
        self.fbo.use()
        self.fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        # Premultiplied "over". See the module docstring for why not SRC_ALPHA.
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self._set_common()

        # Back to front by position down the map, so a nearer piece overlaps a
        # further one. The depth buffer resolves each piece against ITSELF (the
        # collar over the neck); it cannot order the pieces, because the shadows
        # are drawn without depth and would otherwise land on top of bodies
        # behind them.
        for pawn in sorted(pawns, key=lambda pw: pw.pos[1]):
            self._draw_one(pawn)

        ctx.disable(moderngl.DEPTH_TEST)
        if self.samples > 1:
            ctx.copy_framebuffer(self.resolve_fbo, self.fbo)
        ctx.screen.use()
        ctx.viewport = viewport
        self.color_tex.use(0)
        self.composite_vao.render(moderngl.TRIANGLE_STRIP)
        # Hand the context back exactly as it was found. Every other pass in the
        # renderer assumes straight alpha, and a leaked blend mode shows up as a
        # bug somewhere else entirely.
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

    def _draw_one(self, pawn: Pawn) -> None:
        ox, oy = pawn.pos
        _uniform(self.prog, "u_scale").value = float(pawn.size_px)
        _uniform(self.prog, "u_facing").value = (
            math.cos(pawn.facing), math.sin(pawn.facing)
        )
        # Pieces further down the map get a nearer depth slot. Normalised to
        # 0..1 so it can never leave the clip range whatever the canvas size.
        _uniform(self.prog, "u_depth_bias").value = (
            1.0 - min(max(oy / self.game_h, 0.0), 1.0)
        ) * 0.9

        # Shadow first, on the ground and NOT lifted by the bob -- so the piece
        # visibly rises off its own shadow rather than dragging it along.
        # Depth writes are off for it: it is a decal on the paper, and letting
        # it occupy depth would make it occlude the very piece casting it.
        _uniform(self.prog, "u_mode").value = 1
        _uniform(self.prog, "u_alpha").value = SHADOW_ALPHA
        _uniform(self.prog, "u_color").value = (0.0, 0.0, 0.0)
        _uniform(self.prog, "u_lift").value = 0.0
        _uniform(self.prog, "u_origin").value = (
            float(ox + SHADOW_OFFSET[0] * pawn.size_px),
            float(oy + SHADOW_OFFSET[1] * pawn.size_px),
        )
        # depth_mask lives on the FRAMEBUFFER in moderngl, not on the context
        # (which has depth_func but no write mask). Setting ctx.depth_mask binds
        # a new attribute on the context and silently does nothing.
        self.fbo.depth_mask = False
        self.shadow_vao.render(moderngl.TRIANGLES)
        self.fbo.depth_mask = True

        _uniform(self.prog, "u_mode").value = 0
        _uniform(self.prog, "u_alpha").value = 1.0
        _uniform(self.prog, "u_color").value = tuple(c / 255.0 for c in pawn.color)
        _uniform(self.prog, "u_lift").value = float(pawn.bob_px)
        _uniform(self.prog, "u_origin").value = (float(ox), float(oy))
        self.pawn_vao.render(moderngl.TRIANGLES)
