import unittest
from obi.commands.structs import DACCodeRange


class DACCodeRangeTest(unittest.TestCase):
    def test_from_resolution(self):
        def test_out_of_range():
            self.assertRaises(ValueError, lambda: DACCodeRange.from_resolution(16385))
            self.assertRaises(ValueError, lambda: DACCodeRange(0, 16385, 256))
        test_out_of_range()

        def test_step_too_big():
            self.assertRaises(ValueError, lambda: DACCodeRange.from_resolution(63))
            self.assertRaises(ValueError, lambda: DACCodeRange(0, 16384, 65536))
        test_step_too_big()
    def test_from_roi(self):
        self.assertEqual(DACCodeRange.from_roi(1024, 512, 512),
            DACCodeRange(start=8192, count=512, step=4096))