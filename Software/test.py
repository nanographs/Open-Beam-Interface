import unittest
import array

from obi_software.frame_buffer import Frame
from obi_software.stream_interface import DACCodeRange
from obi_software.gui_modules.bmp_import import setup, teardown
from obi_software.base_commands import *

class OBISoftwareTestCase(unittest.TestCase):
    def test_frame(self):
        x_range = DACCodeRange(0, 1000, 0x_02) #start, count, step
        y_range = DACCodeRange(0, 1200, 0x_02)
        frame = Frame(x_range, y_range)
        pixels = array.array('H',[0]*frame.pixels)
        frame.fill(pixels)
    def test_bmp(self):
        commands = setup(beam_type=BeamType.Electron).message
        assert commands[0:4] == SynchronizeCommand(output=OutputMode.NoOutput, raster=False, cookie=123).message
        assert commands[4:5] == BlankCommand(enable=True).message
        assert commands[5:6] == BeamSelectCommand(beam_type=BeamType.Electron).message
        assert commands[6:7] == ExternalCtrlCommand(enable=True).message
        assert commands[7:10] == DelayCommand(5760).message
