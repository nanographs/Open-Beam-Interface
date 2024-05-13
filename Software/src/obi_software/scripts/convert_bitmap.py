import sys
import argparse
import numpy as np
import pathlib
from PIL import Image, ImageChops
import matplotlib.pyplot as plt
from ..base_commands import *

parser = argparse.ArgumentParser()
parser.add_argument('--img_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to image file')
parser.add_argument('--show', action='store_true', help="show the pattern with matplotlib")
args = parser.parse_args()

im = Image.open(args.img_path)
im = im.convert("L")
im = ImageChops.invert(im)
array = np.array(im)

if args.show:
    plt.imshow(array)
    plt.show()
else:
    # array = array*256 #scale up dwell times
    y_pixels, x_pixels = array.shape
    step = int((16384/max(x_pixels, y_pixels))*256)
    x_range = DACCodeRange(start = 0, count = x_pixels, step = step)
    y_range = DACCodeRange(start = 0, count = y_pixels, step = step)
    pixels = list(np.ravel(array))

    print(f"loaded file from {args.img_path}")
    print(array)

    seq = CommandSequence(raster=True, output=OutputMode.NoOutput)

    def add_line(pixels, x_start, x_stop, y):
        y_range = DACCodeRange(start=y, count=0, step=step)
        x_range = DACCodeRange(start=x_start, count=(x_stop-x_start), step=step)
        seq.add(RasterRegionCommand(x_range=x_range,y_range=y_range))
        seq.add(RasterPixelsCommand(dwells=pixels))

    #replot = np.zeros(shape=(y_pixels, x_pixels))
    def optimize(array, seq):
        for y in range(y_pixels):
            pixel_dwells = []
            drawing = False
            x_start = 0
            for x in range(x_pixels):
                pixel_dwell = array[y][x]
                if pixel_dwell > 1:
                    pixel_dwells.append(pixel_dwell)
                    #replot[y][x] = pixel_dwell
                    if not drawing:
                        x_start = x
                    drawing = True
                else:
                    if len(pixel_dwells) > 0:
                        add_line(pixel_dwells, x_start, x, y)
                        pixel_dwells = []
                    drawing = False

    optimize(array, seq)  
    # plt.imshow(replot)
    # plt.show()

    seq = CommandSequence()
    seq.add(SynchronizeCommand(cookie=123, raster_mode=True, output_mode=OutputMode.NoOutput))
    seq.add(RasterRegionCommand(x_range= x_range, y_range = y_range))
    seq.add(RasterPixelsCommand(dwells = pixels))

    print("writing to stdout")
    sys.stdout.buffer.write(seq)


