import sys
import argparse
import numpy as np
from PIL import Image, ImageChops
from ..base_commands import *

parser = argparse.ArgumentParser()
parser.add_argument('--img_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to image file')
args = parser.parse_args()

im = Image.open(args.img_path)
im = im.convert("L")
im = ImageChops.invert(im)
array = np.array(im)
array = array*256 #scale up dwell times
y_pixels, x_pixels = array.shape
step = int((16384/max(x_pixels, y_pixels))*256)
x_range = DACCodeRange(start = 0, count = x_pixels, step = step)
y_range = DACCodeRange(start = 0, count = y_pixels, step = step)
pixels = list(np.ravel(array))

print(f"loaded file from {args.img_path}")
print(array)

seq = CommandSequence()
seq.add(SynchronizeCommand(cookie=123, raster_mode=True, output_mode=OutputMode.NoOutput))
seq.add(RasterRegionCommand(x_range= x_range, y_range = y_range))
seq.add(RasterPixelsCommand(dwells = pixels))

print("writing to stdout")
sys.stdout.buffer.write(seq)


