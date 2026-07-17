from abc import ABC

import pygame

from Game import Game
from Collections.PrioQueue import PrioQueue
from GameObject import GameObject
from UI.Abstract import UICanvas
from UI.Label import Label
from Utils.Colors import BLACK


class State(ABC):
    def __init__(
        self,
        game: Game,
        data: object | None = None,
        layer="foreground",
        bg_color=BLACK,
        previous_state=None,
    ):
        """@param data: gets passed by the parent State"""
        self.game = game
        self.canvas: UICanvas = UICanvas(game)
        self.debug_label = Label(
            self.canvas,
            self.game.GAME_W * 0.85,
            0,
            width=self.game.GAME_W * 0.15,
            height=self.game.GAME_H,
            fg_color=(255, 255, 255),
        )
        self.bg_color = bg_color
        # self.prev_state = None
        self.data = data
        self.layer = layer
        self.keep_previous_state_updating = previous_state is not None
        if previous_state is not None:
            self.prev_state = previous_state
        self.render_queue: PrioQueue = PrioQueue()

    def add_to_render_queue(self, obj: GameObject, z_index: int = 0):
        self.render_queue.add_object(obj, z_index)

    def remove_from_render_queue(self, obj: GameObject):
        if not self.render_queue.remove_object(obj):
            print(f"Warning: object {obj} not found in render queue")

    def change_z_index(self, obj: GameObject, new_z_index: int):
        if not self.render_queue.change_z(obj, new_z_index):
            print(f"Warning: object {obj} not found in render queue")

    def render(self, surface: pygame.Surface):
        surface.fill(self.bg_color)
        for _, obj in self.render_queue:
            obj.render(surface)
        self.canvas.render(surface)

    def update(self, delta_time):
        self.canvas.update(delta_time)
        if self.keep_previous_state_updating:
            self.prev_state.update(delta_time)
        # if not self.game.settings.MOUSE_VISIBLE:
        #     self.cursor_go.move(self.game.cursorpos)

    def enter_state(self):
        """Aggiunge lo stato allo stack di stati del gioco"""
        if self.game.state_stack.size() > 1:
            self.prev_state = (
                self.game.state_stack.top()
            )  # ossia l'ultimo elemento dello stack di stati
        self.game.state_stack.push(self)
        self.game.render_stack[self.layer].append(self.render)

    def exit_state(self):
        """Rimuove lo stato dallo stack di stati del gioco"""
        self.game.state_stack.pop()

    def change_layer(self, layer):
        self.game.render_stack[self.layer].remove(self.render)
        self.layer = layer
        self.game.render_stack[self.layer].append(self.render)

    def change_render_index_in_layer(self, index):
        self.game.render_stack[self.layer].remove(self.render)
        self.game.render_stack[self.layer].insert(index, self.render)

    def set_above_all(self):
        self.game.render_stack[self.layer].remove(self.render)
        self.layer = "above_all"
        self.game.render_stack["above_all"].append(self.render)

    def debug_print(self, msg: str):
        self.debug_label.set_text(msg)
