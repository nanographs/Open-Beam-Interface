from Gateware.applet.open_beam_interface.base_commands import *
import array

seq = CommandSequence(output=OutputMode.NoOutput, raster=True)
side = 8192
dwell = 2

# dwells = [dwell]*side*side
# print(f"{len(dwells)=}")
full_range = DACCodeRange(start = 0, count = side, step = int((16384/side)*256))
seq.add(RasterRegionCommand(x_range = full_range, y_range = full_range))
# seq.add(RasterPixelsCommand(dwells = dwells))
seq.add(RasterPixelRunCommand(length=side*side, dwell_time = dwell))

async def test():
    print(f"writing {len(seq)} bytes")
    await iface.write(bytes(seq))
    await iface.flush()
    print("wrote")

while True:
    await test()