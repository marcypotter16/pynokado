from abc import ABC

from pygame import Surface

from Collections.PrioQueue import PrioQueue


class GameObject(ABC):
    """Base for anything drawable.

    Draw order is owned by whoever the object subscribes to — normally the
    State. An object only needs its own render_queue if the order of ITS
    children is contested (changes at runtime, or is declared by objects that
    don't know about each other). Fixed internal order is better written
    straight into render(). Leaves never touch the queue at all.
    """

    def __init__(self):
        self.render_queue: PrioQueue = PrioQueue()

    def add_to_render_queue(self, obj: "GameObject", z_index: int = 0):
        self.render_queue.add_object(obj, z_index)

    def remove_from_render_queue(self, obj: "GameObject"):
        if not self.render_queue.remove_object(obj):
            print(f"Warning: object {obj} not found in render queue")

    def change_z_index(self, obj: "GameObject", new_z_index: int):
        if not self.render_queue.change_z(obj, new_z_index):
            print(f"Warning: object {obj} not found in render queue")

    def update(self, dt: float):
        pass

    def render(self, surf: Surface):
        """Default: draw subscribed children in z order (a no-op for leaves)."""
        for _, obj in self.render_queue:
            obj.render(surf)
