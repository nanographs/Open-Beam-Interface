import numpy as np
from PIL import Image, ImageChops
import time
import itertools
import multiprocessing
from ..base_commands import *
from multiprocessing import Pool


im = Image.open('Square.jpg').convert("L")
array = np.asarray(im)
y_pix, x_pix = array.shape

seq = CommandSequence(raster=False, output=OutputMode.NoOutput)

# start = time.time()     
# for y in range(y_pix):
#     for x in range(x_pix):
#         dwell = array[y][x]
#         if dwell > 0:
#             seq.add(VectorPixelCommand(x_coord=x, y_coord = y, dwell=dwell))
# stop = time.time()
# print(f"for loop time: {stop-start:.4f}")

# seq = CommandSequence(raster=False, output=OutputMode.NoOutput)

# start = time.time()   
# ax, ay = np.nonzero(array)
# for x, y in zip(ax, ay):
#     seq.add(VectorPixelCommand(x_coord=x, y_coord = y, dwell=array[x][y]))
# stop = time.time()
# print(f"np.nonzero + zip time: {stop-start:.4f}")





def line(xarray):
    if xarray:
        y, xarray = xarray
        c = bytearray()
        for x in xarray:
            c.extend(VectorPixelCommand(x_coord=x, y_coord = 1, dwell=xarray[x]).message)
        return c

if __name__ == "__main__":
    seq = CommandSequence(raster=False, output=OutputMode.NoOutput)
    seqs = bytearray(seq.message)
    pool = Pool()
    start = time.time()
    for i in pool.imap(line, enumerate(array)):
        seqs.extend(i)
    pool.close()
    stop = time.time()
    print(f"pool time: {stop-start:.4f}")
