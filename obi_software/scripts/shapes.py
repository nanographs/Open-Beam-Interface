import math
import numpy as np
import asyncio
import argparse
import matplotlib.pyplot as plt
import logging
import sys
from ..stream_interface import Connection, VectorPixelLinearRunCommand, _ExternalCtrlCommand, _BeamSelectCommand, BeamType, setup_logging
from ..base_commands import CommandSequence, VectorPixelCommand, SynchronizeCommand, ExternalCtrlCommand, BlankCommand, OutputMode, BeamType, SelectBeamCommand

setup_logging({"Stream": logging.DEBUG})

parser = argparse.ArgumentParser()
parser.add_argument('--show', action='store_true', help="show the pattern with matplotlib")
parser.add_argument('--buffer', action='store_true', help="write to stdout")
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)


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

parser.add_argument('--n_points', type=int, help="number of points", default=1000)
parser.add_argument('--repeats', type=int, help="number times to repeat the pattern", default=1)
subparsers = parser.add_subparsers(title='shapes',
                                description='valid shapes',
                                help='options are rose and spiral')
parser_rose = subparsers.add_parser('rose')
parser_rose.add_argument('--a', type=int, help="see rose()", default=2)
parser_rose.add_argument('--b', type=int, help="see rose()", default=5)
parser_rose.set_defaults(rose=True, spiral=False)
parser_spiral = subparsers.add_parser('spiral')
parser_spiral.add_argument('--n_points', type=int, help="see spiral()", default=1000)
parser_spiral.add_argument('--n_loops', type=int, help="see spiral()", default=10)
parser_spiral.set_defaults(spiral=True, rose=False)
args = parser.parse_args()
print(f"{args=}")
if args.rose:
    pattern_func = rose(args.a, args.b, args.n_points)
if args.spiral:
    pattern_func = spiral(args.n_points, args.n_loops)

# x, y  = scale_to_dac_range(polar_to_cartesian(rose(args.a, args.b, 1000)))
x, y  = scale_to_dac_range(polar_to_cartesian(pattern_func))
def show(x, y):
    plt.plot(x, y)
    plt.show()

def iterpattern(x, y, dwell, repeats=1):
    for _ in range(repeats):
        for x_coord, y_coord, in zip(x, y):
            yield x_coord, y_coord, dwell

async def stream_pattern(x, y, dwell):
    conn = Connection('localhost', 2224)
    await conn.transfer(_ExternalCtrlCommand(enable=True))
    await conn.transfer(_BeamSelectCommand(beam_type=BeamType.Ion))
    pattern = iterpattern(x, y, dwell, repeats=args.repeats)
    async for chunk in conn.transfer_multiple(VectorPixelLinearRunCommand(pattern_generator=pattern), 
                                        output_mode=0):
        pass
    #await conn.transfer(_ExternalCtrlCommand(enable=False, beam_type=BeamType.Ion))

def buffer_pattern(x, y, dwell):
    pattern = iterpattern(x, y, dwell, repeats=args.repeats)
    seq = CommandSequence(output=OutputMode.NoOutput, raster = False)
    seq.add(BlankCommand(enable=True))
    seq.add(SelectBeamCommand(beam_type = BeamType.Ion))
    seq.add(ExternalCtrlCommand(enable=True))
    seq.add(BlankCommand(enable=False, inline=True))
    for x, y, dwell in pattern:
        seq.add(VectorPixelCommand(x_coord = x, y_coord = y, dwell = dwell))
    seq.add(BlankCommand(enable=True))
    seq.add(ExternalCtrlCommand(enable=False))
    sys.stdout.buffer.write(seq.message)


def main():
    if args.show:
        show(x, y)
    if args.buffer:
        buffer_pattern(x, y, args.dwell)
    else:
        while True:
            asyncio.run(stream_pattern(x, y, args.dwell))
    

