import unittest
import array

from obi_software.frame_buffer import Frame
from obi_software.beam_interface import DACCodeRange

class OBISoftwareTestCase(unittest.TestCase):
    def test_frame(self):
        x_range = DACCodeRange(0, 1000, 0x_02) #start, count, step
        y_range = DACCodeRange(0, 1200, 0x_02)
        frame = Frame(x_range, y_range)
        pixels = array.array('H',[0]*frame.pixels)
        frame.fill(pixels)