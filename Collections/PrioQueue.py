import itertools
from bisect import insort


class PrioQueue:
    """Draw-order queue. Higher z_index is drawn last (on top).

    Objects with equal z_index keep insertion order. The queue is kept sorted
    on every mutation, so iteration is always in draw order.
    """

    def __init__(self):
        # (z_index, seq, obj) — seq breaks z ties by insertion order and keeps
        # comparisons from ever reaching obj, which need not be orderable.
        self.items: list[tuple[int, int, object]] = []
        self._seq = itertools.count()

    def add_object(self, obj: object, z_index: int = 0):
        insort(self.items, (z_index, next(self._seq), obj), key=lambda e: e[:2])

    def remove_object(self, obj: object) -> bool:
        for i, (_, _, existing) in enumerate(self.items):
            if existing is obj:
                del self.items[i]
                return True
        return False

    def change_z(self, obj: object, new_z_index: int) -> bool:
        if not self.remove_object(obj):
            return False
        self.add_object(obj, new_z_index)
        return True

    def __iter__(self):
        return ((z, obj) for z, _, obj in self.items)

    def __len__(self):
        return len(self.items)
