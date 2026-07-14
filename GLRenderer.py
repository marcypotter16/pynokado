import os
import moderngl
from moderngl import Context, Texture
from numpy import array
import pygame as p

# Load shader sources
_SHADER_DIR = os.path.dirname(__file__)


def _load_shader(filename: str) -> str:
    with open(os.path.join(_SHADER_DIR, filename)) as f:
        return f.read()


# Common vertex shader for fullscreen quad
VERT_SRC = """
#version 330

in vec2 in_pos;
in vec2 in_uv;

out vec2 v_uv;

void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

# Pass-through fragment shader. The game texture is uploaded straight from the
# pygame surface buffer (no CPU convert/flip), which means:
#   * pixels arrive as BGRA (surface native order) -> swizzle .bgra to RGBA
#   * the buffer is top-row-first while GL samples bottom-up -> flip V
WINDOW_SCALING_FRAG_SRC = """
#version 330

uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    vec2 uv = vec2(v_uv.x, 1.0 - v_uv.y);   // flip vertically
    fragColor = texture(tex, uv).bgra;      // BGRA -> RGBA, force opaque below
    fragColor.a = 1.0;                       // surface has no alpha channel
}
"""


class GLRenderer:
    """Handles OpenGL rendering for the game, including window scaling and effects."""

    def __init__(self, ctx: Context, game_size: tuple[int, int]):
        """Initialize the GL renderer.

        Args:
            ctx: ModernGL context
            game_size: (width, height) of the game canvas
        """
        self.ctx = ctx
        self.game_w, self.game_h = game_size

        # Enable blending for transparency
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA

        # Create the game texture
        self.game_texture = self._create_texture(game_size)

        # Load shader programs
        self.programs = {
            "window_scaling": ctx.program(
                vertex_shader=VERT_SRC,
                fragment_shader=WINDOW_SCALING_FRAG_SRC,
            ),
        }

        # Try to load optional buff shader
        try:
            buff_frag = _load_shader("buff_sheen.glsl")
            self.programs["buff"] = ctx.program(
                vertex_shader=VERT_SRC,
                fragment_shader=buff_frag,
            )
        except FileNotFoundError:
            print("[Warning] Buff Shader file not found")

        # Optional hover-glow shader (additive pass around a hovered card).
        try:
            glow_frag = _load_shader("hover_glow.glsl")
            self.programs["hover_glow"] = ctx.program(
                vertex_shader=VERT_SRC,
                fragment_shader=glow_frag,
            )
        except FileNotFoundError:
            print("[Warning] Hover-glow shader file not found")

        # Create fullscreen quad
        self.quad_vbo = self._create_quad_vbo()
        self.quad_vao = self.ctx.simple_vertex_array(
            self.programs["window_scaling"], self.quad_vbo, "in_pos", "in_uv"
        )
        # Separate VAO bound to the glow program (each program needs its own).
        self.glow_vao = None
        if "hover_glow" in self.programs:
            self.glow_vao = self.ctx.simple_vertex_array(
                self.programs["hover_glow"], self.quad_vbo, "in_pos", "in_uv"
            )

        # Scaling values (set by set_viewport)
        self.viewport = (0, 0, self.game_w, self.game_h)

    def _create_texture(self, size: tuple[int, int]) -> Texture:
        """Create a texture for the game canvas."""
        texture = self.ctx.texture(size, 4)
        texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        texture.repeat_x = False
        texture.repeat_y = False
        return texture

    def _create_quad_vbo(self):
        """Create a fullscreen quad vertex buffer."""
        vertices = array(
            [
                # x,    y,   u,   v
                -1.0,
                -1.0,
                0.0,
                0.0,
                1.0,
                -1.0,
                1.0,
                0.0,
                -1.0,
                1.0,
                0.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
            ],
            dtype="f4",
        )
        return self.ctx.buffer(vertices.tobytes())

    def set_viewport(self, screen_w: int, screen_h: int) -> dict:
        """Calculate and set the viewport for letterboxing.

        Args:
            screen_w: Screen width
            screen_h: Screen height

        Returns:
            dict with scaling info: game_to_screen_scale, screen_to_game_scale,
                                    scaled_size, offset
        """
        scale_x = screen_w / self.game_w
        scale_y = screen_h / self.game_h
        game_to_screen_scale = min(scale_x, scale_y)
        screen_to_game_scale = 1 / game_to_screen_scale

        scaled_size = (
            int(self.game_w * game_to_screen_scale),
            int(self.game_h * game_to_screen_scale),
        )

        offset = (
            (screen_w - scaled_size[0]) // 2,
            (screen_h - scaled_size[1]) // 2,
        )

        # OpenGL viewport (y is from bottom)
        viewport_y = screen_h - offset[1] - scaled_size[1]
        self.viewport = (offset[0], viewport_y, scaled_size[0], scaled_size[1])
        self.ctx.viewport = self.viewport

        return {
            "game_to_screen_scale": game_to_screen_scale,
            "screen_to_game_scale": screen_to_game_scale,
            "scaled_size": scaled_size,
            "offset": offset,
        }

    def upload_surface(self, surface: p.Surface):
        """Upload a pygame surface to the game texture.

        Fast path: hand the surface's raw pixel buffer straight to the GPU with
        NO CPU copy. `p.image.tobytes(surface, "RGBA", True)` allocated and
        serialised an ~8 MB byte string every frame (~11 ms at 1080p) *and*
        flipped it on the CPU -- it was over half the frame time even when idle.

        The trade: get_buffer() gives raw memory in the surface's native order
        (BGRA on little-endian) and does NOT flip vertically. So we fix both in
        the fragment shader instead: sample .bgra and invert the V coordinate.

        Args:
            surface: Pygame surface to upload (should match game_size)
        """
        self.game_texture.write(surface.get_buffer())

    def render(self, clear_color: tuple = (0.0, 0.0, 0.0, 1.0)):
        """Render the game texture to screen.

        Args:
            clear_color: RGBA clear color for letterbox bars
        """
        self.ctx.viewport = self.viewport
        self.ctx.clear(*clear_color)
        self.game_texture.use(0)
        self.quad_vao.render(moderngl.TRIANGLE_STRIP)

    MAX_GLOW_CARDS = 12  # must match MAX_CARDS in hover_glow.glsl

    def render_glows(
        self,
        cards: list,
        time_s: float,
        radius_px: float = 70.0,
    ):
        """Single additive glow pass for ALL lit shapes. `cards` is a list of
        (rect_px, color, intensity[, corner]) tuples -- rect in game pixels,
        top-left origin; optional `corner` is the corner radius in px (>=
        min(w,h)/2 makes the glow a circle, e.g. for placed stones). One draw
        call; each shape's glow fades with its own intensity so moving between
        them cross-fades. No-op if the shader is missing or nothing is lit."""
        if self.glow_vao is None or not cards:
            return
        cards = cards[: self.MAX_GLOW_CARDS]
        prog = self.programs["hover_glow"]
        self.ctx.viewport = self.viewport

        # Pack the whole fixed-size arrays (zero-padded) and upload in one write
        # each -- moderngl uniform arrays are set wholesale, not per-index.
        n = self.MAX_GLOW_CARDS
        rects = array([[0, 0, 0, 0]] * n, dtype="f4")
        colors = array([[0, 0, 0]] * n, dtype="f4")
        intensities = array([0] * n, dtype="f4")
        corners = array([0] * n, dtype="f4")
        for i, entry in enumerate(cards):
            rect, color, intensity = entry[0], entry[1], entry[2]
            corner = entry[3] if len(entry) > 3 else 0.0
            rects[i] = rect
            colors[i] = color
            intensities[i] = intensity
            corners[i] = corner

        prog["u_res"].value = (float(self.game_w), float(self.game_h))
        prog["u_time"].value = float(time_s)
        prog["u_radius"].value = float(radius_px)
        prog["u_count"].value = len(cards)
        prog["u_rects"].write(rects.tobytes())
        prog["u_colors"].write(colors.tobytes())
        prog["u_intensities"].write(intensities.tobytes())
        prog["u_corners"].write(corners.tobytes())
        self.glow_vao.render(moderngl.TRIANGLE_STRIP)
