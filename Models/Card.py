import pygame as p
import os

from Game import Game
from Tween.Tween import Tween

class CardModel:
    def __init__(self, art_path: str, strength: int):
        self.art_path = art_path
        self.strength = strength

class CardModelNotFoundError(SyntaxError):
    def __init_subclass__(cls):
        return super().__init_subclass__()

class Card:
    def __init__(self,
                 game: Game, 
                 card_model: CardModel = None,
                 topleft: p.Vector2 = p.Vector2(0, 0),
                 ) -> None:
        self.game = game
        self.topleft = p.Vector2(topleft)
        self.base = p.image.load(os.path.join(game.assets_dir, "sprites", "cards", "base.png"))
        self.base = p.transform.smoothscale(self.base, (200, 300))
        if card_model is None:
            raise CardModelNotFoundError
        self.card_model = card_model
        self.art = p.image.load(card_model.art_path)
        self.art = p.transform.smoothscale(self.art, (180, 280))
        self.rect = self.base.get_rect()
        self.rect.topleft = topleft
        self.art_rect = self.art.get_rect()
        self.art_rect.topleft = topleft + p.Vector2(10, 10)
        self.center = self.rect.center


    def update(self, dt: float):
        if self.game.actions["mouse_sx"]:
            if self.rect.collidepoint(self.game.mousepos):
                self.game.tweener.add_tween(self, 'center', p.Vector2(self.center), self.game.mousepos, 0.1)
        self.rect.center = self.center
        self.art_rect.center = self.center

    def render(self, surf: p.Surface):
        surf.blit(self.base, self.rect)
        surf.blit(self.art, self.art_rect)