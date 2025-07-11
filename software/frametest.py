import asyncio 

from obi.transfer import TCPConnection, TCPStream, setup_logging, dump_hex, GlasgowConnection
from obi.commands import *
from obi.macros import FrameBuffer, RasterScanCommand

from obi.support import stream_logs

import logging
# setup_logging({"Command": logging.DEBUG, "Connection": logging.DEBUG, "Stream": logging.DEBUG})


from rich import print

from obi.launch import _setup

@stream_logs
async def main():
    dac_range = DACCodeRange.from_resolution(512)

    conn = GlasgowConnection()

    await conn.transfer(SynchronizeCommand(cookie=123, raster=True, output = OutputMode.SixteenBit))
    
    cmd = RasterScanCommand(x_range=dac_range, y_range=dac_range, dwell_time=1, cookie=123)

    async for chunk in conn.transfer_multiple(cmd, latency=65536):
        print(f"got chunk: {dump_hex(chunk)}")




asyncio.run(main())
# asyncio.run(main())
