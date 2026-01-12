from dataclasses import dataclass, asdict
import json


@dataclass
class GameSettings:
    SCREEN_W: int = 1920
    SCREEN_H: int = 1080
    FPS: int = 120
    LETTERBOX_COLOR: tuple = (50, 50, 50)
    MOUSE_VISIBLE: bool = False

    @classmethod
    def from_json(cls, json_str: str):
        data = json.loads(json_str)
        return cls(**data)

    def set_resolution(self, new_width: int, new_height: int):
        self.SCREEN_W, self.SCREEN_H = new_width, new_height

    def set_fps(self, new_fps: int):
        if new_fps <= 0:
            raise ValueError("FPS value has to be a positive integer")
        self.FPS = new_fps

    def to_json(self) -> str:
        return json.dumps(asdict(self))


if __name__ == "__main__":
    import os

    gs = GameSettings()
    gs.set_resolution(1280, 720)
    with open(os.path.join(os.getcwd(), "settings.json"), "w") as file:
        file.write(gs.to_json())
    # file = open(os.path.join(os.getcwd(), "settings.json"), "r")
    # gs = GameSettings.from_json(file.read())
    print(asdict(gs))
