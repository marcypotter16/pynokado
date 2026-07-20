import datetime
import math
import os

import pygame as p

from Models.Particles import CPU_Particles_2D, Dust2D, DustParams
from States.State import State
from UI.Label import Label
from UI.Slider import Slider
from Utils.Text import draw_centered_text


class TestParticleState(State):
    """A minimal particle sandbox. A fountain emitter follows the mouse so the
    Particles module can be eyeballed inside the real Game loop. Press [SPACE]
    to toggle whether the emitter tracks the mouse or stays centred."""

    def __init__(self, game, msg=None, layer="foreground"):
        super().__init__(game, msg, layer, bg_color=(18, 18, 24))

        # self.emitter = CPU_Particles_2D(
        # # self.emitter = Dust2D(
        #     pos=p.Vector2(game.GAME_W / 2, game.GAME_H / 2),
        #     min_vel=(-200, -520),
        #     max_vel=(200, -120),
        #     min_rad=4.0,
        #     max_rad=14.0,
        #     min_dur=0.9,
        #     max_dur=2.2,
        #     min_spawn_interval=0.008,
        #     max_spawn_interval=0.02,
        #     max_particles=600,
        # )
        self.emitter = Dust2D(
            pos=p.Vector2(game.GAME_W / 2, game.GAME_H / 2),
            min_speed=20.0,
            max_speed=60.0,
            direction=p.Vector2(1, 0),
            scatter=math.pi / 2,
            min_rad=1.0,
            max_rad=4.0,
            min_dur=12.0,
            max_dur=60.0,
            min_spawn_interval=0.05,
            max_spawn_interval=1.0,
            max_particles=300,
            dust_params=DustParams(
                wind=p.Vector2(15.0, 0.0),
                wind_gust=12.0,
            ),
        )
        self.follow_mouse = True
        self.hud_font = game.fonts["comfortaa"]["small"]
        self._save_msg = ""

        self._build_sliders()

    def _build_sliders(self):
        """A stack of labeled sliders on the left, each bound to a live emitter
        param via a setter. Values are pushed onto the emitter every frame in
        update(), so tweaks take effect immediately."""
        dp = self.emitter.dust_params
        em = self.emitter
        # current cone heading in degrees, for the direction slider.
        dir_deg = math.degrees(math.atan2(em.direction.y, em.direction.x))
        # (label, start, end, default, decimals, setter). Physical units:
        # gravity px/s^2, drag 1/s, turbulence px/s^2, drift deg/s,
        # speeds px/s, dir/scatter degrees.
        specs = [
            ("min_speed", 0.0, 200.0, em.min_speed, 0,
             lambda v: setattr(em, "min_speed", v)),
            ("max_speed", 0.0, 400.0, em.max_speed, 0,
             lambda v: setattr(em, "max_speed", v)),
            ("direction", -180.0, 180.0, dir_deg, 0,
             lambda v: setattr(em, "direction", p.Vector2(1, 0).rotate(v))),
            ("scatter", 0.0, 360.0, math.degrees(em.scatter), 0,
             lambda v: setattr(em, "scatter", math.radians(v))),
            ("min_spawn", 0.001, 2.0, em.min_spawn_interval, 3,
             lambda v: setattr(em, "min_spawn_interval", v)),
            ("max_spawn", 0.001, 4.0, em.max_spawn_interval, 3,
             lambda v: setattr(em, "max_spawn_interval", v)),
            ("gravity", -30.0, 60.0, dp.gravity, 1,
             lambda v: setattr(dp, "gravity", v)),
            ("drag", 0.0, 4.0, dp.drag, 2, lambda v: setattr(dp, "drag", v)),
            ("turbulence", 0.0, 120.0, dp.turbulence, 1,
             lambda v: setattr(dp, "turbulence", v)),
            ("turb_drift", 0.0, 720.0, dp.turbulence_drift, 0,
             lambda v: setattr(dp, "turbulence_drift", v)),
            ("wind_x", -80.0, 80.0, dp.wind.x, 1,
             lambda v: setattr(dp.wind, "x", v)),
            ("wind_y", -80.0, 80.0, dp.wind.y, 1,
             lambda v: setattr(dp.wind, "y", v)),
            ("wind_gust", 0.0, 60.0, dp.wind_gust, 1,
             lambda v: setattr(dp, "wind_gust", v)),
            ("glow", 0.0, 1.0, dp.glow, 2, lambda v: setattr(dp, "glow", v)),
            ("glow_speed", 0.0, 6.0, dp.glow_speed, 2,
             lambda v: setattr(dp, "glow_speed", v)),
            ("min_rad", 0.0, 20.0, em.min_rad, 1,
             lambda v: setattr(em, "min_rad", v)),
            ("max_rad", 0.0, 30.0, em.max_rad, 1,
             lambda v: setattr(em, "max_rad", v)),
            ("max_particles", 0.0, 1200.0, em.max_particles, 0,
             lambda v: setattr(em, "max_particles", int(v))),
        ]

        self._sliders = []
        self._setters = []
        panel_x, panel_y, row_h = 24, 30, 46
        for i, (name, start, end, default, decimals, setter) in enumerate(specs):
            y = panel_y + i * row_h
            Label(self.canvas, x=panel_x, y=y, text=name, fg_color=(210, 210, 220))
            slider = Slider(
                self.canvas,
                x=panel_x,
                y=y + 22,
                width=180,
                height=16,
                bg_color=(40, 40, 48),
                fg_color=(200, 200, 210),
                start=start,
                end=end,
                default=default,
                decimals=decimals,
            )
            self._sliders.append(slider)
            self._setters.append(setter)

    def update(self, delta_time):
        super().update(delta_time)

        for event in self.game.events:
            if event.type == p.KEYDOWN and event.key == p.K_SPACE:
                self.follow_mouse = not self.follow_mouse
            elif event.type == p.KEYDOWN and event.key == p.K_s:
                self._save_params()

        for slider, setter in zip(self._sliders, self._setters):
            setter(slider.value)

        if self.follow_mouse:
            self.emitter.pos = p.Vector2(self.game.cursorpos)
        else:
            self.emitter.pos = p.Vector2(self.game.GAME_W / 2,
                                         self.game.GAME_H / 2)

        self.emitter.update(delta_time)

    def render(self, surface):
        super().render(surface)
        self._draw_emitter_gizmo(surface)
        self.emitter.render(surface)

        hud = (f"Particle sandbox   particles: {len(self.emitter.particles)}   "
               f"[SPACE] follow mouse: {'on' if self.follow_mouse else 'off'}   "
               f"[S] save params   {self._save_msg}")
        hud_rect = p.Rect(0, self.game.GAME_H - 48, self.game.GAME_W, 32)
        draw_centered_text(self.hud_font, surface, hud, (200, 200, 210), hud_rect)

    def _save_params(self):
        """Write the live emitter + dust params as a paste-ready Python snippet."""
        em = self.emitter
        dp = em.dust_params
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = os.path.join(os.getcwd(), "saved_dust")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"dust_params_{stamp}.py")

        snippet = (
            "# Auto-saved from the particle sandbox -- paste into your code.\n"
            "import pygame as p\n"
            "from Models.Particles import Dust2D, DustParams\n\n"
            "emitter = Dust2D(\n"
            f"    pos=p.Vector2({em.pos.x:.1f}, {em.pos.y:.1f}),\n"
            f"    min_speed={em.min_speed:.2f},\n"
            f"    max_speed={em.max_speed:.2f},\n"
            f"    direction=p.Vector2({em.direction.x:.4f}, {em.direction.y:.4f}),\n"
            f"    scatter={em.scatter:.4f},  # radians ({math.degrees(em.scatter):.0f} deg)\n"
            f"    min_rad={em.min_rad:.2f},\n"
            f"    max_rad={em.max_rad:.2f},\n"
            f"    min_dur={em.min_dur:.2f},\n"
            f"    max_dur={em.max_dur:.2f},\n"
            f"    min_spawn_interval={em.min_spawn_interval:.4f},\n"
            f"    max_spawn_interval={em.max_spawn_interval:.4f},\n"
            f"    max_particles={int(em.max_particles)},\n"
            "    dust_params=DustParams(\n"
            f"        gravity={dp.gravity:.2f},\n"
            f"        drag={dp.drag:.3f},\n"
            f"        turbulence={dp.turbulence:.2f},\n"
            f"        turbulence_drift={dp.turbulence_drift:.1f},\n"
            f"        wind=p.Vector2({dp.wind.x:.2f}, {dp.wind.y:.2f}),\n"
            f"        wind_gust={dp.wind_gust:.2f},\n"
            f"        wind_gust_period={dp.wind_gust_period:.2f},\n"
            f"        glow={dp.glow:.3f},\n"
            f"        glow_speed={dp.glow_speed:.3f},\n"
            "    ),\n"
            ")\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(snippet)
        self._save_msg = f"saved -> {os.path.relpath(path, os.getcwd())}"
        print(self._save_msg)

    def _draw_emitter_gizmo(self, surface):
        """Overlay showing the emitter's aim: a green direction arrow and two
        amber lines marking the edges of the scatter cone."""
        em = self.emitter
        origin = p.Vector2(em.pos)
        length = 120.0
        direction = em.direction
        half = em.scatter * 0.5

        # scatter cone edges (rotate the direction by +/- half the cone angle)
        for edge in (direction.rotate_rad(half), direction.rotate_rad(-half)):
            p.draw.line(surface, (200, 150, 40),
                        origin, origin + edge * length, 2)

        # direction arrow
        tip = origin + direction * length
        p.draw.line(surface, (60, 220, 90), origin, tip, 3)
        # arrowhead: two short lines swept back from the tip
        for a in (150, -150):
            barb = direction.rotate(a) * 18
            p.draw.line(surface, (60, 220, 90), tip, tip + barb, 3)

        p.draw.circle(surface, (60, 220, 90), (int(origin.x), int(origin.y)), 4)
