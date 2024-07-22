import asyncio 

from transfer import TCPConnection, TCPStream
from commands import DACCodeRange
from macros import FrameBuffer

import os
cwd = os.getcwd()

from time import perf_counter

async def main():
    conn = TCPConnection("localhost", 2224)
    fb = FrameBuffer(conn)
    dac_range = DACCodeRange.from_resolution(2048)
    total_start = perf_counter()
    total_frames = 0
    start = perf_counter()
    async for frame in fb.capture_frame(x_range = dac_range, y_range = dac_range, dwell_time = 2, latency = 65536):
        stop = perf_counter()
        print(f"{frame=}, {stop-start:04f} s -> {1/(stop-start):04f} fps")
        start = stop
        total_frames += 1
    total_stop = perf_counter()
    total_time = total_stop - total_start
    print(f"{total_frames=}, {total_time=:04f}, {total_frames/total_time:04f} fps")
    fb.current_frame.saveImage_tifffile(cwd)



asyncio.run(main())
