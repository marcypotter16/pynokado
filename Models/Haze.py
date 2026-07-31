"""Noise haze: the tone that fills the paper between glyphs.

A field of glyphs is a scatter of separate stamps, and on bare parchment it
reads as exactly that -- a scatter. Laying a faint, uneven tone through the
gaps binds them into one landform without drawing anything new. That's all this
produces: a [0,1] coverage field, for a caller to ink through whatever mask it
likes (see Terrain.BIOME_HAZE).

Two things make it read as haze rather than as a dirty page:

- Coverage is a REMAP, not a threshold: `(f - coverage) / (1 - coverage)`
  clipped at zero. Cutting the noise off at a level gives hard-edged blobs;
  rescaling what survives keeps a soft falloff, so the haze thins out at its
  edges. Low `coverage` means present nearly everywhere, which is what haze is
  -- unlike a cloud, which is defined by the gaps between its parts.
- A second, much coarser field multiplied over the first. Without it the
  remap gives a haze of the same weight everywhere it exists, which is
  consistent and therefore flat. This makes it broadly heavier in some places.

Built SMALL and resampled up by the caller. Evaluating pnoise2 per pixel at
render size would be millions of Python-level calls; haze has no fine detail
worth resolving, so a couple of hundred cells and a bicubic resample gets the
same picture for a thousandth of the work. That's the same field-then-scale
discipline the rest of the terrain uses (see Terrain._resample).
"""

import noise
import numpy as np


def haze_field(shape: tuple[int, int], seed: int = 0,
               periods: tuple[float, float] = (4.0, 3.0), octaves: int = 4,
               coverage: float = 0.10, variation: float = 0.45) -> np.ndarray:
    """A (rows, cols) coverage field in [0,1].

    `shape` is the CELL grid, not pixels -- keep it small, the caller scales it.
    `periods` is (across, down): how many features fit over the grid, so a low
    number across a wide field gives few broad masses. `coverage` is the remap
    threshold, `variation` the strength of the coarse thick/thin modulation
    (0 disables it).
    """
    return _remap(_fbm(shape, periods, octaves, seed), coverage, variation, shape, seed)


def _fbm(shape: tuple[int, int], periods: tuple[float, float],
         octaves: int, seed: int) -> np.ndarray:
    rows, cols = shape
    px, py = periods
    out = np.empty(shape, dtype=np.float64)
    for j in range(rows):
        for i in range(cols):
            out[j, i] = noise.pnoise2(i / cols * px, j / rows * py,
                                      octaves=octaves, persistence=0.5,
                                      lacunarity=2.0, base=seed % 256)
    return _normalize(out)


def _normalize(field: np.ndarray) -> np.ndarray:
    lo, hi = float(field.min()), float(field.max())
    if hi - lo < 1e-9:
        return np.zeros_like(field)
    return (field - lo) / (hi - lo)


def _remap(field: np.ndarray, coverage: float, variation: float,
           shape: tuple[int, int], seed: int) -> np.ndarray:
    d = np.clip((field - coverage) / max(1e-3, 1.0 - coverage), 0.0, 1.0)
    if variation > 0.0:
        # Deliberately a different seed AND a much longer wavelength than the
        # field it modulates: at a similar scale the two would beat against
        # each other into blotches rather than broad heavy and light zones.
        m = _fbm(shape, (2.0, 1.0), 2, seed + 7)
        d *= (1.0 - variation) + 2.0 * variation * m
    return np.clip(d, 0.0, 1.0)
