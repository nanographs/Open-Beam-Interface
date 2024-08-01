import asyncio 

from obi.transfer import TCPConnection, TCPStream, setup_logging, dump_hex
from obi.commands import DACCodeRange
from obi.macros import FrameBuffer, RasterScanCommand

import logging
setup_logging({"Command": logging.DEBUG, "Connection": logging.DEBUG, "Stream": logging.DEBUG})

import os
cwd = os.getcwd()

import time

from rich import print


async def atask():
    for n in range(5):
        print(f"task: {n}")
        await asyncio.sleep(1)


async def mock_transfer():
    asyncio.create_task(atask())
    for n in range(5):
        yield n
        await asyncio.sleep(1)


async def main():
    conn = TCPConnection("localhost", 2224)
    dac_range = DACCodeRange.from_resolution(256)

    def get_cmd():
        return RasterScanCommand(x_range=dac_range, y_range=dac_range, dwell_time=1000, cookie=123)
    
    start = time.time()
    cmd = get_cmd()

    async for chunk in conn.transfer_multiple(cmd, latency=65536):
        print(f"got chunk1: {dump_hex(chunk)}")
    # async for n in mock_transfer():
        now = time.time()
        elapsed = now-start
        #print(f"{n=}, {elapsed=:04f}")
        if elapsed > 1:
            cmd.abort.set()
    print("done1")

    #print(asyncio.all_tasks(loop=None))

    time.sleep(3)
    cmd = get_cmd()
    async for chunk in conn.transfer_multiple(cmd, latency=65536):
        print(f"got chunk2: {dump_hex(chunk)}")
    print("done2")


asyncio.run(main())
