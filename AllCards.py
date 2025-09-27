from Models.Card import CardModel
import os

card_sprite_dir = os.path.join(os.getcwd(), "Assets", "sprites", "cards")
ALL_CARDS = {
    "dark_tech": CardModel(os.path.join(card_sprite_dir, "dark_tech.png"), 10)
}