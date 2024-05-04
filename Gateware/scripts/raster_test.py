from glasgowcontrib.applet.open_beam_interface import OBIInterface
from glasgowcontrib.applet.open_beam_interface.base_commands import *


print("hello")
conn = OBIInterface(iface)
await conn._synchronize()

pixels = [2]*100
f_range = DACCodeRange(start = 0, count = 10, step = 0x100)
seq = CommandSequence(output=OutputMode.SixteenBit, raster=True)
seq.add(RasterRegionCommand(x_range= f_range, y_range = f_range))
seq.add(RasterPixelsCommand(dwells = pixels))
seq.add(FlushCommand())

await conn.transfer(seq)
