from os import getcwd
from os.path import join

import pygame
from numpy import clip, float32, ndarray, roll, uint8


def images_from_spritesheet(
    path: str, tilesize: tuple[int, int]
) -> list[pygame.Surface]:
    """
    Very useful function that returns a list of images based on a tiled spritesheet.
    You can use for example Aseprite to create an animation, then export the animation as a spritesheet,
    and finally use this function to get all the frames at once, without needing to crop or export single frames.
    :param path: path of the spritesheet
    :param tilesize: a tuple of 2 ints, representing the width and height of each frame in the animation
    :return: a list of the images (pygame images) of the animation.
    """
    x = y = 0
    full_img = pygame.image.load(path).convert_alpha()
    max_x, max_y = full_img.get_rect().size
    images: list[pygame.Surface] = []
    while y < max_y:
        while x < max_x:
            subsurface_rect = pygame.rect.Rect((x, y), tilesize)
            image = full_img.subsurface(subsurface_rect)
            images.append(image)
            x += tilesize[0]
        x = 0
        y += tilesize[1]
    return images


def change_tint(surf: pygame.Surface, color: pygame.Color) -> pygame.Surface:
    img = surf.convert_alpha()
    # Create a mask from the alpha channel
    alpha = pygame.surfarray.array_alpha(img).copy()

    # Fill with the new color (this replaces all pixels)
    img.fill(color)

    # Restore the original alpha channel
    pygame.surfarray.pixels_alpha(img)[:] = alpha
    return img

def age_parchment(paper: pygame.Surface) -> pygame.Surface:
    """Warm a clean paper texture into a worn sepia parchment: a sepia tint plus
    a gentle worn vignette at the edges. Ink blotches belong on the board layer,
    not here. Costly enough to want baking once, not per frame.

    Note: BLEND_MULT ignores the alpha channel, so the darkening layers are
    built as *fully opaque* gradients (transparent-black would multiply the
    paper to black). Softness comes from the gradient values, not alpha."""
    w, h = paper.get_size()
    out = paper.copy()

    # Warm sepia tint (multiply toward a soft tan; kept light).
    tint = pygame.Surface((w, h))
    tint.fill((226, 208, 176))
    out.blit(tint, (0, 0), special_flags=pygame.BLEND_MULT)

    # Gentle worn vignette. Opaque radial gradient, brightest centre
    # (255 = no change) fading to a mild edge darkening.
    vig = pygame.Surface((w, h))
    vig.fill((205, 195, 178))   # edge darkness
    cx, cy = w // 2, h // 2
    maxr = int((w ** 2 + h ** 2) ** 0.5 / 2)
    for i in range(80):
        t = i / 79
        r = int(maxr * (1 - t))
        v = int(205 + (255 - 205) * (t ** 1.5))          # 205(edge)->255(centre)
        pygame.draw.circle(vig, (v, v, v), (cx, cy), r)
    out.blit(vig, (0, 0), special_flags=pygame.BLEND_MULT)
    return out


def smoothstep(x: float, lo, hi):
    """Smooth 0->1 ramp: 0 below lo, 1 above hi, Hermite S-curve between.
    x, lo, hi are in the same units (here: alpha 0..255)."""
    t = clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)

def blur_alpha(a: ndarray, passes=1) -> ndarray:
    a = a.astype(float32)
    for _ in range(passes):
        # average each pixel with its two neighbours along axis 0, then axis 1,
        # le classic blur.
        a = (a + roll(a, 1, axis=0) + roll(a, -1, axis=0)) / 3.0
        a = (a + roll(a, 1, axis=1) + roll(a, -1, axis=1)) / 3.0
    return a

def soften_alpha(surf: pygame.Surface, lo: int = 30, hi: int = 210, blur_passes: int = 1) -> pygame.Surface:
    # lo and hi are the smoothstep parameters.
    # the function smooths out the edge of a surface returning another surf.
    img = surf.convert_alpha()
    alpha = pygame.surfarray.array_alpha(img)
    softened = blur_alpha(alpha, passes=blur_passes)
    softened = smoothstep(softened, lo, hi) * 255.0
    softened = clip(softened, 0, 255).astype(uint8)
    pygame.surfarray.pixels_alpha(img)[:] = softened
    return img

if __name__ == "__main__":
    import os

    # convert_alpha() needs a video mode set.
    pygame.init()
    pygame.display.set_mode((1, 1))

    path = join(getcwd(), "..", "Assets", "sprites", "midjourney-session", "frame_flourish.png")
    original = pygame.image.load(path).convert_alpha()
    softened = soften_alpha(original)

    out_dir = join(getcwd(), "..", "scratch")
    os.makedirs(out_dir, exist_ok=True)

    pygame.image.save(original, join(out_dir, "soften_original.png"))
    pygame.image.save(softened, join(out_dir, "soften_softened.png"))

    # To actually SEE the edge softening we must zoom into a small patch of a
    # stroke edge, not shrink the whole frame. Grab a patch from the top-left
    # corner (where the frame stroke is), scale it up hard with NEAREST so each
    # alpha pixel is a visible block, and lay original vs softened side by side
    # on a mid-grey backdrop.
    PATCH = 60          # source patch size in px
    ZOOM = 12           # nearest-neighbour magnification
    px, py = 105, 235   # top-left of the patch: straddles the left vertical stroke edge

    def zoom_patch(surf):
        patch = pygame.Surface((PATCH, PATCH), pygame.SRCALPHA)
        patch.blit(surf, (0, 0), pygame.Rect(px, py, PATCH, PATCH))
        return pygame.transform.scale(patch, (PATCH * ZOOM, PATCH * ZOOM))

    z_orig = zoom_patch(original)
    z_soft = zoom_patch(softened)
    gap = 30
    zw, zh = z_orig.get_size()
    comp = pygame.Surface((zw * 2 + gap * 3, zh + gap * 2))
    comp.fill((110, 110, 110))
    comp.blit(z_orig, (gap, gap))
    comp.blit(z_soft, (gap * 2 + zw, gap))
    pygame.image.save(comp, join(out_dir, "soften_compare.png"))

    print("wrote:", os.path.abspath(out_dir))
    print("  soften_compare.png  (left = original, right = softened; NEAREST zoom)")
    pygame.quit()
