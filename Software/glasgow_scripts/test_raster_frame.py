from glasgowcontrib.applet.open_beam_interface.base_commands import *
import array

seq = CommandSequence(output=OutputMode.NoOutput, raster=True)
side = 8192
dwell = 2

# dwells = [dwell]*side*side
# print(f"{len(dwells)=}")
full_range = DACCodeRange(start = 0, count = side, step = int((16384/side)*256))
seq.add(RasterRegionCommand(x_range = full_range, y_range = full_range))
# seq.add(RasterPixelsCommand(dwells = dwells))
seq.add(RasterPixelRunCommand(length=side*side, dwell = dwell))

async def test():
    print(f"writing {len(seq.message)} bytes")
    await iface.write(seq.message)
    await iface.flush()
    print("wrote")

while True:
    await test()