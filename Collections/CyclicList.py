class CyclicList:
    def __init__(self):
        self.items = []
        self.current = None
        self.index = 0

    def add(self, item):
        """
        Adds an item, current is set
        """
        self.items.append(item)

    def set_current(self, index):
        self.current = self.items[index]
        self.index = index

    def get_current(self):
        return self.current

    def get_current_index(self):
        return self.index

    def remove(self, item):
        self.items.remove(item)

    def __iter__(self):
        return self.items.__iter__()

    def __len__(self):
        return len(self.items)

    def remove_at(self, index):
        self.items.pop(index)

    def next(self):
        self.index = (self.index + 1) % len(self.items)
        self.current = self.items[self.index]

