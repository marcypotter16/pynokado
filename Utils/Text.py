import pygame.font
from pygame import draw


def draw_text(
    font: pygame.font.Font,
    surface: pygame.Surface,
    text: str,
    color: tuple = (255, 255, 255),
    x: int = 0,
    y: int = 0,
):
    """
    Draws text using pygame.font.Font
    :param font: The font used (pygame.font.Font).
    :param surface: The surface to write on (pygame surface)
    :param text: The text.
    :param color: The color
    :param x: X of the topleft corner of the text
    :param y: Y of the topleft corner of the text
    :return:
    """
    # Use standard pygame font rendering
    text_surface = font.render(str(text), True, color)
    text_rect = text_surface.get_rect()
    text_rect.topleft = (x, y)
    surface.blit(text_surface, text_rect)


def draw_centered_text(
    font: pygame.font.Font,
    surface: pygame.Surface,
    text: str,
    color: tuple,
    rect: pygame.Rect,
):
    """
    Draws text centered in a rect using pygame.font.Font
    :param font: The font used (pygame.font.Font).
    :param surface: The surface to write on (pygame surface)
    :param text: The text.
    :param color: The color
    :param rect: The rect to center text in
    :return:
    """
    if not text:  # Don't render empty strings
        return

    # Use standard pygame font rendering with antialiasing
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect()
    text_rect.center = rect.center
    surface.blit(text_surface, text_rect)


def draw_text_hq(
    font_path: str,
    size: int,
    surface: pygame.Surface,
    text: str,
    color: tuple,
    x: int,
    y: int,
    centered: bool = False,
):
    """
    Draws text using pygame.font.Font with antialiasing.
    :param font_path: Path to the font file
    :param size: Font size
    :param surface: The surface to write on
    :param text: The text to render
    :param color: The color
    :param x: X position
    :param y: Y position
    :param centered: Whether to center the text at (x, y)
    :return:
    """
    font = pygame.font.Font(font_path, size)
    text_surf = font.render(text, True, color)
    text_rect = text_surf.get_rect()
    if centered:
        text_rect.center = (x, y)
    else:
        text_rect.topleft = (x, y)
    surface.blit(text_surf, text_rect)


def draw_number_with_circle_background(
    font: pygame.font.Font,
    surface: pygame.Surface,
    number: str,
    bg_color: tuple,
    fg_color: tuple,
    x: int,
    y: int,
):
    """
    Draws a number with a circle background.
    :param font: The font used.
    :param surface: The surface to write on (pygame surface)
    :param number: The number.
    :param bg_color: The color of the background
    :param fg_color: The color of the number
    :param x: X of the center of the rectangle containing the text
    :param y: Y of the center of the rectangle containing the text
    :return:
    """
    draw.circle(
        surface,
        bg_color,
        (x + font.size(number)[0] * 0.5, y + font.size(number)[1] * 0.5),
        10,
    )
    draw_text(font, surface, str(number), fg_color, x, y)
