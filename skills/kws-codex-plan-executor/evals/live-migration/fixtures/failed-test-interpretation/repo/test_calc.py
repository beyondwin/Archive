import unittest
from calc import ratio


class RatioTest(unittest.TestCase):
    def test_empty_batch_has_defined_semantics(self):
        self.assertEqual(ratio(0, 0), 0.0)


if __name__ == "__main__":
    unittest.main()
