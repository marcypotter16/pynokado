# from Game import Game
from pygame import Surface, Vector2
from Game import Game
from GraphicClasses import GraphicCard
from States.State import State


class TestCard(GraphicCard):
    def __init__(
        self,
        game: Game,
        valore: int,
        seme: str,
        position: tuple[int, int] = ...,
        dimensions: tuple[int, int] = ...,
    ):
        super().__init__(game, valore, seme, position, dimensions)

    def snap_back(self):
        self.game.tweener.add_tween(
            self,
            "position",
            Vector2(self.position),
            Vector2(self.position_before_drag),
            0.2,
            on_finish=self.on_snap_back_finish,
            motion="ease_in_out_cubic",
        )

    def on_snap_back_finish(self):
        self.move(*self.position)


class TweenTestState(State):
    def __init__(self, game, data: object | None = None, layer="foreground"):
        super().__init__(game, msg, layer)
        self.card = TestCard(game, 1, "P", position=(400, 500), dimensions=(100, 150))
        self.game = game

    def update(self, delta_time):
        super().update(delta_time)
        self.card.update()
        if self.card.dropped:
            self.card.snap_back()

    def render(self, surface):
        super().render(surface)
        self.card.render(surface)
