import math
import numpy as np
import asyncio
import argparse
import matplotlib.pyplot as plt
import logging
from ..beam_interface import Connection, VectorPixelLinearRunCommand, _ExternalCtrlCommand, BeamType, setup_logging

setup_logging({"Stream": logging.DEBUG})

parser = argparse.ArgumentParser()
parser.add_argument('--show', action='store_true', help="show the pattern")
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)
args = parser.parse_args()

def circle(r):
    for degree in range(360):
        x = r*math.cos(math.radians(degree))
        y = r*math.sin(math.radians(degree))
    yield x, y

def rose(a, b, n_points):
    theta = np.linspace(0, 2*np.pi, n_points)
    r = a*np.sin(b*theta)
    return r, theta
    
def spiral(n_points, n_loops):
    theta = np.linspace(0, 2*n_loops*np.pi, n_points)
    r = theta
    return r, theta

def polar_to_cartesian(f):
    r, theta = f
    x = r*np.cos(theta)
    y = r*np.sin(theta)
    return x, y

def scale_to_dac_range(f):
    x, y = f
    max_x, min_x, max_y, min_y = np.max(x), np.min(x), np.max(y), np.min(y)
    max_range = max(max_x - min_x, max_y - min_y)
    scale_factor = 16384/max_range
    x = (x - min_x)*scale_factor #shift and scale
    y = (y - min_y)*scale_factor
    x = x.astype("int")
    y = y.astype("int")
    return x, y


x, y  = scale_to_dac_range(polar_to_cartesian(rose(2, 5, 1000)))
def show(x, y):
    plt.plot(x, y)
    plt.show()

def iterpattern(x, y, dwell, repeats=1):
    for _ in range(repeats):
        for x_coord, y_coord, in zip(x, y):
            yield x_coord, y_coord, dwell

async def stream_pattern(x, y, dwell):
    conn = Connection('localhost', 2224)
    await conn.transfer(_ExternalCtrlCommand(enable=True, beam_type=BeamType.Ion))
    pattern = iterpattern(x, y, dwell, repeats=15)
    async for chunk in conn.transfer_multiple(VectorPixelLinearRunCommand(pattern_generator=pattern), 
                                        output_mode=0):
        pass
    #await conn.transfer(_ExternalCtrlCommand(enable=False, beam_type=BeamType.Ion))

if args.show:
    show(x, y)
else:
    while True:
        asyncio.run(stream_pattern(x, y, args.dwell))
    

