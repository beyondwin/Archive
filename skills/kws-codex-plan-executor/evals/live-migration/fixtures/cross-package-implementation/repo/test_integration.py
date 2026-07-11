import unittest
from app.service import invoice_total


class InvoiceTest(unittest.TestCase):
    def test_shared_interface_includes_nonnegative_fee(self):
        self.assertEqual(invoice_total([2, 3], 4), 9)
        with self.assertRaises(ValueError):
            invoice_total([2], -1)


if __name__ == "__main__":
    unittest.main()
