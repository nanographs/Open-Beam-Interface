import unittest
import array
import asyncio

import logging
logger = logging.getLogger()

from obi.macros import RasterScanCommand
from obi.commands import DACCodeRange

from obi.transfer.mock import MockConnection
from obi.transfer import dump_hex


class RasterScanTest(unittest.TestCase):
    async def scan(self):
        test_range = DACCodeRange.from_resolution(2048)
        test_dwell = 2
        test_cmd = RasterScanCommand(cookie=123,
            x_range=test_range, y_range=test_range, dwell_time=test_dwell)
        conn = MockConnection()
        await conn._connect()
        async for chunk in conn.transfer_multiple(test_cmd, latency=65536):
            logger.debug(f"{dump_hex(chunk)}")
    def test_scan(self):
        asyncio.run(self.scan())
        self.assertTrue(True)

        