WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)
ORANGE = (255, 165, 0)
PURPLE = (128, 0, 128)
PINK = (255, 192, 203)
GRAY = (128, 128, 128)
DARK_GRAY = (64, 64, 64)
LIGHT_GRAY = (192, 192, 192)
BROWN = (165, 42, 42)
DARK_GREEN = (0, 100, 0)
DARK_BLUE = (0, 0, 139)
DARK_RED = (139, 0, 0)
DARK_YELLOW = (139, 139, 0)
DARK_CYAN = (0, 139, 139)
DARK_MAGENTA = (139, 0, 139)
DARK_ORANGE = (255, 140, 0)
DARK_PURPLE = (75, 0, 130)
DARK_PINK = (255, 105, 180)
DARK_BROWN = (139, 69, 19)
DARK_GRAY = (64, 64, 64)
LIGHT_GRAY = (192, 192, 192)
LIGHT_GREEN = (144, 238, 144)
LIGHT_BLUE = (173, 216, 230)
LIGHT_RED = (255, 99, 71)
LIGHT_YELLOW = (255, 255, 224)
LIGHT_CYAN = (224, 255, 255)
LIGHT_MAGENTA = (255, 224, 255)

# Shades of gray
GRAY_0 = (18, 18, 18)
GRAY_10 = (38, 50, 56)
GRAY_20 = (51, 51, 51)
GRAY_30 = (77, 77, 77)
GRAY_40 = (102, 102, 102)
GRAY_50 = (128, 128, 128)
GRAY_60 = (153, 153, 153)
GRAY_70 = (179, 179, 179)
GRAY_80 = (204, 204, 204)
GRAY_90 = (230, 230, 230)

# Palette
BACKGROUND = BLACK
DARK = (11, 25, 44)
DARK_10 = (13, 13, 13)
DARK_20 = (23, 23, 23)
LIGHT = (30, 62, 98)
ACCENT = (255, 101, 0)
TEXT = (255, 255, 255)


def hex2rgb(hex: str) -> tuple[int, int, int]:
    return tuple(int(hex.lower()[i : i + 2], 16) for i in (0, 2, 4))


# def hex_no_0x2rgb(hex_no_0x: str) -> tuple[int, int, int]:
#     return hex2rgb("0x" + hex_no_0x)


TROPICAL_TEAL = hex2rgb("51A3A3")
MAUVE_SHADOW = hex2rgb("75485E")
GOLDEN_APRICOT = hex2rgb("CB904D")
