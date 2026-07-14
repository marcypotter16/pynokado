import os

import pygame


class SpriteAtlas:
    """
    Loads a packed spritesheet (an atlas) whose sprites are *not* laid out on a
    uniform grid, and exposes each sprite by name.

    Unlike ``images_from_spritesheet`` (which slices a regular NxM grid), an
    atlas is defined by an explicit mapping of ``name -> (x, y, w, h)`` rects,
    because the sprites have irregular sizes and positions (e.g. the dark UI
    kit: panels, round buttons, sliders and health bars all packed together).

    Sub-surfaces share pixels with the parent surface, so lookups are cheap and
    do not copy image data.
    """

    def __init__(self, path: str, rects: dict[str, tuple[int, int, int, int]]):
        """
        :param path: path of the atlas image (a single PNG).
        :param rects: mapping of sprite name to an (x, y, width, height) rect,
            in atlas pixel coordinates.
        """
        self.path = path
        self.sheet = pygame.image.load(path).convert_alpha()
        self.rects = rects
        self._cache: dict[str, pygame.Surface] = {}

    def get(self, name: str) -> pygame.Surface:
        """Return the (unscaled) sub-surface for ``name``."""
        if name not in self._cache:
            if name not in self.rects:
                raise KeyError(
                    f"'{name}' is not a sprite in this atlas. "
                    f"Available: {', '.join(sorted(self.rects))}"
                )
            self._cache[name] = self.sheet.subsurface(pygame.Rect(self.rects[name]))
        return self._cache[name]

    def get_scaled(self, name: str, size: tuple[int, int]) -> pygame.Surface:
        """Return the sprite for ``name`` scaled to ``size`` (nearest-neighbour, to keep pixel edges crisp)."""
        return pygame.transform.scale(self.get(name), size)

    def names(self) -> list[str]:
        return list(self.rects)

    def export_slices(self, out_dir: str) -> list[str]:
        """
        Write each named sprite to ``out_dir/<name>.png`` and return the list of
        written paths. Handy for eyeballing the slicing outside the game.
        """
        os.makedirs(out_dir, exist_ok=True)
        written = []
        for name in self.rects:
            surf = self.get(name)
            dest = os.path.join(out_dir, f"{name}.png")
            pygame.image.save(surf, dest)
            written.append(dest)
        return written


if __name__ == "__main__":
    # Slice the dark UI kit to individual PNGs so the atlas can be inspected.
    #   uv run python -m Utils.Atlas
    from UI.DarkUIKit import DARK_UI_KIT_PATH, DARK_UI_KIT_RECTS

    pygame.init()
    pygame.display.set_mode((1, 1))
    atlas = SpriteAtlas(DARK_UI_KIT_PATH, DARK_UI_KIT_RECTS)
    out = os.path.join(os.path.dirname(DARK_UI_KIT_PATH), "dark_ui_kit_slices")
    paths = atlas.export_slices(out)
    print(f"Wrote {len(paths)} slices to {out}")
