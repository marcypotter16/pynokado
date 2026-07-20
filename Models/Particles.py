from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
import math as pymath
import random
import noise

import pygame as p
from pygame import math

from Utils.Colors import WHITE

class EmitterType(Enum):
    SPRITE = 0

class Particle:
    def __init__(
            self,
            pos: p.Vector2 = (0, 0),
            vel: p.Vector2 = (0, 0),
            col: p.Color = WHITE,
            rad: float = 5.0,
            lifespan: float = 10.0
        ):
        self.pos = pos
        self.vel = vel
        self.col = col
        self.rad = rad
        self.lifespan = lifespan
        self._timer = 0.0
        self.need_destroy = False
        # Per-particle turbulence state: a wander angle that drifts slowly so the
        # turbulence force stays coherent frame-to-frame (a swirl) instead of
        # cancelling itself out like white noise. Randomised per particle.
        self.wander_angle = random.uniform(0, 360)
        # Glow noise: a private offset into the noise field so each mote flickers
        # out of sync, plus the base grey/alpha to modulate against (so the
        # per-frame glow doesn't compound). base_alpha is set by the lifespan fade.
        self.glow_seed = random.uniform(0, 1000)
        self.base_grey = col.r
        self.base_alpha = col.a

    def update(self, dt: float):
        self.pos = self.pos + self.vel * dt
        self._timer += dt
        if self._timer >= self.lifespan:
            self.need_destroy = True

    def render(self, surf: p.Surface):
        # draw.circle ignores the color's alpha channel, so to honour per-particle
        # fade we render onto a small SRCALPHA surface and blit it with blending.
        r = int(self.rad)
        buf = p.Surface((r * 2, r * 2), p.SRCALPHA)
        p.draw.circle(buf, self.col, (r, r), r)
        surf.blit(buf, (int(self.pos.x) - r, int(self.pos.y) - r))

class Particles2D(ABC):
    def __init__(
            self,
            pos: p.Vector2 = (0, 0),
            min_vel: p.Vector2 = (0, 0),
            max_vel: p.Vector2 = (100, 100),
            min_rad: float = 2.0,
            max_rad: float = 8.0,
            min_dur: float = 1.0,
            max_dur: float = 10.0,
            min_col: p.Color = p.Color(0, 0, 0, 0),
            max_col: p.Color = p.Color(255, 255, 255),
            min_spawn_interval: float = 2.0,
            max_spawn_interval: float = 5.0,
            max_particles: int = 100,
            emitter_type: EmitterType = EmitterType.SPRITE 
        ):
        super().__init__()
        self.pos = pos
        self.min_vel = min_vel
        self.max_vel = max_vel
        self.min_rad = min_rad
        self.max_rad = max_rad
        self.min_dur = min_dur
        self.max_dur = max_dur
        self.min_col = min_col
        self.max_col = max_col
        self.min_spawn_interval = min_spawn_interval
        self.max_spawn_interval = max_spawn_interval
        self.max_particles = max_particles
        self.emitter_type = emitter_type

        self.particles: list[Particle] = []
        self._timer = 0.0
        self._spawn_timer = 0.0
        self._currently_chosen_spawn_interval = random.uniform(self.min_spawn_interval, self.max_spawn_interval)
    
    @staticmethod
    def _get_rand_vec(min: float, max: float, vec_len: int = 2) -> list:
        l = []
        for _ in range(vec_len):
            l.append(random.uniform(min, max))
        return l

    def _rand_color(self) -> "p.Color":
        # One uniform value drives all three channels -> greyscale mote.
        v = int(random.uniform(0, 255))
        return p.Color(v, v, v, 255)

    def _rand_velocity(self) -> "p.Vector2":
        min_v = p.Vector2(self.min_vel)
        max_v = p.Vector2(self.max_vel)
        return p.Vector2(
            random.uniform(min_v.x, max_v.x),
            random.uniform(min_v.y, max_v.y),
        )

    def update(self, dt: float) -> None:
        self._timer += dt
        self._spawn_timer += dt
        if (self._spawn_timer >= self._currently_chosen_spawn_interval
                and len(self.particles) < self.max_particles):
            self.particles.append(
                Particle(
                    p.Vector2(self.pos),
                    self._rand_velocity(),
                    col=self._rand_color(),
                    rad=random.uniform(self.min_rad, self.max_rad),
                    lifespan=random.uniform(self.min_dur, self.max_dur)
                )
            )
            self._spawn_timer = 0.0
            self._currently_chosen_spawn_interval = random.uniform(self.min_spawn_interval, self.max_spawn_interval)
        self.particles = [particle for particle in self.particles if not particle.need_destroy]
        self._update_particles(dt)
        
    def _update_particles(self, dt: float):
        for particle in self.particles:
            particle.update(dt)

    def render(self, surf: p.Surface) -> None:
        for particle in self.particles:
            particle.render(surf)

