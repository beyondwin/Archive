import unittest
from src.example import clamp


class ClampTest(unittest.TestCase):
    def test_clamps_both_edges_and_preserves_in_range_value(self):
        self.assertEqual(clamp(-2, 0, 10), 0)
        self.assertEqual(clamp(12, 0, 10), 10)
        self.assertEqual(clamp(4, 0, 10), 4)


if __name__ == "__main__":
    unittest.main()
