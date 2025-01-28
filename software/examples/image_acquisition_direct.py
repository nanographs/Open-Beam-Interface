import asyncio

from obi.transfer import GlasgowConnection, TCPConnection
from obi.macros import FrameBuffer
from obi.commands import DACCodeRange, OutputMode, ExternalCtrlCommand

async def main():
    # Open Connection
    conn = GlasgowConnection()
    # Create Frame Buffer
    fb = FrameBuffer(conn)
    # Create DAC range
    arange = DACCodeRange.from_resolution(256)
    # Capture frame with parameters
    frame = await fb.capture_frame(x_range=arange, y_range=arange, dwell_time=254, output_mode=OutputMode.EightBit)
    # Save image to specified path
    frame.saveImage_tifffile("test_tiff")

if __name__ == "__main__":
    asyncio.run(main())


