import numpy as np
import asyncio
import argparse
import pathlib
import matplotlib.pyplot as plt
import logging
from ..stream_interface import TCPConnection
from base_commands import *
#from ..frame_buffer import FrameBuffer

parser = argparse.ArgumentParser()
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)
parser.add_argument('--csv_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to csv file with two columns, x and y')
args = parser.parse_args()

def import_csv(dwell):
    file = open(args.csv_path)

    x_coords = []
    y_coords = []

    for line in file:
        x, y = line.strip().split(',')
        x = int(float(x)*254)
        y =int(float(y)*254)
        x_coords.append(x)
        y_coords.append(y)
        yield x, y, dwell
    # return x_coords, y_coords

pattern = import_csv(args.dwell)


async def stream_pattern():
    conn = Connection('localhost', 2224)
    fb = FrameBuffer(conn)
    photo_range = DACCodeRange(0, 4096, int((16384/4096)*256))
    await conn.transfer(ExternalCtrlCommand(enable=True))
    async for chunk in conn.transfer_multiple(VectorPixelIter(pattern_generator=pattern), 
                                        output_mode=0):
        pass
    # full_frame = None
    # async for frame in fb.capture_frame(x_range = photo_range, y_range = photo_range, dwell=4, latency=65536):
    #     full_frame = frame
    await conn.transfer(ExternalCtrlCommand(enable=False))
    # full_frame.saveImage_tifffile(save_dir="")

asyncio.run(stream_pattern())


    

