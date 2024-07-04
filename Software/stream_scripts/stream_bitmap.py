from PIL import Image, ImageChops
import numpy as np
import asyncio
from ..stream_interface import TCPConnection
from base_commands import *
from ..frame_buffer import FrameBuffer

im = Image.open("prox test size.png")
im = im.convert("L")
im = ImageChops.invert(im)
array = np.array(im)
array = array*256 #scale up dwell times
y_pixels, x_pixels = array.shape
step = int((16384/max(x_pixels, y_pixels))*256)
x_range = DACCodeRange(start = 0, count = x_pixels, step = step)
y_range = DACCodeRange(start = 0, count = y_pixels, step = step)
pixels = list(np.ravel(array))


async def stream_pattern():
    conn = TCPConnection('localhost', 2224)
    #fb = FrameBuffer(conn)
    #photo_range = DACCodeRange(0, 4096, int((16384/4096)*256))
    await conn.transfer(ExternalCtrlCommand(enable=True, beam_type=BeamType.Ion))
    async for res in conn.transfer_multiple(RasterPatternCommand(cookie=123, x_range = x_range, y_range = y_range, dwells=pixels), latency=1000000000, output_mode=OutputMode.NoOutput):
        pass
    # full_frame = None
    # async for frame in fb.capture_frame(x_range = photo_range, y_range = photo_range, dwell=4, latency=65536):
    #     full_frame = frame
    await conn.transfer(ExternalCtrlCommand(enable=False, beam_type=BeamType.Ion))

asyncio.run(stream_pattern())

#print(pixels)