class CPU_Particles_2D(Particles2D):
    def __init__(
            self,
            pos=(0, 0),
            min_vel=(0, 0),
            max_vel=(100, 100),
            min_rad=2.0,
            max_rad=8.0,
            min_dur=1.0,
            max_dur=10.0,
            min_col=p.Color(0, 0, 0, 0),
            max_col=p.Color(255, 255, 255),
            min_spawn_interval=2.0,
            max_spawn_interval=5.0,
            max_particles=100,
            emitter_type=EmitterType.SPRITE
        ):
        super().__init__(
            pos, min_vel, max_vel, min_rad, max_rad,
            min_dur, max_dur, min_col, max_col,
            min_spawn_interval, max_spawn_interval, max_particles, emitter_type
        )

    def update(self, dt):
        super().update(dt)

    def render(self, surf):
        super().render(surf)

@dataclass
class DustParams:
    """Physical parameters for dust motion, all in real units so the sliders map
    onto quantities you can reason about.

    :param gravity: downward acceleration in px/s^2. Positive pulls motes down.
        Use a small negative value to make dust rise (hot air / embers).
    :param drag: air-resistance coefficient (1/s). Acceleration is -drag * vel,
        so bigger = motes reach terminal velocity sooner and drift more slowly.
        Terminal fall speed ~= gravity / drag.
    :param turbulence: strength of the wandering swirl force in px/s^2. Unlike
        white noise this force stays coherent for a while, so it actually shows.
    :param turbulence_drift: how fast (deg/s) each mote's wander direction turns.
        Small = long lazy swirls, large = jittery churn.
    :param wind: external force (px/s^2) applied equally to every mote. A steady
        push; combined with turbulence it reads as organic drifting air.
    :param wind_gust: amplitude (px/s^2) of a slow global gust that oscillates
        the wind over time, so the whole field breathes instead of sliding at a
        constant rate. Set to 0 for perfectly steady wind.
    :param wind_gust_period: seconds for one full gust oscillation.
    :param glow: how strongly erratic Perlin noise modulates each mote's
        brightness and alpha, in [0, 1]. 0 = steady, 1 = motes fully wink between
        dark/transparent and bright/opaque as they drift. Reads as dust catching
        stray light. Per-particle noise phase keeps it organic and non-repeating.
    :param glow_speed: how fast (1/s) the noise scrolls -- higher = faster flicker.
    """

    gravity: float = 12.0
    drag: float = 0.8
    turbulence: float = 25.0
    turbulence_drift: float = 120.0
    # default_factory: dataclasses forbid a mutable/shared default, and each
    # instance should own its own Vector2.
    wind: p.Vector2 = field(default_factory=lambda: p.Vector2(0.0, 0.0))
    wind_gust: float = 0.0
    wind_gust_period: float = 6.0
    glow: float = 0.5
    glow_speed: float = 1.5

    def __post_init__(self):
        # Accept a tuple/list for wind and normalise to a Vector2, preserving the
        # old __init__'s behaviour (e.g. DustParams(wind=(15, 0))).
        self.wind = p.Vector2(self.wind)

