import asyncio

from obi.commands import DACCodeRange
from obi.transfer import TCPConnection
from obi.macros import FrameBuffer

async def main():
    ## TCP server must be running at this port
    conn = TCPConnection('localhost', 2224)
    fb = FrameBuffer(conn)
    arange = DACCodeRange.from_resolution(2048)
    frame = await fb.capture_frame(x_range=arange, y_range=arange, dwell_time=10)


if __name__ == "__main__":
    asyncio.run(main())


