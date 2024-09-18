import asyncio

from obi.transfer import GlasgowConnection
from obi.macros import FrameBuffer
from obi.commands import DACCodeRange

async def main():
    conn = GlasgowConnection()
    fb = FrameBuffer(conn)
    arange = DACCodeRange.from_resolution(2048)
    frame = await fb.capture_frame(x_range=arange, y_range=arange, dwell_time=10)

if __name__ == "__main__":
    asyncio.run(main())


