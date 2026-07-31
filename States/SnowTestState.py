"""Does falling snow work on a parchment map? A judgement rig, not a feature.

Puts the real mountain glyphs, at the real size and spacing, on real aged
parchment, arranged as a range with a snowcap, and snows on it out of a cloud
layer. Everything that matters is on a key so the whole space can be swept in
one sitting: cloud style, cloud cover, flake colour, density, size and wind.

The weather itself -- density-field clouds, fog, and the snow sources that hang
off the underside of a cloud -- lives in Models/Weather.py, so the real map can
use it too. This file is the JUDGEMENT RIG around it: a mountain to snow on, a
panel of controls, and the toggles for the two experiments that never left the
rig (gap fog, and the silhouette outline). Read Weather.py for how any of it
works; read this for how to look at it.

KEY BINDINGS
    Letters and digits only, deliberately. `-`/`=` and `[`/`]` were the obvious
    picks for the paired +/- controls and they are unreachable on a non-US
    layout: on the Italian layout this is developed on, `=` is Shift+0 (so
    pygame reports K_0 with a modifier, never K_EQUALS) and the brackets are
    AltGr combos. A binding that silently does nothing on your own keyboard is
    worse than an awkward one, so the pairs live on adjacent letters instead.

Run it with:  python -m States.SnowTestState
"""

import math
import os

import numpy as np
import pygame as p

from Game import Game
from Models.Particles import DustParams
from Models.Terrain import BIOME_GLYPHS, Biome, Terrain
from Models.Weather import CLOUD_HEIGHT, CLOUD_STYLES, CloudField, SnowEmitter
from States.State import State
from UI.Label import Label
from UI.Slider import Slider
from Utils.Image import age_parchment

# The mask the mountain glyphs are sampled on. Coarse on purpose: the real
# terrain samples glyph positions in DATA space and scales the result up (see
# Terrain._build_glyph_coords), and the blue-noise sampler walks every candidate
# cell in Python, so sampling at 1920x1080 directly would cost seconds for a
# layout no denser than this one.
MASK_SHAPE = (135, 240)          # rows, cols

# Flake tints, walking from "what snow actually is" to "what is legible on this
# paper". Dust2D forces every particle to greyscale (see _update_particles
# writing r == g == b), so these are greys by necessity, not by choice.
FLAKE_GREYS = [("white", 255), ("pale grey", 170), ("ink", 60)]

