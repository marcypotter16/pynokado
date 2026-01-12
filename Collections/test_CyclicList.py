import unittest
from CyclicList import CyclicList

class CyclicListTest(unittest.TestCase):
    def setUp(self):
        self.cyclic_list = CyclicList()

    def test_add(self):
        self.cyclic_list.add(1)
        self.assertEqual(self.cyclic_list.items, [1])

    def test_set_current(self):
        self.cyclic_list.add(1)
        self.cyclic_list.add(2)
        self.cyclic_list.set_current(1)
        self.assertEqual(self.cyclic_list.get_current(), 2)

    def test_remove(self):
        self.cyclic_list.add(1)
        self.cyclic_list.add(2)
        self.cyclic_list.remove(1)
        self.assertEqual(self.cyclic_list.items, [2])

    def test_next(self):
        self.cyclic_list.add(1)
        self.cyclic_list.add(2)
        self.cyclic_list.add(3)
        self.cyclic_list.set_current(2)
        self.cyclic_list.next()
        self.assertEqual(self.cyclic_list.get_current(), 1)

if __name__ == '__main__':
    unittest.main()