class Dust2D(CPU_Particles_2D):
    """Dust emitter using a polar *cone* emission model instead of the base
    class's component-wise velocity rectangle.

    Particles leave the source with a random speed in [min_speed, max_speed] and
    a random heading inside a cone of total angle ``scatter`` (radians) centred
    on ``direction``. E.g. direction=(1,0), scatter=pi/2 emits into a 90-degree
    cone facing right. Put the source just off-screen to have dust drift in.
    """

    def __init__(
            self,
            pos=(0, 0),
            min_speed: float = 20.0,
            max_speed: float = 60.0,
            direction: p.Vector2 = (1, 0),
            scatter: float = pymath.pi / 2,
            min_rad=2,
            max_rad=8,
            min_dur=1,
            max_dur=10,
            min_spawn_interval=2,
            max_spawn_interval=5,
            max_particles=100,
            emitter_type=EmitterType.SPRITE,
            dust_params: DustParams = None
        ):

        super().__init__(pos, (0, 0), (0, 0), min_rad, max_rad, min_dur, max_dur,
                         min_spawn_interval=min_spawn_interval, max_spawn_interval=max_spawn_interval,
                         max_particles=max_particles,
                         emitter_type=emitter_type)
        self.min_speed = min_speed
        self.max_speed = max_speed
        self.scatter = scatter
        self.direction = direction
        # Fresh default per emitter: a shared DustParams() default arg would let
        # one emitter's slider tweaks leak into others.
        self.dust_params = dust_params if dust_params is not None else DustParams()

    @property
    def direction(self) -> "p.Vector2":
        return self._direction

    @direction.setter
    def direction(self, value):
        v = p.Vector2(value)
        # keep a normalised heading; fall back to +x if a zero vector is given.
        self._direction = v.normalize() if v.length_squared() > 0 else p.Vector2(1, 0)

    def _rand_velocity(self) -> "p.Vector2":
        # random speed in range, random heading within +/- scatter/2 of direction.
        speed = random.uniform(self.min_speed, self.max_speed)
        half = self.scatter * 0.5
        offset = random.uniform(-half, half)  # radians
        return self._direction.rotate_rad(offset) * speed

    def update(self, dt):
        super().update(dt)

    def _update_particles(self, dt: float):
        dp = self.dust_params

        # Wind is shared by every mote. A slow global gust oscillates it so the
        # whole field breathes instead of sliding at a constant rate. The gust
        # adds a perpendicular sway to the base wind direction.
        wind = p.Vector2(dp.wind)
        if dp.wind_gust != 0.0 and dp.wind_gust_period > 0.0:
            phase = pymath.tau * self._timer / dp.wind_gust_period
            base = dp.wind if dp.wind.length_squared() > 0 else p.Vector2(1, 0)
            perp = p.Vector2(-base.y, base.x)
            if perp.length_squared() > 0:
                perp = perp.normalize()
            wind = wind + perp * (dp.wind_gust * pymath.sin(phase))

        for part in self.particles:
            # --- accumulate accelerations (px/s^2), then integrate once ---
            accel = p.Vector2(0, dp.gravity)          # gravity: constant, downward
            accel += -dp.drag * part.vel              # drag: opposes velocity
            accel += wind                             # external wind force

            # turbulence: a coherent wander force. The direction turns slowly, so
            # over several frames it pushes the same way long enough to be seen,
            # instead of self-cancelling like a fresh random kick every frame.
            part.wander_angle += random.uniform(-1, 1) * dp.turbulence_drift * dt
            accel += p.Vector2(1, 0).rotate(part.wander_angle) * dp.turbulence

            # semi-implicit Euler: update velocity first, then position from it.
            part.vel += accel * dt
            part.update(dt)

            # fade alpha out over the lifespan (clamped, applied after the tick).
            t = math.clamp(part._timer / part.lifespan, 0.0, 1.0)
            part.base_alpha = int(math.lerp(255, 0, t))

            # erratic Perlin glow: a smooth per-particle noise value scrolls over
            # time and modulates brightness + alpha, so motes wink in and out
            # organically instead of shining flatly. pnoise1's practical range is
            # ~[-0.5,0.5]; scale+clamp to [0,1], then map to [1-glow, 1].
            n = noise.pnoise1(part.glow_seed + part._timer * dp.glow_speed) * 2.0
            n = math.clamp(0.5 + 0.5 * n, 0.0, 1.0)
            flick = 1.0 - dp.glow * (1.0 - n)
            part.col.r = part.col.g = part.col.b = int(part.base_grey * flick)
            part.col.a = int(part.base_alpha * flick)

        


if __name__ == "__main__":
    # Standalone visual smoke test: `python -m Models.Particles`
    # A particle fountain follows the mouse. ESC / window-close to quit.
    p.init()
    W, H = 900, 600
    screen = p.display.set_mode((W, H))
    p.display.set_caption("Particles smoke test  --  move mouse, ESC to quit")
    clock = p.time.Clock()

    emitter = CPU_Particles_2D(
        pos=p.Vector2(W / 2, H / 2),
        min_vel=(-120, -260),
        max_vel=(120, -60),
        min_rad=3.0,
        max_rad=9.0,
        min_dur=0.8,
        max_dur=1.8,
        min_spawn_interval=0.01,
        max_spawn_interval=0.03,
        max_particles=400,
    )

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in p.event.get():
            if event.type == p.QUIT:
                running = False
            elif event.type == p.KEYDOWN and event.key == p.K_ESCAPE:
                running = False

        emitter.pos = p.Vector2(p.mouse.get_pos())
        emitter.update(dt)

        screen.fill((18, 18, 24))
        emitter.render(screen)
        screen.blit(
            p.font.SysFont("consolas", 18).render(
                f"particles: {len(emitter.particles)}   fps: {clock.get_fps():.0f}",
                True, (200, 200, 210)),
            (12, 10))
        p.display.flip()

    p.quit()