import asyncio
from hilbertcurve.hilbertcurve import HilbertCurve


def hilbert(pmax = 10):
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
            yield x, y

        offset += dx
        dx *= 2


from .beam_interface import Connection, _VectorPixelCommand

parser = argparse.ArgumentParser()
parser.add_argument('--test', action='store_true')
parser.add_argument('--pmax', type=int, help="hilbert curve will have 2^N points to a side", default=10)
parser.add_argument('--dwell', type=int, help="dwell time per pixel", default=2)
parser.add_argument("port")
args = parser.parse_args()

hil = hilbert(args.pmax)

def test_print():
    for n in range(100):
        try:
            x, y = next(hil)
            print(f"{x=}, {y=}")
        except StopIteration:
            break

async def stream_pattern():
    conn = Connection('localhost', args.port)
    while True:
        try:
            x, y = next(hil)
            await conn.transfer(_VectorPixelCommand(x_coord=x, y_coord=y, dwell=args.dwell))
        except StopIteration:
            print("Done.")
            break

if args.test:
    test_print()
else:
    asyncio.run(stream_pattern)