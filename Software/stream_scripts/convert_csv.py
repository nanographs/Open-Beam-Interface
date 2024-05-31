import sys
import argparse
import numpy as np
import pathlib
from ..base_commands import *

parser = argparse.ArgumentParser()
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)
parser.add_argument('--csv_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to csv file with two columns, x and y')
args = parser.parse_args()

seq = CommandSequence(output=OutputMode.NoOutput, raster=False)

file = open(args.csv_path)
prev_x = 0
prev_y = 0
for line in file:
    x, y = line.strip().split(',')
    x = int(float(x)*254)
    y = int(float(y)*254)
    if (abs(prev_x-x) > 2000) or (abs(prev_y-y) > 2000):
        #print(f"added blank between {x},{y} and prev {prev_x}, {prev_y}")
        seq.add(BlankCommand(enable=True))
        seq.add(BlankCommand(enable=False, inline=True))
    seq.add(VectorPixelCommand(x_coord = x, y_coord = y, dwell = args.dwell))
    prev_x = x
    prev_y = y


sys.stdout.buffer.write(seq.message)

    

