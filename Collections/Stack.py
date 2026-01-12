from typing import Generic, TypeVar


T = TypeVar("T")


class EmptyStackError(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class NegativeCapacityError(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class Stack(Generic[T]):
    def __init__(self, capacity=0):
        """Creates a Stack of elements of type T. If capacity is unset it stores an indefinite amount of elements, else if an element is added after the capacity is reached, the element is added and the last element of the stack is erased"""
        if capacity < 0:
            raise NegativeCapacityError
        self.elements: list[T] = []
        self.capacity = capacity
        self.__size = 0

    def top(self) -> T:
        """
        Returns the top element of the stack
        :return:
        """
        if self.__size == 0:
            raise EmptyStackError
        return self.elements[0]

    def pop(self) -> T:
        """
        Removes the top element of the stack and returns it
        :return:
        """
        if self.__size == 0:
            raise EmptyStackError
        self.__size -= 1
        return self.elements.pop(0)

    def push(self, obj: T) -> None:
        """
        Adds an element to the top of the stack
        :param obj:
        :return:
        """
        if self.capacity == 0 or self.__size < self.capacity:
            self.elements.insert(0, obj)
            self.__size += 1
        else:
            self.elements.pop(-1)
            self.elements.insert(0, obj)

    def remove(self, obj: T) -> None:
        if obj in self.elements:
            self.elements.remove(obj)
            self.__size -= 1

    def is_empty(self) -> bool:
        """
        Returns true if the stack is empty
        :return:
        """
        return self.__size == 0

    def size(self) -> int:
        """
        Returns the size of the stack
        :return:
        """
        return self.__size

    def clear(self) -> None:
        """
        Clears the stack
        """
        self.elements.clear()
        self.__size = 0

    def __str__(self):
        return str(self.elements)

    def to_list(self) -> list[T]:
        return self.elements
