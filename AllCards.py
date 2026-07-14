from Models.Card import CardModel
import os

card_sprite_dir = os.path.join(os.getcwd(), "Assets", "sprites", "cards")
mj_dir = os.path.join(os.getcwd(), "Assets", "sprites", "midjourney-session")

ALL_CARDS = {
    "dark_tech": CardModel(
        os.path.join(card_sprite_dir, "dark_tech.png"),
        strength=10,
        name="Dark Tech",
        faction="tech",
        icon_focus=(0.5, 0.62), icon_zoom=1.6,
    ),
    "Ylean": CardModel(
        os.path.join(mj_dir, "crimson_countess.png"),
        strength=7,
        name="Ylean",
        faction="monster",
        icon_focus=(0.5, 0.32), icon_zoom=1.9,
    ),
    "forest_marauders": CardModel(
        os.path.join(mj_dir, "forest_marauders.png"),
        strength=5,
        name="Orc bros",
        faction="monster",
        icon_focus=(0.5, 0.5), icon_zoom=1.2,
    ),
    "great_pyramids": CardModel(
        os.path.join(mj_dir, "great_pyramids.png"),
        strength=6,
        name="The Great Pyramids",
        faction="ancient",
        icon_focus=(0.42, 0.5), icon_zoom=1.5,
    ),
    "the_polymath": CardModel(
        os.path.join(mj_dir, "the_polymath.png"),
        strength=8,
        name="The Polymath",
        faction="ancient",
        icon_focus=(0.42, 0.32), icon_zoom=1.9,
    ),
    "the_gaunt_one": CardModel(
        os.path.join(mj_dir, "the_gaunt_one.png"),
        strength=9,
        name="The Gaunt One",
        faction="monster",
        icon_focus=(0.5, 0.3), icon_zoom=1.7,
    ),
    "siege_colossus": CardModel(
        os.path.join(mj_dir, "siege_colossus.png"),
        strength=10,
        name="Siege Colossus",
        faction="tech",
        icon_focus=(0.5, 0.42), icon_zoom=1.4,
    ),
    "the_threshold": CardModel(
        os.path.join(mj_dir, "the_threshold.png"),
        strength=4,
        name="The Threshold",
        faction="ancient",
        icon_focus=(0.5, 0.45), icon_zoom=1.3,
    ),
}
