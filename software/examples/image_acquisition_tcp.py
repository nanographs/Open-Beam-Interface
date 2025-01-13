import asyncio

from obi.commands import DACCodeRange
from obi.transfer import TCPConnection
from obi.macros import FrameBuffer

async def main():
    # Open Connection
    # TCP server must be running at this port
    conn = TCPConnection('localhost', 2224)
    # Create Frame Buffer
    fb = FrameBuffer(conn)
    # Create DAC range
    arange = DACCodeRange.from_resolution(2048)
    # Capture frame with parameters
    frame = await fb.capture_frame(x_range=arange, y_range=arange, dwell_time=10)


if __name__ == "__main__":
    asyncio.run(main())


