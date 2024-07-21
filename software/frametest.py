import asyncio 

from transfer import TCPConnection, TCPStream
from commands import DACCodeRange
from macros import RasterScanCommand

async def main():
    conn = TCPConnection("localhost", 2224)
    dac_range = DACCodeRange.from_resolution(2048)
    cmd = RasterScanCommand(x_range = dac_range, y_range = dac_range,
    dwell_time = 2, cookie = 123)
    async for chunk in conn.transfer_multiple(cmd, latency=65536):
        print(f"{chunk=}")

asyncio.run(main())
