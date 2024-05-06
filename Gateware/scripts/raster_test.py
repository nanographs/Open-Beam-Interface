from glasgowcontrib.applet.open_beam_interface.base_commands import *


print("hello")
conn = OBIInterface(iface)
sw = StreamWheel(conn)
f = StreamingFrameContext(x_pixels=512, y_pixels=512, bit_mode = OutputMode.SixteenBit)
f2 = StreamingFrameContext(x_pixels=1024, y_pixels=1024, bit_mode = OutputMode.SixteenBit)

# seq = CommandSequence(output=OutputMode.SixteenBit, raster=True)
# seq.add(RasterRegionCommand(x_range= x_range, y_range = y_range))
# seq.add(RasterPixelsCommand(dwells = pixels))
# seq.add(FlushCommand())


loop = asyncio.get_event_loop()
fut = asyncio.Future()
sw.request_new_context(f)
loop.create_task(sw.turn())
await asyncio.sleep(1)
print("hii")
sw.request_new_context(f2)
print("done")
await asyncio.sleep(1)
#await fut
