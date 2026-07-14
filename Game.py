import os
from typing import Dict

import moderngl

from GLRenderer import GLRenderer
from Resolution import set_dpi_awareness
from Settings import GameSettings
# from SocketManager import SocketManager
from Utils.Timer import SpacedCallback, Timer, TimerManager

set_dpi_awareness()

import pygame as p

import time

from Collections.Stack import Stack
from Tween.Tween import TweenManager
from Utils.Text import draw_centered_text


class Game:
    def __init__(self, workdir: str = os.getcwd(), use_shaders: bool = False):
        self.need_key_event_handling = True
        self.events = None
        self.clock = p.time.Clock()
        self.font_dir = None
        self.assets_dir = None
        self.font_medium = None  # This has to be set!
        self.title_screen = None
        self.show_stats = True

        # self.socket_manager: SocketManager = SocketManager()

        p.init()
        p.mixer.init()
        file = open(os.path.join(os.getcwd(), "settings.json"), "r")
        self.settings = GameSettings.from_json(file.read())
        p.mouse.set_visible(self.settings.MOUSE_VISIBLE)

        self.GAME_W, self.GAME_H = 1920, 1080
        self.GAME_SCREEN_RATIO = (
            int(float(self.GAME_W) / self.settings.SCREEN_W),
            int(float(self.GAME_H) / self.settings.SCREEN_H),
        )
        self.GAME_CENTER = (self.GAME_W / 2, self.GAME_H / 2)
        self.game_canvas = p.Surface((self.GAME_W, self.GAME_H))

        self.screen = p.display.set_mode(
            (self.settings.SCREEN_W, self.settings.SCREEN_H),
            p.RESIZABLE | p.OPENGL | p.DOUBLEBUF,
            vsync=0,
        )

        # Initialize OpenGL renderer
        self.glctx = moderngl.create_context()
        self.gl_renderer = GLRenderer(self.glctx, (self.GAME_W, self.GAME_H))

        # Scaling values (updated by _recompute_scaling)
        self.game_to_screen_scale: float = 1.0
        self.screen_to_game_scale: float = 1.0
        self.scaled_size: tuple[int, int] = (self.GAME_W, self.GAME_H)
        self.game_canvas_offset: tuple[int, int] = (0, 0)

        # Post-render callbacks for GPU effects (called after main canvas render, before flip)
        self.post_render_callbacks: list[callable] = []

        self._recompute_scaling()
        self.running, self.playing = True, True
        self.actions: dict[str, int] = {
            "left": 0,
            "right": 0,
            "up": 0,
            "jump": 0,
            "down": 0,
            "action1": 0,
            "glide": 0,
            "start": 0,
            "mouse_sx": 0,
            "mouse_dx": 0,
        }
        self.jump_action_changed: int = 0
        self.clicked_sx: int = 0
        self.clicked_dx: int = 0
        self.dt, self.prev_time = 0, 0
        self.elapsed = 0.0  # seconds since start, for shader animation
        self.state_stack = Stack()

        self.tweener_manager: TweenManager = TweenManager()
        self.timer_manager: TimerManager = TimerManager()

        # self.event_system = EventSystem()

        # TODO: Make a render stack
        # Structure:
        #  key: layer
        #  value: list of render functions to call
        self.render_stack = {"background": [], "foreground": [], "above_all": []}

        self.cursorpos = None
        self.base_dir = workdir
        self.load_assets()
        self.load_map()
        self.load_states()
        self.load_sounds()

    def game_loop(self):
        while self.playing:
            self.get_dt()
            self.get_events()
            self.update()
            self.render()
            self.clock.tick(self.settings.FPS)

    def get_events(self):
        self.events = p.event.get()
        aux_prev_jump_action = self.actions["jump"]
        aux_prev_mouse_sx = self.actions["mouse_sx"]
        aux_prev_mouse_dx = self.actions["mouse_dx"]
        for event in self.events:
            if event.type == p.QUIT:
                self.playing, self.running = False, False

            if event.type == p.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self.actions["mouse_sx"] = 1
                if event.button == 3:
                    self.actions["mouse_dx"] = 1

            if event.type == p.MOUSEBUTTONUP:
                if event.button == 1:
                    self.actions["mouse_sx"] = 0
                if event.button == 3:
                    self.actions["mouse_dx"] = 0

            if self.need_key_event_handling:
                if event.type == p.KEYDOWN:
                    if event.key == p.K_ESCAPE:
                        self.playing, self.running = False, False
                    if event.key == p.K_a:
                        self.actions["left"] = 1
                    if event.key == p.K_d:
                        self.actions["right"] = 1
                    if event.key == p.K_s:
                        self.actions["down"] = 1
                    if event.key == p.K_w:
                        self.actions["up"] = 1
                        self.actions["jump"] = 1
                    if event.key == p.K_1:
                        self.actions["action1"] = 1
                    if event.key == p.K_SPACE:
                        self.actions["glide"] = 1
                    if event.key == p.K_3:
                        self.actions["start"] = 1
                if event.type == p.KEYUP:
                    if event.key == p.K_a:
                        self.actions["left"] = 0
                    if event.key == p.K_d:
                        self.actions["right"] = 0
                    if event.key == p.K_s:
                        self.actions["down"] = 0
                    if event.key == p.K_w:
                        self.actions["up"] = 0
                        self.actions["jump"] = 0
                        self.actions["down"] = 0
                    if event.key == p.K_1:
                        self.actions["action1"] = 0
                    if event.key == p.K_SPACE:
                        self.actions["glide"] = 0
                    if event.key == p.K_3:
                        self.actions["start"] = 0
                if event.type == p.VIDEORESIZE:
                    self.settings.SCREEN_W, self.settings.SCREEN_H = event.size
                    self.screen = p.display.set_mode(
                        event.size, p.RESIZABLE | p.OPENGL | p.DOUBLEBUF, vsync=0
                    )
                    self._recompute_scaling()
            self.jump_action_changed = self.actions["jump"] - aux_prev_jump_action
        self.clicked_sx = self.actions["mouse_sx"] - aux_prev_mouse_sx
        self.clicked_dx = self.actions["mouse_dx"] - aux_prev_mouse_dx
        # print(self.jump_action_changed)

    def _recompute_scaling(self):
        """Recompute scaling values and update GL viewport."""
        scaling_info = self.gl_renderer.set_viewport(
            self.settings.SCREEN_W, self.settings.SCREEN_H
        )
        self.game_to_screen_scale = scaling_info["game_to_screen_scale"]
        self.screen_to_game_scale = scaling_info["screen_to_game_scale"]
        self.scaled_size = scaling_info["scaled_size"]
        self.game_canvas_offset = scaling_info["offset"]

    def update(self):
        # Convert screen mouse position to game coordinates, accounting for letterbox
        screen_mouse = p.mouse.get_pos()
        # Subtract letterbox offset to get position relative to game area
        # Get position relative to scaled game area
        relative_x = screen_mouse[0] - self.game_canvas_offset[0]
        relative_y = screen_mouse[1] - self.game_canvas_offset[1]
        # Clamp to scaled game bounds (0 to scaled_size)
        relative_x = max(0, min(relative_x, self.scaled_size[0]))
        relative_y = max(0, min(relative_y, self.scaled_size[1]))
        # Scale to game coordinates
        self.cursorpos = (
            relative_x * self.screen_to_game_scale,
            relative_y * self.screen_to_game_scale,
        )
        # self.state_stack.top().update(self.dt, self.actions)
        self.state_stack.top().update(self.dt)
        self.tweener_manager.update()
        self.timer_manager.update()

    def render(self):
        self.state_stack.top().render(self.game_canvas)
        if self.show_stats:
            self.print_stats(self.game_canvas)
        # Render cursor above everything on game canvas
        if not self.settings.MOUSE_VISIBLE and self.cursorpos:
            p.draw.circle(self.game_canvas, p.Color("white"), self.cursorpos, 5)
            p.draw.circle(self.game_canvas, p.Color("black"), self.cursorpos, 8, 2)

        # Upload game canvas to GPU and render
        self.gl_renderer.upload_surface(self.game_canvas)
        self.gl_renderer.render()

        # GPU post-processing effects (buff sheen, etc.)
        for callback in self.post_render_callbacks:
            callback()

        p.display.flip()

    def print_stats(self, surf):
        # canvas = self.state_stack.top().canvas
        # container = VertContainer(canvas, x=800)
        # label = Label(container, text=f"fps: {self.fps}")
        # container.pack()
        rect = p.Rect((0, 0), (120, 30))
        col = p.Color(0, 255, 0)
        p.draw.rect(surf, col, rect, 1, 2)
        draw_centered_text(
            self.fonts["ant"]["medium"],
            surf,
            f"fps: {round(self.clock.get_fps())}",
            col,
            rect,
        )
        # self.game_canvas

    def get_dt(self):
        now = time.time()
        self.dt = now - self.prev_time if self.prev_time > 0 else 0
        self.prev_time = now
        # Small, monotonically-increasing clock for shaders. Wall-clock
        # (prev_time ~1.7e9) has too little float32 precision left for smooth
        # per-frame animation, so accumulate elapsed seconds near zero instead.
        self.elapsed += self.dt

    def load_assets(self):
        # TODO
        # To be modified
        self.assets_dir = os.path.join(self.base_dir, "Assets")
        print(self.base_dir, self.assets_dir)
        # self.sprite_dir = os.path.join(self.assets_dir, "sprites")
        self.font_dir = os.path.join(self.assets_dir, "font")

        # Structured fonts dictionary - Using pygame.font.Font
        self.fonts: Dict[str, Dict[str, p.font.Font]] = {}

        # Font configurations: (filename, [big, medium, small, tiny])
        font_configs = {
            "comfortaa": ("Comfortaa-Regular.ttf", [40, 20, 14, 10]),
            "javier_skull": ("Javier Skull.ttf", [50, 26, 18, 12]),
            "october_crow": ("October Crow.ttf", [50, 26, 18, 12]),
            "press_start": ("PressStart.ttf", [30, 16, 10, 6]),
            "ant": ("AntykwaTorunska-Regular.otf", [45, 25, 20, 10]),
            "stix": ("STIXTwoMath-Regular.otf", [0, 0, 0, 0]),
            # Drop the real files in Assets/font/ with these names (or adjust
            # the filenames here). Missing files fall back to the default font.
            "inconsolata": ("InconsolataNerdFont-Regular.ttf", [40, 22, 16, 11]),
            "ghibli": ("Ghibli.otf", [40, 22, 16, 11]),
            # --- brush / ink faces (good for this ink-wash card style) ---
            "kashima": ("Kashima.otf", [40, 22, 16, 11]),
            "korean_calligraphy": ("KoreanCalligraphy.ttf", [40, 22, 16, 11]),
            "mgs4_brush": ("MGS4Brush.ttf", [40, 22, 16, 11]),
            "sigokae": ("Sigokae.ttf", [40, 22, 16, 11]),
            "harukaze": ("Harukaze.ttf", [60, 42, 36, 20]),
            # --- handwritten / script ---
            "biro_script": ("BiroScript.ttf", [40, 22, 16, 11]),
            "handmade": ("Handmade.otf", [40, 22, 16, 11]),
            "hogback": ("Hogback.otf", [40, 22, 16, 11]),
            "sandwich": ("Sandwich.otf", [40, 22, 16, 11]),
            # --- themed (e.g. a real in-game shop screen) ---
            "chinese_watch_shop": ("ChineseWatchShop.ttf", [60, 42, 36, 20]),
        }

        sizes = ["big", "medium", "small", "tiny"]

        # Load fonts (missing files degrade to pygame's default font instead of
        # crashing, so the font-switch keeps working before assets land).
        for font_name, (filename, font_sizes) in font_configs.items():
            self.fonts[font_name] = {}
            path = os.path.join(self.font_dir, filename)
            exists = os.path.isfile(path)
            if not exists:
                print(f"[Font] '{filename}' not found - using default for '{font_name}'")
            for i, size_name in enumerate(sizes):
                src = path if exists else None
                self.fonts[font_name][size_name] = p.font.Font(src, font_sizes[i])

        # Legacy properties for backward compatibility
        self.font_medium = self.fonts["comfortaa"]["medium"]
        self.font_big = self.fonts["comfortaa"]["big"]
        self.font_small = self.fonts["comfortaa"]["small"]
        self.font_tiny = self.fonts["comfortaa"]["tiny"]

        # Store font file paths for dynamic font creation
        self.font_paths = {
            font_name: os.path.join(self.font_dir, filename)
            for font_name, (filename, _) in font_configs.items()
        }

    def get_font(self, font_name: str, size: int) -> p.font.Font:
        """Get a font at a specific pixel size, creating it dynamically if needed

        Args:
            font_name: Name of the font family (e.g., 'ant', 'comfortaa')
            size: Font size in pixels

        Returns:
            pygame.font.Font at the requested size
        """
        if font_name not in self.font_paths:
            raise ValueError(
                f"Unknown font: {font_name}. Available fonts: {list(self.font_paths.keys())}"
            )

        return p.font.Font(self.font_paths[font_name], size)

    def render_text(
        self,
        text: str,
        font_name: str,
        color: tuple | p.Color = (255, 255, 255),
        target_width: int = None,
        antialias: bool = True,
        base_font_size: int = 20,
    ) -> p.Surface:
        """Render text at the perfect size to fit target width without rescaling

        Args:
            text: The text to render
            font_name: Name of the font family (e.g., 'ant', 'comfortaa')
            color: Text color as RGB tuple or pygame Color
            target_width: Optional target width in pixels - font will be sized to fit
            antialias: Whether to use antialiasing (default: True)
            base_font_size: Initial font size estimate when target_width is specified

        Returns:
            pygame.Surface with rendered text at perfect size (no rescaling needed)
        """
        if target_width is None:
            # No target width - just render at base size
            font = self.get_font(font_name, base_font_size)
            return font.render(text, antialias, color)

        # Calculate exact font size to achieve target width
        # Start with estimate
        font = self.get_font(font_name, base_font_size)
        test_size = font.size(text)  # More efficient than rendering

        if test_size[0] > 0:
            # Calculate perfect font size
            actual_font_size = int(base_font_size * target_width / test_size[0])
            font = self.get_font(font_name, actual_font_size)

        # Render at perfect size - no rescaling needed!
        return font.render(text, antialias, color)

    def render_multiline_text(
        self,
        text: str,
        font_name: str,
        color: tuple | p.Color = (255, 255, 255),
        max_width: int = 300,
        base_font_size: int = 20,
        antialias: bool = True,
    ) -> p.Surface:
        """Render text with word wrapping to fit within max_width

        Args:
            text: The text to render
            font_name: Name of the font family
            color: Text color
            max_width: Maximum width in pixels before wrapping
            base_font_size: Font size to use
            antialias: Whether to use antialiasing

        Returns:
            pygame.Surface with wrapped text
        """
        font = self.get_font(font_name, base_font_size)
        words = text.split(" ")
        lines = []
        current_line = []

        for word in words:
            test_line = " ".join(current_line + [word])
            test_size = font.size(test_line)  # More efficient than rendering

            if test_size[0] <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    # Single word is too long, just add it anyway
                    lines.append(word)

        if current_line:
            lines.append(" ".join(current_line))

        # Create surface to hold all lines
        if not lines:
            return font.render("", antialias, color)

        line_height = font.get_height()
        total_height = line_height * len(lines)

        # Find max width among all lines using size() for efficiency
        max_line_width = max(font.size(line)[0] for line in lines)

        # Create the surface with transparency
        text_surf = p.Surface((max_line_width, total_height), p.SRCALPHA)
        text_surf.fill((0, 0, 0, 0))

        # Render each line
        for i, line in enumerate(lines):
            line_surf = font.render(line, antialias, color)
            text_surf.blit(line_surf, (0, i * line_height))

        return text_surf

    def load_states(self):
        # TO BE DEFINED
        pass
        # self.title_screen = Title(self)
        # self.state_stack.push(self.title_screen)

    def load_map(self):
        pass
        # self.map_dir = os.path.join(self.assets_dir, "map")
        # self.terra = p.transform.scale2x(p.image.load(os.path.join(self.map_dir, 'terra.png')))
        # self.erba = p.transform.scale2x(p.image.load(os.path.join(self.map_dir, 'erbafunghi.png')))
        #
        # map_path = os.path.join(self.map_dir, 'map.txt')
        # map_grid = []
        # with open(map_path, 'r') as f:
        #     lines = f.readlines()
        #     for line in lines:
        #         line = line.strip().split(" ")
        #         map_grid.append(line)
        # self.map = map_grid

    def reset_keys(self):
        for action in self.actions:
            self.actions[action] = False

    def load_sounds(self):
        pass

    def push_state(self, state):
        self.state_stack.push(state)

    def pop_state(self, how_many: int = 1):
        for _ in range(how_many):
            self.state_stack.pop()


if __name__ == "__main__":
    g = Game()
    while g.running:
        g.game_loop()
