import unittest
import array
import asyncio
import time

import logging
logger = logging.getLogger()

from obi.macros import Frame, FrameBuffer
from obi.commands import DACCodeRange
from obi.transfer import MockConnection, setup_logging

class FrameTest(unittest.TestCase):
    def test_fill_overflow(self):
        test_range = DACCodeRange.from_resolution(2048)
        f = Frame.from_DAC_ranges(x_range=test_range, y_range=test_range)
        test_pixels = array.array('H', [x for x in range(2048)]*2049)
        self.assertRaises(ValueError, lambda: f.fill(test_pixels))
    def test_fill_correct(self):
        test_range = DACCodeRange.from_resolution(2048)
        f = Frame.from_DAC_ranges(x_range=test_range, y_range=test_range)
        test_pixels = array.array('H', [x for x in range(2048)]*2048)
        f.fill(test_pixels)

class FrameBufferTest(unittest.TestCase):
    def test_something(self):
        async def test_fn():
            conn = MockConnection()
            await conn._connect()
            fb = FrameBuffer(conn)
            start = time.time()
            async for frame in fb.capture_full_frame(x_res=2048, y_res=2048, dwell_time=215):
                now = time.time()
                elapsed = now-start
                logger.debug(f"{frame=}, {elapsed=:04f}")
                if elapsed > .5:
                    fb.abort_scan()
        asyncio.run(test_fn())

