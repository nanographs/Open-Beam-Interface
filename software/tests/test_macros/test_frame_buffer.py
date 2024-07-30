import unittest
import array

from macros import Frame
from commands import DACCodeRange

class FrameTest(unittest.TestCase):
    def test_fill(self):
        test_range = DACCodeRange.from_resolution(2048)
        f = Frame(x_range=test_range, y_range=test_range)
        test_pixels = array.array('H', [x for x in range(2048)]*2049)
        self.assertRaises(ValueError, lambda: f.fill(test_pixels))
        