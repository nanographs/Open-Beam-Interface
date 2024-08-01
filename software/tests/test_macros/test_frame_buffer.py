import unittest
import array
import asyncio

from obi.macros import Frame, FrameBuffer
from obi.commands import DACCodeRange
from obi.transfer import MockConnection

class FrameTest(unittest.TestCase):
    def test_fill(self):
        test_range = DACCodeRange.from_resolution(2048)
        f = Frame(x_range=test_range, y_range=test_range)
        test_pixels = array.array('H', [x for x in range(2048)]*2049)
        self.assertRaises(ValueError, lambda: f.fill(test_pixels))

class FrameBufferTest(unittest.TestCase):
    def test_something(self):
        async def test_fn():
            conn = MockConnection()
            await conn._connect()
            fb = FrameBuffer(conn)
            async for frame in fb.capture_frame_iter_fill(x_res=2048, y_res=2048, dwell_time=2):
                print(f"{frame=}")
        asyncio.run(test_fn())

