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

# Simple texture pass-through fragment shader
WINDOW_SCALING_FRAG_SRC = """
#version 330

uniform sampler2D tex;
in vec2 v_uv;
out vec4 fragColor;

void main() {
    fragColor = texture(tex, v_uv);
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

        # Create fullscreen quad
        self.quad_vbo = self._create_quad_vbo()
        self.quad_vao = self.ctx.simple_vertex_array(
            self.programs["window_scaling"], self.quad_vbo, "in_pos", "in_uv"
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

        Args:
            surface: Pygame surface to upload (should match game_size)
        """
        self.game_texture.write(p.image.tobytes(surface, "RGBA", True))

    def render(self, clear_color: tuple = (0.0, 0.0, 0.0, 1.0)):
        """Render the game texture to screen.

        Args:
            clear_color: RGBA clear color for letterbox bars
        """
        self.ctx.viewport = self.viewport
        self.ctx.clear(*clear_color)
        self.game_texture.use(0)
        self.quad_vao.render(moderngl.TRIANGLE_STRIP)
