from Game import Game
from States.BoardTestState import BoardTestState

g: Game = Game()
g.push_state(BoardTestState(g))
g.game_loop()