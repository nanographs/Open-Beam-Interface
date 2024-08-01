import unittest
from obi.commands.structs import DACCodeRange


class DACCodeRangeTest(unittest.TestCase):
    def test_from_resolution(self):
        def test_out_of_range():
            self.assertRaises(ValueError, lambda: DACCodeRange.from_resolution(16385))
            self.assertRaises(ValueError, lambda: DACCodeRange(0, 16385, 256))
        test_out_of_range()
