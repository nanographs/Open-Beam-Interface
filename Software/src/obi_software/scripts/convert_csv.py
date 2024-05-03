import sys
import argparse
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)
parser.add_argument('--csv_path', required=True, 
                    type=lambda p: pathlib.Path(p).expanduser(), #expand paths starting with ~ to absolute
                    help='path to csv file with two columns, x and y')
args = parser.parse_args()

seq = CommandSequence()
seq.add(SynchronizeCommand(cookie=123, raster_mode=False, output_mode=OutputMode.NoOutput))

file = open(args.csv_path)
for line in file:
    x, y = line.strip().split(',')
    x = int(float(x)*254)
    y = int(float(y)*254)
    seq.add(VectorPixelCommand(x_coord = x, y_coord = y, dwell = args.dwell))


sys.stdout.buffer.write(seq)

    

