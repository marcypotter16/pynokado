from Game import Game
from States.CardShowcaseState import CardShowcaseState

g: Game = Game()
g.push_state(CardShowcaseState(g))
g.game_loop()