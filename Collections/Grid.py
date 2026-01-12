import numpy as np
from typing import Generic, TypeVar


T = TypeVar("T")


# TODO: Just reimplement it without numpy, it really is unnecessary
class Grid(Generic[T]):
    def __init__(self, n_rows: int, n_cols: int):
        self.n_rows, self.n_cols = n_rows, n_cols
        self.elements = np.zeros((n_rows, n_cols), dtype=object)
        # self.elements: list[list] = []

    #     self._init_grid()
    #     # np.ndarray((n_rows, n_cols))

    # def _init_grid(self):
    #     for row in range(self.n_rows):
    #         self.elements.append([])
    #         for col in range(self.n_cols):
    #             self.elements[row].append(0)

    def insert(self, item: T, row: int, col: int) -> None:
        if 0 <= row < self.n_rows and 0 <= col < self.n_cols:
            self.elements[row, col] = item
        else:
            raise IndexError(
                f"Trying inserting at ({row},{col}) but grid is {self.n_rows}x{self.n_cols}"
            )

    def get(self, row: int, col: int) -> T:
        if 0 <= row < self.n_rows and 0 <= col < self.n_cols:
            return self.elements[row, col]
        else:
            raise IndexError(
                f"Trying reading at ({row},{col}) but grid is {self.n_rows}x{self.n_cols}"
            )

    def get_row(self, row: int) -> list[T]:
        if not 0 <= row < self.n_rows:
            raise IndexError("Row index out of bounds")
        return self.elements[row:]

    def get_col(self, col: int) -> list[T]:
        if not 0 <= col < self.n_cols:
            raise IndexError("Col index out of bounds")
        return self.elements[:col]

    def flatten(self) -> list[T]:
        return self.elements.flatten()

    def __repr__(self):
        s = ""
        for col in range(self.n_cols):
            for row in range(self.n_rows):
                s += str(self.get(row, col)) + "\t"
            s += "\n"
        return s


if __name__ == "__main__":

    g3 = Grid[int](3, 4)
    g3.insert("Hellau", 2, 3)
    print(g3.elements[:])
    print(g3, g3.get_row(2))

    for col in range(g3.n_cols):
        for row in range(g3.n_rows):
            g3.insert(col + row, row, col)

    print(g3.flatten())
