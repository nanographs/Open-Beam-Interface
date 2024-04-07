import unittest
import array
from time import perf_counter
import numpy as np

from obi_software.frame_buffer import Frame, FrameBuffer
from obi_software.beam_interface import DACCodeRange

class OBISoftwareTestCase(unittest.TestCase):
    def test_frame_fill(self):
        x_range = DACCodeRange(0, 1000, 0x_02) #start, count, step
        y_range = DACCodeRange(0, 1200, 0x_02)
        frame = Frame(x_range, y_range)
        pixels = array.array('H',[0]*frame.pixels)
        frame.fill(pixels)
    
    def test_frame_fill_lines(self):
        x_range = DACCodeRange(0, 16384, 0x_02) #start, count, step
        y_range = DACCodeRange(0, 16384, 0x_02)
        frame = Frame(x_range, y_range)
        fb = FrameBuffer(None)
        pixels_per_chunk = fb.opt_chunk_size(frame)
        pixels = array.array('H',[0]*pixels_per_chunk)
        start = perf_counter()
        frame.fill_lines(pixels)
        end = perf_counter()
        print(f"time to fill {pixels_per_chunk*2} bytes: {end-start}")
    
        cast_pixels = memoryview(bytes([0]*pixels_per_chunk*2))
        empty_array = np.zeros(shape=(16384,16384))
        
        start_2 = perf_counter()
        lines = int(pixels_per_chunk*2/frame._x_count)
        empty_array[:lines] = cast_pixels.cast('B', shape=(lines, frame._x_count))
        end_2 = perf_counter()
        print(f"time to cast {pixels_per_chunk*2} bytes: {end_2-start_2}")