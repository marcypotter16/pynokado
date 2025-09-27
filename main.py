from Game import Game
from States.BezierTestState import BezierTestState
from States.CardTestState import CardTestState

g: Game = Game()
g.load_state(CardTestState(g))
g.game_loop()