class SnowTestState(State):
    """See the module docstring. Controls are drawn on screen."""

    def __init__(self, game: Game, data=None, layer="foreground", bg_color=..., previous_state=None):
        super().__init__(game, data, layer, bg_color=(235, 232, 224), previous_state=None)

        self.grey_index = 0
        self.cloud_style = 0
        self.density = 60.0
        self.flake_scale = 1.0
        self.fall_distance = 26.0
        self.windy = True
        self.show_glyphs = True
        self.show_clouds = True
        self.show_fog = True
        self.show_silhouette = False
        self.paused = False
        self._font = game.fonts["ant"]["small"]

        paper_path = os.path.join(game.assets_dir, "sprites", "midjourney-session",
                                  "paper-texture.jpg")  # type: ignore
        self.paper = age_parchment(
            p.transform.smoothscale(
                p.image.load(paper_path).convert(), (game.GAME_W, game.GAME_H))
        )
        # Live overrides for BIOME_GLYPHS, so the sliders tune without writing
        # to Terrain's module-level config -- what's on the slider is exactly
        # the number to paste into BIOME_GLYPHS when it looks right.
        self.glyph_tuning: dict[Biome, dict[str, float]] = {
            biome: {"size": float(BIOME_GLYPHS[biome].size),
                    "spacing": float(BIOME_GLYPHS[biome].spacing)}
            for biome in (Biome.MOUNTAIN, Biome.SNOW)
        }
        self._build_mountains()
        self._build_silhouette()
        self._build_sliders()

        # One area of interest, two layers over it. The AOI is not binary:
        # snow counts 1.4 against rock's 1.0, so both layers gather on the cold
        # high ground -- and for the fog that's where it's most needed, since
        # the cap's pale glyphs have the least tone of their own binding them.
        out_size = (game.GAME_W, game.GAME_H)
        cloud_area = self.snow_mask.astype(np.float64)

        self.clouds = CloudField(cloud_area, out_size, cloud_height=CLOUD_HEIGHT,
                                 style=CLOUD_STYLES[self.cloud_style], periods=(2, 3))
        # Hand-tuned in the rig, and note the sign: the HUD reads out CLOUD
        # COVER, which is 1 - coverage, so "cover 0.60" on screen is this.
        # Cloud is defined by the sky between its parts, so the remap has to
        # leave gaps -- push this much below 0.3 and the noise fills the whole
        # AOI and buries what it's sitting on. `,`/`.` sweeps it.
        self.clouds.coverage = 0.40

        # Fog is the same field at ground level: no lift, no vertical taper (the
        # AOI bounds it, and a taper would fade it out across the middle of the
        # range), drifting slowly enough to read as still. Lower coverage and
        # higher opacity than the clouds, because fog should be present nearly
        # everywhere in the range and simply heavier in places, where a cloud is
        # defined by the sky BETWEEN its parts.
        fog_area = (self.mountain_mask | self.snow_mask).astype(np.float64)
        self.fog = CloudField(fog_area, out_size, cloud_height=0.0, seed=19,
                              work_cols=160, work_rows=110, style="fog",
                              periods=(4, 3), thickness_variation=0.45)
        self.fog.coverage = 0.08
        self.fog.opacity = 2.9
        self.fog.absorption = 1.4
        self.fog.speed = 4.0
        self.fog.taper = (0.0, 1.0)

        self._build_emitter()

    # -- tuning panel -----------------------------------------------------

    def _build_sliders(self):
        """Glyph size and spacing, live. Spacing is the one that decides whether
        a range reads as a range or as scattered stamps, and it can't be judged
        from a number -- so it's on a slider rather than in a constant."""
        self._sliders = []
        panel_x = self.game.GAME_W - 260
        for i, (biome, key, lo, hi) in enumerate([
            (Biome.MOUNTAIN, "spacing", 6.0, 60.0),
            (Biome.MOUNTAIN, "size", 12.0, 90.0),
            (Biome.SNOW, "spacing", 6.0, 60.0),
            (Biome.SNOW, "size", 12.0, 90.0),
        ]):
            y = 30 + i * 52
            Label(self.canvas, x=panel_x, y=y,
                  text=f"{biome.name.lower()} {key}", fg_color=(70, 60, 50))
            self._sliders.append((biome, key, Slider(
                self.canvas, x=panel_x, y=y + 22, width=200, height=14,
                bg_color=(206, 190, 160), fg_color=(70, 60, 50),
                start=lo, end=hi, default=self.glyph_tuning[biome][key], decimals=1)))

    def _apply_sliders(self):
        """Restamp when a slider has moved AND been let go.

        Restamping is a blue-noise resample plus a few hundred sprite blits --
        a good fraction of a second, so doing it per frame while dragging would
        make the slider unusable. Waiting for the release costs nothing in
        feel: the number updates live on the handle, the picture catches up."""
        if self.game.actions["mouse_sx"]:
            return
        changed = False
        for biome, key, slider in self._sliders:
            if abs(slider.value - self.glyph_tuning[biome][key]) > 0.05:
                self.glyph_tuning[biome][key] = slider.value
                changed = True
        if changed:
            self._build_mountains()
            self._build_silhouette()

    def _build_silhouette(self):
        """The 'connect the linework' experiment: one continuous outline around
        the whole range, derived from the glyphs that were already stamped.

        No new art and no change to how glyphs are placed. Take the alpha of
        the stamped layer, morphologically CLOSE it -- dilate then erode, which
        bridges gaps narrower than the structuring element while leaving the
        outer shape where it was -- and the scattered stamps become one blob.
        Contour that blob and you have a single ink line wrapping the massif,
        through the same Terrain.contour the coastline uses.

        Done at quarter resolution: closing is the expensive part, the result
        is a soft line anyway, and a 480x270 grid is plenty to place it."""
        from scipy.ndimage import binary_closing

        alpha = p.surfarray.array_alpha(self.mountains)      # (x, y)
        # Transposed to (rows, cols) -- surfarray is (x, y), every mask in
        # Terrain is (y, x), and contour is one of those.
        small = (alpha[::4, ::4] > 40).T
        rows, cols = small.shape
        # A disk, not the default cross: a cross closes vertical and horizontal
        # gaps faster than diagonal ones and leaves the outline visibly boxy.
        r = 5
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        disk = (yy ** 2 + xx ** 2) <= r * r
        blob = binary_closing(small, structure=disk)

        coverage = Terrain.contour(blob, thickness=1.4, align="outer", soft=True)
        layer = p.Surface((cols, rows), p.SRCALPHA)
        Terrain._blit_ink(layer, coverage, (60, 52, 44, 220))
        self.silhouette = p.transform.smoothscale(layer, (self.game.GAME_W, self.game.GAME_H))

    # -- the scene --------------------------------------------------------

    def _build_mountains(self):
        """A range with a cap in the middle: `_og` peaks on the flanks,
        `_knockout` peaks (white-bodied) on the cap -- the same split
        BIOME_GLYPHS now uses for MOUNTAIN and SNOW, so what's judged here is
        what the map will actually draw."""
        rows, cols = MASK_SHAPE
        cy, cx = rows * 0.5, cols * 0.5
        yy, xx = np.mgrid[0:rows, 0:cols]
        ang = np.arctan2(yy - cy, xx - cx)
        # A few harmonics on the angle: a perfect annulus reads as a machine
        # part, and this costs nothing next to running real noise.
        wobble = (1.0 + 0.18 * np.sin(3 * ang + 0.7)
                      + 0.10 * np.sin(5 * ang + 2.1)
                      + 0.06 * np.sin(8 * ang))
        radius = np.hypot((yy - cy) / (rows * 0.42), (xx - cx) / (cols * 0.26)) / wobble

        self.snow_mask = radius <= 0.55
        self.mountain_mask = (radius > 0.55) & (radius <= 1.0)
        snow_mask, mountain_mask = self.snow_mask, self.mountain_mask

        out_size = (self.game.GAME_W, self.game.GAME_H)
        self.mountains = p.Surface(out_size, p.SRCALPHA)
        # Caps first, flanks over them -- same paint order as BIOME_GLYPHS, so
        # the near dark ridges overlap the high snow behind them.
        for mask, biome, seed in ((snow_mask, Biome.SNOW, 77),
                                  (mountain_mask, Biome.MOUNTAIN, 1312)):
            style = BIOME_GLYPHS[biome]
            tuned = self.glyph_tuning[biome]
            spacing = Terrain.data_spacing_for(tuned["spacing"], MASK_SHAPE, out_size)
            coords = Terrain.compute_glyph_points_mat_unif(
                mask.astype(np.float64), spacing=spacing, how_many=None,
                return_coords=True, rng=np.random.default_rng(seed))
            coords = Terrain.to_render_coords(coords, MASK_SHAPE, out_size)
            Terrain._stamp_glyphs(self.mountains, sorted(coords, key=lambda c: c[0]),
                                  style.paths, glyph_size=round(tuned["size"]),
                                  knockout_glyphs=style.knockout,
                                  knockout_background_color=style.knockout_colour,
                                  knockout_fill=style.knockout_fill,
                                  knockout_variants=style.knockout_variants,
                                  knockout_spread=style.knockout_spread)

    def _build_emitter(self):
        """Rebuilt whenever a knob changes -- it's a test rig, and a fresh
        emitter is clearer than mutating six fields and hoping."""
        self.snow = SnowEmitter(
            source=self.clouds.spawn_point,
            rate=self.density,
            grey=FLAKE_GREYS[self.grey_index][1],
            cull_below=self.game.GAME_H + 20,
            fall_distance=self.fall_distance,
            # Slow drift, not a fall: terminal speed is gravity/drag, so 55/0.9
            # is about 60 px/s -- roughly a real flake, and slow enough that the
            # eye reads individual motes.
            min_speed=4.0, max_speed=16.0, direction=(0, 1), scatter=math.pi / 3,
            min_rad=1.6 * self.flake_scale, max_rad=3.4 * self.flake_scale,
            # Lifespan is now the backstop, not the limit -- fall_distance
            # retires a flake long before this in the normal case.
            min_dur=8.0, max_dur=20.0,
            max_particles=1600,
            dust_params=DustParams(
                gravity=55.0, drag=0.9,
                turbulence=18.0, turbulence_drift=90.0,
                wind=p.Vector2(14.0, 0.0) if self.windy else p.Vector2(0.0, 0.0),
                wind_gust=22.0 if self.windy else 0.0, wind_gust_period=5.0,
                # Snow doesn't twinkle. Dust does -- that's what glow is for,
                # and leaving it on is what would make this read as embers.
                glow=0.0,
            ),
        )

    # -- input ------------------------------------------------------------

    def update(self, delta_time):
        super().update(delta_time)
        rebuild = False

        for event in self.game.events:
            if event.type != p.KEYDOWN:
                continue
            if event.key in (p.K_1, p.K_2, p.K_3):
                self.grey_index = {p.K_1: 0, p.K_2: 1, p.K_3: 2}[event.key]
                rebuild = True
            elif event.key == p.K_q:
                self.cloud_style = (self.cloud_style + 1) % len(CLOUD_STYLES)
                self.clouds.style = CLOUD_STYLES[self.cloud_style]
            elif event.key == p.K_f:
                self.show_fog = not self.show_fog
            elif event.key == p.K_o:
                self.show_silhouette = not self.show_silhouette
            elif event.key == p.K_k:
                # Points vs stripes, the two shapes a squall can take.
                self.clouds.source_width = 0.0 if self.clouds.source_width else 110.0
                self.clouds._pick_sources()
            elif event.key == p.K_j:
                self.clouds.source_count = 1 + self.clouds.source_count % 8
                self.clouds._pick_sources()
            elif event.key in (p.K_z, p.K_x):
                step = 1.3 if event.key == p.K_x else 1 / 1.3
                self.fall_distance = max(4.0, min(900.0, self.fall_distance * step))
                self.snow.fall_distance = self.fall_distance
            elif event.key == p.K_w:
                self.windy = not self.windy
                rebuild = True
            elif event.key == p.K_g:
                self.show_glyphs = not self.show_glyphs
            elif event.key == p.K_h:
                self.show_clouds = not self.show_clouds
            elif event.key == p.K_SPACE:
                self.paused = not self.paused
            elif event.key in (p.K_UP, p.K_DOWN):
                step = 1.25 if event.key == p.K_UP else 1 / 1.25
                self.density = max(2.0, min(900.0, self.density * step))
                self.snow.rate = self.density
            elif event.key in (p.K_c, p.K_v):
                step = 1.2 if event.key == p.K_v else 1 / 1.2
                self.flake_scale = max(0.3, min(4.0, self.flake_scale * step))
                rebuild = True
            elif event.key in (p.K_COMMA, p.K_PERIOD):
                # Cloud cover. Lower coverage = more sky survives the remap.
                step = -0.04 if event.key == p.K_COMMA else 0.04
                self.clouds.coverage = max(0.05, min(0.85, self.clouds.coverage + step))

        if rebuild:
            self._build_emitter()
        self._apply_sliders()
        if not self.paused:
            self.clouds.update(delta_time)
            self._update_fog(delta_time)
            self.snow.update(delta_time)

    # Fog drifts at 4 px/s. Rebuilding it 60 times a second redraws a picture
    # that moved a sixteenth of a pixel, and it's the most expensive layer here
    # -- the smoothscale up to its band dominates. At 15 Hz the motion is
    # indistinguishable and it costs a quarter as much. The surface persists
    # between updates, so rendering is untouched.
    FOG_INTERVAL = 1.0 / 15.0

    def _update_fog(self, delta_time: float) -> None:
        if not self.show_fog:
            return
        self._fog_accum = getattr(self, "_fog_accum", 0.0) + delta_time
        if self._fog_accum >= self.FOG_INTERVAL:
            # Hand over the whole accumulated time, not one interval's worth,
            # or the fog would fall progressively behind the clock.
            self.fog.update(self._fog_accum)
            self._fog_accum = 0.0

    # -- rendering --------------------------------------------------------

    def render(self, surface: p.Surface):
        # Ground up: paper, the haze lying in it, the line binding the range
        # together, the peaks themselves, the snow falling on them, and the
        # cloud it's falling out of last of all.
        surface.blit(self.paper, (0, 0))
        if self.show_fog:
            self.fog.render(surface)
        if self.show_silhouette:
            surface.blit(self.silhouette, (0, 0))
        if self.show_glyphs:
            surface.blit(self.mountains, (0, 0))
        # Snow UNDER the clouds: flakes should emerge from beneath the thing
        # they're falling out of, not be painted on top of it.
        self.snow.render(surface)
        if self.show_clouds:
            self.clouds.render(surface)

        name, grey = FLAKE_GREYS[self.grey_index]
        lines = [
            "SNOW TEST  --  Q cloud style   , . cloud cover   1/2/3 flake colour   C/V flake size",
            f"UP/DOWN snowfall   Z/X fall distance   W wind [{'on' if self.windy else 'off'}]"
            f"   G glyphs [{'on' if self.show_glyphs else 'off'}]"
            f"   H clouds [{'on' if self.show_clouds else 'off'}]"
            f"   F fog [{'on' if self.show_fog else 'off'}]"
            f"   O outline [{'on' if self.show_silhouette else 'off'}]"
            f"   SPACE {'resume' if self.paused else 'pause'}   ESC quit",
            f"clouds: {CLOUD_STYLES[self.cloud_style]}   cover {1 - self.clouds.coverage:.2f}"
            f"   height {self.clouds.cloud_height:.0f} px"
            f"   J/K sources: {self.clouds.source_count}x"
            f"{'stripe' if self.clouds.source_width else 'point'}"
            f"   flakes: {name} (grey {grey}) x{self.flake_scale:.2f} fall {self.fall_distance:.0f} px",
            f"live particles {len(self.snow.particles):4d}"
            f"   spawning {self.density:.0f}/s   fps {self.game.clock.get_fps():.0f}",
        ]
        for i, line in enumerate(lines):
            surface.blit(self._font.render(line, True, (60, 52, 44)), (24, 24 + i * 22))
        self.canvas.render(surface)


if __name__ == "__main__":
    game = Game()
    game.push_state(SnowTestState(game))
    game.game_loop()
