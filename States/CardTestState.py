from AllCards import ALL_CARDS
from Models.Card import Card
from States.State import State
import pygame as p


class CardTestState(State):
    def __init__(self, game, msg=None, layer="foreground"):
        super().__init__(game, msg, layer)
        self.cardTest = Card(game, topleft=p.Vector2(0, 0), card_model=ALL_CARDS['dark_tech'])

    def update(self, delta_time):
        super().update(delta_time)
        self.cardTest.update(delta_time)
    
    def render(self, surface):
        super().render(surface)
        self.cardTest.render(surface)