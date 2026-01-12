import pygame as p
from numpy import linspace

from Utils.Colors import RED, WHITE

GIZMO_SIZE = 5

class QuadraticBezier:
    def __init__(self, p0: p.Vector2, p1: p.Vector2, p2: p.Vector2, resolution=100, show_handle_points=True):
        self.points = []
        self.p0, self.p1, self.p2 = p0, p1, p2
        self.resolution = resolution
        self._create_points()
        self.show_handle_points = show_handle_points

    def _bezier_curve(self, t: float):
        """
        Construct a point for a bezier curve
        @param: t must be between 0 and 1
        @return: the point corresponding to Bezier(t)
        """
        return (1-t) * ((1-t) * self.p0 + t * self.p1) + \
            t * ((1-t) * self.p1 + t * self.p2)
    
    def _create_points(self):
        self.points.clear()
        t = linspace(0, 1, self.resolution)
        for num in t:
            self.points.append(self._bezier_curve(num))
    
    def render(self, surf: p.Surface):
        p.draw.aalines(surf, WHITE, False, self.points)
        if self.show_handle_points:
            p.draw.circle(surf, RED, self.p0, GIZMO_SIZE)
            p.draw.circle(surf, RED, self.p1, GIZMO_SIZE)
            p.draw.circle(surf, RED, self.p2, GIZMO_SIZE)


class CubicBezier(QuadraticBezier):
    def __init__(self, p0, p1, p2, p3, resolution=100, show_handle_points=True):
        self.p3 = p3
        super().__init__(p0, p1, p2, resolution, show_handle_points)


    def _bezier_curve(self, t):
        return  (1-t)**3 * self.p0 + \
                3 * (1-t)**2 * t * self.p1 + \
                3 * (1-t) * t**2 * self.p2 + \
                t**3 * self.p3
    
    def render(self, surf):
        super().render(surf)
        if self.show_handle_points:
            p.draw.circle(surf, RED, self.p3, GIZMO_SIZE)
    
