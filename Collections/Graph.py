from dataclasses import dataclass


@dataclass
class GraphNode:
    node_id: int
    connected: list["GraphNode"]
    is_leaf: bool = True

class Graph:
    def __init__(self) -> None:
        self.__node_id_counter = 0
        self.nodes: list[GraphNode] = []
        self.edges: list[tuple[int, int]] # list of tuples of node_id