import asyncio
import argparse
from hilbertcurve.hilbertcurve import HilbertCurve


def hilbert(pmax = 10, dwell = 2):
    N = 2 # number of dimensions

    #text_file = open("hilbert.txt", "w")
    points = []

    side = 2**pmax
    print(f"{side=}")
    min_coord = 0
    max_coord = side - 1
    cmin = min_coord - 0.5
    cmax = max_coord + 0.5

    offset = 0
    dx = 0.5

    for p in range(pmax, 0, -1):
        hc = HilbertCurve(p, N)
        sidep = 2**p

        npts = 2**(N*p)
        pts = []
        for i in range(npts):
            pt = hc.point_from_distance(i)
            x = pt[0]*side/sidep + offset
            y = pt[1]*side/sidep + offset
            yield int(x), int(y), dwell

        offset += dx
        dx *= 2


from .beam_interface import Connection, _VectorPixelCommand, setup_logging, VectorPixelRunCommand
import logging
from time import perf_counter
setup_logging({"Command": logging.DEBUG, "Stream": logging.DEBUG})

parser = argparse.ArgumentParser()
parser.add_argument('--test', action='store_true', help="just print the first 100 points")
parser.add_argument('--pmax', type=int, help="hilbert curve will have 2^N points?", default=10)
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)
parser.add_argument('--a_b', type=str, help="a = VectorPixelRun, b = _VectorPixel", default="a")
parser.add_argument('--output', type=int, help="output mode: 0 = 16 bit, 1 = 8 bit, 2 = None", default=0)
parser.add_argument('--latency', type=int, help="min abort latency. only applies to mode a", default=65536)
parser.add_argument('--dead_band', type=int, help="dead band around latency. only applies to mode a", default=16384)
parser.add_argument("port", help="port @ localhost to connect to")
args = parser.parse_args()

hil = hilbert(args.pmax, args.dwell)

def test_print():
    for x, y, d in hil:
        print(f"{x=}, {y=}, {d=}")

conn = Connection('localhost', args.port)

async def stream_pattern_a():
    start = perf_counter()
    async for chunk in conn.transfer_multiple(VectorPixelRunCommand(pattern_generator=hil), 
                                            latency=args.latency, dead_band = args.dead_band, output_mode=args.output):
        pass


async def stream_pattern_b():
    while True:
        try:
            x, y, dwell = next(hil)
            await conn.transfer(_VectorPixelCommand(x_coord=x, y_coord=y, dwell=dwell), 
                                        latency=args.latency, output_mode=args.output)
        except StopIteration:
            print("Done.")
            break

start = perf_counter()
if args.test:
    test_print()
else:
    if args.a_b == "a":
        asyncio.run(stream_pattern_a())
    if args.a_b == "b":
        asyncio.run(stream_pattern_b())
stop = perf_counter()
print(f"finished in: {stop-start}")