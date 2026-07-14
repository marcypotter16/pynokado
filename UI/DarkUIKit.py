"""
Named sprite rects for ``Assets/sprites/ui/dark_ui_kit.png`` (a 256x256 packed
atlas of dark-fantasy UI parts: panels, round buttons, arrow buttons, sliders
and gem health bars).

Rects were derived by alpha-flood-fill boundary detection of the atlas, so each
(x, y, w, h) is the tight bounding box of one sprite. Load them with
``Utils.Atlas.SpriteAtlas``:

    from Utils.Atlas import SpriteAtlas
    from UI.DarkUIKit import DARK_UI_KIT_PATH, DARK_UI_KIT_RECTS

    kit = SpriteAtlas(DARK_UI_KIT_PATH, DARK_UI_KIT_RECTS)
    panel = kit.get("panel_title")
    btn   = kit.get_scaled("button_arrow_right", (32, 32))

Naming: round buttons come in two bezel styles, "a" (top block) and "b"
(second block); trailing indices number them left-to-right, top-to-bottom.
"""

import os

DARK_UI_KIT_PATH = os.path.join(
    os.getcwd(), "Assets", "sprites", "ui", "dark_ui_kit.png"
)

DARK_UI_KIT_RECTS: dict[str, tuple[int, int, int, int]] = {
    # --- large panels ---
    "panel_title": (14, 14, 79, 59),      # panel with wooden title bar
    "panel_plain": (14, 82, 79, 57),      # plain stone panel, metal corners
    "panel_ornate": (14, 142, 79, 56),    # gold/wood ornate frame
    # --- tall (vertical) panels ---
    "panel_tall_wood": (97, 14, 24, 59),
    "panel_tall_stone": (98, 79, 23, 60),
    # --- small panels / plaques ---
    "panel_small": (202, 127, 37, 32),    # small rounded panel
    "plaque_wide": (184, 77, 58, 17),     # bordered horizontal plaque
    "plaque_wide_gold": (186, 163, 53, 20),
    # --- round buttons, style A (top block, regions 2-15) ---
    "button_round_a0": (125, 14, 17, 18),
    "button_round_a1": (144, 14, 18, 18),
    "button_round_a2": (164, 14, 18, 18),
    "button_round_a3": (183, 14, 18, 18),
    "button_round_a4": (203, 14, 17, 18),
    "button_round_a5": (222, 14, 18, 18),
    "button_round_a6": (125, 34, 17, 18),
    "button_round_a7": (144, 34, 18, 18),
    "button_round_a8": (164, 34, 18, 18),
    "button_round_a9": (183, 34, 18, 18),
    "button_round_a10": (203, 34, 17, 18),
    "button_round_a11": (222, 34, 18, 18),
    "button_round_a12": (163, 54, 17, 18),
    "button_round_a13": (183, 54, 17, 18),
    # --- round buttons, style B (second block, regions 18-20, 22-27) ---
    "button_round_b0": (125, 77, 17, 17),
    "button_round_b1": (144, 77, 18, 17),
    "button_round_b2": (164, 77, 17, 17),
    "button_round_b3": (125, 98, 16, 17),
    "button_round_b4": (144, 98, 17, 17),
    "button_round_b5": (164, 98, 17, 17),
    "button_round_b6": (183, 98, 17, 17),
    "button_round_b7": (202, 98, 17, 17),
    "button_round_b8": (222, 98, 16, 17),
    # --- small square buttons (regions 31, 35, 40) ---
    "button_square_dark": (101, 145, 16, 16),
    "button_square_stone": (101, 164, 16, 16),
    "button_square_wood": (101, 183, 16, 16),
    # --- arrow buttons (regions 32-34, 37-39) ---
    "button_arrow_up": (125, 146, 16, 17),
    "button_arrow_up_alt": (145, 146, 16, 17),
    "button_arrow_right": (165, 146, 16, 17),
    "button_arrow_left": (125, 166, 16, 17),
    "button_arrow_down": (145, 166, 16, 17),
    "button_arrow_right_alt": (165, 166, 16, 17),
    # --- sliders / long bars ---
    "slider_track": (125, 126, 72, 17),   # region 28, long track
    "bar_long_wood": (127, 187, 113, 14),
    "bar_long_dark": (127, 203, 113, 15),
    # --- gem health/resource bars (gem + fill), varying fill levels ---
    "gembar_full": (13, 204, 55, 14),
    "gembar_mid": (72, 204, 52, 14),
    "gembar_low": (13, 220, 55, 14),
    "gembar_empty": (72, 220, 52, 14),
    "gembar_long_full": (127, 220, 59, 15),
    "gembar_long_dark": (189, 220, 52, 15),
}
