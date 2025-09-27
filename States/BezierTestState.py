from Game import Game
from States.State import State
from UI.Bezier import GIZMO_SIZE, CubicBezier, QuadraticBezier
import pygame as p

class BezierTestState(State):
    def __init__(self, game: Game, msg=None, layer="foreground"):
        super().__init__(game, msg, layer)

        self.bezier_curve = QuadraticBezier(p.Vector2(100, 100), p.Vector2(200, 200), p.Vector2(300, 100))
        self.bezier_curve_cubic = CubicBezier(p.Vector2(100, 300), p.Vector2(200, 300), p.Vector2(200, 500), p.Vector2(300, 500))

        self.selected_handle = False

    def render(self, surface):
        super().render(surface)
        self.bezier_curve.render(surface)
        self.bezier_curve_cubic.render(surface)
        
    
    def update(self, delta_time):
        if self.game.actions["mouse_sx"] == 0:
            self.selected_handle = False
        if self.game.actions["mouse_sx"] == 1 and self.bezier_curve.p1.distance_squared_to(self.game.mousepos) <= GIZMO_SIZE**2:
            self.selected_handle = True
        if self.selected_handle:
            self.bezier_curve.p1 = p.Vector2(self.game.mousepos)
            self.bezier_curve._create_points()
        super().update(delta_time)