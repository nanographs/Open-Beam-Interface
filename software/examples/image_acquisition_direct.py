import asyncio

from obi.transfer import GlasgowConnection
from obi.macros import FrameBuffer
from obi.commands import DACCodeRange

async def main():
    # Open Connection
    conn = GlasgowConnection()
    # Create Frame Buffer
    fb = FrameBuffer(conn)
    # Create DAC range
    arange = DACCodeRange.from_resolution(2048)
    # Capture frame with parameters
    frame = await fb.capture_frame(x_range=arange, y_range=arange, dwell_time=10)

if __name__ == "__main__":
    asyncio.run(main())


