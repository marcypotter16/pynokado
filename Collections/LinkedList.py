class LL_Node:
    def __init__(self, content = None, next = None):
        self.content = content
        self.next = next

    def link(self, next):
        self.next = next

class MB_LL:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.size: int = 0
        self.first = LL_Node()

    def push_front(self, element):
        # if self.size >= self.capacity: return
        node = LL_Node(element, self.first)
        self.first = node
        aux = self.first
        counter = 0
        while aux is not None and aux.next is not None:
            if counter >= self.capacity:
                aux.next = None
            counter += 1
            aux = aux.next

    def to_list(self) -> list:
        l = []
        aux = self.first
        while aux.next is not None:
            l.append(aux.content)
            aux = aux.next
        return l

if __name__ == "__main__":
    l = MB_LL(3)
    l.push_front(1)
    l.push_front(2)
    l.push_front(3)
    l.push_front(4)
    print(l.to_list())
