import os

import pygame as p
import time

from Generic.Stack import Stack
from Tween.Tween import TweenManager




class Game:
    def __init__(self, workdir: str = os.getcwd()):
        self.need_key_event_handling = True
        self.events = None
        self.fps: int = 60
        self.clock = p.time.Clock()
        self.base_dir = workdir
        self.font_dir = None
        self.assets_dir = ""
        self.font_medium = None  # This has to be set!
        self.title_screen = None
        p.init()
        p.mixer.init()
        # self.GAME_W, self.GAME_H = 640, 320
        # self.GAME_W, self.GAME_H = 1920, 1080
        # self.SCREEN_W, self.SCREEN_H = 1920, 1080
        self.GAME_W, self.GAME_H = 1280, 720
        self.SCREEN_W, self.SCREEN_H = 1280, 720
        self.SCREEN_CENTER = (self.GAME_W / 2, self.GAME_H / 2)
        self.game_canvas = p.Surface((self.GAME_W, self.GAME_H))
        self.screen = p.display.set_mode((self.SCREEN_W, self.SCREEN_H))
        self.running, self.playing = True, True
        self.actions: dict[str, int] = {'left': 0, 'right': 0, 'up': 0, 'jump': 0, 'down': 0, 'action1': 0,
                                        'glide': 0, 'start': 0, 'mouse_sx': 0, 'mouse_dx': 0}
        self.jump_action_changed: int = 0
        self.clicked_sx: int = 0
        self.clicked_dx: int = 0
        self.dt, self.prev_time = 0, 0
        self.state_stack = Stack()

        self.tweener = TweenManager()

        # self.event_system = EventSystem()

        # TODO: Make a render stack
        # Structure:
        #  key: layer
        #  value: list of render functions to call
        self.render_stack = {"background": [], "foreground": [], "above_all": []}

        self.mousepos = (0, 0)
        try:
            self.load_assets()
            self.load_map()
            self.load_states()
            self.load_sounds()
        except:
            pass

    def game_loop(self):
        while self.playing:
            self.get_dt()
            self.get_events()
            self.update()
            self.render()
            self.clock.tick(self.fps)

    def get_events(self):
        self.events = p.event.get()
        aux_prev_jump_action = self.actions['jump']
        aux_prev_mouse_sx = self.actions['mouse_sx']
        aux_prev_mouse_dx = self.actions['mouse_dx']
        for event in self.events:
            if event.type == p.QUIT:
                self.playing, self.running = False, False

            if event.type == p.MOUSEBUTTONDOWN:
                if event.button == 1:
                    self.actions['mouse_sx'] = 1
                if event.button == 3:
                    self.actions['mouse_dx'] = 1

            if event.type == p.MOUSEBUTTONUP:
                if event.button == 1:
                    self.actions['mouse_sx'] = 0
                if event.button == 3:
                    self.actions['mouse_dx'] = 0

            if self.need_key_event_handling:
                if event.type == p.KEYDOWN:
                    if event.key == p.K_ESCAPE:
                        self.playing, self.running = False, False
                    if event.key == p.K_a:
                        self.actions['left'] = 1
                    if event.key == p.K_d:
                        self.actions['right'] = 1
                    if event.key == p.K_s:
                        self.actions['down'] = 1
                    if event.key == p.K_w:
                        self.actions['up'] = 1
                        self.actions['jump'] = 1
                    if event.key == p.K_1:
                        self.actions['action1'] = 1
                    if event.key == p.K_SPACE:
                        self.actions['glide'] = 1
                    if event.key == p.K_3:
                        self.actions['start'] = 1
                if event.type == p.KEYUP:
                    if event.key == p.K_a:
                        self.actions['left'] = 0
                    if event.key == p.K_d:
                        self.actions['right'] = 0
                    if event.key == p.K_s:
                        self.actions['down'] = 0
                    if event.key == p.K_w:
                        self.actions['up'] = 0
                        self.actions['jump'] = 0
                        self.actions['down'] = 0
                    if event.key == p.K_1:
                        self.actions['action1'] = 0
                    if event.key == p.K_SPACE:
                        self.actions['glide'] = 0
                    if event.key == p.K_3:
                        self.actions['start'] = 0
            self.jump_action_changed = self.actions['jump'] - aux_prev_jump_action
        self.clicked_sx = self.actions['mouse_sx'] - aux_prev_mouse_sx
        self.clicked_dx = self.actions['mouse_dx'] - aux_prev_mouse_dx
        # print(self.jump_action_changed)

    def update(self):
        self.mousepos = (
            p.mouse.get_pos()[0] * self.GAME_W / self.SCREEN_W, p.mouse.get_pos()[1] * self.GAME_H / self.SCREEN_H)
        # self.state_stack.top().update(self.dt, self.actions)
        self.state_stack.top().update(self.dt)
        self.tweener.update()

    def render(self):
        self.state_stack.top().render(self.game_canvas)
        # for layer in self.render_stack.keys():
        #     for render_function in self.render_stack[layer]:
        #         render_function(self.game_canvas)
        self.screen.blit(p.transform.scale(self.game_canvas, (self.SCREEN_W, self.SCREEN_H)), (0, 0))
        p.display.flip()  # ??

    def get_dt(self):
        now = time.time()
        self.dt = now - self.prev_time
        self.prev_time = now

    def load_assets(self):
        # TODO
        # To be modified
        self.assets_dir = os.path.join(self.base_dir, "Assets")
        print(self.base_dir, self.assets_dir)
        # self.sprite_dir = os.path.join(self.assets_dir, "sprites")
        self.font_dir = os.path.join(self.assets_dir, "font")
        # self.font_medium = p.font_medium.Font(os.path.join(self.font_dir, "PressStart2P-vaV7.ttf"), 20)
        self.font_medium = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Regular.ttf"), 20)
        self.font_big = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Regular.ttf"), 40)
        self.font_small = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Regular.ttf"), 10)
        self.font_tiny = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Regular.ttf"), 5)
        # self.font_big_bold = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Bold.ttf"), 40)
        # self.font_medium_bold = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Bold.ttf"), 20)
        # self.font_small_bold = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Bold.ttf"), 10)
        # self.font_tiny_bold = p.font.Font(os.path.join(self.font_dir, "Comfortaa-Bold.ttf"), 5)

    def load_states(self):
        # TO BE DEFINED
        pass
        # self.title_screen = Title(self)
        # self.state_stack.push(self.title_screen)

    def load_state(self, state):
        self.state_stack.push(state)

    def load_map(self):
        pass
        # self.map_dir = os.path.join(self.assets_dir, "map")
        # self.terra = p.transform.scale2x(p.image.load(os.path.join(self.map_dir, 'terra.png')))
        # self.erba = p.transform.scale2x(p.image.load(os.path.join(self.map_dir, 'erbafunghi.png')))
        #
        # map_path = os.path.join(self.map_dir, 'map.txt')
        # map_grid = []
        # with open(map_path, 'r') as f:
        #     lines = f.readlines()
        #     for line in lines:
        #         line = line.strip().split(" ")
        #         map_grid.append(line)
        # self.map = map_grid

    def reset_keys(self):
        for action in self.actions:
            self.actions[action] = False

    def load_sounds(self):
        pass

    def push_state(self, state):
        self.state_stack.push(state)

    def pop_state(self, how_many: int = 1):
        for _ in range(how_many):
            self.state_stack.pop()



if __name__ == '__main__':
    g = Game()
    while g.running:
        g.game_loop()
