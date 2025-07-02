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
    # Save frame data to TIFF using builtin method
    frame.saveImage_tifffile("example_1.tif")
    # Access frame data from underlying NDArray
    my_array = frame.as_uint16()


if __name__ == "__main__":
    asyncio.run(main())


