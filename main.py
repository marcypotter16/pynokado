from Game import Game
from States.BoardTestState import BoardTestState
from States.CardShowcaseState import CardShowcaseState
from States.TestParticleState import TestParticleState

g: Game = Game()
g.push_state(BoardTestState(g))
g.game_loop()