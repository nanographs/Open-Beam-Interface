import unittest
import asyncio
import time

import logging
logger = logging.getLogger()

from obi.macros.vector import VectorScanCommand

from obi.transfer.mock import MockConnection
from obi.transfer import dump_hex
from obi.commands import *

class VectorScanTest(unittest.TestCase):
    async def scan(self):
        test_cmd = VectorScanCommand(cookie=123)
        start_process = time.perf_counter()
        test_cmd._pre_process_chunks(latency=65536)
        end_process = time.perf_counter()
        conn = MockConnection()
        await conn._connect()
        start_send = time.perf_counter()
        async for chunk in conn.transfer_multiple(test_cmd, latency=65536):
            print(f"{dump_hex(chunk)}")
        end_send = time.perf_counter()
        print(f"process time: {end_process-start_process:04f}, send time: {end_send-start_send:04f} ")
    def test_scan(self):
        asyncio.run(self.scan())
        self.assertTrue(True)
